// The starting screen: six repair stories to choose from, a preview of each, the latest eval
// result, and the demo tools. Starting a story opens the demo stage with it (demo mode only).

import { api, h } from "./dom.js";

const grid = document.getElementById("bike-grid");
const preview = document.getElementById("preview");
const evalLine = document.getElementById("eval-line");
const mechanic = document.getElementById("be-mechanic");
const customer = document.getElementById("be-customer");
const customerNote = document.getElementById("customer-note");
const resetButton = document.getElementById("reset");
const sampleButton = document.getElementById("sample");
const resetStatus = document.getElementById("reset-status");

let demoMode = false;
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

function openPreview(story, from) {
  opener = from;
  const status = h("p", { class: "small", role: "status" });
  const start = h("button", { type: "button", class: "btn btn-big", onclick: () => {
    if (!demoMode) {
      status.textContent = "Starting a story needs demo mode: set DEMO_MODE=1 in .env and restart make api. "
        + "You can still open the workshop from Demo tools and describe any bike to the Agent.";
      return;
    }
    location.href = `/demo?story=${encodeURIComponent(story.key)}`;
  } }, "Start this repair");
  preview.replaceChildren(
    h("div", { class: "preview-photo" }, h("img", { src: story.photo, alt: story.title })),
    h("div", { class: "preview-text" },
      h("h2", { class: "display", id: "preview-title" }, story.title),
      h("p", { class: "muted preview-who" }, `${story.bike} · ${story.customer}`),
      h("p", { class: "bike-request preview-request" }, `“${story.complaint}”`),
      h("table", { class: "story-profile" }, h("tbody", {}, story.profile.map(([label, value]) =>
        h("tr", {}, h("th", { scope: "row" }, label), h("td", {}, value))))),
      h("div", { class: "preview-watch" },
        h("span", { class: "lbl" }, "What to watch for"),
        h("p", {}, story.watch_for)),
      story.measured ? h("p", { class: "small muted" },
        `This story is also an eval: it passed ${story.measured.passed} of ${story.measured.runs} runs against the real model.`) : null,
      h("div", { class: "preview-actions" },
        start,
        h("button", { type: "button", class: "btn btn-outline", onclick: () => preview.close() }, "Back to all bikes")),
      status,
      h("p", { class: "small muted" }, "Illustrative photo (AI-generated). Each Agent turn takes about 30 seconds and costs a few cents.")));
  preview.showModal();
  start.focus();
}

preview.addEventListener("close", () => opener?.focus());  // back to the same bike, and the page hasn't scrolled
preview.addEventListener("click", (event) => { if (event.target === preview) preview.close(); });  // the backdrop

// --- Load ------------------------------------------------------------------------------

async function load() {
  let info;
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
