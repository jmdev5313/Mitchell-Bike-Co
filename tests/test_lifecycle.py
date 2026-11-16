"""After approval: parts arrive, the repair is done, the customer pays."""

import pytest

from shop import customer_links, payments
from shop import work_orders as wo
from shop.errors import NotFound, RuleViolation
from shop.procurement import create_purchase_order, list_purchase_orders, receive_purchase_order
from tests.conftest import HERO_QUOTE


def stock(conn, sku):
    return conn.execute("SELECT stock_qty FROM parts WHERE sku = ?", (sku,)).fetchone()[0]


@pytest.fixture
def ordered(conn, approved):
    """The hero cassette ordered from Velo. Returns (work order id, purchase order id)."""
    velo = conn.execute("SELECT id FROM suppliers WHERE name = 'Velo Supply Co.'").fetchone()[0]
    po = create_purchase_order(conn, approved, velo, [("AD-C11-34W", 1)])
    return approved, po.id


def test_hero_story_to_paid(conn, ordered):
    work_order_id, po_id = ordered
    receive_purchase_order(conn, po_id)
    assert stock(conn, "AD-C11-34W") == 1
    assert list_purchase_orders(conn, work_order_id)[0]["status"] == "received"

    wo.schedule_repair(conn, work_order_id, "2026-11-19")
    assert wo.summary(conn, work_order_id)["scheduled_for"] == "2026-11-19"
    wo.start_repair(conn, work_order_id)
    chains_before = stock(conn, "AD-CH11")
    wo.finish_repair(conn, work_order_id)
    assert (stock(conn, "AD-C11-34W"), stock(conn, "AD-CH11")) == (0, chains_before - 1)
    assert wo.status(conn, work_order_id) == "done"

    payment = payments.start_payment(conn, work_order_id, stripe_session_id="cs_test_1")
    assert (payment.amount_cents, payment.status) == (HERO_QUOTE, "pending")
    paid = payments.complete_payment(conn, payment.id, HERO_QUOTE)
    assert paid.status == "paid" and paid.paid_at
    assert wo.status(conn, work_order_id) == "paid"


def test_cannot_schedule_before_the_parts_arrive(conn, ordered):
    work_order_id, _ = ordered
    with pytest.raises(RuleViolation, match="parts are not in yet: AD-C11-34W needs 1, 0 in stock"):
        wo.schedule_repair(conn, work_order_id, "2026-11-19")


def test_in_stock_jobs_schedule_straight_after_approval(conn, bike_of):
    from shop import messages
    job = wo.open_work_order(conn, bike_of("grace.lee@example.com"), "New chain please")
    wo.record_diagnosis(conn, job, "Chain at 0.75%")
    wo.add_part(conn, job, "AD-CH11")
    wo.lock_quote(conn, job)
    msg = messages.send_draft(conn, messages.draft_message(conn, job, "$34.99", include_quote=True).id)
    wo.record_customer_decision(conn, msg.id, approved=True)
    wo.schedule_repair(conn, job, "2026-11-17")
    assert wo.status(conn, job) == "scheduled"


def test_steps_happen_in_order(conn, ordered):
    work_order_id, po_id = ordered
    with pytest.raises(RuleViolation, match="cannot start the repair"):
        wo.start_repair(conn, work_order_id)
    with pytest.raises(RuleViolation, match="cannot finish the repair"):
        wo.finish_repair(conn, work_order_id)
    with pytest.raises(RuleViolation, match="payment is taken once the repair is done"):
        payments.start_payment(conn, work_order_id)
    receive_purchase_order(conn, po_id)
    with pytest.raises(RuleViolation, match="received, not ordered"):
        receive_purchase_order(conn, po_id)
    with pytest.raises(RuleViolation, match="must be a date"):
        wo.schedule_repair(conn, work_order_id, "next Tuesday")


def test_finishing_needs_the_stock_still_there(conn, ordered):
    work_order_id, po_id = ordered
    receive_purchase_order(conn, po_id)
    wo.schedule_repair(conn, work_order_id, "2026-11-19")
    wo.start_repair(conn, work_order_id)
    conn.execute("UPDATE parts SET stock_qty = 0 WHERE sku = 'AD-C11-34W'")  # used on another bike
    with pytest.raises(RuleViolation, match="not enough stock to finish"):
        wo.finish_repair(conn, work_order_id)


@pytest.fixture
def done(conn, ordered):
    work_order_id, po_id = ordered
    receive_purchase_order(conn, po_id)
    wo.schedule_repair(conn, work_order_id, "2026-11-19")
    wo.start_repair(conn, work_order_id)
    wo.finish_repair(conn, work_order_id)
    return work_order_id


def test_payment_must_be_the_quoted_amount_and_only_once(conn, done):
    payment = payments.start_payment(conn, done)
    with pytest.raises(RuleViolation, match="received 100 cents"):
        payments.complete_payment(conn, payment.id, 100)
    payments.complete_payment(conn, payment.id, HERO_QUOTE)
    with pytest.raises(RuleViolation, match="paid, not pending"):
        payments.complete_payment(conn, payment.id, HERO_QUOTE)
    with pytest.raises(RuleViolation, match="is paid"):
        payments.start_payment(conn, done)


def test_abandoned_checkouts_do_not_block_payment(conn, done):
    abandoned = payments.start_payment(conn, done, "cs_test_abandoned")
    retry = payments.start_payment(conn, done, "cs_test_retry")
    payments.complete_payment(conn, payments.payment_for_session(conn, "cs_test_retry").id, HERO_QUOTE)
    assert payments.get_payment(conn, abandoned.id).status == "pending"
    assert [p.status for p in payments.list_payments(conn, done)] == ["pending", "paid"]
    assert retry.id != abandoned.id


def test_customer_links(conn, quoted):
    token = customer_links.link_token(conn, quoted)
    assert len(token) >= 32
    assert customer_links.link_token(conn, quoted) == token  # stable once created
    assert customer_links.work_order_for(conn, token) == quoted
    with pytest.raises(NotFound, match="not valid"):
        customer_links.work_order_for(conn, "guess")
    with pytest.raises(NotFound):
        customer_links.link_token(conn, 9999)
    with pytest.raises(NotFound):
        payments.payment_for_session(conn, "cs_unknown")
