# Mitchell Bike Co.

A fictional bike shop where an AI Agent works alongside the Mechanic, over MCP. Portfolio project; all shop data is synthetic. See `README.md` for the idea and `docs/decisions.md` for why things are the way they are.

## Commands

- `make reset` deletes, rebuilds, and seeds `data/shop.db` (`make db` and `make seed` do the two halves)
- `make test` runs the unit tests
- `make sample` adds a quoted hero work order to `data/shop.db` and prints its Customer token (no model call)
- `make api` serves everything: the front door at `/`, the workshop at `/workshop`, Customer pages at `/c/{token}`, API docs at `/docs`. `DEMO_MODE=1` turns on the front door's shortcuts and reset (`api/demo.py`); never with real data
- `make api` runs the API on port 8000 (docs at `/docs`); staff endpoints need `STAFF_PASSCODE` from `.env` as a bearer token
- `make agent-check` runs the hero story against the real model and checks the database outcome (its own `data/check.db`; spends a few cents)
- `make record` records a real run of the Agent on each story for the hosted demo to replay (`ARGS="--only <key>"`; spends tokens, well under a dollar for all)
- `make evals` runs the eval suite (`evals/scenarios/<group>/`, each a `Scenario` with a `play`) against the real model, 3 runs per scenario, on its own `data/eval.db`; `ARGS="--only <key|group> --runs 1"`. Judge by the shop's state, never by a model grading wording
- `make agent` chats with the Agent as the Mechanic (needs `ANTHROPIC_API_KEY` in `.env`; spends tokens)
- `make demo` runs the hero story through the servers (its own `data/demo.db`)
- `make servers` runs the three MCP servers over HTTP; `uv run python -m mcp_servers.<name>` runs one over stdio
- Deploying: a merge to `main` deploys itself once the tests pass (`.github/workflows/test.yml`, with the `FLY_API_TOKEN` repository secret). By hand, `fly deploy` from this folder builds the `Dockerfile` on Fly's servers and runs it as `fly.toml` says (one machine, the `/data` volume). Secrets are set with `fly secrets set`, never in `fly.toml` or the image; `.dockerignore` keeps `.env` out.
- Always run Python through `uv run`. The system `python3` is older than the 3.12 the project needs.

## Rules for this codebase

- **`shop/` has no AI code.** No model, agent SDK, or MCP imports. Every business rule (compatibility, stock, quote approval, ordering) lives here and is unit-tested without tokens.
- **MCP servers are thin.** `mcp_servers/` wraps `shop/` functions; it does not reimplement rules. Register tools with `@shop_tool(server)` from `mcp_servers/common.py`: the function takes `conn` first (hidden from the model), and the decorator maps `NotFound`/`RuleViolation` to tool errors and writes the audit log.
- **`.mcp.json` connects Claude Code to the three servers** (stdio, `AGENT_RUNTIME=claude-code`), so the shop's tools are available in this project. Calls write to `data/shop.db` and its audit log; `make reset` clears them.
- **MCP SDK is v2** (`mcp>=2`): the server class is `MCPServer` from `mcp.server.mcpserver`, not v1's `FastMCP`.
- **Approvals go through `shop.flow.customer_decides`**, which records the decision and places the Agent's order plan (`order_plan_lines`). Don't call `record_customer_decision` directly from the API or tools, or the planned order won't be placed.
- **Every action lands in the work order's history** (`shop.events`, table `work_order_events`): the MCP servers record the Agent's tool calls that touch a work order, the API records the Mechanic's and Customer's actions, and `shop.flow` records the shop's. Add an event when you add an action.
- **API database connections are per request with `check_same_thread=False`** (`api.deps.get_db`): FastAPI may use them from more than one worker thread. Never share one between requests.
- **Customer approval is enforced server-side.** The Customer approves or declines a sent message that carries the locked quote, and `shop/procurement.py` refuses to order anything for a work order until they have approved, or anything beyond the approved parts. Never rely on an agent platform's approval prompt.
- **Some actions are not the Agent's.** The Agent drafts messages but only the Mechanic sends them, and only the Customer records an approval. MCP servers must not expose `send_draft` or `record_customer_decision` as Agent tools.
- **The Agent sits behind `AgentRuntime`** (`agents/runtime/base.py`). Anthropic is the only runtime today (a Dust runtime was planned and deferred); a second platform would implement the same interface. Code outside `agents/runtime/` must not depend on a specific platform; get a runtime with `agents.runtime.open_agent()`.
- **Agent conversation history is append-only** (`agents/conversations.py`). Store each message exactly as sent and never edit or strip it: Claude Sonnet 5.5 ties thinking blocks to the exact history.
- **Tests never call the model.** Drive runtimes with a scripted fake client (`tests/test_agent_runtime.py`). Real-model runs are opt-in commands, not CI.
- **Money is integer cents.** Never floats.
- **The Customer's only credential is their link** (`shop/customer_links.py`): an unguessable token tied to one work order. Anything that serves the Customer resolves the token to that work order and shows nothing else.
- **Seed data refers to records by readable keys** (SKU, standard kind and name, bike model key), never by row id.
- **Rules raise `NotFound` or `RuleViolation`** from `shop/errors.py`; MCP servers turn these into tool errors, and the API into 404 and 409 with the rule's message.
- **The hosted demo gives each visitor their own database** (`SANDBOXES=1`, `api/sandboxes.py`). Request code gets its connection from `db.connect()` with no path, so the visitor's sandbox applies; anything it starts (tasks, the Agent's MCP servers) inherits it through `shop.db.using()`. A Customer link token leaves the API through `sandboxes.public_token()` and is read back with `sandboxes.bare_token()`.
- **The hosted demo's spending limits live in `api/guards.py`.** Every live Agent turn is checked with `guards.agent_refusal()` before the model is called and charged with `guards.record_turn()` after; a new way to start a turn must do both.
- **Recorded runs replay a real run of the Agent** (`agents/runtime/replay.py`, `api/recorded.py`, recordings from `make record` in `demo/recordings/`). The recorded runtime's tool calls run for real; a recorded shop pins its calendar with `shop.clock`. Code that needs "today" for a shop decision uses `clock.today(conn)`, never `date.today()`. A recorded run is never charged or limited by `api/guards.py`.
- **Open Agent conversations live in `api/agent_pool.py`**, one task per conversation: MCP connections must be opened and closed by the same task, so never call a runtime's `open`/`close` from a request handler directly.
- **The API is thin too.** `api/` wraps `shop/` functions; staff routers depend on `require_staff`, and Customer routes resolve the link token first and check that every id they touch belongs to that work order.
- **Compatibility is checked against the Customer's actual bike** (`bike_standards`), not the catalog model. Exceptions go in `standard_compat` with a note.
- **Real standards, invented products.** Interface standards (freehubs, BB shells, axles, etc.) are real; brands, product names, and prices are invented. Real brands may appear in illustrative photos, never in the shop's data.

- **The web pages are plain HTML, CSS and JavaScript in `web/`**, served by the API (`/static`, `/c/{token}`), no framework or build step. Put text from the API on the page with `textContent` (the `h()` helper in `web/static/js/dom.js`), never `innerHTML`: messages are written by Customers and the Agent.
- **The Agent's activity log is written in plain code** (`agents/activity.py`): `TOOL_SERVERS` maps each tool to its MCP server (a test checks it against the servers), and `describe()` summarizes each result. Add a summary there when you add a tool.
- **The visual system lives in `web/static/css/shop.css`** as CSS variables. Each colour has one meaning: work blue only for "Send to Emma" and the focus ring, red only for refusals, catalog mismatches and out of stock, green only for in stock and paid, manila for anything the Customer sees. Structure comes from rules and tables, not cards.

## Conventions

- In documentation, name people by persona, capitalized: **Customer**, **Mechanic**, **Agent** (see the README). Seed data keeps realistic names.
- Record each significant choice in `docs/decisions.md`: what was decided, what was rejected, and why.
- Secrets live in `.env` (gitignored). Stripe keys are test mode only: `api.deps.get_stripe` refuses anything but `sk_test_`/`rk_test_`. A payment is only recorded after the server retrieves the checkout session from Stripe and sees it paid; never trust the browser's redirect alone.
- Unedited photos go in `data/photos/raw/` (gitignored); commit cropped copies only.
