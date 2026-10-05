// The state of the library: where it is, what is unsent, what the upstream has, updates, backups, undo.
import { get, post, ApiError } from "./api.js";
import { h, clear, button, list, table, note, kv, logPane, run, ask, info, announce } from "./dom.js";

function count(n, one, many) {
  return n + " " + (n === 1 ? one : many);
}

export async function show(main, ctx) {
  const where = h("div", { class: "panel" });
  const banner = h("div");
  const saved = h("div", { class: "panel" });
  const log = logPane("Update log");

  function draw(found) {
    clear(banner);
    if (found.new_commits) {
      banner.append(note("warn", h("div", { class: "banner" },
        h("strong", { text: "A newer version of the bibliography is available: " + count(found.new_commits, "new commit", "new commits")
          + (found.new_entries ? ", " + count(found.new_entries, "new entry", "new entries") : "") + "." }),
        button("Update now", (event) => run(event.currentTarget, updating), { class: "primary" }))));
    }
    if (found.interrupted) banner.append(note("bad", "A write or update did not finish. The state from before it: " + found.interrupted));
    const pr = found.pull_request;
    clear(where, h("h2", { text: "This library" }), kv([
      ["Folder", found.root], ["Chosen by", ctx.session.chosen_by[found.origin] || found.origin],
      ["Managed by cdlbib", found.managed ? "yes" : "no"], ["Branch", found.branch],
      ["Unsent changes", found.pending === null ? null : found.pending.length ? list(found.pending) : "none"],
      ["Other changed files", found.unrelated && found.unrelated.length ? list(found.unrelated) : null],
      ["New upstream commits", found.new_commits === null ? null : String(found.new_commits) + (found.refreshed ? " (asked just now)" : " (as last fetched)")],
      ["New upstream entries", found.new_entries === null ? null : String(found.new_entries)],
      ["Commits the upstream lacks", found.local_commits === null ? null : String(found.local_commits)],
      ["Last update check", found.managed ? (found.last_check || "never") : null],
      ["Pull request", pr ? pr.url + " (" + pr.state + ")" : null],
    ]), found.notes.length ? note("", list(found.notes)) : null,
    h("div", { class: "row" },
      button("Ask the upstream now", (event) => run(event.currentTarget, async () => { draw(await post("/api/state/refresh", {}, log.add)); announce("State refreshed."); })),
      button("Update the managed library", (event) => run(event.currentTarget, updating)),
      found.pending && found.pending.length ? button("Go to Send", () => ctx.go("send")) : null));
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
      const said = await ask({ title: "Unsent changes", body: error.data.question,
        choices: error.data.choices.map((choice) => ({ value: choice, label: error.data.answers[choice], kind: choice === "discard" ? "danger" : "" })) });
      if (!said) { info("Nothing was changed."); return; }
      const done = await post("/api/update/decide", { decision: error.data.decision, choice: said.choice }, log.add);
      outcome(done);
      if (done.decision === "send") { ctx.go("send"); return; }
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

  async function backups() {
    clear(saved, h("h2", { text: "Backups and undo" }));
    let found;
    try {
      found = await get("/api/backups");
    } catch (error) {
      saved.append(h("p", { class: "muted", text: error.message }));
      return;
    }
    saved.append(h("p", { class: "muted", text: count(found.backups.length, "backup", "backups") + " of " + found.root + ", newest first (kept in " + found.folder + ")." }));
    if (found.checkpoint) saved.append(h("p", { text: "Undo restores the command checkpoint " + found.checkpoint + "." }));
    if (found.backups.length) {
      saved.append(h("div", { class: "row" }, button("Undo the last change", (event) => run(event.currentTarget, () => restore(null)))),
        table(["Backup", "Taken", "State", ""], found.backups.map((b) => [h("span", { class: "mono", text: b.stamp }), b.when,
          (b.branch ? "branch " + b.branch : "no branch") + " at " + b.commit + ", " + count(b.changed, "changed file", "changed files")
            + (b.has_bundle ? ", local commits saved" : "") + (b.only_copy ? ", holds commits kept nowhere else" : ""),
          button("Restore", (event) => run(event.currentTarget, () => restore(b.stamp)), { "aria-label": "Restore backup " + b.stamp })])));
    }
    if (found.unreadable.length) saved.append(note("warn", list(found.unreadable.map(([stamp, why]) => stamp + ": unreadable (" + why + ")"))));
  }

  async function load() {
    draw(await get("/api/state"));
    await backups();
  }

  clear(main, h("div", { class: "stack" }, h("h1", { text: "Library state" }), banner, where, saved,
    h("details", null, h("summary", { text: "Log" }), log.el)));
  await load();
}
