"""Agent runtimes. Pick one by name; the rest of the app only sees `AgentRuntime`."""

from agents.runtime.base import AgentRuntime, ToolCall, TurnResult

RUNTIMES = ("anthropic",)


def open_agent(runtime: str = "anthropic", conversation_id: str | None = None) -> AgentRuntime:
    """A runtime for a new conversation, or for resuming one. Use it with `async with`."""
    if runtime == "anthropic":
        from agents.runtime.anthropic_runtime import AnthropicRuntime

        return AnthropicRuntime(conversation_id)
    raise ValueError(f"unknown runtime {runtime!r}; choose from {', '.join(RUNTIMES)}")


__all__ = ["AgentRuntime", "ToolCall", "TurnResult", "RUNTIMES", "open_agent"]
