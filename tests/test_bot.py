"""Three integration scenarios using synthetic native fields, never live WeChat."""
from dataclasses import replace
import json
from pathlib import Path
import time

from PIL import Image
import pytest

from wechat_bot.config import Config
from wechat_bot.gateway import Event, SendResult
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
    assert len(rows(runtime, "inbox")) == 3 and len(rows(runtime, "draws")) == 2
    private = dict(chat_type="private", chat_id="wxid_owner", sender_id="wxid_owner", mentioned_ids=())
    process(runtime, event(13, text="暂停群功能", **private))
    assert not runtime.receive_error  # Stickers enabled must not treat private IDs as a group.
    process(runtime, event(14, sender="wxid_carol"))
    assert len(rows(runtime, "draws")) == 2
    process(runtime, event(15, text="恢复群功能", **private))
    process(runtime, event(16, sender="wxid_carol"))
    assert len(rows(runtime, "draws")) == 3
    assert all(item["chat_id"] in {"123@chatroom", "wxid_owner"} for item in rows(runtime, "outbox"))


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
    process(runtime, event(2, "我猜是 alley"))
    # A second member can continue the same persisted game after process restart.
    runtime = Runtime(runtime.config, gateway)
    winner = event(3, "我猜是 apple", sender="wxid_bob")
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
    runtime.receive(event(8, message_type="sticker", text="", mentioned_ids=()))
    # The receive intent has committed, but no bytes have been downloaded. A
    # subsequent connection must resume the same upload with fresh ownership.
    gateway = FakeGateway()
    gateway.connection_id = "new-synthetic-connection"
    def fetch(upload):
        assert upload.connection_id == gateway.connection_id
        assert upload.account_id == "wxid_robot" and upload.chat_id == "123@chatroom"
        return {"data": gif.getvalue(), "source_format": "GIF"}
    gateway.fetch_sticker = fetch
    runtime = Runtime(runtime.config, gateway)
    assert runtime.process_one()
    runtime = Runtime(runtime.config, gateway)
    process(runtime, event(9, "随机表情包", sender="wxid_bob"))
    while runtime.send_one():
        pass
    native = [item for item in gateway.sent if item.kind == "sticker"]
    assert len(native) == 1 and Path(native[0].path).read_bytes() == gif.getvalue()
    assert native[0].chat_id == "123@chatroom"
