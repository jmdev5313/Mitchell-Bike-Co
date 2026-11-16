"""Open Agent conversations, kept between requests.

Opening a conversation starts its MCP server processes, so a conversation stays
open after a turn and is reused by the next one. Each open conversation lives in
its own task, which opens the runtime, runs its turns one at a time, and closes
it: MCP connections must be closed by the task that opened them. Conversations
idle for longer than IDLE_SECONDS are closed the next time the pool is used, and
all are closed when the app shuts down.
"""

import asyncio
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from agents.runtime import AgentRuntime, TurnResult, open_agent
from agents.runtime.base import EventHandler

IDLE_SECONDS = 15 * 60

# conversation_id or None (new) -> a runtime, not yet opened
AgentFactory = Callable[[str | None], AgentRuntime]


def default_factory(conversation_id: str | None) -> AgentRuntime:
    return open_agent("anthropic", conversation_id)


class Busy(Exception):
    """A turn is already running in this conversation."""


class _Worker:
    """One open conversation, run by its own task."""

    def __init__(self, factory: AgentFactory, conversation_id: str | None) -> None:
        loop = asyncio.get_running_loop()
        self.ready: asyncio.Future[str] = loop.create_future()
        self.requests: asyncio.Queue = asyncio.Queue()
        self.busy = False
        self.last_used = time.monotonic()
        self.task = asyncio.create_task(self._run(factory, conversation_id))

    async def _run(self, factory: AgentFactory, conversation_id: str | None) -> None:
        try:
            async with factory(conversation_id) as agent:
                self.ready.set_result(agent.conversation_id)
                while (item := await self.requests.get()) is not None:
                    text, images, on_event, done = item
                    try:
                        done.set_result(await agent.send(text, images, on_event))
                    except Exception as e:  # noqa: BLE001 - handed to the waiting request
                        done.set_exception(e)
        except Exception as e:  # noqa: BLE001
            if not self.ready.done():
                self.ready.set_exception(e)
            else:
                raise

    async def send(self, text: str, images: Sequence[Path], on_event: EventHandler | None) -> TurnResult:
        if self.busy:
            raise Busy("a turn is already running in this conversation")
        self.busy = True
        try:
            done = asyncio.get_running_loop().create_future()
            await self.requests.put((text, images, on_event, done))
            return await done
        finally:
            self.busy = False
            self.last_used = time.monotonic()

    async def close(self) -> None:
        await self.requests.put(None)
        await asyncio.gather(self.task, return_exceptions=True)


class AgentPool:
    def __init__(self, factory: AgentFactory = default_factory, idle_seconds: float = IDLE_SECONDS) -> None:
        self.factory = factory
        self.idle_seconds = idle_seconds
        self._workers: dict[str, _Worker] = {}
        self._opening = asyncio.Lock()

    async def new(self) -> str:
        """Start a conversation and keep it open. Returns its id."""
        await self._close_idle()
        worker = _Worker(self.factory, None)
        conversation_id = await worker.ready
        self._workers[conversation_id] = worker
        return conversation_id

    async def send(
        self, conversation_id: str, text: str, images: Sequence[Path] = (), on_event: EventHandler | None = None
    ) -> TurnResult:
        """Run one turn, resuming the conversation from the database if it was closed."""
        return await (await self._worker(conversation_id)).send(text, images, on_event)

    def is_busy(self, conversation_id: str) -> bool:
        worker = self._workers.get(conversation_id)
        return bool(worker and worker.busy)

    async def close_all(self) -> None:
        workers, self._workers = list(self._workers.values()), {}
        for worker in workers:
            await worker.close()

    async def _worker(self, conversation_id: str) -> _Worker:
        await self._close_idle()
        async with self._opening:
            worker = self._workers.get(conversation_id)
            if worker is None:
                worker = _Worker(self.factory, conversation_id)
                await worker.ready
                self._workers[conversation_id] = worker
        return worker

    async def _close_idle(self) -> None:
        now = time.monotonic()
        for conversation_id, worker in list(self._workers.items()):
            if not worker.busy and now - worker.last_used > self.idle_seconds:
                del self._workers[conversation_id]
                await worker.close()

    def __len__(self) -> int:
        return len(self._workers)
