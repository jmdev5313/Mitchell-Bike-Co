// The Customer's page, from their private link: /c/{token}.
// One screen per stage of the repair, one obvious action on each.

import "./cue.js";
import { h, icon, CHECK, LOCK, dollars, shortDate, longDate, api } from "./dom.js";

const token = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || "");
const base = `/api/customer/${encodeURIComponent(token)}`;
const app = document.getElementById("app");
const workOrderLabel = document.getElementById("work-order-label");
const params = new URLSearchParams(location.search);

let busy = false;
let checkoutLink = null;  // inside the demo stage, when the browser blocks the checkout tab
let confirmingDecline = false;
let error = null;

// Plain words for parts: the Customer never sees part numbers or trade names.
const PART_WORDS = {
  cassette: "Gear cluster (cassette)",
  chain: "Chain",
  rotor: "Brake rotor",
  tire: "Tire",
  brake_pad: "Brake pads",
};

function lineLabel(line) {
  if (line.category === "labor") {
    const name = line.name.replace(/\s*\(.*\)\s*$/, "");
    return `Labor: ${name.charAt(0).toLowerCase()}${name.slice(1)}`;
  }
  const words = PART_WORDS[line.category] || line.name;
  return line.qty > 1 ? `${words} × ${line.qty}` : words;
}

async function load() {
  try {
    render(await api(base));
  } catch (e) {
    renderError(e);
  }
}

async function act(request) {
  if (busy) return;
  busy = true;
  error = null;
  rerender();
  try {
    const view = await request();
    busy = false;
    confirmingDecline = false;
    if (view) render(view);
  } catch (e) {
    busy = false;
    error = e.message;
    rerender();
  }
}

let current = null;
function rerender() { if (current) render(current); }

function render(view) {
  current = view;
  workOrderLabel.textContent = `Work order #${view.work_order_id}`;
  document.title = `${titleFor(view)} · Mitchell Bike Co.`;
  const screen = {
    quoted: view.open_quote_message_id ? quoteScreen : looking,
    declined: declinedScreen,
    approved: onIt, awaiting_parts: onIt, scheduled: onIt, in_progress: onIt,
    done: readyScreen,
    paid: paidScreen,
  }[view.status] || looking;
  app.replaceChildren(...screen(view).filter(Boolean));
}

function titleFor(view) {
  return {
    quoted: "Your repair quote", declined: "Quote declined", done: "Your bike is ready", paid: "Paid",
  }[view.status] || "Your repair";
}

function bikeName(view) {
  return view.bike.nickname || view.bike.model;
}

function firstName(view) {
  return (view.customer || "").split(" ")[0];
}

function heading(text, lede) {
  return [h("h1", { class: "display" }, text), lede ? h("p", { class: "lede" }, lede) : null];
}

function latestShopMessage(view, excludeId = null) {
  const shop = view.messages.filter((m) => m.from === "shop" && m.id !== excludeId);
  return shop[shop.length - 1] || null;
}

function shopMessage(message) {
  if (!message) return null;
  return h("section", { class: "shop-message" },
    h("div", { class: "from" }, `From the shop, ${shortDate(message.at)}`),
    h("p", {}, message.body));
}

function errorNotice() {
  return error ? h("p", { class: "notice-refused", role: "alert" }, h("strong", {}, "Couldn't do that: "), error) : null;
}

function quoteLedger(view, { totalLabel = "Total", totalSize = null } = {}) {
  const lines = view.quote.lines;
  const rows = lines.map((line, i) =>
    h("tr", { class: i === lines.length - 1 ? "last" : null },
      h("th", { scope: "row" }, lineLabel(line)),
      h("td", {}, dollars(line.unit_price_cents * line.qty))));
  const total = h("td", { style: totalSize ? `font-size: ${totalSize}px` : null }, dollars(view.quote.total_cents));
  rows.push(h("tr", { class: "total" }, h("th", { scope: "row" }, totalLabel), total));
  return h("table", { class: "ledger" }, h("caption", { class: "visually-hidden" }, "Quote"), h("tbody", {}, rows));
}

function thread(view, { excludeId = null, title = "Messages with the shop" } = {}) {
  const items = view.messages.filter((m) => m.id !== excludeId);
  if (!items.length) return null;
  return h("section", {},
    h("h2", {}, title),
    h("ol", { class: "thread" }, items.map((m) =>
      h("li", {},
        h("div", { class: "who" }, `${m.from === "shop" ? "Mitchell Bike Co." : "You"}, ${shortDate(m.at)}`),
        h("p", { class: "body" }, m.body)))));
}

/** The reply box. A `suggestion` shows as the placeholder and becomes real text on Tab or a tap. */
function replyForm(placeholder, { suggestion = null } = {}) {
  const input = h("input", {
    id: "reply", class: "input", type: "text", name: "body", required: true,
    placeholder: suggestion || placeholder, autocomplete: "off", maxlength: 2000,
    "aria-describedby": suggestion ? "reply-hint" : null,
  });
  const chip = suggestion ? h("button", { type: "button", class: "suggestion", onclick: () => use() },
    h("span", { class: "visually-hidden" }, "Use the suggestion: "), suggestion) : null;
  const suggestRow = suggestion ? h("div", { class: "suggest-row" },
    h("span", { id: "reply-hint", class: "small" }, "Tap to use it, or press Tab:"), chip) : null;
  function use() {
    input.value = suggestion;
    input.focus();
    input.setSelectionRange(suggestion.length, suggestion.length);
    suggestRow.hidden = true;
  }
  if (suggestion) {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Tab" && !event.shiftKey && !input.value) { event.preventDefault(); use(); }
    });
    input.addEventListener("input", () => { suggestRow.hidden = Boolean(input.value); });
  }
  return h("form", {
    class: "reply-form",
    onsubmit: (event) => {
      event.preventDefault();
      const body = input.value.trim();
      if (!body) return;
      act(() => api(`${base}/replies`, { method: "POST", body: { body } }));
    },
  },
    h("label", { for: "reply" }, "Questions? Message the shop"),
    h("div", { class: "row" }, input,
      h("button", { type: "submit", class: "btn btn-outline", disabled: busy }, "Send")),
    suggestRow);
}

function step(label, { done = false, when = "", current = false } = {}) {
  const marker = done ? icon(CHECK) : h("span", { class: "box", "aria-hidden": "true" });
  return h("li", { class: done || current ? null : "todo", "aria-current": current ? "step" : null },
    marker,
    h("span", { class: "label" }, label, done ? h("span", { class: "visually-hidden" }, " (done)") : null),
    when ? h("span", { class: "when" }, when) : null);
}

function steps(view) {
  const t = view.timeline;
  const list = [step("Quote approved", { done: true, when: shortDate(t.decided_at) })];
  if (t.parts_ordered) {
    list.push(t.parts_received_at
      ? step("Parts arrived", { done: true, when: shortDate(t.parts_received_at) })
      : step("Waiting for parts", { current: view.status === "awaiting_parts" }));
  }
  if (t.finished_at) {
    list.push(step("Repair finished", { done: true, when: shortDate(t.finished_at) }));
  } else if (view.status === "in_progress") {
    list.push(step("Repair in progress", { current: true }));
  } else if (view.scheduled_for) {
    list.push(step(`Repair booked for ${longDate(view.scheduled_for)}`, { current: view.status === "scheduled" }));
  } else {
    list.push(step("Repair to be booked"));
  }
  list.push(view.status === "done"
    ? step("Pay and pick up", { current: true })
    : step("Ready to pick up"));
  return h("ol", { class: "steps", "aria-label": "Repair progress" }, list);
}

// --- Screens -----------------------------------------------------------------

function quoteScreen(view) {
  const quoteMessage = view.messages.find((m) => m.id === view.open_quote_message_id);
  const decide = (approved) => act(() =>
    api(`${base}/messages/${view.open_quote_message_id}/decision`, { method: "POST", body: { approved } }));

  const actions = confirmingDecline
    ? h("div", { class: "decline-confirm", style: "margin-top: 16px" },
        h("p", { style: "margin: 0 0 8px; font-weight: 600" }, "Decline this quote? We won't do any work on your bike."),
        h("div", { style: "display: flex; gap: 8px; flex-wrap: wrap" },
          h("button", { type: "button", class: "btn", disabled: busy, onclick: () => decide(false) }, "Yes, decline"),
          h("button", { type: "button", class: "btn btn-outline", disabled: busy,
            onclick: () => { confirmingDecline = false; rerender(); } }, "Keep the quote")))
    : h("div", { style: "display: flex; flex-direction: column; gap: 2px; margin-top: 16px" },
        h("button", { type: "button", class: "btn btn-big", disabled: busy, onclick: () => decide(true) },
          busy ? "Saving…" : `Approve ${dollars(view.quote.total_cents)}`),
        h("button", { type: "button", class: "btn-text", disabled: busy,
          onclick: () => { confirmingDecline = true; rerender(); } }, "Decline"));

  return [
    ...heading("Your repair quote", `For your ${bikeName(view)}`),
    shopMessage(quoteMessage),
    h("hr", { class: "tear", "aria-hidden": "true" }),
    h("div", { style: "margin-top: 8px" }, quoteLedger(view)),
    actions,
    errorNotice(),
    replyForm("Message the shop", { suggestion: "Can it be ready by Friday?" }),
    thread(view, { excludeId: view.open_quote_message_id, title: "Other messages with the shop" }),
  ];
}

function looking(view) {
  const latest = latestShopMessage(view);
  return [
    ...heading("We're looking at your bike", `For your ${bikeName(view)}`),
    shopMessage(latest),
    errorNotice(),
    replyForm("Ask the shop anything"),
    thread(view, { excludeId: latest && latest.id, title: "Earlier messages" }),
  ];
}

function declinedScreen(view) {
  return [
    ...heading("You declined the quote", `For your ${bikeName(view)}`),
    h("p", { style: "margin: 16px 0 0" },
      "We won't do any work on your bike. If you change your mind or have a question, message the shop below."),
    errorNotice(),
    replyForm("Message the shop"),
    thread(view),
  ];
}

function onIt(view) {
  const latest = latestShopMessage(view);
  return [
    ...heading("Thanks, we're on it", `Hi ${firstName(view)}. This is for your ${bikeName(view)}.`),
    steps(view),
    shopMessage(latest),
    h("hr", { class: "tear", "aria-hidden": "true" }),
    h("div", { class: "amount-due" },
      h("span", { class: "label" }, "Quoted total"),
      h("span", { class: "value num", style: "font-size: 32px" }, dollars(view.quote.total_cents))),
    h("p", { class: "note" }, "You'll pay when the repair is done."),
    errorNotice(),
    replyForm("Ask the shop anything"),
    thread(view, { excludeId: latest && latest.id, title: "Earlier messages" }),
  ];
}

function readyScreen(view) {
  const latest = latestShopMessage(view);
  const pay = () => {
    // Stripe Checkout can't run inside a frame, so inside the demo stage it opens in a new tab.
    // The tab is opened now, during the click, so the browser doesn't block it as a pop-up.
    const framed = window.parent !== window;
    const tab = framed ? window.open("", "_blank") : null;
    return act(async () => {
      let checkout_url;
      try {
        ({ checkout_url } = await api(`${base}/checkout`, { method: "POST" }));
      } catch (e) {
        if (tab) tab.close();
        throw e;
      }
      if (tab) {
        tab.opener = null;
        tab.location.href = checkout_url;
      } else if (framed) {
        checkoutLink = checkout_url;  // the browser blocked the new tab: offer a link instead
      } else {
        location.assign(checkout_url);
      }
      return framed ? api(base) : null;  // in the stage this page stays, so show it again
    });
  };
  return [
    ...heading("Your bike is ready", `Hi ${firstName(view)}. This is for your ${bikeName(view)}.`),
    steps(view),
    shopMessage(latest),
    params.get("checkout") === "cancelled"
      ? h("p", { class: "note", role: "status" }, "Payment cancelled. You haven't been charged.")
      : null,
    h("hr", { class: "tear", "aria-hidden": "true" }),
    h("div", { class: "amount-due" },
      h("span", { class: "label" }, "Amount due"),
      h("span", { class: "value num" }, dollars(view.quote.total_cents))),
    h("div", { style: "margin-top: 16px" },
      h("button", { type: "button", class: "btn btn-big", disabled: busy, onclick: pay },
        busy ? "Opening secure checkout…" : `Pay ${dollars(view.quote.total_cents)}`),
      h("div", { class: "secure-note" }, icon(LOCK, 14, 1.8), "Secure checkout by Stripe, test mode"),
      checkoutLink ? h("p", { class: "note", role: "status" }, "Your browser kept the checkout from opening. ",
        h("a", { href: checkoutLink, target: "_blank", rel: "noopener noreferrer" }, "Open the secure checkout in a new tab")) : null),
    errorNotice(),
    thread(view, { excludeId: latest && latest.id, title: "Earlier messages" }),
  ];
}

function paidScreen(view) {
  const paidOn = shortDate(view.timeline.paid_at);
  return [
    h("h1", { class: "display", style: "margin-top: 24px" }, "Paid, thank you!"),
    h("p", { class: "status-line paid-mark" }, icon(CHECK), `Paid ${paidOn}`),
    h("p", { style: "margin: 12px 0 0" },
      `${dollars(view.quote.total_cents)} received. Your ${bikeName(view)} is ready to pick up.`),
    h("hr", { class: "tear", "aria-hidden": "true", style: "margin-top: 24px" }),
    h("section", {},
      h("h2", {}, "Receipt"),
      quoteLedger(view, { totalLabel: `Paid ${paidOn}`, totalSize: 32 })),
    thread(view),
  ];
}

function renderError(e) {
  if (e.status === 404) {
    workOrderLabel.textContent = "";
    document.title = "Link not found · Mitchell Bike Co.";
    app.replaceChildren(
      ...heading("This link doesn't work").filter(Boolean),
      h("p", { style: "margin: 16px 0 0" },
        "Check that you opened the whole link from the shop's message. If it still doesn't work, contact the shop."));
    return;
  }
  app.replaceChildren(
    ...heading("Something went wrong").filter(Boolean),
    h("p", { class: "notice-refused", role: "alert" }, h("strong", {}, "Couldn't load your repair: "), e.message),
    h("button", { type: "button", class: "btn btn-outline", style: "margin-top: 16px", onclick: load }, "Try again"));
}

load();
