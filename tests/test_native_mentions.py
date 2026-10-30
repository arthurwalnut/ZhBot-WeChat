"""Native mention preflight on synthetic SDK objects; never opens WeChat."""
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
import json
import sys
import threading
import time

import pytest

from wechat_bot.adapters import helper_native, member_names
from wechat_bot.gateway import Outgoing
from test_bot import event, process, rows, setup


@pytest.fixture
def native(tmp_path, monkeypatch):
    # The regression suite remains runnable without downloading the optional SDK.
    sdk = ModuleType('wxbot_framework')
    sdk.__path__ = []
    text = ModuleType('wxbot_framework.text')
    text.validate_target = lambda value: value
    text.validate_mentions = lambda room, members: members
    contacts = ModuleType('wxbot_framework.contacts')
    contacts.read_contact_name = Mock(return_value=None)
    monkeypatch.setitem(sys.modules, 'wxbot_framework', sdk)
    monkeypatch.setitem(sys.modules, text.__name__, text)
    monkeypatch.setitem(sys.modules, contacts.__name__, contacts)
    raw = SimpleNamespace(_calls=threading.RLock(), _check_account=Mock(),
                          _channel=SimpleNamespace(read_memory=Mock(), core_base=0x100000000))
    backend = SimpleNamespace(raw=raw, group_members=Mock(return_value=()),
                              send_at_text=Mock(return_value=True), send_text=Mock(return_value=True))
    gateway = helper_native.HelperNative(Path('unused-helper'), tmp_path, 'wxid_robot', 123,
                                         ('123@chatroom', '456@chatroom'))
    gateway._backend = backend
    gateway.connection_id = 'synthetic-connection'
    monkeypatch.setattr(gateway, 'health', lambda: {'connected': True})
    fallback = Mock(return_value=None)
    monkeypatch.setattr(helper_native, 'read_group_contact_name', fallback)
    return gateway, backend, contacts, fallback


def test_mentions_prefer_current_group_names_and_keep_native_targets(native):
    gateway, backend, contacts, fallback = native
    outgoing = Outgoing('wxid_robot', '123@chatroom', 'group', 'text', text='回复',
                        mentioned_ids=('wxid_alice', 'wxid_bob'), connection_id=gateway.connection_id)
    backend.group_members.return_value = (
        {'wxid': 'wxid_alice', 'group_nickname': '小张', 'wechat_name': '张三'},
        {'wxid': 'wxid_bob', 'group_nickname': '', 'wechat_name': ''},
    )

    def nonfriend_name(read, base, member, *, expected_account):
        assert backend.raw._calls._is_owned()
        assert member == 'wxid_bob' and expected_account == 'wxid_robot'
        assert read is backend.raw._channel.read_memory and base == backend.raw._channel.core_base
        return '群友乙'

    fallback.side_effect = nonfriend_name
    assert gateway.send(outgoing).status == 'accepted'
    backend.send_at_text.assert_called_with('123@chatroom', '@小张\u2005 @群友乙\u2005\n回复',
                                             outgoing.mentioned_ids)
    assert contacts.read_contact_name.call_count == fallback.call_count == 1
    # Same member in another room and after renaming must be looked up again.
    other = replace(outgoing, chat_id='456@chatroom', mentioned_ids=('wxid_alice',))
    backend.group_members.return_value = (
        {'wxid': 'wxid_alice', 'group_nickname': '张老师', 'wechat_name': '张三'},)
    assert gateway.send(other).status == 'accepted'
    backend.send_at_text.assert_called_with('456@chatroom', '@张老师\u2005\n回复', ('wxid_alice',))
    backend.group_members.return_value = (
        {'wxid': 'wxid_alice', 'group_nickname': '小张改名', 'wechat_name': '张三'},)
    assert gateway.send(replace(outgoing, mentioned_ids=('wxid_alice',))).status == 'accepted'
    assert backend.send_at_text.call_args.args[1] == '@小张改名\u2005\n回复'
    # A genuine SDK wechat_name remains usable when there is no group override.
    backend.group_members.return_value = (
        {'wxid': 'wxid_alice', 'group_nickname': '', 'wechat_name': '张三'},)
    assert gateway.send(other).status == 'accepted'
    assert backend.send_at_text.call_args.args[1] == '@张三\u2005\n回复'
    assert backend.group_members.call_count == 4
    assert fallback.call_count == 1


def test_unavailable_name_never_submits_and_retries_saved_reply_with_a_limit(tmp_path, native):
    gateway, backend, contacts, fallback = native
    outgoing = Outgoing('wxid_robot', '123@chatroom', 'group', 'text', text='回复',
                        mentioned_ids=('wxid_alice',), connection_id=gateway.connection_id)
    result = gateway.send(outgoing)
    assert (result.status, result.detail, result.retryable) == ('failed', 'MENTION_NAME_UNAVAILABLE', True)
    backend.send_at_text.assert_not_called()
    backend.send_text.assert_not_called()
    runtime = setup(tmp_path, gateway=gateway)
    process(runtime, event(1))
    original = rows(runtime, 'draws')
    payload = json.loads(rows(runtime, 'outbox')[0]['payload'])
    clock = time.time()
    for offset, expected in ((0, 'pending'), (3, 'pending'), (8, 'failed')):
        assert runtime.send_one(now=clock + offset)
        row = rows(runtime, 'outbox')[0]
        assert row['state'] == expected and row['detail'] == 'MENTION_NAME_UNAVAILABLE'
        assert json.loads(row['payload']) == payload and rows(runtime, 'draws') == original
    assert rows(runtime, 'outbox')[0]['attempts'] == 3
    assert not runtime.send_one(now=clock + 20)
    backend.send_at_text.assert_not_called()
    # A later reply may succeed once the regular contact cache is populated.
    contacts.read_contact_name.return_value = '张三'
    assert gateway.send(outgoing).status == 'accepted'
    assert backend.send_at_text.call_args.args[1] == '@张三\u2005\n回复'


def test_nonfriend_reader_rejects_unverified_profiles_and_other_accounts(native, monkeypatch):
    _, _, contacts, _ = native
    account = ModuleType('wxbot_framework.account')
    account.read_current_account = Mock(return_value='wxid_robot')
    account.validate_account = lambda value: value
    profiles = ModuleType('wxbot_framework.native_profiles')
    profiles.select_memory_profile = Mock(return_value=None)
    groups = ModuleType('wxbot_framework.group_members')
    groups._StableReader, groups._find_room = Mock(), Mock()
    contacts.ContactDirectoryError = type('ContactDirectoryError', (RuntimeError,), {})
    contacts._DirectoryReader = Mock(side_effect=contacts.ContactDirectoryError('synthetic cache unavailable'))
    contacts._directory_cache = Mock()
    for module in (account, profiles, groups):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    read = Mock(side_effect=AssertionError('no process memory in this test'))
    for profile in (None, SimpleNamespace(version='unknown'), SimpleNamespace(version='4.1.15.13')):
        profiles.select_memory_profile.return_value = profile
        assert member_names.read_group_contact_name(read, 0x100000000, 'wxid_alice',
                                                     expected_account='wxid_robot') is None
    contacts._DirectoryReader.assert_not_called()
    for version in ('4.1.15.56', '4.2.0.11'):
        profiles.select_memory_profile.return_value = SimpleNamespace(version=version)
        assert member_names.read_group_contact_name(read, 0x100000000, 'wxid_alice',
                                                     expected_account='wxid_robot') is None
    assert contacts._DirectoryReader.call_count == 2
    contacts._DirectoryReader.reset_mock()
    assert member_names.read_group_contact_name(read, 0x100000000, 'wxid_alice',
                                                 expected_account='wxid_another') is None
    contacts._DirectoryReader.assert_not_called()
