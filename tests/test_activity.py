"""The activity log's summaries, from real tool results."""

import json

import pytest
from mcp import Client

from agents import activity
from mcp_servers import catalog, procurement, work_orders
from shop import messages
from shop import work_orders as wo

pytestmark = pytest.mark.anyio
SERVERS = {"catalog": catalog.server, "work orders": work_orders.server, "procurement": procurement.server}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def server_db(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))


async def call(server_name, tool, **args):
    async with Client(SERVERS[server_name]) as client:
        result = await client.call_tool(tool, args)
    text = "\n".join(c.text for c in result.content)
    return activity.describe(tool, args, text, result.is_error)


async def test_tool_servers_match_the_real_servers():
    for name, server in SERVERS.items():
        async with Client(server) as client:
            tools = [t.name for t in (await client.list_tools()).tools]
        assert {t: activity.server_for(t) for t in tools} == {t: name for t in tools}
    assert len(activity.TOOL_SERVERS) == 18


async def test_hero_summaries(conn, quoted, quote_sent):
    assert await call("catalog", "find_customer", query="clark") == "Emma Clark (1 bike)"
    assert await call("catalog", "get_bike", customer_bike_id=1) == (
        "Halden Arc 2023. Differs from catalog: freehub Shimano HG 8-10 speed (catalog: Shimano HG 11-speed road)"
    )
    assert await call("catalog", "list_fitting_parts", customer_bike_id=1, category="cassette") == (
        "1 of 6 cassettes fit: AD-C11-34W (out of stock)"
    )
    assert await call("work orders", "add_part", work_order_id=quoted, sku="AD-C11-28R") == (
        "Refused: cannot add parts: work order 1 is quoted"
    )
    assert await call("procurement", "supplier_options", sku="AD-C11-34W", qty=1) == (
        "Velo Supply Co. $42.50, 2 days · Northgate Distribution $39.00, 5 days"
    )
    estimate = await call("procurement", "estimate_ready_date", supplier_ids=[1])
    assert estimate.startswith("Ready ") and "via Velo Supply Co. (2-day lead time + 1 repair day)" in estimate
    refused = await call("procurement", "create_purchase_order", work_order_id=quoted, supplier_id=1,
                         lines=[{"sku": "AD-C11-34W", "qty": 1}])
    assert refused == "Refused: work order 1 is quoted: parts can only be ordered after the customer approves the quote"
    wo.record_customer_decision(conn, quote_sent, approved=True)
    assert await call("procurement", "create_purchase_order", work_order_id=quoted, supplier_id=1,
                      lines=[{"sku": "AD-C11-34W", "qty": 1}]) == "Ordered from Velo Supply Co.: $42.50"


async def test_quote_and_draft_summaries(conn, diagnosed):
    wo.add_part(conn, diagnosed, "AD-C11-34W")
    assert await call("work orders", "lock_quote", work_order_id=diagnosed) == "Quote locked at $74.99"
    assert await call("work orders", "draft_customer_message", work_order_id=diagnosed,
                      body="Hi Emma", include_quote=True) == (
        "Draft to the Customer, carrying the $74.99 quote. Waiting for the Mechanic to send"
    )


def test_unknown_shapes_fall_back_quietly():
    assert activity.describe("lock_quote", {}, "not json", False) == "Done"
    assert activity.describe("mystery_tool", {}, json.dumps({"a": 1}), False) == "Done"
    assert activity.entry("mystery_tool", {}, "", False)["server"] == "unknown"


def test_a_draft_entry_names_the_message_it_drafted():
    result = json.dumps({"id": 7, "work_order_id": 1, "status": "draft", "body": "Hi Emma"})
    assert activity.entry("draft_customer_message", {}, result, False)["message_id"] == 7
    assert "message_id" not in activity.entry("draft_customer_message", {}, "Error: no", True)
    assert "message_id" not in activity.entry("lock_quote", {}, result, False)
