"""Read-only Windows/UIA queries; never activates, scrolls or sends input."""

import importlib.metadata
import ctypes
from ctypes import wintypes
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import profiles


def _windows_modules():
    if sys.platform != "win32":
        raise RuntimeError("微信读取需要 Windows 桌面。")
    try:
        import win32api
        import win32con
        import win32gui
        import win32process
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError('请安装项目的 reader 可选依赖：pip install -e ".[reader]"') from exc
    return win32api, win32con, win32gui, win32process, Desktop


def file_version(path):
    api, *_ = _windows_modules()
    info = api.GetFileVersionInfo(str(path), "\\")
    return ".".join(str(v) for v in (
        info["FileVersionMS"] >> 16, info["FileVersionMS"] & 65535,
        info["FileVersionLS"] >> 16, info["FileVersionLS"] & 65535,
    ))


def window_info(hwnd):
    api, con, gui, proc, _ = _windows_modules()
    if not gui.IsWindow(hwnd):
        raise ValueError("窗口已关闭，请重新 select。")
    _, pid = proc.GetWindowThreadProcessId(hwnd)
    handle = api.OpenProcess(con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        query_path = kernel.QueryFullProcessImageNameW
        query_path.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                              ctypes.POINTER(wintypes.DWORD)]
        query_path.restype = wintypes.BOOL
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not query_path(int(handle), 0, buffer, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        path = buffer.value
        started = str(proc.GetProcessTimes(handle)["CreationTime"])
    finally:
        handle.Close()
    if Path(path).name.lower() not in profiles.PROCESS_NAMES:
        raise ValueError("目标窗口的进程不是微信，请重新选择。")
    version = None
    version_error = None
    try:
        version = file_version(path)
    except Exception as exc:
        version_error = str(exc)
    return {
        "hwnd": hwnd, "pid": pid, "process_path": path,
        "process_started": started, "class_name": gui.GetClassName(hwnd),
        "window_title": gui.GetWindowText(hwnd), "version": version,
        "version_error": version_error, "minimized": bool(gui.IsIconic(hwnd)),
    }


def list_windows():
    _, _, gui, _, _ = _windows_modules()
    import pywintypes
    windows = []
    def visit(hwnd, _):
        if gui.IsWindowVisible(hwnd):
            try:
                windows.append(window_info(hwnd))
            except (ValueError, OSError, pywintypes.error):
                pass
    gui.EnumWindows(visit, None)
    return windows


def doctor():
    report = {"observed_at": datetime.now(timezone.utc).isoformat(),
              "os": platform.platform(), "python": sys.version,
              "dependencies": {}, "windows": [], "errors": [],
              "reception_verified": False}
    for package in ("pywinauto", "pywin32", "comtypes"):
        try:
            report["dependencies"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            report["dependencies"][package] = None
    try:
        report["windows"] = list_windows()
    except Exception as exc:
        report["errors"].append(str(exc))
    return report


class UIABackend:
    """Single explicitly selected window. Selectors require real UIA inspection."""

    def __init__(self, binding):
        self.binding = binding

    def _root(self):
        current = window_info(self.binding["hwnd"])
        for key in ("pid", "process_started", "process_path", "class_name", "version"):
            if current[key] != self.binding.get(key):
                raise ValueError(f"窗口绑定已变化（{key}）；请重新 select。")
        *_, Desktop = _windows_modules()
        root = Desktop(backend="uia").window(handle=current["hwnd"]).element_info
        if root.process_id != current["pid"]:
            raise ValueError("UIA 进程与所选窗口不一致。")
        return current, root

    def probe(self, include_text=False):
        current, root = self._root()
        nodes = root.descendants(depth=24)
        controls = []
        for node in nodes:
            item = {"control_type": node.control_type, "class_name": node.class_name,
                    "name_length": len(node.name),
                    "automation_id": node.automation_id if include_text else None}
            if include_text:
                item["name"] = node.name
            controls.append(item)
        return {"window": current, "control_count": len(nodes), "controls": controls,
                "text_included": include_text, "reception_verified": False}

    def read_snapshot(self, config):
        from .reader import Message, Snapshot
        current, root = self._root()
        if current["minimized"]:
            raise ValueError("所选窗口已最小化；暂停，请手工恢复并重新开始观察。")
        rules = config.get("selectors", {})
        nodes = root.descendants(depth=24)
        title = profiles.unique(nodes, rules.get("title", {}), "会话标题")
        if title.name != config["chat"]["title"]:
            raise ValueError("当前会话标题与选择记录不同；暂停，请重新 select。")
        container = profiles.unique(nodes, rules.get("messages", {}), "消息列表")
        # Require bottom-of-list evidence. Never scroll to obtain it.
        from pywinauto.controls.uiawrapper import UIAWrapper
        scroll = UIAWrapper(container).iface_scroll
        position = scroll.CurrentVerticalScrollPercent
        if position not in (-1, 100):
            raise ValueError("消息列表不在底部；存在历史滚动，暂停并重建基线。")
        messages = []
        row_rule = rules.get("row", {})
        if not row_rule:
            raise ValueError("消息行规则尚未配置，真实接收未完成。")
        rows = [node for node in container.children() if profiles.matches(node, row_rule)]
        for row in rows:
            subtree = [row, *row.descendants(depth=8)]
            text_nodes = [n for n in subtree if profiles.matches(n, rules.get("text", {}))]
            if len(text_nodes) > 1:
                raise ValueError("单条消息匹配多个正文节点，暂停检查定位规则。")
            text = text_nodes[0].name if text_nodes else None
            # No parsing of nicknames, timestamps or native IDs from display text.
            messages.append(Message(text=text, message_type="text" if text else "unknown",
                                    runtime_key=tuple(row.runtime_id)))
        if not rows:
            raise ValueError("没有可核实的消息行；不把空列表视为已接入。")
        return Snapshot(chat_key=(current["hwnd"], tuple(container.runtime_id), title.name),
                        title=title.name, messages=messages,
                        observed_at=datetime.now(timezone.utc).isoformat(), backend="uia")


def query_worker(pipe, action, argument):
    """Importable target for Windows spawn (package __main__ is not importable)."""
    try:
        if action == "doctor":
            result = doctor()
        elif action == "probe":
            result = UIABackend(argument[0]).probe(argument[1])
        else:
            result = UIABackend(argument["binding"]).read_snapshot(argument)
        pipe.send((True, result))
    except Exception as exc:
        pipe.send((False, f"{type(exc).__name__}: {exc}"))
    finally:
        pipe.close()
