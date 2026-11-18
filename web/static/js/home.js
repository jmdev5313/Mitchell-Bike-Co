// The starting screen: six repair stories to choose from, a preview of each, the latest eval
// result, and the demo tools. Starting a story opens the demo stage with it (demo mode only).
// When the live Agent can't take turns (the hosted demo's budget), stories play as recorded runs;
// with Turnstile on, a live story starts after the bot check.

import { api, h } from "./dom.js";
import { startStory, explainRecordedRuns, longDate } from "./story.js";

const grid = document.getElementById("bike-grid");
const preview = document.getElementById("preview");
const evalLine = document.getElementById("eval-line");
const mechanic = document.getElementById("be-mechanic");
const customer = document.getElementById("be-customer");
const customerNote = document.getElementById("customer-note");
const resetButton = document.getElementById("reset");
const sampleButton = document.getElementById("sample");
const resetStatus = document.getElementById("reset-status");
const resting = document.getElementById("resting");

let demoMode = false;
let info = {};  // GET /api/demo
let opener = null;  // the card that opened the preview, to return focus to

function describeEval(result) {
  if (!result) {
    return "The eval suite hasn't been run on this machine yet. Run make evals: it plays every story against the real model and checks what ended up in the shop's database.";
  }
  if (result.suite) {
    const cost = result.cost_usd != null ? ` The whole suite cost about $${result.cost_usd.toFixed(2)} to run.` : "";
    return `Every story here is also an automated test. ${result.passed_runs} of ${result.total_runs} runs passed across `
      + `${result.scenarios} scenarios on ${result.model} (${result.runs_per_scenario} runs each).${cost} Each run is judged by `
      + "what ended up in the shop's database, not by the Agent's wording: the right parts, the locked price, a date the "
      + "suppliers can keep, and nothing ordered without the Customer's approval.";
  }
  const cost = result.cost_usd != null ? `, about $${result.cost_usd.toFixed(2)} a run` : "";
  return `${result.passed ? "Passed" : "Failed"}: ${result.required_passed} of ${result.required_total} required checks on ${result.model}${cost}.`;
}

// --- The six stories ---------------------------------------------------------------

function card(story) {
  const [kind, model, rider] = [story.label, story.bike, story.customer];
  return h("li", {},
    h("button", { type: "button", class: "bike-card", "data-key": story.key, onclick: (event) => openPreview(story, event.currentTarget) },
      h("span", { class: "bike-photo" }, h("img", { src: story.photo, alt: "" })),
      h("span", { class: "bike-body" },
        story.key === "hero" ? h("span", { class: "start-here" }, "Start here") : null,
        h("span", { class: "bike-request" }, `“${story.complaint}”`),
        h("span", { class: "bike-who" }, `${kind} · ${model} · ${rider}`))));
}

let turnstileReady = null;
function loadTurnstile() {
  turnstileReady ??= new Promise((resolve, reject) => {
    document.head.append(h("script", {
      src: "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit", async: true,
      onload: () => resolve(window.turnstile), onerror: () => reject(new Error("The bot check couldn't load. Reload the page and try again.")),
    }));
  });
  return turnstileReady;
}

function restingNotice(story) {
  return h("div", { class: "resting-box", role: "status" },
    h("strong", {}, info.agent?.reason || "The live Agent is resting."),
    story.recorded
      ? h("p", {}, "You can still play this story with a ", h("strong", {}, "recorded run"),
        `: the Agent's real turns on it, recorded on ${longDate(story.recorded.recorded_on)}, `
        + "replayed in your own copy of the shop. Its tool calls run again against the shop's rules, so the quote, the draft and the "
        + `order plan are real. Then you send the quote, approve it as ${story.customer.split(" ")[0]} and pay, as usual.`)
      : h("p", {}, "This story has no recorded run yet. Try one of the others, or come back when the live Agent is back."),
    story.recorded ? h("p", { class: "small muted" }, "You can't change the Mechanic's messages in a recorded run, and the shop's calendar shows the day it was recorded so the dates match. ",
      h("button", { type: "button", class: "linkish", onclick: () => explainRecordedRuns({ recordedOn: story.recorded.recorded_on }) }, "More about recorded runs")) : null);
}

function openPreview(story, from) {
  opener = from;
  const live = !demoMode || !info.agent || info.agent.live;
  const recorded = !live && Boolean(story.recorded);
  const status = h("div", { role: "status" });
  let token = null;
  const start = h("button", { type: "button", class: "btn btn-big", onclick: async () => {
    if (!demoMode) {
      status.replaceChildren(h("p", { class: "small" }, "Starting a story needs demo mode: set DEMO_MODE=1 in .env and restart make api. "
        + "You can still open the workshop from Demo tools and describe any bike to the Agent."));
      return;
    }
    start.disabled = true;
    status.replaceChildren();
    try {
      await startStory(story.key, { recorded, turnstileToken: token });
      location.href = "/demo";
    } catch (e) {
      let current = null;
      try { current = sessionStorage.getItem("mbc-story"); } catch { /* private mode */ }
      status.replaceChildren(h("div", { class: "notice-refused", role: "alert" },
        h("p", { style: "margin: 0" }, h("strong", {}, "Not started: "), e.message),
        current && e.status === 429 ? h("p", { class: "small", style: "margin: 4px 0 0" }, "Your current shop is still open: you can keep playing the story you started. ",
          h("a", { href: "/demo" }, "Back to my story →")) : null));
      if (e.status === 403 && window.turnstile) { token = null; window.turnstile.reset(); }
      else start.disabled = false;
    }
  } }, recorded ? "Start the recorded run" : "Start this repair");

  // The bot check, for a live story when the hosted demo has Turnstile on. It usually passes unseen.
  const widget = h("div");
  const check = h("div", { class: "bot-check", hidden: true },
    h("p", { class: "lbl" }, "One quick check before we set up your shop"), widget,
    h("p", { class: "small muted" }, "It keeps scripts from running up the live Agent's budget. Most visitors never see it."));
  if (demoMode && live && info.turnstile_site_key) {
    start.disabled = true;
    loadTurnstile().then((turnstile) => turnstile.render(widget, {
      sitekey: info.turnstile_site_key, appearance: "interaction-only",
      callback: (t) => { token = t; start.disabled = false; },
      "expired-callback": () => { token = null; start.disabled = true; },
      "before-interactive-callback": () => { check.hidden = false; },
      "after-interactive-callback": () => { check.hidden = true; },
      "error-callback": () => { status.replaceChildren(h("p", { class: "small" }, "The bot check couldn't run. Reload the page and try again.")); },
    })).catch((e) => status.replaceChildren(h("p", { class: "small" }, e.message)));
  }
  if (!live && !recorded) start.disabled = true;

  preview.replaceChildren(
    h("div", { class: "preview-photo" }, h("img", { src: story.photo, alt: story.title })),
    h("div", { class: "preview-text" },
      h("h2", { class: "display", id: "preview-title" }, story.title),
      h("p", { class: "muted preview-who" }, `${story.bike} · ${story.customer}`),
      h("p", { class: "bike-request preview-request" }, `“${story.complaint}”`),
      live ? h("table", { class: "story-profile" }, h("tbody", {}, story.profile.map(([label, value]) =>
        h("tr", {}, h("th", { scope: "row" }, label), h("td", {}, value))))) : null,  // on the workshop's Bike tab, too
      h("div", { class: "preview-watch" },
        h("span", { class: "lbl" }, "What to watch for"),
        h("p", {}, story.watch_for)),
      live ? null : restingNotice(story),
      live && story.measured ? h("p", { class: "small muted" },
        `This story is also an eval: it passed ${story.measured.passed} of ${story.measured.runs} runs against the real model.`) : null,
      check,
      h("div", { class: "preview-actions" },
        start,
        h("button", { type: "button", class: "btn btn-outline", onclick: () => preview.close() }, "Back to all bikes")),
      status,
      h("p", { class: "small muted" }, live
        ? "Illustrative photo (AI-generated). Each Agent turn takes about 30 seconds and costs a few cents."
        : `Illustrative photo (AI-generated).${story.measured ? ` This story is also an eval: it passed ${story.measured.passed} of ${story.measured.runs} runs against the real model.` : ""}`)));
  preview.showModal();
  (start.disabled ? preview.querySelector(".btn-outline") : start).focus();
}

preview.addEventListener("close", () => opener?.focus());  // back to the same bike, and the page hasn't scrolled
preview.addEventListener("click", (event) => { if (event.target === preview) preview.close(); });  // the backdrop

// --- Load ------------------------------------------------------------------------------

async function load() {
  try {
    info = await api("/api/demo");
  } catch {
    evalLine.textContent = "Couldn't reach the shop's API.";
    return;
  }
  demoMode = info.demo_mode;
  evalLine.textContent = describeEval(info.latest_eval);
  evalLine.classList.toggle("muted", !info.latest_eval);
  try {
    grid.replaceChildren(...(await api("/api/demo/stories")).map(card));
  } catch {
    grid.replaceChildren(h("li", { class: "muted" }, "Couldn't load the stories."));
  }

  // The live Agent resting (budget spent, or switched off): every story still plays, recorded.
  const restingNow = demoMode && info.agent && !info.agent.live;
  resting.hidden = !restingNow;
  if (restingNow) {
    resting.replaceChildren(
      h("p", {}, h("strong", {}, info.agent.reason), " Every story still plays, with a recorded run of the real Agent."),
      h("button", { type: "button", class: "linkish", onclick: () => explainRecordedRuns() }, "What's a recorded run?"));
  }

  resetButton.hidden = sampleButton.hidden = !demoMode;
  resetButton.nextElementSibling.hidden = sampleButton.nextElementSibling.hidden = !demoMode;
  if (demoMode) {
    if (info.staff_passcode) {
      mechanic.addEventListener("click", () => {
        try { sessionStorage.setItem("mbc-staff-passcode", info.staff_passcode); } catch { /* private mode */ }
      });
    }
    if (info.customer_token) {
      customer.href = `/c/${info.customer_token}`;
      customer.removeAttribute("aria-disabled");
      customerNote.textContent = "Opens the newest open work order's private link.";
    } else {
      customer.removeAttribute("href");
      customer.setAttribute("aria-disabled", "true");
      customerNote.textContent = "No Customer has a link yet: they get one when the Mechanic sends a quote.";
    }
  } else {
    customer.href = "#customer";
    customerNote.textContent = "Customers open the private link the shop sends them. Run make sample to create one.";
  }
}

async function demoAction(busyText, path, done) {
  resetButton.disabled = sampleButton.disabled = true;
  resetStatus.textContent = busyText;
  try {
    resetStatus.textContent = done(await api(path, { method: "POST" }));
    load();
  } catch (e) {
    resetStatus.textContent = `Couldn't do that: ${e.message}`;
  } finally {
    resetButton.disabled = sampleButton.disabled = false;
  }
}

resetButton.addEventListener("click", () => demoAction("Resetting…", "/api/demo/reset", () => "Done. The shop is empty."));
sampleButton.addEventListener("click", () => demoAction("Adding a sample quote…", "/api/demo/sample",
  (result) => `Done. Work order #${result.work_order_id} has a quote waiting for Emma.`));

load();
