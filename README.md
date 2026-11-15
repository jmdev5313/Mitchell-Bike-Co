# Mitchell Bike Co.

A fictional bike shop run by AI agents, built to demonstrate agentic workflows over the Model Context Protocol (MCP).

> **Status:** early scaffolding. Mitchell Bike Co. is not a real business; all shop data is synthetic.

## The idea

A customer sends a photo and says "my gears skip under load." A service agent diagnoses the problem, checks which parts fit that customer's actual bike, and finds the cassette is out of stock. A procurement agent drafts a purchase order, which waits for a manager's approval when it is over the spend limit. The customer gets a quote, books a slot, and pays.

## How it is put together

- `shop/` holds the business rules and the database. It has no AI code.
- `mcp_servers/` exposes the shop as MCP tools: catalog, work orders, procurement.
- `agents/` holds the agents behind a small runtime interface, so the agent platform can be swapped by configuration.
- `api/` and `web/` are the backend and the two-screen frontend.
- `evals/` holds the scenario suite that measures whether the agents get it right.

## Getting started

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```
cp .env.example .env
make db
make test
```

## Documentation

- [Decisions log](docs/decisions.md)
