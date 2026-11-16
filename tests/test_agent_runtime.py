"""The Anthropic runtime, driven by a scripted fake model. No tokens are spent."""

import json
from contextlib import AsyncExitStack

import pytest
from anthropic.types.beta import BetaMessage
from mcp import Client

from agents import conversations
from agents.cli import Session
from agents.runtime.anthropic_runtime import AnthropicRuntime
from mcp_servers import catalog, procurement, work_orders

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def test_db(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))


async def in_memory(conversation_id: str, stack: AsyncExitStack) -> dict[str, Client]:
    servers = {"catalog": catalog.server, "work_orders": work_orders.server, "procurement": procurement.server}
    return {name: await stack.enter_async_context(Client(s)) for name, s in servers.items()}


def message(*content, stop_reason="end_turn"):
    return BetaMessage.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
        "content": list(content), "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50},
    })


def text(t):
    return {"type": "text", "text": t}


def tool_use(id, name, **input):
    return {"type": "tool_use", "id": id, "name": name, "input": input}


def progress(t):
    return {"type": "thinking", "thinking": t, "signature": "sig"}


class FakeModel:
    """Stands in for AsyncAnthropic: replays scripted responses and records each request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = self
        self.messages = self

    async def create(self, **request):
        self.requests.append(json.loads(json.dumps(request, default=str)))
        return self.responses.pop(0)


def agent(model, conversation_id=None):
    return AnthropicRuntime(conversation_id, client=model, connect=in_memory, model="claude-sonnet-5-5")


async def test_a_turn_with_tool_calls(conn):
    model = FakeModel(
        message(progress("Looking up the customer."),
                tool_use("t1", "find_customer", query="clark"),
                tool_use("t2", "get_bike", customer_bike_id=1), stop_reason="tool_use"),
        message(text("Emma's Arc has upgraded wheels with an HG 8-10 freehub.")),
    )
    async with agent(model) as a:
        result = await a.send("Whose bike is the Halden Arc on the stand? Customer is Clark.")

    assert result.reply == "Emma's Arc has upgraded wheels with an HG 8-10 freehub."
    assert [c.name for c in result.tool_calls] == ["find_customer", "get_bike"]
    assert not any(c.is_error for c in result.tool_calls)
    assert result.progress == ["Looking up the customer."]
    assert result.usage == {"input_tokens": 200, "output_tokens": 40, "cache_read_input_tokens": 100}

    first = model.requests[0]
    assert first["model"] == "claude-sonnet-5-5"
    assert first["output_config"] == {"effort": "medium"}
    assert first["fallbacks"] == "default"
    assert first["cache_control"] == {"type": "ephemeral"}
    assert "service agent at Mitchell Bike Co." in first["system"]
    assert len(first["tools"]) == 17
    assert [t["name"] for t in first["tools"]] == sorted(t["name"] for t in first["tools"])

    # Both tool results go back together, in one user message, matched by id.
    second = model.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    results = second[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert "Emma Clark" in results[0]["content"]


async def test_history_is_stored_and_resumed_unchanged(conn):
    first = FakeModel(message(text("Hi, I'm ready.")))
    async with agent(first) as a:
        await a.send("Hello")
        conversation_id = a.conversation_id

    second = FakeModel(message(text("Still here.")))
    async with agent(second, conversation_id) as a:
        await a.send("Are you there?")

    sent = second.requests[0]["messages"]
    assert sent[:2] == first.requests[0]["messages"] + [
        {"role": "assistant", "content": [{"type": "text", "text": "Hi, I'm ready."}]}
    ]
    assert sent[2]["content"][-1]["text"] == "Are you there?"
    assert len(conversations.history(conn, conversation_id)) == 4


async def test_tool_refusals_reach_the_model_as_errors(conn):
    model = FakeModel(
        message(tool_use("t1", "check_fit", sku="NOPE", customer_bike_id=1), stop_reason="tool_use"),
        message(text("That SKU doesn't exist.")),
    )
    async with agent(model) as a:
        result = await a.send("Does NOPE fit?")
    assert result.tool_calls[0].is_error
    sent = model.requests[1]["messages"][-1]["content"][0]
    assert sent["is_error"] is True and "no part with SKU NOPE" in sent["content"]


async def test_opening_a_work_order_links_the_conversation(conn):
    model = FakeModel(
        message(tool_use("t1", "open_work_order", customer_bike_id=1, complaint="Gears skip"),
                stop_reason="tool_use"),
        message(text("Opened.")),
    )
    async with agent(model) as a:
        await a.send("Open a work order for Emma's Arc.")
        conversation_id = a.conversation_id
    assert conversations.get(conn, conversation_id).work_order_id is not None


async def test_a_declined_request_leaves_no_assistant_message(conn):
    model = FakeModel(message(stop_reason="refusal"))
    async with agent(model) as a:
        result = await a.send("Something the model declines")
        conversation_id = a.conversation_id
    assert result.refused
    assert [m["role"] for m in conversations.history(conn, conversation_id)] == ["user"]


async def test_turns_stop_at_the_step_limit(conn, monkeypatch):
    monkeypatch.setattr("agents.runtime.anthropic_runtime.MAX_STEPS", 2)
    model = FakeModel(*[
        message(tool_use(f"t{i}", "list_services"), stop_reason="tool_use") for i in range(2)
    ])
    async with agent(model) as a:
        result = await a.send("Loop forever")
    assert result.stop_reason == "step_limit"
    assert len(result.tool_calls) == 2


async def test_photos_are_sent_as_images(conn, tmp_path):
    photo = tmp_path / "cassette.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n")
    model = FakeModel(message(text("I see the cassette.")))
    async with agent(model) as a:
        await a.send("Here's the cassette.", [photo])
    first = model.requests[0]["messages"][0]["content"]
    assert first[0]["type"] == "image" and first[0]["source"]["media_type"] == "image/png"
    assert first[1] == {"type": "text", "text": "Here's the cassette."}


async def test_session_commands_act_for_mechanic_and_customer(conn, quote_sent, quoted):
    convo = conversations.create(conn, "anthropic")
    conversations.link_work_order(conn, convo.id, quoted)
    session = Session(convo.id)
    assert "quote $169.98" in session.handle("/drafts")
    assert session.handle("/approve") == "The Customer approved the $169.98 quote."
    assert "is approved" in session.handle("/approve")  # can't decide twice
    text, photos = session.take_message("What's next?")
    assert text.startswith("(Shop update: The customer approved the quote")
    assert session.take_message("Again")[0] == "Again"  # updates are delivered once
