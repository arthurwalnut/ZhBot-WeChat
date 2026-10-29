"""Regression for visible-only UIA lists with no readable scroll pattern."""

from wechat_reader.reader import Message, Snapshot, SnapshotDiffer


def test_visible_snapshot_append_and_viewport_gaps():
    def snapshot(*rows):
        # Each tuple is a transient runtime ID, displayed text, and row top.
        return Snapshot(
            chat_key="same-container", title="local-test", observed_at="test-time",
            messages=tuple(Message(text=text, message_type="text", runtime_key=(key,))
                           for key, text, top in rows),
            row_positions=tuple(((key,), (0, top, 100, top + 20))
                                for key, text, top in rows),
            require_full_prefix=True,
        )

    differ = SnapshotDiffer("local-account", "local-chat")
    first = (1, "same", 0)
    duplicate = (2, "same", 20)
    assert differ.update(snapshot(first)).status == "baseline"
    result = differ.update(snapshot(first, duplicate))
    assert result.status == "new"
    assert len(result.events) == 1 and result.events[0].text == "same"
    assert result.events[0].observation_kind == "new"
    assert result.events[0].native_message_id is None
    assert differ.update(snapshot(first, duplicate)).status == "unchanged"

    # A transiently truncated view must not replay its restored tail as arrivals.
    result = differ.update(snapshot(first))
    assert result.status == "gap" and not result.events
    result = differ.update(snapshot(first, duplicate))
    assert result.status == "baseline" and not result.events

    # Same rows and text, changed geometry: scrolling/resizing is an interruption.
    moved = snapshot((1, "same", -10), (2, "same", 10))
    result = differ.update(moved)
    assert result.status == "gap" and not result.events
    assert differ.update(moved).status == "baseline"
    assert differ.update(snapshot((3, "history", 0))).status == "gap"
    assert differ.update(snapshot((3, "history", 0))).status == "baseline"
    # Mutation, reorder and partial eviction also cannot establish new arrivals.
    assert differ.update(snapshot((3, "changed", 0))).status == "gap"
    assert differ.update(snapshot((3, "changed", 0))).status == "baseline"
    assert differ.update(snapshot((3, "changed", 0), (4, "next", 20))).status == "new"
    reordered = snapshot((4, "next", 20), (3, "changed", 0))
    assert differ.update(reordered).status == "gap"
    assert differ.update(reordered).status == "baseline"
    assert differ.update(snapshot((3, "changed", 0), (5, "tail", 20))).status == "gap"
    assert differ.update(snapshot((3, "changed", 0), (5, "tail", 20))).status == "baseline"
    result = differ.update(snapshot((3, "changed", 0), (5, "tail", 20), (6, "tail", 40)))
    assert result.status == "new" and [event.text for event in result.events] == ["tail"]

    # Snapshot output carries observed labels/sources without promoting them to
    # native IDs, or classifying already visible history as newly arrived.
    visible = Snapshot("other-container", "group", (
        Message(text="visible history", sender_display_name="sample sender",
                message_type="text", sender_display_name_source="windows_ocr"),
    ), "test-time")
    events = differ.visible_events(visible)
    assert len(events) == 1 and events[0].observation_kind == "snapshot"
    assert events[0].sender_display_name == "sample sender"
    assert events[0].sender_display_name_source == "windows_ocr"
    assert events[0].native_message_id is None and events[0].native_sender_id is None
    assert events[0].native_sent_at is None
    assert differ.update(snapshot((3, "changed", 0), (5, "tail", 20), (6, "tail", 40))).status == "unchanged"


def test_sender_capture_discards_rows_changed_during_screenshot(monkeypatch):
    from types import SimpleNamespace
    from wechat_reader import backend, ocr, profiles

    def node(**values):
        defaults = dict(control_type="", class_name="", automation_id="", name="",
                        runtime_id=(), descendants=lambda depth: [])
        return SimpleNamespace(**(defaults | values))

    def rect(top=0):
        return SimpleNamespace(left=0, top=top, right=300, bottom=top + 50)

    def row(key=1, text="body A", top=0):
        return node(control_type="ListItem", class_name="mmui::ChatTextItemView",
                    runtime_id=(key,), name=text, rectangle=rect(top))

    state = {"rows": [row()]}
    title = node(control_type="Text", automation_id=profiles.TITLE_ID, name="test group")
    kind = node(class_name="mmui::ChatTitleBarChatRoomView")
    container = node(**profiles.MMUI_SELECTORS["messages"], runtime_id=(100,),
                     rectangle=SimpleNamespace(left=0, top=0, right=300, bottom=200),
                     children=lambda: state["rows"])
    root = node(descendants=lambda depth: [title, kind, container])
    observer = backend.UIABackend({})
    monkeypatch.setattr(observer, "_root", lambda: ({"hwnd": 1, "minimized": False}, root))
    monkeypatch.setattr(backend.ctypes, "windll", SimpleNamespace(
        user32=SimpleNamespace(GetDpiForWindow=lambda hwnd: 96)), raising=False)
    image, ocr_calls = object(), []
    monkeypatch.setattr(backend, "_visible_capture", lambda hwnd, viewport: image)

    def recognize(captured, rectangles, scale):
        assert captured is image
        ocr_calls.append(rectangles)
        return ["sender A"]

    monkeypatch.setattr(ocr, "extract_sender_labels", recognize)
    config = {"chat": {"title": "test group"}, "selectors": profiles.MMUI_SELECTORS}
    stable = observer.read_snapshot(config)
    assert stable.interruption is None and stable.messages[0].text == "body A"
    assert stable.messages[0].sender_display_name == "sender A"
    assert len(ocr_calls) == 1

    # The capture itself triggers either scrolling or a replacement at the same
    # coordinates. Neither new screenshot may label the old UIA message body.
    for changed in (row(top=-10), row(key=2, text="body B")):
        state["rows"] = [row()]

        def capture(hwnd, viewport):
            state["rows"] = [changed]
            return image

        monkeypatch.setattr(backend, "_visible_capture", capture)
        interrupted = observer.read_snapshot(config)
        assert interrupted.interruption and not interrupted.messages
        differ = SnapshotDiffer("local-account", "local-chat")
        assert differ.update(stable).status == "baseline"
        assert differ.update(interrupted).status == "gap"
        assert differ.visible_events(interrupted) == []
        assert differ.update(stable).status == "baseline"
    assert len(ocr_calls) == 1
