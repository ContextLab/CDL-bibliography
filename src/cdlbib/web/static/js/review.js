// The review queue: entries that are not verified or approved, each with its evidence.
// The whole queue is reachable: it is searched with the library's search syntax and paged.
import { get } from "./api.js";
import { h, clear, button, field, status, note, run, showError, announce } from "./dom.js";
import { renderDetail } from "./detail.js";

const PAGE = 100;

export async function show(main, ctx) {
  let all = false;
  let offset = 0;
  let revision = null;
  let chosen = null;           // the key whose detail is shown
  let asked = 0;
  const search = h("input", { type: "search", id: "review-search", autocomplete: "off", spellcheck: "false",
    placeholder: "words, or field:word (key, author, title, venue, year, doi, type, status)" });
  const queue = h("div", { class: "queue", role: "group", "aria-label": "Entries waiting for review" });
  const pager = h("div", { class: "row", role: "group", "aria-label": "Pages of the queue" });
  const detail = h("section", { class: "detail panel", tabindex: "-1", "aria-label": "Entry under review" },
    h("p", { class: "muted", text: "Select an entry to see what the sources say about it." }));
  const which = h("div", { class: "row", role: "group", "aria-label": "Which entries" });

  async function open(key, focus) {
    chosen = key;
    for (const other of queue.querySelectorAll("button.item")) other.setAttribute("aria-pressed", other.dataset.key === key ? "true" : "false");
    ctx.selected = key;
    await renderDetail(detail, ctx, key, load);
    if (focus) detail.focus();
  }

  async function load() {
    const mine = ++asked;
    clear(which,
      button("Changed entries", (event) => run(event.currentTarget, () => { all = false; offset = 0; return load(); }), { "aria-pressed": all ? "false" : "true" }),
      button("All entries", (event) => run(event.currentTarget, () => { all = true; offset = 0; return load(); }), { "aria-pressed": all ? "true" : "false" }));
    let found;
    try {
      found = await get("/api/review-queue", { all, q: search.value.trim(), offset, limit: PAGE });
    } catch (error) {
      if (mine === asked) { clear(queue, note("bad", h("pre", { text: error.message }))); clear(pager); }
      throw error;
    }
    if (mine !== asked) return;
    if (found.total && offset >= found.total) { offset = Math.max(0, Math.floor((found.total - 1) / PAGE) * PAGE); await load(); return; }
    revision = found.revision;
    const first = found.total ? offset + 1 : 0;
    clear(queue, h("p", { class: "muted", id: "review-count", text: found.total + (found.total === 1 ? " entry is" : " entries are") + " not verified or approved"
      + (all ? "" : " among those that differ from the GitHub master") + (search.value.trim() ? ", matching the search" : "") + "."
      + (found.total > PAGE ? " Showing " + first + " to " + (offset + found.entries.length) + "." : "") }),
    found.entries.map((item) => button([h("strong", { class: "mono", text: item.key }), " ", status(item.status),
      h("div", { text: [item.authors, item.year].filter(Boolean).join(" · ") }),
      h("div", { text: item.title }), item.issues.length ? h("div", { class: "muted", text: item.issues.join("; ") }) : null],
    () => run(null, () => open(item.key, true)), { class: "item", "data-key": item.key, "aria-pressed": item.key === chosen ? "true" : "false" })));
    clear(pager, found.total > PAGE ? [
      button("Previous " + PAGE, (event) => run(event.currentTarget, () => { offset = Math.max(0, offset - PAGE); return load(); }), { disabled: offset === 0 }),
      button("Next " + PAGE, (event) => run(event.currentTarget, () => { offset += PAGE; return load(); }), { disabled: offset + PAGE >= found.total }),
    ] : null);
  }

  let timer = null;
  search.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { offset = 0; load().catch(showError); }, 200);
  });
  // When the library changed on disk (another window, another program), the queue and the entry shown are read again.
  const focused = async () => {
    if (!queue.isConnected) { window.removeEventListener("focus", focused); return; }
    try {
      const now = await get("/api/revision");
      if (revision !== null && now.revision !== revision) {
        await load();
        if (chosen) await renderDetail(detail, ctx, chosen, load);
        announce("The library changed on disk; the queue was read again.");
      }
    } catch (error) { /* shown on the next action */ }
  };
  window.addEventListener("focus", focused);

  clear(main, h("h1", { text: "Review queue" }),
    h("p", { class: "muted", text: "A lookup, a proposal or a model reading is evidence. An approval is recorded only by the Approve action, under this computer's GitHub login." }),
    which, field("Search the queue", search), h("div", { class: "two" }, h("div", null, queue, pager), detail));
  await load().catch(showError);
}
