"""baize.ext.channels — ConversationAdapter interface for external chat channels (V26 D2).

Part of ``baize.ext`` (imported lazily; never at core import time).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChannelMessage:
    channel: str
    sender: str
    text: str
    extra: dict = field(default_factory=dict)


class ConversationAdapter:
    """Unified adapter: inbound -> run contract -> outbound.

    Status: reserved. Unconnected adapters are marked reserved and must not
    be claimed as supported in release notes.
    """

    def __init__(self, channel_name: str) -> None:
        self.channel_name = channel_name
        self.status = "reserved"

    def handle_inbound(self, msg: ChannelMessage) -> dict:
        raise NotImplementedError(f"channel {self.channel_name} is reserved")

    def format_outbound(self, result: Any) -> str:
        raise NotImplementedError(f"channel {self.channel_name} is reserved")
