"""Storage sharing and generated-cache retention on isolated databases only."""
from io import BytesIO
from importlib.resources import files
import json
import os
from pathlib import Path
import sqlite3
import time

from PIL import Image

from wechat_bot import board_cache
from wechat_bot.stickers import StickerService
from wordle.game import WordleService
from test_bot import event, process, setup


def test_dictionary_snapshots_share_bytes_without_changing_active_games(tmp_path):
    words = {'apple', 'alley'}
    service = WordleService(tmp_path / 'words.sqlite3', answer_picker=lambda _: 'apple',
                            dictionary_provider=lambda _: (('apple',), words))
    first = service.start('first', 'alice')
    service.start('second', 'bob')
    with service.store.transaction() as c:
        assert c.execute('SELECT COUNT(*) FROM wordle_dictionaries').fetchone()[0] == 1
        assert c.execute('SELECT COUNT(*) FROM games WHERE allowed_words_json IS NULL').fetchone()[0] == 2
        before = service.store.load(c, 'first')['allowed_words_json']
    words.add('crane')
    service.start('third', 'carol')
    with service.store.transaction() as c:
        assert c.execute('SELECT COUNT(*) FROM wordle_dictionaries').fetchone()[0] == 2
        assert service.store.load(c, 'first')['allowed_words_json'] == before
        assert 'crane' in json.loads(service.store.load(c, 'third')['allowed_words_json'])
        # Pre-v0.2.7 inline snapshots remain byte-for-byte untouched by startup.
        c.execute('UPDATE games SET allowed_words_json=?,allowed_words_digest=NULL WHERE id=?',
                  (before, first['game_id']))
    reopened = WordleService(service.store.path)
    with reopened.store.transaction() as c:
        assert c.execute('SELECT allowed_words_json FROM games WHERE id=?',
                         (first['game_id'],)).fetchone()[0] == before
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
        # A very old active game with neither snapshot representation must not
        # silently gain the newly imported upstream vocabulary on migration.
        c.execute("""INSERT INTO games (group_id,creator_id,length,answer,status,created_at_utc)
                     VALUES ('legacy-null','alice',5,'apple','active','earlier')""")
        reopened.store.initialize_schema(c)
        legacy_allowed = set(json.loads(reopened.store.load(c, 'legacy-null')['allowed_words_json']))
        expanded = set(json.loads(files('wordle').joinpath('words.json').read_text(encoding='utf-8'))['allowed_guesses'])
        prior = set(json.loads(files('wordle').joinpath('word_space_upgrade.json').read_text(encoding='utf-8'))['prior_seed_words'])
        assert 'apple' in legacy_allowed and not (legacy_allowed & (expanded - prior))
        assert expanded - prior  # The fixture really contains new upstream words.
    assert reopened.guess('second', 'alice', 'alley')['status'] == 'active'
    assert reopened.guess('second', 'bob', 'apple')['status'] == 'won'


def test_sticker_original_and_conversion_are_reused_without_duplicate_files(tmp_path):
    service = StickerService(tmp_path)
    c = sqlite3.connect(tmp_path / 'bot.sqlite3')
    c.row_factory = sqlite3.Row
    with c:
        service.initialize(c)
    def image_bytes(color, kind):
        stream = BytesIO()
        Image.new('RGB', (8, 8), color).save(stream, format=kind)
        return stream.getvalue()
    gif = image_bytes('red', 'GIF')
    prepared = service.prepare(gif)
    assert prepared['path'] == prepared['source_path']
    assert len(list(service.directory.rglob('*.*'))) == 1
    actor = dict(account_id='robot', chat_id='one@chatroom', sender_id='owner')
    with c:
        item = service.add_local(c, **actor, prepared=prepared)
    original = image_bytes('green', 'PNG')
    converted = service.prepare(image_bytes('green', 'GIF'), source_format='PNG', source_data=original)
    with c:
        service.add_local(c, **actor, prepared=converted)
    existing = service.find_source(c, original, 'PNG')
    files = {p: p.read_bytes() for p in service.directory.rglob('*') if p.is_file()}
    # Another valid encoder output for the same original should not create an
    # unreferenced GIF. Reuse the existing verified send copy across group pools.
    reused = service.prepare(image_bytes('blue', 'GIF'), source_format='PNG',
                             source_data=original, existing=existing)
    with c:
        second = service.add_local(c, **dict(actor, chat_id='two@chatroom'), prepared=reused)
    assert second['path'] == existing['path']
    assert {p: p.read_bytes() for p in service.directory.rglob('*') if p.is_file()} == files
    assert Path(item['path']).read_bytes() == gif
    with c:
        c.execute('UPDATE stickers SET deleted=1')
    assert service.find_source(c, original, 'PNG') is None
    assert all(p.exists() for p in files)  # Soft deletion never purges originals.
    c.close()


def test_board_cache_shares_png_and_prunes_only_unprotected_new_cache(tmp_path):
    runtime = setup(tmp_path)
    runtime.router.game.answer_picker = lambda _: 'apple'
    process(runtime, event(1, '猜词'))
    process(runtime, event(2, '猜词棋盘'))
    while runtime.send_one():
        pass
    paths = [Path(item.path) for item in runtime.gateway.sent]
    assert len(paths) == 2 and paths[0] == paths[1]
    board = runtime.router.game.current('123@chatroom')
    expired = board_cache.render_cached(dict(board, game_id=999), tmp_path)
    legacy = tmp_path / 'media/wordle/reply-legacy.png'
    legacy.write_bytes(paths[0].read_bytes())
    original = tmp_path / 'media/stickers/originals/source.png'
    original.parent.mkdir(parents=True)
    original.write_bytes(b'preserved original')
    old = time.time() - board_cache.MAX_AGE - 60
    for path in [paths[0], expired, legacy, original]:
        os.utime(path, (old, old))
    for state in ('pending', 'sending', 'uncertain', 'failed'):
        with runtime.store.transaction() as c:
            c.execute('UPDATE outbox SET state=? WHERE id=2', (state,))
        runtime._next_cache_cleanup = 0
        runtime.maintain_cache()
        assert paths[0].exists() and legacy.exists() and original.exists()
    assert not expired.exists()
    # The size target also leaves protected entries intact, even over the cap.
    assert board_cache.prune(tmp_path, {board_cache.board_key(board)}, max_bytes=0) == 0
    with runtime.store.transaction() as c:
        c.execute("UPDATE outbox SET state='accepted'")
    runtime._next_cache_cleanup = 0
    runtime.maintain_cache()
    assert not paths[0].exists()
    rebuilt = board_cache.render_cached(board, tmp_path)
    assert rebuilt == paths[0] and rebuilt.read_bytes() == legacy.read_bytes()
