"""Thin adapter for the pinned helper native_text backend, without plugin startup."""
from __future__ import annotations

import hashlib
from io import BytesIO
import importlib.util
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..gateway import Event, GatewayError, Outgoing, SendResult
from .member_names import read_group_contact_name

UPSTREAM_COMMIT = "3e65e4bdaff438dc616f32d412175842fa138763"
BRIDGES = {
    "native/build_text/text_bridge.dll": "82e7aa658b9f7a707bc52600f68c7c9025208234eebfe6ec4453530688a96e6b",
    "native/build/selftest_bridge.dll": "3c313cafc5ad7c9b7689359fa25e1f6ffb8816169e8ce5e4c2c01f1da338b353",
}
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.@-]{1,127}\Z")


def _media_diagnostic(data):
    """Small format evidence, without CDN parameters, XML or chat content."""
    from PIL import Image
    result = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "header_hex": data[:12].hex(), "format": "UNKNOWN"}
    try:
        with Image.open(BytesIO(data)) as image:
            result.update(format=image.format, width=image.width, height=image.height)
    except Exception:
        if data.startswith(b"wxgf"):
            result["format"] = "WXGF"
    return result


def verify_dependency(helper_root):
    """Check source revision and packaged DLLs before importing upstream code."""
    root = Path(helper_root).resolve()
    command = ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root)]
    try:
        revision = subprocess.run(command + ["rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True, timeout=10).stdout.strip()
        changes = subprocess.run(command + ["status", "--porcelain", "--untracked-files=no"],
                                 check=True, capture_output=True, text=True, timeout=10).stdout
        if revision != UPSTREAM_COMMIT or changes:
            raise ValueError("helper 源码不是锁定的原始提交")
        for relative, digest in BRIDGES.items():
            if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
                raise ValueError("helper 桥接 DLL 摘要不匹配")
        for required in ("LICENSE", "THIRD_PARTY_NOTICES.md", "native/bridge_watchdog.py"):
            if not (root / required).is_file():
                raise ValueError("helper 必需许可或生命周期组件缺失")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise GatewayError("DEPENDENCY_INVALID", str(error)) from error
    return root


def _load(helper_root):
    root = verify_dependency(helper_root)
    if sys.platform != "win32":
        raise GatewayError("PLATFORM_UNSUPPORTED", "原生桥接需要 Windows x64")
    # One helper checkout per interpreter; never silently reuse another checkout's modules.
    for name, expected in (("wxbot_framework", root / "wxbot_framework"),
                           ("run_selftest", root / "native")):
        loaded = sys.modules.get(name)
        if loaded is not None and Path(loaded.__file__).resolve().parent != expected:
            raise GatewayError("DEPENDENCY_INVALID", "解释器已加载另一个 helper 副本")
    for directory in (root, root / "native"):
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
    try:
        import run_selftest
        import text_service
    except (ImportError, OSError) as error:
        raise GatewayError("DEPENDENCY_INVALID", "原生依赖导入失败：" + str(error)) from error
    return root, run_selftest, text_service


def inspect_bound(helper_root, pid):
    """Read ONLY this explicitly selected process; no injection or process discovery."""
    if type(pid) is not int or pid <= 0:
        raise GatewayError("BINDING_REQUIRED", "需要明确指定机器人微信 PID")
    root, native, service = _load(helper_root)
    try:
        core = native.modules(pid).get("weixin.dll")
        if not core:
            raise GatewayError("LOGIN_REQUIRED", "指定进程没有已加载的微信核心模块")
        baseline = json.loads((root / "native/compatibility.json").read_text(encoding="utf-8"))
        build = native.compatible_core(core[1], baseline)
        if build is None:
            raise GatewayError("VERSION_UNSUPPORTED", "指定进程核心 DLL 的大小/SHA-256 不在上游白名单")
        profile = service.inspect_profile(pid)
        if not profile or not profile.get("wxid"):
            raise GatewayError("LOGIN_REQUIRED", "未读到指定进程当前登录账号；请完成微信登录")
        return {"pid": pid, "account_id": profile["wxid"], "display_name": profile.get("name", ""),
                "wechat_version": build["wechat_version"], "core_path": str(core[1]),
                "core_sha256": build["sha256"], "core_size": build["size"], "bridge_supported": True,
                "upstream_commit": UPSTREAM_COMMIT}
    except OSError as error:
        code = "LOGIN_REQUIRED" if getattr(error, "winerror", None) in (87, 299) else "ACCESS_DENIED"
        raise GatewayError(code, "无法读取指定微信进程：" + str(error)) from error


def find_bound_pid(helper_root, account_id):
    """Read-only recovery: return the unique process of an already bound account.

    Each candidate's exact on-disk build is checked before reading identity. No
    candidate is injected, and unknown builds are never tried with old offsets.
    """
    _, native, _ = _load(helper_root)
    from wxbot_framework.account import validate_account
    validate_account(account_id)
    matches = []
    for candidate in native.wechat_candidates():
        try:
            identity = inspect_bound(helper_root, candidate)
        except GatewayError:
            continue
        if identity["account_id"] == account_id:
            matches.append(identity)
    if len(matches) != 1:
        raise GatewayError("LOGIN_REQUIRED", "未找到唯一且构建受支持的已绑定机器人账号进程")
    return matches[0]


def _sticker_helpers(root):
    # Load only the pure resource utility, never plugins/anti_recall/__init__.py.
    name = "_astra_helper_sticker_resources"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, root / "plugins/anti_recall/stickers.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


class HelperNative:
    def __init__(self, helper_root, data_dir, account_id, pid, group_allowlist, owner_id="", *, binding_mode=False):
        self.root = Path(helper_root).resolve()
        self.data_dir = Path(data_dir).resolve()
        self.account_id = account_id
        self.pid = pid
        self.group_allowlist = frozenset(group_allowlist)
        self.owner_id = owner_id
        self.binding_mode = binding_mode
        self.connection_id = ""
        self._backend = None
        self._lock = threading.RLock()
        self._stopping = False
        self._fault = None
        self._identity = None
        self.last_event_at = None
        self.rejected_identity = 0

    def start(self, emit):
        with self._lock:
            if self._backend is not None:
                raise GatewayError("ALREADY_RUNNING", "原生适配器已启动")
            try:
                self._identity = inspect_bound(self.root, self.pid)
            except GatewayError as error:
                if error.code != "LOGIN_REQUIRED" or not self.account_id or self.binding_mode:
                    raise
                # A persisted binding can survive a client PID change. Discovery is
                # read-only; the selected process is rechecked by backend.start too.
                self._identity = find_bound_pid(self.root, self.account_id)
                self.pid = self._identity["pid"]
            if not self.account_id or self._identity["account_id"] != self.account_id:
                raise GatewayError("ACCOUNT_MISMATCH", "指定进程当前账号与绑定机器人账号不同")
            from wxbot_framework.backend import NativeTextBackend
            from wxbot_framework.account import validate_account
            from wxbot_framework.text import validate_target
            validate_account(self.account_id)
            for room in self.group_allowlist:
                validate_target(room)
                if not room.endswith("@chatroom"):
                    raise GatewayError("BINDING_REQUIRED", "群白名单必须是原生群 ID")
            self._stopping, self._fault = False, None
            backend = NativeTextBackend(self.root, {
                "wechat_pid": self.pid, "wechat_account": self.account_id,
                # This upstream option controls automatic image/file/voice downloads,
                # NOT text routing. Disable these account-wide collectors. Our sticker
                # fetch is explicit and only follows a matched upload intent.
                "chat_allowlist": ["astra-no-media@chatroom"],
                "image_directory": "media/received", "emoticon_directory": "media/stickers",
                "file_directory": "media/unused-files",
            }, data_root=self.data_dir)
            self._backend, self.connection_id = backend, backend.session_id

            def receive(message):
                try:
                    event = self._convert(message)
                    if event is not None:
                        self.last_event_at = event.received_at
                        emit(event)
                except Exception:
                    # Upstream catches handler exceptions. Mark a durable health fault
                    # rather than silently continuing after an application queue failure.
                    self._fault = "RECEIVE_HANDLER_FAILED"
                    backend.raw._stop.set()
                    raise
            try:
                backend.start(receive)
                if backend.raw.self_wxid != self.account_id:
                    raise GatewayError("ACCOUNT_MISMATCH", "连接后账号核对失败")
            except BaseException:
                try:
                    backend.stop()
                except Exception:
                    # Keep ownership reference so caller can retry safe shutdown.
                    self._fault = "CLEANUP_PENDING"
                else:
                    self._backend = None
                raise
            return self.health()

    def _convert(self, message):
        if self._stopping or self._fault or message.session_id != self.connection_id:
            return None
        data = message.data
        if message.type not in (1, 3, 47) or message.is_self:
            return None  # Appmsg/replies/forwarded XML never enter command routing.
        account, room, sender = data.get("self_wxid"), message.chat_id, message.sender_id
        if account != self.account_id:
            self._fault = "ACCOUNT_MISMATCH"
            return None
        native_id = data.get("native_message_id")
        if (not isinstance(native_id, str) or not native_id.isdecimal() or int(native_id) <= 0 or
                not isinstance(sender, str) or not _IDENTIFIER.fullmatch(sender) or
                sender.endswith("@chatroom") or sender.startswith("gh_") or
                sender in ("filehelper", "weixin", "fmessage", "newsapp", "floatbottle") or
                not isinstance(room, str) or not _IDENTIFIER.fullmatch(room) or
                bool(room.endswith("@chatroom")) != bool(message.is_group)):
            self.rejected_identity += 1
            return None
        if not self.binding_mode and not (
            (message.is_group and room in self.group_allowlist) or
            (not message.is_group and room == self.owner_id and sender == self.owner_id)
        ):
            # The only unlisted-group input is an owner's explicit registration
            # command. Runtime checks its local one-use code before saving any
            # candidate; it never creates a business reply here.
            from ..groups import matches_registration
            if not (message.is_group and message.type == 1 and matches_registration(
                    self.account_id, self.owner_id, sender, message.text, data.get("at_members") or ())):
                return None
        kind = {1: "text", 3: "image", 47: "sticker"}[message.type]
        media = None
        if kind == "image":
            # Metadata is enough to reject ordinary images during sticker upload.
            # It is not proof that a PNG's bytes were successfully downloaded.
            media = {"native_type": 3, "status": "metadata_only"}
        elif kind == "sticker":
            try:
                item = _sticker_helpers(self.root).parse_sticker(data.get("raw_content") or data.get("content") or "")
                media = {"sticker": {"md5": item.md5, "length": item.length, "url": item.url}, "native_type": 47}
            except ValueError:
                media = {"error": "表情元数据缺少受支持的原件地址、MD5或格式", "native_type": 47}
        return Event(account_id=account, chat_id=room, chat_type="group" if message.is_group else "private",
                     sender_id=sender, native_message_id=native_id, received_at=time.time(),
                     message_type=kind, text=message.text if kind == "text" else "",
                     mentioned_ids=tuple(data.get("at_members") or ()), connection_id=self.connection_id,
                     sender_display_name=data.get("sender_wechat_name"), media_ref=media)

    def health(self):
        backend = self._backend
        error = self._fault
        alive = False
        recoverable = False
        if backend is not None:
            error = error or ("NATIVE_RECEIVER_FAILED" if backend.last_error else None)
            alive = bool(backend.raw._thread and backend.raw._thread.is_alive() and not backend.raw._stop.is_set())
            if backend.last_error and not self._fault:
                try:
                    exited = bool(backend.raw._guard and backend.raw._guard.target_exited())
                except OSError:
                    exited = False
                if exited:
                    error, recoverable = "PROCESS_EXITED", True
                elif str(backend.last_error).startswith("微信已退出登录或当前账号发生变化"):
                    # Reconnection still checks the configured account; a different
                    # account can never become this adapter's new binding.
                    error, recoverable = "LOGIN_REQUIRED", True
        ready = bool(alive and not error and not self._stopping)
        capabilities = []
        if backend and alive:
            exposed = {"text.receive", "text.send", "group.text.mention", "image.send",
                       "emoticon.send", "emoticon.extract"}
            capabilities = sorted(set(backend.capabilities) & exposed | {"image.metadata"})
        return {"state": "READY" if ready else "DEGRADED" if error else "STOPPED",
                "connected": ready, "receiver_alive": alive, "error": error, "recoverable": recoverable,
                "account_id": self.account_id, "pid": self.pid, "connection_id": self.connection_id,
                "wechat_version": (self._identity or {}).get("wechat_version"),
                "capabilities": capabilities, "last_event_at": self.last_event_at,
                "rejected_identity": self.rejected_identity,
                "native_error_type": type(backend.last_error).__name__ if backend and backend.last_error else None}

    def send(self, outgoing: Outgoing):
        with self._lock:
            backend = self._backend
            if self.binding_mode:
                return SendResult("failed", "OBSERVE_ONLY")
            if outgoing.account_id != self.account_id:
                return SendResult("failed", "ACCOUNT_MISMATCH")
            if not outgoing.connection_id or outgoing.connection_id != self.connection_id:
                return SendResult("failed", "STALE_CONNECTION")
            if outgoing.chat_type == "group":
                allowed = outgoing.chat_id in self.group_allowlist and outgoing.chat_id.endswith("@chatroom")
            else:
                allowed = outgoing.chat_type == "private" and outgoing.chat_id == self.owner_id and bool(self.owner_id)
            if not allowed:
                return SendResult("failed", "RECIPIENT_NOT_ALLOWED")
            if not self.health()["connected"]:
                return SendResult("failed", "NOT_CONNECTED", retryable=True)
            try:
                from wxbot_framework.text import validate_target, validate_mentions
                validate_target(outgoing.chat_id)
                if outgoing.kind == "text":
                    text = outgoing.text
                    if outgoing.mentioned_ids:
                        validate_mentions(outgoing.chat_id, outgoing.mentioned_ids)
                        # ServiceFacade.send_at_text supplies these visible labels
                        # before calling NativeTextBackend. This adapter uses the
                        # backend directly, so it must supply the same text format.
                        labels = self._mention_labels(outgoing.chat_id, outgoing.mentioned_ids)
                        if labels is None:
                            return SendResult('failed', 'MENTION_NAME_UNAVAILABLE', retryable=True)
                        text = ' '.join(labels) + '\n' + text
                    encoded = text.encode("utf-8")
                    if not 1 <= len(encoded) <= 1023 or b"\0" in encoded:
                        raise ValueError("含艾特标签的文本须为 1–1023 个 UTF-8 字节；长回复需独立 outbox 分段")
                elif outgoing.kind in ("image", "sticker"):
                    path = Path(outgoing.path or "").resolve(strict=True)
                    if not path.is_relative_to(self.data_dir):
                        raise ValueError("发送资源必须位于机器人数据目录")
                    if outgoing.kind == "image":
                        from wxbot_framework.images import validate_image_path
                        validate_image_path(path)
                    else:
                        if "emoticon.send" not in backend.capabilities:
                            raise ValueError("此客户端构建尚未开放原生表情")
                        from wxbot_framework.emoticons import validate_emoticon_path
                        validate_emoticon_path(path)
                else:
                    raise ValueError("不支持的发送类型")
                # Pure preflight failures above are definitely not submitted.
                backend.raw._check_account(force=True)
            except (ValueError, OSError, RuntimeError) as error:
                return SendResult("failed", type(error).__name__ + ": preflight rejected")
            try:
                backend.raw.last_result = None
                if outgoing.kind == "text":
                    result = (backend.send_at_text(outgoing.chat_id, text, outgoing.mentioned_ids)
                              if outgoing.mentioned_ids else backend.send_text(outgoing.chat_id, text))
                elif outgoing.kind == "image":
                    result = backend.send_image(outgoing.chat_id, str(path))
                else:
                    result = backend.send_emoticon(outgoing.chat_id, str(path))
                if result is True:
                    return SendResult("accepted", "本地原生完成检查通过；手机显示及实际提及待确认")
                # A False return can follow remote submission or an absent completion
                # report. It is NOT evidence that the server received nothing.
                return SendResult("uncertain", "helper did not confirm native completion; do not resend")
            except Exception as error:
                return SendResult("uncertain", type(error).__name__ + ": native call outcome unknown")

    def _mention_labels(self, room, members):
        """Resolve fresh names per room; native IDs remain the mention targets."""
        from wxbot_framework.contacts import read_contact_name

        def usable(name):
            return (isinstance(name, str) and name.strip() and len(name) <= 64
                    and not any(ord(ch) < 32 or ord(ch) == 127 for ch in name))

        backend, labels = self._backend, []
        try:
            with backend.raw._calls:
                backend.raw._check_account(force=True)
                rows = backend.group_members(room) or ()
                directory = {row['wxid']: row for row in rows}
                channel = backend.raw._channel
                for member in members:
                    row = directory.get(member, {})
                    name = next((row[key] for key in ('group_nickname', 'wechat_name')
                                 if usable(row.get(key))), None)
                    if name is None and channel is not None:
                        args = (channel.read_memory, channel.core_base, member)
                        name = read_contact_name(*args, expected_account=self.account_id)
                        if not usable(name):
                            name = read_group_contact_name(*args, expected_account=self.account_id)
                    if not usable(name):
                        return None
                    labels.append('@' + name.strip() + '\u2005')
                backend.raw._check_account(force=True)
        except (OSError, ValueError, RuntimeError):
            return None
        return labels

    def fetch_sticker(self, event: Event):
        if (self.binding_mode or event.account_id != self.account_id or event.message_type != "sticker" or
                event.chat_type != "group" or event.chat_id not in self.group_allowlist):
            raise GatewayError("MEDIA_REJECTED", "表情事件账号或原生类型不符")
        media = event.media_ref or {}
        if "sticker" not in media:
            raise GatewayError("MEDIA_UNSUPPORTED", media.get("error", "表情缺少可获取原件"))
        resources = _sticker_helpers(self.root)
        item = resources.Sticker(**media["sticker"])
        current = lambda: bool(event.connection_id == self.connection_id and self.health()["connected"])
        try:
            data = resources.download_sticker(item, current)
        except resources.StickerError as error:
            # Upstream's resource errors are fixed messages, with URLs and keys omitted.
            raise GatewayError("MEDIA_DOWNLOAD_FAILED", str(error)) from None
        diagnostic = _media_diagnostic(data)
        try:
            if data.startswith(b"wxgf"):
                raise GatewayError("MEDIA_UNSUPPORTED", "WXGF 尚未启用转换；不改变原动画播放时长")
            from ..sticker_media import convert_sticker
            try:
                payload = resources._gif_payload(data) if data.startswith((b"GIF87a", b"GIF89a")) else data
            except resources.StickerError:
                raise GatewayError("MEDIA_UNSUPPORTED", "原生表情资源必须是完整 GIF") from None
            result = convert_sticker(payload, current)
            legacy_digest = None
            if result['source_format'] == 'PNG':
                # Old 32-color hashes help recognize existing library entries.
                # Legacy encoder limits must not reject a newly supported source.
                try:
                    legacy_digest = hashlib.sha256(resources.gif_bytes(data, current)).hexdigest()
                except (ValueError, RuntimeError, OSError):
                    pass
            return {**result, "source_data": data, "legacy_digest": legacy_digest,
                    "diagnostic": diagnostic}
        except Exception as error:
            # Only a fully downloaded and MD5-verified selected upload reaches
            # this point. Runtime may preserve these bytes outside the library.
            error.source_data = data
            error.media_diagnostic = diagnostic
            raise

    def stop(self):
        with self._lock:
            self._stopping = True
            if self._backend is None:
                return {"already_stopped": True}
            try:
                result = self._backend.stop()  # Keep watchdog/locks until safe unload succeeds.
            except Exception:
                self._fault = "CLEANUP_PENDING"
                raise
            self._backend = None
            return result
