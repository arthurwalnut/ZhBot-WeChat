"""Owner-requested group enrollment and local whitelist configuration.

Enrollment only records verified message metadata. Enabling a group is a
separate local action; configuration changes take effect after normal restart.
"""
from dataclasses import replace
import json
import re
import secrets
import time

from .config import load_config, write_config

ENROLLMENT_SECONDS = 300
SETTING = 'group_enrollment'
_IDENTIFIER = re.compile(r'[A-Za-z0-9_.@-]{1,127}\Z')
_COMMAND = re.compile(r'登记群聊 ([0-9A-F]{12})\Z')
_LABELS = re.compile(r'^(?:@[^@\r\n\u2005]+\u2005\s*)+')


def _code(text):
    if not isinstance(text, str) or len(text) > 512:
        return None
    match = _COMMAND.fullmatch(_LABELS.sub('', text).strip())
    return match.group(1) if match else None


def matches_registration(account_id, owner_id, sender_id, text, mentioned_ids):
    """Format/owner/mention gate only; capture checks the actual active code."""
    return bool(account_id and owner_id and owner_id != account_id and sender_id == owner_id
                and isinstance(mentioned_ids, (list, tuple)) and account_id in mentioned_ids
                and _code(text))


def is_registration(config, event):
    return bool(event.account_id == config.account_id and not event.is_self
                and event.chat_type == 'group' and event.message_type == 'text'
                and isinstance(event.chat_id, str) and _IDENTIFIER.fullmatch(event.chat_id)
                and event.chat_id.endswith('@chatroom')
                and isinstance(event.native_message_id, str) and re.fullmatch(r'[0-9]{1,20}', event.native_message_id)
                and int(event.native_message_id) > 0
                and matches_registration(config.account_id, config.owner_id, event.sender_id,
                                         event.text, event.mentioned_ids))


def _record(connection, config):
    from .store import BotStore
    try:
        record = json.loads(BotStore.setting(connection, SETTING, 'null'))
    except (ValueError, TypeError):
        return None
    if (not isinstance(record, dict) or record.get('account_id') != config.account_id
            or record.get('owner_id') != config.owner_id):
        return None
    return record


def _save(connection, record):
    from .store import BotStore
    if not connection.in_transaction:
        raise ValueError('群登记需要已开启的事务')
    BotStore.set_setting(connection, SETTING, json.dumps(record, ensure_ascii=False))


def _valid(record, now):
    return bool(record and isinstance(record.get('created_at'), (float, int))
                and isinstance(record.get('expires_at'), (float, int))
                and record['created_at'] <= now < record['expires_at']
                and record['expires_at'] - record['created_at'] == ENROLLMENT_SECONDS)


def capture(connection, config, event):
    """Consume at most one candidate; no inbox, outbox or group activation."""
    if not is_registration(config, event):
        return False
    record, now = _record(connection, config), time.time()
    if not _valid(record, now) or record.get('state') not in ('waiting', 'candidate'):
        return False
    code = record.get('code')
    if not isinstance(code, str) or not secrets.compare_digest(code, _code(event.text)):
        return False
    if record['state'] == 'candidate':
        return (record.get('group_id') == event.chat_id
                and record.get('native_message_id') == event.native_message_id)
    record.update(state='candidate', group_id=event.chat_id, sender_id=event.sender_id,
                  native_message_id=event.native_message_id, received_at=now)
    _save(connection, record)
    return True


def _fresh(config):
    if config.source_path is None or not config.source_path.is_file():
        raise ValueError('群管理需要已保存的机器人配置文件')
    current = load_config(config.source_path)
    current.require_binding()
    if (current.account_id, current.owner_id, current.data_dir) != (
            config.account_id, config.owner_id, config.data_dir):
        raise ValueError('账号、主人或数据目录已变化，请重新打开管理窗口')
    return current


def _runtime(config):
    from .__main__ import read_status
    record = read_status(config)
    applied = record.get('group_allowlist', [])
    if not isinstance(applied, list) or any(not isinstance(item, str) for item in applied):
        applied = []
    supported = record.get('enrollment_supported') is True
    return {'runtime_state': record.get('state', 'STOPPED'), 'applied_groups': applied,
            'restart_required': record.get('state') != 'READY' or not supported
                                or applied != list(config.group_allowlist)}


def _status(connection, config):
    record, now = _record(connection, config), time.time()
    enrollment = {'state': 'idle'}
    if record and record.get('state') in ('waiting', 'candidate'):
        enrollment = {key: record[key] for key in ('group_id', 'sender_id', 'native_message_id', 'expires_at')
                      if key in record}
        enrollment['state'] = record['state'] if _valid(record, now) else 'expired'
        if enrollment['state'] == 'waiting':
            enrollment['command'] = '登记群聊 ' + record['code']
    return dict(groups=list(config.group_allowlist), enrollment=enrollment, **_runtime(config))


def _group_list(value, name):
    if not isinstance(value, (list, tuple)) or len(value) > 1000:
        raise ValueError(name + '需要为群 ID 数组，最多 1000 个')
    if any(not isinstance(item, str) or not _IDENTIFIER.fullmatch(item)
           or not item.endswith('@chatroom') for item in value):
        raise ValueError(name + '需要已知的原生群 ID，以 @chatroom 结尾')
    if len(set(value)) != len(value):
        raise ValueError(name + '不能包含重复群 ID')
    return list(value)


def manage(connection, config, action, request):
    """Caller holds the shared database write lock for config read/modify/write."""
    if not connection.in_transaction:
        raise ValueError('群管理需要已开启的事务')
    config = _fresh(config)
    if action == 'group_status':
        return _status(connection, config)
    if action == 'group_begin':
        runtime = _runtime(config)
        if not config.owner_id:
            raise ValueError('先配置真实主人账号，才能使用群内登记')
        if runtime['runtime_state'] != 'READY':
            raise ValueError('先启动机器人并等待 READY，再生成登记码')
        if runtime['restart_required']:
            raise ValueError('请先正常重启机器人，加载群登记功能和当前配置')
        now = time.time()
        _save(connection, dict(state='waiting', account_id=config.account_id, owner_id=config.owner_id,
                               code=secrets.token_hex(6).upper(), created_at=now,
                               expires_at=now + ENROLLMENT_SECONDS))
        return _status(connection, config)
    if action == 'group_cancel':
        _save(connection, None)
        return _status(connection, config)
    if action == 'group_accept':
        record = _record(connection, config)
        if record and record.get('state') == 'accepted' and record.get('group_id') in config.group_allowlist:
            return dict(groups=list(config.group_allowlist), restart_required=True)
        if not _valid(record, time.time()) or record.get('state') != 'candidate':
            raise ValueError('没有有效的待确认群，请重新生成登记码并在目标群发送')
        group = _group_list([record['group_id']], '待确认群')[0]
        groups = list(config.group_allowlist)
        if group not in groups:
            groups.append(group)
            write_config(config.source_path, replace(config, group_allowlist=tuple(groups)))
        record['state'] = 'accepted'
        record.pop('code', None)
        _save(connection, record)
        return dict(groups=groups, restart_required=True)
    if action == 'group_edit':
        expected = _group_list(request.get('expected_groups'), '页面中的群名单')
        if expected != list(config.group_allowlist):
            raise ValueError('群名单已经变化，请刷新后再修改')
        added = _group_list(request.get('add', []), '添加群')
        removed = _group_list(request.get('remove', []), '移除群')
        if set(added) & set(removed):
            raise ValueError('同一群不能同时添加和移除')
        if any(group not in expected for group in removed):
            raise ValueError('待移除的群不在当前名单中，请刷新后再修改')
        groups = [group for group in expected if group not in removed]
        groups.extend(group for group in added if group not in groups)
        if not groups:
            raise ValueError('当前至少需要保留一个允许群，暂停全部群功能请正常停止机器人')
        if groups != expected:
            write_config(config.source_path, replace(config, group_allowlist=tuple(groups)))
        return dict(groups=groups, restart_required=True)
    raise ValueError('未知群管理操作')
