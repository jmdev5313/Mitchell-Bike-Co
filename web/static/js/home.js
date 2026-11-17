// The front door: fills in the demo details (passcode, sample Customer link, latest eval) from /api/demo.

import { api, h } from "./dom.js";

const mechanic = document.getElementById("be-mechanic");
const customer = document.getElementById("be-customer");
const passcodeNote = document.getElementById("passcode-note");
const customerNote = document.getElementById("customer-note");
const evalLine = document.getElementById("eval-line");
const resetSection = document.getElementById("reset-section");
const resetButton = document.getElementById("reset");
const sampleButton = document.getElementById("sample");
const resetStatus = document.getElementById("reset-status");

function describeEval(result) {
  if (!result) {
    return "The live check hasn't been run on this machine yet. Run make agent-check: it plays the hero story against the real model and checks what ended up in the database.";
  }
  if (result.suite) {
    const suiteCost = result.cost_usd != null ? ` The whole suite cost about $${result.cost_usd.toFixed(2)} to run.` : "";
    return `${result.passed_runs} of ${result.total_runs} runs passed across ${result.scenarios} scenarios on ${result.model} `
      + `(${result.runs_per_scenario} runs each; ${result.scenarios_all_passed} of ${result.scenarios} passed every time).${suiteCost} `
      + "Each run is judged by what ended up in the shop's database, not by the Agent's wording: the right parts, the locked price, "
      + "a date the suppliers can keep, and nothing ordered without the Customer's approval.";
  }
  const cost = result.cost_usd != null ? `, about $${result.cost_usd.toFixed(2)} a run` : "";
  return `${result.passed ? "Passed" : "Failed"}: ${result.required_passed} of ${result.required_total} required checks on ${result.model}, `
    + `${result.tool_calls} tool calls${cost}. make agent-check plays the hero story against the real model and judges the outcome `
    + "by what ended up in the database, not by the Agent's wording.";
}

async function load() {
  let info;
  try {
    info = await api("/api/demo");
  } catch {
    evalLine.textContent = "Couldn't reach the shop's API.";
    return;
  }
  evalLine.textContent = describeEval(info.latest_eval);
  evalLine.classList.toggle("muted", !info.latest_eval);

  if (info.demo_mode) {
    resetSection.hidden = false;
    document.getElementById("stage-door").hidden = false;
    if (info.staff_passcode) {
      passcodeNote.textContent = "Demo mode: you'll be signed in to the workshop automatically.";
      mechanic.addEventListener("click", () => {
        try { sessionStorage.setItem("mbc-staff-passcode", info.staff_passcode); } catch { /* private mode */ }
      });
    }
    if (info.customer_token) {
      customer.href = `/c/${info.customer_token}`;
      customer.removeAttribute("aria-disabled");
      customerNote.textContent = "Opens the newest open work order's link.";
    } else {
      customer.removeAttribute("href");
      customer.setAttribute("aria-disabled", "true");
      customerNote.textContent = "Emma has no link yet: she gets one when the Mechanic sends her the quote. Be the Mechanic first, or generate a sample quote below.";
    }
  } else {
    passcodeNote.textContent = "Sign in with STAFF_PASSCODE from .env.";
    customer.href = "#customer";
    customer.addEventListener("click", (event) => {
      event.preventDefault();
      customerNote.replaceChildren(
        "Customers open the private link the shop sends them. Run ", h("code", {}, "make sample"),
        " to create one, or turn on demo mode (DEMO_MODE=1) to get it here.");
    });
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

resetButton.addEventListener("click", () => demoAction("Resetting…", "/api/demo/reset",
  () => "Done. The shop is empty and the Agent is ready: Be the Mechanic to start."));
sampleButton.addEventListener("click", () => demoAction("Adding a sample quote…", "/api/demo/sample",
  (result) => `Done. Work order #${result.work_order_id} has a quote waiting for Emma: Be the Customer to see it.`));

load();
