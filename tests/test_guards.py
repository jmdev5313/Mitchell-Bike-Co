"""The hosted demo's limits on the live Agent: budgets, turns per shop, new shops per network, the off switch."""

from contextlib import closing
from datetime import UTC, datetime

from agents.pricing import cost_micros
from api import guards, sandboxes
from tests.test_agent_runtime import message, text
from tests.test_sandboxes import STAFF, client, model, new_visitor, opened, sandbox_files  # noqa: F401 - fixtures

HERO_USAGE = {"input_tokens": 26, "output_tokens": 2513, "cache_creation_input_tokens": 13941,
              "cache_read_input_tokens": 83661}


def test_costs_are_counted_in_whole_micro_dollars():
    assert cost_micros("claude-sonnet-5-5", HERO_USAGE) == 68401  # the hero run: about 6.8 cents
    assert cost_micros("claude-sonnet-5-5", {"output_tokens": 1}) == 10
    assert cost_micros("claude-sonnet-5-5", {"cache_read_input_tokens": 1}) == 1  # rounded up
    assert cost_micros("some-new-model", {"output_tokens": 1}) == 20  # priced as the dearest listed


def start_chat(client) -> str:
    return client.post("/api/conversations", headers=STAFF).json()["conversation_id"]


def say(client, conversation: str, words: str = "Emma's bike"):
    return client.post(f"/api/conversations/{conversation}/messages", headers=STAFF, data={"text": words})


def spend(sandbox: str, dollars: int, at: datetime | None = None) -> None:
    with closing(guards.connect()) as conn, conn:
        conn.execute("INSERT INTO agent_turns (sandbox, conversation_id, model, cost_micros, at) VALUES (?, ?, ?, ?, ?)",
                     (sandbox, "c", "claude-sonnet-5-5", dollars * 1_000_000, (at or datetime.now(UTC)).isoformat()))


def test_each_turn_is_charged_to_the_ledger(client, model):
    key = new_visitor(client)
    conversation = start_chat(client)
    model.responses.append(message(text("Hello.")))
    assert "event: reply" in say(client, conversation).text
    with closing(guards.connect()) as conn:
        row = conn.execute("SELECT sandbox, conversation_id, cost_micros FROM agent_turns").fetchone()
    # FakeModel's usage: 100 input, 20 output, 50 cache read
    assert tuple(row) == (key, conversation, cost_micros("claude-sonnet-5-5",
                          {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50}))


def test_the_daily_budget_stops_new_turns(client, model):
    new_visitor(client)
    conversation = start_chat(client)
    assert client.get("/api/demo").json()["agent"] == {"live": True, "reason": None}
    spend("someone-else", 1)  # $1: the default daily budget, used by another visitor
    refused = say(client, conversation)
    assert refused.status_code == 429 and "today's budget" in refused.json()["detail"]
    assert client.get("/api/demo").json()["agent"]["live"] is False
    assert model.requests == []  # the model was never called


def test_the_monthly_budget_stops_new_turns(client, monkeypatch):
    monkeypatch.setenv("AGENT_DAILY_BUDGET_CENTS", "100000")
    new_visitor(client)
    conversation = start_chat(client)
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spend("someone-else", 18, at=month_start)
    refused = say(client, conversation)
    assert refused.status_code == 429 and "this month's budget" in refused.json()["detail"]


def test_last_months_spending_does_not_count(client, model):
    new_visitor(client)
    conversation = start_chat(client)
    spend("someone-else", 50, at=datetime(2020, 1, 15, tzinfo=UTC))
    model.responses.append(message(text("Hello.")))
    assert say(client, conversation).status_code == 200


def test_each_shop_gets_a_limited_number_of_turns(client, model, monkeypatch):
    monkeypatch.setenv("AGENT_TURNS_PER_SANDBOX", "1")
    new_visitor(client)
    conversation = start_chat(client)
    model.responses.append(message(text("Hello.")))
    assert say(client, conversation).status_code == 200
    refused = say(client, conversation, "And again")
    assert refused.status_code == 429 and "used its 1 Agent turns" in refused.json()["detail"]
    client.post("/api/demo/reset")  # resetting the shop doesn't hand out more turns
    assert say(client, start_chat(client)).status_code == 429

    new_visitor(client)  # someone else still can
    model.responses.append(message(text("Hi.")))
    assert say(client, start_chat(client)).status_code == 200


def test_the_live_agent_can_be_switched_off(client, monkeypatch):
    new_visitor(client)
    conversation = start_chat(client)
    monkeypatch.setenv("AGENT_LIVE", "0")
    refused = say(client, conversation)
    assert refused.status_code == 503 and "switched off" in refused.json()["detail"]


def test_messages_have_a_length_limit(client):
    new_visitor(client)
    assert say(client, start_chat(client), "x" * 4001).status_code == 422


def test_a_network_can_only_start_so_many_shops_an_hour(client, tmp_path, monkeypatch):
    monkeypatch.setenv("NEW_SANDBOXES_PER_HOUR", "2")
    new_visitor(client)
    new_visitor(client)
    before = sandbox_files(tmp_path)
    client.cookies.clear()
    refused = client.post("/api/demo/stories/hero/start")
    assert refused.status_code == 429 and "Too many new demos" in refused.json()["detail"]
    assert "set-cookie" not in refused.headers and sandbox_files(tmp_path) == before
    assert client.get("/api/demo").status_code == 200  # looking is still fine


def test_networks_are_told_apart_by_the_proxys_header(client, monkeypatch):
    monkeypatch.setenv("NEW_SANDBOXES_PER_HOUR", "1")
    monkeypatch.setenv("CLIENT_IP_HEADER", "Fly-Client-IP")
    client.cookies.clear()
    assert client.post("/api/demo/reset", headers={"Fly-Client-IP": "203.0.113.1"}).status_code == 200
    client.cookies.clear()
    assert client.post("/api/demo/reset", headers={"Fly-Client-IP": "203.0.113.1"}).status_code == 429
    client.cookies.clear()
    assert client.post("/api/demo/reset", headers={"Fly-Client-IP": "198.51.100.7"}).status_code == 200
    with closing(guards.connect()) as conn:
        networks = [r[0] for r in conn.execute("SELECT network FROM sandbox_starts")]
    assert not any("203.0.113.1" in n or "198.51.100.7" in n for n in networks)  # addresses aren't stored


def test_on_a_laptop_there_is_no_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("SANDBOXES", raising=False)
    monkeypatch.delenv("AGENT_LIVE", raising=False)
    monkeypatch.setenv("SANDBOX_DIR", str(tmp_path))
    assert guards.agent_refusal(None) is None
    assert guards.record_turn(None, "c", "claude-sonnet-5-5", HERO_USAGE) == 68401
    assert not (tmp_path / "control.db").exists()
    assert sandboxes.current_key() is None
