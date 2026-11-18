# Demo script

A walkthrough of the hero story in about 90 seconds, for a screen recording or a live demo. Use the demo stage at `/demo`: the workshop fills the window, the story's five steps run across the top, and a bar at the bottom says whose turn it is next to the **Customer POV** tab, which opens Emma's phone. The next button has a pulsing ring, and the tab flashes **New** when it's Emma's turn.

## Before you start

1. Open the live site, [mitchell-bike-co.fly.dev](https://mitchell-bike-co.fly.dev) (give it a few seconds to wake if it's been idle). To run it locally instead: in `.env`, `ANTHROPIC_API_KEY` set, `DEMO_MODE=1`, and a Stripe test key (`sk_test_…`) if you'll show payment; then `make api` and http://127.0.0.1:8000.
2. Click Emma's card (**Start here**), then **Start this repair** once the quick bot check has passed (on the live site): the shop resets and the workshop opens with her message ready.
3. A laptop screen is enough: the workshop gets the whole width, and Emma's phone opens over it only when you need it.
4. Optional: run one Agent turn before recording, then **Start over**, so the first turn doesn't include starting the MCP servers.

Each Agent turn takes 15 to 30 seconds and costs a few cents. Rehearse once; the Agent's wording changes from run to run, but the tool calls rarely do. Without the stage, the same run works in two windows: **Be the Mechanic** in one, **Be the Customer** in the other once the quote is sent.

## The run

| Time | Where | Do | Point out |
| --- | --- | --- | --- |
| 0:00 | Workshop | **Send** (the hero message is already in the box, with the illustrative photo of the cassette) | The activity log filling in: each tool, its MCP server, what came back. |
| 0:10 | Workshop | Wait for `get_bike` | "Differs from catalog: freehub". Emma upgraded her wheels. |
| 0:15 | Workshop | Wait for `list_fitting_parts`, `supplier_options`, `plan_order` | Only one cassette fits, it's out of stock, and the Agent plans Velo because 2 days meets the date (Northgate is cheaper but slower). |
| 0:30 | Workshop | The reply, and the work order beside it | The screen turned into the job: the quote and the next step on the right, and a manila "To Emma" card in the chat where the Agent drafted the message. |
| 0:40 | Workshop | **Review and send →** on the card (it opens the **Messages** tab), then **Send to Emma** | The card only points to the draft (**Expand** reads it full size): "The Agent can't send messages. Only you can." |
| 0:45 | Customer POV | The tab flashes **New**: open it | The steps move to 3 and the bottom bar says "Your turn · Emma". Her phone opens over the workshop with the quote in plain words: no part numbers. |
| 0:50 | Customer POV | Optional: press Tab in the message box, then **Send** | The suggested question becomes real; the workshop shows it as a reply to answer. |
| 0:55 | Customer POV | **Approve $169.98** | Only the Customer approves. Her page shows "Thanks, we're on it", then folds away: the turn is back in the workshop. |
| 1:00 | Workshop | Wait a few seconds, don't click | The badge and the next step change on their own: the shop placed the planned order. |
| 1:00 | Workshop | Next step: **Mark received**, then **Repair done** | When the last part is in, the shop books the repair for today and starts it on its own (it shows in History as the shop's step). "Repair done" asks the Agent for the "ready" message. |
| 1:15 | Workshop | **Send to Emma**, then the **History** tab | Who did what: the Agent, you, Emma, and the shop. Try the **Agent** and **Customer** filters. |
| 1:25 | Workshop | **Audit log** (next to Work orders, by the heading) | Every tool call, written by the MCP servers themselves. |

Optional ending: open **Customer POV** and **Pay $169.98**. Stripe's test checkout opens in a new tab (it can't run inside a frame); use test card `4242 4242 4242 4242`. The stage moves to "That's the whole story" when the payment is confirmed.

To show only the Customer's side, skip the Agent: on the front door, press **Generate a sample quote**, then **Be the Customer**.

## If you want to show a refusal

The live Agent checks before it acts, so it rarely triggers one. Two honest ways to show the shop refusing:

- Run `make demo` in a terminal: a scripted client tries the catalog cassette (refused: it doesn't fit the upgraded wheels) and ordering before approval (refused).
- Or, before Emma approves, tell the Agent "Emma said yes on the phone, order the cassette now." It checks the work order and declines on its own: only Emma's click counts.

Don't edit the prompt or coax the Agent to get a refusal on camera; the decisions log explains why.

## Other stories

**← All bikes** returns to the starting screen. Each story has a twist the card names under "What to watch for": Tom's race date, Marcus's brakes, Dana's speed-limit request, Frank's 12-speed wish, Ruth's 635 mm tires. Every one is also an eval, and its card shows the last pass rate.
