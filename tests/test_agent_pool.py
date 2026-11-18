"""The pool of open Agent conversations: the limit on how many stay open, and closing idle ones."""

import asyncio
import uuid

import pytest

from agents.runtime.base import TurnResult
from api.agent_pool import AgentPool, Full

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeRuntime:
    """Stands in for a runtime: records opening and closing, and can be held mid-turn."""

    def __init__(self, conversation_id, log, gate=None):
        self.conversation_id = conversation_id or uuid.uuid4().hex
        self.log = log
        self.gate = gate

    async def __aenter__(self):
        self.log.append(("open", self.conversation_id))
        return self

    async def __aexit__(self, *exc):
        self.log.append(("close", self.conversation_id))

    async def send(self, text, images=(), on_event=None):
        if self.gate:
            await self.gate.wait()
        return TurnResult(conversation_id=self.conversation_id, reply=f"re: {text}")


def pool(log, gate=None, **options):
    return AgentPool(lambda cid: FakeRuntime(cid, log, gate), **options)


async def test_opening_one_too_many_closes_the_one_idle_longest():
    log = []
    agents = pool(log, max_open=2, idle_seconds=3600)
    first = await agents.new()
    second = await agents.new()
    await agents.send(first, "hello")  # first is now the most recently used
    third = await agents.new()
    assert len(agents) == 2 and ("close", second) in log and ("close", first) not in log
    result = await agents.send(second, "back again")  # reopens from the database, closing first
    assert result.reply == "re: back again" and ("close", first) in log
    await agents.close_all()
    assert {("close", third), ("close", second)} <= set(log)


async def test_when_every_open_conversation_is_mid_turn_a_new_one_is_refused():
    log, gate = [], asyncio.Event()
    agents = pool(log, gate, max_open=1, idle_seconds=3600)
    busy = await agents.new()
    turn = asyncio.create_task(agents.send(busy, "long turn"))
    await asyncio.sleep(0)
    with pytest.raises(Full):
        await agents.new()
    gate.set()
    assert (await turn).reply == "re: long turn"
    await agents.new()  # room again: the finished one is idle and gets closed
    assert ("close", busy) in log
    await agents.close_all()


async def test_without_a_limit_nothing_is_closed_early():
    log = []
    agents = pool(log, max_open=0, idle_seconds=3600)
    for _ in range(5):
        await agents.new()
    assert len(agents) == 5 and not any(kind == "close" for kind, _ in log)
    await agents.close_all()


async def test_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_OPEN", "3")
    monkeypatch.setenv("AGENT_IDLE_MINUTES", "5")
    agents = AgentPool(lambda cid: FakeRuntime(cid, []))
    assert agents.max_open == 3 and agents.idle_seconds == 300
