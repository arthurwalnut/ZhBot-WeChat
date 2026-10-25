"""Ordered observations; UI runtime keys are transient anchors, never WeChat IDs.

An unchanged fixed-size snapshot of identical texts cannot reveal whether another
identical message arrived. Content-only alignment is also unable to distinguish
every history scroll from arrival; the backend must mark detected interruptions.
"""

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class Message:
    text: str | None = None
    sender_display_name: str | None = None
    message_type: str = "unknown"
    native_message_id: str | None = None
    native_sender_id: str | None = None
    native_sent_at: str | None = None
    runtime_key: tuple | str | None = None


@dataclass(frozen=True)
class Snapshot:
    chat_key: str | tuple
    title: str
    messages: tuple[Message, ...] | list[Message]
    observed_at: str
    backend: str = "uia"
    detected_chat_type: str | None = None
    interruption: str | None = None


@dataclass(frozen=True)
class Event:
    event_id: str
    observed_at: str
    account_alias: str
    chat_alias: str
    conversation_title: str
    detected_chat_type: str | None
    sender_display_name: str | None
    text: str | None
    message_type: str
    backend: str
    native_message_id: str | None = None
    native_sender_id: str | None = None
    native_sent_at: str | None = None


@dataclass(frozen=True)
class DiffResult:
    status: str
    events: list[Event] = field(default_factory=list)
    reason: str | None = None


def _key(message: Message) -> tuple:
    runtime = message.runtime_key
    if isinstance(runtime, list):
        runtime = tuple(runtime)
    return (runtime, message.native_message_id, message.sender_display_name,
            message.text, message.message_type, message.native_sender_id,
            message.native_sent_at)


class SnapshotDiffer:
    """Establish a baseline, emit tail additions, and rebaseline on uncertainty.

    Consecutive equal texts retain their positions; they are not put in a set.
    Callers should pause/reselect after a binding or account change. The aliases
    are user labels and do not establish an account or conversation identity.
    """

    def __init__(self, account_alias: str, chat_alias: str):
        self.account_alias = account_alias
        self.chat_alias = chat_alias
        self._previous: Snapshot | None = None

    def update(self, snapshot: Snapshot) -> DiffResult:
        previous = self._previous
        # Copy the sequence so a caller cannot mutate an established baseline.
        self._previous = Snapshot(
            snapshot.chat_key, snapshot.title, tuple(snapshot.messages),
            snapshot.observed_at, snapshot.backend, snapshot.detected_chat_type,
        )
        if snapshot.interruption:
            self._previous = None
            return DiffResult("gap", reason=snapshot.interruption)
        if previous is None:
            return DiffResult("baseline", reason="Initial snapshot; no historical events emitted.")
        if (previous.chat_key, previous.title, previous.backend) != (
                snapshot.chat_key, snapshot.title, snapshot.backend):
            return DiffResult("gap", reason="Conversation or backend changed; baseline reset.")
        old = [_key(message) for message in previous.messages]
        new = [_key(message) for message in snapshot.messages]
        if old == new:
            return DiffResult("unchanged")
        # Empty snapshots provide no anchor for distinguishing arrivals/history.
        if not old or not new:
            return DiffResult("gap", reason="Empty snapshot; baseline reset.")
        overlaps = [size for size in range(1, min(len(old), len(new)) + 1)
                    if old[-size:] == new[:size]]
        if not overlaps:
            return DiffResult("gap", reason="Snapshots do not align; baseline reset.")
        overlap = overlaps[-1]
        if overlap == len(new):
            return DiffResult("gap", reason="Snapshot shortened or history moved; baseline reset.")
        if len(overlaps) > 1 and overlap != len(old):
            return DiffResult("gap", reason="Repeated rows make alignment ambiguous; baseline reset.")
        added = snapshot.messages[overlap:]
        if overlap != len(old) and any(_key(message) in old for message in added):
            return DiffResult("gap", reason="Tail may contain reordered history; baseline reset.")
        # A previously visible runtime row reappearing at the tail is a reorder.
        old_runtime = {key[0] for key in old if key[0] is not None}
        if any(_key(message)[0] in old_runtime for message in added
               if message.runtime_key is not None):
            return DiffResult("gap", reason="Runtime rows were reused/reordered; baseline reset.")
        return DiffResult("new", [self._event(snapshot, message) for message in added])

    def _event(self, snapshot: Snapshot, message: Message) -> Event:
        return Event(
            event_id=str(uuid4()), observed_at=snapshot.observed_at,
            account_alias=self.account_alias, chat_alias=self.chat_alias,
            conversation_title=snapshot.title,
            detected_chat_type=snapshot.detected_chat_type,
            sender_display_name=message.sender_display_name, text=message.text,
            message_type=message.message_type, backend=snapshot.backend,
            native_message_id=message.native_message_id,
            native_sender_id=message.native_sender_id,
            native_sent_at=message.native_sent_at,
        )
