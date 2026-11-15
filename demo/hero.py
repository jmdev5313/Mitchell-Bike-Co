"""The hero story, run end to end through the three MCP servers.

Each server is launched over stdio exactly as an agent runtime would launch it.
The script plays the Agent's tool calls in order, and stands in for the two
actions that are deliberately not Agent tools: the Mechanic sending a draft and
the Customer approving the quote.

It uses its own database (data/demo.db by default, rebuilt on every run), so the
main database is left alone.

Run: make demo   (or: uv run python -m demo.hero)
"""

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import Client, StdioServerParameters

from shop import db, messages, seed
from shop import work_orders as wo

DEMO_DB = Path(os.environ.get("DEMO_DB_PATH", "data/demo.db"))
SERVERS = ("catalog", "work_orders", "procurement")


def say(persona: str, text: str) -> None:
    print(f"\n{persona:>9} | {text}")


def show(text: str) -> None:
    print(f"{'':>9} |   {text}")


async def main() -> None:
    DEMO_DB.unlink(missing_ok=True)
    conn = db.connect(db.init(DEMO_DB))
    seed.load(conn)

    env = {"DB_PATH": str(DEMO_DB), "AGENT_RUNTIME": "demo", "MCP_LOG_LEVEL": "WARNING"}
    async with AsyncExitStack() as stack:
        clients = {
            name: await stack.enter_async_context(Client(StdioServerParameters(
                command="uv", args=["run", "python", "-m", f"mcp_servers.{name}"],
                env=env, cwd=Path.cwd(),
            )))
            for name in SERVERS
        }

        async def tool(server: str, name: str, **args):
            result = await clients[server].call_tool(name, args)
            data = result.structured_content
            if isinstance(data, dict) and set(data) == {"result"}:
                data = data["result"]
            label = f"{server}.{name}"
            if result.is_error:
                show(f"{label} -> REFUSED: {result.content[0].text}")
                return None
            show(f"{label} -> ok")
            return data

        say("Customer", '"My gears skip when I pedal hard." (drops off the bike)')
        say("Mechanic", "Skips under load in the smaller cogs; chain checker reads 0.75%. Whose bike is this?")
        [customer] = await tool("catalog", "find_customer", query="Emma")
        bike_id = customer["bikes"][0]["customer_bike_id"]
        bike = await tool("catalog", "get_bike", customer_bike_id=bike_id)
        say("Agent", f"{customer['name']}'s {bike['model']}. It differs from the catalog model:")
        for d in bike["differs_from_catalog_model"]:
            show(f"{d['kind']}: catalog has {d['catalog_model']}, this bike has {d['this_bike']}")
        show(f"History: {bike['service_history'][-2]['summary']} ({bike['service_history'][-2]['odometer_km']} km)")
        show(f"History: {bike['service_history'][-1]['summary']} ({bike['service_history'][-1]['odometer_km']} km)")

        cassettes = await tool("catalog", "list_fitting_parts", customer_bike_id=bike_id, category="cassette")
        fitting = [c for c in cassettes if c["fits"]]
        say("Agent", "Only one cassette fits the upgraded wheels:")
        for c in fitting:
            show(f"{c['sku']} {c['name']}: ${c['price_cents'] / 100:.2f}, {c['stock_qty']} in stock")

        order = await tool("work_orders", "open_work_order", customer_bike_id=bike_id,
                           complaint="Gears skip when I pedal hard")
        wo_id = order["work_order_id"]
        await tool("work_orders", "record_diagnosis", work_order_id=wo_id,
                   diagnosis="Chain worn to 0.75% (replaced at 5,000 km). Cassette worn; it came "
                             "secondhand with the wheels at 6,900 km and has not been replaced.")
        say("Agent", "Trying the cassette the catalog lists for this model, to show the guardrail:")
        await tool("work_orders", "add_part", work_order_id=wo_id, sku="AD-C11-28R")
        say("Agent", "Adding the parts that fit, and the labor:")
        await tool("work_orders", "add_part", work_order_id=wo_id, sku=fitting[0]["sku"])
        await tool("work_orders", "add_part", work_order_id=wo_id, sku="AD-CH11")
        await tool("work_orders", "add_service", work_order_id=wo_id,
                   service_name="Drivetrain replacement (chain and cassette)")
        quoted = await tool("work_orders", "lock_quote", work_order_id=wo_id)
        total = quoted["quoted_total_cents"]

        options = await tool("procurement", "supplier_options", sku=fitting[0]["sku"], qty=1)
        fastest = options[0]
        estimate = await tool("procurement", "estimate_ready_date", supplier_ids=[fastest["supplier_id"]])
        draft = await tool(
            "work_orders", "draft_customer_message", work_order_id=wo_id, include_quote=True,
            body=(f"Hi {customer['name'].split()[0]}, the chain and the gear cluster on your back wheel are "
                  f"worn out, which is why the gears skip. Replacing both comes to ${total / 100:.2f}, parts "
                  f"and labor. The right part for your wheels needs ordering, so your bike would be ready "
                  f"{estimate['ready_date']} if you approve today."),
        )
        say("Agent", "Drafted for the Mechanic to review:")
        show(json.dumps(draft["body"]))

        say("Agent", "Trying to order before the Customer approves, to show the guardrail:")
        lines = [{"sku": fitting[0]["sku"], "qty": 1}]
        await tool("procurement", "create_purchase_order", work_order_id=wo_id,
                   supplier_id=fastest["supplier_id"], lines=lines)

        say("Mechanic", "Looks right. Sends it. (not an Agent tool)")
        messages.send_draft(conn, draft["id"])
        say("Customer", f"Clicks Approve on the ${total / 100:.2f} quote. (not an Agent tool)")
        wo.record_customer_decision(conn, draft["id"], approved=True)

        say("Agent", f"Approved. Ordering from {fastest['supplier_name']} "
                     f"({fastest['lead_time_days']} days, ${fastest['total_cents'] / 100:.2f}):")
        await tool("procurement", "create_purchase_order", work_order_id=wo_id,
                   supplier_id=fastest["supplier_id"], lines=lines)
        final = await tool("work_orders", "get_work_order", work_order_id=wo_id)
        say("Agent", f"Work order {wo_id} is now {final['status']}.")

    calls = conn.execute("SELECT COUNT(*), SUM(result_summary LIKE 'refused:%') FROM audit_log").fetchone()
    say("Audit", f"{calls[0]} tool calls recorded, {calls[1]} refused. Database: {DEMO_DB}")
    conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
