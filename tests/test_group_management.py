"""Isolated config/database enrollment; no native bridge or WeChat traffic."""
from dataclasses import replace
import json
import os
import re
import time
from types import SimpleNamespace

import pytest

from wechat_bot.admin import AdminService
from wechat_bot.config import Config, load_config, write_config
from wechat_bot.gateway import Event
from wechat_bot import groups


def fixture_admin(tmp_path, *, owner='wxid_owner'):
    directory = tmp_path / 'runtime'
    directory.mkdir(parents=True)
    path = directory / 'config.bot.toml'
    cfg = Config(account_id='wxid_robot', owner_id=owner, wechat_pid=123,
                 group_allowlist=('existing@chatroom',), data_dir=directory,
                 helper_root=tmp_path / 'helper', stickers=True, per_user_cooldown_seconds=7,
                 source_path=path)
    write_config(path, cfg)
    ready(cfg)
    return AdminService(load_config(path))


def ready(cfg, *, supported=True, state='READY'):
    (cfg.data_dir / 'status.json').write_text(json.dumps(dict(
        state=state, pid=os.getpid(), updated_at=time.time(),
        group_allowlist=list(cfg.group_allowlist), enrollment_supported=supported)), encoding='utf-8')


def registration(command, **changes):
    event = Event(account_id='wxid_robot', chat_id='new@chatroom', chat_type='group',
                  sender_id='wxid_owner', native_message_id='123456789', received_at=time.time(),
                  message_type='text', text='@机器人\u2005 ' + command, mentioned_ids=('wxid_robot',))
    return replace(event, **changes)


def test_registration_requires_native_owner_candidate_and_local_accept(tmp_path):
    admin = fixture_admin(tmp_path)
    before = admin.config
    begun = admin.execute({'action': 'group_begin'})
    assert begun['enrollment']['state'] == 'waiting'
    command = begun['enrollment']['command']
    assert re.fullmatch('登记群聊 [0-9A-F]{12}', command)
    event = registration(command)
    assert groups.is_registration(before, event)
    for wrong in (replace(event, sender_id='wxid_other'), replace(event, mentioned_ids=()),
                  replace(event, account_id='wxid_other'), replace(event, is_self=True),
                  replace(event, chat_type='private'), replace(event, chat_id='wxid_owner'),
                  replace(event, native_message_id='fake-local-id'), replace(event, message_type='image'),
                  replace(event, text='引用：' + event.text)):
        assert not groups.is_registration(before, wrong)
        with admin.store.transaction() as c:
            assert not groups.capture(c, before, wrong)
    with admin.store.transaction() as c:
        assert groups.capture(c, before, event)
        assert groups.capture(c, before, event)  # Same native message is idempotent.
        assert not groups.capture(c, before, replace(event, chat_id='other@chatroom', native_message_id='234'))
        assert c.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 0
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 0
    candidate = admin.execute({'action': 'group_status'})['enrollment']
    assert candidate['state'] == 'candidate' and candidate['group_id'] == event.chat_id
    assert candidate['native_message_id'] == event.native_message_id
    assert 'command' not in candidate
    assert load_config(before.source_path).group_allowlist == before.group_allowlist

    accepted = admin.execute({'action': 'group_accept'})
    assert accepted['groups'] == ['existing@chatroom', 'new@chatroom'] and accepted['restart_required']
    after = load_config(before.source_path)
    assert replace(after, group_allowlist=before.group_allowlist) == before
    backups = list((before.source_path.parent / 'backups').glob('config.bot.toml.*.bak'))
    assert len(backups) == 1
    assert load_config(backups[0]).group_allowlist == before.group_allowlist
    assert admin.execute({'action': 'group_accept'})['groups'] == accepted['groups']
    assert len(list((before.source_path.parent / 'backups').glob('config.bot.toml.*.bak'))) == 1
    status = admin.execute({'action': 'group_status'})
    assert status['restart_required'] and status['applied_groups'] == ['existing@chatroom']
    assert status['enrollment']['state'] == 'idle'
    ready(after)  # Simulate the status produced after restarting with saved config.
    assert not admin.execute({'action': 'group_status'})['restart_required']


def test_registration_expiry_cancel_and_runtime_requirements(tmp_path, monkeypatch):
    admin = fixture_admin(tmp_path)
    clock = [1000.0]
    monkeypatch.setattr(groups, 'time', SimpleNamespace(time=lambda: clock[0]))
    first = admin.execute({'action': 'group_begin'})['enrollment']['command']
    second = admin.execute({'action': 'group_begin'})['enrollment']['command']
    assert first != second
    with admin.store.transaction() as c:
        assert not groups.capture(c, admin.config, registration(first))
    clock[0] += groups.ENROLLMENT_SECONDS
    with admin.store.transaction() as c:
        assert not groups.capture(c, admin.config, registration(second))
    assert admin.execute({'action': 'group_status'})['enrollment']['state'] == 'expired'
    with pytest.raises(ValueError, match='有效'):
        admin.execute({'action': 'group_accept'})
    third = admin.execute({'action': 'group_begin'})['enrollment']['command']
    with admin.store.transaction() as c:
        assert groups.capture(c, admin.config, registration(third))
    clock[0] += groups.ENROLLMENT_SECONDS
    with pytest.raises(ValueError, match='有效'):
        admin.execute({'action': 'group_accept'})
    admin.execute({'action': 'group_cancel'})
    assert admin.execute({'action': 'group_status'})['enrollment']['state'] == 'idle'
    ready(admin.config, supported=False)
    with pytest.raises(ValueError, match='重启'):
        admin.execute({'action': 'group_begin'})
    ready(admin.config, state='STOPPED')
    with pytest.raises(ValueError, match='READY'):
        admin.execute({'action': 'group_begin'})
    no_owner = fixture_admin(tmp_path / 'no-owner', owner='')
    with pytest.raises(ValueError, match='主人'):
        no_owner.execute({'action': 'group_begin'})


def test_manual_group_changes_preserve_config_and_reject_stale_updates(tmp_path):
    admin = fixture_admin(tmp_path)
    old = admin.config
    added = admin.execute({'action': 'group_edit', 'add': ['manual@chatroom'],
                           'expected_groups': ['existing@chatroom']})
    assert added['groups'] == ['existing@chatroom', 'manual@chatroom']
    # A second window with an older list cannot overwrite the first edit.
    with pytest.raises(ValueError, match='已经变化'):
        admin.execute({'action': 'group_edit', 'add': ['second@chatroom'],
                       'expected_groups': ['existing@chatroom']})
    for updates in ({'add': ['not-a-group']}, {'add': ['other@chatroom'], 'remove': ['other@chatroom']},
                    {'remove': ['existing@chatroom', 'manual@chatroom']}):
        with pytest.raises(ValueError):
            admin.execute(dict(action='group_edit', expected_groups=added['groups'], **updates))
    assert load_config(old.source_path).group_allowlist == tuple(added['groups'])
    # Keep fresh unrelated configuration, even when this AdminService was constructed earlier.
    write_config(old.source_path, replace(load_config(old.source_path), per_user_cooldown_seconds=8))
    removed = admin.execute({'action': 'group_edit', 'remove': ['existing@chatroom'],
                             'expected_groups': added['groups']})
    assert removed['groups'] == ['manual@chatroom'] and removed['restart_required']
    assert load_config(old.source_path).per_user_cooldown_seconds == 8
    with admin.store.transaction() as c:
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 0
