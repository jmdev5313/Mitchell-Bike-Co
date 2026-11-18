"""Recorded runs in the hosted demo: a story played with a recording of the real Agent.

When the live Agent can't take turns (its budget is spent, or it's switched off), a visitor
can still play a story: starting it "recorded" pins the shop's calendar to the day the
recording was made and marks the shop as replaying that story (both in its settings).
From then on the shop's Agent conversations run on the recorded runtime
(agents/runtime/replay.py): the tool calls run for real against the shop's rules, and the
words come from the recording. The Mechanic can only send the recording's next message,
and only once the shop reaches the step it was sent at, so the replayed tool calls find
the records they expect. The Customer can't ask questions, since answering one needs the
live Agent. Nothing is charged to the budget.
"""

import json
import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from agents.runtime import AgentRuntime, open_agent
from agents.runtime.replay import Recording, Turn
from shop import clock, db
from shop.errors import NotFound

RECORDINGS = Path(__file__).resolve().parent.parent / "demo" / "recordings"  # made by `make record`
SETTING = "recorded_story"


def path_for(key: str) -> Path:
    return Path(os.environ.get("RECORDINGS_DIR") or RECORDINGS) / f"{key}.json"


@lru_cache(maxsize=16)
def _load(path: Path, mtime: float) -> Recording:
    return Recording.load(path)


def recording(key: str) -> Recording | None:
    """The story's recording, if one has been made."""
    path = path_for(key)
    return _load(path, path.stat().st_mtime) if path.exists() else None


def active(conn: sqlite3.Connection) -> Recording | None:
    """The recording this shop is replaying, or None for a live shop."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (SETTING,)).fetchone()
    return recording(row[0]) if row else None


def start(conn: sqlite3.Connection, key: str) -> Recording:
    """Make this (freshly reset) shop replay the story's recording."""
    found = recording(key)
    if found is None:
        raise NotFound(f"there's no recorded run of the {key} story yet")
    clock.pin(conn, found.recorded_on)
    with conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (SETTING, key))
    return found


def _sent(conn: sqlite3.Connection) -> set[str]:
    """Every message the Mechanic has sent the Agent in this shop."""
    out = set()
    for (content,) in conn.execute("SELECT content_json FROM agent_messages WHERE role = 'user'"):
        blocks = json.loads(content)
        texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            out.add("\n".join(texts))
    return out


def next_turn(conn: sqlite3.Connection, found: Recording) -> Turn | None:
    """The recording's next message, once the shop has reached the step it was sent at.

    The first is ready at once. A later one is ready when the shop's own next step asks
    the Mechanic to send the Agent exactly that message (as "Repair done" does: the
    recording sends the same words as the workshop's button).
    """
    from api.staff import next_step

    sent = _sent(conn)
    for i, turn in enumerate(found.turns):
        if turn.message in sent:
            continue
        if i == 0:
            return turn
        for row in conn.execute("SELECT id, status FROM work_orders"):
            action = next_step(conn, row["id"], row["status"]).get("action") or {}
            if action.get("prompt") == turn.message:
                return turn
        return None
    return None


def status(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """What the pages need to show a recorded run, or None for a live shop."""
    found = active(conn)
    if found is None:
        return None
    turn = next_turn(conn, found)
    return {"story": found.story, "model": found.model, "recorded_on": found.recorded_on.isoformat(),
            "next_message": turn.message if turn else None, "photo": bool(turn and turn.photo)}


def open_runtime(conversation_id: str | None, **options: Any) -> AgentRuntime | None:
    """The recorded runtime, if the current shop is replaying a story; otherwise None."""
    conn = db.connect()
    try:
        found = active(conn)
    finally:
        conn.close()
    return open_agent("recorded", conversation_id, recording=found, **options) if found else None
