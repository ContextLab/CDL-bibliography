// Sending: what will be sent, the completion step for the changed entries, then the one send action.
import { get, post, ApiError } from "./api.js";
import { h, clear, button, field, list, note, kv, logPane, run, announce } from "./dom.js";
import { completionStep } from "./offers.js";
import { checkResult } from "./check.js";

function link(url) {
  return /^https:\/\//.test(url) ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: url }) : h("span", { text: url });
}

export async function show(main) {
  const what = h("div", { class: "panel" });
  const log = logPane("Send log");
  const step = completionStep({ log: log.add });
  const out = h("div", { class: "stack", "aria-live": "polite" });
  const summary = h("input", { type: "text", id: "send-summary", maxlength: "100" });
  const skip = h("input", { type: "checkbox", id: "send-no-complete" });

  async function state() {
    const found = await get("/api/state");
    clear(what, h("h2", { text: "What will be sent" }),
      kv([["Library", found.root], ["Branch", found.branch || "(none)"],
        ["Files to send", found.pending === null ? null : found.pending.length ? list(found.pending) : "nothing has changed"],
        ["Left as they are", found.unrelated && found.unrelated.length ? list(found.unrelated) : null]]),
      found.notes.length ? note("warn", list(found.notes)) : null);
  }

  async function sending() {
    log.clear();
    clear(out);
    if (skip.checked) log.add("completion skipped (--no-complete)");
    else if (!(await step.run())) { await state(); return; }
    try {
      const done = await post("/api/send", { summary: summary.value.trim() || null }, log.add);
      clear(out, note("good", kv([["Pull request", link(done.url)], ["Branch", done.branch], ["Fork", done.fork + (done.created_fork ? " (created now)" : "")],
        ["Committed", done.files.length ? list(done.files) : "nothing new (the pull request was resumed)"],
        ["Left uncommitted", done.left.length ? list(done.left) : null]])));
      announce("Sent. Pull request: " + done.url);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      clear(out, note("bad", h("pre", { text: error.message })), error.data.check ? checkResult(error.data.check) : null);
      announce(error.message);
    }
    await state();
  }

  clear(main, h("div", { class: "stack" }, h("h1", { text: "Send" }), what,
    h("div", { class: "panel" }, h("h2", { text: "Send the change" }),
      h("p", { class: "muted", text: "First the completion step: for new or changed entries that are not yet verified, what the sources would fill in or change, to accept, edit or skip. Then the format check and the citation check of every new or edited entry; then cdl.bib and verification/ are committed on a branch, pushed to your fork, and the pull request is opened or updated." }),
      field("One line describing the change (optional)", summary),
      h("label", { class: "check" }, skip, " Skip the completion step (as `cdlbib send --no-complete`)"),
      h("div", { class: "row" }, button("Check and send", (event) => run(event.currentTarget, sending), { class: "primary", "data-action": "send" })),
      step.el, log.el, out)));
  await state();
}
