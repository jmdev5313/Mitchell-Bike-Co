"""Correspondence with the customer about a work order.

Drafts can be written by the agent or a mechanic; only a mechanic sends them
(the MCP servers give the agent no send tool). A message can carry the quote,
and the customer approves or declines that message, so an approval always
refers to an amount the customer was actually shown.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from shop.errors import NotFound, RuleViolation

DRAFT_AUTHORS = ("agent", "mechanic")


@dataclass(frozen=True)
class Message:
    id: int
    work_order_id: int
    direction: str
    status: str
    author: str
    body: str
    quoted_total_cents: int | None
    created_at: str
    sent_at: str | None


def draft_message(
    conn: sqlite3.Connection,
    work_order_id: int,
    body: str,
    author: str = "agent",
    include_quote: bool = False,
) -> Message:
    """Draft a message to the customer. With `include_quote`, it carries the locked quote."""
    if author not in DRAFT_AUTHORS:
        raise RuleViolation(f"drafts are written by the agent or a mechanic, not {author!r}")
    body = _clean(body)
    wo = _work_order(conn, work_order_id)
    quoted_total = None
    if include_quote:
        if wo["status"] != "quoted":
            raise RuleViolation(
                f"work order {work_order_id} is {wo['status']}: lock the quote before sending it"
            )
        quoted_total = wo["quoted_total_cents"]
    with conn:
        cur = conn.execute(
            """INSERT INTO customer_messages
                 (work_order_id, direction, status, author, body, quoted_total_cents)
               VALUES (?, 'to_customer', 'draft', ?, ?, ?)""",
            (work_order_id, author, body, quoted_total),
        )
    return get_message(conn, cur.lastrowid)


def edit_draft(conn: sqlite3.Connection, message_id: int, body: str) -> Message:
    msg = get_message(conn, message_id)
    if msg.status != "draft":
        raise RuleViolation(f"message {message_id} is {msg.status}; only drafts can be edited")
    with conn:
        conn.execute("UPDATE customer_messages SET body = ? WHERE id = ?", (_clean(body), message_id))
    return get_message(conn, message_id)


def send_draft(conn: sqlite3.Connection, message_id: int) -> Message:
    """Send a draft. Only a mechanic does this."""
    msg = get_message(conn, message_id)
    if msg.status != "draft":
        raise RuleViolation(f"message {message_id} is {msg.status}, not a draft")
    if msg.quoted_total_cents is not None:
        wo = _work_order(conn, msg.work_order_id)
        if wo["status"] != "quoted" or wo["quoted_total_cents"] != msg.quoted_total_cents:
            raise RuleViolation(f"message {message_id} carries a quote that is no longer open")
    with conn:
        conn.execute(
            "UPDATE customer_messages SET status = 'sent', sent_at = ? WHERE id = ?",
            (_now(), message_id),
        )
    return get_message(conn, message_id)


def receive_message(conn: sqlite3.Connection, work_order_id: int, body: str) -> Message:
    """Record a reply from the customer."""
    body = _clean(body)
    _work_order(conn, work_order_id)
    with conn:
        cur = conn.execute(
            """INSERT INTO customer_messages (work_order_id, direction, status, author, body, sent_at)
               VALUES (?, 'from_customer', 'received', 'customer', ?, ?)""",
            (work_order_id, body, _now()),
        )
    return get_message(conn, cur.lastrowid)


def get_message(conn: sqlite3.Connection, message_id: int) -> Message:
    row = conn.execute("SELECT * FROM customer_messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        raise NotFound(f"no message with id {message_id}")
    return Message(**dict(row))


def list_messages(conn: sqlite3.Connection, work_order_id: int) -> list[Message]:
    _work_order(conn, work_order_id)
    rows = conn.execute(
        "SELECT * FROM customer_messages WHERE work_order_id = ? ORDER BY id", (work_order_id,)
    ).fetchall()
    return [Message(**dict(r)) for r in rows]


def _work_order(conn, work_order_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, status, quoted_total_cents FROM work_orders WHERE id = ?", (work_order_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"no work order with id {work_order_id}")
    return row


def _clean(body: str) -> str:
    if not body or not body.strip():
        raise RuleViolation("the message is empty")
    return body.strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
