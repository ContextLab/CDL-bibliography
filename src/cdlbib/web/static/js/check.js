// Checks: chosen entries, the changed entries, or the house format alone; the log as it runs.
import { post } from "./api.js";
import { h, clear, button, field, list, table, note, status, logPane, run, announce } from "./dom.js";
import { completionStep } from "./offers.js";

function corrections(found) {
  const rows = [];
  for (const [key, fields] of Object.entries(found.corrections || {})) {
    for (const [name, value] of Object.entries(fields)) rows.push([key, name === "ID" ? "key" : name, value === null ? "(removed)" : String(value)]);
  }
  return rows;
}

export function formatResult(found) {
  const parts = [note(found.ok ? "good" : "bad", found.ok ? "format: looks good!" : (found.failure ? "errors found: " + found.failure : "errors found in " + found.errors.length + " entr" + (found.errors.length === 1 ? "y" : "ies")))];
  if (found.forced && found.forced.length) parts.push(note("bad", list(found.forced)));
  const rows = corrections(found);
  if (rows.length) parts.push(table(["Entry", "Field", "House format"], rows.slice(0, 500)), rows.length > 500 ? h("p", { class: "muted", text: "… and " + (rows.length - 500) + " more." }) : null);
  if (found.log) parts.push(h("details", null, h("summary", { text: "The format check's log" }), h("pre", { class: "mono log", text: found.log })));
  return parts;
}

export function checkResult(found) {
  const parts = [note(found.ok ? "good" : "bad", found.ok ? "looks good!" : "Not every checked entry passed."), formatResult(found.format)];
  if (found.citations) {
    const checked = Object.entries(found.citations.checked);
    if (checked.length) {
      parts.push(h("h3", { text: "Entries checked" }), table(["Entry", "Status", "Issues"], checked.map(([key, item]) => [key, status(item.status),
        item.issues.length ? list(item.issues) : ""])));
    }
  } else if (!found.citations_due) {
    parts.push(h("p", { class: "muted", text: "Citations were not checked." }));
  }
  return parts;
}

export async function show(main, ctx) {
  const keys = h("input", { type: "text", id: "check-keys", spellcheck: "false", autocomplete: "off" });
  keys.value = ctx.selected || "";
  const log = logPane("Check log");
  const out = h("section", { "aria-label": "Result", "aria-live": "polite" });
  const step = completionStep({ log: log.add });
  const skip = h("input", { type: "checkbox", id: "check-no-complete" });

  // The changed entries: the completion step first, as `cdlbib verify` does, unless it is skipped.
  async function changed() {
    log.clear();
    clear(out);
    if (skip.checked) log.add("completion skipped (--no-complete)");
    else if (!(await step.run())) return;
    await go("/api/check/changed", {}, checkResult, true);
  }

  async function go(path, body, render, keep) {
    if (!keep) log.clear();
    clear(out);
    const found = await post(path, body, log.add);
    clear(out, h("h2", { text: "Result" }), render(found));
    announce("Check finished.");
  }

  clear(main, h("div", { class: "stack" },
    h("h1", { text: "Check" }),
    h("div", { class: "panel" },
      field("Entries to check (keys, separated by spaces or commas)", keys),
      h("div", { class: "row" },
        button("Check these entries", (event) => run(event.currentTarget, () => go("/api/check/keys",
          { keys: keys.value.split(/[\s,]+/).filter(Boolean) }, checkResult)), { class: "primary" }),
        button("Check the changed entries", (event) => run(event.currentTarget, changed), { "data-action": "check-changed" }),
        button("Format check only", (event) => run(event.currentTarget, () => go("/api/check/format", {}, formatResult)))),
      h("label", { class: "check" }, skip, " Skip the completion step before checking the changed entries (as `cdlbib verify --no-complete`)")),
    step.el, h("h2", { text: "Log" }), log.el, out));
}
