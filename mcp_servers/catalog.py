"""Catalog server: customers, their bikes, parts fit, stock, and labor.

Run: python -m mcp_servers.catalog [--http] [--port 8101]
"""

import sqlite3
from dataclasses import asdict
from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_servers.common import run, shop_tool
from shop import compat, garage, stock, work_orders

server = MCPServer(
    "mitchell-catalog",
    instructions=(
        "Mitchell Bike Co. catalog. Look up a customer's bike before recommending parts: "
        "fit is checked against the bike the customer actually has, which can differ from "
        "its catalog model. Prices are integer cents."
    ),
)
tool = shop_tool(server)


@tool
def find_customer(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    """Find customers by part of their name or email, with their bikes and bike ids."""
    return garage.find_customers(conn, query)


@tool
def get_bike(conn: sqlite3.Connection, customer_bike_id: int) -> dict[str, Any]:
    """A customer's bike: its actual standards, how they differ from the catalog model
    (upgrades), the customer's notes, and its service history at this shop."""
    return garage.bike_profile(conn, customer_bike_id)


@tool
def check_fit(conn: sqlite3.Connection, sku: str, customer_bike_id: int) -> dict[str, Any]:
    """Whether a part fits this bike. Lists every mismatch, and any fitting notes
    (such as a spacer or adapter) when it fits through a known exception."""
    return asdict(compat.check_fit(conn, sku, customer_bike_id))


@tool
def list_fitting_parts(conn: sqlite3.Connection, customer_bike_id: int, category: str) -> list[dict[str, Any]]:
    """Every part in a category (cassette, chain, rotor, tire) checked against this bike,
    fitting parts first, with stock levels and prices."""
    results = []
    for fit in compat.fit_report(conn, customer_bike_id, category):
        status = stock.stock_status(conn, fit.sku)
        price = conn.execute("SELECT price_cents FROM parts WHERE sku = ?", (fit.sku,)).fetchone()[0]
        results.append({**asdict(fit), "stock_qty": status.stock_qty, "price_cents": price})
    return results


@tool
def stock_status(conn: sqlite3.Connection, sku: str) -> dict[str, Any]:
    """How many of a part the shop has on the shelf."""
    status = stock.stock_status(conn, sku)
    return {**asdict(status), "in_stock": status.in_stock}


@tool
def list_services(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The shop's labor catalog: service names, minutes, and prices."""
    return work_orders.list_services(conn)


if __name__ == "__main__":
    run(server, default_port=8101)
