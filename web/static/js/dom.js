// Small helpers shared by the pages. Text from the API (messages, names) is
// always set as text, never parsed as HTML.

/** Build an element: h("p", {class: "x", onclick: fn}, "text", child, ...). */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) {
      el.setAttribute(key, "");
    } else {
      el.setAttribute(key, String(value));
    }
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** Inline stroke icon from a path, hidden from screen readers. */
export function icon(path, size = 16, strokeWidth = 2.2) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", strokeWidth);
  svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", path);
  svg.append(p);
  return svg;
}

export const CHECK = "M2.5 8.5l3.5 3.5 7.5-8";
export const LOCK = "M4 7h8v7H4zM6 7V5a2 2 0 014 0v2";

/** $169.98 from 16998. Money is integer cents everywhere. */
export function dollars(cents) {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  return `${sign}$${Math.floor(abs / 100).toLocaleString("en-US")}.${String(abs % 100).padStart(2, "0")}`;
}

/** "Nov 19" from an ISO date or timestamp, in the viewer's time zone for timestamps. */
export function shortDate(value) {
  if (!value) return "";
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00`) : new Date(value.replace(" ", "T") + (/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? "" : "Z"));
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** "Thursday, Nov 19" from an ISO date. */
export function longDate(value) {
  if (!value) return "";
  const date = new Date(`${value}T12:00:00`);
  return date.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
}

/** fetch() that returns parsed JSON, or throws an Error carrying the API's reason. */
export async function api(path, { method = "GET", body, headers = {} } = {}) {
  const options = { method, headers: { ...headers } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let data = null;
  try { data = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) {
    const error = new Error((data && data.detail) || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}
