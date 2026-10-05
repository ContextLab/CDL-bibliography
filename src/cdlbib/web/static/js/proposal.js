// One proposal: typed against proposed, where each change comes from, and the decision.
// The browser sends back the proposal's id and the decision; the proposal itself stays on the server.
import { post } from "./api.js";
import { h, clear, button, field, list, table, note, status, kv, run, announce } from "./dom.js";

export function candidateLine(lead) {
  return [lead.authors, lead.year].filter(Boolean).join(" ") + ": " + (lead.title || "(no title)")
    + [lead.journal, lead.doi || lead.arxiv || lead.pmid].filter(Boolean).map((part) => " · " + part).join("");
}

export function appliedLines(done, verb) {
  const lines = [];
  for (const key of done.removed) lines.push("Removed duplicate: " + key);
  for (const key of done.written) lines.push((verb || "Added") + ": " + key);
  for (const [from, to] of Object.entries(done.renamed || {})) lines.push("Rename: " + from + " -> " + to);
  for (const [key, why] of done.refused) lines.push("Not written " + key + ": " + why);
  if (done.backup) lines.push("Backup taken first: " + done.backup + " (Library state can restore it).");
  if (done.saved_copy) lines.push("The file as it was: " + done.saved_copy);
  if (done.evidence_stored === true) lines.push("The model reading's evidence was stored with the entry (it is not an approval).");
  if (done.evidence_stored === false) lines.push("The entry was written, but the model evidence could not be stored: " + done.evidence_error);
  return lines.concat(done.notes || []);
}

// A card for the proposal `found`. `settled(id)` is called when it is accepted or skipped.
export function proposalCard(found, { verb, settled } = {}) {
  const card = h("article", { class: "card", "data-proposal": found.id, "aria-label": "Proposal " + (found.key_typed || found.key_proposed || "(new)") });

  function finish(lines, good) {
    clear(card, note(good ? "good" : "", list(lines)));
    announce(lines.join(" "));
    if (settled) settled(found.id);
  }

  function draw(item) {
    found = item;
    const title = item.key_typed || item.key_proposed || "(new)";
    const tags = [];
    if (item.evidence) tags.push(h("span", { class: "tag warn", text: "model reading: evidence, not an approval" }));
    else if (item.manual) tags.push(h("span", { class: "tag warn", text: "typed by hand: no source record" }));
    if (item.record_source) tags.push(h("span", { class: "tag", text: "source: " + item.record_source }));
    if (item.needs_decision) tags.push(h("span", { class: "tag warn", text: "needs your decision" }));
    const parts = [h("div", { class: "detail-head" }, h("h3", { text: "Entry: " + title }), tags,
      h("span", null, "Verification: ", item.status ? status(item.status) : "not checked"))];
    if (item.issues.length) parts.push(note("warn", list(item.issues)));
    if (item.notes.length) parts.push(note("", list(item.notes)));
    parts.push(h("div", { class: "two" },
      h("div", null, h("h3", { text: "Typed" }), h("pre", { class: "mono panel", text: item.typed_raw || "(no typed entry)" })),
      h("div", null, h("h3", { text: "Proposed" }), h("pre", { class: "mono panel", text: item.proposed_raw || "(no proposed entry)" }))));
    if (item.changes.length) {
      parts.push(table(["Field", "Typed", "Proposed", "Source", ""], item.changes.map((c) => [c.field, c.typed === null ? "" : c.typed,
        c.proposed === null ? "" : c.proposed, c.source, c.kind])));
    }
    if (item.unfilled.length) {
      parts.push(h("h3", { text: "Unfilled" }), list(item.unfilled.map((m) => m.field + ": " + m.reason
        + Object.entries(m.source_values || {}).map(([name, value]) => " (" + name + ": " + value + ")").join(""))));
    }
    parts.push(kv([
      ["Key", item.key_typed && item.key_proposed && item.key_proposed !== item.key_typed ? item.key_typed + " -> " + item.key_proposed : item.key_proposed],
      ["Renames", Object.keys(item.renames).length ? list(Object.entries(item.renames).map(([from, to]) => from + " -> " + to)) : null],
      ["Duplicate", item.duplicate_of], ["Unsupported", item.unsupported],
    ]));
    if (item.candidates.length) {
      parts.push(h("h3", { text: "Candidates" }), list(item.candidates.map((lead, index) => [candidateLine(lead), " ",
        button("Use this one", (event) => run(event.currentTarget, async () => draw(await post("/api/proposal/candidate", { proposal: item.id, index }))))])));
    }
    const editor = h("div", { hidden: true });
    const actions = h("div", { class: "row" });
    if (item.duplicate_of && item.duplicate_in_library) {
      actions.append(button("Remove this typed duplicate", (event) => run(event.currentTarget, async () => {
        const done = await post("/api/proposal/remove-duplicate", { proposal: item.id });
        finish(appliedLines(done, verb), done.removed.length > 0);
      })), button("Keep both for the formatter", (event) => run(event.currentTarget, skip)));
    } else {
      actions.append(button("Accept", (event) => run(event.currentTarget, async () => {
        const done = await post("/api/proposal/accept", { proposal: item.id });
        finish(appliedLines(done, verb), done.written.length > 0);
      }), { class: "primary", disabled: !item.acceptable, "data-action": "accept" }),
      button("Edit", () => { editor.hidden = !editor.hidden; if (!editor.hidden) editor.querySelector("textarea").focus(); }, { "data-action": "edit" }),
      button("Skip", (event) => run(event.currentTarget, skip), { "data-action": "skip" }));
    }
    if (!item.acceptable && item.cannot_accept) parts.push(h("p", { class: "muted", text: item.cannot_accept }));
    const text = h("textarea", { class: "mono", rows: "12", spellcheck: "false" });
    text.value = item.proposed_raw || item.typed_raw || "";
    editor.append(field("Edit the entry, then check it again", text),
      button("Recheck", (event) => run(event.currentTarget, async () => draw(await post("/api/proposal/recheck", { proposal: item.id, raw: text.value }))),
        { "data-action": "recheck" }));
    parts.push(actions, editor);
    clear(card, parts);
  }

  async function skip() {
    await post("/api/proposal/skip", { proposal: found.id });
    finish(["Skipped; nothing was changed."], false);
  }

  draw(found);
  return card;
}

// A list of proposal cards with "accept remaining".
export function proposalList({ verb } = {}) {
  const open = new Set();
  const cards = h("div");
  const remaining = button("Accept all remaining", (event) => run(event.currentTarget, async () => {
    const done = await post("/api/proposal/accept-remaining", { proposals: [...open] });
    for (const id of done.accepted) {
      const card = cards.querySelector('[data-proposal="' + id + '"]');
      if (card) clear(card, note("good", "Accepted with the remaining proposals."));
      open.delete(id);
    }
    summary.replaceChildren(note(done.written.length ? "good" : "", list(appliedLines(done, verb).concat(
      open.size ? [open.size + " proposal(s) need an individual decision and were left."] : []))));
    update();
  }), { hidden: true, "data-action": "accept-remaining" });
  const summary = h("div", { "aria-live": "polite" });
  function update() { remaining.hidden = open.size < 1; }
  return {
    el: h("section", { "aria-label": "Proposals" }, h("div", { class: "row" }, remaining), summary, cards),
    add(found) {
      open.add(found.id);
      cards.prepend(proposalCard(found, { verb, settled: (id) => { open.delete(id); update(); } }));
      update();
    },
    errors(found) {
      if (found && found.length) summary.replaceChildren(note("bad", list(found.map(([label, why]) => label + ": " + why))));
    },
  };
}
