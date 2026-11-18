"""The live check's judging logic, with a scripted model standing in for Claude."""

from datetime import date

import pytest

from evals import hero
from agents.pricing import cost_usd
from shop import schedule
from tests.test_agent_runtime import FakeModel, agent, message, text, tool_use

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def test_db(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))


def turn_one(body: str, plan_supplier: int = 1):
    """The tool calls a good Agent makes in turn 1 (ids follow the seed order)."""
    calls = [
        ("find_customer", {"query": "Emma Clark"}),
        ("get_bike", {"customer_bike_id": 1}),
        ("list_fitting_parts", {"customer_bike_id": 1, "category": "cassette"}),
        ("open_work_order", {"customer_bike_id": 1, "complaint": "Gears skip under load"}),
        ("record_diagnosis", {"work_order_id": 1, "diagnosis": "Chain at 0.75%; cassette worn"}),
        ("add_part", {"work_order_id": 1, "sku": "AD-C11-34W"}),
        ("add_part", {"work_order_id": 1, "sku": "AD-CH11"}),
        ("add_service", {"work_order_id": 1, "service_name": hero.LABOR}),
        ("lock_quote", {"work_order_id": 1}),
        ("supplier_options", {"sku": "AD-C11-34W", "qty": 1}),
        ("estimate_ready_date", {"supplier_ids": [1]}),
        ("plan_order", {"work_order_id": 1, "lines": [{"sku": "AD-C11-34W", "supplier_id": plan_supplier, "qty": 1}]}),
        ("draft_customer_message", {"work_order_id": 1, "body": body, "include_quote": True}),
    ]
    return [
        message(tool_use(f"t{i}", name, **args), stop_reason="tool_use") for i, (name, args) in enumerate(calls)
    ] + [message(text("Quote drafted for your review."))]


def turn_two(extra_lines=()):
    """The shop already placed the planned order; the Agent checks, and may order extras."""
    calls = [message(tool_use("o1", "get_work_order", work_order_id=1), stop_reason="tool_use")]
    if extra_lines:
        calls.append(message(tool_use("o2", "create_purchase_order", work_order_id=1, supplier_id=1,
                                      lines=list(extra_lines)), stop_reason="tool_use"))
    return calls + [message(text("The cassette is on order from Velo."))]


def good_body(ready: date) -> str:
    return (f"Hi Emma, the chain and the gear cluster on your back wheel are worn out. Replacing both "
            f"comes to $169.98. Your bike will be ready {ready:%B} {ready.day}.")


async def test_a_good_run_passes():
    today = date.today()
    model = FakeModel(*turn_one(good_body(schedule.ready_date(today, 2))), *turn_two())
    report = await hero.run(lambda: agent(model), today)
    failed = [c.name for c in report.checks if c.required and not c.passed]
    assert failed == [] and report.passed
    assert len(report.turns) == 2
    assert report.usage["input_tokens"] > 0


async def test_wrong_date_and_part_numbers_fail_and_stop_before_ordering():
    today = date.today()
    body = "Hi Emma, we'll swap the AD-C11-34W. $169.98, ready " + (today.replace(year=today.year + 1)).isoformat()
    model = FakeModel(*turn_one(body))
    report = await hero.run(lambda: agent(model), today)
    failed = {c.name for c in report.checks if c.required and not c.passed}
    assert failed == {
        "message uses no part numbers",
        "message promises a ready date the supplier lead time backs up",
        "message promises the plan's ready date",
    }
    assert len(report.turns) == 1  # no approval, so no turn 2


async def test_planning_a_slower_supplier_than_promised_fails():
    today = date.today()
    model = FakeModel(*turn_one(good_body(schedule.ready_date(today, 2)), plan_supplier=2))
    report = await hero.run(lambda: agent(model), today)
    failed = {c.name for c in report.checks if c.required and not c.passed}
    assert failed == {"message promises the plan's ready date"}
    assert len(report.turns) == 1  # not approved, so nothing is ordered


async def test_ordering_the_in_stock_chain_is_only_a_note():
    today = date.today()
    model = FakeModel(*turn_one(good_body(schedule.ready_date(today, 2))),
                      *turn_two(extra_lines=[{"sku": "AD-CH11", "qty": 1}]))
    report = await hero.run(lambda: agent(model), today)
    assert report.passed
    note = next(c for c in report.checks if c.name.startswith("did not order the chain"))
    assert not note.passed and not note.required


def test_cost_estimate():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000,
             "cache_creation_input_tokens": 100_000, "cache_read_input_tokens": 1_000_000}
    assert cost_usd("claude-sonnet-5-5", usage) == pytest.approx(2.00 + 1.00 + 0.25 + 0.10)
    assert cost_usd("some-other-model", usage) is None
