import pytest

from shop import work_orders as wo
from shop.errors import NotFound, RuleViolation
from tests.conftest import HERO, HERO_QUOTE


def test_hero_flow_to_approval(conn, quoted):
    assert wo.status(conn, quoted) == "quoted"
    assert wo.total_cents(conn, quoted) == HERO_QUOTE
    assert wo.record_customer_decision(conn, quoted, approved=True, total_cents_seen=HERO_QUOTE) == "approved"


def test_customer_can_decline(conn, quoted):
    assert wo.record_customer_decision(conn, quoted, approved=False, total_cents_seen=HERO_QUOTE) == "declined"


def test_approval_must_match_the_quoted_amount(conn, quoted):
    with pytest.raises(RuleViolation, match=r"answered a quote of \$150.00, but the quote is \$169.98"):
        wo.record_customer_decision(conn, quoted, approved=True, total_cents_seen=15000)
    assert wo.status(conn, quoted) == "quoted"


def test_parts_that_do_not_fit_are_refused(conn, diagnosed):
    with pytest.raises(RuleViolation, match="does not fit this bike: freehub"):
        wo.add_part(conn, diagnosed, "AD-C11-28R")  # the catalog cassette for this model


def test_quote_locks_the_lines(conn, quoted):
    with pytest.raises(RuleViolation, match="cannot add parts: work order .* is quoted"):
        wo.add_part(conn, quoted, "AD-CH11")


def test_cannot_quote_before_diagnosis_or_with_no_lines(conn, bike_of, diagnosed):
    fresh = wo.open_work_order(conn, bike_of(HERO), "Squeaky brakes")
    with pytest.raises(RuleViolation, match="is intake"):
        wo.send_quote(conn, fresh)
    with pytest.raises(RuleViolation, match="no lines"):
        wo.send_quote(conn, diagnosed)


def test_cannot_decide_before_a_quote(conn, diagnosed):
    with pytest.raises(RuleViolation, match="is diagnosed"):
        wo.record_customer_decision(conn, diagnosed, approved=True, total_cents_seen=0)


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
