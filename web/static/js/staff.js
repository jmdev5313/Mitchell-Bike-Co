// Shared pieces of the Mechanic workspace: the staff passcode, stages, and the
// components that appear on more than one screen (stage meter, draft band, ledger).

import { h, dollars, shortDate } from "./dom.js";

const KEY = "mbc-staff-passcode";

export function passcode() {
  try { return sessionStorage.getItem(KEY) || ""; } catch { return ""; }
}
export function setPasscode(value) {
  try { value ? sessionStorage.setItem(KEY, value) : sessionStorage.removeItem(KEY); } catch { /* private mode */ }
}

export class Unauthorized extends Error {}

/** fetch() for staff endpoints: adds the passcode, parses JSON, throws with the API's reason. */
export async function staff(path, { method = "GET", body, form } = {}) {
  const headers = { Authorization: `Bearer ${passcode()}` };
  const options = { method, headers };
  if (form) options.body = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const response = await fetch(path, options);
  if (response.status === 401) throw new Unauthorized("staff passcode required");
  let data = null;
  try { data = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) {
    const error = new Error((data && data.detail) || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}

// --- Stages ------------------------------------------------------------------

export const STAGES = ["Diagnosed", "Quoted", "Customer approval", "Parts", "Repair", "Paid"];

const STATUS = {
  intake: { done: 0, label: "Intake" },
  diagnosed: { done: 1, label: "Diagnosed" },
  quoted: { done: 2, label: "Quoted" },
  declined: { done: 2, label: "Declined" },
  approved: { done: 3, label: "Approved" },
  awaiting_parts: { done: 3, label: "Awaiting parts" },
  scheduled: { done: 4, label: "Scheduled" },
  in_progress: { done: 4, label: "In repair" },
  done: { done: 5, label: "Ready to pay" },
  paid: { done: 6, label: "Paid" },
};

export function stageOf(status) {
  return STATUS[status] || { done: 0, label: status };
}

/** Six small segments plus a text label, in place of a status pill. */
export function stageMeter(status) {
  const { done, label } = stageOf(status);
  return h("span", { class: "stage" },
    h("span", { class: "segs", "aria-hidden": "true" },
      STAGES.map((_, i) => h("span", { class: `seg${i < done ? " on" : ""}` }))),
    h("span", {}, label),
    h("span", { class: "visually-hidden" }, `, step ${Math.min(done + 1, 6)} of 6`));
}

/** Six bars: done solid, current striped, future light grey. */
export function progressStrip(status) {
  const { done } = stageOf(status);
  const declined = status === "declined";
  return h("ol", { class: "strip", "aria-label": "Progress" },
    STAGES.map((name, i) => {
      const state = i < done ? "done" : i === done && !declined && status !== "paid" ? "current" : "future";
      return h("li", { class: state, "aria-current": state === "current" ? "step" : null },
        h("span", { class: "bar", "aria-hidden": "true" }),
        i === 2 && declined ? "Declined" : name,
        state === "done" ? h("span", { class: "visually-hidden" }, " (done)") : null);
    }));
}

// --- Components --------------------------------------------------------------

export function ledger(lines, total, { totalLabel = "Total", totalSize = 30, stock = null } = {}) {
  const rows = lines.map((line, i) =>
    h("tr", { class: i === lines.length - 1 ? "last" : null },
      h("th", { scope: "row" }, line.qty > 1 ? `${line.name} × ${line.qty}` : line.name,
        stock ? stock(line) : null),
      h("td", {}, dollars(line.unit_price_cents * line.qty))));
  rows.push(h("tr", { class: "total" },
    h("th", { scope: "row" }, totalLabel),
    h("td", { style: `font-size: ${totalSize}px` }, dollars(total))));
  return h("table", { class: "ledger", style: "font-size: 14px" }, h("tbody", {}, rows));
}

/** The latest draft to the Customer, editable, with "Send to Emma". Only a person sends. */
export function draftBand(order, { onChange, customerName }) {
  const drafts = order.messages.filter((m) => m.status === "draft");
  const draft = drafts[drafts.length - 1];
  if (!draft) return null;
  const first = (customerName || "the Customer").split(" ")[0];
  const id = `draft-${draft.id}`;
  const textarea = h("textarea", { id, class: "textarea", rows: 5 });
  textarea.value = draft.body;
  const status = h("p", { class: "small", role: "status", style: "margin: 0" });
  let busy = false;

  async function save() {
    if (textarea.value.trim() !== draft.body) {
      await staff(`/api/messages/${draft.id}`, { method: "PATCH", body: { body: textarea.value.trim() } });
    }
  }
  async function run(label, work) {
    if (busy) return;
    busy = true;
    status.textContent = label;
    try {
      await work();
      onChange();
    } catch (e) {
      busy = false;
      status.replaceChildren(h("span", { class: "notice-refused", style: "display: block" },
        h("strong", {}, "Couldn't do that: "), e.message));
    }
  }

  const sendIt = () => run("Sending…", async () => { await save(); await staff(`/api/messages/${draft.id}/send`, { method: "POST" }); });

  // The full-size editor: the same draft in a dialog, for reading and editing it comfortably.
  const big = h("textarea", { class: "textarea", "aria-label": `Draft to ${first} (large editor)` });
  const dialog = h("dialog", { class: "expand-dialog draft-dialog", "aria-labelledby": `${id}-big-title` },
    h("form", { method: "dialog", onsubmit: (event) => event.preventDefault() },
      h("div", { class: "head" },
        h("h2", { id: `${id}-big-title`, class: "display", style: "font-size: 28px" }, `Draft to ${first}`),
        draft.quoted_total_cents !== null ? h("span", { class: "meta" }, `Carries the ${dollars(draft.quoted_total_cents)} quote`) : null),
      big,
      h("p", { class: "who-sends", style: "margin: 0" }, "The Agent can't send messages. Only you can, after reviewing it."),
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn btn-outline", onclick: () => { textarea.value = big.value; dialog.close(); textarea.focus(); } },
          "Back to the small box"),
        h("span", { style: "display: flex; gap: 8px; flex-wrap: wrap" },
          h("button", { type: "button", class: "btn btn-outline", onclick: () => { textarea.value = big.value; dialog.close(); run("Saving…", save); } },
            "Save edits"),
          h("button", { type: "button", class: "btn btn-send", onclick: () => { textarea.value = big.value; dialog.close(); sendIt(); } },
            `Send to ${first}`)))));
  dialog.addEventListener("cancel", () => { textarea.value = big.value; });

  return h("div", { class: "draft-band", id: `${id}-band`, tabindex: "-1" },
    h("div", { class: "head" },
      h("label", { class: "title", for: id }, `Draft to ${first}`),
      h("span", { class: "meta" },
        draft.quoted_total_cents !== null ? `Carries the ${dollars(draft.quoted_total_cents)} quote · ` : "",
        `Drafted by the ${draft.author === "agent" ? "Agent" : "Mechanic"}, ${shortDate(draft.created_at)}`,
        " · ",
        h("button", { type: "button", class: "linkish", onclick: () => { big.value = textarea.value; dialog.showModal(); big.focus(); big.setSelectionRange(0, 0); big.scrollTop = 0; } },
          "Expand"))),
    textarea,
    h("p", { class: "who-sends", style: "margin: 0" },
      "The Agent can't send messages. Only you can, after reviewing it."),
    h("div", { class: "actions" },
      h("button", { type: "button", class: "btn btn-send", onclick: sendIt }, `Send to ${first}`),
      h("button", { type: "button", class: "btn btn-outline",
        onclick: () => run("Saving…", save) }, "Save edits")),
    status, dialog);
}

/** The Customer's private link, with open and copy. */
export function customerLink(token, name) {
  if (!token) {
    return h("p", { class: "small muted", style: "margin: 0" },
      `${name || "The Customer"} gets a private link when the first message is sent.`);
  }
  const url = `${location.origin}/c/${token}`;
  const copied = h("span", { class: "small muted", role: "status" });
  return h("div", { style: "display: flex; flex-wrap: wrap; gap: 8px; align-items: center" },
    h("a", { class: "btn btn-outline", href: url, target: "_blank", rel: "noopener noreferrer" },
      `Open ${(name || "Customer").split(" ")[0]}'s page`),
    h("button", { type: "button", class: "btn btn-outline", onclick: async () => {
      try { await navigator.clipboard.writeText(url); copied.textContent = "Link copied"; }
      catch { copied.textContent = url; }
    } }, "Copy link"),
    copied);
}

export function refusedNotice(message) {
  return h("p", { class: "notice-refused", role: "alert" }, h("strong", {}, "Refused: "), message);
}

// --- Next step, history, badges ------------------------------------------------

const WHOSE = { mechanic: "Your turn", agent: "The Agent's turn", customer: "The Customer's turn", shop: "The shop's turn", nobody: "Nothing to do" };

/** The hero story's opening message, offered wherever a conversation starts. */
export const HERO = "Emma Clark's gravel bike is on the stand. Gears skip under load in the smaller cogs, and my chain checker reads 0.75%. Work out what it needs and draft her a quote.";

/** Open a fresh conversation (reusing an unused one) with the hero message waiting in the box. */
export async function startWithAgent() {
  try { sessionStorage.setItem("mbc-prefill", HERO); } catch { /* private mode */ }
  const unused = (await staff("/api/conversations")).find((c) => c.turns === 0 && !c.work_order_id);
  const id = unused ? unused.id : (await staff("/api/conversations", { method: "POST" })).conversation_id;
  if (location.hash === `#/agent/${id}`) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = `#/agent/${id}`;
}

/** Ask the Agent: open the job's screen with the prompt waiting in the message box. */
export function askAgent(order, prompt) {
  try { sessionStorage.setItem("mbc-prefill", prompt); } catch { /* private mode */ }
  location.hash = `#/work-orders/${order.work_order_id}`;
}

export function takePrefill() {
  try {
    const value = sessionStorage.getItem("mbc-prefill");
    sessionStorage.removeItem("mbc-prefill");
    return value || "";
  } catch { return ""; }
}

/** What happens next, whose turn it is, and the one button that moves it forward. */
export function nextStepBar(order, { onChange, onFinished, onAskAgent, onReviewDraft } = {}) {
  const step = order.next_step;
  const action = step.action;
  const id = order.work_order_id;
  const status = h("span", { class: "small", role: "status" });
  let busy = false;

  async function run(work) {
    if (busy) return;
    busy = true;
    status.textContent = "Working…";
    try { await work(); onChange && onChange(); }
    catch (e) { busy = false; status.replaceChildren(h("span", { class: "refused" }, h("strong", {}, "Refused: "), e.message)); }
  }

  const controls = [];
  if (action) {
    if (action.kind === "send_draft") {
      controls.push(h("button", { type: "button", class: "btn", onclick: () => {
        if (onReviewDraft) return onReviewDraft();
        const box = document.getElementById(`draft-${action.message_id}`);
        if (box) { box.scrollIntoView({ block: "center" }); box.focus(); }
      } }, "Review the draft"));
    } else if (action.kind === "receive") {
      controls.push(h("button", { type: "button", class: "btn", onclick: () => run(() => staff(`/api/purchase-orders/${action.purchase_order_id}/receive`, { method: "POST" })) }, action.label));
    } else if (action.kind === "book") {
      const date = h("input", { type: "date", class: "input", value: action.date, "aria-label": "Repair date" });
      controls.push(h("button", { type: "button", class: "btn", onclick: () => run(() => staff(`/api/work-orders/${id}/schedule`, { method: "POST", body: { scheduled_for: date.value } })) }, "Book repair"), date);
    } else if (action.kind === "start") {
      controls.push(h("button", { type: "button", class: "btn", onclick: () => run(() => staff(`/api/work-orders/${id}/start`, { method: "POST" })) }, action.label));
    } else if (action.kind === "finish") {
      controls.push(h("button", { type: "button", class: "btn", onclick: () => run(async () => {
        await staff(`/api/work-orders/${id}/finish`, { method: "POST" });
        if (onFinished) onFinished();
      }) }, action.label));
    } else if (action.kind === "ask_agent") {
      controls.push(h("button", { type: "button", class: "btn", onclick: () => (onAskAgent ? onAskAgent(action.prompt) : askAgent(order, action.prompt)) }, action.label));
    }
  }

  return h("div", { class: "nextbar" },
    h("div", { class: "what" },
      h("span", { class: "lbl" }, "Next"),
      h("span", { class: "text" }, step.text),
      h("span", { class: "whose" }, WHOSE[step.waiting_on] || "")),
    controls.length ? h("div", { class: "do" }, controls, status) : null);
}

function when(iso) {
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
}

const ACTOR_LABEL = { agent: "Agent", mechanic: "Mechanic", customer: "Customer", shop: "Shop" };

/** The work order's history, filterable by who acted. Items new since the last visit are marked. */
export function historySection(order) {
  const newIds = new Set((order.unseen || []).map((e) => e.id));
  let filter = "all";
  const list = h("ol", { class: "history", "aria-label": "History" });
  const counts = (actor) => order.history.filter((e) => actor === "all" || e.actor === actor).length;
  const buttons = ["all", "agent", "mechanic", "customer", "shop"].map((actor) =>
    h("button", { type: "button", "aria-pressed": String(actor === filter), onclick: () => { filter = actor; draw(); } },
      `${actor === "all" ? "All" : ACTOR_LABEL[actor]} · ${counts(actor)}`));
  function draw() {
    buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(["all", "agent", "mechanic", "customer", "shop"][i] === filter)));
    const shown = order.history.filter((e) => filter === "all" || e.actor === filter);
    list.replaceChildren(...(shown.length ? shown.map((e) => h("li", {
      class: [e.is_error ? "is-refused" : "", newIds.has(e.id) ? "is-new" : ""].join(" ").trim() || null,
    },
      h("span", { class: "when" }, when(e.at)),
      h("span", { class: `actor ${e.actor}` }, ACTOR_LABEL[e.actor]),
      h("span", { class: "summary" },
        newIds.has(e.id) ? h("span", { class: "visually-hidden" }, "New: ") : null,
        e.is_error ? [h("strong", {}, "Refused: "), e.summary.replace(/^Refused: /, "")] : e.summary,
        e.detail && e.detail.server ? h("span", { class: "server" }, ` · ${e.detail.tool} via ${e.detail.server}`) : null))) : [h("li", {}, h("span", {}), h("span", {}), h("span", { class: "muted" }, "Nothing yet."))]));
  }
  draw();
  return h("section", { class: "section" },
    h("h2", {}, "History"),
    h("p", { class: "small muted", style: "margin: 0" }, "Everything that happened on this work order: the Agent's tool calls, your actions, the Customer's, and what the shop did on its own."),
    h("div", { class: "filters", role: "group", "aria-label": "Filter history by who acted" }, buttons),
    list);
}

export function newBadge(count, summary, actor) {
  if (!count) return null;
  return h("div", { class: "new-line" },
    h("span", { class: "badge" }, count > 1 ? `${count} new` : "New"),
    h("span", {}, `${ACTOR_LABEL[actor] || ""}: ${summary}`));
}
