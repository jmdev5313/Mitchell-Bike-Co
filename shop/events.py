"""A work order's history: who did what, and when.

Events are written where each action happens: the MCP servers for the agent's
tool calls, the API for the mechanic's and customer's actions, and the shop's
own flow for what it does automatically. Reading them back gives the timeline
and the new-activity badges.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

ACTORS = ("agent", "mechanic", "customer", "shop")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def record(
    conn: sqlite3.Connection,
    work_order_id: int,
    actor: str,
    kind: str,
    summary: str,
    detail: dict[str, Any] | None = None,
    is_error: bool = False,
) -> int:
    if actor not in ACTORS:
        raise ValueError(f"unknown actor {actor!r}")
    with conn:
        cur = conn.execute(
            """INSERT INTO work_order_events (work_order_id, at, actor, kind, summary, detail_json, is_error)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (work_order_id, now(), actor, kind, summary, json.dumps(detail) if detail else None, int(is_error)),
        )
    return cur.lastrowid


def history(conn: sqlite3.Connection, work_order_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM work_order_events WHERE work_order_id = ? ORDER BY id", (work_order_id,)
    ).fetchall()
    return [
        {
            "id": r["id"], "at": r["at"], "actor": r["actor"], "kind": r["kind"], "summary": r["summary"],
            "detail": json.loads(r["detail_json"]) if r["detail_json"] else {}, "is_error": bool(r["is_error"]),
        }
        for r in rows
    ]


def unseen(conn: sqlite3.Connection, work_order_id: int) -> list[dict[str, Any]]:
    """What others (agent, customer, shop) did since a mechanic last opened the work order."""
    seen = conn.execute("SELECT staff_seen_at FROM work_orders WHERE id = ?", (work_order_id,)).fetchone()
    since = seen["staff_seen_at"] if seen and seen["staff_seen_at"] else ""
    rows = conn.execute(
        """SELECT id, at, actor, kind, summary FROM work_order_events
           WHERE work_order_id = ? AND actor != 'mechanic' AND at > ? ORDER BY id""",
        (work_order_id, since),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_seen(conn: sqlite3.Connection, work_order_id: int) -> None:
    with conn:
        conn.execute("UPDATE work_orders SET staff_seen_at = ? WHERE id = ?", (now(), work_order_id))


def latest_id(conn: sqlite3.Connection) -> int:
    """The newest event across all work orders: screens poll this to know when to refresh."""
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM work_order_events").fetchone()[0]
