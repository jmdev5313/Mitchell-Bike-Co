"""Purchase orders: ordering the parts a customer has approved.

The gate is enforced here, when the order is created: parts can be ordered only
for a work order whose quote the customer approved, and only the parts (and
quantities) on that quote, no matter who or what is asking.
"""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

from shop import schedule
from shop.errors import NotFound, RuleViolation
from shop.work_orders import ORDERABLE

PLANNABLE = ("diagnosed", "quoted")  # the plan is made with the quote, before the customer decides


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


def set_order_plan(
    conn: sqlite3.Connection,
    work_order_id: int,
    lines: list[tuple[str, int, int]],
    today: date | None = None,
) -> dict:
    """Plan what to order if the customer approves: lines of (SKU, supplier id, qty).

    Replaces any earlier plan. Each part must be on the work order and the supplier
    must carry enough of it. The plan's ready date (order today, slowest supplier,
    one repair day) becomes the date the shop can promise the customer.
    """
    wo = conn.execute("SELECT id, status FROM work_orders WHERE id = ?", (work_order_id,)).fetchone()
    if wo is None:
        raise NotFound(f"no work order with id {work_order_id}")
    if wo["status"] not in PLANNABLE:
        raise RuleViolation(f"work order {work_order_id} is {wo['status']}: plan the order with the quote, before the customer decides")
    rows, seen = [], set()
    for sku, supplier_id, qty in lines:
        if qty <= 0:
            raise RuleViolation(f"{sku}: quantity must be positive")
        if sku in seen:
            raise RuleViolation(f"{sku}: listed more than once")
        seen.add(sku)
        part = conn.execute("SELECT id FROM parts WHERE sku = ?", (sku,)).fetchone()
        if part is None:
            raise NotFound(f"no part with SKU {sku}")
        on_quote = _approved_qty(conn, work_order_id, part["id"])
        if qty > on_quote:
            raise RuleViolation(f"{sku}: the work order has {on_quote}, plan asks for {qty}")
        offer = conn.execute(
            """SELECT sp.available_qty, s.lead_time_days FROM supplier_parts sp JOIN suppliers s ON s.id = sp.supplier_id
               WHERE sp.supplier_id = ? AND sp.part_id = ?""",
            (supplier_id, part["id"]),
        ).fetchone()
        if offer is None:
            raise RuleViolation(f"{sku}: supplier {supplier_id} does not carry it")
        if qty > offer["available_qty"]:
            raise RuleViolation(f"{sku}: supplier has {offer['available_qty']}, plan asks for {qty}")
        rows.append((part["id"], supplier_id, qty, offer["lead_time_days"]))
    promised = schedule.ready_date(today or date.today(), max((r[3] for r in rows), default=0)).isoformat() if rows else None
    with conn:
        conn.execute("DELETE FROM order_plan_lines WHERE work_order_id = ?", (work_order_id,))
        conn.executemany(
            "INSERT INTO order_plan_lines (work_order_id, part_id, supplier_id, qty) VALUES (?, ?, ?, ?)",
            [(work_order_id, part_id, supplier_id, qty) for part_id, supplier_id, qty, _ in rows],
        )
        conn.execute("UPDATE work_orders SET promised_ready_on = ? WHERE id = ?", (promised, work_order_id))
    return order_plan(conn, work_order_id)


def order_plan(conn: sqlite3.Connection, work_order_id: int) -> dict:
    lines = [
        dict(r) for r in conn.execute(
            """SELECT p.sku, p.name, s.id AS supplier_id, s.name AS supplier, s.lead_time_days, l.qty,
                      sp.unit_cost_cents, l.qty * sp.unit_cost_cents AS total_cents
               FROM order_plan_lines l
               JOIN parts p ON p.id = l.part_id JOIN suppliers s ON s.id = l.supplier_id
               LEFT JOIN supplier_parts sp ON sp.supplier_id = l.supplier_id AND sp.part_id = l.part_id
               WHERE l.work_order_id = ? ORDER BY p.sku""",
            (work_order_id,),
        )
    ]
    row = conn.execute("SELECT promised_ready_on FROM work_orders WHERE id = ?", (work_order_id,)).fetchone()
    return {"lines": lines, "promised_ready_on": row["promised_ready_on"] if row else None}


def place_planned_orders(conn: sqlite3.Connection, work_order_id: int) -> dict:
    """Place the planned orders, one per supplier. Each is checked by create_purchase_order's rules.

    Returns what was placed and what failed (with the rule's reason), so a failure can
    go back to the agent to re-plan.
    """
    by_supplier: dict[int, list[tuple[str, int]]] = {}
    for line in order_plan(conn, work_order_id)["lines"]:
        by_supplier.setdefault(line["supplier_id"], []).append((line["sku"], line["qty"]))
    placed, failed = [], []
    for supplier_id, lines in by_supplier.items():
        name = conn.execute("SELECT name FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()["name"]
        try:
            po = create_purchase_order(conn, work_order_id, supplier_id, lines)
            placed.append({**asdict(po), "supplier": name, "skus": [sku for sku, _ in lines]})
        except RuleViolation as e:
            failed.append({"supplier": name, "skus": [sku for sku, _ in lines], "reason": str(e)})
    return {"placed": placed, "failed": failed}


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
