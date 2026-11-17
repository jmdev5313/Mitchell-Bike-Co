// The demo stage (/demo): the workshop at full width, and the Customer's phone in a "Customer POV"
// overlay that opens from a tab at the bottom. A step guide says whose turn it is; the tab says
// "New" when it's the Customer's turn, and the next button on that side gets a ring (cue.js).
// Demo mode only: it signs in to the workshop and opens the Customer's link for you.

import { h, api, dollars } from "./dom.js";

const stage = document.getElementById("stage");
const guide = document.getElementById("guide");
const stepsList = document.getElementById("steps");
const restart = document.getElementById("restart");
const frameMechanic = document.getElementById("frame-mechanic");
const workshop = document.getElementById("side-mechanic");
const pov = document.getElementById("pov");
const povTab = document.getElementById("pov-tab");
const povSub = document.getElementById("pov-sub");
const povBadge = document.getElementById("pov-badge");
const sheet = document.getElementById("pov-sheet");
const scrim = document.getElementById("pov-scrim");
const phone = document.getElementById("phone");
const screen = document.getElementById("phone-screen");
const phoneApp = document.getElementById("phone-app");  // the page under the phone's status bar

const PHONE_W = 390;
const PHONE_H = 844;

let frameCustomer = null;
let last = { step: null, whose: null, token: undefined };
let collapseTimer = null;

const stepNames = (first) => ["Ask the Agent", "Send the quote", `${first} approves`, "The repair", `${first} pays`];

async function boot() {
  let info;
  try {
    info = await api("/api/demo");
  } catch {
    guide.textContent = "Couldn't reach the shop's API. Is make api running?";
    return;
  }
  if (!info.demo_mode) {
    for (const el of [stepsList, restart]) el.hidden = true;
    guide.hidden = true;
    stage.replaceChildren(h("div", { class: "page" },
      h("h1", { class: "display" }, "The demo stage needs demo mode"),
      h("p", { class: "lede", style: "max-width: 640px" },
        "Set DEMO_MODE=1 in .env and restart make api. Demo mode signs you in to the workshop and opens the Customer's link for you, so only use it with synthetic data."),
      h("p", {}, h("a", { href: "/" }, "Back to the front door"))));
    return;
  }
  if (info.staff_passcode) {
    try { sessionStorage.setItem("mbc-staff-passcode", info.staff_passcode); } catch { /* private mode */ }
  }
  const story = info.story;
  frameMechanic.src = story.work_order_id ? `/workshop#/work-orders/${story.work_order_id}` : "/workshop#/work-orders";
  frameMechanic.addEventListener("load", () => cue(last.story));
  render(story);
  setInterval(tick, 2000);
  addEventListener("resize", fitPhone);
  povTab.addEventListener("click", () => setOpen(sheet.hidden));
  scrim.addEventListener("click", () => setOpen(false));
  addEventListener("keydown", (event) => { if (event.key === "Escape" && !sheet.hidden) setOpen(false); });
}

async function tick() {
  if (document.hidden) return;
  try { render((await api("/api/demo")).story); } catch { /* the next tick will try again */ }
}

function render(story) {
  const first = (story.customer || "Emma Clark").split(" ")[0];
  const names = stepNames(first);
  const changed = story.step !== last.step || story.whose !== last.whose;

  // The steps across the top
  stepsList.replaceChildren(...names.map((name, i) => {
    const n = i + 1;
    const state = n < story.step ? "done" : n === story.step ? "current" : "todo";
    return h("li", { class: state, "aria-current": state === "current" ? "step" : null },
      h("span", { class: "n", "aria-hidden": "true" }, String(n)), name,
      state === "done" ? h("span", { class: "visually-hidden" }, " (done)") : null);
  }));

  // Whose turn
  const theirs = story.whose === "customer";
  workshop.classList.toggle("is-turn", story.whose === "mechanic");
  pov.classList.toggle("is-turn", theirs);
  povBadge.hidden = !theirs;
  povSub.textContent = theirs ? `Your turn as ${first}` : `${first}'s phone`;
  // Guide and steps first, so the screen reader hears the step, then the change.
  if (changed || story.next_step !== last.story?.next_step) guide.replaceChildren(...guideText(story, first));

  // The Customer's phone: her link appears once the shop has sent her something
  if (story.customer_token !== last.token) {
    if (story.customer_token) {
      frameCustomer = h("iframe", { title: `${first}'s page, on her phone`, src: `/c/${story.customer_token}` });
      frameCustomer.addEventListener("load", () => cue(last.story));
      phoneApp.replaceChildren(frameCustomer);
    } else {
      frameCustomer = null;
      phoneApp.replaceChildren(h("div", { class: "phone-empty" },
        h("p", { class: "display" }, "No messages yet"),
        h("p", {}, `${first} gets a private link when the Mechanic sends her the quote. It opens here.`)));
    }
    fitPhone();
  } else if (changed && frameCustomer && (theirs || story.step === 6)) {
    frameCustomer.contentWindow.location.reload();  // her page doesn't refresh itself
  }

  // When her turn ends, give her page a moment to show what happened, then fold it away.
  if (changed && last.whose === "customer" && story.whose === "mechanic" && !sheet.hidden) {
    clearTimeout(collapseTimer);
    collapseTimer = setTimeout(() => setOpen(false), 1800);
  }

  last = { step: story.step, whose: story.whose, token: story.customer_token, story };
  cue(story);
}

/** Whose turn, and one short line. The rings show which button; the steps up top show where you are. */
function guideText(story, first) {
  const total = story.total_cents !== null ? dollars(story.total_cents) : "the quote";
  const tag = story.whose === "customer" ? `Your turn · ${first}` : story.whose === "mechanic" ? "Your turn · Mechanic" : "Done";
  const say = (...parts) => [h("span", { class: `lead whose-${story.whose}` }, tag), h("span", {}, ...parts)];
  switch (story.step) {
    case 1:
      return story.work_order_id
        ? say("The Agent is working. Watch its tool calls; its draft to ", first, " appears in the chat.")
        : say("Start with the Agent, then Send. A turn takes 20 to 40 seconds.");
    case 2:
      return say(`Send the Agent's quote to ${first}.`);
    case 3:
      return story.whose === "mechanic"
        ? say(first, " wrote to the shop: answer her, then it's her turn to approve.")
        : say(`Open Customer POV and approve ${total}. Optional: press Tab to ask a question first.`);
    case 4:
      return say(`${story.next_step}.`);
    case 5:
      return story.whose === "mechanic"
        ? say(first, " wrote to the shop: answer her. She can pay any time.")
        : say(`Open Customer POV and pay ${total}. Test card 4242 4242 4242 4242.`);
    default:
      return story.status === "declined"
        ? say(first, " declined the quote. Start over to run it again.")
        : say("That's the whole story. See who did what in the work order's History tab, or Start over.");
  }
}

/** Tell each side which controls to ring: only the side whose turn it is gets any. */
function cue(story) {
  if (!story) return;
  const id = story.work_order_id;
  const row = id ? [`.data tr:has(a[href="#/work-orders/${id}"])`] : [];  // on the list, the job's row
  const draft = [".draft-card.is-draft .review", ".draft-band .btn-send"];
  let mechanic = [];
  if (story.whose === "mechanic") {
    if (story.step === 1) mechanic = id ? [] : [".start-agent", ".job-chat .composer button[type=submit]"];
    else mechanic = [...(story.action === "send_draft" ? draft : [".nextbar .do .btn"]), ...row,
      '.job[data-view="chat"] .job-switch button:last-child'];  // the next button is on the work order half
  }
  const customer = story.whose === "customer" ? [".btn-big"] : [];
  povTab.classList.toggle("cue", story.whose === "customer" && sheet.hidden);
  post(frameMechanic, mechanic);
  if (frameCustomer) post(frameCustomer, customer);
}

function post(frame, selectors) {
  try { frame.contentWindow.postMessage({ type: "mbc-cue", selectors }, location.origin); } catch { /* not loaded yet */ }
}

/** Open or fold away the Customer POV overlay. */
function setOpen(open) {
  clearTimeout(collapseTimer);
  sheet.hidden = !open;
  scrim.hidden = !open;
  pov.classList.toggle("is-open", open);
  povTab.setAttribute("aria-expanded", String(open));
  povTab.querySelector(".pov-caret").textContent = open ? "▼" : "▲";
  povTab.classList.toggle("cue", !open && last.whose === "customer");
  if (open) fitPhone();
}

/** Scale the phone to fit the overlay, keeping a real phone's proportions. */
function fitPhone() {
  if (sheet.hidden) return;
  const room = { w: Math.min(innerWidth - 64, 460), h: stage.clientHeight - 24 };  // the tab sits in the bottom bar, below
  const bezel = 2 * 12;  // the phone's frame, in CSS (.phone border)
  const scale = Math.max(0.4, Math.min(1, room.w / (PHONE_W + bezel), (room.h - 16) / (PHONE_H + bezel)));
  phone.style.width = `${Math.round(PHONE_W * scale) + bezel}px`;
  phone.style.height = `${Math.round(PHONE_H * scale) + bezel}px`;
  screen.style.width = `${PHONE_W}px`;
  screen.style.height = `${PHONE_H}px`;
  screen.style.transform = `scale(${scale})`;
}

restart.addEventListener("click", async () => {
  restart.disabled = true;
  guide.replaceChildren(h("span", { class: "lead" }, "Starting over…"));
  try {
    await api("/api/demo/reset", { method: "POST" });
    frameMechanic.src = `/workshop?fresh=${Date.now()}#/work-orders`;  // a new load, even if the address was the same
    setOpen(false);
    last = { step: null, whose: null, token: undefined };
    await tick();
  } catch (e) {
    guide.textContent = `Couldn't start over: ${e.message}`;
  } finally {
    restart.disabled = false;
  }
});

boot();
