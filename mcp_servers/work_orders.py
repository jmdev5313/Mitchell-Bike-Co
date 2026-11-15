"""Work orders server: diagnosis, parts and labor, the quote, and messages to the customer.

The agent can draft messages but not send them (a mechanic does), and cannot
record the customer's approval (only the customer does). Neither is a tool here.

Run: python -m mcp_servers.work_orders [--http] [--port 8102]
"""

import sqlite3
from dataclasses import asdict
from typing import Any

from mcp_servers.common import new_server, run, shop_tool
from shop import messages
from shop import work_orders as wo

server = new_server(
    "mitchell-work-orders",
    (
        "Mitchell Bike Co. work orders. Flow: open a work order, record the diagnosis, add "
        "parts (they must fit the bike) and labor, lock the quote, then draft a message to "
        "the customer that includes the quote. A mechanic reviews and sends your drafts; the "
        "customer approves or declines the quote themselves. Write to customers in plain "
        "language. Prices are integer cents."
    ),
)
tool = shop_tool(server)


@tool
def open_work_order(conn: sqlite3.Connection, customer_bike_id: int, complaint: str) -> dict[str, Any]:
    """Open a work order for a customer's bike, with the complaint in the customer's words."""
    return wo.summary(conn, wo.open_work_order(conn, customer_bike_id, complaint))


@tool
def get_work_order(conn: sqlite3.Connection, work_order_id: int) -> dict[str, Any]:
    """A work order's status, complaint, diagnosis, lines, and totals."""
    return wo.summary(conn, work_order_id)


@tool
def record_diagnosis(conn: sqlite3.Connection, work_order_id: int, diagnosis: str) -> dict[str, Any]:
    """Record the diagnosis, with the evidence behind it (observations, measurements, history)."""
    wo.record_diagnosis(conn, work_order_id, diagnosis)
    return wo.summary(conn, work_order_id)


@tool
def add_part(conn: sqlite3.Connection, work_order_id: int, sku: str, qty: int = 1) -> dict[str, Any]:
    """Add a part at its catalog price. Refused if the part does not fit the bike."""
    wo.add_part(conn, work_order_id, sku, qty)
    return wo.summary(conn, work_order_id)


@tool
def add_service(conn: sqlite3.Connection, work_order_id: int, service_name: str) -> dict[str, Any]:
    """Add labor by its exact service name from the labor catalog."""
    wo.add_service(conn, work_order_id, service_name)
    return wo.summary(conn, work_order_id)


@tool
def lock_quote(conn: sqlite3.Connection, work_order_id: int) -> dict[str, Any]:
    """Lock the lines and total. After this, nothing can be added, and the quote can be
    sent to the customer in a message."""
    wo.lock_quote(conn, work_order_id)
    return wo.summary(conn, work_order_id)


@tool
def draft_customer_message(
    conn: sqlite3.Connection, work_order_id: int, body: str, include_quote: bool = False
) -> dict[str, Any]:
    """Draft a message to the customer for a mechanic to review and send. With
    include_quote, the message carries the locked quote and its approve/decline buttons."""
    return asdict(messages.draft_message(conn, work_order_id, body, author="agent", include_quote=include_quote))


@tool
def list_customer_messages(conn: sqlite3.Connection, work_order_id: int) -> list[dict[str, Any]]:
    """The message thread with the customer for a work order, oldest first."""
    return [asdict(m) for m in messages.list_messages(conn, work_order_id)]


if __name__ == "__main__":
    run(server, default_port=8102)
