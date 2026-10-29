"""Local admin contract on isolated data; never sends WeChat messages."""
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path

from PIL import Image
import pytest

from wechat_bot.admin import AdminService
from wechat_bot.config import Config
from wechat_bot.gateway import Event
from wechat_bot import dictionaries
from wordle.game import WordleService
from zxj.service import draw


def test_owner_management_records_dictionaries_and_media(tmp_path):
    cfg = Config(account_id='wxid_robot', owner_id='wxid_owner', wechat_pid=123,
                 group_allowlist=('one@chatroom', 'two@chatroom'), data_dir=tmp_path / 'data')
    admin = AdminService(cfg)
    with admin.store.transaction() as c:
        for identifier, member, group, name in ((1, 'wxid_a', 'one@chatroom', '甲'), (2, 'wxid_b', 'two@chatroom', '乙')):
            event = Event(cfg.account_id, group, 'group', member, str(identifier), 1,
                          'text', sender_display_name=name)
            c.execute("""INSERT INTO inbox
                (namespace,account_id,chat_id,native_message_id,received_at,payload)
                VALUES ('helper.native_text',?,?,?,?,?)""", (cfg.account_id, group,
                event.native_message_id, event.received_at, json.dumps(asdict(event))))
        old = draw('wxid_a', connection=c, now=datetime(2026, 10, 30, tzinfo=UTC))
        draw('wxid_b', connection=c, now=datetime(2026, 10, 30, tzinfo=UTC))
    game = WordleService(admin.store.path, dictionary_provider=dictionaries.words,
                         answer_picker=lambda words: 'apple')
    game.start('one@chatroom', 'wxid_a')
    game.guess('one@chatroom', 'wxid_b', 'apple')
    game.start('two@chatroom', 'wxid_a')
    overview = admin.execute({'action': 'overview'})
    assert overview['ok'] and overview['counts'] == {'draws': 2, 'wins': 1, 'stickers': 0}
    history = admin.execute({'action': 'zxj_history', 'group_id': 'one@chatroom'})
    assert history['total'] == 2  # Both members were observed in this group, including its winner.
    history = admin.execute({'action': 'zxj_history', 'group_id': 'one@chatroom', 'user_id': 'wxid_a'})
    assert history['total'] == 1 and history['items'][0]['member'] == '甲'
    assert history['items'][0]['result'] == old['result']
    wins = admin.execute({'action': 'wordle_wins', 'user_id': 'wxid_b'})
    assert len(wins['items']) == 1 and wins['items'][0]['word'] == 'apple'
    assert wins['items'][0]['group_id'] == 'one@chatroom'
    assert admin.execute({'action': 'wordle_wins', 'group_id': 'two@chatroom'})['items'] == []

    admin.execute({'action': 'zxj_save', 'characters': {'z': '中 正', 'x': '星', 'j': '家'}})
    assert admin.execute({'action': 'zxj_dictionary'})['characters']['z'] == ['中', '正']
    with admin.store.transaction() as c:
        assert draw('wxid_a', connection=c, now=datetime(2026, 10, 30, tzinfo=UTC),
                    characters=dictionaries.characters(c))['result'] == old['result']
        assert draw('wxid_new', connection=c, characters=dictionaries.characters(c))['result'] in ('中星家', '正星家')
    admin.execute({'action': 'wordle_edit', 'add': ['zzyzx']})
    words = admin.execute({'action': 'wordle_dictionary', 'length': 5, 'search': 'zzyzx'})
    assert words['items'] == [{'word': 'zzyzx', 'length': 5, 'kind': '答案词'}]
    admin.execute({'action': 'wordle_edit', 'remove': ['zzyzx']})
    assert admin.execute({'action': 'wordle_dictionary', 'search': 'zzyzx'})['total'] == 0

    source = tmp_path / 'picture.png'
    Image.new('RGB', (20, 20), 'orange').save(source)
    added = admin.execute({'action': 'sticker_add', 'group_id': 'one@chatroom', 'path': str(source)})
    assert not added['duplicate']
    repeated = admin.execute({'action': 'sticker_add', 'group_id': 'one@chatroom', 'path': str(source)})
    assert repeated['duplicate'] and repeated['id'] == added['id']
    stickers = admin.execute({'action': 'stickers', 'user_id': cfg.owner_id})['items']
    assert len(stickers) == 1 and stickers[0]['origin'] == '本机导入'
    assert Path(stickers[0]['preview_path']).is_file() and Path(stickers[0]['original_path']).read_bytes() == source.read_bytes()
    assert admin.execute({'action': 'stickers', 'group_id': 'two@chatroom'})['items'] == []
    with pytest.raises(ValueError):
        admin.execute({'action': 'sticker_delete', 'group_id': 'two@chatroom', 'id': added['id']})
    admin.execute({'action': 'sticker_delete', 'group_id': 'one@chatroom', 'id': added['id']})
    assert admin.execute({'action': 'stickers'})['total'] == 0
    assert Path(stickers[0]['preview_path']).exists()
    with admin.store.transaction() as c:
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 0
    with pytest.raises(ValueError):
        admin.execute({'action': 'zxj_history', 'group_id': 'unknown@chatroom'})
    with pytest.raises(ValueError):
        admin.execute({'action': 'wordle_edit', 'add': ['a bad word']})
