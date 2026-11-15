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
