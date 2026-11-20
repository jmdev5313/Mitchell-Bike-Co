"""Paying through the Customer link, with Stripe's responses faked."""

import hashlib
import hmac
import json
import shutil
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.deps import get_stripe
from shop import customer_links, events, payments
from shop import work_orders as wo
from shop.procurement import create_purchase_order, receive_purchase_order
from tests.conftest import HERO_QUOTE


class FakeStripe:
    """Stands in for stripe.StripeClient: records sessions and refunds, and lets a test pay or expire a session."""

    def __init__(self):
        self.sessions: dict[str, SimpleNamespace] = {}
        self.created: list[tuple[dict, dict]] = []
        self.refunded: list[tuple[dict, dict]] = []
        self.v1 = SimpleNamespace(checkout=SimpleNamespace(sessions=self),
                                  refunds=SimpleNamespace(create=self.refund))

    def create(self, params, options=None):
        self.created.append((params, options or {}))
        n = len(self.sessions) + 1
        session = SimpleNamespace(
            id=f"cs_test_{n}",
            url=f"https://checkout.stripe.com/c/pay/cs_test_{n}",
            client_reference_id=params["client_reference_id"],
            currency=params["line_items"][0]["price_data"]["currency"],
            amount_total=params["line_items"][0]["price_data"]["unit_amount"],
            metadata=params["metadata"],
            status="open",
            payment_status="unpaid",
            payment_intent=None,
        )
        self.sessions[session.id] = session
        return session

    def retrieve(self, session_id):
        return self.sessions[session_id]

    def pay(self, session_id):
        session = self.sessions[session_id]
        session.status, session.payment_status, session.payment_intent = "complete", "paid", f"pi_{session_id}"

    def expire(self, session_id):
        self.sessions[session_id].status = "expired"

    def refund(self, params, options=None):
        self.refunded.append((params, options or {}))
        intent = params["payment_intent"]
        session = next(s for s in self.sessions.values() if s.payment_intent == intent)
        return SimpleNamespace(id=f"re_{len(self.refunded)}", amount=session.amount_total, status="succeeded")

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


# One open checkout per repair, and a duplicate payment is refunded

def test_a_second_checkout_reuses_the_open_one(client, conn, done, stripe_fake):
    token = customer_links.link_token(conn, done)
    first = client.post(f"/api/customer/{token}/checkout").json()
    second = client.post(f"/api/customer/{token}/checkout").json()  # another tab, or a second click
    assert second == first and len(stripe_fake.created) == 1
    assert [p.status for p in payments.list_payments(conn, done)] == ["pending"]


def test_an_expired_checkout_is_abandoned_and_replaced(client, conn, done, stripe_fake):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.expire("cs_test_1")
    again = client.post(f"/api/customer/{token}/checkout").json()
    assert again["checkout_url"].endswith("cs_test_2")
    assert [p.status for p in payments.list_payments(conn, done)] == ["failed", "pending"]


def test_a_checkout_paid_since_we_looked_is_recorded_not_reopened(client, conn, done, stripe_fake):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.pay("cs_test_1")  # paid, but the Customer never came back
    response = client.post(f"/api/customer/{token}/checkout")
    assert response.status_code == 409 and "already paid" in response.json()["detail"]
    assert wo.status(conn, done) == "paid" and len(stripe_fake.created) == 1


def test_a_payment_still_processing_blocks_another_checkout(client, conn, done, stripe_fake):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.sessions["cs_test_1"].status = "complete"  # a bank debit, say: done at Stripe, money not in yet
    response = client.post(f"/api/customer/{token}/checkout")
    assert response.status_code == 409 and "being processed" in response.json()["detail"]


def test_a_duplicate_payment_is_refunded_once(client, conn, done, stripe_fake):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    # A second checkout that slipped past the one-open-checkout rule (say, two clicks at the same instant).
    duplicate = payments.start_payment(conn, done)
    payments.attach_checkout_session(conn, duplicate.id, stripe_fake.create(
        {**stripe_fake.created[0][0]}, {}).id)
    stripe_fake.pay("cs_test_1")
    stripe_fake.pay("cs_test_2")

    for session_id in ("cs_test_1", "cs_test_2", "cs_test_2"):  # the second one comes back twice
        client.get(f"/api/customer/{token}/checkout/return", params={"session_id": session_id}, follow_redirects=False)

    assert [p.status for p in payments.list_payments(conn, done)] == ["paid", "refunded"]
    assert wo.status(conn, done) == "paid"
    [(params, options)] = stripe_fake.refunded
    assert params["payment_intent"] == "pi_cs_test_2" and params["reason"] == "duplicate"
    assert options["idempotency_key"] == "mitchell-refund-cs_test_2"
    assert [e["kind"] for e in events.history(conn, done)][-2:] == ["paid", "refunded"]


# Stripe's webhook

SECRET = "whsec_test_secret"


def signed(payload: str, secret: str = SECRET) -> dict[str, str]:
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.{payload}".encode(), hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"}


def event(kind: str, session: SimpleNamespace | dict) -> str:
    obj = session if isinstance(session, dict) else {"id": session.id, "object": "checkout.session",
                                                       "metadata": session.metadata}
    return json.dumps({"id": "evt_test", "object": "event", "type": kind, "data": {"object": obj}})


@pytest.fixture
def hook(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    def send(payload: str, headers: dict | None = None):
        return client.post("/api/stripe/webhook", content=payload, headers=headers or signed(payload))

    return send


def test_the_webhook_records_a_payment_the_customer_never_came_back_from(client, conn, done, stripe_fake, hook):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.pay("cs_test_1")
    response = hook(event("checkout.session.completed", stripe_fake.sessions["cs_test_1"]))
    assert response.status_code == 200 and response.json()["payment"] == "paid"
    assert wo.status(conn, done) == "paid"
    # Stripe retries, and the Customer's return link arrives late: still one payment.
    assert hook(event("checkout.session.completed", stripe_fake.sessions["cs_test_1"])).json()["payment"] == "paid"
    client.get(f"/api/customer/{token}/checkout/return", params={"session_id": "cs_test_1"}, follow_redirects=False)
    assert [p.status for p in payments.list_payments(conn, done)] == ["paid"]


def test_the_webhook_asks_stripe_rather_than_trusting_the_event(client, conn, done, stripe_fake, hook):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    # A correctly signed event, but Stripe says the session isn't paid: nothing is recorded.
    assert hook(event("checkout.session.completed", stripe_fake.sessions["cs_test_1"])).json()["payment"] == "pending"
    assert wo.status(conn, done) == "done"


def test_expired_and_failed_checkouts_are_abandoned(client, conn, done, stripe_fake, hook):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.expire("cs_test_1")
    assert hook(event("checkout.session.expired", stripe_fake.sessions["cs_test_1"])).json()["payment"] == "failed"

    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.sessions["cs_test_2"].status = "complete"  # a bank debit that later bounced
    assert hook(event("checkout.session.async_payment_failed", stripe_fake.sessions["cs_test_2"])).json()["payment"] == "failed"
    assert client.get(f"/api/customer/{token}").json()["can_pay"] is True


def test_the_webhook_refuses_a_bad_signature(client, conn, done, stripe_fake, hook):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.pay("cs_test_1")
    payload = event("checkout.session.completed", stripe_fake.sessions["cs_test_1"])
    assert hook(payload, signed(payload, "whsec_someone_else")).status_code == 400
    assert hook(payload, {"Content-Type": "application/json"}).status_code == 400
    assert wo.status(conn, done) == "done"


def test_the_webhook_needs_its_secret(client, monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    payload = event("checkout.session.completed", {"id": "cs_test_1"})
    assert client.post("/api/stripe/webhook", content=payload, headers=signed(payload)).status_code == 503


def test_the_webhook_ignores_what_isnt_the_shops(hook):
    assert hook(event("checkout.session.completed", {"id": "cs_from_another_app"})).json()["ignored"]
    assert hook(event("customer.created", {"id": "cus_1"})).json()["ignored"]


def test_in_the_hosted_demo_the_webhook_finds_the_visitors_sandbox(client, conn, done, stripe_fake, hook,
                                                                  tmp_path, monkeypatch):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    stripe_fake.pay("cs_test_1")
    key = "0123456789abcdef0123456789abcdef"
    (tmp_path / "sandboxes").mkdir()
    sandbox = tmp_path / "sandboxes" / f"{key}.db"
    shutil.copy(tmp_path / "shop.db", sandbox)
    monkeypatch.setenv("SANDBOXES", "1")
    monkeypatch.setenv("SANDBOX_DIR", str(tmp_path / "sandboxes"))

    elsewhere = {"id": "cs_test_1", "metadata": {"sandbox": "f" * 32}}
    assert hook(event("checkout.session.completed", elsewhere)).json()["ignored"]
    files = set((tmp_path / "sandboxes").iterdir())
    response = hook(event("checkout.session.completed", {"id": "cs_test_1", "metadata": {"sandbox": key}}))
    assert response.json()["payment"] == "paid"
    assert set((tmp_path / "sandboxes").iterdir()) == files  # no sandbox was made for Stripe
    assert wo.status(conn, done) == "done"  # the shared database is untouched...
    from shop import db
    with db.connect(sandbox) as theirs:  # ...and the visitor's shop is paid
        assert wo.status(theirs, done) == "paid"


def test_sessions_carry_the_sandbox_only_in_the_hosted_demo(client, conn, done, stripe_fake):
    token = customer_links.link_token(conn, done)
    client.post(f"/api/customer/{token}/checkout")
    assert "sandbox" not in stripe_fake.created[0][0]["metadata"]
