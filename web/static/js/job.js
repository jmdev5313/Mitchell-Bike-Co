// One screen per job: the conversation with the Agent on the left, the work order on the right
// (Overview, Bike, History). The panel collapses to a strip; at narrow widths the two become a switch.

import { h, dollars, shortDate, longDate } from "./dom.js";
import {
  staff, Unauthorized, stageMeter, ledger, draftBand, customerLink, nextStepBar, historySection,
  takePrefill, HERO, startWithAgent,
} from "./staff.js";
import { mechanicTurn, agentTurn, composerForm } from "./agent.js";

const TABS = [
  { id: "overview", label: () => "Overview" },
  { id: "bike", label: () => "Bike" },
  { id: "history", label: (order) => `History · ${order.history.length}` },
];

// Kept across re-renders (the workshop refreshes in place when something happens).
const ui = { orderId: undefined, tab: "overview", view: "chat" };

function isCollapsed() {
  try { return localStorage.getItem("mbc-panel") === "collapsed"; } catch { return false; }
}
function setCollapsed(value) {
  try { value ? localStorage.setItem("mbc-panel", "collapsed") : localStorage.removeItem("mbc-panel"); } catch { /* private mode */ }
}

export async function jobScreen(app, { orderId = null, conversationId = null, onUnauthorized }) {
  const order = orderId ? await staff(`/api/work-orders/${orderId}`) : null;
  if (!conversationId && order && order.conversation_ids.length) {
    // Open the newest conversation that has something in it, not an empty one started by mistake.
    const used = order.conversation_ids.length > 1
      ? (await staff("/api/conversations")).filter((c) => c.work_order_id === order.work_order_id && c.turns > 0)
      : [];
    conversationId = used.length ? used[0].id : order.conversation_ids[0];
  }
  const convo = conversationId ? await staff(`/api/conversations/${conversationId}`) : null;
  if (!order && convo && convo.work_order_id) {
    // The Agent opened a work order in this conversation: it's a job now.
    location.replace(`#/work-orders/${convo.work_order_id}/${convo.conversation_id}`);
    return;
  }

  const id = order ? order.work_order_id : null;
  if (ui.orderId !== id) Object.assign(ui, { orderId: id, tab: "overview", view: "chat" });
  const customer = order ? order.bike.customer : "";
  const first = customer.split(" ")[0];
  document.title = `${order ? `Work order #${id}` : "New job"} · Workshop · Mitchell Bike Co.`;

  let currentConvo = convo ? convo.conversation_id : null;
  const rerender = () => jobScreen(app, { orderId: id, conversationId: currentConvo, onUnauthorized }).catch((e) => {
    if (e instanceof Unauthorized) onUnauthorized();
  });

  // Keep the reader's place when this screen redraws itself.
  const old = app.querySelector(".job");
  const same = old && old.dataset.order === String(id) && old.dataset.convo === String(currentConvo);
  const keep = same ? { chat: old.querySelector(".transcript").scrollTop, panel: old.querySelector(".job-panel").scrollTop } : null;

  // --- The conversation ---
  const prefill = takePrefill();
  const transcript = h("div", { class: "transcript", "aria-live": "polite" });
  const entries = convo ? convo.entries : [];
  if (entries.length) {
    for (const entry of entries) {
      transcript.append(entry.role === "mechanic" ? mechanicTurn(entry.text, entry.photos) : agentTurn(entry, { order, onReview: reveal }));
    }
  } else {
    transcript.append(emptyHint({ order, prefill, setText: (text) => composer.api.setText(text) }));
  }

  const composer = composerForm({
    transcript,
    rerender,
    onUnauthorized,
    // A job with no conversation yet starts one when the Mechanic first sends.
    conversationId: async () => {
      if (!currentConvo) {
        const { conversation_id } = await staff("/api/conversations", { method: "POST", body: id ? { work_order_id: id } : {} });
        currentConvo = conversation_id;
        history.replaceState(null, "", id ? `#/work-orders/${id}/${conversation_id}` : `#/agent/${conversation_id}`);
      }
      return currentConvo;
    },
  });

  const chatHead = h("div", { class: "job-chat-head" },
    h("span", {}, "Conversation with the Agent"),
    order && order.conversation_ids.length > 1 ? h("span", { class: "convo-pick" },
      order.conversation_ids.slice().reverse().map((cid, i) => h("a", {
        href: `#/work-orders/${id}/${cid}`, "aria-current": cid === currentConvo ? "true" : null,
        "aria-label": `Conversation ${i + 1}`,
      }, String(i + 1)))) : null,
    h("button", { type: "button", class: "linkish", onclick: () => newConversation().catch(rerender) }, "+ New conversation"));

  async function newConversation() {
    if (!id) return startWithAgent();
    const { conversation_id } = await staff("/api/conversations", { method: "POST", body: { work_order_id: id } });
    location.hash = `#/work-orders/${id}/${conversation_id}`;
  }

  const chat = h("main", { class: "job-chat", id: "job-chat" }, chatHead, transcript, composer);

  // --- The work order panel ---
  const panel = h("aside", { class: "job-panel rail", id: "job-panel", "aria-label": order ? `Work order #${id}` : "Work order" });

  function drawPanel() {
    if (!order) {
      panel.replaceChildren(h("div", { class: "rail-section" },
        h("h2", { class: "display", style: "font-size: 24px" }, "No work order yet"),
        h("p", { class: "small muted", style: "margin: 0" },
          "When the Agent opens one, this becomes the job's screen: the quote, the draft to the Customer and the next step appear here, beside the conversation.")));
      return;
    }
    const tabs = TABS.map((t) => h("button", {
      type: "button", role: "tab", id: `tab-${t.id}`, "aria-controls": "tabpanel",
      "aria-selected": String(ui.tab === t.id), tabindex: ui.tab === t.id ? "0" : "-1",
      onclick: () => { ui.tab = t.id; drawPanel(); panel.querySelector(`#tab-${t.id}`).focus(); },
    }, t.label(order)));
    const tablist = h("div", { class: "tabs", role: "tablist", "aria-label": "Work order" }, tabs);
    tablist.addEventListener("keydown", (event) => {
      const i = TABS.findIndex((t) => t.id === ui.tab);
      const next = event.key === "ArrowRight" ? i + 1 : event.key === "ArrowLeft" ? i - 1 : null;
      if (next === null) return;
      event.preventDefault();
      ui.tab = TABS[(next + TABS.length) % TABS.length].id;
      drawPanel();
      panel.querySelector(`#tab-${ui.tab}`).focus();
    });
    const body = ui.tab === "bike" ? bikeTab(order) : ui.tab === "history" ? h("div", { class: "rail-section" }, historySection(order)) : overviewTab();
    panel.replaceChildren(tablist, h("div", { id: "tabpanel", role: "tabpanel", "aria-labelledby": `tab-${ui.tab}` }, body));
  }

  function overviewTab() {
    const diffs = order.bike.differs_from_catalog_model;
    const ordered = new Map();
    for (const po of order.purchase_orders) for (const line of po.lines) ordered.set(line.sku, po);
    const stock = (line) => {
      if (line.kind !== "part") return null;
      const po = ordered.get(line.sku);
      const planned = order.order_plan.lines.find((l) => l.sku === line.sku);
      if (po) {
        return h("span", { class: po.status === "received" ? "stock-in" : "stock-out", style: "display: block" },
          po.status === "received" ? `Arrived from ${po.supplier}` : `Ordered from ${po.supplier}, ${po.lead_time_days} days`);
      }
      if (line.in_stock) return h("span", { class: "stock-in", style: "display: block" }, "In stock");
      return h("span", { class: "stock-out", style: "display: block" },
        planned ? `Out of stock · planned from ${planned.supplier}, ${planned.lead_time_days} days` : "Out of stock");
    };
    const thread = order.messages.filter((m) => m.status !== "draft");
    return [
      nextStepBar(order, {
        onChange: rerender,
        onReviewDraft: reveal,
        // "Repair done" goes straight to the Agent for the "ready to pick up" message.
        onFinished: () => composer.api.send(
          `The repair on work order #${id} is done. Draft ${first} a short message that the bike is ready to pick up and can be paid for from the link.`),
        onAskAgent: (prompt) => { showView("chat"); composer.api.setText(prompt); },
      }),
      diffs.length ? h("div", { class: "mismatch", style: "margin: 16px 24px 0" },
        h("div", { class: "label" }, "Differs from catalog"),
        diffs.map((d) => h("div", {}, `${d.kind.replace(/_/g, " ")}: `, h("s", { class: "muted" }, d.catalog_model), " → ", h("strong", {}, d.this_bike)))) : null,
      order.lines.length ? h("div", { class: "rail-section" },
        h("h2", {}, order.quoted_total_cents !== null ? "Quote" : "Quote (draft)"),
        ledger(order.lines, order.quoted_total_cents ?? order.total_cents, {
          totalLabel: order.quoted_total_cents !== null ? "Total" : "Running total", stock,
        }),
        order.order_plan.promised_ready_on ? h("p", { class: "small", style: "margin: 10px 0 0" },
          h("strong", {}, "Promised to the Customer: "), longDate(order.order_plan.promised_ready_on)) : null) : null,
      draftBand(order, { onChange: rerender, customerName: customer }),
      h("div", { class: "rail-section" },
        h("h2", {}, `Messages with ${first}`),
        thread.length ? h("ol", { class: "mthread" }, thread.map((m) => h("li", {},
          h("div", { class: "who" },
            m.direction === "to_customer" ? `Shop → ${first}` : first,
            h("div", { class: "when", style: "font-weight: 400" }, shortDate(m.sent_at))),
          h("p", { class: "body" }, m.body,
            m.quoted_total_cents !== null ? h("span", { class: "small muted", style: "display: block; margin-top: 4px" }, `Carried the ${dollars(m.quoted_total_cents)} quote`) : null))))
          : h("p", { class: "small muted", style: "margin: 0" }, "Nothing sent yet."),
        h("div", { style: "margin-top: 14px" }, customerLink(order.customer_link_token, customer))),
    ];
  }

  // "Review and send" in the chat, and "Review the draft" in the next step: show the draft and put focus on it.
  function reveal() {
    if (root.classList.contains("is-collapsed")) toggle();
    ui.tab = "overview";
    drawPanel();
    showView("order");
    const band = panel.querySelector(".draft-band");
    if (!band) return;
    band.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    band.focus({ preventScroll: true });
    band.classList.add("is-flagged");
    setTimeout(() => band.classList.remove("is-flagged"), 2600);
  }

  // --- Layout: collapse, and the narrow-width switch ---
  const toggleButton = h("button", { type: "button", class: "btn btn-outline panel-toggle", "aria-controls": "job-panel", onclick: () => toggle() });
  const strip = h("button", { type: "button", class: "panel-strip", "aria-controls": "job-panel", onclick: () => toggle() },
    h("span", {}, order ? `Work order #${id}` : "Work order"));
  function toggle() {
    const collapsed = !root.classList.contains("is-collapsed");
    root.classList.toggle("is-collapsed", collapsed);
    setCollapsed(collapsed);
    drawToggle();
  }
  function drawToggle() {
    const collapsed = root.classList.contains("is-collapsed");
    toggleButton.textContent = collapsed ? "Show work order" : "Hide work order";
    toggleButton.setAttribute("aria-expanded", String(!collapsed));
    strip.setAttribute("aria-expanded", String(!collapsed));
  }

  const switches = [["chat", "Agent"], ["order", order ? `Work order #${id}` : "Work order"]].map(([view, label]) =>
    h("button", { type: "button", "aria-pressed": String(ui.view === view), onclick: () => showView(view) }, label));
  function showView(view) {
    ui.view = view;
    root.dataset.view = view;
    switches.forEach((b, i) => b.setAttribute("aria-pressed", String(["chat", "order"][i] === view)));
  }

  const head = h("div", { class: "job-head" },
    h("div", { class: "job-title" },
      h("a", { class: "crumb", href: "#/work-orders" }, "← Work orders"),
      h("h1", { class: "display" }, order ? `Work order #${id} · ${customer}` : "New job"),
      h("span", { class: "subhead" }, order
        ? `${order.bike.model} “${order.bike.nickname}”`
        : "Describe the bike on the stand. When the Agent opens a work order, it appears beside the conversation.")),
    h("div", { class: "job-tools" }, order ? stageMeter(order.status) : null, toggleButton));

  const root = h("div", { class: "job", "data-order": String(id), "data-convo": String(currentConvo), "data-view": ui.view },
    head,
    h("div", { class: "job-switch filters", role: "group", "aria-label": "Show" }, switches),
    h("div", { class: "job-body" }, chat, strip, panel));
  root.classList.toggle("is-collapsed", isCollapsed());
  drawToggle();
  drawPanel();

  app.replaceChildren(root);
  document.documentElement.style.setProperty("--topbar-h", `${document.querySelector(".topbar").offsetHeight}px`);
  if (keep) {
    transcript.scrollTop = keep.chat;
    panel.scrollTop = keep.panel;
  } else {
    transcript.scrollTop = transcript.scrollHeight;
  }
  if (prefill) composer.api.setText(prefill);
  else if (!entries.length && order) composer.api.setText(`About work order #${id} for ${customer}: `);
  if (order && order.unseen.length) staff(`/api/work-orders/${id}/seen`, { method: "POST" }).catch(() => {});
}

function emptyHint({ order, prefill, setText }) {
  const turn = (...content) => h("div", { class: "turn", "data-hint": "" }, h("div", { class: "speaker" }, ""), h("div", { class: "content" }, ...content));
  if (prefill === HERO) {
    return turn(
      h("p", { style: "font-size: 18px" }, "The hero story is waiting in the box below. Press Send and watch the Agent work, tool call by tool call."),
      h("p", { class: "muted" }, "Edit it first if you like: describe what you see, what you measured, and whose bike it is."));
  }
  if (order) {
    return turn(
      h("p", { style: "font-size: 18px" }, `No conversation about work order #${order.work_order_id} yet.`),
      h("p", { class: "muted" }, "Ask the Agent anything about this job. It reads the work order, the bike and the messages before it acts."));
  }
  const copied = h("span", { class: "small muted", role: "status" });
  return turn(
    h("p", { class: "muted", style: "margin-bottom: 4px" }, "Try the hero story:"),
    h("p", {}, `“${HERO}”`),
    h("div", { class: "hint-actions" },
      h("button", { type: "button", class: "btn", onclick: () => setText(HERO) }, "Use this message"),
      h("button", { type: "button", class: "btn btn-outline", onclick: async () => {
        try { await navigator.clipboard.writeText(HERO); copied.textContent = "Copied"; } catch { copied.textContent = "Select the text above to copy it"; }
      } }, "Copy"),
      copied));
}

function bikeTab(order) {
  const differs = new Set(order.bike.differs_from_catalog_model.map((d) => d.kind));
  const catalog = Object.fromEntries(order.bike.differs_from_catalog_model.map((d) => [d.kind, d.catalog_model]));
  return h("div", {},
    h("div", { class: "rail-section" },
      h("h2", {}, `${order.bike.model} “${order.bike.nickname}”`),
      differs.size ? h("div", { class: "mismatch", style: "margin-bottom: 12px" },
        h("div", { class: "label" }, "Differs from its catalog model"),
        "Fit is checked against this bike, not the catalog.") : null,
      h("table", { class: "compare" },
        h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Standard"), h("th", { scope: "col" }, "This bike"), h("th", { scope: "col" }, "Catalog model"))),
        h("tbody", {}, Object.entries(order.bike.standards).map(([kind, name]) =>
          h("tr", { class: differs.has(kind) ? "differs" : null },
            h("th", { scope: "row", style: "font-weight: 400" }, kind.replace(/_/g, " ")),
            h("td", { class: "this" }, name),
            h("td", {}, differs.has(kind) ? h("s", {}, catalog[kind]) : "same")))))),
    order.diagnosis ? h("div", { class: "rail-section" },
      h("h2", {}, "Diagnosis"), h("p", { style: "margin: 0; white-space: pre-line" }, order.diagnosis)) : null,
    order.bike.service_history.length ? h("div", { class: "rail-section" },
      h("h2", {}, "Service history"),
      h("ol", { class: "small", style: "margin: 0; padding-left: 18px; line-height: 1.6" },
        order.bike.service_history.slice().reverse().map((r) =>
          h("li", {}, `${shortDate(r.date)} ${r.date.slice(0, 4)} · ${r.odometer_km?.toLocaleString("en-US") ?? "?"} km · ${r.summary}`)))) : null);
}
