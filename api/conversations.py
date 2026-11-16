"""The Mechanic's chat with the Agent.

Sending a message streams the turn as Server-Sent Events while it runs:
  event: progress   {"text": ...}                      a short status note
  event: tool_call  {"name": ..., "is_error": ..., "result": ...}
  event: reply      {"text": ..., "stop_reason": ..., "work_order_id": ..., "usage": {...}}
  event: error      {"detail": ...}
"""

import asyncio
import json
import sqlite3
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from agents import conversations
from api.agent_pool import AgentPool, Busy
from api.deps import get_db, require_staff
from shop import db

router = APIRouter(prefix="/api/conversations", tags=["agent"], dependencies=[Depends(require_staff)])

PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTOS = 4


def pool(request: Request) -> AgentPool:
    return request.app.state.agent_pool


def _require_conversation(conn: sqlite3.Connection, conversation_id: str) -> None:
    try:
        conversations.get(conn, conversation_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no conversation {conversation_id}")


@router.get("")
def list_conversations(conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    """Conversations with the Agent, newest first."""
    return conversations.list_conversations(conn)


@router.post("", status_code=status.HTTP_201_CREATED)
async def new_conversation(agents: AgentPool = Depends(pool)) -> dict[str, str]:
    """Start a conversation with the Agent."""
    return {"conversation_id": await agents.new()}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The conversation as the Mechanic sees it, and the work order it's linked to."""
    _require_conversation(conn, conversation_id)
    convo = conversations.get(conn, conversation_id)
    return {
        "conversation_id": convo.id,
        "work_order_id": convo.work_order_id,
        "model": convo.model,
        "entries": conversations.transcript(conn, conversation_id),
        "usage": conversations.usage_totals(conn, conversation_id),
    }


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    text: str = Form(min_length=1),
    photos: list[UploadFile] = File(default=[]),
    agents: AgentPool = Depends(pool),
) -> StreamingResponse:
    """Send the Mechanic's message (and up to 4 photos) and stream the Agent's turn."""
    conn = db.connect()
    try:
        _require_conversation(conn, conversation_id)
    finally:
        conn.close()
    if agents.is_busy(conversation_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "a turn is already running in this conversation")
    if len(photos) > MAX_PHOTOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"at most {MAX_PHOTOS} photos per message")

    workdir = tempfile.TemporaryDirectory(prefix="mbc-photos-")
    paths = []
    for i, photo in enumerate(photos):
        suffix = PHOTO_TYPES.get(photo.content_type or "")
        data = await photo.read()
        if suffix is None or len(data) > MAX_PHOTO_BYTES:
            workdir.cleanup()
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "photos must be JPEG, PNG, GIF, or WebP, up to 5 MB each"
            )
        path = Path(workdir.name) / f"photo{i}{suffix}"
        path.write_bytes(data)
        paths.append(path)

    return StreamingResponse(
        _stream_turn(agents, conversation_id, text, paths, workdir),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_turn(
    agents: AgentPool, conversation_id: str, text: str, photos: list[Path], workdir: tempfile.TemporaryDirectory
) -> AsyncIterator[str]:
    events: asyncio.Queue = asyncio.Queue()

    async def on_event(event: dict[str, Any]) -> None:
        await events.put(event)

    async def run() -> None:
        try:
            result = await agents.send(conversation_id, text, photos, on_event)
            conn = db.connect()
            try:
                work_order_id = conversations.get(conn, conversation_id).work_order_id
            finally:
                conn.close()
            await events.put({
                "type": "reply", "text": result.reply, "stop_reason": result.stop_reason,
                "work_order_id": work_order_id, "usage": result.usage,
            })
        except Busy as e:
            await events.put({"type": "error", "detail": str(e)})
        except Exception as e:  # noqa: BLE001 - reported to the client, turn already stored
            await events.put({"type": "error", "detail": f"the turn failed: {type(e).__name__}: {e}"})
        finally:
            workdir.cleanup()
            await events.put(None)

    # The turn keeps running if the client disconnects, so its messages are still stored.
    task = asyncio.create_task(run())
    try:
        while (event := await events.get()) is not None:
            kind = event.pop("type")
            yield f"event: {kind}\ndata: {json.dumps(event)}\n\n"
    finally:
        if task.done():
            task.result()
