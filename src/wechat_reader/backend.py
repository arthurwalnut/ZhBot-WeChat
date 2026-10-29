"""Read-only Windows/UIA queries; never activates, scrolls or sends input."""

import importlib.metadata
import ctypes
from ctypes import wintypes
import platform
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import profiles


def _visible_capture(hwnd, viewport):
    """Capture only the selected viewport, rejecting other windows in front."""
    from PIL import ImageGrab
    _, _, gui, _, _ = _windows_modules()
    candidate = gui.GetTopWindow(None)
    while candidate and candidate != hwnd:
        if gui.IsWindowVisible(candidate) and not gui.IsIconic(candidate):
            left, top, right, bottom = gui.GetWindowRect(candidate)
            if (right > viewport.left and left < viewport.right
                    and bottom > viewport.top and top < viewport.bottom):
                raise ValueError("群消息区域被其他窗口遮挡；发送者 OCR 暂停，请手工移开遮挡窗口。")
        candidate = gui.GetWindow(candidate, 2)  # GW_HWNDNEXT, front to back.
    if candidate != hwnd:
        raise ValueError("无法核实截图目标窗口的可见性。")
    return ImageGrab.grab(bbox=(viewport.left, viewport.top, viewport.right, viewport.bottom),
                          all_screens=True)


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
        "visible": bool(gui.IsWindowVisible(hwnd)),
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


def _read_visible_rows(container, rules):
    """Take detached row values so a later UIA read can validate a screenshot."""
    from .reader import Message
    viewport = container.rectangle
    messages, positions = [], []
    row_rule = rules.get("row", {})
    if not row_rule:
        raise ValueError("消息行规则尚未配置，真实接收未完成。")
    for row in container.children():
        if not profiles.matches(row, row_rule):
            continue
        rect = row.rectangle
        if not (rect.right > viewport.left and rect.left < viewport.right
                and rect.bottom > viewport.top and rect.top < viewport.bottom):
            continue
        subtree = [row, *row.descendants(depth=8)]
        text_nodes = [node for node in subtree if profiles.matches(node, rules.get("text", {}))]
        if len(text_nodes) > 1:
            raise ValueError("单条消息匹配多个正文节点，暂停检查定位规则。")
        text = text_nodes[0].name if text_nodes else None
        runtime_key = tuple(row.runtime_id)
        messages.append(Message(text=text, message_type="text" if text else "unknown",
                                runtime_key=runtime_key))
        positions.append((runtime_key, (rect.left, rect.top, rect.right, rect.bottom)))
    return viewport, messages, positions


def _view_signature(viewport, messages, positions, chat_type):
    return ((viewport.left, viewport.top, viewport.right, viewport.bottom), chat_type,
            tuple((message.runtime_key, message.text, message.message_type, rectangle)
                  for message, (_, rectangle) in zip(messages, positions)))


class UIABackend:
    """Single explicitly selected window. Selectors require real UIA inspection."""

    def __init__(self, binding):
        self.binding = binding

    def _root(self):
        current = window_info(self.binding["hwnd"])
        if not current["visible"]:
            raise ValueError("所选窗口已隐藏；暂停，请手工恢复窗口或重新 select。")
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
        return {"window": current, "uia_root_class": root.class_name,
                "control_count": len(nodes), "controls": controls,
                "text_included": include_text, "reception_verified": False}

    def select_chat(self):
        current, root = self._root()
        if current["minimized"]:
            raise ValueError("请先手工恢复微信并打开目标会话。")
        nodes = root.descendants(depth=24)
        title = profiles.unique(nodes, profiles.MMUI_SELECTORS["title"], "会话标题")
        profiles.unique(nodes, profiles.MMUI_SELECTORS["messages"], "消息列表")
        return {"title": title.name, "detected_type": profiles.detect_chat_type(nodes),
                "selectors": profiles.MMUI_SELECTORS}

    def read_snapshot(self, config):
        from .reader import Snapshot
        current, root = self._root()
        if current["minimized"]:
            raise ValueError("所选窗口已最小化；暂停，请手工恢复并重新开始观察。")
        rules = config.get("selectors", {})
        nodes = root.descendants(depth=24)
        title = profiles.unique(nodes, rules.get("title", {}), "会话标题")
        if title.name != config["chat"]["title"]:
            raise ValueError("当前会话标题与选择记录不同；暂停，请重新 select。")
        container = profiles.unique(nodes, rules.get("messages", {}), "消息列表")
        chat_type = profiles.detect_chat_type(nodes)
        # This actual Qt list exposes no ScrollPattern. Read only rows whose
        # rectangles intersect the viewport; never assume it is at the bottom.
        viewport, messages, positions = _read_visible_rows(container, rules)
        interruption = None
        if chat_type == "group" and messages:
            from dataclasses import replace
            from .ocr import extract_sender_labels
            before_capture = _view_signature(viewport, messages, positions, chat_type)
            screenshot = _visible_capture(current["hwnd"], viewport)
            # Validate immediately, before OCR can attach a label from a newer
            # screen row to an older UIA body. Container identity alone is insufficient.
            captured_current, captured_root = self._root()
            captured_nodes = captured_root.descendants(depth=24)
            captured_title = profiles.unique(captured_nodes, rules.get("title", {}), "会话标题")
            captured_container = profiles.unique(captured_nodes, rules.get("messages", {}), "消息列表")
            captured_view = _read_visible_rows(captured_container, rules)
            if (captured_current["minimized"] or captured_title.name != title.name
                    or tuple(captured_container.runtime_id) != tuple(container.runtime_id)
                    or _view_signature(*captured_view, profiles.detect_chat_type(captured_nodes)) != before_capture):
                interruption = "截图前后消息行、视口或会话发生变化；本次内容已丢弃，等待重新建立基线。"
                messages, positions = [], []
            else:
                get_dpi = ctypes.windll.user32.GetDpiForWindow
                get_dpi.argtypes = [wintypes.HWND]
                get_dpi.restype = wintypes.UINT
                scale = get_dpi(current["hwnd"]) / 96
                text_indexes = [i for i, message in enumerate(messages) if message.message_type == "text"]
                visible_rows = [(left - viewport.left, top - viewport.top,
                                 right - viewport.left, bottom - viewport.top)
                                for _, (left, top, right, bottom) in positions]
                labels = extract_sender_labels(screenshot, [visible_rows[i] for i in text_indexes], scale=scale)
                for index, label in zip(text_indexes, labels):
                    messages[index] = replace(messages[index], sender_display_name=label,
                                              sender_display_name_source="windows-ocr" if label else None)
        # Recheck after traversal: a chat/window may change during a UIA query.
        after, current_root = self._root()
        after_nodes = current_root.descendants(depth=24)
        after_title = profiles.unique(after_nodes, rules.get("title", {}), "会话标题")
        after_container = profiles.unique(after_nodes, rules.get("messages", {}), "消息列表")
        if (after["minimized"] or after_title.name != config["chat"]["title"]
                or tuple(after_container.runtime_id) != tuple(container.runtime_id)):
            raise ValueError("读取过程中窗口或会话结构变化，丢弃本次快照并重新选择。")
        return Snapshot(chat_key=(current["hwnd"], tuple(container.runtime_id), title.name),
                        title=title.name, messages=messages,
                        observed_at=datetime.now(timezone.utc).isoformat(),
                        backend="uia-visible+windows-ocr" if chat_type == "group" else "uia-visible",
                        detected_chat_type=chat_type,
                        interruption=interruption, row_positions=tuple(positions), require_full_prefix=True)


def query_worker(pipe, action, argument):
    """Importable target for Windows spawn (package __main__ is not importable)."""
    # The parent handles Ctrl+C and terminates this read-only worker in finally.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        if action == "doctor":
            result = doctor()
        elif action == "probe":
            result = UIABackend(argument[0]).probe(argument[1])
        elif action == "select":
            result = UIABackend(argument).select_chat()
        else:
            result = UIABackend(argument["binding"]).read_snapshot(argument)
        pipe.send((True, result))
    except Exception as exc:
        pipe.send((False, f"{type(exc).__name__}: {exc}"))
    finally:
        pipe.close()
