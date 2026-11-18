"""What the shop does on its own when a work order moves forward.

When the customer approves, the shop places the orders the agent planned with the
quote: the decision was already made (that supplier is why the ready date holds),
so placing it is plain code, not another model call. If a planned order fails
(the supplier sold out, say), the shop records why, and the mechanic asks the
agent to re-plan.

Once an approved work order has every part on the shelf (at approval when nothing
needed ordering, or when the last order arrives), the shop books the repair for
today and starts it, so the mechanic's next step is finishing the repair.
"""

import sqlite3
from datetime import date

from shop import events, procurement
from shop import work_orders as wo
from shop.errors import NotFound


def _dollars(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def customer_decides(conn: sqlite3.Connection, quote_message_id: int, approved: bool) -> dict:
    """The customer approves or declines a quote. On approval, the planned orders are placed.

    Returns the new status and what the shop ordered (or failed to).
    """
    msg = conn.execute(
        "SELECT work_order_id, quoted_total_cents FROM customer_messages WHERE id = ?", (quote_message_id,)
    ).fetchone()
    if msg is None:
        raise NotFound(f"no message with id {quote_message_id}")
    status = wo.record_customer_decision(conn, quote_message_id, approved)
    work_order_id = msg["work_order_id"]
    total = _dollars(msg["quoted_total_cents"] or 0)
    events.record(conn, work_order_id, "customer", status,
                  f"Approved the {total} quote" if approved else f"Declined the {total} quote")
    result = {"status": status, "placed": [], "failed": []}
    if approved:
        result.update(procurement.place_planned_orders(conn, work_order_id))
        for po in result["placed"]:
            events.record(conn, work_order_id, "shop", "order_placed",
                          f"Placed the planned order: {', '.join(po['skus'])} from {po['supplier']}, {_dollars(po['total_cents'])}",
                          {"purchase_order_id": po["id"]})
        for failure in result["failed"]:
            events.record(conn, work_order_id, "shop", "order_failed",
                          f"Couldn't place the planned order from {failure['supplier']}: {failure['reason']}",
                          is_error=True)
        result["started"] = start_when_ready(conn, work_order_id)
    return result


def start_when_ready(conn: sqlite3.Connection, work_order_id: int, today: date | None = None) -> bool:
    """If an approved work order has every part on the shelf, book it for today and start it.

    Returns whether it started. Booking and starting still go through the same rules as
    doing them by hand, and both land in the history as the shop's actions.
    """
    if wo.status(conn, work_order_id) not in ("approved", "awaiting_parts") or wo.parts_short(conn, work_order_id):
        return False
    wo.schedule_repair(conn, work_order_id, (today or date.today()).isoformat())
    wo.start_repair(conn, work_order_id)
    events.record(conn, work_order_id, "shop", "repair_started",
                  "Booked the repair for today and started it: every part is in")
    return True
