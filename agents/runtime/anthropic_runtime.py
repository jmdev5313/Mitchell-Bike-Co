"""The Agent on the Claude API, using the shop's MCP servers as its tools.

The loop is written out here rather than using the SDK's beta tool runner, so
every message is stored exactly as sent (some models tie thinking blocks to the
exact history) and a conversation can be resumed from the database later.
"""

import base64
import json
import mimetypes
import os
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import anthropic
from mcp import Client, StdioServerParameters

from agents import config, conversations
from agents.runtime.base import AgentRuntime, ToolCall, TurnResult
from shop import db

SERVERS = ("catalog", "work_orders", "procurement")
MAX_STEPS = 25        # model calls per turn, a backstop against loops
MAX_TOKENS = 16000
BETAS = ["server-side-fallback-2026-07-01", "thinking-display-updates-2026-08-18"]

# Opens the MCP servers for a conversation: (conversation_id, exit_stack) -> {server: client}
ServerConnector = Callable[[str, AsyncExitStack], Any]


async def connect_stdio(conversation_id: str, stack: AsyncExitStack) -> dict[str, Client]:
    """Launch each shop server as a subprocess for this conversation, as Claude Code does."""
    env = {
        "DB_PATH": str(db.db_path()),
        "AGENT_RUNTIME": "anthropic",
        "CONVERSATION_ID": conversation_id,
        "MCP_LOG_LEVEL": "WARNING",
    }
    clients = {}
    for name in SERVERS:
        params = StdioServerParameters(
            command="uv", args=["run", "python", "-m", f"mcp_servers.{name}"], env=env, cwd=Path.cwd()
        )
        clients[name] = await stack.enter_async_context(Client(params))
    return clients


class AnthropicRuntime(AgentRuntime):
    name = "anthropic"

    def __init__(
        self,
        conversation_id: str | None = None,
        *,
        client: Any = None,
        connect: ServerConnector = connect_stdio,
        model: str | None = None,
        effort: str | None = None,
    ) -> None:
        self.conversation_id = conversation_id or ""
        self._resume = conversation_id is not None
        self._client = client
        self._connect = connect
        self.model = model or config.agent_model()
        self.effort = effort or config.agent_effort()
        self._stack: AsyncExitStack | None = None
        self._conn = None
        self._tools: list[dict] = []
        self._tool_server: dict[str, Client] = {}
        self._messages: list[dict] = []

    async def open(self) -> None:
        self._conn = db.connect()
        if self._resume:
            convo = conversations.get(self._conn, self.conversation_id)
            if convo.runtime != self.name:
                raise ValueError(f"conversation {convo.id} belongs to the {convo.runtime} runtime")
            self._messages = conversations.history(self._conn, self.conversation_id)
        else:
            self.conversation_id = conversations.create(self._conn, self.name, self.model).id
        self._client = self._client or anthropic.AsyncAnthropic()
        self._stack = AsyncExitStack()
        servers = await self._connect(self.conversation_id, self._stack)
        for server in servers.values():
            for tool in (await server.list_tools()).tools:
                if tool.name in self._tool_server:
                    raise ValueError(f"tool {tool.name} is offered by two servers")
                self._tool_server[tool.name] = server
                self._tools.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.input_schema,
                })
        self._tools.sort(key=lambda t: t["name"])  # a stable order keeps the prompt cache warm

    async def close(self) -> None:
        if self._stack:
            await self._stack.aclose()
        if self._conn:
            self._conn.close()

    async def send(self, text: str, images: Sequence[Path] = ()) -> TurnResult:
        content: list[dict] = [_image_block(p) for p in images]
        content.append({"type": "text", "text": text})
        self._append("user", content)

        result = TurnResult(conversation_id=self.conversation_id, reply="")
        for _ in range(MAX_STEPS):
            response = await self._client.beta.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=config.system_prompt(),
                tools=self._tools,
                messages=self._messages,
                thinking={"type": "adaptive", "display": "updates"},
                output_config={"effort": self.effort},
                cache_control={"type": "ephemeral"},
                betas=BETAS,
                fallbacks="default",
            )
            usage = _usage(response)
            for key, value in usage.items():
                result.usage[key] = result.usage.get(key, 0) + value

            if response.stop_reason == "refusal":
                # Nothing from a refused response goes into the history.
                result.stop_reason = "refusal"
                result.reply = "The model declined this request."
                return result

            blocks = [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in response.content]
            self._append("assistant", blocks, usage)
            result.progress += [b["thinking"] for b in blocks if b["type"] == "thinking" and b.get("thinking")]
            text_out = "\n\n".join(b["text"] for b in blocks if b["type"] == "text").strip()

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in (b for b in blocks if b["type"] == "tool_use"):
                    call = await self._call_tool(block["name"], block.get("input") or {})
                    result.tool_calls.append(call)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": call.result,
                        "is_error": call.is_error,
                    })
                self._append("user", tool_results)
                continue

            if response.stop_reason == "pause_turn":
                continue

            result.reply = text_out
            result.stop_reason = response.stop_reason or "end_turn"
            return result

        result.stop_reason = "step_limit"
        result.reply = f"Stopped after {MAX_STEPS} steps without finishing. Ask me to continue."
        return result

    async def _call_tool(self, name: str, arguments: dict) -> ToolCall:
        server = self._tool_server.get(name)
        if server is None:
            return ToolCall(name, arguments, True, f"unknown tool {name}")
        response = await server.call_tool(name, arguments)
        text = "\n".join(c.text for c in response.content if getattr(c, "type", "") == "text")
        if not text and response.structured_content is not None:
            text = json.dumps(response.structured_content)
        if name == "open_work_order" and not response.is_error and response.structured_content:
            conversations.link_work_order(
                self._conn, self.conversation_id, response.structured_content["work_order_id"]
            )
        return ToolCall(name, arguments, bool(response.is_error), text)

    def _append(self, role: str, content: list[dict], usage: dict | None = None) -> None:
        self._messages.append({"role": role, "content": content})
        conversations.append(self._conn, self.conversation_id, role, content, usage)


def _image_block(path: Path) -> dict:
    media_type = mimetypes.guess_type(path.name)[0]
    if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        raise ValueError(f"{path.name}: photos must be JPEG, PNG, GIF, or WebP")
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def _usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    fields = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return {f: getattr(usage, f) or 0 for f in fields if isinstance(getattr(usage, f, None), int)}
