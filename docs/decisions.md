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
