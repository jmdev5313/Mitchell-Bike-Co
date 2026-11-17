"""What the shop does on its own when a work order moves forward.

When the customer approves, the shop places the orders the agent planned with the
quote: the decision was already made (that supplier is why the ready date holds),
so placing it is plain code, not another model call. If a planned order fails
(the supplier sold out, say), the shop records why, and the mechanic asks the
agent to re-plan.
"""

import sqlite3

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
    return result
