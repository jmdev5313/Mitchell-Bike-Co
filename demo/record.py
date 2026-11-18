"""Record a real run of the Agent on each repair story, for the hosted demo to replay.

    make record                      every story (spends real tokens: well under a dollar)
    make record ARGS="--only hero"   one story

Each story is played the way a visitor plays it, on a fresh seeded shop of its own
(data/record.db), with the shop's calendar pinned to today: the story's opening message
(with the illustrative photo for Emma's), then, if the Agent drafted a quote, the
Mechanic sends it, the Customer approves, the parts arrive, the repair is finished, and
the Mechanic sends the same "repair done" message the workshop's button sends. The
model's responses are saved to demo/recordings/<story>.json (see agents/runtime/replay.py).
"""

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

import anthropic

from agents import config, conversations
from agents.runtime.anthropic_runtime import AnthropicRuntime
from agents.runtime.replay import Recording, RecordingClient, Turn
from demo.stories import BY_KEY, STORIES
from shop import clock, db, flow, messages, procurement, seed
from shop import work_orders as wo

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / "demo" / "recordings"
RECORD_DB = ROOT / "data" / "record.db"
HERO_PHOTO = ROOT / "web" / "static" / "img" / "hero-cassette.jpg"


def repair_done_message(work_order_id: int, first_name: str) -> str:
    """What the workshop's "Repair done" button sends the Agent (web/static/js/job.js, onFinished)."""
    return (f"The repair on work order #{work_order_id} is done. Draft {first_name} a short message that the bike "
            "is ready to pick up and can be paid for from the link.")


def fresh_shop(today: date) -> Path:
    RECORD_DB.unlink(missing_ok=True)
    conn = db.connect(db.init(RECORD_DB))
    try:
        seed.load(conn)
        clock.pin(conn, today)
    finally:
        conn.close()
    return RECORD_DB


def _play_the_shop(conn, work_order_id: int) -> bool:
    """The Mechanic's and Customer's steps between the Agent's turns. Returns whether the repair got done."""
    drafts = [m for m in messages.list_messages(conn, work_order_id)
              if m.status == "draft" and m.quoted_total_cents is not None]
    if not drafts:
        return False
    sent = messages.send_draft(conn, drafts[-1].id)
    flow.customer_decides(conn, sent.id, approved=True)
    for po in procurement.list_purchase_orders(conn, work_order_id):
        if po["status"] == "ordered":
            procurement.receive_purchase_order(conn, po["id"])
    flow.start_when_ready(conn, work_order_id)
    if wo.summary(conn, work_order_id)["status"] != "in_progress":
        return False
    wo.finish_repair(conn, work_order_id)
    return True


async def record(story_key: str, today: date) -> Recording:
    story = BY_KEY[story_key]
    client = RecordingClient(anthropic.AsyncAnthropic())
    recording = Recording(story=story.key, model=config.agent_model(), recorded_on=today, turns=[])
    path = fresh_shop(today)
    with db.using(path):
        async with AnthropicRuntime(client=client) as agent:
            opening = story.mechanic_message(today)
            photo = story.key == "hero" and HERO_PHOTO.exists()
            client.new_turn()
            result = await agent.send(opening, [HERO_PHOTO] if photo else [])
            recording.turns.append(Turn(opening, photo, client.turns[-1]))
            print(f"  turn 1: {len(result.tool_calls)} tool calls, stop {result.stop_reason}")

            conn = db.connect()
            try:
                work_order_id = conversations.get(conn, agent.conversation_id).work_order_id
                done = work_order_id is not None and _play_the_shop(conn, work_order_id)
            finally:
                conn.close()
            if not done:
                print("  no quote to send, so the story ends after the first turn")
                return recording
            message = repair_done_message(work_order_id, story.customer.split(" ")[0])
            client.new_turn()
            result = await agent.send(message)
            recording.turns.append(Turn(message, False, client.turns[-1]))
            print(f"  turn 2: {len(result.tool_calls)} tool calls, stop {result.stop_reason}")
    return recording


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", help="one story's key")
    args = parser.parse_args(argv)
    config.load_env()
    keys = [args.only] if args.only else [s.key for s in STORIES]
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown:
        print(f"unknown story: {', '.join(unknown)}", file=sys.stderr)
        return 2
    today = date.today()
    for key in keys:
        print(f"Recording {key}…")
        recording = await record(key, today)
        recording.save(RECORDINGS / f"{key}.json")
        print(f"  saved demo/recordings/{key}.json")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
