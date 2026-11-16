# Decisions log

One entry per choice: what was decided, what was rejected, and why.

## 2026-11-15

### A bike shop as the domain
- **Decided:** a fictional bike shop, Mitchell Bike Co.
- **Why:** parts compatibility is a real rules problem with the same shape as enterprise configure-price-quote, and one service ticket naturally crosses service, procurement, payments, and Customer correspondence.

### One hero workflow
- **Decided:** build a single service ticket end to end.
- **Rejected:** separate shallow demos for each department.
- **Why:** one story that works is a better demo than five that half work.

### Business rules live outside the agents
- **Decided:** `shop/` holds every rule (compatibility, stock, spend limit) and has no dependency on any model or agent SDK. MCP servers are thin wrappers over it.
- **Why:** rules can be unit-tested without spending tokens, and they hold whichever agent runtime is calling.

### Approval is a tool result
- **Decided:** the purchase order tool itself returns "pending approval" when an order is over the limit.
- **Rejected:** relying on an agent platform's built-in approval prompts.
- **Why:** platforms differ; enforcing the limit server-side makes it impossible for an agent to skip.

### Swappable agent runtime
- **Decided:** Anthropic by default, behind an `AgentRuntime` interface, with Dust as a second implementation.
- **Why:** shows depth in one platform and proves the design is not locked to it. The same eval suite can then compare both.

### Compatibility as standards
- **Decided:** a bike is the set of interface standards it has; a part lists the standards it requires; a cross-fit table records exceptions with a note.
- **Rejected:** a part-to-bike-model lookup table.
- **Why:** Customers upgrade their bikes, so fit must be checked against the actual bike, not the catalog model.

### SQLite
- **Decided:** SQLite with a schema file and YAML seed data.
- **Rejected:** Postgres.
- **Why:** anyone can clone the repo and run it with no setup.

### Real standards, invented products
- **Decided:** real interface standards, with invented brands, product names, and prices in the shop catalog.
- **Why:** standards are facts about how bikes are built; invented products avoid implying real prices or stock.

### Milestones, not days or sprints
- **Decided:** split the work into numbered milestones (M0, M1, ...), each defined by what it delivers.
- **Rejected:** "days", which read as a schedule commitment; "sprints", a Scrum term for fixed timeboxes with team ceremonies.
- **Why:** this is a solo project split by deliverable, and milestones map directly onto GitHub Milestones for tracking issues and PRs.

### Keep the cassette as the hero part
- **Decided:** the hero repair is a worn chain and cassette, and the twist is that the Customer's upgraded wheels need a different cassette than the catalog model. Customer-facing text uses plain language ("the gear cluster on your back wheel"); technical names stay in the Agent's working notes. A familiar case such as brake pads covers broader evals.
- **Rejected:** switching the hero to a more familiar part such as tires or brake pads.
- **Why:** skipping gears is one of the most common shop repairs, and a cassette and freehub is the clearest real case where the obvious part doesn't fit the actual bike. The audience needs to follow the twist, not the part names.

### Diagnose from text, service history, and photos
- **Decided:** the Agent diagnoses from the complaint plus its own follow-up questions, the bike's service notes, and photos. It states its confidence and asks for a measurement (such as a chain checker) when evidence is thin.
- **Rejected:** video and audio input.
- **Why:** both the Anthropic API and Dust handle images and text natively, so the story runs the same on both runtimes. Dust turns audio and video into speech transcripts rather than analyzing sound or footage, so neither would add real evidence. Grounded, multi-source reasoning also gives the evals concrete things to check.

### Seed data uses readable keys
- **Decided:** seed YAML refers to SKUs, standard kind and name, and bike model keys; the loader resolves them to row ids and rejects anything unknown. Customers' bikes inherit their model's standards and list only their upgrades.
- **Rejected:** hand-numbered ids in the YAML.
- **Why:** ids break as soon as a record is added, and "upgrades" make the hero twist visible in the data itself.

### Catalog model specs are stored, but fit ignores them
- **Decided:** a `bike_model_standards` table records what each model ships with. Fit checks only read `bike_standards`, the Customer's actual bike.
- **Why:** the Agent needs to say "the catalog says X, but your bike has Y". Storing the model specs makes that possible without letting them leak into the fit check.

### The Agent works for the Mechanic, not the Customer
- **Decided:** the Mechanic (shop staff) uses the Agent. The Customer is who the work is for, and appears through messages and a payment link.
- **Rejected:** a Customer-facing chat agent as the main user.
- **Why:** with the Customer as the user, "your purchase" and "the shop's purchase" blurred together. It matches the configure-price-quote parallel, where staff use the tools, and a person checks the Agent's work before anything reaches the Customer.
- **Revises:** "Diagnose from text, service history, and photos". The inputs stay the same, but the main evidence is now the Mechanic's observations and measurements. Photos are optional supporting evidence.

### Customer correspondence: the Agent drafts, the Mechanic sends
- **Decided:** the Agent drafts messages to the Customer (quote, ready date, answers to questions) in plain language, and the Mechanic reviews each draft before it is sent. The Agent reads the Customer's replies and updates the work order from them.
- **Why:** it puts the plain-language rule and the Customer's side of the story on screen without letting an agent talk to the public unchecked. It also gives evals something concrete: no promised date the supplier's lead time can't meet, no jargon, and no price that differs from the quote. Messages will be stored per work order (schema to come with the work-order tools in M2).

### The Customer is the human in the loop
- **Decided:** the only approval in the story is the Customer's. The quote locks the work order's lines and total; the Customer approves that exact amount or declines; and `shop/procurement.py` refuses to order parts for a work order until it is approved, or beyond the parts and quantities on the quote. Parts added to a work order must fit the bike. The shop orders one cassette, for the job.
- **Rejected:** a Shop Manager approving shop spending over a limit, with the Agent also restocking the shelf. It was a second approval about a different purchase, and it made the story hard to follow.
- **Revises:** "Approval is a tool result". The principle stands (the rule is enforced in the shop's code, not by an agent platform's prompt), but the gate is now the Customer's approval instead of a spend limit.
- **Why:** one approval, by the person whose money it is, is easy to follow and still shows an agent that cannot act without a human's sign-off. Supplier choice (faster or cheaper) stays as the Agent's judgment call.

### Persona language in documentation
- **Decided:** documentation names people by persona, capitalized: Customer, Mechanic, Agent. Seed data keeps realistic names (such as Emma Clark, the hero Customer).
- **Rejected:** telling the story with a named character.
- **Why:** personas keep the roles clear as the story grows, and match how the frontend, evals, and docs will refer to each role.

### The Customer approves with an action, not a reply
- **Decided:** the quote reaches the Customer in a message that carries the locked total, with approve and decline actions. Only the Customer's action records the decision, against that specific sent message. The Agent reads replies to answer questions, but has no tool to record an approval.
- **Rejected:** the Agent interpreting a free-text reply ("sounds good, though Friday would be better") as approval.
- **Revises:** "Customer correspondence: the Agent drafts, the Mechanic sends", which had the Agent updating the work order from the Customer's replies.
- **Why:** this is the one approval the story relies on, so it must not depend on a model reading intent. Tying it to a sent message also guarantees the Customer was shown the amount they approved.

### Who can do what is enforced twice
- **Decided:** drafting is open to the Agent and the Mechanic; sending a draft is the Mechanic's; recording a decision is the Customer's. The MCP servers leave those last two out of the Agent's tools, and `shop/` refuses them in the wrong state (unsent quote, stale quote, decided work order).
- **Why:** tool access alone is a configuration that can drift, and state rules alone don't say who acted. Together, a mistake in either still leaves the other in place.

### Service history is structured data
- **Decided:** a `service_records` table (date, odometer, summary) per bike, seeded from `customers.yaml`.
- **Rejected:** free-text notes files in `data/service_notes/`.
- **Why:** the Agent cites specific evidence ("chain replaced at 5,000 km; the cassette came with the wheels at 6,900 km and has not been replaced"), and evals can check it against the same rows.

### Ready dates come from a rule
- **Decided:** ready date = order date + the slowest supplier's lead time + one repair day, in calendar days (`shop/schedule.py`).
- **Why:** the Agent may only promise dates the shop can back up, and a rule makes "no promise the lead time can't meet" checkable. Calendar days keep it simple until opening hours matter.

### Three MCP servers on the v2 SDK
- **Decided:** catalog, work orders, and procurement as three servers built on the official MCP Python SDK v2 (`MCPServer`). Each runs over stdio by default or Streamable HTTP with `--http`. A shared `shop_tool` decorator opens a fresh database connection per call, maps shop errors to tool errors, and writes the audit log.
- **Rejected:** one combined server; pinning the v1 SDK (`FastMCP`).
- **Why:** an Agent composing several servers is how MCP is meant to be used, and the shared layer keeps the duplication small. v2 is current, so there's no migration later. HTTP is there from the start because Dust can only reach servers over the web.

### Refusals are tool errors the model can read
- **Decided:** a `NotFound` or `RuleViolation` from `shop/` becomes a tool result with `is_error` and the rule's own message ("parts can only be ordered after the customer approves the quote"). Any other exception is logged and reaches the model only as a generic error.
- **Why:** the Agent can correct itself from a clear reason, and evals can check that it did. Unexpected crashes don't leak internals into a conversation.

### The audit log records who called, from the environment
- **Decided:** every tool call writes the tool, its arguments, and a result summary (or the refusal) to `audit_log`. The runtime and conversation id come from the `AGENT_RUNTIME` and `CONVERSATION_ID` environment variables of the server process.
- **Why:** the record is written by the server, so it's the same whichever runtime calls. Passing the conversation id per request (in MCP request metadata) can replace the environment variable in M3 if one server process serves many conversations.

### Try it two ways before there's an Agent
- **Decided:** a committed `.mcp.json` lets Claude Code act as the Agent against the real servers, and `make demo` replays the hero story through the servers as stdio subprocesses, launched the way a runtime launches them. The demo plays the Mechanic's send and the Customer's approval directly through `shop/`, and uses its own database.
- **Why:** both exercise the tools end to end before M3. The demo is also a test (`tests/test_demo.py`), so the launch path an agent runtime uses is checked in CI, not just the in-memory one.

### Claude Sonnet 5.5 at medium effort, with server-side fallback
- **Decided:** the Agent runs on `claude-sonnet-5-5` (set by `AGENT_MODEL`) at effort `medium` (`AGENT_EFFORT`), with adaptive thinking and progress updates shown to the Mechanic. Requests opt into `fallbacks: "default"`, so a declined request is retried server-side on the model Anthropic recommends. The prompt and tool list are prompt-cached.
- **Rejected:** Claude Opus 5.5 as the default; a separate router model (`ROUTER_MODEL`), which only made sense with several agents.
- **Why:** Sonnet 5.5 costs half as much as Opus 5.5 and is faster, which suits a few-step tool workflow. `medium` is Anthropic's suggested starting point for multi-step tool use; the evals in M5 decide whether to raise it.

### A hand-written agent loop, stored message by message
- **Decided:** the Anthropic runtime runs its own loop over `client.beta.messages.create`: call the model, run the requested tools through MCP, send all results back in one message, repeat (up to 25 calls per turn). Every message is stored in `agent_messages` exactly as sent, and a conversation can be resumed from the database.
- **Rejected:** the SDK's beta tool runner with its MCP helpers.
- **Why:** Claude Sonnet 5.5 ties thinking blocks to the exact conversation, so the history must be stored and replayed byte for byte, and the M4 API needs to resume conversations across requests. The loop is short, and it also gives a clean record of tool calls for the CLI and the evals.

### Each conversation gets its own server processes
- **Decided:** the Anthropic runtime launches the three MCP servers over stdio for each conversation, with `CONVERSATION_ID` set, so every audit log entry names its conversation.
- **Why:** it makes the audit log complete with no change to MCP requests. The cost (three short-lived processes per conversation) is fine at this scale; a hosted deployment can revisit it.

### The Mechanic chat stands in for the screens
- **Decided:** `make agent` is a terminal chat in which the user is the Mechanic. Slash commands perform the actions that are not the Agent's (sending a draft, the Customer's approval or reply), and the Agent hears about them as a short shop update with the next message.
- **Why:** it makes the whole story playable with the real model before the M4 API and M6 frontend exist, without giving the Agent tools it must not have.

### Judge the Agent by what it did, not what it said
- **Decided:** `make agent-check` runs the hero story against the real model and checks the shop's state afterwards: work order lines, the locked total, the drafted quote message (total, no part numbers, a date that `estimate_ready_date` can back up for a supplier), no order before approval, then one order from a supplier that meets the promised date. Required checks decide pass or fail. Advisory ones, such as whether the diagnosis cites the measurement or whether an in-stock part was ordered, are reported but don't fail the run. Each run saves its checks, tool calls, tokens, and estimated cost to `evals/results/`.
- **Rejected:** grading the Agent's replies with another model (for now); running it in CI.
- **Why:** state checks are deterministic, free to evaluate, and test what matters to the shop. The wording of replies varies from run to run. Running the check costs real money, so it stays opt-in. The same checker runs against a scripted model in the unit tests, so its logic is covered in CI. It is the seed of the M5 scenario suite.

### Defer the Dust runtime
- **Decided:** M3 ships with the Anthropic runtime only. The Dust runtime (secured web-reachable servers, a public address, a Dust agent set up in its builder) is deferred.
- **Revises:** "Swappable agent runtime". The `AgentRuntime` interface stays, and so do the servers' HTTP transport and the `DUST_*` settings, so a second platform can be added later without changes elsewhere.
- **Why:** it needs a Dust workspace with admin rights, plus hosting, and the story is complete without it. The time goes to the API and frontend, which make the project usable.

### The rest of the work order lifecycle
- **Decided:** after the order, the shop marks the purchase order received (stock goes up), schedules the repair for a date once every part is on the shelf, starts it, and finishes it (stock goes down). The Customer then pays the locked quote: a payment is started (for example, a Stripe checkout) and completed when the money is confirmed, for exactly the quoted amount. Abandoned checkouts stay pending and don't block a retry.
- **Why:** each step is a rule in `shop/`, so the API, the Agent, and tests all get the same checks. Stock is checked when the repair is scheduled and again when it is finished, but not reserved in between; with one hero story that is enough, and a reservation table can come later if two jobs ever compete for one part.

### The Customer gets a private link, not an account
- **Decided:** each work order gets an unguessable token (192 bits). The Customer's view of the thread, the quote, and payment is reached only through it.
- **Rejected:** customer accounts and passwords.
- **Why:** it matches how shops already reach customers (a text with a link), and it keeps the Customer side to exactly one work order. Accounts would be a lot of work for nothing the story needs.

### A thin FastAPI app with a staff passcode
- **Decided:** the API is FastAPI over `shop/`. Staff endpoints (work orders, the thread, editing and sending drafts, receiving parts, scheduling, starting and finishing the repair) need `STAFF_PASSCODE` as a bearer token, and fail closed when it isn't set. Customer endpoints are under `/api/customer/{token}`. A `NotFound` becomes 404, and a `RuleViolation` becomes 409 with the rule's message.
- **Rejected:** staff accounts and logins for now.
- **Why:** one passcode keeps the staff side from being open while the app runs locally; real accounts belong with hosting. Keeping rules in `shop/` means the API, the MCP servers, and the tests can't disagree.

### The Customer sees the conversation, not the workshop
- **Decided:** the Customer's view has their bike, the quote lines and total, sent messages and their own replies, the schedule, and whether it's paid. It leaves out drafts, the diagnosis notes, purchase orders, and anything about other work orders. A decision on a message from another work order returns 404, the same as a message that doesn't exist.
- **Why:** drafts are the Mechanic's to review, and internal notes are written for the shop. Answering 404 either way means a link can't be used to probe other work orders.

### Stripe Checkout in test mode, confirmed with Stripe
- **Decided:** a finished repair is paid through Stripe's hosted Checkout page, for exactly the locked quote. The server starts a pending payment, creates a Checkout session (idempotent per payment), and records it. When the Customer comes back, the server retrieves the session from Stripe and checks that it belongs to this work order, is in USD, and is paid, before completing the payment. `/checkout/confirm` does the same for a Customer who closed the page early. Only test-mode keys are accepted.
- **Rejected:** webhooks for now; a simulated pay button.
- **Why:** hosted Checkout keeps card details off this app entirely, and test mode makes it a real Stripe flow without real money. Confirming by retrieving the session needs no public address, unlike webhooks, so it works on a laptop. Webhooks can be added with hosting, as the safety net for Customers who never come back.
