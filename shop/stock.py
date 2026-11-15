"""Stock levels and supplier options for parts."""

import sqlite3
from dataclasses import dataclass

from shop.errors import NotFound, RuleViolation


@dataclass(frozen=True)
class StockStatus:
    sku: str
    name: str
    stock_qty: int
    reorder_point: int

    @property
    def in_stock(self) -> bool:
        return self.stock_qty > 0


@dataclass(frozen=True)
class SupplierOption:
    supplier_id: int
    supplier_name: str
    unit_cost_cents: int
    available_qty: int
    lead_time_days: int

    def total_cents(self, qty: int) -> int:
        return self.unit_cost_cents * qty


def stock_status(conn: sqlite3.Connection, sku: str) -> StockStatus:
    row = conn.execute(
        "SELECT sku, name, stock_qty, reorder_point FROM parts WHERE sku = ?", (sku,)
    ).fetchone()
    if row is None:
        raise NotFound(f"no part with SKU {sku}")
    return StockStatus(row["sku"], row["name"], row["stock_qty"], row["reorder_point"])


def supplier_options(conn: sqlite3.Connection, sku: str, qty: int) -> list[SupplierOption]:
    """Suppliers that can supply `qty` of the part, fastest first, then cheapest."""
    if qty <= 0:
        raise RuleViolation("quantity must be positive")
    stock_status(conn, sku)  # raises NotFound for an unknown SKU
    rows = conn.execute(
        """SELECT s.id, s.name, sp.unit_cost_cents, sp.available_qty, s.lead_time_days
           FROM supplier_parts sp
           JOIN suppliers s ON s.id = sp.supplier_id
           JOIN parts p ON p.id = sp.part_id
           WHERE p.sku = ? AND sp.available_qty >= ?
           ORDER BY s.lead_time_days, sp.unit_cost_cents""",
        (sku, qty),
    ).fetchall()
    return [SupplierOption(*row) for row in rows]
