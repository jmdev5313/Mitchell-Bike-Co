// The Agent chat: conversations on the left, the transcript with its activity log
// in the middle (streamed live while the Agent works), the linked work order on the right.

import { h, icon, richText } from "./dom.js";
import { staff, passcode, Unauthorized, stageMeter, ledger, draftBand, customerLink } from "./staff.js";

const PHOTO = "M2 4h12v9H2zM5.5 8a1 1 0 100-.01M14 11l-4-4-6 6";
const CLIP = "M13 7.5l-5.5 5.5a3.2 3.2 0 01-4.5-4.5l6-6a2.2 2.2 0 013 3l-6 6a1.2 1.2 0 01-1.7-1.7L10 4.5";

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

function mechanicTurn(text, photos = 0) {
  return h("div", { class: "turn" },
    h("div", { class: "speaker" }, "Mechanic"),
    h("div", { class: "content" },
      h("p", { style: "white-space: pre-line; font-size: 16px" }, text),
      photos ? h("div", { class: "attach" }, icon(PHOTO, 16, 1.6), `${photos} photo${photos === 1 ? "" : "s"}`) : null));
}

function agentTurn(entry) {
  return h("div", { class: "turn" },
    h("div", { class: "speaker" }, "Agent"),
    h("div", { class: "content" }, activityLog(entry.tools), richText(entry.text)));
}

export async function agentScreen(app, conversationId, { onUnauthorized }) {
  document.title = "Agent · Workshop · Mitchell Bike Co.";
  const conversations = await staff("/api/conversations");
  if (!conversationId && conversations.length) {
    location.replace(`#/agent/${conversations[0].id}`);
    return;
  }
  const convo = conversationId ? await staff(`/api/conversations/${conversationId}`) : null;
  const order = convo && convo.work_order_id ? await staff(`/api/work-orders/${convo.work_order_id}`) : null;
  const rerender = () => agentScreen(app, conversationId, { onUnauthorized }).catch((e) => {
    if (e instanceof Unauthorized) onUnauthorized();
  });

  async function newConversation() {
    const { conversation_id } = await staff("/api/conversations", { method: "POST" });
    location.hash = `#/agent/${conversation_id}`;
  }

  // Left: conversations
  const convos = h("aside", { class: "convos rail", "aria-label": "Conversations" },
    h("button", { type: "button", class: "btn btn-outline", style: "width: 100%; justify-content: flex-start", onclick: () => newConversation().catch(rerender) },
      "+ New conversation"),
    conversations.length
      ? h("ul", { class: "list" }, conversations.map((c) => h("li", {},
        h("a", { href: `#/agent/${c.id}`, "aria-current": c.id === conversationId ? "true" : null },
          h("span", { class: "t" }, c.preview ? truncate(c.preview, 48) : "New conversation"),
          h("span", { class: "m" }, h("span", {}, c.work_order_id ? `Work order #${c.work_order_id}` : "No work order yet"),
            h("span", {}, `${c.turns} turn${c.turns === 1 ? "" : "s"}`))))))
      : h("p", { class: "small muted" }, "No conversations yet."));

  // Middle: transcript and composer
  const transcript = h("div", { class: "transcript", "aria-live": "polite" });
  if (!convo) {
    transcript.append(h("div", { class: "turn" }, h("div", { class: "speaker" }, ""),
      h("div", { class: "content" },
        h("p", { style: "font-size: 18px" }, "Start a conversation, then describe the bike on the stand: what you see, what you measured, and whose bike it is."),
        h("p", { class: "muted" }, "The Agent looks up the bike, checks what fits, builds the quote and drafts the message to the Customer. You review and send it."))));
  } else if (!convo.entries.length) {
    transcript.append(h("div", { class: "turn", "data-hint": "" }, h("div", { class: "speaker" }, ""),
      h("div", { class: "content" }, h("p", { class: "muted" },
        "Try: “Emma Clark's gravel bike is on the stand. Gears skip under load in the smaller cogs, and my chain checker reads 0.75%. Work out what it needs and draft her a quote.”"))));
  } else {
    for (const entry of convo.entries) {
      transcript.append(entry.role === "mechanic" ? mechanicTurn(entry.text, entry.photos) : agentTurn(entry));
    }
  }

  const composer = convo ? composerForm(convo.conversation_id, transcript, rerender, onUnauthorized) : null;
  const center = h("main", { class: "center" }, transcript, composer);

  // Right: linked work order
  const side = h("aside", { class: "side rail", "aria-label": "Linked work order" },
    order ? workOrderPanel(order, rerender) : h("div", { class: "rail-section" },
      h("h2", { class: "display", style: "font-size: 24px" }, "No work order yet"),
      h("p", { class: "small muted" }, "When the Agent opens one, it appears here with its quote and the draft to the Customer.")),
    convo && Object.keys(convo.usage).length ? h("div", { class: "rail-section small muted" },
      `Tokens this conversation: ${(convo.usage.input_tokens || 0) + (convo.usage.cache_read_input_tokens || 0) + (convo.usage.cache_creation_input_tokens || 0)} in, ${convo.usage.output_tokens || 0} out · ${convo.model}`) : null);

  app.replaceChildren(h("div", { class: "chat" }, convos, center, side));
  if (composer) composer.querySelector("textarea").focus();
}

function workOrderPanel(order, rerender) {
  const customer = order.bike.customer;
  const diffs = order.bike.differs_from_catalog_model;
  return h("div", {},
    h("div", { class: "rail-section", style: "padding-bottom: 12px" },
      h("div", { style: "display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 4px 12px" },
        h("h2", { class: "display", style: "font-size: 28px" }, `Work order #${order.work_order_id}`),
        stageMeter(order.status)),
      h("div", { style: "font-weight: 500" }, customer),
      h("div", { class: "small muted" }, order.bike.model)),
    diffs.length ? h("div", { class: "mismatch", style: "margin: 0 24px" },
      h("div", { class: "label" }, "Differs from catalog"),
      diffs.map((d) => h("div", {}, `${d.kind.replace(/_/g, " ")}: `, h("s", { class: "muted" }, d.catalog_model), " → ", h("strong", {}, d.this_bike)))) : null,
    order.lines.length ? h("div", { class: "rail-section" },
      ledger(order.lines, order.quoted_total_cents ?? order.total_cents, {
        totalLabel: order.quoted_total_cents !== null ? "Total" : "Running total",
        stock: (line) => line.kind === "part" && !line.in_stock ? h("span", { class: "stock-out", style: "display: block" }, "Out of stock") : null,
      })) : null,
    draftBand(order, { onChange: rerender, customerName: customer }),
    h("div", { class: "rail-section", style: "display: flex; flex-direction: column; gap: 10px" },
      h("p", { class: "small", style: "margin: 0" }, h("strong", {}, "Next: "), order.next_step.text),
      customerLink(order.customer_link_token, customer),
      h("a", { href: `#/work-orders/${order.work_order_id}`, style: "font-weight: 600; min-height: 44px; display: inline-flex; align-items: center" }, "Open work order")));
}

function composerForm(conversationId, transcript, rerender, onUnauthorized) {
  const textarea = h("textarea", { id: "msg", class: "textarea", rows: 2, required: true,
    placeholder: "Describe what you see and measure…" });
  const files = h("input", { type: "file", accept: "image/jpeg,image/png,image/gif,image/webp", multiple: true, class: "visually-hidden", id: "photos", tabindex: "-1" });
  const fileNote = h("div", { class: "files", role: "status" });
  files.addEventListener("change", () => {
    fileNote.textContent = files.files.length ? `${files.files.length} photo${files.files.length === 1 ? "" : "s"} attached` : "";
  });
  const send = h("button", { type: "submit", class: "btn" }, "Send");

  const form = h("form", { class: "composer", onsubmit: async (event) => {
    event.preventDefault();
    const text = textarea.value.trim();
    if (!text || send.disabled) return;
    const form = new FormData();
    form.append("text", text);
    for (const file of files.files) form.append("photos", file);
    send.disabled = true;
    textarea.disabled = true;
    textarea.value = "";
    fileNote.textContent = "";
    transcript.querySelector("[data-hint]")?.remove();
    transcript.append(mechanicTurn(text, files.files.length));
    try {
      await streamTurn(conversationId, form, transcript);
      rerender();
    } catch (e) {
      if (e instanceof Unauthorized) return onUnauthorized();
      transcript.append(h("p", { class: "notice-refused", role: "alert" }, h("strong", {}, "The turn failed: "), e.message));
      send.disabled = false;
      textarea.disabled = false;
      textarea.value = text;
    }
  } },
    h("label", { class: "lbl", for: "msg" }, "Message the Agent"),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn btn-outline attach-btn", "aria-label": "Attach photos", onclick: () => files.click() }, icon(CLIP, 18, 1.4)),
      textarea, send),
    files, fileNote);
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) form.requestSubmit();
  });
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

function truncate(text, n) {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}
