import pytest

from shop import work_orders as wo
from shop.errors import NotFound, RuleViolation
from shop.procurement import create_purchase_order
from tests.conftest import HERO_QUOTE


def supplier_id(conn, name):
    return conn.execute("SELECT id FROM suppliers WHERE name = ?", (name,)).fetchone()["id"]


@pytest.fixture
def velo(conn):
    return supplier_id(conn, "Velo Supply Co.")


@pytest.fixture
def approved(conn, quoted):
    wo.record_customer_decision(conn, quoted, approved=True, total_cents_seen=HERO_QUOTE)
    return quoted


def test_hero_order_after_customer_approval(conn, approved, velo):
    po = create_purchase_order(conn, approved, velo, [("AD-C11-34W", 1)])
    assert po.total_cents == 4250  # the supplier's price, not the customer's
    assert wo.status(conn, approved) == "awaiting_parts"


def test_no_order_before_the_customer_approves(conn, quoted, velo):
    with pytest.raises(RuleViolation, match="after the customer approves the quote"):
        create_purchase_order(conn, quoted, velo, [("AD-C11-34W", 1)])


def test_no_order_after_the_customer_declines(conn, quoted, velo):
    wo.record_customer_decision(conn, quoted, approved=False, total_cents_seen=HERO_QUOTE)
    with pytest.raises(RuleViolation, match="is declined"):
        create_purchase_order(conn, quoted, velo, [("AD-C11-34W", 1)])


def test_only_approved_parts_and_quantities(conn, approved, velo):
    with pytest.raises(RuleViolation, match="leaves 1 to order, asked for 2"):
        create_purchase_order(conn, approved, velo, [("AD-C11-34W", 2)])
    with pytest.raises(RuleViolation, match="leaves 0 to order"):
        create_purchase_order(conn, approved, velo, [("AD-C11-28R", 1)])  # not on the quote


def test_cannot_order_the_same_part_twice(conn, approved, velo):
    create_purchase_order(conn, approved, velo, [("AD-C11-34W", 1)])
    northgate = supplier_id(conn, "Northgate Distribution")
    with pytest.raises(RuleViolation, match="leaves 0 to order"):
        create_purchase_order(conn, approved, northgate, [("AD-C11-34W", 1)])


def test_cancelled_orders_free_up_the_quantity(conn, approved, velo):
    po = create_purchase_order(conn, approved, velo, [("AD-C11-34W", 1)])
    conn.execute("UPDATE purchase_orders SET status = 'cancelled' WHERE id = ?", (po.id,))
    northgate = supplier_id(conn, "Northgate Distribution")
    assert create_purchase_order(conn, approved, northgate, [("AD-C11-34W", 1)]).total_cents == 3900


@pytest.mark.parametrize("lines, error, match", [
    ([], RuleViolation, "at least one line"),
    ([("AD-C11-34W", 0)], RuleViolation, "must be positive"),
    ([("AD-C11-34W", 1), ("AD-C11-34W", 1)], RuleViolation, "more than once"),
    ([("NOPE", 1)], NotFound, "no part"),
])
def test_bad_orders_are_refused(conn, approved, velo, lines, error, match):
    with pytest.raises(error, match=match):
        create_purchase_order(conn, approved, velo, lines)
    assert conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0] == 0


def test_supplier_must_carry_and_have_the_part(conn, approved):
    crankshaft = supplier_id(conn, "Crankshaft Wholesale")
    with pytest.raises(RuleViolation, match="does not carry"):
        create_purchase_order(conn, approved, crankshaft, [("AD-C11-34W", 1)])
    with pytest.raises(NotFound):
        create_purchase_order(conn, approved, 9999, [("AD-C11-34W", 1)])
    with pytest.raises(NotFound):
        create_purchase_order(conn, 9999, crankshaft, [("AD-C11-34W", 1)])
