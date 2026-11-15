# Mitchell Bike Co.

A fictional bike shop where an AI Agent works alongside the Mechanic, built to demonstrate agentic workflows over the Model Context Protocol (MCP).

> **Status:** early scaffolding. Mitchell Bike Co. is not a real business; all shop data is synthetic.

## Personas

- **Customer:** owns the bike and pays for the repair. Talks to the shop through messages and approves the quote.
- **Mechanic:** shop staff with the bike on the stand. Works with the Agent and reviews everything it drafts for the Customer.
- **Agent:** the shop's AI service agent. Diagnoses alongside the Mechanic, checks fit and stock, drafts messages, and orders parts once the Customer approves.

## The idea

The Customer brings in a gravel bike: "my gears skip when I pedal hard." The Mechanic puts it on the stand and asks the Agent for help, sharing what they see and measure ("skips under load in the smaller cogs, chain checker reads 0.75%") and, if useful, a photo. The Agent reads the bike's service history (the cassette has never been replaced) and confirms the diagnosis: a worn chain and cassette, the gear cluster on the back wheel. It says how confident it is, and asks for a measurement it is missing rather than guessing.

Then comes the twist. The catalog says this bike model takes one cassette, but the Customer upgraded their wheels, so it needs a different one. The Agent checks fit against the bike the Customer actually has, and finds the right cassette is out of stock.

The Agent adds the parts and labor to the work order (it cannot add a part that doesn't fit) and drafts a message to the Customer in plain language: what is wrong, the total, and when it will be ready. The Mechanic reviews the draft before it is sent. The Customer is the human in the loop: they approve that exact amount, or decline. If they ask a question instead ("can it be ready by Friday?"), the Agent drafts an answer it can back up from the supplier's lead time.

Only once the Customer approves can the cassette be ordered. The Agent picks a supplier (faster, or cheaper but slower, to match the date the Customer was promised) and orders exactly what was approved. The shop's own code enforces this: no order before approval, and nothing beyond the approved parts, whatever the Agent asks for. The part arrives, the Mechanic does the repair, and the Customer pays through a payment link.

## How it is put together

- `shop/` holds the business rules and the database. It has no AI code.
- `mcp_servers/` exposes the shop as MCP tools: catalog, work orders, procurement.
- `agents/` holds the agents behind a small runtime interface, so the agent platform can be swapped by configuration.
- `api/` and `web/` are the backend and the frontend: the Mechanic's workspace and the Customer's message thread.
- `evals/` holds the scenario suite that measures whether the agents get it right.

## Getting started

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```
cp .env.example .env
make reset   # create the database and load the seed data
make test
```

## Roadmap

Work is split into milestones, each defined by what it delivers rather than how long it takes.

| Milestone | Delivers | Status |
| --- | --- | --- |
| M0 | Scaffold, schema, CI, decisions log | Done |
| M1 | Seed data and core business rules in `shop/` (fit, stock, quote approval, ordering) | Next |
| M2 | MCP servers: catalog, work orders (including Customer messages), procurement | |
| M3 | The Agent, behind the `AgentRuntime` interface | |
| M4 | Backend API | |
| M5 | Eval suite | |
| M6 | Web frontend: Mechanic workspace and Customer thread | |

## Documentation

- [Decisions log](docs/decisions.md)
