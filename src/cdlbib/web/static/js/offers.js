// The completion step that comes before a check of the changed entries and before a send, as
// in the command line (`verify` and `send` without --no-complete): for each new or changed
// entry that is not yet verified, what the sources would fill in or change, decided one
// entry at a time.
import { get, post, ApiError } from "./api.js";
import { h, clear, button, note, announce } from "./dom.js";
import { proposalList } from "./proposal.js";

export function completionStep({ log, verb }) {
  const proposals = proposalList({ verb: verb || "Completed" });
  const said = h("div", { class: "stack", "aria-live": "polite" });
  const el = h("div", { class: "stack" }, said, proposals.el);

  // Resolves true when every changed entry has been offered (or completion is unavailable, which
  // is said and does not stop what follows, as in the command line); false when the person stops.
  function run() {
    return new Promise((resolve) => {
      async function next(restart) {
        let found;
        try {
          found = await post("/api/send/offers", { restart }, log);
        } catch (error) {
          if (!(error instanceof ApiError) || error.kind === "Unreachable") { clear(said, note("bad", error.message)); resolve(false); return; }
          clear(said, note("warn", "Completion unavailable: " + error.message));
          resolve(true);
          return;
        }
        if (found.done) {
          clear(said, note("", "Completion: no more changed entries have something to offer."));
          resolve(true);
          return;
        }
        const offer = found.offer;
        clear(said, offer.error ? note("warn", offer.key + ": completion unavailable: " + offer.error)
          : h("p", { text: "Completion offered for " + offer.key + ". Decide below, then continue." }),
        h("div", { class: "row" },
          button("Continue", (event) => { event.currentTarget.disabled = true; next(false); }, { class: "primary", "data-action": "offers-continue" }),
          button("Stop here", () => { clear(said, note("", "Stopped. Nothing further was checked or sent.")); resolve(false); })));
        for (const item of offer.proposals) proposals.add(item);
        announce("Completion offered for " + offer.key);
      }
      // Is there anything to offer? (The entries that differ from the reference and are not yet accepted.)
      get("/api/send/due").then((due) => {
        if (!due.reachable) { clear(said, note("warn", "Completion unavailable: " + due.problem)); resolve(true); return; }
        if (!due.keys.length) { clear(said, note("", "Completion: no changed entry is waiting for it.")); resolve(true); return; }
        next(true);
      }, (error) => { clear(said, note("bad", error.message)); resolve(false); });
    });
  }

  return { el, run };
}
