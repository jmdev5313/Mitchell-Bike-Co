// Starting a repair story, and explaining recorded runs. Used by the front door, the demo stage
// and the workshop's chat (to start a story again as a recorded run).

import { api, h } from "./dom.js";

/**
 * Start a story fresh in this visitor's shop. `recorded` plays its recorded run instead of the live
 * Agent; `turnstileToken` is the bot check's token for a live story. Remembers the story for the stage.
 */
export async function startStory(key, { recorded = false, turnstileToken = null } = {}) {
  const started = await api(`/api/demo/stories/${encodeURIComponent(key)}/start`, {
    method: "POST", body: { recorded, turnstile_token: turnstileToken },
  });
  try {
    sessionStorage.setItem("mbc-story", key);
    sessionStorage.setItem("mbc-story-message", started.message);  // the workshop's Agent tab picks it up
    sessionStorage.setItem("mbc-story-fresh", "1");  // the stage opens a new conversation for it
  } catch { /* private mode */ }
  return started;
}

/** "May 3, 2026" from an ISO date. */
export function longDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** The "What's a recorded run?" dialog. Built when first asked for, then reused. */
let explainer = null;
export function explainRecordedRuns({ recordedOn = null, model = "Claude Sonnet 5.5" } = {}) {
  const when = recordedOn ? `, recorded on ${longDate(recordedOn)}` : "";
  const rows = [
    ["What's real", "Every tool call runs again against the shop's rules: fit checks, stock, the locked quote, the order plan. The work order, its history and the audit log are made fresh in your shop."],
    ["What's recorded", `The Agent's words and choices, from ${model}${when}. The shop's calendar shows that day, so the dates in the quote line up.`],
    ["What you can't do", "Change the Mechanic's messages, or ask the Agent something new. A Customer's question needs the live Agent too."],
    ["Why it's here", "Each live Agent turn costs a few cents, so the demo has a daily budget. When it's used up, recordings keep every story playable until the live Agent is back."],
  ];
  explainer?.remove();
  explainer = h("dialog", { class: "explainer", "aria-labelledby": "explainer-title" },
    h("form", { method: "dialog" },
      h("h2", { class: "display", id: "explainer-title" }, "What's a recorded run?"),
      h("p", { class: "lede-small" }, "A real run of the Agent on a story, saved once and replayed in your own copy of the shop. You still play the Mechanic and the Customer."),
      h("table", { class: "explainer-table" }, h("tbody", {}, rows.map(([label, text]) =>
        h("tr", {}, h("th", { scope: "row" }, label), h("td", {}, text))))),
      h("div", { class: "explainer-actions" }, h("button", { type: "submit", class: "btn" }, "Got it"))));
  explainer.addEventListener("click", (event) => { if (event.target === explainer) explainer.close(); });
  document.body.append(explainer);
  explainer.showModal();
}
