"""Recorded runs: the shop's pinned calendar, replaying a recording, and playing one in the hosted demo."""

import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from agents import conversations
from agents.runtime import open_agent
from agents.runtime.replay import NO_REPLY, Recording, Response, Turn
from api import guards, recorded, sandboxes, turnstile
from api.app import app
from demo.record import repair_done_message
from demo.stories import BY_KEY
from shop import clock, db, schedule
from shop import procurement
from shop import work_orders as wo
from tests.conftest import HERO
from tests.test_agent_runtime import FakeModel, agent, in_memory, message, text
from tests.test_guards import spend
from tests.test_sandboxes import STAFF, new_visitor

RECORDED_ON = date(2026, 11, 17)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def shop(conn, tmp_path, monkeypatch):
    """The `conn` fixture's database, made the one the runtime and the shop's servers use."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    return conn


def tool(id, name, **input):
    return {"type": "tool_use", "id": id, "name": name, "input": input}


def hero_recording() -> Recording:
    """A small, hand-written recording of Emma's story: look her up, then reply; later, a reply to "repair done"."""
    opening = BY_KEY["hero"].mechanic_message(RECORDED_ON)
    return Recording(story="hero", model="claude-sonnet-5-5", recorded_on=RECORDED_ON, turns=[
        Turn(opening, photo=True, responses=[
            Response([{"type": "thinking", "thinking": "Finding Emma.", "signature": "sig"},
                      tool("t1", "find_customer", query="clark")], "tool_use", 0.4),
            Response([{"type": "text", "text": "Emma's Arc has upgraded wheels. Quote drafted."}], "end_turn", 0.2),
        ]),
        Turn(repair_done_message(1, "Emma"), responses=[
            Response([{"type": "text", "text": "Draft ready: her bike can be picked up."}], "end_turn", 0.1),
        ]),
    ])


# --- The shop's calendar -------------------------------------------------------------------

def test_the_calendar_is_today_unless_pinned(conn):
    assert clock.today(conn) == date.today()
    clock.pin(conn, RECORDED_ON)
    assert clock.today(conn) == RECORDED_ON


def test_a_pinned_calendar_sets_the_promised_date(conn, quoted):
    clock.pin(conn, RECORDED_ON)
    velo = conn.execute("SELECT id, lead_time_days FROM suppliers WHERE name LIKE 'Velo%'").fetchone()
    procurement.set_order_plan(conn, quoted, [("AD-C11-34W", velo["id"], 1)])
    promised = conn.execute("SELECT promised_ready_on FROM work_orders WHERE id = ?", (quoted,)).fetchone()[0]
    assert promised == schedule.ready_date(RECORDED_ON, velo["lead_time_days"]).isoformat()


# --- Replaying ----------------------------------------------------------------------------

def test_a_recording_survives_saving_and_loading(tmp_path):
    original = hero_recording()
    original.save(tmp_path / "hero.json")
    assert Recording.load(tmp_path / "hero.json") == original


@pytest.mark.anyio
async def test_a_replay_runs_the_recorded_tool_calls_for_real(shop):
    recording = hero_recording()
    async with open_agent("recorded", recording=recording, connect=in_memory, pace=False) as replay:
        result = await replay.send(recording.turns[0].message)
    assert result.reply == "Emma's Arc has upgraded wheels. Quote drafted."
    assert [c.name for c in result.tool_calls] == ["find_customer"]
    assert "Emma Clark" in result.tool_calls[0].result  # a real answer from the shop, not a recorded one
    assert result.progress == ["Finding Emma."]
    assert sum(result.usage.values()) == 0  # nothing spent
    assert shop.execute("SELECT runtime FROM agent_conversations").fetchone()[0] == "recorded"


@pytest.mark.anyio
async def test_a_replay_picks_up_where_the_conversation_is(shop):
    recording = hero_recording()
    async with open_agent("recorded", recording=recording, connect=in_memory, pace=False) as replay:
        await replay.send(recording.turns[0].message)
        conversation = replay.conversation_id
    async with open_agent("recorded", conversation, recording=recording, connect=in_memory, pace=False) as again:
        result = await again.send(recording.turns[1].message)  # reopened between turns
    assert result.reply == "Draft ready: her bike can be picked up."


@pytest.mark.anyio
async def test_a_message_the_recording_never_had_gets_no_reply(shop):
    async with open_agent("recorded", recording=hero_recording(), connect=in_memory, pace=False) as replay:
        result = await replay.send("Something new")
    assert result.reply == NO_REPLY and result.tool_calls == []


# --- When the next recorded message is ready ---------------------------------------------------

def test_the_next_message_waits_for_the_shop_to_reach_its_step(conn, approved):
    recording = hero_recording()
    assert recorded.next_turn(conn, recording) is recording.turns[0]
    convo = conversations.create(conn, "recorded", "claude-sonnet-5-5")
    conversations.append(conn, convo.id, "user", [{"type": "text", "text": recording.turns[0].message}])
    assert recorded.next_turn(conn, recording) is None  # the repair isn't done yet
    with conn:
        conn.execute("UPDATE work_orders SET status = 'done', finished_at = ? WHERE id = ?",
                     (datetime.now(timezone.utc).isoformat(), approved))
    assert recorded.next_turn(conn, recording) is recording.turns[1]
    conversations.append(conn, convo.id, "user", [{"type": "text", "text": recording.turns[1].message}])
    assert recorded.next_turn(conn, recording) is None  # the recording is used up


# --- In the hosted demo ---------------------------------------------------------------------

@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def client(tmp_path, monkeypatch, model):
    monkeypatch.setenv("SANDBOXES", "1")
    monkeypatch.setenv("SANDBOX_DIR", str(tmp_path / "sandboxes"))
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("STAFF_PASSCODE", "pc")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shared.db"))
    for name in ("TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY", "AGENT_LIVE", "PUBLIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(recorded, "RECORDINGS", tmp_path / "recordings")
    hero_recording().save(tmp_path / "recordings" / "hero.json")
    app.state.agent_factory = lambda cid: (recorded.open_runtime(cid, connect=in_memory, pace=False)
                                           or agent(model, cid))
    with TestClient(app) as c:
        yield c
    del app.state.agent_factory


def start(client, key="hero", **body):
    return client.post(f"/api/demo/stories/{key}/start", json=body)


def chat(client) -> str:
    return client.post("/api/conversations", headers=STAFF).json()["conversation_id"]


def say(client, conversation, words):
    return client.post(f"/api/conversations/{conversation}/messages", headers=STAFF, data={"text": words})


def test_the_stories_say_which_have_a_recording(client):
    stories = {s["key"]: s for s in client.get("/api/demo/stories").json()}
    assert stories["hero"]["recorded"] == {"recorded_on": "2026-11-17", "model": "claude-sonnet-5-5"}
    assert stories["race-day"]["recorded"] is None
    client.cookies.clear()
    assert start(client, "race-day", recorded=True).status_code == 404


def test_a_recorded_story_plays_without_spending(client, model):
    started = start(client, recorded=True).json()
    assert started["recorded"] and started["photo"] and started["message"] == hero_recording().turns[0].message
    info = client.get("/api/demo").json()
    assert info["recorded"]["next_message"] == started["message"] and info["recorded"]["recorded_on"] == "2026-11-17"

    conversation = chat(client)
    assert say(client, conversation, "Something of my own").status_code == 409
    turn = say(client, conversation, started["message"])
    assert "event: reply" in turn.text and "Quote drafted." in turn.text
    assert model.requests == []  # the live model was never called
    detail = client.get(f"/api/conversations/{conversation}", headers=STAFF).json()
    assert detail["runtime"] == "recorded"
    assert client.get("/api/demo").json()["recorded"]["next_message"] is None
    with closing(guards.connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_turns").fetchone()[0] == 0  # not charged


def test_a_recorded_run_plays_after_the_budget_is_spent(client):
    new_visitor(client)
    spend("someone-else", 50)
    assert client.get("/api/demo").json()["agent"]["live"] is False
    message = start(client, recorded=True).json()["message"]
    assert say(client, chat(client), message).status_code == 200


def test_a_recorded_shop_pins_its_calendar(client):
    start(client, recorded=True)
    key = sandboxes.key_for(client.cookies[sandboxes.COOKIE])
    with closing(sqlite3.connect(sandboxes.path_for(key))) as conn:
        assert clock.today(conn) == RECORDED_ON
    start(client)  # starting live again clears it
    with closing(sqlite3.connect(sandboxes.path_for(key))) as conn:
        assert clock.today(conn) == date.today()


def test_the_customer_cant_ask_questions_in_a_recorded_run(client):
    start(client, recorded=True)
    key = sandboxes.key_for(client.cookies[sandboxes.COOKIE])
    from demo.sample import create_sample

    with db.using(sandboxes.path_for(key)), closing(db.connect()) as conn:
        _, token, _ = create_sample(conn)
        public = f"{key}.{token}"
    view = client.get(f"/api/customer/{public}").json()
    assert view["can_ask"] is False
    assert client.post(f"/api/customer/{public}/replies", json={"body": "Ready Friday?"}).status_code == 409


# --- The bot check ------------------------------------------------------------------------

@pytest.fixture
def bot_check(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
    tokens = []
    monkeypatch.setattr(turnstile, "verify", lambda token: tokens.append(token) or token == "good")
    return tokens


def test_a_live_story_needs_the_bot_check(client, bot_check):
    client.cookies.clear()
    assert client.get("/api/demo").json()["turnstile_site_key"] == "site"
    assert client.get("/api/demo").json()["agent"]["live"] is True  # the front door isn't held up by it
    refused = start(client, turnstile_token="bad")
    assert refused.status_code == 403 and "bot check" in refused.json()["detail"]
    assert start(client, turnstile_token="good").status_code == 200
    assert start(client).status_code == 200  # this shop passed: starting over needs no new check
    assert bot_check == ["bad", "good"]


def test_a_recorded_story_needs_no_bot_check(client, bot_check):
    client.cookies.clear()
    assert start(client, recorded=True).status_code == 200 and bot_check == []


def test_the_live_agent_only_works_for_a_checked_shop(client, bot_check, model):
    new_visitor(client)  # a shop made without starting a story
    refused = say(client, chat(client), "Emma's bike")
    assert refused.status_code == 429 and "front door" in refused.json()["detail"]
    start(client, turnstile_token="good")
    model.responses.append(message(text("Hello.")))
    assert say(client, chat(client), HERO).status_code == 200
