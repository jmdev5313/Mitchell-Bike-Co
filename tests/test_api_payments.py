"""Paying through the Customer link, with Stripe's responses faked."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.deps import get_stripe
from shop import customer_links, payments
from shop import work_orders as wo
from shop.procurement import create_purchase_order, receive_purchase_order
from tests.conftest import HERO_QUOTE


class FakeStripe:
    """Stands in for stripe.StripeClient: records sessions, and lets a test mark them paid."""

    def __init__(self):
        self.sessions: dict[str, SimpleNamespace] = {}
        self.created: list[tuple[dict, dict]] = []
        self.v1 = SimpleNamespace(checkout=SimpleNamespace(sessions=self))

    def create(self, params, options=None):
        self.created.append((params, options or {}))
        session = SimpleNamespace(
            id=f"cs_test_{len(self.sessions) + 1}",
            url=f"https://checkout.stripe.com/c/pay/cs_test_{len(self.sessions) + 1}",
            client_reference_id=params["client_reference_id"],
            currency=params["line_items"][0]["price_data"]["currency"],
            amount_total=params["line_items"][0]["price_data"]["unit_amount"],
            payment_status="unpaid",
        )
        self.sessions[session.id] = session
        return session

    def retrieve(self, session_id):
        return self.sessions[session_id]

    def pay(self, session_id):
        self.sessions[session_id].payment_status = "paid"


@pytest.fixture
def stripe_fake():
    return FakeStripe()


@pytest.fixture
def client(conn, tmp_path, monkeypatch, stripe_fake):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://shop.test")
    app.dependency_overrides[get_stripe] = lambda: stripe_fake
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def done(conn, approved):
    velo = conn.execute("SELECT id FROM suppliers WHERE name = 'Velo Supply Co.'").fetchone()[0]
    receive_purchase_order(conn, create_purchase_order(conn, approved, velo, [("AD-C11-34W", 1)]).id)
    wo.schedule_repair(conn, approved, "2026-11-19")
    wo.start_repair(conn, approved)
    wo.finish_repair(conn, approved)
    return approved


def test_customer_pays_through_stripe_checkout(client, conn, done, stripe_fake):
    token = customer_links.link_token(conn, done)
    assert client.get(f"/api/customer/{token}").json()["can_pay"] is True

    started = client.post(f"/api/customer/{token}/checkout").json()
    assert started["checkout_url"].startswith("https://checkout.stripe.com/")
    params, options = stripe_fake.created[0]
    assert params["mode"] == "payment" and params["client_reference_id"] == str(done)
    assert params["line_items"][0]["price_data"]["unit_amount"] == HERO_QUOTE
    # Stripe's own page says it's a demo, too: in the item's name and next to its Pay button.
    assert "test mode, no charge" in params["line_items"][0]["price_data"]["product_data"]["name"]
    assert "no real payment is taken" in params["custom_text"]["submit"]["message"]
    assert params["success_url"] == f"http://shop.test/api/customer/{token}/checkout/return?session_id={{CHECKOUT_SESSION_ID}}"
    # The key carries the link token, so a rebuilt database can't reuse an earlier key.
    assert params["cancel_url"] == f"http://shop.test/c/{token}?checkout=cancelled"
    assert options["idempotency_key"] == f"mitchell-{token}-payment-{started['payment_id']}"

    # Coming back before paying changes nothing.
    back = client.get(f"/api/customer/{token}/checkout/return", params={"session_id": "cs_test_1"},
                      follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"] == f"http://shop.test/c/{token}"
    assert wo.status(conn, done) == "done"

    stripe_fake.pay("cs_test_1")
    client.get(f"/api/customer/{token}/checkout/return", params={"session_id": "cs_test_1"}, follow_redirects=False)
    view = client.get(f"/api/customer/{token}").json()
    assert view["paid"] is True and view["can_pay"] is False and view["status"] == "paid"
    assert client.post(f"/api/customer/{token}/checkout").status_code == 409  # already paid


def test_confirm_catches_a_customer_who_closed_the_page(client, conn, done, stripe_fake):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.pay("cs_test_1")
    assert client.post(f"/api/customer/{token}/checkout/confirm").json()["status"] == "paid"


def test_no_checkout_before_the_repair_is_done(client, conn, approved):
    token = customer_links.link_token(conn, approved)
    response = client.post(f"/api/customer/{token}/checkout")
    assert response.status_code == 409 and "once the repair is done" in response.json()["detail"]


def test_sessions_from_another_work_order_are_refused(client, conn, done, bike_of, stripe_fake):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.pay("cs_test_1")
    other = customer_links.link_token(conn, wo.open_work_order(conn, bike_of("grace.lee@example.com"), "Brakes"))
    response = client.get(f"/api/customer/{other}/checkout/return", params={"session_id": "cs_test_1"})
    assert response.status_code == 404
    assert payments.list_payments(conn, done)[0].status == "pending"


def test_a_tampered_session_is_refused(client, conn, done, stripe_fake):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.sessions["cs_test_1"].client_reference_id = "999"
    stripe_fake.pay("cs_test_1")
    response = client.get(f"/api/customer/{token}/checkout/return", params={"session_id": "cs_test_1"})
    assert response.status_code == 409


def test_only_test_mode_keys(conn, tmp_path, monkeypatch, done):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    token = customer_links.link_token(conn, done)
    client = TestClient(app)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_not_allowed")
    response = client.post(f"/api/customer/{token}/checkout")
    assert response.status_code == 503 and "test-mode" in response.json()["detail"]
    monkeypatch.delenv("STRIPE_SECRET_KEY")
    assert client.post(f"/api/customer/{token}/checkout").status_code == 503


def test_stripe_errors_come_back_as_502_with_the_reason(client, conn, done, stripe_fake):
    import stripe

    def refuse(params, options=None):
        raise stripe.IdempotencyError("Keys for idempotent requests can only be used with the same parameters")

    stripe_fake.create = refuse
    token = customer_links.link_token(conn, done)
    response = client.post(f"/api/customer/{token}/checkout")
    assert response.status_code == 502
    assert response.json()["detail"].startswith("Stripe refused the checkout: Keys for idempotent requests")
