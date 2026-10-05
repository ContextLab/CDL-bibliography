// Sending: what will be sent, completion offers for the changed entries, then the one send action.
import { get, post, ApiError } from "./api.js";
import { h, clear, button, field, list, note, kv, logPane, run, announce } from "./dom.js";
import { proposalList } from "./proposal.js";
import { checkResult } from "./check.js";

function link(url) {
  return /^https:\/\//.test(url) ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: url }) : h("span", { text: url });
}

export async function show(main, ctx) {
  const what = h("div", { class: "panel" });
  const offers = h("div", { class: "stack" });
  const proposals = proposalList({ verb: "Completed" });
  const log = logPane("Send log");
  const out = h("div", { class: "stack", "aria-live": "polite" });
  const summary = h("input", { type: "text", id: "send-summary", maxlength: "100" });

  async function state() {
    const found = await get("/api/state");
    clear(what, h("h2", { text: "What will be sent" }),
      kv([["Library", found.root], ["Branch", found.branch || "(none)"],
        ["Files to send", found.pending === null ? null : found.pending.length ? list(found.pending) : "nothing has changed"],
        ["Left as they are", found.unrelated && found.unrelated.length ? list(found.unrelated) : null]]),
      found.notes.length ? note("warn", list(found.notes)) : null);
  }

  async function next(restart) {
    const found = await post("/api/send/offers", { restart }, log.add);
    if (found.done) {
      clear(offers, note("", "No more changed entries have a completion to offer."));
      return;
    }
    const offer = found.offer;
    clear(offers, offer.error ? note("warn", offer.key + ": completion unavailable: " + offer.error) : h("p", { text: "Completion offered for " + offer.key + ":" }),
      button("Next entry", (event) => run(event.currentTarget, () => next(false))));
    for (const item of offer.proposals) proposals.add(item);
    announce("Completion offered for " + offer.key);
  }

  async function sending() {
    log.clear();
    clear(out);
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
    h("div", { class: "panel" }, h("h2", { text: "Completion offers" }),
      h("p", { class: "muted", text: "For new or changed entries that are not yet verified: what the sources would fill in or change. Nothing is written unless accepted." }),
      h("div", { class: "row" }, button("Look for completions", (event) => run(event.currentTarget, () => next(true)))), offers, proposals.el),
    h("div", { class: "panel" }, h("h2", { text: "Send the change" }),
      h("p", { class: "muted", text: "Runs the format check and the citation check of every new or edited entry, then commits cdl.bib and verification/ on a branch, pushes it to your fork and opens or updates the pull request." }),
      field("One line describing the change (optional)", summary),
      h("div", { class: "row" }, button("Check and send", (event) => run(event.currentTarget, sending), { class: "primary" })),
      h("h3", { text: "Log" }), log.el, out)));
  await state();
}
