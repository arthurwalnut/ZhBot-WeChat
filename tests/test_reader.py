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
