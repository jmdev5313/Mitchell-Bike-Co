"""The MCP servers, called through a real MCP client (in memory)."""

import json
from datetime import date, timedelta

import pytest
from mcp import Client

from mcp_servers import catalog, procurement, work_orders
from shop import messages
from shop import work_orders as wo
from tests.conftest import HERO, HERO_QUOTE

SERVERS = (catalog.server, work_orders.server, procurement.server)
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def server_db(conn, tmp_path, monkeypatch):
    """Point the servers at the same seeded test database as `conn`."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    monkeypatch.setenv("AGENT_RUNTIME", "test")


async def call(server, tool, **args):
    async with Client(server) as client:
        return await client.call_tool(tool, args)


async def ok(server, tool, **args):
    result = await call(server, tool, **args)
    assert not result.is_error, result.content[0].text
    data = result.structured_content
    return data["result"] if isinstance(data, dict) and set(data) == {"result"} else data


async def refused(server, tool, **args) -> str:
    result = await call(server, tool, **args)
    assert result.is_error
    return result.content[0].text


async def test_tool_lists():
    names = {}
    for server in SERVERS:
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
        names[server.name] = sorted(t.name for t in tools)
        for t in tools:
            assert "conn" not in t.input_schema.get("properties", {}), t.name
            assert t.description, t.name
    assert names == {
        "mitchell-catalog": ["check_fit", "find_customer", "get_bike", "list_fitting_parts",
                             "list_services", "stock_status"],
        "mitchell-work-orders": ["add_part", "add_service", "draft_customer_message", "get_work_order",
                                 "list_customer_messages", "lock_quote", "open_work_order",
                                 "record_diagnosis"],
        "mitchell-procurement": ["create_purchase_order", "estimate_ready_date", "supplier_options"],
    }


async def test_agent_cannot_send_or_approve():
    for server in SERVERS:
        for forbidden in ("send_draft", "send_customer_message", "record_customer_decision"):
            text = await refused(server, forbidden)
            assert "unknown tool" in text.lower() or forbidden in text


async def test_hero_story_through_the_tools(conn):
    # Find the bike and see the upgrade.
    [customer] = await ok(catalog.server, "find_customer", query="clark")
    bike_id = customer["bikes"][0]["customer_bike_id"]
    bike = await ok(catalog.server, "get_bike", customer_bike_id=bike_id)
    assert bike["differs_from_catalog_model"] == [{
        "kind": "freehub", "catalog_model": "Shimano HG 11-speed road", "this_bike": "Shimano HG 8-10 speed",
    }]
    assert "11-34 cassette already fitted" in bike["service_history"][-1]["summary"]

    # Only the wide-range cassette fits, and it is out of stock.
    cassettes = await ok(catalog.server, "list_fitting_parts", customer_bike_id=bike_id, category="cassette")
    fitting = [c for c in cassettes if c["fits"]]
    assert [(c["sku"], c["stock_qty"]) for c in fitting] == [("AD-C11-34W", 0)]

    # Build the work order. The catalog cassette is refused with the reason.
    order = await ok(work_orders.server, "open_work_order", customer_bike_id=bike_id,
                     complaint="Gears skip when I pedal hard")
    wo_id = order["work_order_id"]
    await ok(work_orders.server, "record_diagnosis", work_order_id=wo_id,
             diagnosis="Chain at 0.75%; cassette worn (came secondhand with the wheels)")
    text = await refused(work_orders.server, "add_part", work_order_id=wo_id, sku="AD-C11-28R")
    assert "does not fit this bike: freehub" in text
    await ok(work_orders.server, "add_part", work_order_id=wo_id, sku="AD-C11-34W")
    await ok(work_orders.server, "add_part", work_order_id=wo_id, sku="AD-CH11")
    await ok(work_orders.server, "add_service", work_order_id=wo_id,
             service_name="Drivetrain replacement (chain and cassette)")
    quoted = await ok(work_orders.server, "lock_quote", work_order_id=wo_id)
    assert quoted["quoted_total_cents"] == HERO_QUOTE
    draft = await ok(work_orders.server, "draft_customer_message", work_order_id=wo_id,
                     body="Your repair comes to $169.98.", include_quote=True)
    assert (draft["status"], draft["quoted_total_cents"]) == ("draft", HERO_QUOTE)

    # Nothing can be ordered yet.
    velo = (await ok(procurement.server, "supplier_options", sku="AD-C11-34W", qty=1))[0]
    text = await refused(procurement.server, "create_purchase_order", work_order_id=wo_id,
                         supplier_id=velo["supplier_id"], lines=[{"sku": "AD-C11-34W", "qty": 1}])
    assert "after the customer approves the quote" in text

    # The Mechanic sends and the Customer approves, outside the Agent's tools.
    messages.send_draft(conn, draft["id"])
    wo.record_customer_decision(conn, draft["id"], approved=True)

    estimate = await ok(procurement.server, "estimate_ready_date", supplier_ids=[velo["supplier_id"]])
    assert estimate["ready_date"] == (date.today() + timedelta(days=3)).isoformat()
    po = await ok(procurement.server, "create_purchase_order", work_order_id=wo_id,
                  supplier_id=velo["supplier_id"], lines=[{"sku": "AD-C11-34W", "qty": 1}])
    assert po["total_cents"] == 4250
    assert (await ok(work_orders.server, "get_work_order", work_order_id=wo_id))["status"] == "awaiting_parts"


async def test_every_call_is_audited(conn):
    await ok(catalog.server, "check_fit", sku="AD-C11-34W", customer_bike_id=1)
    await refused(catalog.server, "check_fit", sku="NOPE", customer_bike_id=1)
    rows = conn.execute("SELECT tool, runtime, args_json, result_summary FROM audit_log ORDER BY id").fetchall()
    assert [(r["tool"], r["runtime"]) for r in rows] == [("check_fit", "test"), ("check_fit", "test")]
    assert json.loads(rows[1]["args_json"]) == {"customer_bike_id": 1, "sku": "NOPE"}
    assert '"fits": true' in rows[0]["result_summary"]
    assert rows[1]["result_summary"] == "refused: no part with SKU NOPE"


async def test_ready_date_with_parts_in_stock():
    estimate = await ok(procurement.server, "estimate_ready_date")
    assert estimate["lead_time_days"] == 0
    assert estimate["ready_date"] == (date.today() + timedelta(days=1)).isoformat()


async def test_bad_arguments_are_tool_errors():
    assert "no supplier" in await refused(procurement.server, "estimate_ready_date", supplier_ids=[9999])
    assert "at least 2 characters" in await refused(catalog.server, "find_customer", query="x")
    assert await refused(catalog.server, "check_fit", sku="AD-CH11")  # missing customer_bike_id
