"""Purchase orders: ordering the parts a customer has approved.

The gate is enforced here, when the order is created: parts can be ordered only
for a work order whose quote the customer approved, and only the parts (and
quantities) on that quote, no matter who or what is asking.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from shop.errors import NotFound, RuleViolation
from shop.work_orders import ORDERABLE


@dataclass(frozen=True)
class PurchaseOrder:
    id: int
    work_order_id: int
    supplier_id: int
    total_cents: int


def create_purchase_order(
    conn: sqlite3.Connection,
    work_order_id: int,
    supplier_id: int,
    lines: list[tuple[str, int]],
) -> PurchaseOrder:
    """Order `lines` of (SKU, qty) from one supplier for an approved work order.

    Prices come from the supplier's catalog, never from the caller.
    """
    wo = conn.execute("SELECT id, status FROM work_orders WHERE id = ?", (work_order_id,)).fetchone()
    if wo is None:
        raise NotFound(f"no work order with id {work_order_id}")
    if wo["status"] not in ORDERABLE:
        raise RuleViolation(
            f"work order {work_order_id} is {wo['status']}: "
            "parts can only be ordered after the customer approves the quote"
        )
    if not lines:
        raise RuleViolation("a purchase order needs at least one line")
    if not conn.execute("SELECT 1 FROM suppliers WHERE id = ?", (supplier_id,)).fetchone():
        raise NotFound(f"no supplier with id {supplier_id}")

    priced = []
    seen = set()
    for sku, qty in lines:
        if qty <= 0:
            raise RuleViolation(f"{sku}: quantity must be positive")
        if sku in seen:
            raise RuleViolation(f"{sku}: listed more than once")
        seen.add(sku)
        part = conn.execute("SELECT id FROM parts WHERE sku = ?", (sku,)).fetchone()
        if part is None:
            raise NotFound(f"no part with SKU {sku}")
        remaining = _approved_qty(conn, work_order_id, part["id"]) - _ordered_qty(conn, work_order_id, part["id"])
        if qty > remaining:
            raise RuleViolation(
                f"{sku}: the approved quote leaves {remaining} to order, asked for {qty}"
            )
        offer = conn.execute(
            "SELECT unit_cost_cents, available_qty FROM supplier_parts WHERE supplier_id = ? AND part_id = ?",
            (supplier_id, part["id"]),
        ).fetchone()
        if offer is None:
            raise RuleViolation(f"{sku}: this supplier does not carry it")
        if qty > offer["available_qty"]:
            raise RuleViolation(f"{sku}: supplier has {offer['available_qty']}, asked for {qty}")
        priced.append((part["id"], qty, offer["unit_cost_cents"]))

    total = sum(qty * cost for _, qty, cost in priced)
    with conn:
        cur = conn.execute(
            """INSERT INTO purchase_orders (supplier_id, work_order_id, status, total_cents)
               VALUES (?, ?, 'ordered', ?)""",
            (supplier_id, work_order_id, total),
        )
        conn.executemany(
            """INSERT INTO purchase_order_lines (purchase_order_id, part_id, qty, unit_cost_cents)
               VALUES (?, ?, ?, ?)""",
            [(cur.lastrowid, part_id, qty, cost) for part_id, qty, cost in priced],
        )
        conn.execute("UPDATE work_orders SET status = 'awaiting_parts' WHERE id = ?", (work_order_id,))
    return PurchaseOrder(cur.lastrowid, work_order_id, supplier_id, total)


def receive_purchase_order(conn: sqlite3.Connection, po_id: int) -> None:
    """The parts arrived: mark the order received and put them on the shelf."""
    po = conn.execute("SELECT status FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if po is None:
        raise NotFound(f"no purchase order with id {po_id}")
    if po["status"] != "ordered":
        raise RuleViolation(f"purchase order {po_id} is {po['status']}, not ordered")
    with conn:
        for part_id, qty in conn.execute(
            "SELECT part_id, qty FROM purchase_order_lines WHERE purchase_order_id = ?", (po_id,)
        ).fetchall():
            conn.execute("UPDATE parts SET stock_qty = stock_qty + ? WHERE id = ?", (qty, part_id))
        conn.execute(
            "UPDATE purchase_orders SET status = 'received', received_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), po_id),
        )


def list_purchase_orders(conn: sqlite3.Connection, work_order_id: int) -> list[dict]:
    orders = conn.execute(
        """SELECT po.id, po.status, po.total_cents, po.created_at, po.received_at,
                  s.name AS supplier, s.lead_time_days
           FROM purchase_orders po JOIN suppliers s ON s.id = po.supplier_id
           WHERE po.work_order_id = ? ORDER BY po.id""",
        (work_order_id,),
    ).fetchall()
    return [
        {
            **dict(o),
            "lines": [
                dict(line) for line in conn.execute(
                    """SELECT p.sku, p.name, pol.qty, pol.unit_cost_cents
                       FROM purchase_order_lines pol JOIN parts p ON p.id = pol.part_id
                       WHERE pol.purchase_order_id = ? ORDER BY p.sku""",
                    (o["id"],),
                )
            ],
        }
        for o in orders
    ]


def _approved_qty(conn, work_order_id: int, part_id: int) -> int:
    return conn.execute(
        "SELECT COALESCE(SUM(qty), 0) FROM work_order_lines WHERE work_order_id = ? AND part_id = ?",
        (work_order_id, part_id),
    ).fetchone()[0]


def _ordered_qty(conn, work_order_id: int, part_id: int) -> int:
    return conn.execute(
        """SELECT COALESCE(SUM(pol.qty), 0) FROM purchase_order_lines pol
           JOIN purchase_orders po ON po.id = pol.purchase_order_id
           WHERE po.work_order_id = ? AND pol.part_id = ? AND po.status != 'cancelled'""",
        (work_order_id, part_id),
    ).fetchone()[0]
