// The Mechanic's workspace: /workshop#/work-orders, #/work-orders/{id}, #/agent, #/agent/{id}.

import { h, dollars, shortDate, longDate } from "./dom.js";
import {
  staff, passcode, setPasscode, Unauthorized, stageMeter, progressStrip, ledger, draftBand,
  customerLink, refusedNotice, nextStepBar, historySection, newBadge,
} from "./staff.js";
import { agentScreen } from "./agent.js";

const app = document.getElementById("app");
const nav = document.getElementById("nav");

// --- Routing -----------------------------------------------------------------

function route() {
  const [section = "work-orders", id] = location.hash.replace(/^#\/?/, "").split("/");
  for (const link of nav.querySelectorAll("a")) {
    link.toggleAttribute("aria-current", link.dataset.section === section);
    if (link.dataset.section === section) link.setAttribute("aria-current", "page");
  }
  if (!passcode()) return Promise.resolve(gate());
  const screens = {
    "work-orders": () => (id ? workOrder(Number(id)) : workOrders()),
    agent: () => agentScreen(app, id, { onUnauthorized: signOut }),
  };
  return (screens[section] || screens["work-orders"])().catch(handle);
}

function handle(e) {
  if (e instanceof Unauthorized) return signOut();
  app.replaceChildren(h("div", { class: "page" },
    h("h1", { class: "display" }, "Something went wrong"),
    h("p", { class: "notice-refused", role: "alert" }, h("strong", {}, "Couldn't load this page: "), e.message),
    h("button", { type: "button", class: "btn btn-outline", style: "margin-top: 16px", onclick: route }, "Try again")));
}

function signOut() {
  setPasscode("");
  gate("That passcode didn't work. Try again.");
}

window.addEventListener("hashchange", route);

// --- Live updates: poll for new history events, refresh the screen when something happened ---

let latestEvent = null;
function userIsBusy() {
  const el = document.activeElement;
  const typing = el && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && el.type !== "button")) && el.value;
  return Boolean(typing || window.mbcStreaming || document.querySelector("dialog[open]"));
}
async function poll() {
  if (!passcode() || document.hidden) return;
  try {
    const { latest_event_id, needs_you } = await staff("/api/activity/latest");
    const link = nav.querySelector('[data-section="work-orders"]');
    link.querySelector(".badge")?.remove();
    if (needs_you) link.append(h("span", { class: "badge", "aria-label": `${needs_you} need you` }, String(needs_you)));
    if (latestEvent !== null && latest_event_id !== latestEvent && !userIsBusy()) {
      const y = window.scrollY;  // refresh in place: keep the reader where they were
      await route();
      window.scrollTo(0, y);
    }
    latestEvent = latest_event_id;
  } catch { /* offline or signed out: the next screen load will say so */ }
}
setInterval(poll, 4000);
poll();

// --- Passcode gate -----------------------------------------------------------

function gate(message = "") {
  document.title = "Sign in · Workshop · Mitchell Bike Co.";
  const input = h("input", { id: "passcode", class: "input", type: "password", autocomplete: "current-password", required: true });
  app.replaceChildren(h("div", { class: "gate" },
    h("h1", { class: "display" }, "Workshop"),
    h("p", { class: "muted", style: "margin: 4px 0 0" }, "Staff only. Enter the shop's passcode (STAFF_PASSCODE in .env)."),
    h("form", { onsubmit: async (event) => {
      event.preventDefault();
      setPasscode(input.value);
      try {
        await staff("/api/work-orders");
        route();
      } catch (e) {
        if (e instanceof Unauthorized) return signOut();
        handle(e);
      }
    } },
      h("label", { for: "passcode" }, "Passcode"),
      h("div", { class: "row" }, input, h("button", { type: "submit", class: "btn" }, "Sign in"))),
    message ? h("p", { class: "notice-refused", role: "alert", style: "margin-top: 12px" }, message) : null));
  input.focus();
}

// --- Work order list ---------------------------------------------------------

const FILTERS = [
  { id: "all", label: "All", test: () => true },
  { id: "mechanic", label: "Needs you", test: (o) => o.next_step.waiting_on === "mechanic" },
  { id: "agent", label: "With the Agent", test: (o) => o.next_step.waiting_on === "agent" },
  { id: "customer", label: "Waiting on Customer", test: (o) => o.next_step.waiting_on === "customer" },
  { id: "closed", label: "Closed", test: (o) => o.next_step.waiting_on === "nobody" },
];
let filter = "all";

async function workOrders() {
  document.title = "Work orders · Workshop · Mitchell Bike Co.";
  const orders = await staff("/api/work-orders");
  const render = () => {
    const shown = orders.filter(FILTERS.find((f) => f.id === filter).test);
    app.replaceChildren(h("div", { class: "page" },
      h("div", { style: "display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px" },
        h("h1", { class: "display" }, "Work orders"),
        h("a", { class: "btn", href: "#/agent" }, "Start with the Agent")),
      h("div", { class: "filters", role: "group", "aria-label": "Filter by who it's waiting on" },
        FILTERS.map((f) => h("button", {
          type: "button", "aria-pressed": String(f.id === filter),
          onclick: () => { filter = f.id; render(); },
        }, `${f.label} · ${orders.filter(f.test).length}`))),
      orders.length === 0
        ? h("p", { class: "empty" }, "No work orders yet. Describe a bike on the stand to the Agent and it will open one.")
        : h("div", { class: "table-box" },
          h("table", { class: "data" },
            h("caption", { class: "visually-hidden" }, "Work orders"),
            h("thead", {}, h("tr", {},
              h("th", { scope: "col" }, "#"), h("th", { scope: "col" }, "Customer · bike"),
              h("th", { scope: "col" }, "Complaint"), h("th", { scope: "col" }, "Stage"),
              h("th", { scope: "col" }, "Next step"), h("th", { scope: "col", class: "money" }, "Total"))),
            h("tbody", {}, shown.map((o) => h("tr", {
              class: "clickable",
              onclick: (event) => { if (!event.target.closest("a")) location.hash = `#/work-orders/${o.id}`; },
            },
              h("td", {}, h("a", { href: `#/work-orders/${o.id}` }, String(o.id))),
              h("td", {}, h("div", { style: "font-weight: 600" }, o.customer), h("div", { class: "small muted" }, o.bike),
                newBadge(o.unseen_count, o.unseen_latest, o.unseen_actor)),
              h("td", {}, o.complaint),
              h("td", {}, stageMeter(o.status)),
              h("td", { class: o.next_step.waiting_on === "mechanic" ? "next-mechanic" : "muted" }, o.next_step.text),
              h("td", { class: "money" }, dollars(o.quoted_total_cents ?? o.total_cents)))))))));
  };
  render();
}

// --- Work order detail -------------------------------------------------------

async function workOrder(id) {
  const order = await staff(`/api/work-orders/${id}`);
  const customer = order.bike.customer;
  document.title = `Work order #${id} · Workshop · Mitchell Bike Co.`;
  const reload = () => {
    const y = window.scrollY;
    return workOrder(id).then(() => window.scrollTo(0, y)).catch(handle);
  };
  const notice = h("div", { role: "alert" });

  async function act(work) {
    notice.replaceChildren();
    try { await work(); reload(); }
    catch (e) {
      if (e instanceof Unauthorized) return signOut();
      notice.replaceChildren(refusedNotice(e.message));
    }
  }

  const ordered = new Map();
  for (const po of order.purchase_orders) {
    for (const line of po.lines) ordered.set(line.sku, po);
  }
  const stock = (line) => {
    if (line.kind !== "part") return null;
    const po = ordered.get(line.sku);
    if (po) {
      return h("span", { class: po.status === "received" ? "stock-in" : "stock-out", style: "display: block" },
        po.status === "received" ? `Arrived from ${po.supplier}` : `Ordered from ${po.supplier}, ${po.lead_time_days} days`);
    }
    return line.in_stock
      ? h("span", { class: "stock-in", style: "display: block" }, "In stock")
      : h("span", { class: "stock-out", style: "display: block" }, "Out of stock");
  };

  const thread = order.messages.filter((m) => m.status !== "draft");
  const differs = new Set(order.bike.differs_from_catalog_model.map((d) => d.kind));
  const catalog = Object.fromEntries(order.bike.differs_from_catalog_model.map((d) => [d.kind, d.catalog_model]));

  const s = order.status;
  const today = new Date().toISOString().slice(0, 10);
  const dateInput = h("input", { id: "repair-date", class: "input", type: "date", value: order.scheduled_for || today,
    disabled: !["approved", "awaiting_parts"].includes(s) });

  app.replaceChildren(h("div", { class: "page" },
    h("a", { class: "crumb", href: "#/work-orders" }, "← Work orders"),
    h("div", { style: "display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 16px; margin-top: 6px" },
      h("div", {},
        h("h1", { class: "display" }, `Work order #${id} · ${customer}`),
        h("p", { class: "subhead" }, `${order.bike.model} “${order.bike.nickname}” · “${order.complaint}”`)),
      order.conversation_ids.length
        ? h("a", { href: `#/agent/${order.conversation_ids[0]}`, style: "font-weight: 600" }, "Open the Agent conversation")
        : null),
    progressStrip(s),
    nextStepBar(order, { onChange: reload }),
    notice,
    h("div", { class: "cols", style: "margin-top: 8px" },
      h("div", { class: "main-col" },
        h("section", { class: "section" },
          h("h2", {}, `Messages with ${customer.split(" ")[0]}`),
          draftBand(order, { onChange: reload, customerName: customer }),
          thread.length
            ? h("ol", { class: "mthread" }, thread.map((m) => h("li", {},
              h("div", { class: "who" },
                m.direction === "to_customer" ? `Shop → ${customer.split(" ")[0]}` : customer.split(" ")[0],
                h("div", { class: "when", style: "font-weight: 400" }, shortDate(m.sent_at))),
              h("p", { class: "body" }, m.body,
                m.quoted_total_cents !== null ? h("span", { class: "small muted", style: "display: block; margin-top: 4px" }, `Carried the ${dollars(m.quoted_total_cents)} quote`) : null))))
            : h("p", { class: "muted small" }, "Nothing sent yet.")),
        order.diagnosis ? h("section", { class: "section" }, h("h2", {}, "Diagnosis"), h("p", { style: "margin: 0; white-space: pre-line" }, order.diagnosis)) : null,
        order.lines.length ? h("section", { class: "section" },
          h("h2", {}, order.quoted_total_cents !== null ? "Quote (locked)" : "Quote (draft)"),
          ledger(order.lines, order.quoted_total_cents ?? order.total_cents, { stock })) : null,
        order.order_plan.lines.length ? h("section", { class: "section" },
          h("h2", {}, "Order plan"),
          h("p", { class: "small muted", style: "margin: 0 0 8px" },
            "Chosen by the Agent with the quote. The shop places it the moment the Customer approves."),
          h("ul", { style: "margin: 0; padding-left: 18px" }, order.order_plan.lines.map((l) =>
            h("li", {}, `${l.sku} × ${l.qty} from ${l.supplier}, ${l.lead_time_days}-day lead time, ${dollars(l.total_cents)}`))),
          order.order_plan.promised_ready_on ? h("p", { class: "small", style: "margin: 8px 0 0" },
            h("strong", {}, "Promised to the Customer: "), longDate(order.order_plan.promised_ready_on)) : null) : null,
        historySection(order)),
      h("div", { class: "side-col" },
        h("section", { class: "section" },
          h("h2", {}, "Bike"),
          differs.size ? h("div", { class: "mismatch", style: "margin-bottom: 12px" },
            h("div", { class: "label" }, "Differs from its catalog model"),
            "Fit is checked against this bike, not the catalog.") : null,
          h("table", { class: "compare" },
            h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Standard"), h("th", { scope: "col" }, "This bike"), h("th", { scope: "col" }, "Catalog model"))),
            h("tbody", {}, Object.entries(order.bike.standards).map(([kind, name]) =>
              h("tr", { class: differs.has(kind) ? "differs" : null },
                h("th", { scope: "row", style: "font-weight: 400" }, kind.replace(/_/g, " ")),
                h("td", { class: "this" }, name),
                h("td", {}, differs.has(kind) ? h("s", {}, catalog[kind]) : "same"))))),
          order.bike.service_history.length ? h("div", { style: "margin-top: 16px" },
            h("h3", { style: "font-size: 15px; margin: 0 0 6px" }, "Service history"),
            h("ol", { class: "small", style: "margin: 0; padding-left: 18px; line-height: 1.6" },
              order.bike.service_history.slice().reverse().map((r) =>
                h("li", {}, `${shortDate(r.date)} ${r.date.slice(0, 4)} · ${r.odometer_km?.toLocaleString("en-US") ?? "?"} km · ${r.summary}`)))) : null),
        h("section", { class: "section" },
          h("h2", {}, "Parts and repair"),
          order.purchase_orders.length ? h("table", { class: "compare", style: "margin-bottom: 12px" },
            h("tbody", {}, order.purchase_orders.map((po) => h("tr", {},
              h("td", {}, `${po.lines.map((l) => l.sku).join(", ")} from ${po.supplier}`,
                h("div", { class: "small muted" }, `${dollars(po.total_cents)} · ${po.status === "received" ? `arrived ${shortDate(po.received_at)}` : `ordered ${shortDate(po.created_at)}, ${po.lead_time_days}-day lead time`}`)),
              h("td", { style: "text-align: right" }, po.status === "ordered"
                ? h("button", { type: "button", class: "btn btn-outline", onclick: () => act(() => staff(`/api/purchase-orders/${po.id}/receive`, { method: "POST" })) }, "Mark received")
                : null)))))
            : h("p", { class: "small muted", style: "margin: 0 0 12px" }, ["approved", "awaiting_parts"].includes(s) ? "No parts ordered. The Agent orders what's out of stock after approval." : "Parts are ordered after the Customer approves."),
          h("div", { class: "repair-steps" },
            h("label", { for: "repair-date", class: "small", style: "font-weight: 600" }, "Repair date"),
            h("div", { class: "row" }, dateInput,
              h("button", { type: "button", class: "btn btn-outline", disabled: !["approved", "awaiting_parts"].includes(s),
                onclick: () => act(() => staff(`/api/work-orders/${id}/schedule`, { method: "POST", body: { scheduled_for: dateInput.value } })) },
                order.scheduled_for ? `Booked ${longDate(order.scheduled_for)}` : "Schedule")),
            h("button", { type: "button", class: "btn btn-outline", disabled: s !== "scheduled",
              onclick: () => act(() => staff(`/api/work-orders/${id}/start`, { method: "POST" })) }, "Start repair"),
            h("button", { type: "button", class: "btn btn-outline", disabled: s !== "in_progress",
              onclick: () => act(() => staff(`/api/work-orders/${id}/finish`, { method: "POST" })) }, "Finish repair"))),
        h("section", { class: "section" },
          h("h2", {}, "Customer link"),
          customerLink(order.customer_link_token, customer))))));
  if (order.unseen.length) staff(`/api/work-orders/${id}/seen`, { method: "POST" }).catch(() => {});
}

route();
