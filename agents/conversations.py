"""Storage for agent conversations: who is talking, and the exact message history.

History is append-only. Some models tie their thinking blocks to the exact
conversation that produced them, so a stored message is never edited.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Conversation:
    id: str
    runtime: str
    model: str | None
    work_order_id: int | None
    external_id: str | None


def create(conn: sqlite3.Connection, runtime: str, model: str | None = None) -> Conversation:
    conversation_id = uuid.uuid4().hex
    with conn:
        conn.execute(
            "INSERT INTO agent_conversations (id, runtime, model) VALUES (?, ?, ?)",
            (conversation_id, runtime, model),
        )
    return get(conn, conversation_id)


def get(conn: sqlite3.Connection, conversation_id: str) -> Conversation:
    row = conn.execute(
        "SELECT id, runtime, model, work_order_id, external_id FROM agent_conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"no conversation {conversation_id}")
    return Conversation(**dict(row))


def link_work_order(conn: sqlite3.Connection, conversation_id: str, work_order_id: int) -> None:
    with conn:
        conn.execute(
            "UPDATE agent_conversations SET work_order_id = ? WHERE id = ? AND work_order_id IS NULL",
            (work_order_id, conversation_id),
        )


def set_external_id(conn: sqlite3.Connection, conversation_id: str, external_id: str) -> None:
    with conn:
        conn.execute(
            "UPDATE agent_conversations SET external_id = ? WHERE id = ?", (external_id, conversation_id)
        )


def append(
    conn: sqlite3.Connection,
    conversation_id: str,
    role: str,
    content: Any,
    usage: dict | None = None,
) -> None:
    with conn:
        conn.execute(
            """INSERT INTO agent_messages (conversation_id, role, content_json, usage_json)
               VALUES (?, ?, ?, ?)""",
            (conversation_id, role, json.dumps(content), json.dumps(usage) if usage else None),
        )


def history(conn: sqlite3.Connection, conversation_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content_json FROM agent_messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [{"role": r["role"], "content": json.loads(r["content_json"])} for r in rows]


def usage_totals(conn: sqlite3.Connection, conversation_id: str) -> dict[str, int]:
    totals: dict[str, int] = {}
    for (usage_json,) in conn.execute(
        "SELECT usage_json FROM agent_messages WHERE conversation_id = ? AND usage_json IS NOT NULL",
        (conversation_id,),
    ):
        for key, value in json.loads(usage_json).items():
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value
    return totals
