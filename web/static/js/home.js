// The front door: fills in the demo details (passcode, sample Customer link, latest eval) from /api/demo.

import { api, h } from "./dom.js";

const mechanic = document.getElementById("be-mechanic");
const customer = document.getElementById("be-customer");
const passcodeNote = document.getElementById("passcode-note");
const customerNote = document.getElementById("customer-note");
const evalLine = document.getElementById("eval-line");
const resetSection = document.getElementById("reset-section");
const resetButton = document.getElementById("reset");
const resetStatus = document.getElementById("reset-status");

function describeEval(result) {
  if (!result) {
    return "The live check hasn't been run on this machine yet. Run make agent-check: it plays the hero story against the real model and checks what ended up in the database.";
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
    if (info.staff_passcode) {
      passcodeNote.textContent = "Demo mode: you'll be signed in to the workshop automatically.";
      mechanic.addEventListener("click", () => {
        try { sessionStorage.setItem("mbc-staff-passcode", info.staff_passcode); } catch { /* private mode */ }
      });
    }
    if (info.customer_token) {
      customer.href = `/c/${info.customer_token}`;
      customerNote.textContent = "Opens the newest open work order's link.";
    } else {
      customer.removeAttribute("href");
      customer.setAttribute("aria-disabled", "true");
      customerNote.textContent = "No open work order has a Customer link yet. Reset the demo, or send a quote from the workshop.";
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

resetButton.addEventListener("click", async () => {
  resetButton.disabled = true;
  resetStatus.textContent = "Resetting…";
  try {
    const result = await api("/api/demo/reset", { method: "POST" });
    customer.href = `/c/${result.customer_token}`;
    resetStatus.textContent = `Done. Work order #${result.work_order_id} has a quote waiting for Emma.`;
    load();
  } catch (e) {
    resetStatus.textContent = `Couldn't reset: ${e.message}`;
  } finally {
    resetButton.disabled = false;
  }
});

load();
