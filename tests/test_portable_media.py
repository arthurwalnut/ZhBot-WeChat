"""Relocate an isolated runtime, then resolve and send its durable replies."""
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import shutil

from PIL import Image
import pytest

from wechat_bot.admin import AdminService
from wechat_bot.runtime import Runtime
from wechat_bot.stickers import StickerError
from test_bot import FakeGateway, event, process, rows, setup


def test_copied_runtime_resolves_old_media_and_keeps_uncertain_replies(tmp_path):
    old_root = tmp_path / 'old project' / 'runtime'
    new_root = tmp_path / '新目录 with spaces' / 'runtime'
    old = setup(old_root, stickers=True)
    png, gif = BytesIO(), BytesIO()
    Image.new('RGB', (8, 8), 'red').save(png, format='PNG')
    Image.new('RGB', (8, 8), 'red').save(gif, format='GIF')
    prepared = old.stickers.prepare(gif.getvalue(), source_format='PNG', source_data=png.getvalue())
    scope = dict(account_id=old.config.account_id, chat_id='123@chatroom', sender_id=old.config.owner_id)
    with old.store.transaction() as c:
        item = old.stickers.add_local(c, **scope, prepared=prepared)
        stored = dict(c.execute('SELECT * FROM stickers').fetchone())
        assert stored['path'].startswith('media/stickers/') and not Path(stored['path']).is_absolute()
        assert stored['source_path'].startswith('media/stickers/originals/')
        # Preserve legacy metadata exactly; old versions wrote absolute paths.
        c.execute('UPDATE stickers SET path=?,source_path=? WHERE id=?',
                  (item['path'], item['source_path'], item['id']))
    for identifier in range(1, 5):
        process(old, event(identifier, '随机表情包'))
    process(old, event(5, '猜词'))
    with old.store.transaction() as c:
        for row in c.execute("SELECT id,payload FROM outbox WHERE id<=4").fetchall():
            payload = dict(json.loads(row['payload']), path=item['path'])
            if row['id'] == 4:
                payload.pop('sticker_id')  # Legacy pre-library outbox resource.
            c.execute('UPDATE outbox SET payload=? WHERE id=?', (json.dumps(payload), row['id']))
        c.execute("UPDATE outbox SET state='uncertain' WHERE id=2")
        c.execute("UPDATE outbox SET state='sending' WHERE id=3")
        blue = BytesIO()
        Image.new('RGB', (8, 8), 'blue').save(blue, format='GIF')
        deleted = old.stickers.add_local(c, **scope, prepared=old.stickers.prepare(blue.getvalue()))
        old.stickers.delete(c, **scope, sticker_id=deleted['id'])
        previous_stickers = [tuple(r) for r in c.execute('SELECT * FROM stickers ORDER BY id')]
        previous_games = [tuple(r) for r in c.execute('SELECT * FROM games ORDER BY id')]
    shutil.copytree(old_root, new_root)
    # Even while the old location still exists, all reads must use the copy.
    Path(item['path']).write_bytes(b'not the copied GIF')
    Path(item['source_path']).write_bytes(b'not the copied original')
    config = replace(old.config, data_dir=new_root)
    gateway = FakeGateway()
    current = Runtime(config, gateway)
    with current.store.transaction() as c:
        assert current.stickers.audit_paths(c) == {'stickers': 2, 'originals': 2}
        assert [tuple(r) for r in c.execute('SELECT * FROM stickers ORDER BY id')] == previous_stickers
    page = AdminService(config).execute({'action': 'stickers'})
    preview = page['items'][0]
    assert Path(preview['preview_path']).is_relative_to(new_root)
    assert Path(preview['preview_path']).read_bytes() == gif.getvalue()
    assert Path(preview['original_path']).read_bytes() == png.getvalue()
    current.store.recover()
    while current.send_one():
        pass
    assert [message.kind for message in gateway.sent] == ['sticker', 'sticker', 'image']
    assert all(Path(message.path).is_relative_to(new_root) for message in gateway.sent)
    assert [r['state'] for r in rows(current, 'outbox')] == ['accepted', 'uncertain', 'uncertain', 'accepted', 'accepted']
    with current.store.transaction() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM games ORDER BY id')] == previous_games
        assert [tuple(r) for r in c.execute('SELECT * FROM stickers ORDER BY id')] == previous_stickers
    process(current, event(6, '随机表情包'))
    assert json.loads(rows(current, 'outbox')[-1]['payload'])['path'].startswith('media/stickers/')
    assert current.send_one() and len(gateway.sent) == 4

    # Relocation never accepts an arbitrary external basename or altered bytes.
    with pytest.raises(StickerError, match='路径'):
        current.stickers.resolve_path(dict(item, path='C:/unrelated/' + Path(item['path']).name))
    with pytest.raises(StickerError, match='路径'):
        current.stickers.resolve_path(dict(item, path='../media/stickers/' + Path(item['path']).name))
    copied = current.stickers.resolve_path(item)
    copied.write_bytes(b'x' * len(gif.getvalue()))
    with pytest.raises(StickerError, match='摘要'):
        current.stickers.resolve_path(item)
