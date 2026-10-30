"""Owner-edited replies on isolated databases, never live group messages."""
from dataclasses import replace
import json
import time

import pytest

from wechat_bot.admin import AdminService
from wechat_bot.gateway import SendResult
from wechat_bot.runtime import Runtime
from wechat_bot import qa
from test_bot import FakeGateway, event, process, rows, setup


def text(runtime):
    return json.loads(rows(runtime, 'outbox')[-1]['payload'])['text']


def test_owner_qa_crud_exact_matching_and_group_permissions(tmp_path):
    initial = setup(tmp_path)
    config = replace(initial.config, group_allowlist=('123@chatroom', '456@chatroom'),
                     require_native_mention=False)
    runtime = Runtime(config, FakeGateway())
    admin = AdminService(config)
    first = admin.execute({'action': 'qa_save', 'question': ' 你是谁 ', 'replies': ['我是群里的机器人']})['item']
    assert first['question'] == '你是谁' and first['reply_count'] == 1
    greeting = admin.execute({'action': 'qa_save', 'question': '你好', 'replies': ['你好呀\n今天怎么样']})['item']
    assert admin.execute({'action': 'qa_list', 'search': '你是谁'})['items'] == [first]
    # Reconstruct both services to read the same persistent mapping.
    runtime = Runtime(config, FakeGateway())
    admin = AdminService(config)
    assert admin.execute({'action': 'qa_list'})['total'] == 2
    for identifier, changes in (
        (1, {'mentioned_ids': ()}),
        (2, {'chat_id': 'outside@chatroom'}),
        (3, {'account_id': 'wxid_another'}),
        (4, {'chat_type': 'private', 'chat_id': 'wxid_owner', 'sender': 'wxid_owner', 'mentioned_ids': ()}),
    ):
        runtime.receive(event(identifier, '你是谁', **changes))
    assert rows(runtime, 'inbox') == []  # Hidden Q&A still requires an actual native @.
    process(runtime, event(5, '你是谁'))
    assert text(runtime) == '我是群里的机器人'
    process(runtime, event(6, '你好', chat_id='456@chatroom'))
    assert text(runtime) == '你好呀\n今天怎么样'
    process(runtime, event(7, '你好！'))
    assert text(runtime) == '我没听懂哦~\n试试@我发送“帮助”吧'
    process(runtime, event(8, '帮助'))
    assert text(runtime).splitlines()[0] == '@我 后输入'
    assert '你是谁' not in text(runtime) and '你好' not in text(runtime)
    # Editing is visible to the already-running router; it is not a process cache.
    admin.execute({'action': 'qa_save', 'id': first['id'], 'question': '你是谁', 'replies': ['改过的回复']})
    process(runtime, event(9, '你是谁'))
    assert text(runtime) == '改过的回复'
    assert admin.execute({'action': 'qa_list'})['total'] == 2
    admin.execute({'action': 'qa_delete', 'id': greeting['id']})
    process(runtime, event(10, '你好'))
    assert text(runtime) == '我没听懂哦~\n试试@我发送“帮助”吧'
    with pytest.raises(ValueError, match='已经存在'):
        admin.execute({'action': 'qa_save', 'question': '你是谁', 'replies': ['重复问题']})
    for builtin in ('帮助', '今日zxj', '猜词 3', '我猜是apple', '添加表情包', '暂停群功能', '登记群聊 ABCDEF123456'):
        with pytest.raises(ValueError, match='内置指令'):
            admin.execute({'action': 'qa_save', 'question': builtin, 'replies': ['不能覆盖']})
    with pytest.raises(ValueError, match='UTF-8'):
        admin.execute({'action': 'qa_save', 'id': first['id'], 'question': '你是谁', 'replies': ['字' * 234]})
    assert admin.execute({'action': 'qa_list'})['items'][0]['replies'] == ['改过的回复']
    # Existing pause and cooldown continue to gate hidden replies.
    process(runtime, event(11, '暂停群功能', chat_type='private', chat_id='wxid_owner',
                           sender='wxid_owner', mentioned_ids=()))
    before = len(rows(runtime, 'outbox'))
    process(runtime, event(12, '你是谁'))
    assert len(rows(runtime, 'outbox')) == before
    process(runtime, event(13, '恢复群功能', chat_type='private', chat_id='wxid_owner',
                           sender='wxid_owner', mentioned_ids=()))
    limited = Runtime(replace(config, per_user_cooldown_seconds=10), FakeGateway())
    before = len(rows(limited, 'outbox'))
    process(limited, event(14, '你是谁'))
    assert len(rows(limited, 'outbox')) == before


def test_random_reply_is_persisted_once_across_send_failure_and_restart(tmp_path, monkeypatch):
    gateway = FakeGateway([SendResult('failed', 'not submitted', True), SendResult('accepted')])
    runtime = setup(tmp_path, gateway=gateway)
    admin = AdminService(runtime.config)
    item = admin.execute({'action': 'qa_save', 'question': '你好', 'replies': ['早上好', '你好呀\n很高兴见到你']})['item']
    selected = []

    def choose(values):
        selected.append(tuple(values))
        return values[-1]

    monkeypatch.setattr(qa.secrets, 'choice', choose)
    message = event(1, '你好')
    process(runtime, message)
    saved = json.loads(rows(runtime, 'outbox')[0]['payload'])
    assert saved['text'] == '你好呀\n很高兴见到你' and len(selected) == 1
    admin.execute({'action': 'qa_save', 'id': item['id'], 'question': '你好', 'replies': ['新的候选']})
    clock = time.time()
    assert runtime.send_one(now=clock)
    assert rows(runtime, 'outbox')[0]['state'] == 'pending'
    restarted = Runtime(runtime.config, gateway)
    restarted.store.recover()
    restarted.receive(message)  # Dedup across restart must not pick another reply.
    assert not restarted.router.process_one()
    assert restarted.send_one(now=clock + 5)
    assert [outgoing.text for outgoing in gateway.sent] == [saved['text'], saved['text']]
    assert len(selected) == 1 and rows(restarted, 'outbox')[0]['state'] == 'accepted'
    process(restarted, event(2, '你好'))
    assert text(restarted) == '新的候选' and len(selected) == 2
