"""Recorded runs: a real run of the Agent on a story, saved once and replayed later.

A recording keeps, for each of the Mechanic's messages, the model's responses exactly as
the API returned them (thinking, text and tool calls) and how long each took. Replaying
uses the ordinary Anthropic runtime with a stand-in client that hands back those
responses instead of calling the API: the tool calls in them still go to the shop's MCP
servers and run against its rules, so the work order, quote and order plan are made for
real. Only the model's words and choices come from the recording, and no tokens are spent.

The stand-in works out where it is from the conversation it's given (which recorded
message was sent last, and how many responses have followed it), so a conversation can be
closed and reopened mid-story.

Recordings are made with `make record` (demo/record.py) and live in demo/recordings/.
"""

import asyncio
import functools
import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from anthropic.types.beta import BetaMessage

from agents.runtime.anthropic_runtime import AnthropicRuntime, connect_stdio

MAX_PAUSE = 8.0  # seconds: a long model call replays a little faster than it ran
NO_REPLY = "This recorded run has no reply for that message."


@dataclass
class Response:
    content: list[dict]
    stop_reason: str
    seconds: float = 0.0


@dataclass
class Turn:
    message: str                 # the Mechanic's message, exactly as sent
    photo: bool = False          # sent with the story's illustrative photo
    responses: list[Response] = field(default_factory=list)


@dataclass
class Recording:
    story: str
    model: str
    recorded_on: date
    turns: list[Turn]

    def to_json(self) -> dict[str, Any]:
        return {
            "story": self.story, "model": self.model, "recorded_on": self.recorded_on.isoformat(),
            "turns": [{"message": t.message, "photo": t.photo,
                       "responses": [{"content": r.content, "stop_reason": r.stop_reason,
                                      "seconds": round(r.seconds, 2)} for r in t.responses]}
                      for t in self.turns],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Recording":
        return cls(
            story=data["story"], model=data["model"], recorded_on=date.fromisoformat(data["recorded_on"]),
            turns=[Turn(t["message"], t.get("photo", False),
                        [Response(r["content"], r["stop_reason"], r.get("seconds", 0.0)) for r in t["responses"]])
                   for t in data["turns"]],
        )

    @classmethod
    def load(cls, path: Path) -> "Recording":
        return cls.from_json(json.loads(path.read_text()))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1) + "\n")


def _text(message: dict) -> str | None:
    """The text the Mechanic typed, if this is one of their messages (not tool results)."""
    if message["role"] != "user" or isinstance(message["content"], str):
        return message["content"] if message["role"] == "user" else None
    texts = [b["text"] for b in message["content"] if b.get("type") == "text"]
    return "\n".join(texts) if texts else None


class ReplayClient:
    """Stands in for AsyncAnthropic, answering each call with the recorded response it's up to."""

    def __init__(self, recording: Recording, pace: bool = True) -> None:
        self.recording = recording
        self.pace = pace
        self.beta = self
        self.messages = self

    async def create(self, *, messages: list[dict], model: str = "", **_: Any) -> BetaMessage:
        last = max((i for i, m in enumerate(messages) if _text(m) is not None), default=None)
        sent = _text(messages[last]) if last is not None else None
        done = sum(1 for m in messages[(last or 0) + 1:] if m["role"] == "assistant")
        turn = next((t for t in self.recording.turns if t.message == sent), None)
        if turn is None or done >= len(turn.responses):
            return _message([{"type": "text", "text": NO_REPLY}], "end_turn", model)
        response = turn.responses[done]
        if self.pace and response.seconds:
            await asyncio.sleep(min(response.seconds, MAX_PAUSE))
        return _message(response.content, response.stop_reason, model)


def _message(content: list[dict], stop_reason: str, model: str) -> BetaMessage:
    return BetaMessage.model_validate({
        "id": "msg_replay", "type": "message", "role": "assistant", "model": model,
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},  # nothing is spent replaying
    })


class RecordedRuntime(AnthropicRuntime):
    """The Anthropic runtime, answered from a recording instead of the API."""

    name = "recorded"

    def __init__(self, conversation_id: str | None = None, *, recording: Recording, pace: bool = True,
                 **options: Any) -> None:
        options.setdefault("connect", functools.partial(connect_stdio, runtime=self.name))
        super().__init__(conversation_id, client=ReplayClient(recording, pace), model=recording.model, **options)


class RecordingClient:
    """Wraps AsyncAnthropic to keep every response and how long it took, turn by turn (for `make record`)."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.turns: list[list[Response]] = []
        self.beta = self
        self.messages = self

    def new_turn(self) -> None:
        self.turns.append([])

    async def create(self, **kwargs: Any) -> Any:
        started = time.monotonic()
        response = await self._client.beta.messages.create(**kwargs)
        blocks = [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in response.content]
        self.turns[-1].append(Response(blocks, response.stop_reason or "end_turn", time.monotonic() - started))
        return response
