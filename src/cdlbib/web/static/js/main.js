// Start-up: the token, the views, the theme, the login shown in the header.
import { setToken, hasToken, get, post, follow } from "./api.js";
import { h, clear, button, announce, showError, run, ask, note } from "./dom.js";
import * as library from "./library.js";
import * as edit from "./edit.js";
import * as check from "./check.js";
import * as review from "./review.js";
import * as addView from "./add.js";
import * as sendView from "./send.js";
import * as stateView from "./state.js";
import * as setup from "./setup.js";

const VIEWS = [
  ["library", "Library", library], ["check", "Check", check], ["review", "Review", review], ["add", "Add", addView],
  ["send", "Send", sendView], ["state", "Library state", stateView], ["setup", "Setup", setup],
];
const HIDDEN = { edit };
const THEMES = ["system", "light", "dark"];

const main = document.getElementById("main");
const ctx = {
  session: null,
  selected: null,         // the key selected in the library
  guard: null,            // a view's "there is unsaved text" test
  go(route) { window.location.hash = "#/" + route; },
  identity() { return ctx.session && ctx.session.identity; },
  showIdentity,
};

function readToken() {
  const found = /^#token=([A-Za-z0-9_-]{20,})$/.exec(window.location.hash);
  if (!found) return false;
  setToken(found[1]);
  window.history.replaceState(null, "", window.location.pathname);
  return true;
}

function showIdentity(found) {
  if (found) ctx.session.identity = found;
  const known = ctx.identity();
  const el = document.getElementById("identity");
  if (!known || known.available === null) el.textContent = "GitHub: not checked";
  else if (known.available) el.textContent = "GitHub: " + known.detail;
  else el.textContent = "GitHub: no login";
  el.title = known && !known.available ? [known.detail, known.how].filter(Boolean).join(" ") : "";
}

function theme(name) {
  const root = document.documentElement;
  if (name === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", name);
  const toggle = document.getElementById("theme-toggle");
  toggle.textContent = "Theme: " + name;
  toggle.setAttribute("aria-label", "Colour theme: " + name + ". Activate to change.");
  try { window.localStorage.setItem("cdlbib-theme", name); } catch (error) { /* the choice lasts for this page only */ }
}

function storedTheme() {
  try {
    const name = window.localStorage.getItem("cdlbib-theme");
    return THEMES.includes(name) ? name : "system";
  } catch (error) { return "system"; }
}

function route() {
  const found = /^#\/([a-z]+)(?:\/(.*))?$/.exec(window.location.hash);
  return found ? [found[1], found[2] ? decodeURIComponent(found[2]) : null] : ["library", null];
}

let shown = null;

async function show() {
  const [name, param] = route();
  const view = (VIEWS.find((item) => item[0] === name) || [])[2] || HIDDEN[name] || library;
  if (ctx.guard && ctx.guard()) {
    const leave = await ask({ title: "Leave without saving?", body: "The text you edited has not been saved.", confirm: "Leave", danger: true });
    if (!leave) { window.history.replaceState(null, "", shown || "#/library"); return; }
  }
  ctx.guard = null;
  shown = window.location.hash;
  for (const item of document.querySelectorAll("#nav button")) {
    if (item.dataset.view === name) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  clear(main);
  try {
    await view.show(main, ctx, param);
  } catch (error) {
    clear(main, note("bad", h("pre", { text: error.message || String(error) })));
    showError(error);
  }
}

async function start() {
  theme(storedTheme());
  document.getElementById("theme-toggle").addEventListener("click", () => {
    theme(THEMES[(THEMES.indexOf(storedThemeNow()) + 1) % THEMES.length]);
  });
  document.getElementById("skip").addEventListener("click", () => main.focus());
  if (!readToken() && !hasToken()) {
    clear(main, h("div", { class: "panel" }, h("h1", { text: "This page needs its key" }),
      h("p", { text: "Open the address that `cdlbib web` printed in the terminal. It carries the key of that run, and this page does not keep it after it is closed or reloaded." })));
    return;
  }
  ctx.session = await get("/api/session");
  const parts = ctx.session.root.split("/").filter(Boolean);
  document.getElementById("library-path").textContent = (parts.length > 2 ? "…/" : "/") + parts.slice(-2).join("/");
  document.getElementById("library-path").title = ctx.session.bib;
  const nav = document.getElementById("nav");
  for (const [name, label] of VIEWS) nav.append(button(label, () => ctx.go(name), { "data-view": name }));
  showIdentity();
  const checker = document.getElementById("identity-check");
  checker.addEventListener("click", () => run(checker, async () => {
    showIdentity(await post("/api/identity/check"));
    announce(document.getElementById("identity").textContent);
  }));
  window.addEventListener("hashchange", show);
  window.addEventListener("beforeunload", (event) => { if (ctx.guard && ctx.guard()) event.preventDefault(); });
  if (ctx.session.prepare) {
    clear(main, h("p", { class: "muted", text: "Reading the library…" }));
    const activity = document.getElementById("activity");
    try { await follow(ctx.session.prepare, (line) => { activity.classList.add("on"); activity.textContent = line; }); } catch (error) { showError(error); }
    activity.classList.remove("on");
    activity.textContent = "";
  }
  if (!/^#\//.test(window.location.hash)) window.history.replaceState(null, "", "#/library");
  await show();
}

function storedThemeNow() {
  return document.documentElement.getAttribute("data-theme") || "system";
}

start().catch((error) => {
  clear(main, note("bad", h("pre", { text: error.message || String(error) })));
});
