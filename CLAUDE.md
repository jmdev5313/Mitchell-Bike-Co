# Mitchell Bike Co.

A fictional bike shop where an AI Agent works alongside the Mechanic, over MCP. Portfolio project; all shop data is synthetic. See `README.md` for the idea and `docs/decisions.md` for why things are the way they are.

## Commands

- `make reset` deletes, rebuilds, and seeds `data/shop.db` (`make db` and `make seed` do the two halves)
- `make test` runs the unit tests
- Always run Python through `uv run`. The system `python3` is older than the 3.12 the project needs.

## Rules for this codebase

- **`shop/` has no AI code.** No model, agent SDK, or MCP imports. Every business rule (compatibility, stock, quote approval, ordering) lives here and is unit-tested without tokens.
- **MCP servers are thin.** `mcp_servers/` wraps `shop/` functions; it does not reimplement rules.
- **Customer approval is enforced server-side.** The Customer approves the exact quoted total, and `shop/procurement.py` refuses to order anything for a work order until they have, or anything beyond the approved parts. Never rely on an agent platform's approval prompt.
- **The Agent sits behind `AgentRuntime`.** Anthropic is the default, Dust the second implementation. Code outside `agents/runtime/` must not depend on a specific platform.
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
