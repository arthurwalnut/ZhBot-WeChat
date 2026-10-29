"""Three integration scenarios using synthetic native fields, never live WeChat."""
from dataclasses import replace
import json
from pathlib import Path
import time

from PIL import Image
import pytest

from wechat_bot.config import Config
from wechat_bot.gateway import Event, GatewayError, SendResult
from wechat_bot.runtime import Runtime


class FakeGateway:
    connection_id = "synthetic-connection"

    def __init__(self, results=()):
        self.sent = []
        self.results = list(results)

    def send(self, outgoing):
        self.sent.append(outgoing)
        return self.results.pop(0) if self.results else SendResult("accepted", "synthetic submission")

    def health(self):
        return {"connected": True, "synthetic": True}


def setup(tmp_path, *, stickers=False, gateway=None):
    config = Config(account_id="wxid_robot", owner_id="wxid_owner", group_allowlist=("123@chatroom",),
                    data_dir=tmp_path, wechat_pid=123, per_user_cooldown_seconds=0, stickers=stickers)
    return Runtime(config, gateway or FakeGateway())


def event(identifier, text="随机zxj", sender="wxid_alice", **changes):
    original = Event(account_id="wxid_robot", chat_id="123@chatroom", chat_type="group",
        sender_id=sender, native_message_id=str(identifier), received_at=time.time(), message_type="text",
        text=text if changes.get("chat_type") == "private" else "@测试机器人\u2005" + text,
        mentioned_ids=("wxid_robot",), connection_id="synthetic-connection")
    return replace(original, **changes)


def rows(runtime, table):
    with runtime.store.transaction() as connection:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def process(runtime, value):
    runtime.receive(value)
    assert runtime.router.process_one(Event)


def test_identity_native_mentions_scope_and_owner_management(tmp_path):
    runtime = setup(tmp_path, stickers=True)
    first = event(1, sender_display_name="同名成员")
    process(runtime, first)
    process(runtime, event(2, sender="wxid_bob", sender_display_name="同名成员"))
    process(runtime, event(3, sender_display_name="改名后的成员"))
    draws = rows(runtime, "draws")
    assert {item["user_id"] for item in draws} == {"wxid_alice", "wxid_bob"}
    assert len(draws) == 2
    replies = rows(runtime, "outbox")
    assert json.loads(replies[0]["payload"])["text"] == json.loads(replies[2]["payload"])["text"]
    saved = next(item for item in draws if item['user_id'] == 'wxid_alice')
    from datetime import datetime
    date = datetime.strptime(saved['business_date'], '%Y-%m-%d').strftime('%y.%m.%d')
    assert json.loads(replies[0]['payload'])['text'] == f"今天（{date}）\n你的zxj是“{saved['result']}”"
    for value in (
        event(4, mentioned_ids=()),  # Visible @ text has no native mention.
        event(5, chat_id="other@chatroom"),
        event(6, is_self=True),
        event(7, sender_id=""),
        event(8, native_message_id=""),
        event(9, account_id="wxid_other"),
        event(10, message_type="app", text="<refermsg>随机zxj</refermsg>"),
        event(11, text="引用：随机zxj"),
        event(12, text="暂停群功能", chat_type="private", chat_id="wxid_bob", sender="wxid_bob"),
    ):
        runtime.receive(value)
    assert len(rows(runtime, "inbox")) == 4 and len(rows(runtime, "draws")) == 2
    assert runtime.router.process_one(Event)  # Explicitly mentioned unknown text gets help.
    assert '帮助' in json.loads(rows(runtime,"outbox")[-1]['payload'])['text']
    private = dict(chat_type="private", chat_id="wxid_owner", sender_id="wxid_owner", mentioned_ids=())
    process(runtime, event(13, text="暂停群功能", **private))
    assert not runtime.receive_error  # Stickers enabled must not treat private IDs as a group.
    process(runtime, event(14, sender="wxid_carol"))
    assert len(rows(runtime, "draws")) == 2
    process(runtime, event(15, text="恢复群功能", **private))
    process(runtime, event(16, sender="wxid_carol"))
    assert len(rows(runtime, "draws")) == 3
    process(runtime, event(17, text=''))
    assert '帮助' in json.loads(rows(runtime,"outbox")[-1]['payload'])['text']
    process(runtime, event(18, text='我的zxj'))
    assert f"{date}：{saved['result']}" in json.loads(rows(runtime,'outbox')[-1]['payload'])['text']
    assert all(item["chat_id"] in {"123@chatroom", "wxid_owner"} for item in rows(runtime, "outbox"))
    assert all('。' not in json.loads(item['payload']).get('text', '') for item in rows(runtime, 'outbox'))


def test_atomic_effects_dedup_send_failures_and_uncertain_restart(tmp_path):
    gateway = FakeGateway([SendResult("failed", "not submitted", True), SendResult("accepted")])
    runtime = setup(tmp_path, gateway=gateway)
    value = event(1)
    runtime.receive(value)
    runtime.receive(value)
    assert len(rows(runtime, "inbox")) == 1
    def crash():
        raise RuntimeError("crash before business/inbox/outbox commit")
    with pytest.raises(RuntimeError):
        runtime.router.process_one(Event, before_commit=crash)
    assert rows(runtime, "draws") == [] and rows(runtime, "outbox") == []
    assert rows(runtime, "inbox")[0]["state"] == "pending"
    assert runtime.router.process_one(Event)
    saved = rows(runtime, "draws")[0]
    reply = json.loads(rows(runtime, "outbox")[0]["payload"])
    clock = time.time()
    assert runtime.send_one(now=clock)
    assert rows(runtime, "outbox")[0]["state"] == "pending"
    # Restart after committed effects; only the unsent saved reply is retried.
    restarted = Runtime(runtime.config, gateway)
    restarted.store.recover()
    restarted.receive(value)
    assert not restarted.router.process_one(Event)
    assert restarted.send_one(now=clock + 5)
    assert rows(restarted, "draws") == [saved]
    assert gateway.sent[0].text == gateway.sent[1].text == reply["text"]
    assert rows(restarted, "outbox")[0]["state"] == "accepted"
    process(restarted, event(2, sender="wxid_bob"))
    with restarted.store.transaction() as connection:
        connection.execute("UPDATE outbox SET state='sending' WHERE id=2")
    restarted = Runtime(runtime.config, gateway)
    restarted.store.recover()
    assert rows(restarted, "outbox")[1]["state"] == "uncertain"
    assert not restarted.send_one(now=clock + 10)
    process(restarted, event(3, sender="wxid_carol"))
    gateway.results.append(SendResult("uncertain", "native submission timed out"))
    assert restarted.send_one(now=clock + 10)
    assert rows(restarted, "outbox")[2]["state"] == "uncertain"
    assert not restarted.send_one(now=clock + 20)
    assert len(gateway.sent) == 3 and len(rows(restarted, "draws")) == 3
    # Expired commands cause no game/draw effect.
    restarted.receive(event(4, sender="wxid_expired", received_at=clock - 1000))
    assert restarted.router.process_one(Event, now=clock)
    assert rows(restarted, "inbox")[-1]["state"] == "expired"
    assert len(rows(restarted, "draws")) == 3


def test_multiplayer_game_snapshots_png_targets_and_persistent_sticker_channel(tmp_path):
    gateway = FakeGateway()
    runtime = setup(tmp_path, stickers=True, gateway=gateway)
    runtime.router.game.answer_picker = lambda _: "apple"
    process(runtime, event(1, "猜词"))
    for identifier, malformed in ((100,"我猜是"),(101,"我猜是 apple extra")):
        process(runtime,event(identifier,malformed))
        assert rows(runtime,"guesses") == []
        assert '格式：我猜是 apple' in json.loads(rows(runtime,"outbox")[-1]['payload'])['text']
    process(runtime, event(2, "我猜是 alley"))
    # A second member can continue the same persisted game after process restart.
    runtime = Runtime(runtime.config, gateway)
    winner = event(3, "我猜是apple", sender="wxid_bob")
    process(runtime, winner)
    runtime.receive(winner)
    assert not runtime.router.process_one(Event)
    process(runtime, event(4, "猜词战绩", sender="wxid_bob"))
    process(runtime, event(5, "随机zxj"))
    process(runtime, event(6, "随机zxj", sender="wxid_bob"))
    payloads = [json.loads(item["payload"]) for item in rows(runtime, "outbox")]
    boards = [item["board"] for item in payloads if item["kind"] == "image"]
    assert [len(board["guesses"]) for board in boards] == [0, 1, 2]
    assert [board["status"] for board in boards] == ["active", "active", "won"]
    assert "answer" not in boards[0] and "answer" not in boards[1]
    assert boards[2]["winner_id"] == "wxid_bob"
    assert len(rows(runtime, "guesses")) == 2
    assert runtime.router.game.stats("wxid_bob", "123@chatroom")["wins"] == 1
    while runtime.send_one():
        pass
    images = [outgoing for outgoing in gateway.sent if outgoing.kind == "image"]
    assert len(images) == 3 and len({item.path for item in images}) == 3
    for item in images:
        with Image.open(item.path) as png:
            assert png.format == "PNG"
            png.load()
    assert len({Path(item.path).read_bytes() for item in images}) == 3
    assert all(item.account_id == "wxid_robot" and item.chat_id == "123@chatroom" for item in gateway.sent)
    assert all(item.mentioned_ids in (("wxid_alice",), ("wxid_bob",)) for item in gateway.sent if item.kind == "text")

    # Explicit upload uses the actual runtime/router chain; fake download is
    # confined to this test and the reply must select native sticker, not image.
    from io import BytesIO
    gif = BytesIO()
    Image.new("RGB", (8, 8), "red").save(gif, format="GIF")
    process(runtime, event(7, "添加表情包"))
    assert '30 秒' in json.loads(rows(runtime, 'outbox')[-1]['payload'])['text']
    runtime.receive(event(8, message_type="sticker", text="", mentioned_ids=()))
    # Simulate downtime longer than the ordinary command TTL, preserving the
    # already accepted upload's original arrival within its 30-second wait.
    with runtime.store.transaction() as connection:
        accepted = connection.execute("SELECT id,payload FROM inbox WHERE native_message_id='8'").fetchone()
        payload = json.loads(accepted['payload'])
        payload['received_at'] -= 1000
        for name in ('received_at','wait_started_at','wait_expires_at'):
            payload['sticker_intent'][name] -= 1000
        connection.execute('UPDATE inbox SET received_at=?,payload=? WHERE id=?',
                           (payload['received_at'],json.dumps(payload),accepted['id']))
    # The receive intent has committed, but no bytes have been downloaded. A
    # subsequent connection must resume the same upload with fresh ownership.
    gateway = FakeGateway()
    gateway.connection_id = "new-synthetic-connection"
    def fetch(upload):
        assert upload.connection_id == gateway.connection_id
        assert upload.account_id == "wxid_robot" and upload.chat_id == "123@chatroom"
        assert time.time()-upload.received_at > runtime.config.max_command_age_seconds
        return {"data": gif.getvalue(), "source_format": "GIF", "note": "仅保留在记录中的资源说明"}
    gateway.fetch_sticker = fetch
    runtime = Runtime(runtime.config, gateway)
    assert runtime.process_one()
    assert json.loads(rows(runtime, 'outbox')[-1]['payload'])['text'] == '表情编号1：添加成功'
    assert rows(runtime, 'stickers')[0]['note'] == '仅保留在记录中的资源说明'
    runtime = Runtime(runtime.config, gateway)
    process(runtime, event(9, "随机表情包", sender="wxid_bob"))
    while runtime.send_one():
        pass
    native = [item for item in gateway.sent if item.kind == "sticker"]
    assert len(native) == 1 and Path(native[0].path).read_bytes() == gif.getvalue()
    assert native[0].chat_id == "123@chatroom"

    # Safe media reasons reach the reply; arbitrary exception payloads do not.
    for identifier, failure, expected in (
        (10, GatewayError('MEDIA_UNSUPPORTED','WXGF 尚未启用转换；不改变原动画播放时长'), 'WXGF 尚未启用转换'),
        (12, GatewayError('MEDIA_DOWNLOAD_FAILED','表情包内容校验失败或连接已结束'), '表情包内容校验失败'),
        (14, GatewayError('MEDIA_UNSUPPORTED','https://cdn.invalid/?token=secret <xml>secret</xml>'), 'GatewayError'),
    ):
        process(runtime,event(identifier,'添加表情包'))
        runtime.receive(event(identifier+1,message_type='sticker',text='',mentioned_ids=()))
        def failed_fetch(_):
            raise failure
        gateway.fetch_sticker = failed_fetch
        assert runtime.process_one()
        response = json.loads(rows(runtime,'outbox')[-1]['payload'])['text']
        assert expected in response and 'secret' not in response and 'https:' not in response and '<xml>' not in response
        assert len(rows(runtime,'stickers')) == 1

    # A selected, downloaded original survives conversion failure for diagnosis,
    # without creating a random-sendable library entry or leaking its metadata.
    failure = GatewayError('MEDIA_UNSUPPORTED', '该原生表情原件格式尚未支持')
    failure.source_data = b'unsupported-synthetic-format'
    failure.media_diagnostic = {'bytes': len(failure.source_data), 'format': 'UNKNOWN'}
    process(runtime, event(16, '添加表情包'))
    runtime.receive(event(17, message_type='sticker', text='', mentioned_ids=()))
    def unsupported_fetch(_):
        raise failure
    gateway.fetch_sticker = unsupported_fetch
    assert runtime.process_one()
    archived = list((runtime.stickers.directory / 'unprocessed').glob('*.bin'))
    assert len(archived) == 1 and archived[0].read_bytes() == failure.source_data
    assert len(rows(runtime, 'stickers')) == 1
