import pytest

from shop.errors import NotFound, RuleViolation
from shop.stock import stock_status, supplier_options


def test_hero_cassette_is_out_of_stock(conn):
    assert not stock_status(conn, "AD-C11-34W").in_stock
    assert stock_status(conn, "AD-CH11").in_stock


def test_supplier_options_filter_by_availability(conn):
    options = supplier_options(conn, "AD-C11-34W", 1)
    assert [(o.supplier_name, o.lead_time_days, o.unit_cost_cents) for o in options] == [
        ("Velo Supply Co.", 2, 4250),        # fastest first
        ("Northgate Distribution", 5, 3900),  # cheaper but slower
    ]
    names = [o.supplier_name for o in supplier_options(conn, "AD-C11-34W", 3)]
    assert names == ["Velo Supply Co."]  # Northgate has only 2


def test_supplier_option_total(conn):
    option = supplier_options(conn, "AD-C11-34W", 3)[0]
    assert option.total_cents(3) == 12750


def test_bad_inputs(conn):
    with pytest.raises(NotFound):
        stock_status(conn, "NOPE")
    with pytest.raises(NotFound):
        supplier_options(conn, "NOPE", 1)
    with pytest.raises(RuleViolation):
        supplier_options(conn, "AD-C11-34W", 0)
