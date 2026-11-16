"""Payments for finished repairs.

A payment is started (for example, when the customer opens a Stripe checkout)
and completed when the money is confirmed. The amount is always the locked
quote: nothing else can be charged.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from shop.errors import NotFound, RuleViolation


@dataclass(frozen=True)
class Payment:
    id: int
    work_order_id: int
    stripe_session_id: str | None
    amount_cents: int
    status: str
    created_at: str
    paid_at: str | None


def start_payment(conn: sqlite3.Connection, work_order_id: int, stripe_session_id: str | None = None) -> Payment:
    """Start collecting the quoted total for a finished repair."""
    wo = _work_order(conn, work_order_id)
    if wo["status"] != "done":
        raise RuleViolation(f"work order {work_order_id} is {wo['status']}: payment is taken once the repair is done")
    with conn:
        cur = conn.execute(
            """INSERT INTO payments (work_order_id, stripe_session_id, amount_cents, status)
               VALUES (?, ?, ?, 'pending')""",
            (work_order_id, stripe_session_id, wo["quoted_total_cents"]),
        )
    return get_payment(conn, cur.lastrowid)


def complete_payment(conn: sqlite3.Connection, payment_id: int, amount_received_cents: int) -> Payment:
    """The money is confirmed: mark the payment paid and the work order paid."""
    payment = get_payment(conn, payment_id)
    if payment.status != "pending":
        raise RuleViolation(f"payment {payment_id} is {payment.status}, not pending")
    if amount_received_cents != payment.amount_cents:
        raise RuleViolation(
            f"received {amount_received_cents} cents, but the payment is for {payment.amount_cents}"
        )
    wo = _work_order(conn, payment.work_order_id)
    if wo["status"] != "done":
        raise RuleViolation(f"work order {wo['id']} is {wo['status']}, not done")
    with conn:
        conn.execute(
            "UPDATE payments SET status = 'paid', paid_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), payment_id),
        )
        conn.execute("UPDATE work_orders SET status = 'paid' WHERE id = ?", (wo["id"],))
    return get_payment(conn, payment_id)


def get_payment(conn: sqlite3.Connection, payment_id: int) -> Payment:
    row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    if row is None:
        raise NotFound(f"no payment with id {payment_id}")
    return Payment(**dict(row))


def payment_for_session(conn: sqlite3.Connection, stripe_session_id: str) -> Payment:
    row = conn.execute("SELECT id FROM payments WHERE stripe_session_id = ?", (stripe_session_id,)).fetchone()
    if row is None:
        raise NotFound(f"no payment for checkout session {stripe_session_id}")
    return get_payment(conn, row["id"])


def list_payments(conn: sqlite3.Connection, work_order_id: int) -> list[Payment]:
    rows = conn.execute("SELECT * FROM payments WHERE work_order_id = ? ORDER BY id", (work_order_id,))
    return [Payment(**dict(r)) for r in rows]


def _work_order(conn, work_order_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, status, quoted_total_cents FROM work_orders WHERE id = ?", (work_order_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"no work order with id {work_order_id}")
    return row
