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


def list_conversations(conn: sqlite3.Connection) -> list[dict]:
    """Conversations, newest first, with the Mechanic's first message as a preview."""
    rows = conn.execute(
        "SELECT id, runtime, model, work_order_id, created_at FROM agent_conversations ORDER BY created_at DESC, rowid DESC"
    ).fetchall()
    out = []
    for r in rows:
        entries = transcript(conn, r["id"])
        first = next((e["text"] for e in entries if e["role"] == "mechanic"), "")
        out.append({**dict(r), "preview": first[:120], "turns": sum(e["role"] == "mechanic" for e in entries)})
    return out


def transcript(conn: sqlite3.Connection, conversation_id: str) -> list[dict]:
    """The conversation as people see it: Mechanic messages and Agent replies.

    Each Agent entry carries its tool calls (name, MCP server, a summary of the
    result, and whether it was refused); photos show as a count. The raw history
    (with thinking blocks) stays in `history`.
    """
    from agents import activity

    get(conn, conversation_id)
    entries: list[dict] = []
    agent: dict | None = None
    pending: dict[str, dict] = {}  # tool_use id -> its call, until the result arrives
    for message in history(conn, conversation_id):
        blocks = message["content"] if isinstance(message["content"], list) else [
            {"type": "text", "text": message["content"]}
        ]
        if message["role"] == "user":
            for b in blocks:
                if b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                    call = pending.pop(b["tool_use_id"])
                    content = b.get("content")
                    text = content if isinstance(content, str) else "\n".join(
                        c.get("text", "") for c in content or [] if isinstance(c, dict)
                    )
                    call.update(activity.entry(call["name"], call.pop("arguments"), text, bool(b.get("is_error"))))
            texts = [b["text"] for b in blocks if b.get("type") == "text"]
            if not texts:
                continue  # tool results only
            agent = None
            entries.append({
                "role": "mechanic",
                "text": "\n\n".join(texts),
                "photos": sum(b.get("type") == "image" for b in blocks),
            })
            continue
        if agent is None:
            agent = {"role": "agent", "text": "", "tools": [], "progress": []}
            entries.append(agent)
        for b in blocks:
            if b.get("type") == "text" and b.get("text"):
                agent["text"] = (agent["text"] + "\n\n" + b["text"]).strip()
            elif b.get("type") == "tool_use":
                call = {"name": b["name"], "server": activity.server_for(b["name"]), "arguments": b.get("input") or {},
                        "is_error": False, "summary": ""}
                pending[b["id"]] = call
                agent["tools"].append(call)
            elif b.get("type") == "thinking" and b.get("thinking"):
                agent["progress"].append(b["thinking"])
    for call in pending.values():  # a turn that stopped before its results came back
        call.pop("arguments", None)
        call["summary"] = "No result"
    return entries
