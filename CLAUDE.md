# Mitchell Bike Co.

A fictional bike shop where an AI Agent works alongside the Mechanic, over MCP. Portfolio project; all shop data is synthetic. See `README.md` for the idea and `docs/decisions.md` for why things are the way they are.

## Commands

- `make reset` deletes, rebuilds, and seeds `data/shop.db` (`make db` and `make seed` do the two halves)
- `make test` runs the unit tests
- `make agent` chats with the Agent as the Mechanic (needs `ANTHROPIC_API_KEY` in `.env`; spends tokens)
- `make demo` runs the hero story through the servers (its own `data/demo.db`)
- `make servers` runs the three MCP servers over HTTP; `uv run python -m mcp_servers.<name>` runs one over stdio
- Always run Python through `uv run`. The system `python3` is older than the 3.12 the project needs.

## Rules for this codebase

- **`shop/` has no AI code.** No model, agent SDK, or MCP imports. Every business rule (compatibility, stock, quote approval, ordering) lives here and is unit-tested without tokens.
- **MCP servers are thin.** `mcp_servers/` wraps `shop/` functions; it does not reimplement rules. Register tools with `@shop_tool(server)` from `mcp_servers/common.py`: the function takes `conn` first (hidden from the model), and the decorator maps `NotFound`/`RuleViolation` to tool errors and writes the audit log.
- **`.mcp.json` connects Claude Code to the three servers** (stdio, `AGENT_RUNTIME=claude-code`), so the shop's tools are available in this project. Calls write to `data/shop.db` and its audit log; `make reset` clears them.
- **MCP SDK is v2** (`mcp>=2`): the server class is `MCPServer` from `mcp.server.mcpserver`, not v1's `FastMCP`.
- **Customer approval is enforced server-side.** The Customer approves or declines a sent message that carries the locked quote, and `shop/procurement.py` refuses to order anything for a work order until they have approved, or anything beyond the approved parts. Never rely on an agent platform's approval prompt.
- **Some actions are not the Agent's.** The Agent drafts messages but only the Mechanic sends them, and only the Customer records an approval. MCP servers must not expose `send_draft` or `record_customer_decision` as Agent tools.
- **The Agent sits behind `AgentRuntime`** (`agents/runtime/base.py`). Anthropic is the default, Dust the second implementation. Code outside `agents/runtime/` must not depend on a specific platform; get a runtime with `agents.runtime.open_agent()`.
- **Agent conversation history is append-only** (`agents/conversations.py`). Store each message exactly as sent and never edit or strip it: Claude Sonnet 5.5 ties thinking blocks to the exact history.
- **Tests never call the model.** Drive runtimes with a scripted fake client (`tests/test_agent_runtime.py`). Real-model runs are opt-in commands, not CI.
- **Money is integer cents.** Never floats.
- **Seed data refers to records by readable keys** (SKU, standard kind and name, bike model key), never by row id.
- **Rules raise `NotFound` or `RuleViolation`** from `shop/errors.py`; MCP servers turn these into tool errors.
- **Compatibility is checked against the Customer's actual bike** (`bike_standards`), not the catalog model. Exceptions go in `standard_compat` with a note.
- **Real standards, invented products.** Interface standards (freehubs, BB shells, axles, etc.) are real; brands, product names, and prices are invented.

## Conventions

- In documentation, name people by persona, capitalized: **Customer**, **Mechanic**, **Agent** (see the README). Seed data keeps realistic names.
- Record each significant choice in `docs/decisions.md`: what was decided, what was rejected, and why.
- Secrets live in `.env` (gitignored). Stripe keys are test mode only.
- Unedited photos go in `data/photos/raw/` (gitignored); commit cropped copies only.
