"""Work orders: from intake to a quote the customer approves or declines.

The customer is the human in the loop. They approve a specific dollar amount,
and nothing is ordered for a work order until they have.
"""

import sqlite3
from datetime import date, datetime, timezone

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


def lock_quote(conn: sqlite3.Connection, work_order_id: int) -> int:
    """Lock the lines and record the total. The customer sees it in a quote message."""
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


def record_customer_decision(conn: sqlite3.Connection, quote_message_id: int, approved: bool) -> str:
    """Record the customer approving or declining the quote message they were sent.

    The customer answers a specific sent message that carries the quote, so an
    approval always refers to an amount they were shown. Only the customer does
    this (the MCP servers give the agent no tool for it).
    """
    msg = conn.execute(
        "SELECT work_order_id, status, quoted_total_cents FROM customer_messages WHERE id = ?",
        (quote_message_id,),
    ).fetchone()
    if msg is None:
        raise NotFound(f"no message with id {quote_message_id}")
    if msg["quoted_total_cents"] is None:
        raise RuleViolation(f"message {quote_message_id} does not carry a quote")
    if msg["status"] != "sent":
        raise RuleViolation(f"message {quote_message_id} has not been sent to the customer")
    wo = _get(conn, msg["work_order_id"])
    _require_status(wo, ("quoted",), "record the customer's decision")
    if msg["quoted_total_cents"] != wo["quoted_total_cents"]:
        raise RuleViolation(
            f"customer was shown {_dollars(msg['quoted_total_cents'])}, "
            f"but the quote is {_dollars(wo['quoted_total_cents'])}"
        )
    new_status = "approved" if approved else "declined"
    with conn:
        conn.execute(
            "UPDATE work_orders SET status = ?, decided_at = ? WHERE id = ?",
            (new_status, datetime.now(timezone.utc).isoformat(timespec="seconds"), wo["id"]),
        )
    return new_status


def schedule_repair(conn: sqlite3.Connection, work_order_id: int, scheduled_for: str) -> None:
    """Book the repair once every part on the work order is on the shelf.

    `scheduled_for` is a date, YYYY-MM-DD. Stock is checked here and again when the
    repair is finished; it is not reserved for the work order in between.
    """
    _require_status(_get(conn, work_order_id), ("approved", "awaiting_parts"), "schedule the repair")
    try:
        day = date.fromisoformat(scheduled_for)
    except (TypeError, ValueError):
        raise RuleViolation(f"scheduled_for must be a date like 2026-11-20, not {scheduled_for!r}")
    short = _parts_short(conn, work_order_id)
    if short:
        raise RuleViolation("parts are not in yet: " + "; ".join(short))
    with conn:
        conn.execute(
            "UPDATE work_orders SET status = 'scheduled', scheduled_for = ? WHERE id = ?",
            (day.isoformat(), work_order_id),
        )


def start_repair(conn: sqlite3.Connection, work_order_id: int) -> None:
    _require_status(_get(conn, work_order_id), ("scheduled",), "start the repair")
    with conn:
        conn.execute("UPDATE work_orders SET status = 'in_progress' WHERE id = ?", (work_order_id,))


def finish_repair(conn: sqlite3.Connection, work_order_id: int) -> None:
    """Mark the repair done and take its parts off the shelf."""
    _require_status(_get(conn, work_order_id), ("in_progress",), "finish the repair")
    short = _parts_short(conn, work_order_id)
    if short:
        raise RuleViolation("not enough stock to finish: " + "; ".join(short))
    with conn:
        for part_id, qty in conn.execute(
            """SELECT part_id, SUM(qty) FROM work_order_lines
               WHERE work_order_id = ? AND part_id IS NOT NULL GROUP BY part_id""",
            (work_order_id,),
        ).fetchall():
            conn.execute("UPDATE parts SET stock_qty = stock_qty - ? WHERE id = ?", (qty, part_id))
        conn.execute(
            "UPDATE work_orders SET status = 'done', finished_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), work_order_id),
        )


def _parts_short(conn, work_order_id: int) -> list[str]:
    """Parts on the work order with less stock than it needs, as readable notes."""
    return [
        f"{r['sku']} needs {r['needed']}, {r['stock_qty']} in stock"
        for r in conn.execute(
            """SELECT p.sku, p.stock_qty, SUM(l.qty) AS needed
               FROM work_order_lines l JOIN parts p ON p.id = l.part_id
               WHERE l.work_order_id = ? GROUP BY p.id HAVING p.stock_qty < SUM(l.qty)
               ORDER BY p.sku""",
            (work_order_id,),
        )
    ]


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


def list_services(conn: sqlite3.Connection) -> list[dict]:
    return [
        {"name": r["name"], "minutes": r["minutes"], "price_cents": r["price_cents"]}
        for r in conn.execute("SELECT name, minutes, price_cents FROM services ORDER BY name")
    ]


def summary(conn: sqlite3.Connection, work_order_id: int) -> dict:
    """Everything about a work order the agent or a screen needs to show it."""
    wo = _get(conn, work_order_id)
    lines = [
        {
            "line_id": r["id"],
            "kind": "part" if r["sku"] else "service",
            "category": r["category"] if r["sku"] else "labor",
            "sku": r["sku"],
            "name": r["part_name"] or r["service_name"],
            "qty": r["qty"],
            "unit_price_cents": r["unit_price_cents"],
            "in_stock": None if r["sku"] is None else r["stock_qty"] >= r["qty"],
        }
        for r in conn.execute(
            """SELECT l.id, l.qty, l.unit_price_cents, p.sku, p.name AS part_name, p.stock_qty, p.category,
                      s.name AS service_name
               FROM work_order_lines l
               LEFT JOIN parts p ON p.id = l.part_id
               LEFT JOIN services s ON s.id = l.service_id
               WHERE l.work_order_id = ? ORDER BY l.id""",
            (work_order_id,),
        )
    ]
    return {
        "work_order_id": wo["id"],
        "customer_bike_id": wo["customer_bike_id"],
        "status": wo["status"],
        "complaint": wo["complaint"],
        "diagnosis": wo["diagnosis"],
        "lines": lines,
        "total_cents": total_cents(conn, work_order_id),
        "quoted_total_cents": wo["quoted_total_cents"],
        "decided_at": wo["decided_at"],
        "scheduled_for": wo["scheduled_for"],
        "finished_at": wo["finished_at"],
        "created_at": wo["created_at"],
    }


def list_work_orders(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    """Work orders, newest first, with who and which bike they are for."""
    rows = conn.execute(
        f"""SELECT w.id, w.status, w.complaint, w.quoted_total_cents, w.scheduled_for, w.created_at,
                   c.name AS customer, cb.nickname AS bike, cb.id AS customer_bike_id
            FROM work_orders w
            JOIN customers c ON c.id = w.customer_id
            JOIN customer_bikes cb ON cb.id = w.customer_bike_id
            {"WHERE w.status = ?" if status else ""}
            ORDER BY w.id DESC""",
        (status,) if status else (),
    ).fetchall()
    return [{**dict(r), "total_cents": total_cents(conn, r["id"])} for r in rows]
