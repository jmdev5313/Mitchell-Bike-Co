"""The HTTP API, through FastAPI's test client."""

import pytest
from fastapi.testclient import TestClient

from api.app import app
from shop import customer_links, messages
from shop import work_orders as wo
from shop.procurement import create_purchase_order
from tests.conftest import HERO_QUOTE

PASSCODE = "test-passcode"
STAFF = {"Authorization": f"Bearer {PASSCODE}"}


@pytest.fixture
def client(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    monkeypatch.setenv("STAFF_PASSCODE", PASSCODE)
    return TestClient(app)


def test_staff_endpoints_need_the_passcode(client, monkeypatch):
    assert client.get("/api/work-orders").status_code == 401
    assert client.get("/api/work-orders", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/work-orders", headers=STAFF).status_code == 200
    monkeypatch.delenv("STAFF_PASSCODE")
    assert client.get("/api/work-orders", headers=STAFF).status_code == 503  # fails closed


def test_mechanic_reviews_and_sends_the_quote(client, conn, quoted):
    draft = messages.draft_message(conn, quoted, "Your repair is $169.98.", include_quote=True)

    orders = client.get("/api/work-orders", headers=STAFF).json()
    assert [(o["id"], o["status"], o["customer"]) for o in orders] == [(quoted, "quoted", "Emma Clark")]

    detail = client.get(f"/api/work-orders/{quoted}", headers=STAFF).json()
    assert detail["bike"]["differs_from_catalog_model"][0]["kind"] == "freehub"
    assert [m["status"] for m in detail["messages"]] == ["draft"]
    assert detail["customer_link_token"] is None

    edited = client.patch(f"/api/messages/{draft.id}", headers=STAFF, json={"body": "Hi Emma, it's $169.98."})
    assert edited.json()["body"] == "Hi Emma, it's $169.98."
    sent = client.post(f"/api/messages/{draft.id}/send", headers=STAFF).json()
    assert sent["message"]["status"] == "sent"
    assert sent["customer_link_token"] == customer_links.link_token(conn, quoted)


def test_rule_refusals_are_409_with_the_reason(client, conn, quote_sent):
    response = client.patch(f"/api/messages/{quote_sent}", headers=STAFF, json={"body": "too late"})
    assert response.status_code == 409
    assert response.json() == {"detail": f"message {quote_sent} is sent; only drafts can be edited"}
    assert client.get("/api/work-orders/9999", headers=STAFF).status_code == 404


def test_customer_sees_only_sent_messages_and_approves(client, conn, quoted, quote_sent):
    messages.draft_message(conn, quoted, "Internal draft the customer must not see")
    token = customer_links.link_token(conn, quoted)

    view = client.get(f"/api/customer/{token}").json()
    assert view["customer"] == "Emma Clark" and view["status"] == "quoted"
    assert [m["body"] for m in view["messages"]] == ["Your repair comes to $169.98."]
    assert view["quote"]["total_cents"] == HERO_QUOTE
    assert view["open_quote_message_id"] == quote_sent
    assert "diagnosis" not in view

    approved = client.post(f"/api/customer/{token}/messages/{quote_sent}/decision", json={"approved": True})
    assert approved.json()["status"] == "approved"
    assert approved.json()["open_quote_message_id"] is None

    replied = client.post(f"/api/customer/{token}/replies", json={"body": "Thanks! Friday works."})
    assert replied.json()["messages"][-1] == {
        "id": replied.json()["messages"][-1]["id"], "from": "you", "body": "Thanks! Friday works.",
        "quoted_total_cents": None, "at": replied.json()["messages"][-1]["at"],
    }


def test_customer_links_cannot_reach_other_work_orders(client, conn, bike_of, quoted, quote_sent):
    other = wo.open_work_order(conn, bike_of("grace.lee@example.com"), "Squeaky brakes")
    other_token = customer_links.link_token(conn, other)
    response = client.post(f"/api/customer/{other_token}/messages/{quote_sent}/decision", json={"approved": True})
    assert response.status_code == 404
    assert wo.status(conn, quoted) == "quoted"
    assert client.get("/api/customer/not-a-real-token").status_code == 404


def test_after_approval_the_mechanic_runs_the_repair(client, conn, approved):
    velo = conn.execute("SELECT id FROM suppliers WHERE name = 'Velo Supply Co.'").fetchone()[0]
    po = create_purchase_order(conn, approved, velo, [("AD-C11-34W", 1)])

    early = client.post(f"/api/work-orders/{approved}/schedule", headers=STAFF, json={"scheduled_for": "2026-11-19"})
    assert early.status_code == 409 and "parts are not in yet" in early.json()["detail"]

    # The last part in: the shop books the repair for today and starts it.
    assert client.post(f"/api/purchase-orders/{po.id}/receive", headers=STAFF).json() == {
        "status": "received", "repair_started": True}
    order = client.get(f"/api/work-orders/{approved}", headers=STAFF).json()
    assert order["status"] == "in_progress" and order["next_step"]["action"]["kind"] == "finish"
    assert [e["kind"] for e in order["history"]][-2:] == ["parts_received", "repair_started"]
    assert order["history"][-1]["actor"] == "shop"
    done = client.post(f"/api/work-orders/{approved}/finish", headers=STAFF).json()
    assert done["status"] == "done" and done["purchase_orders"][0]["status"] == "received"


def test_health_and_docs(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/customer/{token}" in paths and "/api/work-orders/{work_order_id}/finish" in paths
