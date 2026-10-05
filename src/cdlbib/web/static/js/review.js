// The review queue: entries that are not verified or approved, each with its evidence.
import { get } from "./api.js";
import { h, clear, button, status, note, run, showError } from "./dom.js";
import { renderDetail } from "./detail.js";

export async function show(main, ctx) {
  let all = false;
  const queue = h("div", { class: "queue", role: "group", "aria-label": "Entries waiting for review" });
  const detail = h("section", { class: "detail panel", tabindex: "-1", "aria-label": "Entry under review" },
    h("p", { class: "muted", text: "Select an entry to see what the sources say about it." }));
  const which = h("div", { class: "row", role: "group", "aria-label": "Which entries" });

  async function open(item, control) {
    for (const other of queue.querySelectorAll("button.item")) other.setAttribute("aria-pressed", other === control ? "true" : "false");
    ctx.selected = item.key;
    await renderDetail(detail, ctx, item.key, load);
    detail.focus();
  }

  async function load() {
    clear(which,
      button("Changed entries", (event) => run(event.currentTarget, () => { all = false; return load(); }), { "aria-pressed": all ? "false" : "true" }),
      button("All entries", (event) => run(event.currentTarget, () => { all = true; return load(); }), { "aria-pressed": all ? "true" : "false" }));
    clear(queue, h("p", { class: "muted", text: "Reading the queue…" }));
    let found;
    try {
      found = await get("/api/review-queue", { all });
    } catch (error) {
      clear(queue, note("bad", h("pre", { text: error.message })));
      throw error;
    }
    clear(queue, h("p", { class: "muted", text: found.entries.length + (found.entries.length === 1 ? " entry is" : " entries are") + " not verified or approved"
      + (all ? "." : " among those that differ from the GitHub master.") }),
    found.entries.slice(0, 500).map((item) => {
      const control = button([h("strong", { class: "mono", text: item.key }), " ", status(item.status), h("div", { text: [item.authors, item.year].filter(Boolean).join(" · ") }),
        h("div", { text: item.title }), item.issues.length ? h("div", { class: "muted", text: item.issues.join("; ") }) : null],
      (event) => run(null, () => open(item, event.currentTarget)), { class: "item", "aria-pressed": "false" });
      return control;
    }),
    found.entries.length > 500 ? h("p", { class: "muted", text: "The first 500 are listed." }) : null);
  }

  clear(main, h("h1", { text: "Review queue" }),
    h("p", { class: "muted", text: "A lookup, a proposal or a model reading is evidence. An approval is recorded only by the Approve action, under this computer's GitHub login." }),
    which, h("div", { class: "two" }, queue, detail));
  await load().catch(showError);
}
