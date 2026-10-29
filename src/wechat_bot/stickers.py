"""Explicit member uploads and a persistent native-GIF library.

Database methods use the caller's transaction and never commit. Resource bytes
are obtained by the gateway only after a wait is claimed; this module never
scans WeChat caches or downloads arbitrary user-supplied URLs.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import math
import os
from pathlib import Path
import secrets
import tempfile
import uuid
import warnings

from PIL import Image


MAX_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_DIMENSION = 1024
MAX_FRAMES = 300
MAX_PIXELS = 64 * 1024 * 1024
WAIT_SECONDS = 30


class StickerError(ValueError):
    pass


def _identity(account_id, chat_id, sender_id):
    if any(not isinstance(value, str) or not value or len(value) > 128
           or any(ord(char) < 32 for char in value)
           for value in (account_id, chat_id, sender_id)):
        raise StickerError("表情操作需要可靠的账号、群和成员 ID")
    if not chat_id.endswith("@chatroom"):
        raise StickerError("表情库仅用于已绑定群")


def _timestamp(received_at):
    if isinstance(received_at, bool) or not isinstance(received_at, (int, float)) or not math.isfinite(received_at):
        raise StickerError("表情接收时间无效")
    return float(received_at)


def _gif_info(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise StickerError("表情 GIF 必须非空且不超过 1 MiB")
    if not data.startswith((b"GIF87a", b"GIF89a")) or not data.endswith(b";"):
        raise StickerError("原生表情资源必须是完整 GIF")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as picture:
                width, height = picture.size
                frames = picture.n_frames
                if (picture.format != "GIF" or min(width, height) < 1
                        or max(width, height) > MAX_DIMENSION or not 1 <= frames <= MAX_FRAMES
                        or width * height * frames > MAX_PIXELS):
                    raise StickerError("表情超出 1024 像素、300 帧或累计像素限制")
                for index in range(frames):
                    picture.seek(index)
                    picture.load()
        return {"width": width, "height": height, "frames": frames, "format": "GIF"}
    except StickerError:
        raise
    except Exception:
        raise StickerError("表情 GIF 无法完整解码") from None


class StickerService:
    def __init__(self, data_dir):
        self.directory = Path(data_dir).expanduser().resolve() / "media" / "stickers"
        self.boot_id = uuid.uuid4().hex

    def initialize(self, connection):
        # execute(), not executescript(): preserve a transaction already in progress.
        connection.execute("""CREATE TABLE IF NOT EXISTS sticker_waits (
            account_id TEXT NOT NULL, chat_id TEXT NOT NULL, sender_id TEXT NOT NULL,
            boot_id TEXT NOT NULL, started_at REAL NOT NULL, expires_at REAL NOT NULL,
            PRIMARY KEY (account_id, chat_id, sender_id))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS stickers (
            id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, chat_id TEXT NOT NULL,
            sender_id TEXT NOT NULL, native_message_id TEXT NOT NULL,
            created_at REAL NOT NULL, digest TEXT NOT NULL, path TEXT NOT NULL,
            bytes INTEGER NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
            frames INTEGER NOT NULL, format TEXT NOT NULL, source_format TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '', deleted INTEGER NOT NULL DEFAULT 0,
            UNIQUE (account_id, chat_id, native_message_id))""")
        connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS unique_active_sticker
            ON stickers(account_id, chat_id, digest) WHERE deleted = 0""")
        # Additive migration: existing GIF files, ownership and rows stay intact.
        columns = {row[1] for row in connection.execute("PRAGMA table_info(stickers)")}
        for name, kind in (("source_digest", "TEXT"), ("source_path", "TEXT"), ("source_bytes", "INTEGER")):
            if name not in columns:
                connection.execute(f"ALTER TABLE stickers ADD COLUMN {name} {kind}")
        connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS unique_active_sticker_source
            ON stickers(account_id, chat_id, source_digest)
            WHERE deleted=0 AND source_digest IS NOT NULL""")

    def begin_wait(self, connection, *, account_id, chat_id, sender_id, received_at):
        _identity(account_id, chat_id, sender_id)
        received_at = _timestamp(received_at)
        connection.execute("""INSERT INTO sticker_waits VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, chat_id, sender_id) DO UPDATE SET
            boot_id=excluded.boot_id, started_at=excluded.started_at, expires_at=excluded.expires_at""",
            (account_id, chat_id, sender_id, self.boot_id, received_at, received_at + WAIT_SECONDS))
        return {"expires_at": received_at + WAIT_SECONDS}

    def waiting(self, connection, *, account_id, chat_id, sender_id, received_at):
        _identity(account_id, chat_id, sender_id)
        received_at = _timestamp(received_at)
        row = connection.execute("""SELECT * FROM sticker_waits
            WHERE account_id=? AND chat_id=? AND sender_id=? AND boot_id=?
            AND started_at < ? AND expires_at >= ?""",
            (account_id, chat_id, sender_id, self.boot_id, received_at, received_at)).fetchone()
        return dict(row) if row else None

    def cancel_wait(self, connection, *, account_id, chat_id, sender_id):
        _identity(account_id, chat_id, sender_id)
        return bool(connection.execute("""DELETE FROM sticker_waits
            WHERE account_id=? AND chat_id=? AND sender_id=? AND boot_id=?""",
            (account_id, chat_id, sender_id, self.boot_id)).rowcount)

    def claim(self, connection, *, account_id, chat_id, sender_id,
              native_message_id, received_at, message_type):
        """Return an inbox-serializable intent, consuming only a native sticker.

        Caller must insert that intent and the incoming event into inbox in this
        same transaction. A crash after commit can then resume the upload even
        though unmatched waits from the old process expire on restart.
        """
        waiting = self.waiting(connection, account_id=account_id, chat_id=chat_id,
                               sender_id=sender_id, received_at=received_at)
        if not waiting or message_type != "sticker":
            return None
        if not isinstance(native_message_id, str) or not native_message_id:
            raise StickerError("表情入库需要原生消息 ID")
        self.cancel_wait(connection, account_id=account_id, chat_id=chat_id, sender_id=sender_id)
        return {"account_id": account_id, "chat_id": chat_id, "sender_id": sender_id,
                "native_message_id": native_message_id, "received_at": float(received_at),
                "wait_started_at": waiting["started_at"], "wait_expires_at": waiting["expires_at"]}

    @staticmethod
    def _persist(directory, filename, data):
        directory.mkdir(parents=True, exist_ok=True)
        if directory.resolve() != directory or directory.is_symlink():
            raise StickerError("表情保存目录发生重定向")
        destination = directory / filename
        if destination.exists():
            if destination.is_symlink() or destination.stat().st_size != len(data) or destination.read_bytes() != data:
                raise StickerError("同摘要的现有表情文件内容不一致")
        else:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(prefix=".upload-", suffix=".tmp", dir=directory, delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()  # Only this call's uncommitted temporary file.
        return destination

    def prepare(self, data: bytes, *, source_format="GIF", note="", source_data=None, legacy_digest=None):
        """Validate and atomically persist bytes before opening the business transaction."""
        information = _gif_info(data)
        if source_format not in ("GIF", "PNG", "JPEG", "WEBP", "BMP"):
            raise StickerError("表情原件格式尚未支持")
        if not isinstance(note, str) or len(note) > 500:
            raise StickerError("表情转换说明无效")
        if source_data is None and source_format == "GIF":
            source_data = data
        signatures = {"GIF": (b"GIF87a", b"GIF89a"), "PNG": (b"\x89PNG\r\n\x1a\n",),
                      "JPEG": (b"\xff\xd8\xff",), "WEBP": (b"RIFF",), "BMP": (b"BM",)}
        if (not isinstance(source_data, bytes) or not 0 < len(source_data) <= MAX_SOURCE_BYTES
                or not source_data.startswith(signatures[source_format])):
            raise StickerError("表情原件缺失、格式不符或超过 20 MiB")
        if source_format == "WEBP" and source_data[8:12] != b"WEBP":
            raise StickerError("表情原件缺失、格式不符或超过 20 MiB")
        if legacy_digest is not None and (not isinstance(legacy_digest, str) or len(legacy_digest) != 64
                or any(char not in "0123456789abcdef" for char in legacy_digest)):
            raise StickerError("表情旧版摘要无效")
        digest = sha256(data).hexdigest()
        source_digest = sha256(source_data).hexdigest()
        destination = self._persist(self.directory, digest + ".gif", data)
        source_path = self._persist(self.directory / "originals", source_digest + "." + source_format.lower(), source_data)
        return {**information, "digest": digest, "path": str(destination), "bytes": len(data),
                "source_format": source_format, "note": note, "source_digest": source_digest,
                "source_path": str(source_path), "source_bytes": len(source_data), "legacy_digest": legacy_digest}

    def archive_failed_source(self, data):
        """Keep a fully downloaded, MD5-checked upload for local diagnosis only.

        This creates no library entry and is never selected for sending.
        """
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_SOURCE_BYTES:
            raise StickerError("表情原件缺失、格式不符或超过 20 MiB")
        digest = sha256(data).hexdigest()
        return self._persist(self.directory / "unprocessed", digest + ".bin", data)

    def add(self, connection, intent, prepared):
        _identity(intent["account_id"], intent["chat_id"], intent["sender_id"])
        received_at = _timestamp(intent["received_at"])
        if not intent["wait_started_at"] < received_at <= intent["wait_expires_at"]:
            raise StickerError("表情首次到达时已超出上传等待")
        digest = prepared["digest"]
        path = Path(prepared["path"])
        if path != self.directory / (digest + ".gif") or path.is_symlink() or not path.is_file():
            raise StickerError("表情尚未保存到持久目录")
        # Short local read: do not commit a successful library entry for a missing,
        # substituted, or incomplete file after preparation.
        if path.stat().st_size != prepared["bytes"] or not 0 < prepared["bytes"] <= MAX_BYTES:
            raise StickerError("已保存表情的大小不一致")
        data = path.read_bytes()
        if sha256(data).hexdigest() != digest:
            raise StickerError("已保存表情的摘要不一致")
        source_digest = prepared["source_digest"]
        source_path = Path(prepared["source_path"])
        if (source_path != self.directory / "originals" / (source_digest + "." + prepared["source_format"].lower())
                or source_path.is_symlink() or source_path.parent.is_symlink() or not source_path.is_file()
                or source_path.stat().st_size != prepared["source_bytes"]
                or not 0 < prepared["source_bytes"] <= MAX_SOURCE_BYTES
                or sha256(source_path.read_bytes()).hexdigest() != source_digest):
            raise StickerError("已保存表情原件的路径或摘要不一致")
        existing = connection.execute("""SELECT * FROM stickers
            WHERE account_id=? AND chat_id=? AND
              (((digest IN (?,?) OR source_digest=?) AND deleted=0) OR native_message_id=?)
            ORDER BY CASE WHEN source_digest=? THEN 0 ELSE 1 END,id LIMIT 1""",
            (intent["account_id"], intent["chat_id"], digest, prepared.get("legacy_digest"),
             source_digest, intent["native_message_id"], source_digest)).fetchone()
        if existing:
            if existing["deleted"]:
                raise StickerError("该上传消息对应的条目已删除")
            # A re-upload can supply an original which old versions never kept.
            # Do not replace that entry's sendable GIF, owner or native message.
            if existing["source_digest"] is None and existing["source_format"] == prepared["source_format"]:
                connection.execute("UPDATE stickers SET source_digest=?,source_path=?,source_bytes=? WHERE id=?",
                    (source_digest, str(source_path), prepared["source_bytes"], existing["id"]))
            return {**dict(connection.execute("SELECT * FROM stickers WHERE id=?", (existing["id"],)).fetchone()),
                    "is_duplicate": True}
        fields = ("digest", "path", "bytes", "width", "height", "frames", "format", "source_format", "note",
                  "source_digest", "source_path", "source_bytes")
        cursor = connection.execute("""INSERT INTO stickers
            (account_id,chat_id,sender_id,native_message_id,created_at,
             digest,path,bytes,width,height,frames,format,source_format,note,source_digest,source_path,source_bytes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (intent["account_id"], intent["chat_id"], intent["sender_id"], intent["native_message_id"], received_at,
             *(prepared[name] for name in fields)))
        return {**dict(connection.execute("SELECT * FROM stickers WHERE id=?", (cursor.lastrowid,)).fetchone()),
                "is_duplicate": False}

    def list(self, connection, *, account_id, chat_id, sender_id, page=1):
        _identity(account_id, chat_id, sender_id)
        if type(page) is not int or page < 1:
            raise StickerError("页码必须是正整数")
        arguments = (account_id, chat_id, sender_id)
        total = connection.execute("""SELECT COUNT(*) FROM stickers
            WHERE account_id=? AND chat_id=? AND sender_id=? AND deleted=0""", arguments).fetchone()[0]
        items = [dict(row) for row in connection.execute("""SELECT * FROM stickers
            WHERE account_id=? AND chat_id=? AND sender_id=? AND deleted=0
            ORDER BY id DESC LIMIT 10 OFFSET ?""", (*arguments, (page - 1) * 10))]
        return {"items": items, "page": page, "total": total, "pages": max(1, (total + 9) // 10)}

    def random(self, connection, *, account_id, chat_id):
        rows = connection.execute("""SELECT * FROM stickers
            WHERE account_id=? AND chat_id=? AND deleted=0 ORDER BY id""", (account_id, chat_id)).fetchall()
        return dict(secrets.choice(rows)) if rows else None

    def delete(self, connection, *, account_id, chat_id, sender_id, sticker_id, owner_id=""):
        """Hide an entry. Caller cancels pending sends for its ID in this transaction.

        Files are retained: accepted/uncertain/sending replies may still refer to
        them. Physical cleanup requires checking all outbox references.
        """
        _identity(account_id, chat_id, sender_id)
        if type(sticker_id) is not int or sticker_id < 1:
            raise StickerError("表情编号必须是正整数")
        row = connection.execute("""SELECT * FROM stickers
            WHERE id=? AND account_id=? AND chat_id=? AND deleted=0""",
            (sticker_id, account_id, chat_id)).fetchone()
        if not row:
            raise StickerError("找不到当前群的表情编号")
        if sender_id != row["sender_id"] and (not owner_id or sender_id != owner_id):
            raise StickerError("只有添加者或主人可删除这条表情")
        connection.execute("UPDATE stickers SET deleted=1 WHERE id=?", (sticker_id,))
        return dict(row)
