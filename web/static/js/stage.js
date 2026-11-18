// The demo stage (/demo): a visitor picks a repair story, then plays it. The workshop is at full width,
// and the Customer's phone is in a "Customer POV" overlay that opens from a tab at the bottom. A step guide says whose turn it is; the tab says
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
const picker = document.getElementById("picker");
const allBikes = document.getElementById("all-bikes");

const PHONE_W = 390;
const PHONE_H = 844;

let frameCustomer = null;
let last = { step: null, whose: null, token: undefined };
let collapseTimer = null;
let stories = [];
let current = null;  // the story being played, from sessionStorage

function storedStory() {
  try { return sessionStorage.getItem("mbc-story"); } catch { return null; }
}

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
  try { stories = await api("/api/demo/stories"); } catch { stories = []; }
  current = stories.find((s) => s.key === storedStory()) || null;
  frameMechanic.src = story.work_order_id ? `/workshop#/work-orders/${story.work_order_id}` : "/workshop#/work-orders";
  frameMechanic.addEventListener("load", () => cue(last.story));
  render(story);
  setInterval(tick, 2000);
  addEventListener("resize", fitPhone);
  povTab.addEventListener("click", () => setOpen(sheet.hidden));
  scrim.addEventListener("click", () => setOpen(false));
  addEventListener("keydown", (event) => { if (event.key === "Escape" && !sheet.hidden) setOpen(false); });
  allBikes.addEventListener("click", () => showPicker());
  if (!current) showPicker();  // first visit: pick a bike before anything else
  else allBikes.hidden = false;
}

async function tick() {
  if (document.hidden) return;
  try { render((await api("/api/demo")).story); } catch { /* the next tick will try again */ }
}

function render(story) {
  const first = (story.customer || current?.customer || "Emma Clark").split(" ")[0];
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
        : say(current ? `Press Send in the workshop: ${first}'s story is in the box. A turn takes 20 to 40 seconds.`
          : "Start with the Agent, then Send. A turn takes 20 to 40 seconds.");
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
        : say(`Open Customer POV and pay ${total} with Stripe's test card: no real money moves.`);
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
    if (current) await startStory(current);  // replay the story being played
    else {
      await api("/api/demo/reset", { method: "POST" });
      frameMechanic.src = `/workshop?fresh=${Date.now()}#/work-orders`;  // a new load, even if the address was the same
      setOpen(false);
      last = { step: null, whose: null, token: undefined };
      await tick();
    }
  } catch (e) {
    guide.textContent = `Couldn't start over: ${e.message}`;
  } finally {
    restart.disabled = false;
  }
});

// --- Picking a story ---------------------------------------------------------------

function badge(measured) {
  return measured
    ? h("span", { class: "measured" }, `Measured ${measured.passed}/${measured.runs} passed`)
    : h("span", { class: "measured pending" }, "Not measured yet");
}

function showPicker() {
  setOpen(false);
  picker.hidden = false;
  document.body.classList.add("is-picking");  // the steps, the guide and Customer POV belong to a story being played
  picker.replaceChildren(
    h("div", { class: "picker-head" },
      h("h1", { class: "display", id: "picker-title" }, "Experience a repair alongside an AI agent."),
      h("p", {}, "Pick a repair story and play both sides. As the Mechanic, watch the Agent check the bike's history, find "
        + "parts that fit and draft a quote for you to review and send. As the Customer, decide whether the repair goes "
        + "ahead, then pay. The case history shows who did what, and every story is also an automated test of the AI, "
        + "checking real outcomes like whether the quoted parts actually fit."),
      h("p", { class: "small muted" }, "Bike photos are AI-generated illustrations.")),
    h("ul", { class: "bike-grid" }, stories.map((s) => h("li", {},
      h("button", { type: "button", class: "bike-card", onclick: () => showStory(s) },
        h("span", { class: "bike-photo" }, h("img", { src: s.photo, alt: "" })),
        h("span", { class: "bike-body" },
          h("span", { class: "bike-top" }, h("span", { class: "bike-kind" }, s.label), h("span", { class: "tag" }, groupLabel(s.group))),
          h("span", { class: "bike-who" }, `${s.bike} · ${s.customer}`),
          h("span", { class: "bike-quote" }, `“${s.complaint}”`),
          badge(s.measured)))))));
  picker.querySelector(".bike-card")?.focus();
}

function groupLabel(group) {
  return { story: "The hero story", compatibility: "Compatibility", diagnosis: "Diagnosis",
    guardrails: "Guardrails", procurement: "Procurement" }[group] || group;
}

function showStory(s) {
  const first = s.customer.split(" ")[0];
  const start = h("button", { type: "button", class: "btn btn-big start-story", onclick: () => {
    start.disabled = true;
    status.textContent = "Setting up the shop…";
    startStory(s).catch((e) => {
      start.disabled = false;
      status.textContent = `Couldn't start: ${e.message}`;
    });
  } }, "Start this story");
  const status = h("span", { class: "small", role: "status" });
  picker.replaceChildren(h("div", { class: "story-card" },
    h("div", { class: "story-photo" },
      h("img", { src: s.photo, alt: s.title }),
      h("span", { class: "small muted" }, "Illustrative photo (AI-generated)")),
    h("div", { class: "story-text" },
      h("button", { type: "button", class: "linkish", onclick: () => showPicker() }, "← All bikes"),
      h("span", { class: "tag" }, groupLabel(s.group)),
      h("h1", { class: "display", id: "picker-title" }, s.title),
      h("p", { class: "muted", style: "margin: 0" }, `${s.bike} · ${s.customer}`),
      h("div", { class: "story-block" }, h("span", { class: "lbl" }, "Why it's in"), h("p", { class: "bike-quote" }, `“${s.complaint}”`)),
      h("div", { class: "story-block" }, h("span", { class: "lbl" }, "The bike"),
        h("table", { class: "story-profile" }, h("tbody", {}, s.profile.map(([label, value, differs]) => h("tr", {},
          h("th", { scope: "row" }, label),
          h("td", {}, value, differs ? h("strong", { class: "differs" }, " · worth a closer look") : null)))))),
      h("div", { class: "story-block watch" }, h("span", { class: "lbl" }, "What to watch for"),
        h("p", { class: "watch-q" }, s.watch_for), h("p", { class: "muted small" }, s.watch_detail)),
      h("div", { class: "story-start" }, start, badge(s.measured),
        h("span", { class: "small muted" }, "Each Agent turn takes about 30 seconds and costs a few cents."), status))));
  start.focus();
}

async function startStory(s) {
  const started = await api(`/api/demo/stories/${s.key}/start`, { method: "POST" });
  current = s;
  try {
    sessionStorage.setItem("mbc-story", s.key);
    sessionStorage.setItem("mbc-story-message", started.message);  // the workshop's Agent tab picks it up
  } catch { /* private mode */ }
  picker.hidden = true;
  document.body.classList.remove("is-picking");
  allBikes.hidden = false;
  setOpen(false);
  frameMechanic.src = `/workshop?fresh=${Date.now()}#/agent`;  // a new conversation with the story's message ready
  last = { step: null, whose: null, token: undefined };
  await tick();
}

boot();
