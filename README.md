# Mitchell Bike Co.

A fictional bike shop run by AI agents, built to demonstrate agentic workflows over the Model Context Protocol (MCP).

> **Status:** early scaffolding. Mitchell Bike Co. is not a real business; all shop data is synthetic.

## The idea

A customer says "my gears skip when I pedal hard" and sends a photo of their back wheel. A service agent asks a couple of follow-up questions, reads the bike's service history, and checks the photo: the chain and the gear cluster on the back wheel (the cassette) are worn out. It says how confident it is, and asks for a measurement when the evidence is thin.

Then comes the twist. The catalog says this bike model takes one cassette, but the customer upgraded their wheels, so it needs a different one. The agent checks fit against the bike the customer actually has, and finds the right part is out of stock. A procurement agent drafts a purchase order, which waits for a manager's approval when it is over the spend limit. The customer gets a quote, books a slot, and pays.

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

## Roadmap

Work is split into milestones, each defined by what it delivers rather than how long it takes.

| Milestone | Delivers | Status |
| --- | --- | --- |
| M0 | Scaffold, schema, CI, decisions log | Done |
| M1 | Seed data and core business rules in `shop/` (fit, stock, spend limit) | Next |
| M2 | MCP servers: catalog, work orders, procurement | |
| M3 | Agents behind the `AgentRuntime` interface | |
| M4 | Backend API | |
| M5 | Eval suite | |
| M6 | Two-screen web frontend | |

## Documentation

- [Decisions log](docs/decisions.md)
