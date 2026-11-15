import shutil

import pytest

from shop import db, seed
from tests.conftest import HERO, STOCK_ARC


def bike_specs(conn, bike_id):
    return {
        row["kind"]: row["name"]
        for row in conn.execute(
            """SELECT s.kind, s.name FROM bike_standards bs JOIN standards s ON s.id = bs.standard_id
               WHERE bs.customer_bike_id = ?""",
            (bike_id,),
        )
    }


def test_seed_loads_every_area(conn):
    for table in ("standards", "standard_compat", "parts", "part_requirements", "services",
                  "bike_models", "bike_model_standards", "suppliers", "supplier_parts",
                  "customers", "customer_bikes", "bike_standards", "service_records"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0, table


def test_upgrades_override_the_model_specs(conn, bike_of):
    hero, stock = bike_specs(conn, bike_of(HERO)), bike_specs(conn, bike_of(STOCK_ARC))
    assert hero["freehub"] == "Shimano HG 8-10 speed"
    assert stock["freehub"] == "Shimano HG 11-speed road"
    assert {k: v for k, v in hero.items() if k != "freehub"} == {
        k: v for k, v in stock.items() if k != "freehub"
    }


def test_seeding_twice_is_refused(conn):
    with pytest.raises(seed.SeedError, match="already has data"):
        seed.load(conn)


def test_unknown_standard_is_reported(tmp_path):
    seed_dir = tmp_path / "seed"
    shutil.copytree(seed.SEED_DIR, seed_dir)
    catalog = seed_dir / "catalog.yaml"
    catalog.write_text(catalog.read_text().replace("wheel_size: 650b", "wheel_size: 29er", 1))
    conn = db.connect(db.init(tmp_path / "shop.db"))
    with pytest.raises(seed.SeedError, match="unknown standard wheel_size: 29er"):
        seed.load(conn, seed_dir)
    assert conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0] == 0  # rolled back
    conn.close()


def test_hero_service_history(conn, bike_of):
    rows = conn.execute(
        "SELECT serviced_on, odometer_km FROM service_records WHERE customer_bike_id = ? ORDER BY serviced_on",
        (bike_of(HERO),),
    ).fetchall()
    assert [(r["serviced_on"], r["odometer_km"]) for r in rows] == [
        ("2023-05-20", 600), ("2024-07-14", 5000), ("2025-03-08", 6900)
    ]
