"""Agent runtimes. Pick one by name; the rest of the app only sees `AgentRuntime`."""

from agents.runtime.base import AgentRuntime, ToolCall, TurnResult

RUNTIMES = ("anthropic", "recorded")


def open_agent(runtime: str = "anthropic", conversation_id: str | None = None, **options) -> AgentRuntime:
    """A runtime for a new conversation, or for resuming one. Use it with `async with`.

    "recorded" replays a recorded run (pass `recording=`); see agents/runtime/replay.py."""
    if runtime == "anthropic":
        from agents.runtime.anthropic_runtime import AnthropicRuntime

        return AnthropicRuntime(conversation_id, **options)
    if runtime == "recorded":
        from agents.runtime.replay import RecordedRuntime

        return RecordedRuntime(conversation_id, **options)
    raise ValueError(f"unknown runtime {runtime!r}; choose from {', '.join(RUNTIMES)}")


__all__ = ["AgentRuntime", "ToolCall", "TurnResult", "RUNTIMES", "open_agent"]
