# Decisions log

One entry per choice: what was decided, what was rejected, and why.

## 2026-11-15

### A bike shop as the domain
- **Decided:** a fictional bike shop, Mitchell Bike Co.
- **Why:** parts compatibility is a real rules problem with the same shape as enterprise configure-price-quote, and one service ticket naturally crosses service, procurement, payments, and customer service.

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
- **Why:** customers upgrade their bikes, so fit must be checked against the actual bike, not the catalog model.

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
- **Decided:** the hero repair is a worn chain and cassette, and the twist is that the customer's upgraded wheels need a different cassette than the catalog model. Customer-facing text uses plain language ("the gear cluster on your back wheel"); technical names stay in the agent's working notes. A familiar case such as brake pads covers broader evals.
- **Rejected:** switching the hero to a more familiar part such as tires or brake pads.
- **Why:** skipping gears is one of the most common shop repairs, and a cassette and freehub is the clearest real case where the obvious part doesn't fit the actual bike. The audience needs to follow the twist, not the part names.

### Diagnose from text, service history, and photos
- **Decided:** the agent diagnoses from the complaint plus its own follow-up questions, the bike's service notes, and customer photos. It states its confidence and asks for a measurement (such as a chain checker) when evidence is thin.
- **Rejected:** video and audio input.
- **Why:** both the Anthropic API and Dust handle images and text natively, so the story runs the same on both runtimes. Dust turns audio and video into speech transcripts rather than analyzing sound or footage, so neither would add real evidence. Grounded, multi-source reasoning also gives the evals concrete things to check.
