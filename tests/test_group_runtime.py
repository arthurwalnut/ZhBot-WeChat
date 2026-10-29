"""New-group onboarding through the real adapter conversion, with synthetic input only."""
from dataclasses import replace
from types import SimpleNamespace
import json
import threading
import time

from wechat_bot.admin import AdminService
from wechat_bot.adapters.helper_native import HelperNative
from wechat_bot.config import Config, load_config, write_config
from wechat_bot.runtime import Runtime
from test_bot import FakeGateway


def test_native_registration_is_narrow_and_requires_local_acceptance_and_restart(tmp_path):
    path = tmp_path / 'config.toml'
    cfg = Config(account_id='wxid_robot', owner_id='wxid_owner', wechat_pid=123,
                 group_allowlist=('old@chatroom',), data_dir=tmp_path, source_path=path,
                 per_user_cooldown_seconds=0)
    write_config(path, cfg)
    runtime = Runtime(cfg, FakeGateway())
    runtime.state = 'READY'
    runtime.write_status()  # Isolated synthetic runtime; never loads a DLL.
    admin = AdminService(cfg)
    admin.execute({'action': 'group_begin'})
    command = admin.execute({'action': 'group_status'})['enrollment']['command']

    def convert(text, *, sender='wxid_owner', mentions=('wxid_robot',), native_id='101', kind=1):
        adapter = HelperNative(cfg.helper_root, cfg.data_dir, cfg.account_id, cfg.wechat_pid,
                               cfg.group_allowlist, owner_id=cfg.owner_id)
        adapter.connection_id = 'synthetic-connection'
        message = SimpleNamespace(session_id=adapter.connection_id, type=kind, is_self=False,
            is_group=True, chat_id='new@chatroom', sender_id=sender, text=text,
            data={'self_wxid': cfg.account_id, 'native_message_id': native_id, 'at_members': mentions})
        return adapter._convert(message)

    text = '@测试机器人\u2005' + command
    assert convert('普通群消息') is None
    assert convert(text, sender='wxid_other') is None
    assert convert(text, mentions=()) is None
    assert convert(text, native_id='') is None
    assert convert(text, kind=3) is None
    candidate = convert(text)
    assert candidate is not None
    wrong = command[:-1] + ('0' if command[-1] != '0' else '1')
    runtime.receive(replace(candidate, text='@测试机器人\u2005' + wrong))
    assert admin.execute({'action': 'group_status'})['enrollment']['state'] == 'waiting'
    runtime.receive(candidate)
    runtime.receive(candidate)
    status = admin.execute({'action': 'group_status'})
    assert status['groups'] == ['old@chatroom']
    assert status['enrollment']['state'] == 'candidate'
    assert status['enrollment']['group_id'] == 'new@chatroom'
    assert status['enrollment']['native_message_id'] == '101'
    with runtime.store.transaction() as c:
        assert c.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 0
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 0

    admin.execute({'action': 'group_accept'})
    updated = load_config(path)
    assert updated.group_allowlist == ('old@chatroom', 'new@chatroom')
    assert cfg.group_allowlist == ('old@chatroom',)  # Existing runtime is unchanged until restart.
    gateway = FakeGateway()
    restarted = Runtime(updated, gateway)
    event = replace(candidate, native_message_id='102', received_at=time.time(), text='@测试机器人\u2005随机zxj')
    restarted.receive(event)
    assert restarted.process_one()
    with restarted.store.transaction() as c:
        reply = c.execute('SELECT chat_id,state FROM outbox').fetchone()
        assert tuple(reply) == ('new@chatroom', 'pending')
    AdminService(updated).execute({'action': 'group_edit', 'add': [], 'remove': ['new@chatroom'],
                                  'expected_groups': list(updated.group_allowlist)})
    removed = Runtime(load_config(path), gateway)
    assert removed.send_one()
    assert gateway.sent == []
    with removed.store.transaction() as c:
        assert c.execute('SELECT state FROM outbox').fetchone()[0] == 'expired'
        assert c.execute('SELECT COUNT(*) FROM draws').fetchone()[0] == 1


def test_status_publish_survives_short_windows_reader(tmp_path):
    cfg = Config(account_id='wxid_robot', group_allowlist=('old@chatroom',), data_dir=tmp_path)
    runtime = Runtime(cfg, FakeGateway())
    runtime.state = 'READY'
    runtime.write_status()
    reader = (tmp_path / 'status.json').open('rb')
    release = threading.Timer(0.08, reader.close)
    release.start()
    try:
        runtime.last_receive = 123.0
        runtime.write_status()
    finally:
        release.join()
        reader.close()
    saved = json.loads((tmp_path / 'status.json').read_text(encoding='utf-8'))
    assert saved['last_receive'] == 123.0 and saved['state'] == 'READY'
