// The state of the library: where it is, what is unsent, what the upstream has, updates, backups, undo.
import { get, post, ApiError } from "./api.js";
import { h, clear, button, list, table, note, kv, logPane, run, ask, info, announce, add } from "./dom.js";

function count(n, one, many) {
  return n + " " + (n === 1 ? one : many);
}

// The question about unsent changes (the core's wording), and what follows from the answer.
// Returns what the update did, or null when the person chose nothing.
export async function decide(error, ctx, onLine) {
  const said = await ask({ title: "Unsent changes", body: error.data.question,
    choices: error.data.choices.map((choice) => ({ value: choice, label: error.data.answers[choice], kind: choice === "discard" ? "danger" : "" })) });
  if (!said) { info("Nothing was changed."); return null; }
  const done = await post("/api/update/decide", { decision: error.data.decision, choice: said.choice }, onLine);
  info([done.message].concat(done.notes || []).filter(Boolean).join("\n") || "Nothing to do.");
  if (done.decision === "send") ctx.go("send");
  return done;
}

export async function show(main, ctx) {
  const where = h("div", { class: "panel" });
  const banner = h("div");
  const saved = h("div", { class: "panel" });
  const owed = h("div");

  // Model evidence that could not be stored when its entry was written: kept until it is.
  async function evidence() {
    const found = (await get("/api/evidence/pending")).pending;
    clear(owed);
    if (!found.length) return;
    add(owed, h("div", { class: "panel", id: "pending-evidence" }, h("h2", { text: "Model evidence not yet stored" }),
      table(["Entry", "", ""], found.map((item) => [h("span", { class: "mono", text: item.key }),
        item.stale ? "The entry has changed since the model read it; this evidence can no longer be stored with it." : "Written; the evidence of the model reading waits to be stored (it is not an approval).",
        item.stale ? "" : button("Retry", (event) => run(event.currentTarget, async () => {
          const done = await post("/api/evidence/retry", { key: item.key }, log.add);
          info(done.evidence_stored ? "The evidence was stored with " + done.key + "." : done.evidence_error);
          await evidence();
        }), { "aria-label": "Retry storing the evidence of " + item.key })]))));
  }
  const log = logPane("Update log");

  function draw(found) {
    clear(banner);
    if (found.not_managed) add(banner, note("", found.not_managed));
    if (found.managed && found.new_commits) {
      add(banner, note("warn", h("div", { class: "banner" },
        h("strong", { text: "A newer version of the bibliography is available: " + count(found.new_commits, "new commit", "new commits")
          + (found.new_entries ? ", " + count(found.new_entries, "new entry", "new entries") : "") + "." }),
        button("Update now", (event) => run(event.currentTarget, updating), { class: "primary" }))));
    }
    if (found.interrupted) add(banner, note("bad", "A write or update did not finish. The state from before it: " + found.interrupted));
    const pr = found.pull_request;
    const approvals = found.approvals || [];
    clear(where, h("h2", { text: "This library" }), kv([
      ["Folder", found.root], ["Chosen by", ctx.session.chosen_by[found.origin] || found.origin],
      ["Managed by cdlbib", found.managed ? "yes" : "no"], ["Branch", found.branch],
      ["Unsent changes", found.pending === null ? null : found.pending.length ? list(found.pending) : approvals.length ? null : "none"],
      ["Unsent approvals", approvals.length ? list(approvals.map((item) => `${item.key} (@${item.login})`)) : null],
      ["Other changed files", found.unrelated && found.unrelated.length ? list(found.unrelated) : null],
      ["New upstream commits", found.new_commits === null ? null : String(found.new_commits) + (found.refreshed ? " (asked just now)" : " (as last fetched)")],
      ["New upstream entries", found.new_entries === null ? null : String(found.new_entries)],
      ["Commits the upstream lacks", found.local_commits === null ? null : String(found.local_commits)],
      ["Last update check", found.managed ? found.last_check_text : null],
      ["Pull request", pr ? pr.url + " (" + pr.state + ")" : null],
    ]), found.notes.length ? note("", list(found.notes)) : null,
    h("div", { class: "row" },
      button("Ask the upstream now", (event) => run(event.currentTarget, async () => { draw(await post("/api/state/refresh", {}, log.add)); announce("State refreshed."); })),
      found.managed && !found.new_commits ? button("Update the library now", (event) => run(event.currentTarget, updating), { "data-action": "update" }) : null,
      (found.pending && found.pending.length) || approvals.length ? button("Go to Send", () => ctx.go("send")) : null));
  }

  function outcome(done) {
    info([done.message].concat(done.notes || []).filter(Boolean).join("\n") || "Nothing to do.");
  }

  async function updating() {
    log.clear();
    try {
      outcome(await post("/api/update", {}, log.add));
    } catch (error) {
      if (!(error instanceof ApiError) || error.kind !== "UpdateNeedsDecision") throw error;
      const done = await decide(error, ctx, log.add);
      if (!done || done.decision === "send") return;
    }
    await load();
  }

  async function restore(stamp) {
    const said = await ask({ title: stamp ? "Restore backup " + stamp + "?" : "Undo the last change?",
      body: "The library is put back as it was at that backup. Its present state is backed up first, so this can be undone the same way.",
      confirm: "Restore", danger: true });
    if (!said) return;
    const done = await post("/api/undo", { stamp: stamp || null }, log.add);
    info(["restored backup " + done.restored.stamp + " (" + done.restored.when + ")",
      "the library as it was just before is backup " + done.before.stamp]
      .concat(done.taken_off.map(([branch, commit]) => "branch " + branch + " was on commit " + commit + ", which backup " + done.before.stamp + " keeps"))
      .concat(done.notes).join("\n"));
    await load();
  }

  async function backups(state) {
    clear(saved, h("h2", { text: "Backups and undo" }));
    if (!state.managed) {       // backups and undo belong to the library cdlbib manages, and this is not it
      add(saved, h("p", { class: "muted", text: state.not_managed }));
      return;
    }
    let found;
    try {
      found = await get("/api/backups");
    } catch (error) {
      add(saved, h("p", { class: "muted", text: error.message }));
      return;
    }
    add(saved, h("p", { class: "muted", text: count(found.backups.length, "backup", "backups") + " of " + found.root + ", newest first (kept in " + found.folder + ")." }));
    if (found.checkpoint) add(saved, h("p", { text: "Undo restores the command checkpoint " + found.checkpoint + "." }));
    if (found.backups.length) {
      add(saved, h("div", { class: "row" }, button("Undo the last change", (event) => run(event.currentTarget, () => restore(null)))),
        table(["Backup", "Taken", "State", ""], found.backups.map((b) => [h("span", { class: "mono", text: b.stamp }), b.when,
          b.line,
          button("Restore", (event) => run(event.currentTarget, () => restore(b.stamp)), { "aria-label": "Restore backup " + b.stamp })])));
    }
    if (found.unreadable.length) add(saved, note("warn", list(found.unreadable.map(([stamp, why]) => stamp + ": unreadable (" + why + ")"))));
  }

  async function load() {
    const found = await get("/api/state");
    draw(found);
    await evidence();
    await backups(found);
  }

  clear(main, h("div", { class: "stack" }, h("h1", { text: "Library state" }), banner, where, owed, saved,
    log.el));
  await load();
}
