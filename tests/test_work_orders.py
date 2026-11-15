import pytest

from shop import work_orders as wo
from shop.errors import NotFound, RuleViolation
from shop import messages
from tests.conftest import HERO, HERO_QUOTE


def test_hero_flow_to_approval(conn, quoted, quote_sent):
    assert wo.status(conn, quoted) == "quoted"
    assert wo.total_cents(conn, quoted) == HERO_QUOTE
    assert wo.record_customer_decision(conn, quote_sent, approved=True) == "approved"


def test_customer_can_decline(conn, quoted, quote_sent):
    assert wo.record_customer_decision(conn, quote_sent, approved=False) == "declined"


def test_customer_must_have_been_sent_the_quote(conn, quoted):
    draft = messages.draft_message(conn, quoted, "Your repair comes to $169.98.", include_quote=True)
    with pytest.raises(RuleViolation, match="has not been sent"):
        wo.record_customer_decision(conn, draft.id, approved=True)
    plain = messages.send_draft(conn, messages.draft_message(conn, quoted, "Hi, a quick update").id)
    with pytest.raises(RuleViolation, match="does not carry a quote"):
        wo.record_customer_decision(conn, plain.id, approved=True)
    assert wo.status(conn, quoted) == "quoted"


def test_approval_must_match_the_quoted_amount(conn, quoted, quote_sent):
    conn.execute("UPDATE customer_messages SET quoted_total_cents = 15000 WHERE id = ?", (quote_sent,))
    with pytest.raises(RuleViolation, match=r"shown \$150.00, but the quote is \$169.98"):
        wo.record_customer_decision(conn, quote_sent, approved=True)


def test_customer_decides_only_once(conn, quote_sent):
    wo.record_customer_decision(conn, quote_sent, approved=True)
    with pytest.raises(RuleViolation, match="is approved"):
        wo.record_customer_decision(conn, quote_sent, approved=False)


def test_parts_that_do_not_fit_are_refused(conn, diagnosed):
    with pytest.raises(RuleViolation, match="does not fit this bike: freehub"):
        wo.add_part(conn, diagnosed, "AD-C11-28R")  # the catalog cassette for this model


def test_quote_locks_the_lines(conn, quoted):
    with pytest.raises(RuleViolation, match="cannot add parts: work order .* is quoted"):
        wo.add_part(conn, quoted, "AD-CH11")


def test_cannot_quote_before_diagnosis_or_with_no_lines(conn, bike_of, diagnosed):
    fresh = wo.open_work_order(conn, bike_of(HERO), "Squeaky brakes")
    with pytest.raises(RuleViolation, match="is intake"):
        wo.lock_quote(conn, fresh)
    with pytest.raises(RuleViolation, match="no lines"):
        wo.lock_quote(conn, diagnosed)


def test_cannot_decide_on_an_unknown_message(conn):
    with pytest.raises(NotFound):
        wo.record_customer_decision(conn, 9999, approved=True)


def test_bad_inputs(conn, bike_of, diagnosed):
    with pytest.raises(NotFound):
        wo.open_work_order(conn, 9999, "Anything")
    with pytest.raises(RuleViolation):
        wo.open_work_order(conn, bike_of(HERO), "  ")
    with pytest.raises(NotFound):
        wo.add_service(conn, diagnosed, "Teleportation")
    with pytest.raises(RuleViolation):
        wo.add_part(conn, diagnosed, "AD-CH11", qty=0)
    with pytest.raises(NotFound):
        wo.status(conn, 9999)
