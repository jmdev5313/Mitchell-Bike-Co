"""Work orders: from intake to a quote the customer approves or declines.

The customer is the human in the loop. They approve a specific dollar amount,
and nothing is ordered for a work order until they have.
"""

import sqlite3
from datetime import datetime, timezone

from shop.compat import check_fit
from shop.errors import NotFound, RuleViolation

EDITABLE = ("intake", "diagnosed")      # lines can change only before the quote
ORDERABLE = ("approved", "awaiting_parts")  # parts can be ordered only after approval


def open_work_order(conn: sqlite3.Connection, customer_bike_id: int, complaint: str) -> int:
    if not complaint or not complaint.strip():
        raise RuleViolation("a work order needs the customer's complaint")
    bike = conn.execute(
        "SELECT customer_id FROM customer_bikes WHERE id = ?", (customer_bike_id,)
    ).fetchone()
    if bike is None:
        raise NotFound(f"no customer bike with id {customer_bike_id}")
    with conn:
        cur = conn.execute(
            """INSERT INTO work_orders (customer_id, customer_bike_id, status, complaint)
               VALUES (?, ?, 'intake', ?)""",
            (bike["customer_id"], customer_bike_id, complaint.strip()),
        )
    return cur.lastrowid


def status(conn: sqlite3.Connection, work_order_id: int) -> str:
    return _get(conn, work_order_id)["status"]


def record_diagnosis(conn: sqlite3.Connection, work_order_id: int, diagnosis: str) -> None:
    _require_status(_get(conn, work_order_id), EDITABLE, "record a diagnosis")
    if not diagnosis or not diagnosis.strip():
        raise RuleViolation("the diagnosis is empty")
    with conn:
        conn.execute(
            "UPDATE work_orders SET diagnosis = ?, status = 'diagnosed' WHERE id = ?",
            (diagnosis.strip(), work_order_id),
        )


def add_part(conn: sqlite3.Connection, work_order_id: int, sku: str, qty: int = 1) -> int:
    """Add a part at its catalog price. Refuses parts that do not fit the bike."""
    wo = _get(conn, work_order_id)
    _require_status(wo, ("diagnosed",), "add parts")
    if qty <= 0:
        raise RuleViolation("quantity must be positive")
    fit = check_fit(conn, sku, wo["customer_bike_id"])  # raises NotFound for an unknown SKU
    if not fit.fits:
        raise RuleViolation(f"{sku} does not fit this bike: {'; '.join(fit.problems)}")
    part = conn.execute("SELECT id, price_cents FROM parts WHERE sku = ?", (sku,)).fetchone()
    return _add_line(conn, work_order_id, part_id=part["id"], qty=qty, price=part["price_cents"])


def add_service(conn: sqlite3.Connection, work_order_id: int, service_name: str) -> int:
    _require_status(_get(conn, work_order_id), ("diagnosed",), "add services")
    service = conn.execute(
        "SELECT id, price_cents FROM services WHERE name = ?", (service_name,)
    ).fetchone()
    if service is None:
        raise NotFound(f"no service named {service_name!r}")
    return _add_line(conn, work_order_id, service_id=service["id"], qty=1, price=service["price_cents"])


def total_cents(conn: sqlite3.Connection, work_order_id: int) -> int:
    _get(conn, work_order_id)
    row = conn.execute(
        "SELECT COALESCE(SUM(qty * unit_price_cents), 0) FROM work_order_lines WHERE work_order_id = ?",
        (work_order_id,),
    ).fetchone()
    return row[0]


def send_quote(conn: sqlite3.Connection, work_order_id: int) -> int:
    """Lock the lines and record the total the customer is being asked to approve."""
    _require_status(_get(conn, work_order_id), ("diagnosed",), "quote")
    total = total_cents(conn, work_order_id)
    if total == 0:
        raise RuleViolation("nothing to quote: the work order has no lines")
    with conn:
        conn.execute(
            "UPDATE work_orders SET quoted_total_cents = ?, status = 'quoted' WHERE id = ?",
            (total, work_order_id),
        )
    return total


def record_customer_decision(
    conn: sqlite3.Connection, work_order_id: int, approved: bool, total_cents_seen: int
) -> str:
    """Record the customer's answer to the quote they were sent.

    `total_cents_seen` is the amount the customer agreed to. It must match the
    locked quote, so an approval always refers to a specific dollar amount.
    """
    wo = _get(conn, work_order_id)
    _require_status(wo, ("quoted",), "record the customer's decision")
    if total_cents_seen != wo["quoted_total_cents"]:
        raise RuleViolation(
            f"customer answered a quote of {_dollars(total_cents_seen)}, "
            f"but the quote is {_dollars(wo['quoted_total_cents'])}"
        )
    new_status = "approved" if approved else "declined"
    with conn:
        conn.execute(
            "UPDATE work_orders SET status = ?, decided_at = ? WHERE id = ?",
            (new_status, datetime.now(timezone.utc).isoformat(timespec="seconds"), work_order_id),
        )
    return new_status


def _get(conn, work_order_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM work_orders WHERE id = ?", (work_order_id,)).fetchone()
    if row is None:
        raise NotFound(f"no work order with id {work_order_id}")
    return row


def _require_status(wo, allowed: tuple[str, ...], action: str) -> None:
    if wo["status"] not in allowed:
        raise RuleViolation(f"cannot {action}: work order {wo['id']} is {wo['status']}")


def _add_line(conn, work_order_id, qty, price, part_id=None, service_id=None) -> int:
    with conn:
        cur = conn.execute(
            """INSERT INTO work_order_lines (work_order_id, part_id, service_id, qty, unit_price_cents)
               VALUES (?, ?, ?, ?, ?)""",
            (work_order_id, part_id, service_id, qty, price),
        )
    return cur.lastrowid


def _dollars(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"
