# Mitchell Bike Co.

A fictional bike shop run by AI agents over MCP. Portfolio project; all shop data is synthetic. See `README.md` for the idea and `docs/decisions.md` for why things are the way they are.

## Commands

- `make db` creates `data/shop.db` from `shop/schema.sql` (refuses to overwrite; delete the file to rebuild)
- `make test` runs the unit tests
- Always run Python through `uv run`. The system `python3` is older than the 3.12 the project needs.

## Rules for this codebase

- **`shop/` has no AI code.** No model, agent SDK, or MCP imports. Every business rule (compatibility, stock, spend limit) lives here and is unit-tested without tokens.
- **MCP servers are thin.** `mcp_servers/` wraps `shop/` functions; it does not reimplement rules.
- **Approval is enforced server-side.** A purchase order over `PO_APPROVAL_LIMIT_CENTS` comes back as pending approval from the tool itself. Never rely on an agent platform's approval prompt.
- **Agents sit behind `AgentRuntime`.** Anthropic is the default, Dust the second implementation. Code outside `agents/runtime/` must not depend on a specific platform.
- **Money is integer cents.** Never floats.
- **Compatibility is checked against the customer's actual bike** (`bike_standards`), not the catalog model. Exceptions go in `standard_compat` with a note.
- **Real standards, invented products.** Interface standards (freehubs, BB shells, axles, etc.) are real; brands, product names, and prices are invented.

## Conventions

- Record each significant choice in `docs/decisions.md`: what was decided, what was rejected, and why.
- Secrets live in `.env` (gitignored). Stripe keys are test mode only.
- Unedited photos go in `data/photos/raw/` (gitignored); commit cropped copies only.
