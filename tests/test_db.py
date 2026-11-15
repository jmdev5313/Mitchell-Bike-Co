from shop import db


def test_init_creates_all_tables(tmp_path):
    path = db.init(tmp_path / "shop.db")
    conn = db.connect(path)
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    conn.close()
    assert {"standards", "parts", "customer_bikes", "work_orders", "purchase_orders", "audit_log"} <= tables
