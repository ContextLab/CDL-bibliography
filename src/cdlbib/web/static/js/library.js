// The library: search, a table that draws only the rows in view, and the selected entry.
import { get } from "./api.js";
import { h, clear, button, field, words, showError, announce } from "./dom.js";
import { renderDetail } from "./detail.js";

const ROW = 30;          // pixels; the style sheet's --row is set from this
const SPARE = 12;        // rows drawn beyond each edge of the view
const COLUMNS = [["status", "Status"], ["key", "Key"], ["authors", "Authors"], ["year", "Year"], ["title", "Title"], ["venue", "Venue"]];
const MARKS = { metadata_verified: "●", human_verified: "●", needs_review: "▲", pending: "○" };
const [KEY, , AUTHORS, YEAR, TITLE, VENUE, , STATUS] = [0, 1, 2, 3, 4, 5, 6, 7];

export async function show(main, ctx) {
  let rows = [];
  let revision = null;
  let at = new Map();          // key -> index in rows
  let shown = [];              // indices of the rows that match
  let chosen = -1;             // position in `shown`
  let asked = 0;
  let filter = "";

  const search = h("input", { type: "search", id: "search", placeholder: "words, or field:word (key, author, title, venue, year, doi, type, status)", autocomplete: "off", spellcheck: "false" });
  const counts = h("div", { class: "counts", role: "group", "aria-label": "Entries by status" });
  const summary = h("span", { class: "muted", id: "match-count", "aria-live": "polite" });
  const body = h("div", { class: "vt-rows", role: "presentation" });
  const space = h("div", { role: "presentation" }, body);
  const scroll = h("div", { class: "vt-scroll", tabindex: "0", role: "grid", "aria-label": "Entries", "aria-describedby": "match-count" }, space);
  // The headings are for the eye; each row carries its own spoken label, since rows come and go as the list scrolls.
  const head = h("div", { class: "vt-head", "aria-hidden": "true" }, COLUMNS.map(([name, label]) => h("span", { class: "c-" + name, text: label })));
  const detail = h("section", { class: "detail panel", "aria-label": "Selected entry" }, h("p", { class: "muted", text: "Select an entry to see its text, issues and evidence." }));
  scroll.style.setProperty("--row", ROW + "px");

  function draw() {
    const first = Math.max(0, Math.floor(scroll.scrollTop / ROW) - SPARE);
    const last = Math.min(shown.length, Math.ceil((scroll.scrollTop + scroll.clientHeight) / ROW) + SPARE);
    body.style.transform = "translateY(" + first * ROW + "px)";
    const made = [];
    for (let position = first; position < last; position += 1) {
      const row = rows[shown[position]];
      made.push(h("div", { class: "vt-row", role: "row", id: "row-" + position, "aria-rowindex": position + 1, "aria-selected": position === chosen ? "true" : "false", "data-position": position,
        "aria-label": [row[KEY], words(row[STATUS]), row[AUTHORS], row[YEAR], row[TITLE], row[VENUE]].filter(Boolean).join(", ") },
        h("span", { class: "c-status st st-" + row[STATUS], role: "gridcell", text: words(row[STATUS]) }),
        h("span", { class: "c-key mono", role: "gridcell", "data-mark": MARKS[row[STATUS]] || "✕", text: row[KEY] }),
        h("span", { class: "c-authors", role: "gridcell", text: row[AUTHORS] }),
        h("span", { class: "c-year", role: "gridcell", text: row[YEAR] }),
        h("span", { class: "c-title", role: "gridcell", text: row[TITLE] }),
        h("span", { class: "c-venue", role: "gridcell", text: row[VENUE] })));
    }
    body.replaceChildren(...made);
    if (chosen >= first && chosen < last) scroll.setAttribute("aria-activedescendant", "row-" + chosen);
    else scroll.removeAttribute("aria-activedescendant");
  }

  let pending = false;
  function later() {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(() => { pending = false; draw(); });
  }

  function lay() {
    space.style.height = shown.length * ROW + "px";
    scroll.setAttribute("aria-rowcount", String(shown.length));
    summary.textContent = shown.length === rows.length ? rows.length + " entries" : shown.length + " of " + rows.length + " entries";
    draw();
  }

  async function open(position, focus) {
    if (position < 0 || position >= shown.length) return;
    chosen = position;
    const top = position * ROW;
    if (top < scroll.scrollTop) scroll.scrollTop = top;
    else if (top + ROW > scroll.scrollTop + scroll.clientHeight) scroll.scrollTop = top + ROW - scroll.clientHeight;
    draw();
    const key = rows[shown[position]][KEY];
    ctx.selected = key;
    try {
      await renderDetail(detail, ctx, key, load);
      if (focus) detail.focus();
    } catch (error) { showError(error); }
  }

  async function match() {
    const mine = ++asked;
    const q = search.value.trim();
    if (!q && !filter) {
      shown = rows.map((_, index) => index);
    } else {
      const found = await get("/api/search", { q, status: filter });
      if (mine !== asked) return;
      if (found.revision !== revision) { await load(); return; }
      shown = found.keys.map((key) => at.get(key)).filter((index) => index !== undefined);
    }
    chosen = ctx.selected ? shown.indexOf(at.get(ctx.selected)) : -1;
    space.style.height = shown.length * ROW + "px";
    scroll.scrollTop = chosen >= 0 ? Math.max(0, chosen * ROW - scroll.clientHeight / 2 + ROW) : 0;
    lay();
  }

  async function load() {
    const found = await get("/api/entries");
    rows = found.rows;
    revision = found.revision;
    at = new Map(rows.map((row, index) => [row[KEY], index]));
    clear(counts, button("all " + rows.length, () => { filter = ""; press(); match().catch(showError); }, { "aria-pressed": filter === "" ? "true" : "false", "data-status": "" }),
      Object.entries(found.counts).sort().map(([name, count]) => button(words(name) + " " + count, () => { filter = name; press(); match().catch(showError); },
        { "aria-pressed": filter === name ? "true" : "false", "data-status": name })));
    await match();
  }

  function press() {
    for (const item of counts.querySelectorAll("button")) item.setAttribute("aria-pressed", item.dataset.status === filter ? "true" : "false");
  }

  let timer = null;
  search.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => match().catch(showError), 180);
  });
  scroll.addEventListener("scroll", later, { passive: true });
  scroll.addEventListener("click", (event) => {
    const row = event.target.closest(".vt-row");
    if (row) open(Number(row.dataset.position));
  });
  scroll.addEventListener("keydown", (event) => {
    const page = Math.max(1, Math.floor(scroll.clientHeight / ROW) - 1);
    const to = { ArrowDown: chosen + 1, ArrowUp: chosen - 1, PageDown: chosen + page, PageUp: chosen - page, Home: 0, End: shown.length - 1 }[event.key];
    if (event.key === "Enter" && chosen >= 0) { event.preventDefault(); detail.focus(); return; }
    if (to === undefined) return;
    event.preventDefault();
    open(Math.max(0, Math.min(shown.length - 1, to)));
  });
  const resized = new ResizeObserver(later);
  resized.observe(scroll);
  const focused = async () => {
    if (!scroll.isConnected) { window.removeEventListener("focus", focused); resized.disconnect(); return; }
    try {
      const now = await get("/api/revision");
      if (now.revision !== revision) { await load(); announce("The library changed on disk; the list was read again."); }
    } catch (error) { /* shown on the next action */ }
  };
  window.addEventListener("focus", focused);

  detail.tabIndex = -1;
  clear(main, h("div", { class: "library" },
    h("section", { "aria-label": "Entries" },
      h("div", { class: "row" }, h("div", { class: "grow" }, field("Search the library", search)),
        button("New entry", () => ctx.go("edit"))),
      counts, h("div", { class: "row" }, summary),
      h("div", { class: "vt" }, head, scroll)),
    detail));
  await load();
  if (chosen >= 0) open(chosen);
}
