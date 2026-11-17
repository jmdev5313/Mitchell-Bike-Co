// The demo stage (/demo): the workshop and the Customer's phone side by side. A step guide says
// whose turn it is, and the next button on that side gets a ring (cue.js, inside each page).
// Demo mode only: it signs in to the workshop and opens the Customer's link for you.

import { h, api, dollars } from "./dom.js";

const stage = document.getElementById("stage");
const guide = document.getElementById("guide");
const stepsList = document.getElementById("steps");
const tabs = document.getElementById("tabs");
const restart = document.getElementById("restart");
const frameMechanic = document.getElementById("frame-mechanic");
const phone = document.getElementById("phone");
const screen = document.getElementById("phone-screen");
const sides = { mechanic: document.getElementById("side-mechanic"), customer: document.getElementById("side-customer") };

const NARROW = matchMedia("(max-width: 1100px)");
const PHONE_W = 390;
const PHONE_H = 844;

let frameCustomer = null;
let last = { step: null, whose: null, token: undefined };
let view = "mechanic";  // which side shows at narrow widths

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
    for (const el of [stepsList, tabs, restart]) el.hidden = true;
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
  NARROW.addEventListener("change", () => { showSide(view); fitPhone(); });
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
  for (const [who, side] of Object.entries(sides)) {
    const turn = story.whose === who;
    side.classList.toggle("is-turn", turn);
    side.querySelector(".turn").hidden = !turn;
  }
  document.getElementById("label-customer").replaceChildren(h("strong", {}, `You're ${first}`), " · her phone");
  // Within a step (the repair has several), the guide follows the work order's next step.
  if (changed || story.next_step !== last.story?.next_step) guide.replaceChildren(...guideText(story, first));

  // The Customer's phone: her link appears once the shop has sent her something
  if (story.customer_token !== last.token) {
    if (story.customer_token) {
      frameCustomer = h("iframe", { title: `${first}'s page, on her phone`, src: `/c/${story.customer_token}` });
      frameCustomer.addEventListener("load", () => cue(last.story));
      screen.replaceChildren(frameCustomer);
    } else {
      frameCustomer = null;
      screen.replaceChildren(h("div", { class: "phone-empty" },
        h("p", { class: "display" }, "No messages yet"),
        h("p", {}, `${first} gets a private link when the Mechanic sends her the quote. It opens here.`)));
    }
    fitPhone();
  } else if (changed && frameCustomer && (story.whose === "customer" || story.step === 6)) {
    frameCustomer.contentWindow.location.reload();  // her page doesn't refresh itself
  }

  // At narrow widths, follow the turn
  tabs.replaceChildren(...[["mechanic", "Workshop"], ["customer", `${first}'s phone`]].map(([who, label]) =>
    h("button", { type: "button", "data-who": who, "aria-pressed": String(view === who), onclick: () => showSide(who) },
      label, story.whose === who ? h("span", { class: "tab-dot turn-dot", title: "Your turn" },
        h("span", { class: "visually-hidden" }, ", your turn")) : null)));
  if (changed && (story.whose === "mechanic" || story.whose === "customer")) showSide(story.whose);

  last = { step: story.step, whose: story.whose, token: story.customer_token, story };
  cue(story);
}

function guideText(story, first) {
  const total = story.total_cents !== null ? dollars(story.total_cents) : "the quote";
  const lead = (text) => h("span", { class: "lead" }, text);
  const where = story.whose === "customer" ? `Your turn as ${first}` : story.whose === "mechanic" ? "Your turn as the Mechanic" : "Done";
  const head = story.step <= 5 ? lead(`Step ${story.step} of 5 · ${where}`) : lead(where);
  const say = (...parts) => [head, h("span", {}, ...parts)];
  switch (story.step) {
    case 1:
      return story.work_order_id
        ? say("The Agent is working: watch its tool calls in the activity log. When it finishes, its draft to ", first, " appears as a card in the chat.")
        : say("In the workshop, click ", h("b", {}, "Start with the Agent"), ", then ", h("b", {}, "Send"),
          ". The Agent looks up the bike, checks what fits, quotes and drafts a message. A turn takes 20 to 40 seconds and costs a few cents.");
    case 2:
      return say("Click ", h("b", {}, "Review and send →"), " on the Agent's draft, then ", h("b", {}, `Send to ${first}`),
        ". The Agent can't send messages; only you can.");
    case 3:
      return story.whose === "mechanic"
        ? say(first, " wrote to the shop. In the workshop: ", h("b", {}, story.next_step), ", then send the answer. Then it's her turn to approve.")
        : say("On ", first, "'s phone, read the quote and tap ", h("b", {}, `Approve ${total}`),
          ". Optional: press Tab in her message box to ask “Can it be ready by Friday?” first.");
    case 4:
      return say("In the workshop: ", h("b", {}, story.next_step), ". Use the button in the next-step bar on the Overview tab.",
        story.status === "approved" || story.status === "awaiting_parts" ? ` The shop ordered the parts the moment ${first} approved.` : "");
    case 5:
      if (story.whose === "mechanic") {
        return say(first, " wrote to the shop. In the workshop: ", h("b", {}, story.next_step), ", then send the answer. She can pay any time.");
      }
      return say("On ", first, "'s phone, tap ", h("b", {}, `Pay ${total}`),
        ". Stripe test mode opens in a new tab: card 4242 4242 4242 4242, any future date, any CVC.");
    default:
      return story.status === "declined"
        ? say(first, " declined the quote. Click Start over to run it again.")
        : say("That's the whole story: the Agent proposed, you sent, ", first,
          " decided and paid. Open the History tab in the workshop to see who did what, or click Start over.");
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
  post(frameMechanic, mechanic);
  if (frameCustomer) post(frameCustomer, customer);
}

function post(frame, selectors) {
  try { frame.contentWindow.postMessage({ type: "mbc-cue", selectors }, location.origin); } catch { /* not loaded yet */ }
}

function showSide(who) {
  view = who;
  stage.dataset.view = who;
  for (const b of tabs.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.who === who));
  fitPhone();
}

/** Scale the phone to fit the space it has, keeping a real phone's proportions. */
function fitPhone() {
  const side = sides.customer;
  const label = side.querySelector(".side-label").offsetHeight;
  const room = { w: side.clientWidth - 32, h: side.clientHeight - label - 32 };
  if (room.w <= 0 || room.h <= 0) return;
  const scale = Math.min(1, room.w / (PHONE_W + 20), room.h / (PHONE_H + 20));
  phone.style.width = `${Math.round(PHONE_W * scale) + 20}px`;
  phone.style.height = `${Math.round(PHONE_H * scale) + 20}px`;
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
    last = { step: null, whose: null, token: undefined };
    await tick();
  } catch (e) {
    guide.textContent = `Couldn't start over: ${e.message}`;
  } finally {
    restart.disabled = false;
  }
});

boot();
