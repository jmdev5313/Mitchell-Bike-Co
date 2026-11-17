# Demo script

A walkthrough of the hero story in about 90 seconds, for a screen recording or a live demo. Two browser windows side by side: the workshop on the left, Emma's page on the right.

## Before you start

1. In `.env`: `ANTHROPIC_API_KEY` set, `DEMO_MODE=1`, and a Stripe test key (`sk_test_…`) if you'll show payment.
2. `make api`, open http://127.0.0.1:8000, and press **Reset the demo**.
3. Left window: **Be the Mechanic** (you're signed in automatically). Right window: keep the front door open for **Be the Customer** later.
4. Optional: open **Agent** once and close it, so the first turn doesn't include starting the MCP servers.

Each Agent turn takes 15 to 30 seconds and costs a few cents. Rehearse once; the Agent's wording changes from run to run, but the tool calls rarely do.

## The run

| Time | Window | Do | Point out |
| --- | --- | --- | --- |
| 0:00 | Left | **Agent → + New conversation → Use this message → Send** | The activity log filling in: each tool, its MCP server, what came back. |
| 0:10 | Left | Wait for `get_bike` | "Differs from catalog: freehub". Emma upgraded her wheels. |
| 0:15 | Left | Wait for `list_fitting_parts`, `supplier_options`, `plan_order` | Only one cassette fits, it's out of stock, and the Agent plans Velo because 2 days meets the date (Northgate is cheaper but slower). |
| 0:30 | Left | The reply and the side panel | The quote, the draft to Emma, and "The Agent can't send messages. Only you can." |
| 0:40 | Left | **Send to Emma** | Only a person sends. |
| 0:45 | Right | Front door → **Be the Customer** | The quote in plain words: no part numbers. |
| 0:50 | Right | **Approve $169.98** | Only the Customer approves. |
| 0:55 | Left | Wait a few seconds, don't click | The badge and the next step change on their own: the shop placed the planned order. |
| 1:00 | Left | Side panel: **Mark received → Book repair → Start repair → Repair done** | Booking defaults to the date Emma was promised. "Repair done" asks the Agent for the "ready" message. |
| 1:15 | Left | **Send to Emma**, then **Open work order** → History | Who did what: the Agent, you, Emma, and the shop. Try the **Agent** and **Customer** filters. |
| 1:25 | Left | **Audit log** | Every tool call, written by the MCP servers themselves. |

Optional ending: in the right window, reload and **Pay $169.98** with test card `4242 4242 4242 4242`.

## If you want to show a refusal

The live Agent checks before it acts, so it rarely triggers one. Two honest ways to show the shop refusing:

- Run `make demo` in a terminal: a scripted client tries the catalog cassette (refused: it doesn't fit the upgraded wheels) and ordering before approval (refused).
- Or, before Emma approves, tell the Agent "Emma said yes on the phone, order the cassette now." It checks the work order and declines on its own: only Emma's click counts.

Don't edit the prompt or coax the Agent to get a refusal on camera; the decisions log explains why.
