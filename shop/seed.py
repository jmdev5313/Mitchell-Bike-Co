"""Load YAML seed data from data/seed/ into an empty database.

Seed files refer to records by readable keys (SKU, standard kind and name,
bike model key), and this loader resolves them to row ids.
"""

import sqlite3
import sys
from pathlib import Path

import yaml

from shop import db

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed"
FILES = ("standards", "catalog", "suppliers", "customers")
OPTIONAL_FILES = ("settings",)


class SeedError(Exception):
    """Seed data that is inconsistent or refers to something that does not exist."""


def load(conn: sqlite3.Connection, seed_dir: Path = SEED_DIR) -> None:
    """Load every seed file into `conn` in one transaction."""
    if conn.execute("SELECT 1 FROM parts LIMIT 1").fetchone():
        raise SeedError("database already has data; use `make reset` to rebuild it")
    data = {name: _read(seed_dir / f"{name}.yaml") for name in FILES}
    for name in OPTIONAL_FILES:
        path = seed_dir / f"{name}.yaml"
        data[name] = _read(path) if path.exists() else {}
    with conn:
        _load_settings(conn, data["settings"])
        standards = _load_standards(conn, data["standards"])
        parts = _load_parts(conn, data["catalog"]["parts"], standards)
        _load_services(conn, data["catalog"]["services"])
        models = _load_bike_models(conn, data["catalog"]["bike_models"], standards)
        _load_suppliers(conn, data["suppliers"]["suppliers"], parts)
        _load_customers(conn, data["customers"]["customers"], models, standards)


def _read(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _standard_ids(mapping: dict, standards: dict, where: str) -> list[int]:
    ids = []
    for kind, name in mapping.items():
        key = (kind, name)
        if key not in standards:
            raise SeedError(f"{where}: unknown standard {kind}: {name}")
        ids.append(standards[key])
    return ids


def _load_settings(conn, settings: dict) -> None:
    for key, value in settings.items():
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def _load_standards(conn, data: dict) -> dict[tuple[str, str], int]:
    ids = {}
    for kind, names in data["standards"].items():
        for name in names:
            cur = conn.execute("INSERT INTO standards (kind, name) VALUES (?, ?)", (kind, name))
            ids[(kind, name)] = cur.lastrowid
    for rule in data.get("compat", []):
        kind = rule["kind"]
        required, satisfied_by = (
            _standard_ids({kind: rule[k]}, ids, "compat")[0] for k in ("required", "satisfied_by")
        )
        conn.execute(
            "INSERT INTO standard_compat (required_id, satisfied_by_id, note) VALUES (?, ?, ?)",
            (required, satisfied_by, rule.get("note")),
        )
    return ids


def _load_parts(conn, parts: list, standards: dict) -> dict[str, int]:
    ids = {}
    for p in parts:
        cur = conn.execute(
            """INSERT INTO parts (sku, name, brand, category, price_cents, stock_qty, reorder_point)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (p["sku"], p["name"], p["brand"], p["category"], p["price_cents"],
             p.get("stock_qty", 0), p.get("reorder_point", 0)),
        )
        ids[p["sku"]] = cur.lastrowid
        for std_id in _standard_ids(p.get("requires", {}), standards, p["sku"]):
            conn.execute(
                "INSERT INTO part_requirements (part_id, standard_id) VALUES (?, ?)",
                (cur.lastrowid, std_id),
            )
    return ids


def _load_services(conn, services: list) -> None:
    for s in services:
        conn.execute(
            "INSERT INTO services (name, minutes, price_cents) VALUES (?, ?, ?)",
            (s["name"], s["minutes"], s["price_cents"]),
        )


def _load_bike_models(conn, models: list, standards: dict) -> dict[str, tuple[int, dict]]:
    """Returns model key -> (row id, standards mapping), so bikes can inherit specs."""
    out = {}
    for m in models:
        cur = conn.execute(
            """INSERT INTO bike_models (brand, model, year, category, price_cents, stock_qty)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (m["brand"], m["model"], m["year"], m["category"], m["price_cents"], m.get("stock_qty", 0)),
        )
        for std_id in _standard_ids(m["standards"], standards, m["key"]):
            conn.execute(
                "INSERT INTO bike_model_standards (bike_model_id, standard_id) VALUES (?, ?)",
                (cur.lastrowid, std_id),
            )
        out[m["key"]] = (cur.lastrowid, m["standards"])
    return out


def _load_suppliers(conn, suppliers: list, parts: dict) -> None:
    for s in suppliers:
        cur = conn.execute(
            "INSERT INTO suppliers (name, lead_time_days) VALUES (?, ?)",
            (s["name"], s["lead_time_days"]),
        )
        for sp in s.get("parts", []):
            if sp["sku"] not in parts:
                raise SeedError(f"supplier {s['name']}: unknown SKU {sp['sku']}")
            conn.execute(
                """INSERT INTO supplier_parts (supplier_id, part_id, unit_cost_cents, available_qty)
                   VALUES (?, ?, ?, ?)""",
                (cur.lastrowid, parts[sp["sku"]], sp["unit_cost_cents"], sp["available_qty"]),
            )


def _load_customers(conn, customers: list, models: dict, standards: dict) -> None:
    for c in customers:
        cur = conn.execute("INSERT INTO customers (name, email) VALUES (?, ?)", (c["name"], c["email"]))
        customer_id = cur.lastrowid
        for b in c.get("bikes", []):
            where = f"{c['email']} / {b.get('nickname')}"
            if "model" in b:
                if b["model"] not in models:
                    raise SeedError(f"{where}: unknown bike model {b['model']}")
                model_id, specs = models[b["model"]]
                specs = {**specs, **b.get("upgrades", {})}
            else:
                if "upgrades" in b:
                    raise SeedError(f"{where}: upgrades need a model; list standards instead")
                model_id, specs = None, b.get("standards", {})
            bike = conn.execute(
                """INSERT INTO customer_bikes (customer_id, bike_model_id, nickname, notes)
                   VALUES (?, ?, ?, ?)""",
                (customer_id, model_id, b.get("nickname"), b.get("notes")),
            )
            for std_id in _standard_ids(specs, standards, where):
                conn.execute(
                    "INSERT INTO bike_standards (customer_bike_id, standard_id) VALUES (?, ?)",
                    (bike.lastrowid, std_id),
                )


def main(argv: list[str]) -> None:
    path = db.db_path()
    if argv == ["--reset"]:
        path.unlink(missing_ok=True)
        db.init(path)
    elif argv:
        raise SystemExit("usage: python -m shop.seed [--reset]")
    elif not path.exists():
        raise SystemExit(f"{path} does not exist. Run `make db` first, or `make reset`.")
    conn = db.connect(path)
    try:
        load(conn)
    except SeedError as e:
        raise SystemExit(f"Seed failed: {e}")
    finally:
        conn.close()
    print(f"Seeded {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
