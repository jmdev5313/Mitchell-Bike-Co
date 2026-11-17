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

  return h("div", { class: "draft-band" },
    h("div", { class: "head" },
      h("label", { class: "title", for: id }, `Draft to ${first}`),
      h("span", { class: "meta" },
        draft.quoted_total_cents !== null ? `Carries the ${dollars(draft.quoted_total_cents)} quote · ` : "",
        `Drafted by the ${draft.author === "agent" ? "Agent" : "Mechanic"}, ${shortDate(draft.created_at)}`)),
    textarea,
    h("p", { class: "who-sends", style: "margin: 0" },
      "The Agent can't send messages. Only you can, after reviewing it."),
    h("div", { class: "actions" },
      h("button", { type: "button", class: "btn btn-send",
        onclick: () => run("Sending…", async () => { await save(); await staff(`/api/messages/${draft.id}/send`, { method: "POST" }); }) },
        `Send to ${first}`),
      h("button", { type: "button", class: "btn btn-outline",
        onclick: () => run("Saving…", save) }, "Save edits")),
    status);
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
