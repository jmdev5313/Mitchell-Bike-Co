"""The Mechanic's chat with the Agent.

Sending a message streams the turn as Server-Sent Events while it runs:
  event: progress   {"text": ...}                      a short status note
  event: tool_call  {"name": ..., "is_error": ..., "result": ...}
  event: reply      {"text": ..., "stop_reason": ..., "work_order_id": ..., "usage": {...}}
  event: error      {"detail": ...}
"""

import asyncio
import base64
import hashlib
import json
import sqlite3
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents import conversations
from api import guards, recorded, sandboxes
from api.agent_pool import AgentPool, Busy, Full
from api.deps import get_db, require_staff
from shop import db

router = APIRouter(prefix="/api/conversations", tags=["agent"], dependencies=[Depends(require_staff)])

PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTOS = 4
MAX_TEXT = 4000  # characters in one Mechanic message

# The hero story's illustrative photo of the worn cassette. It was made with an image model, so
# wherever it appears in a conversation it's labelled as generated. Matched by its exact bytes.
HERO_PHOTO = Path(__file__).resolve().parent.parent / "web" / "static" / "img" / "hero-cassette.jpg"


def _hero_digest() -> str | None:
    return hashlib.sha256(HERO_PHOTO.read_bytes()).hexdigest() if HERO_PHOTO.exists() else None


def _with_images(entries: list[dict]) -> list[dict]:
    """Turn stored photos into data URLs for the page, marking the illustrative hero photo."""
    hero = _hero_digest()
    for entry in entries:
        images = entry.pop("images", None)
        if entry["role"] != "mechanic":
            continue
        entry["images"] = [
            {
                "src": f"data:{image['media_type']};base64,{image['data']}",
                "illustrative": hero is not None
                and hashlib.sha256(base64.b64decode(image["data"])).hexdigest() == hero,
            }
            for image in images or []
        ]
    return entries


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


class NewConversation(BaseModel):
    work_order_id: int | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def new_conversation(
    body: NewConversation | None = None,
    agents: AgentPool = Depends(pool),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, str]:
    """Start a conversation with the Agent, optionally about an existing work order."""
    work_order_id = body.work_order_id if body else None
    if work_order_id is not None and conn.execute(
        "SELECT 1 FROM work_orders WHERE id = ?", (work_order_id,)
    ).fetchone() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no work order {work_order_id}")
    try:
        conversation_id = await agents.new()
    except Full as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    if work_order_id is not None:
        conversations.link_work_order(conn, conversation_id, work_order_id)
    return {"conversation_id": conversation_id}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The conversation as the Mechanic sees it, and the work order it's linked to."""
    _require_conversation(conn, conversation_id)
    convo = conversations.get(conn, conversation_id)
    return {
        "conversation_id": convo.id,
        "work_order_id": convo.work_order_id,
        "model": convo.model,
        "runtime": convo.runtime,  # "recorded" for a recorded run's replay
        "entries": _with_images(conversations.transcript(conn, conversation_id)),
        "usage": conversations.usage_totals(conn, conversation_id),
    }


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    text: str = Form(min_length=1, max_length=MAX_TEXT),
    photos: list[UploadFile] = File(default=[]),
    agents: AgentPool = Depends(pool),
) -> StreamingResponse:
    """Send the Mechanic's message (and up to 4 photos) and stream the Agent's turn."""
    conn = db.connect()
    try:
        _require_conversation(conn, conversation_id)
        replaying = recorded.active(conn)
        turn = recorded.next_turn(conn, replaying) if replaying else None
    finally:
        conn.close()
    if agents.is_busy(conversation_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "a turn is already running in this conversation")
    if replaying:  # a recorded run spends nothing, but only plays the recording's next message
        if turn is None or text.strip() != turn.message:
            raise HTTPException(status.HTTP_409_CONFLICT, "In a recorded run, only the recording's next message can be sent.")
    elif refusal := guards.agent_refusal(sandboxes.current_key()):  # the hosted demo's spending limits
        code = status.HTTP_503_SERVICE_UNAVAILABLE if not guards.live() else status.HTTP_429_TOO_MANY_REQUESTS
        raise HTTPException(code, refusal)
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
        _stream_turn(agents, conversation_id, text.strip() if replaying else text, paths, workdir,
                     charge=not replaying),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_turn(
    agents: AgentPool, conversation_id: str, text: str, photos: list[Path], workdir: tempfile.TemporaryDirectory,
    charge: bool = True,
) -> AsyncIterator[str]:
    events: asyncio.Queue = asyncio.Queue()

    async def on_event(event: dict[str, Any]) -> None:
        await events.put(event)

    def usage_so_far() -> tuple[str, dict[str, int]]:
        conn = db.connect()
        try:
            return conversations.get(conn, conversation_id).model, conversations.usage_totals(conn, conversation_id)
        finally:
            conn.close()

    async def run() -> None:
        model, before = usage_so_far()
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
        except (Busy, Full) as e:
            await events.put({"type": "error", "detail": str(e)})
        except Exception as e:  # noqa: BLE001 - reported to the client, turn already stored
            await events.put({"type": "error", "detail": f"the turn failed: {type(e).__name__}: {e}"})
        finally:
            # Charge the turn to the demo's budget from what was stored, so a turn that failed partway still counts.
            if charge:
                _, after = usage_so_far()
                spent = {k: after.get(k, 0) - before.get(k, 0) for k in after}
                guards.record_turn(sandboxes.current_key(), conversation_id, model, spent)
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
