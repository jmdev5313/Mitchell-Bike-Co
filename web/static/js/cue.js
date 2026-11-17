// Inside the demo stage (/demo), the stage tells this page which control comes next, and that
// control gets a ring. Outside the stage, or from any other window, it does nothing.

if (window.parent !== window) {
  let selectors = [];
  let queued = false;
  const apply = () => {
    queued = false;
    for (const el of document.querySelectorAll(".cue")) el.classList.remove("cue");
    for (const selector of selectors) {
      for (const el of document.querySelectorAll(selector)) el.classList.add("cue");
    }
  };
  window.addEventListener("message", (event) => {
    if (event.origin !== location.origin || event.source !== window.parent) return;
    if (!event.data || event.data.type !== "mbc-cue" || !Array.isArray(event.data.selectors)) return;
    selectors = event.data.selectors.filter((s) => typeof s === "string");
    apply();
  });
  // Pages redraw themselves; put the ring back on the new elements.
  new MutationObserver(() => {
    if (!queued) { queued = true; requestAnimationFrame(apply); }
  }).observe(document.documentElement, { childList: true, subtree: true });
}
