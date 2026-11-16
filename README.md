# Mitchell Bike Co.

A fictional bike shop where an AI Agent works alongside the Mechanic, built to demonstrate agentic workflows over the Model Context Protocol (MCP).

> **Status:** early scaffolding. Mitchell Bike Co. is not a real business; all shop data is synthetic.

## Personas

- **Customer:** owns the bike and pays for the repair. Talks to the shop through messages, and approves or declines the quote.
- **Mechanic:** shop staff with the bike on the stand. Works with the Agent and reviews everything it drafts for the Customer.
- **Agent:** the shop's AI service agent. Diagnoses alongside the Mechanic, checks fit and stock, drafts messages, and orders parts once the Customer approves. It cannot send a message or approve on the Customer's behalf.

## The idea

The Customer brings in a gravel bike: "my gears skip when I pedal hard." The Mechanic puts it on the stand and asks the Agent for help, sharing what they see and measure ("skips under load in the smaller cogs, chain checker reads 0.75%") and, if useful, a photo. The Agent reads the bike's service history (the cassette has never been replaced) and confirms the diagnosis: a worn chain and cassette, the gear cluster on the back wheel. It says how confident it is, and asks for a measurement it is missing rather than guessing.

Then comes the twist. The catalog says this bike model takes one cassette, but the Customer upgraded their wheels, so it needs a different one. The Agent checks fit against the bike the Customer actually has, and finds the right cassette is out of stock.

The Agent adds the parts and labor to the work order (it cannot add a part that doesn't fit) and drafts a message to the Customer in plain language: what is wrong, the total, and when it will be ready. The Mechanic reviews the draft before it is sent. The Customer is the human in the loop: the quote message carries approve and decline buttons for that exact amount, and only the Customer's click records the decision. If they reply with a question instead ("can it be ready by Friday?"), the Agent reads it and drafts an answer it can back up from the supplier's lead time.

Only once the Customer approves can the cassette be ordered. The Agent picks a supplier (faster, or cheaper but slower, to match the date the Customer was promised) and orders exactly what was approved. The shop's own code enforces this: no order before approval, and nothing beyond the approved parts, whatever the Agent asks for. The part arrives, the Mechanic does the repair, and the Customer pays through a payment link.

## How it is put together

- `shop/` holds the business rules and the database. It has no AI code.
- `mcp_servers/` exposes the shop as three MCP servers (catalog, work orders, procurement). Every tool call is written to an audit log. The Agent gets no tool to send a message or approve a quote.
- `agents/` holds the Agent: its prompt (`agents/prompts/service_agent.md`) and a small runtime interface, so the agent platform can be swapped by configuration. The Anthropic runtime runs Claude Sonnet 5.5 against the three MCP servers.
- `api/` is the HTTP API (FastAPI): staff endpoints for the Mechanic's workspace, behind a passcode, and Customer endpoints reached through the Customer's private link. `make api` runs it, with interactive docs at `/docs`.
- `web/` will be the frontend: the Mechanic's workspace and the Customer's message thread.
- `evals/` measures whether the Agent gets it right. `make agent-check` is the first check, the full hero story against the real model; the scenario suite follows in M5.

## Getting started

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```
cp .env.example .env
make reset   # create the database and load the seed data
make test
```

Each MCP server runs over stdio for a local client, or over HTTP for a hosted one:

```
uv run python -m mcp_servers.catalog          # stdio
make servers                                  # all three over HTTP on ports 8101-8103
```

## Try it

**Try the API by hand.** `make sample` adds Emma's quoted work order, with the quote already sent, and prints her Customer token. Run `make api`, open http://127.0.0.1:8000/docs, and paste the token into the Customer endpoints to view the quote or approve it. For the staff endpoints, click Authorize and paste `STAFF_PASSCODE` from your `.env`.

**Chat with the Agent as the Mechanic.** Add your Anthropic API key to `.env`, then run `make agent`. It uses Claude Sonnet 5.5 and costs a little per message. Try the same message as below. Slash commands act out what the Agent can't do: `/send` sends its draft (as the Mechanic), `/approve` or `/decline` answers the quote (as the Customer), `/reply TEXT` replies as the Customer, `/photo PATH` attaches a photo, and `/usage` shows tokens used. Conversations are stored, so `make agent ARGS='--conversation ID'` resumes one.

**Check the Agent against the real model.** `make agent-check` runs the hero story with Claude Sonnet 5.5 (two Mechanic turns, with the send and approval acted out in between) and checks the outcome in the database, not the wording: the right cassette on the quote, the total, a quote message in plain language with a date the supplier's lead time backs up, nothing ordered before approval, then one order from a supplier that meets the promised date. A first run passed all 19 required checks in about 30 seconds, for about 6 cents. Results are saved in `evals/results/`.

**Watch the hero story run.** `make demo` launches the three servers and plays the Agent's tool calls in order, including the two the shop refuses (a cassette that doesn't fit, and ordering before the Customer approves). It stands in for the Mechanic sending the quote and the Customer approving it, since neither is an Agent tool. It uses its own database, `data/demo.db`.

**Be the Mechanic, with Claude Code as the Agent.** The repo's `.mcp.json` connects Claude Code to the three servers. Open the project in Claude Code, approve the servers when asked, and try:

> Emma's gravel bike skips under load in the smaller cogs, and the chain checker reads 0.75%. Find her bike, work out what it needs, build the work order and quote, and draft her a message.

The Agent can draft but not send, so the quote stops there. To play the Mechanic and the Customer, use `shop.messages.send_draft` and `shop.work_orders.record_customer_decision` from a Python shell (`uv run python`). The Mechanic's workspace and the Customer's thread arrive with the API and frontend (M4, M6).

## Roadmap

Work is split into milestones, each defined by what it delivers rather than how long it takes.

| Milestone | Delivers | Status |
| --- | --- | --- |
| M0 | Scaffold, schema, CI, decisions log | Done |
| M1 | Seed data and core business rules in `shop/` (fit, stock, quote approval, ordering) | Done |
| M2 | MCP servers: catalog, work orders (including Customer messages), procurement | Done |
| M3 | The Agent, behind the `AgentRuntime` interface (Dust runtime deferred) | Done |
| M4 | Backend API | Next |
| M5 | Eval suite | |
| M6 | Web frontend: Mechanic workspace and Customer thread | |

## Documentation

- [Decisions log](docs/decisions.md)
