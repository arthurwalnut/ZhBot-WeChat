"""One combined scenario for explicit uploads, transaction failure and restart."""
from io import BytesIO
from hashlib import sha256
import json
from pathlib import Path
import random
import sqlite3

from PIL import GifImagePlugin, Image
import pytest

from wechat_bot.stickers import StickerError, StickerService
from wechat_bot.sticker_media import convert_sticker


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
    assert service.waiting(connection, **bob, received_at=330)
    assert service.claim(connection, **bob, native_message_id="6", received_at=331, message_type="sticker") is None
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
    assert item["id"] == first["id"] and restarted.resolve_path(item).read_bytes() == gif.getvalue()
    with pytest.raises(StickerError):
        restarted.delete_with_pending(connection, **bob, sticker_id=item["id"])
    with connection:
        restarted.delete_with_pending(connection, **bob, sticker_id=item["id"], owner_id="wxid_bob")
    assert restarted.random(connection, **scope) is None
    assert restarted.list(connection, **alice)["total"] == 0
    assert connection.execute("SELECT 1 FROM sqlite_master WHERE name='outbox'").fetchone() is None
    assert path.exists()  # Sending/uncertain outbox references may still need it.
    connection.close()


def test_common_formats_and_large_gif_keep_animation_timing():
    # Decode real samples in the installed Pillow build, without relying on
    # filename extensions or only checking that a codec has been registered.
    for kind in ('JPEG', 'WEBP', 'BMP'):
        original = BytesIO()
        Image.new('RGB', (5000, 20), 'red').save(original, format=kind)
        converted = convert_sticker(original.getvalue())
        assert converted['source_format'] == kind and converted['converted']
        with Image.open(BytesIO(converted['data'])) as image:
            assert image.format == 'GIF' and image.size == (1024, 4)
            assert image.n_frames == 1

    def gif_frames(pictures, durations, loop):
        # Explicit fixture frames include repeated images with distinct times;
        # Image.save(save_all=True) would otherwise merge that test case.
        output = BytesIO()
        options = {'optimize': False}
        if loop is not None:
            options['loop'] = loop
        header, _ = GifImagePlugin.getheader(pictures[0], info=options)
        for block in header:
            output.write(block)
        for index, picture in enumerate(pictures):
            for block in GifImagePlugin.getdata(picture, duration=durations[index],
                    disposal=2, include_color_table=index > 0):
                output.write(block)
        output.write(b';')
        return output.getvalue()

    red = Image.new('RGB', (1200, 50), 'red').quantize()
    blue = Image.new('RGB', (1200, 50), 'blue').quantize()
    for loop in (None, 0, 2):
        original = gif_frames([red, blue, blue], [70, 130, 230], loop)
        result = convert_sticker(original)
        assert result['source_format'] == 'GIF' and result['converted']
        assert len(result['data']) <= 1024 * 1024
        with Image.open(BytesIO(result['data'])) as image:
            assert image.size == (1024, 42) and image.n_frames == 3
            assert image.info.get('loop') == loop
            for index, (duration, color) in enumerate(zip((70, 130, 230), ('red', 'blue', 'blue'))):
                image.seek(index)
                assert image.info['duration'] == duration
                assert image.convert('RGB').getpixel((50, 20)) == Image.new('RGB', (1, 1), color).getpixel((0, 0))
        # A subsequent request preserves this now-sendable encoded GIF exactly.
        passthrough = convert_sticker(result['data'])
        assert passthrough['data'] == result['data'] and not passthrough['converted']

    noise = Image.frombytes('L', (1024, 1024), random.Random(7).randbytes(1024 * 1024)).convert('P')
    original = gif_frames([noise, noise], [40, 90], 3)
    assert len(original) > 1024 * 1024
    result = convert_sticker(original)
    assert len(result['data']) <= 1024 * 1024 and result['width'] < 1024
    with Image.open(BytesIO(result['data'])) as image:
        assert image.n_frames == 2 and image.info.get('loop') == 3
        assert image.info['duration'] == 40
        image.seek(1)
        assert image.info['duration'] == 90

    # The source can exceed the former 64 Mi decoded-pixel ceiling. The
    # sendable copy meets the unchanged SDK ceiling without discarding frames.
    large_frame = Image.new('RGB', (1024, 1024), 'green').quantize()
    original = gif_frames([large_frame] * 80, [20] * 80, None)
    result = convert_sticker(original)
    assert result['converted'] and result['frames'] == 80
    assert result['width'] * result['height'] * result['frames'] <= 64 * 1024 * 1024
    with Image.open(BytesIO(result['data'])) as image:
        assert image.n_frames == 80 and 'loop' not in image.info
        for index in range(80):
            image.seek(index)
            assert image.info['duration'] == 20
    tiny = Image.new('P', (2, 2))
    with pytest.raises(StickerError, match='超过 300 帧'):
        convert_sticker(gif_frames([tiny] * 301, [20] * 301, None))

    oversized = BytesIO()
    Image.new('RGB', (8193, 1), 'red').save(oversized, format='PNG')
    with pytest.raises(StickerError, match='8192'):
        convert_sticker(oversized.getvalue())
    with pytest.raises(StickerError, match='完整解码'):
        convert_sticker(b'not an image')


def test_png_quality_limits_and_original_dedup_migration(tmp_path):
    # A 256-level image must not take the previous 32-color conversion path.
    picture = Image.frombytes("L", (256, 1), bytes(range(256))).convert("RGB")
    png = BytesIO()
    picture.save(png, format="PNG")
    original = png.getvalue()
    conversion = convert_sticker(original)
    payload, note = conversion['data'], conversion['note']
    with Image.open(BytesIO(payload)) as result:
        assert result.size == picture.size and len(result.getcolors()) == 256
        assert result.convert("RGB").tobytes() == picture.tobytes()

    transparent = Image.new("RGBA", (2, 1), (255, 0, 0, 0))
    transparent.putpixel((1, 0), (0, 255, 0, 255))
    buffer = BytesIO()
    transparent.save(buffer, format="PNG")
    converted = convert_sticker(buffer.getvalue())['data']
    with Image.open(BytesIO(converted)) as result:
        assert result.convert("RGBA").getpixel((0, 0))[3] == 0
        assert result.convert("RGBA").getpixel((1, 0)) == (0, 255, 0, 255)

    # Independently exercise dimension and encoded-size limits, preserving
    # proportional geometry while avoiding an unconditional 32-color fallback.
    for picture in (Image.new("RGB", (2048, 512), "red"),
                    Image.frombytes("L", (1024, 1024), random.Random(1).randbytes(1024 * 1024))):
        buffer = BytesIO()
        picture.save(buffer, format="PNG")
        conversion = convert_sticker(buffer.getvalue())
        converted, resized_note = conversion['data'], conversion['note']
        with Image.open(BytesIO(converted)) as result:
            assert max(result.size) <= 1024 and len(converted) <= 1024 * 1024
            assert result.size != picture.size and "缩至" in resized_note
            assert abs(result.width / result.height - picture.width / picture.height) < 0.01
    animation = BytesIO()
    Image.new("RGB", (8, 8), "red").save(animation, format="PNG", save_all=True,
        append_images=[Image.new("RGB", (8, 8), "blue")], duration=[100, 200], loop=0)
    with pytest.raises(StickerError, match="动态 PNG"):
        convert_sticker(animation.getvalue())
    with pytest.raises(StickerError, match="连接已结束"):
        convert_sticker(original, lambda: False)

    # Start from the exact pre-originals column layout. Migration adds metadata
    # without replacing a legacy sender, media file, digest or row identifier.
    service = StickerService(tmp_path)
    connection = sqlite3.connect(tmp_path / "bot.sqlite3")
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE stickers (
        id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, chat_id TEXT NOT NULL,
        sender_id TEXT NOT NULL, native_message_id TEXT NOT NULL, created_at REAL NOT NULL,
        digest TEXT NOT NULL, path TEXT NOT NULL, bytes INTEGER NOT NULL,
        width INTEGER NOT NULL, height INTEGER NOT NULL, frames INTEGER NOT NULL,
        format TEXT NOT NULL, source_format TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
        deleted INTEGER NOT NULL DEFAULT 0, UNIQUE(account_id,chat_id,native_message_id))""")
    old_gif = BytesIO()
    Image.new("RGB", (8, 8), "red").save(old_gif, format="GIF")
    old_digest = sha256(old_gif.getvalue()).hexdigest()
    old_path = service.directory / (old_digest + ".gif")
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(old_gif.getvalue())
    connection.execute("""INSERT INTO stickers VALUES
        (1,'wxid_robot','123@chatroom','wxid_alice','10',100,?,?,?,8,8,1,'GIF','PNG','old',0)""",
        (old_digest, str(old_path), len(old_gif.getvalue())))
    connection.commit()
    original_row = tuple(connection.execute("SELECT * FROM stickers WHERE id=1").fetchone())
    with connection:
        service.initialize(connection)
    old = connection.execute("SELECT * FROM stickers WHERE id=1").fetchone()
    assert tuple(old)[:len(original_row)] == original_row and old['origin'] == 'wechat'
    assert old["source_digest"] is None and old["source_path"] is None
    scope = {"account_id": "wxid_robot", "chat_id": "123@chatroom", "sender_id": "wxid_bob"}
    prepared = service.prepare(payload, source_format="PNG", source_data=original,
                               note=note, legacy_digest=old_digest)
    assert Path(prepared["source_path"]).read_bytes() == original
    with connection:
        service.begin_wait(connection, **scope, received_at=200)
        intent = service.claim(connection, **scope, native_message_id="11", received_at=201, message_type="sticker")
        duplicate = service.add(connection, intent, prepared)
    assert duplicate["is_duplicate"] and duplicate["id"] == 1
    assert duplicate["sender_id"] == "wxid_alice" and duplicate["path"] == str(old_path)
    assert duplicate["digest"] == old_digest and old_path.read_bytes() == old_gif.getvalue()
    assert duplicate["source_digest"] == sha256(original).hexdigest()
    # A later encoder change can produce different GIF bytes. Source identity
    # still blocks a new entry, without requiring the legacy-digest hint again.
    prepared.pop("legacy_digest")
    with connection:
        service.begin_wait(connection, **scope, received_at=300)
        intent = service.claim(connection, **scope, native_message_id="12", received_at=301, message_type="sticker")
        duplicate = service.add(connection, intent, prepared)
    assert duplicate["is_duplicate"] and connection.execute("SELECT COUNT(*) FROM stickers").fetchone()[0] == 1
    connection.close()
