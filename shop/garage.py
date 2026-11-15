"""Customers and their bikes: lookups the agent uses before any rule applies."""

import sqlite3

from shop.errors import NotFound, RuleViolation


def find_customers(conn: sqlite3.Connection, query: str) -> list[dict]:
    """Customers whose name or email contains `query`, with their bikes."""
    query = (query or "").strip()
    if len(query) < 2:
        raise RuleViolation("search needs at least 2 characters")
    customers = conn.execute(
        """SELECT id, name, email FROM customers
           WHERE name LIKE ? OR email LIKE ? ORDER BY name LIMIT 20""",
        (f"%{query}%", f"%{query}%"),
    ).fetchall()
    return [
        {
            "customer_id": c["id"],
            "name": c["name"],
            "email": c["email"],
            "bikes": [
                {"customer_bike_id": b["id"], "nickname": b["nickname"], "model": _model_label(b)}
                for b in conn.execute(
                    """SELECT cb.id, cb.nickname, bm.brand, bm.model, bm.year
                       FROM customer_bikes cb LEFT JOIN bike_models bm ON bm.id = cb.bike_model_id
                       WHERE cb.customer_id = ? ORDER BY cb.id""",
                    (c["id"],),
                )
            ],
        }
        for c in customers
    ]


def bike_profile(conn: sqlite3.Connection, customer_bike_id: int) -> dict:
    """What the bike actually has, how that differs from its catalog model, and its history."""
    bike = conn.execute(
        """SELECT cb.id, cb.bike_model_id, cb.nickname, cb.notes, c.name AS customer,
                  bm.brand, bm.model, bm.year
           FROM customer_bikes cb
           JOIN customers c ON c.id = cb.customer_id
           LEFT JOIN bike_models bm ON bm.id = cb.bike_model_id
           WHERE cb.id = ?""",
        (customer_bike_id,),
    ).fetchone()
    if bike is None:
        raise NotFound(f"no customer bike with id {customer_bike_id}")

    actual = _specs(conn, "bike_standards", "customer_bike_id", customer_bike_id)
    catalog = (
        _specs(conn, "bike_model_standards", "bike_model_id", bike["bike_model_id"])
        if bike["bike_model_id"] else {}
    )
    differences = [
        {"kind": kind, "catalog_model": catalog.get(kind), "this_bike": actual.get(kind)}
        for kind in sorted(set(actual) | set(catalog))
        if catalog and catalog.get(kind) != actual.get(kind)
    ]
    history = [
        {"date": r["serviced_on"], "odometer_km": r["odometer_km"], "summary": r["summary"]}
        for r in conn.execute(
            """SELECT serviced_on, odometer_km, summary FROM service_records
               WHERE customer_bike_id = ? ORDER BY serviced_on, id""",
            (customer_bike_id,),
        )
    ]
    return {
        "customer_bike_id": bike["id"],
        "customer": bike["customer"],
        "nickname": bike["nickname"],
        "model": _model_label(bike),
        "notes": bike["notes"],
        "standards": actual,
        "differs_from_catalog_model": differences,
        "service_history": history,
    }


def _specs(conn, table: str, key: str, value: int) -> dict[str, str]:
    rows = conn.execute(
        f"""SELECT s.kind, s.name FROM {table} t JOIN standards s ON s.id = t.standard_id
            WHERE t.{key} = ? ORDER BY s.kind""",
        (value,),
    )
    return {r["kind"]: r["name"] for r in rows}


def _model_label(row) -> str:
    if row["brand"] is None:
        return "bought elsewhere"
    return f"{row['brand']} {row['model']} {row['year']}"
