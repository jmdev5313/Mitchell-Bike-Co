"""Parts compatibility: does a part fit the bike a customer actually has?

A part fits when every standard it requires is on the bike, either directly or
through a `standard_compat` exception (which may carry a fitting note).
"""

import sqlite3
from dataclasses import dataclass, field

from shop.errors import NotFound


@dataclass(frozen=True)
class FitResult:
    sku: str
    name: str
    fits: bool
    problems: list[str] = field(default_factory=list)  # why it does not fit
    notes: list[str] = field(default_factory=list)     # what fitting it takes


def check_fit(conn: sqlite3.Connection, sku: str, customer_bike_id: int) -> FitResult:
    part = conn.execute("SELECT id, sku, name FROM parts WHERE sku = ?", (sku,)).fetchone()
    if part is None:
        raise NotFound(f"no part with SKU {sku}")
    _require_bike(conn, customer_bike_id)
    return _fit(conn, part, customer_bike_id)


def fit_report(conn: sqlite3.Connection, customer_bike_id: int, category: str) -> list[FitResult]:
    """Every part in `category`, checked against the bike. Fitting parts come first."""
    _require_bike(conn, customer_bike_id)
    parts = conn.execute(
        "SELECT id, sku, name FROM parts WHERE category = ? ORDER BY sku", (category,)
    ).fetchall()
    results = [_fit(conn, p, customer_bike_id) for p in parts]
    return sorted(results, key=lambda r: not r.fits)


def _require_bike(conn, customer_bike_id: int) -> None:
    if not conn.execute("SELECT 1 FROM customer_bikes WHERE id = ?", (customer_bike_id,)).fetchone():
        raise NotFound(f"no customer bike with id {customer_bike_id}")


def _fit(conn, part, customer_bike_id: int) -> FitResult:
    requirements = conn.execute(
        """SELECT s.id, s.kind, s.name,
                  EXISTS (SELECT 1 FROM bike_standards bs
                          WHERE bs.customer_bike_id = ? AND bs.standard_id = s.id) AS on_bike
           FROM part_requirements pr JOIN standards s ON s.id = pr.standard_id
           WHERE pr.part_id = ? ORDER BY s.kind""",
        (customer_bike_id, part["id"]),
    ).fetchall()

    problems, notes = [], []
    for req in requirements:
        if req["on_bike"]:
            continue
        exception = conn.execute(
            """SELECT sc.note, s.name FROM standard_compat sc
               JOIN bike_standards bs ON bs.standard_id = sc.satisfied_by_id
               JOIN standards s ON s.id = sc.satisfied_by_id
               WHERE sc.required_id = ? AND bs.customer_bike_id = ?""",
            (req["id"], customer_bike_id),
        ).fetchone()
        if exception:
            notes.append(f"{req['kind']}: fits {exception['name']}, {exception['note'] or 'no note'}")
            continue
        has = [r["name"] for r in conn.execute(
            """SELECT s.name FROM bike_standards bs JOIN standards s ON s.id = bs.standard_id
               WHERE bs.customer_bike_id = ? AND s.kind = ? ORDER BY s.name""",
            (customer_bike_id, req["kind"]),
        )]
        problems.append(
            f"{req['kind']}: needs {req['name']}, bike has {', '.join(has) or 'none recorded'}"
        )

    return FitResult(part["sku"], part["name"], fits=not problems, problems=problems, notes=notes)
