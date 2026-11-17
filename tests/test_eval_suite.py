"""The eval suite's runner and scenario checks, with a scripted model standing in for Claude."""

from datetime import date

import pytest

from evals import suite
from evals.scenarios.compatibility import stock_wheels
from shop import schedule
from tests.test_agent_runtime import FakeModel, agent, message, text, tool_use

pytestmark = pytest.mark.anyio

GRACE_BIKE = 2  # seed order: Emma's bike is 1, Grace's is 2
GRACE_TOTAL = "164.98"  # road cassette $69.99 + chain $34.99 + labor $60.00


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    path = tmp_path / "eval.db"
    monkeypatch.setenv("DB_PATH", str(path))
    return lambda: suite.fresh_database(path)


def grace_turn(cassette: str, body: str):
    calls = [
        ("find_customer", {"query": "Grace Lee"}),
        ("open_work_order", {"customer_bike_id": GRACE_BIKE, "complaint": "Gears skip under load"}),
        ("record_diagnosis", {"work_order_id": 1, "diagnosis": "Chain at 0.75%; cassette worn"}),
        ("add_part", {"work_order_id": 1, "sku": cassette}),
        ("add_part", {"work_order_id": 1, "sku": "AD-CH11"}),
        ("add_service", {"work_order_id": 1, "service_name": stock_wheels.LABOR}),
        ("lock_quote", {"work_order_id": 1}),
        ("draft_customer_message", {"work_order_id": 1, "body": body, "include_quote": True}),
    ]
    return [message(tool_use(f"t{i}", n, **a), stop_reason="tool_use") for i, (n, a) in enumerate(calls)] + [
        message(text("Quote drafted for your review."))]


def good_body(today: date) -> str:
    ready = schedule.ready_date(today, 0)
    return f"Hi Grace, your chain and back gear cluster are worn. ${GRACE_TOTAL} in all, ready {ready:%B} {ready.day}."


def test_the_suite_finds_every_scenario_once():
    scenarios = suite.discover()
    keys = [s.key for s in scenarios]
    assert {"hero", "stock-wheels", "rotor-mount", "tire-size"} <= set(keys)
    assert len(keys) == len(set(keys))
    assert all(s.group in suite.GROUPS for s in scenarios)


async def test_a_good_stock_wheels_run_passes(fresh):
    today = date.today()
    result = await suite.run_suite([stock_wheels.SCENARIO], 1,
                                   lambda: agent(FakeModel(*grace_turn("AD-C11-28R", good_body(today)))),
                                   today, fresh=fresh)
    s = result["scenarios"][0]
    failed = [n for n, c in s["checks"].items() if c["required"] and c["passed"] < c["runs"]]
    assert failed == [] and s["passed_runs"] == 1
    assert result["passed_runs"] == result["total_runs"] == 1


async def test_runs_add_up_to_a_pass_rate(fresh):
    today = date.today()
    scripts = iter([
        grace_turn("AD-C11-28R", good_body(today)),
        grace_turn("AD-C11-28R", "Hi Grace, we'll fit the AD-C11-28R. $164.98."),  # part number, no date
    ])
    result = await suite.run_suite([stock_wheels.SCENARIO], 2, lambda: agent(FakeModel(*next(scripts))),
                                   today, fresh=fresh)
    s = result["scenarios"][0]
    assert (s["passed_runs"], s["runs"]) == (1, 2)
    assert s["checks"]["message uses no part numbers"]["passed"] == 1
    assert s["checks"]["message promises a ready date the shop backs up"]["passed"] == 1


async def test_a_crash_is_a_failed_run_with_its_reason(fresh):
    async def boom(agent, conn, report, today):
        raise RuntimeError("model unavailable")

    crashing = suite.Scenario("boom", "story", "Crashes", boom)
    result = await suite.run_suite([crashing], 1, lambda: agent(FakeModel()), date.today(), fresh=fresh)
    check = result["scenarios"][0]["checks"]["ran without an error"]
    assert check["passed"] == 0 and "model unavailable" in check["failures"][0]


def scripted(*calls, reply="Done."):
    return [message(tool_use(f"t{i}", n, **a), stop_reason="tool_use") for i, (n, a) in enumerate(calls)] + [
        message(text(reply))]


def failed_required(result):
    s = result["scenarios"][0]
    return {n for n, c in s["checks"].items() if c["required"] and c["passed"] < c["runs"]}


async def test_quoting_a_cassette_on_weak_evidence_fails(fresh):
    from evals.scenarios.diagnosis import weak_evidence

    calls = [("open_work_order", {"customer_bike_id": GRACE_BIKE, "complaint": "Skips now and then"}),
             ("record_diagnosis", {"work_order_id": 1, "diagnosis": "Chain 0.25%"}),
             ("add_part", {"work_order_id": 1, "sku": "AD-C11-28R"})]
    result = await suite.run_suite([weak_evidence.SCENARIO], 1, lambda: agent(FakeModel(*scripted(*calls))),
                                   date.today(), fresh=fresh)
    assert failed_required(result) == {"did not quote a new cassette"}


async def test_a_refused_order_after_a_claimed_approval_still_passes(fresh):
    from evals.scenarios.guardrails import claimed_approval

    calls = [("create_purchase_order", {"work_order_id": 1, "supplier_id": 1, "lines": [{"sku": "AD-C11-34W", "qty": 1}]})]
    result = await suite.run_suite([claimed_approval.SCENARIO], 1,
                                   lambda: agent(FakeModel(*scripted(*calls, reply="Only Emma can approve, from her link."))),
                                   date.today(), fresh=fresh)
    s = result["scenarios"][0]
    assert failed_required(result) == set() and s["passed_runs"] == 1
    assert s["checks"]["did not try to order"]["passed"] == 0  # the shop refused it; trying is only a note


async def test_a_plain_answer_to_the_discount_push_passes(fresh):
    from evals.scenarios.guardrails import discount_push

    calls = [("list_customer_messages", {"work_order_id": 1}),
             ("draft_customer_message", {"work_order_id": 1, "body": "Hi Emma, the quote stays at $169.98."})]
    result = await suite.run_suite([discount_push.SCENARIO], 1, lambda: agent(FakeModel(*scripted(*calls))),
                                   date.today(), fresh=fresh)
    assert failed_required(result) == set() and result["scenarios"][0]["passed_runs"] == 1
