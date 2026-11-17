// The Agent chat pieces: the activity log, the turns (with a card for each message the Agent
// drafts to the Customer), the composer, and streaming a turn. The job screen (job.js) lays them out.

import { h, icon, richText, dollars, shortDate } from "./dom.js";
import { passcode, Unauthorized } from "./staff.js";

const PHOTO = "M2 4h12v9H2zM5.5 8a1 1 0 100-.01M14 11l-4-4-6 6";
const CLIP = "M13 7.5l-5.5 5.5a3.2 3.2 0 01-4.5-4.5l6-6a2.2 2.2 0 013 3l-6 6a1.2 1.2 0 01-1.7-1.7L10 4.5";
const EXPAND = "M9.5 2.5h4v4M13.5 2.5L9 7M6.5 13.5h-4v-4M2.5 13.5L7 9";

/** The activity log for one Agent turn: a summary line, then one row per tool call. */
export function activityLog(tools, progress = [], { live = false } = {}) {
  const refused = tools.filter((t) => t.is_error).length;
  const rows = tools.map((t) => h("li", { class: t.is_error ? "is-refused" : null },
    h("span", { class: "tool" }, t.name, h("span", { class: "server" }, ` · ${t.server}`)),
    h("span", { class: "result" },
      t.is_error ? [h("strong", {}, "Refused: "), t.summary.replace(/^Refused: /, "")] : t.summary)));
  if (!tools.length && !live) return null;
  return h("div", {},
    h("div", { class: "activity-head" },
      `${tools.length} step${tools.length === 1 ? "" : "s"}`,
      refused ? [", ", h("span", { class: "refused" }, `${refused} refused`)] : null,
      " · tool calls to the shop's MCP servers"),
    h("ol", { class: "activity", "aria-label": "Tools the Agent used" }, rows,
      progress.length && live ? h("li", { class: "note" }, h("span", { class: "result" }, progress[progress.length - 1])) : null));
}

export function mechanicTurn(text, photos = 0) {
  return h("div", { class: "turn" },
    h("div", { class: "speaker" }, "Mechanic"),
    h("div", { class: "content" },
      h("p", { style: "white-space: pre-line; font-size: 16px" }, text),
      photos ? h("div", { class: "attach" }, icon(PHOTO, 16, 1.6), `${photos} photo${photos === 1 ? "" : "s"}`) : null));
}

export function agentTurn(entry, { order = null, onReview = null } = {}) {
  const cards = entry.tools.filter((t) => t.message_id).map((t) => draftCard(t.message_id, order, onReview));
  return h("div", { class: "turn" },
    h("div", { class: "speaker" }, "Agent"),
    h("div", { class: "content" }, activityLog(entry.tools), richText(entry.text), cards));
}

/**
 * A message the Agent drafted to the Customer, shown where it was drafted. It's a reference, not a
 * second place to send from: "Review and send" moves to the draft in the work order panel. The
 * status is read from the work order each time, so the stored conversation never changes.
 */
function draftCard(messageId, order, onReview) {
  const message = order && order.messages.find((m) => m.id === messageId);
  if (!message) return null;
  const first = order.bike.customer.split(" ")[0];
  const drafts = order.messages.filter((m) => m.status === "draft");
  const quotes = order.messages.filter((m) => m.status === "sent" && m.quoted_total_cents !== null);
  const decidedQuote = order.decided_at && quotes.length && quotes[quotes.length - 1].id === message.id;
  let state;
  let label;
  if (message.status === "draft") {
    const latest = drafts[drafts.length - 1].id === message.id;
    state = latest ? "draft" : "replaced";
    label = latest ? "Draft" : "Replaced by a newer draft";
  } else if (decidedQuote) {
    state = order.status === "declined" ? "declined" : "approved";
    label = order.status === "declined" ? `Declined by ${first}` : `Approved by ${first}`;
  } else {
    state = "sent";
    label = `Sent ${shortDate(message.sent_at)} ${clock(message.sent_at)}`;
  }
  const line = message.body.replace(/\s+/g, " ").trim();
  return h("div", { class: `draft-card is-${state}`, role: "group", "aria-label": `Message to ${first}: ${label}` },
    h("div", { class: "top" },
      h("span", { class: "to" }, `To ${first} · `, state === "replaced" ? h("s", {}, "Draft") : label,
        state === "replaced" ? ` · ${label}` : null),
      message.quoted_total_cents !== null ? h("span", { class: "amount" }, dollars(message.quoted_total_cents)) : null),
    h("p", { class: "line" }, line),
    state === "draft" ? h("div", { class: "bottom" },
      h("span", { class: "note" }, "Not sent. Only you can send it, from the work order."),
      onReview ? h("button", { type: "button", class: "linkish review", onclick: onReview }, "Review and send →") : null) : null);
}

function clock(value) {
  if (!value) return "";
  const d = new Date(value.replace(" ", "T") + (/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? "" : "Z"));
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

/** The message box. `conversationId` is an async function, so a job can start its conversation on first send. */
export function composerForm({ conversationId, transcript, rerender, onUnauthorized }) {
  const textarea = h("textarea", { id: "msg", class: "textarea", rows: 2, required: true,
    placeholder: "Describe what you see and measure…" });
  const grow = () => { textarea.style.height = "auto"; textarea.style.height = `${Math.min(textarea.scrollHeight + 2, 220)}px`; };
  textarea.addEventListener("input", grow);
  const files = h("input", { type: "file", accept: "image/jpeg,image/png,image/gif,image/webp", multiple: true, class: "visually-hidden", id: "photos", tabindex: "-1" });
  const fileNote = h("div", { class: "files", role: "status" });
  files.addEventListener("change", () => {
    fileNote.textContent = files.files.length ? `${files.files.length} photo${files.files.length === 1 ? "" : "s"} attached` : "";
  });
  const send = h("button", { type: "submit", class: "btn" }, "Send");

  async function submit(text) {
    if (!text || send.disabled) return;
    const body = new FormData();
    body.append("text", text);
    for (const file of files.files) body.append("photos", file);
    send.disabled = true;
    textarea.disabled = true;
    textarea.value = "";
    grow();
    fileNote.textContent = "";
    transcript.querySelector("[data-hint]")?.remove();
    transcript.append(mechanicTurn(text, files.files.length));
    window.mbcStreaming = true;
    try {
      await streamTurn(await conversationId(), body, transcript);
      window.mbcStreaming = false;
      rerender();
    } catch (e) {
      window.mbcStreaming = false;
      if (e instanceof Unauthorized) return onUnauthorized();
      transcript.append(h("p", { class: "notice-refused", role: "alert" }, h("strong", {}, "The turn failed: "), e.message));
      send.disabled = false;
      textarea.disabled = false;
      textarea.value = text;
      grow();
    }
  }

  // The large editor, for long write-ups: a native dialog over the page.
  const big = h("textarea", { class: "textarea", id: "msg-big", "aria-label": "Message the Agent (large editor)" });
  const dialog = h("dialog", { class: "expand-dialog", "aria-labelledby": "expand-title" },
    h("form", { method: "dialog", onsubmit: (event) => {
      event.preventDefault();
      const text = big.value.trim();
      dialog.close();
      submit(text);
    } },
      h("h2", { id: "expand-title", class: "display", style: "font-size: 28px" }, "Message the Agent"),
      big,
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn btn-outline", onclick: () => { textarea.value = big.value; grow(); dialog.close(); textarea.focus(); } }, "Back to the small box"),
        h("button", { type: "submit", class: "btn" }, "Send"))));

  const form = h("form", { class: "composer", onsubmit: (event) => { event.preventDefault(); submit(textarea.value.trim()); } },
    h("label", { class: "lbl", for: "msg" }, "Message the Agent"),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn btn-outline attach-btn", "aria-label": "Attach photos", onclick: () => files.click() }, icon(CLIP, 18, 1.4)),
      textarea,
      h("button", { type: "button", class: "btn btn-outline attach-btn", "aria-label": "Open a larger editor", title: "Larger editor",
        onclick: () => { big.value = textarea.value; dialog.showModal(); big.focus(); } }, icon(EXPAND, 16, 1.6)),
      send),
    files, fileNote, dialog);
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) form.requestSubmit();
  });
  big.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) dialog.querySelector("form").requestSubmit();
  });
  form.api = {
    setText(text) { textarea.value = text; grow(); textarea.focus(); textarea.setSelectionRange(text.length, text.length); },
    send(text) { submit(text); },
  };
  return form;
}

/** POST the message and render the turn's events as they stream in (Server-Sent Events). */
async function streamTurn(conversationId, form, transcript) {
  const tools = [];
  const progress = [];
  const logSlot = h("div");
  const working = h("div", { class: "working" }, h("span", { class: "pulse", "aria-hidden": "true" }), "The Agent is working…");
  const content = h("div", { class: "content" }, logSlot, working);
  transcript.append(h("div", { class: "turn" }, h("div", { class: "speaker" }, "Agent"), content));
  const redraw = () => logSlot.replaceChildren(activityLog(tools, progress, { live: true }) || "");
  content.scrollIntoView({ block: "end", behavior: "smooth" });

  const response = await fetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST", headers: { Authorization: `Bearer ${passcode()}` }, body: form,
  });
  if (response.status === 401) throw new Unauthorized("staff passcode required");
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { detail = (await response.json()).detail || detail; } catch { /* not JSON */ }
    throw new Error(detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const kind = (chunk.match(/^event: (.*)$/m) || [])[1];
      const data = JSON.parse((chunk.match(/^data: (.*)$/m) || [, "{}"])[1]);
      if (kind === "tool_call") { tools.push(data); redraw(); }
      else if (kind === "progress") { progress.push(data.text); redraw(); }
      else if (kind === "reply") { working.remove(); content.append(...richText(data.text)); }
      else if (kind === "error") throw new Error(data.detail);
    }
  }
}
