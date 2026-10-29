"""One combined scenario for explicit uploads, transaction failure and restart."""
from io import BytesIO
import json
from pathlib import Path
import sqlite3

from PIL import Image
import pytest

from wechat_bot.stickers import StickerError, StickerService


def test_member_upload_isolation_and_persistent_native_resources(tmp_path, monkeypatch):
    service = StickerService(tmp_path)
    connection = sqlite3.connect(tmp_path / "bot.sqlite3")
    connection.row_factory = sqlite3.Row
    service.initialize(connection)
    connection.execute("CREATE TABLE upload_inbox (id TEXT PRIMARY KEY, intent TEXT NOT NULL)")
    connection.commit()
    scope = {"account_id": "wxid_robot", "chat_id": "123@chatroom"}
    alice, bob = {**scope, "sender_id": "wxid_alice"}, {**scope, "sender_id": "wxid_bob"}
    with connection:
        service.begin_wait(connection, **alice, received_at=100)
        service.begin_wait(connection, **bob, received_at=101)
    # A's ordinary image/text neither consumes B's wait nor enters the library.
    for kind in ("image", "text"):
        assert service.claim(connection, **alice, native_message_id="1", received_at=102, message_type=kind) is None
    assert service.waiting(connection, **alice, received_at=103)
    assert service.waiting(connection, **bob, received_at=103)
    assert service.claim(connection, **{**alice, "chat_id": "456@chatroom"},
                         native_message_id="2", received_at=103, message_type="sticker") is None
    assert service.claim(connection, **{**alice, "sender_id": "wxid_carol"},
                         native_message_id="2", received_at=103, message_type="sticker") is None
    assert service.claim(connection, **alice, native_message_id="2", received_at=99, message_type="sticker") is None
    # Consumption and inbox persistence roll back together.
    with pytest.raises(RuntimeError), connection:
        service.claim(connection, **alice, native_message_id="3", received_at=104, message_type="sticker")
        raise RuntimeError("inbox insertion failed")
    assert service.waiting(connection, **alice, received_at=105)
    with connection:
        intent = service.claim(connection, **alice, native_message_id="4", received_at=105, message_type="sticker")
        connection.execute("INSERT INTO upload_inbox VALUES (?, ?)", ("4", json.dumps(intent)))
    assert service.waiting(connection, **alice, received_at=106) is None
    # Restart cancels unmatched B but keeps A's accepted intent in inbox.
    service = StickerService(tmp_path)
    service.initialize(connection)
    assert service.waiting(connection, **bob, received_at=106) is None
    intent = json.loads(connection.execute("SELECT intent FROM upload_inbox WHERE id='4'").fetchone()[0])
    gif = BytesIO()
    Image.new("RGB", (8, 8), "red").save(gif, format="GIF", save_all=True,
        append_images=[Image.new("RGB", (8, 8), "blue")], duration=[100, 200], loop=0)
    prepared = service.prepare(gif.getvalue())
    path = Path(prepared["path"])
    assert path.read_bytes() == gif.getvalue() and prepared["frames"] == 2
    png = BytesIO()
    Image.new("RGB", (8, 8), "red").save(png, format="PNG")
    with pytest.raises(StickerError):
        service.prepare(png.getvalue())
    with pytest.raises(StickerError):
        service.prepare(gif.getvalue()[:-1])
    # Failed business commit leaves no library entry/success; durable bytes stay.
    with pytest.raises(RuntimeError), connection:
        service.add(connection, intent, prepared)
        raise RuntimeError("outbox insertion failed")
    assert service.random(connection, **scope) is None and path.exists()
    with connection:
        first = service.add(connection, intent, prepared)
    assert not first["is_duplicate"] and first["sender_id"] == "wxid_alice"
    with connection:
        service.begin_wait(connection, **bob, received_at=200)
        bob_intent = service.claim(connection, **bob, native_message_id="5", received_at=201, message_type="sticker")
        duplicate = service.add(connection, bob_intent, prepared)
    assert duplicate["is_duplicate"] and duplicate["id"] == first["id"]
    assert duplicate["sender_id"] == "wxid_alice"
    assert service.list(connection, **bob)["total"] == 0
    assert service.list(connection, **alice)["total"] == 1
    with connection:
        service.begin_wait(connection, **bob, received_at=300)
    assert service.claim(connection, **bob, native_message_id="6", received_at=361, message_type="sticker") is None
    with connection:
        service.begin_wait(connection, **bob, received_at=400)
        assert service.cancel_wait(connection, **bob)
    assert service.waiting(connection, **bob, received_at=401) is None
    # Failure before rename never creates a persistent library success or temp leak.
    other = BytesIO()
    Image.new("RGB", (8, 8), "green").save(other, format="GIF")
    with monkeypatch.context() as patch:
        def fail_replace(*args):
            raise OSError("disk failure")
        patch.setattr("wechat_bot.stickers.os.replace", fail_replace)
        with pytest.raises(OSError):
            service.prepare(other.getvalue())
    assert not list(service.directory.glob(".upload-*.tmp"))
    connection.close()
    connection = sqlite3.connect(tmp_path / "bot.sqlite3")
    connection.row_factory = sqlite3.Row
    restarted = StickerService(tmp_path)
    item = restarted.random(connection, **scope)
    assert item["id"] == first["id"] and Path(item["path"]).read_bytes() == gif.getvalue()
    with pytest.raises(StickerError):
        restarted.delete(connection, **bob, sticker_id=item["id"])
    with connection:
        restarted.delete(connection, **bob, sticker_id=item["id"], owner_id="wxid_bob")
    assert restarted.random(connection, **scope) is None
    assert restarted.list(connection, **alice)["total"] == 0
    assert path.exists()  # Sending/uncertain outbox references may still need it.
    connection.close()
