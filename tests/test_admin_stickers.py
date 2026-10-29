"""Local imports share the native library without fabricating upload events."""
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import time

from PIL import Image
import pytest

from wechat_bot.stickers import StickerError, StickerService
from wechat_bot.config import Config
from wechat_bot.gateway import Event, SendResult
from wechat_bot.runtime import Runtime


def test_local_import_shared_pool_and_transactional_delete(tmp_path, monkeypatch):
    service = StickerService(tmp_path)
    connection = sqlite3.connect(tmp_path / 'bot.sqlite3')
    connection.row_factory = sqlite3.Row
    with connection:
        service.initialize(connection)
    scope = {'account_id': 'wxid_robot', 'chat_id': '123@chatroom'}
    alice = {**scope, 'sender_id': 'wxid_alice'}
    owner = {**scope, 'sender_id': 'wxid_owner'}
    bob = {**scope, 'sender_id': 'wxid_bob'}

    def prepare(color):
        raw = BytesIO()
        Image.new('RGB', (8, 8), color).save(raw, format='GIF')
        return service.prepare(raw.getvalue())

    red, blue = prepare('red'), prepare('blue')
    with connection:
        service.begin_wait(connection, **alice, received_at=100)
        intent = service.claim(connection, **alice, native_message_id='100',
                               received_at=101, message_type='sticker')
        native = service.add(connection, intent, red)
        duplicate = service.add_local(connection, **owner, prepared=red)
        imported = service.add_local(connection, **owner, prepared=blue)
    assert native['origin'] == 'wechat' and native['native_message_id'] == '100'
    assert duplicate['is_duplicate'] and duplicate['id'] == native['id']
    assert duplicate['sender_id'] == 'wxid_alice' and duplicate['origin'] == 'wechat'
    assert imported['origin'] == 'local' and imported['native_message_id'].startswith('local:')
    assert imported['sender_id'] == 'wxid_owner'
    # No synthetic upload wait or inbox event was needed for either local import.
    assert connection.execute('SELECT COUNT(*) FROM sticker_waits').fetchone()[0] == 0
    assert connection.execute("SELECT 1 FROM sqlite_master WHERE name='inbox'").fetchone() is None
    with connection:
        service.begin_wait(connection, **bob, received_at=110)
        intent = service.claim(connection, **bob, native_message_id='101',
                               received_at=111, message_type='sticker')
        duplicate = service.add(connection, intent, blue)
    assert duplicate['is_duplicate'] and duplicate['id'] == imported['id']
    assert duplicate['sender_id'] == 'wxid_owner' and duplicate['origin'] == 'local'

    monkeypatch.setattr('wechat_bot.stickers.secrets.choice', lambda items: max(items, key=lambda item: item['id']))
    assert service.random(connection, **scope)['id'] == imported['id']
    assert service.list(connection, **alice)['total'] == service.list(connection, **owner)['total'] == 1
    assert service.list(connection, **bob)['total'] == 0

    connection.execute('''CREATE TABLE outbox (id INTEGER PRIMARY KEY,account_id TEXT,chat_id TEXT,
        payload TEXT,state TEXT,detail TEXT DEFAULT '')''')
    payload = json.dumps({'kind': 'sticker', 'sticker_id': imported['id']})
    with connection:
        connection.executemany('INSERT INTO outbox(id,account_id,chat_id,payload,state) VALUES (?,?,?,?,?)', [
            (1, scope['account_id'], scope['chat_id'], payload, 'pending'),
            (2, scope['account_id'], scope['chat_id'], payload, 'sending'),
            (3, scope['account_id'], 'other@chatroom', payload, 'pending'),
            (4, 'wxid_other_robot', scope['chat_id'], payload, 'pending'),
            (5, scope['account_id'], scope['chat_id'], json.dumps({'kind':'sticker','sticker_id':native['id']}), 'pending'),
        ])
    with pytest.raises(StickerError), connection:
        service.delete_with_pending(connection, **alice, sticker_id=imported['id'])
    with pytest.raises(RuntimeError), connection:
        service.delete_with_pending(connection, **owner, sticker_id=imported['id'])
        raise RuntimeError('administrative transaction failed')
    assert connection.execute('SELECT deleted FROM stickers WHERE id=?', (imported['id'],)).fetchone()[0] == 0
    assert connection.execute('SELECT state FROM outbox WHERE id=1').fetchone()[0] == 'pending'
    with connection:
        service.delete_with_pending(connection, **owner, sticker_id=imported['id'])
    assert dict(connection.execute('SELECT id,state FROM outbox')) == {
        1: 'expired', 2: 'sending', 3: 'pending', 4: 'pending', 5: 'pending'}
    assert Path(imported['path']).exists() and Path(imported['source_path']).exists()
    assert service.random(connection, **scope)['id'] == native['id']
    connection.close()


@pytest.mark.parametrize('result,expected', [
    (SendResult('failed', 'not submitted', True), 'expired'),
    (SendResult('accepted', 'submission completed'), 'accepted'),
    (SendResult('uncertain', 'submission outcome unknown'), 'uncertain'),
])
def test_admin_delete_during_send_never_requeues_deleted_item(tmp_path, result, expected):
    """Interleave another DB connection while the sender holds no transaction."""
    config = Config(account_id='wxid_robot', owner_id='wxid_owner', group_allowlist=('123@chatroom',),
                    data_dir=tmp_path, wechat_pid=1, stickers=True, per_user_cooldown_seconds=0)

    class Gateway:
        connection_id = 'synthetic-connection'
        calls = 0

        def send(self, outgoing):
            self.calls += 1
            assert outgoing.kind == 'sticker'
            # This is a separate SQLite transaction, as used by the EXE admin.
            with runtime.store.transaction() as connection:
                assert connection.execute('SELECT state FROM outbox').fetchone()[0] == 'sending'
                runtime.stickers.delete_with_pending(connection, account_id=config.account_id,
                    chat_id='123@chatroom', sender_id=config.owner_id, owner_id=config.owner_id,
                    sticker_id=item['id'])
            return result

    gateway = Gateway()
    runtime = Runtime(config, gateway)
    raw = BytesIO()
    Image.new('RGB', (8, 8), 'red').save(raw, format='GIF')
    prepared = runtime.stickers.prepare(raw.getvalue())
    with runtime.store.transaction() as connection:
        item = runtime.stickers.add_local(connection, account_id=config.account_id,
            chat_id='123@chatroom', sender_id=config.owner_id, prepared=prepared)
    now = time.time()
    runtime.receive(Event(config.account_id, '123@chatroom', 'group', 'wxid_alice', '123', now,
        'text', text='随机表情包', mentioned_ids=(config.account_id,), connection_id=gateway.connection_id))
    assert runtime.process_one() and runtime.send_one(now=now)
    with runtime.store.transaction() as connection:
        assert connection.execute('SELECT state FROM outbox').fetchone()[0] == expected
    assert not runtime.send_one(now=now + 5) and gateway.calls == 1
    assert Path(item['path']).exists()
    if expected == 'expired':
        # A pending item left by an older runtime must also be rejected before
        # invoking native code; this exercises the pre-claim availability check.
        with runtime.store.transaction() as connection:
            connection.execute("UPDATE outbox SET state='pending',next_attempt=0")
        assert runtime.send_one(now=now + 10) and gateway.calls == 1
        with runtime.store.transaction() as connection:
            assert connection.execute('SELECT state FROM outbox').fetchone()[0] == 'expired'
