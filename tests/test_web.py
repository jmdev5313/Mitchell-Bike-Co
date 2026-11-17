"""The web pages are served by the API, and the Customer page gets what it needs."""

from fastapi.testclient import TestClient

from api.app import app
from shop import customer_links, messages
from shop import work_orders as wo
from shop.procurement import create_purchase_order, receive_purchase_order


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    return TestClient(app)


def test_customer_page_and_assets_are_served(conn, tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    page = c.get("/c/any-token")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert page.headers["referrer-policy"] == "no-referrer"
    assert '<script type="module" src="/static/js/customer.js">' in page.text
    assert "Stripe test mode" in page.text  # the demo footer
    for asset in ("/static/css/shop.css", "/static/js/customer.js", "/static/js/dom.js"):
        assert c.get(asset).status_code == 200, asset


def test_customer_view_has_the_timeline(conn, tmp_path, monkeypatch, approved):
    velo = conn.execute("SELECT id FROM suppliers WHERE name = 'Velo Supply Co.'").fetchone()[0]
    receive_purchase_order(conn, create_purchase_order(conn, approved, velo, [("AD-C11-34W", 1)]).id)
    wo.schedule_repair(conn, approved, "2026-11-19")
    wo.start_repair(conn, approved)
    wo.finish_repair(conn, approved)
    view = client(tmp_path, monkeypatch).get(f"/api/customer/{customer_links.link_token(conn, approved)}").json()
    assert view["work_order_id"] == approved
    t = view["timeline"]
    assert t["decided_at"] and t["parts_ordered"] and t["parts_received_at"] and t["finished_at"]
    assert t["paid_at"] is None
    assert [line["category"] for line in view["quote"]["lines"]] == ["cassette", "chain", "labor"]


def test_drafts_never_reach_the_customer_page_data(conn, tmp_path, monkeypatch, quoted, quote_sent):
    messages.draft_message(conn, quoted, "Internal: check the rotor too")
    view = client(tmp_path, monkeypatch).get(f"/api/customer/{customer_links.link_token(conn, quoted)}").json()
    assert all("Internal" not in m["body"] for m in view["messages"])
