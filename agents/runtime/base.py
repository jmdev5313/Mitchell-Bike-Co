"""The interface every agent runtime implements, so the platform can be swapped.

A runtime is opened for one conversation (new or resumed) and used as an async
context manager. Each `send` is one turn: the Mechanic's message in, the Agent's
reply out, with a record of the tools it called along the way.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    is_error: bool
    result: str


@dataclass
class TurnResult:
    conversation_id: str
    reply: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    progress: list[str] = field(default_factory=list)   # short status notes between tool calls
    stop_reason: str = "end_turn"                       # end_turn, refusal, max_tokens, step_limit
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return self.stop_reason == "refusal"


class AgentRuntime(ABC):
    """One conversation with the Agent on some platform."""

    name: str
    conversation_id: str

    async def __aenter__(self) -> "AgentRuntime":
        await self.open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    @abstractmethod
    async def open(self) -> None:
        """Create or resume the conversation and connect to the shop's tools."""

    @abstractmethod
    async def close(self) -> None:
        """Release connections. The conversation stays stored and can be resumed."""

    @abstractmethod
    async def send(self, text: str, images: Sequence[Path] = ()) -> TurnResult:
        """One Mechanic turn: the message (and any photos) in, the Agent's reply out."""
