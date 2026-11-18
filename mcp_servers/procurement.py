"""Procurement server: suppliers, ready dates, and ordering approved parts.

Run: python -m mcp_servers.procurement [--http] [--port 8103]
"""

import sqlite3
from dataclasses import asdict
from typing import Any, TypedDict

from mcp_servers.common import new_server, run, shop_tool
from shop import clock, procurement, schedule, stock
from shop.errors import NotFound

server = new_server(
    "mitchell-procurement",
    (
        "Mitchell Bike Co. procurement. Plan the order with the quote (plan_order): the shop "
        "places it itself when the customer approves. Parts can be ordered only for a work order "
        "whose quote the customer has approved, and only the parts and quantities on that quote. "
        "Only promise the customer a ready date the plan backs up. Prices are integer cents."
    ),
)
tool = shop_tool(server)


class OrderLine(TypedDict):
    sku: str
    qty: int


@tool
def supplier_options(conn: sqlite3.Connection, sku: str, qty: int) -> list[dict[str, Any]]:
    """Suppliers that can supply this quantity, fastest first, with unit cost, total, and lead time."""
    return [
        {**asdict(o), "total_cents": o.total_cents(qty)}
        for o in stock.supplier_options(conn, sku, qty)
    ]


@tool
def estimate_ready_date(conn: sqlite3.Connection, supplier_ids: list[int] | None = None) -> dict[str, Any]:
    """The earliest date the repair can be ready if parts are ordered today from these
    suppliers (the slowest one counts). Pass no suppliers when every part is in stock."""
    lead_times, names = [], []
    for supplier_id in supplier_ids or []:
        row = conn.execute("SELECT name, lead_time_days FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if row is None:
            raise NotFound(f"no supplier with id {supplier_id}")
        lead_times.append(row["lead_time_days"])
        names.append(row["name"])
    today = clock.today(conn)
    lead = max(lead_times, default=0)
    return {
        "order_date": today.isoformat(),
        "suppliers": names,
        "lead_time_days": lead,
        "ready_date": schedule.ready_date(today, lead).isoformat(),
    }


class PlanLine(TypedDict):
    sku: str
    supplier_id: int
    qty: int


@tool
def plan_order(conn: sqlite3.Connection, work_order_id: int, lines: list[PlanLine]) -> dict[str, Any]:
    """Record which supplier each out-of-stock part will be ordered from if the customer
    approves. Make the plan with the quote, before drafting the message: the shop places
    these orders itself the moment the customer approves, and the plan's ready date is the
    one to promise the customer. Replaces any earlier plan."""
    return {"work_order_id": work_order_id, **procurement.set_order_plan(
        conn, work_order_id, [(line["sku"], line["supplier_id"], line["qty"]) for line in lines]
    )}


@tool
def create_purchase_order(
    conn: sqlite3.Connection, work_order_id: int, supplier_id: int, lines: list[OrderLine]
) -> dict[str, Any]:
    """Order parts from one supplier for a work order the customer has approved. Normally the
    shop places the planned order itself on approval; use this only when the plan failed or
    something extra was approved. Prices come from the supplier."""
    po = procurement.create_purchase_order(
        conn, work_order_id, supplier_id, [(line["sku"], line["qty"]) for line in lines]
    )
    supplier = conn.execute("SELECT name, lead_time_days FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    return {**asdict(po), "supplier_name": supplier["name"], "lead_time_days": supplier["lead_time_days"]}


if __name__ == "__main__":
    run(server, default_port=8103)
