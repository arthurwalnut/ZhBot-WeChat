"""Application boundary; these are Astra types, not helper SDK interfaces."""
from dataclasses import dataclass
from typing import Any


class GatewayError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.state = code
        super().__init__(message)


@dataclass(frozen=True)
class Event:
    account_id: str
    chat_id: str
    chat_type: str
    sender_id: str
    native_message_id: str
    received_at: float
    message_type: str
    text: str = ""
    mentioned_ids: tuple[str, ...] = ()
    is_self: bool = False
    connection_id: str = ""
    sender_display_name: str | None = None
    sent_at: float | None = None
    media_ref: dict[str, Any] | None = None
    adapter_namespace: str = "helper_native"


@dataclass(frozen=True)
class Outgoing:
    account_id: str
    chat_id: str
    chat_type: str
    kind: str
    text: str = ""
    mentioned_ids: tuple[str, ...] = ()
    path: str | None = None
    connection_id: str = ""


@dataclass(frozen=True)
class SendResult:
    # accepted = helper completed its native submission check, not recipient delivery.
    status: str
    detail: str = ""
    retryable: bool = False
