// The Mechanic's workspace: /workshop#/work-orders, the job screen at #/work-orders/{id}[/{conversation}],
// a job not yet on a work order at #/agent/{conversation}, and #/audit.

import { h, dollars } from "./dom.js";
import { staff, passcode, setPasscode, Unauthorized, stageMeter, newBadge, startWithAgent } from "./staff.js";
import { jobScreen } from "./job.js";

const app = document.getElementById("app");
const nav = document.getElementById("nav");

// --- Routing -----------------------------------------------------------------

function route() {
  const [section = "work-orders", id, conversationId] = location.hash.replace(/^#\/?/, "").split("/");
  for (const link of nav.querySelectorAll("a")) {
    link.toggleAttribute("aria-current", link.dataset.section === section);
    if (link.dataset.section === section) link.setAttribute("aria-current", "page");
  }
  if (!passcode()) return Promise.resolve(gate());
  const screens = {
    "work-orders": () => (id ? jobScreen(app, { orderId: Number(id), conversationId, onUnauthorized: signOut }) : workOrders()),
    agent: () => (id ? jobScreen(app, { conversationId: id, onUnauthorized: signOut }) : agentStart()),
    audit: () => auditLog(),
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
  const [orders, conversations] = await Promise.all([staff("/api/work-orders"), staff("/api/conversations")]);
  const loose = conversations.filter((c) => !c.work_order_id && c.turns > 0);
  const render = () => {
    const shown = orders.filter(FILTERS.find((f) => f.id === filter).test);
    app.replaceChildren(h("div", { class: "page" },
      h("div", { style: "display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px" },
        h("h1", { class: "display" }, "Work orders"),
        h("button", { type: "button", class: "btn", onclick: () => startWithAgent().catch(handle) }, "Start with the Agent")),
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
              h("td", { class: "money" }, dollars(o.quoted_total_cents ?? o.total_cents))))))),
      loose.length ? h("section", { class: "section" },
        h("h2", {}, "Conversations not on a work order yet"),
        h("ul", { class: "loose" }, loose.map((c) => h("li", {},
          h("a", { href: `#/agent/${c.id}` }, c.preview.length > 90 ? `${c.preview.slice(0, 89)}…` : c.preview),
          h("span", { class: "small muted" }, ` · ${c.turns} turn${c.turns === 1 ? "" : "s"}`))))) : null));
  };
  render();
}

// --- The Agent tab: the newest conversation, or a fresh one with the hero message ready ---

async function agentStart() {
  const conversations = await staff("/api/conversations");
  if (conversations.length) location.replace(`#/agent/${conversations[0].id}`);
  else await startWithAgent();
}

// --- Audit log --------------------------------------------------------------

let refusedOnly = false;

async function auditLog() {
  document.title = "Audit log · Workshop · Mitchell Bike Co.";
  const data = await staff(`/api/audit?refused_only=${refusedOnly}`);
  const when = (iso) => {
    const d = new Date(iso.replace(" ", "T") + (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? "" : "Z"));
    return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
  };
  app.replaceChildren(h("div", { class: "page" },
    h("h1", { class: "display" }, "Audit log"),
    h("p", { class: "subhead" },
      "Every tool call the Agent made, written by the shop's MCP servers themselves, so it's the same whichever agent platform called. ",
      "Each work order's History shows the friendly version, alongside the people's actions."),
    h("div", { class: "filters", role: "group", "aria-label": "Filter the audit log" },
      h("button", { type: "button", "aria-pressed": String(!refusedOnly), onclick: () => { refusedOnly = false; auditLog().catch(handle); } }, `All calls · ${data.total}`),
      h("button", { type: "button", "aria-pressed": String(refusedOnly), onclick: () => { refusedOnly = true; auditLog().catch(handle); } }, `Refused by the shop · ${data.refused}`)),
    data.entries.length === 0
      ? h("p", { class: "empty" }, refusedOnly ? "No refused calls yet." : "No tool calls yet. Start a conversation with the Agent.")
      : h("div", { class: "table-box" },
        h("table", { class: "data" },
          h("caption", { class: "visually-hidden" }, "Agent tool calls, newest first"),
          h("thead", {}, h("tr", {},
            h("th", { scope: "col" }, "When"), h("th", { scope: "col" }, "Tool · MCP server"),
            h("th", { scope: "col" }, "Result"), h("th", { scope: "col" }, "Work order"), h("th", { scope: "col" }, "Arguments"))),
          h("tbody", {}, data.entries.map((e) => h("tr", { class: e.refused ? "is-refused-row" : null },
            h("td", { class: "small muted", style: "white-space: nowrap" }, when(e.at), h("div", {}, e.runtime || "")),
            h("td", {}, h("span", { style: "font-weight: 600" }, e.tool), h("div", { class: "small muted" }, e.server)),
            h("td", { class: "small" }, e.refused
              ? h("span", {}, h("strong", { class: "refused" }, "Refused: "), e.result.replace(/^refused: /, ""))
              : h("span", { class: "muted" }, (e.result || "").slice(0, 160) + ((e.result || "").length > 160 ? "…" : ""))),
            h("td", {}, e.work_order_id ? h("a", { href: `#/work-orders/${e.work_order_id}` }, `#${e.work_order_id}`) : h("span", { class: "muted small" }, "—")),
            h("td", { class: "small" }, h("details", {},
              h("summary", {}, "Show"),
              h("pre", { style: "white-space: pre-wrap; margin: 4px 0 0; font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace" },
                JSON.stringify(e.arguments, null, 2)))))))))));
}

route();
