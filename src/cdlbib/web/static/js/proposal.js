// One proposal: typed against proposed, where each change comes from, and the decision.
// The browser sends back the id of the version it shows and the decision; the proposal itself
// stays on the server, and a recheck or a choice makes a new version under a new id.
import { get, post, ApiError } from "./api.js";
import { h, clear, button, field, list, table, note, status, kv, showError, announce, drafts, add } from "./dom.js";

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
  return lines.concat(done.notes || []);
}

// A card for the proposal `found`. `settled(id)` is called when it is accepted or skipped,
// `renewed(old id, new id)` when a recheck or a choice gave a new version.
export function proposalCard(found, { verb, settled, renewed } = {}) {
  const card = h("article", { class: "card", "data-proposal": found.id, "aria-label": "Proposal " + (found.key_typed || found.key_proposed || "(new)") });
  let pending = false;
  let typedInEditor = () => false;
  drafts.add(() => card.isConnected && typedInEditor());

  // One action at a time on a card: while a job of this card runs, all its controls are off,
  // so nothing is decided about a version that is being replaced.
  async function act(action) {
    if (pending) return;
    pending = true;
    const controls = [...card.querySelectorAll("button, textarea, input")].filter((el) => !el.disabled);
    for (const el of controls) el.disabled = true;
    card.setAttribute("aria-busy", "true");
    try {
      await action();
    } catch (error) {
      if (error instanceof ApiError && error.kind === "StaleProposal") {
        try {
          draw(await get("/api/proposal", { proposal: error.data.current }), error.message);
        } catch (again) { showError(again); }
      } else {
        showError(error);
      }
    } finally {
      pending = false;
      card.removeAttribute("aria-busy");
      for (const el of controls) if (el.isConnected) el.disabled = false;
    }
  }

  function finish(lines, good) {
    typedInEditor = () => false;
    clear(card, note(good ? "good" : "", list(lines)));
    announce(lines.join(" "));
    if (settled) settled(found.id);
  }

  function names(item, choice) {
    const picks = choice.typed.map(() => "typed");
    const rows = choice.typed.map((mine, index) => {
      const theirs = choice.source[index];
      if (mine === theirs) return h("li", { text: mine });
      const group = "names-" + item.id + "-" + choice.field + "-" + index;
      const radio = (value, label, checked) => h("label", null, h("input", { type: "radio", name: group, value, checked,
        on: { change: () => { picks[index] = value; } } }), " " + label);
      return h("li", null, radio("typed", "keep typed: " + mine, true), " ", radio("source", "use the source's: " + theirs, false));
    });
    return h("fieldset", { class: "names" }, h("legend", { text: "The " + choice.field + " names differ from the source's; choose name by name" }),
      h("ol", { class: "plain" }, rows),
      button("Use these names", () => act(async () => draw(await post("/api/proposal/names", { proposal: item.id, field: choice.field, picks }))),
        { "data-action": "names" }));
  }

  function draw(item, said) {
    if (item.id !== found.id && renewed) renewed(found.id, item.id);
    found = item;
    card.dataset.proposal = item.id;
    const title = item.key_typed || item.key_proposed || "(new)";
    const tags = [];
    if (item.evidence) tags.push(h("span", { class: "tag warn", text: "model reading: evidence, not an approval" }));
    else if (item.manual) tags.push(h("span", { class: "tag warn", text: "typed by hand: no source record" }));
    if (item.record_source) tags.push(h("span", { class: "tag", text: "source: " + item.record_source }));
    if (item.needs_decision) tags.push(h("span", { class: "tag warn", text: "needs your decision" }));
    const parts = [h("div", { class: "detail-head" }, h("h3", { text: "Entry: " + title }), tags,
      h("span", null, "Verification: ", item.status ? status(item.status) : "not checked"))];
    if (said) parts.push(note("warn", said));
    if (item.issues.length) parts.push(note("warn", list(item.issues)));
    if (item.notes.length) parts.push(note("", list(item.notes)));
    parts.push(h("div", { class: "two" },
      h("div", null, h("h3", { text: "Typed" }), h("pre", { class: "mono panel", text: item.typed_raw || "(no typed entry)" })),
      h("div", null, h("h3", { text: "Proposed" }), h("pre", { class: "mono panel", text: item.proposed_raw || "(no proposed entry)" }))));
    if (item.changes.length) {
      parts.push(table(["Field", "Typed", "Proposed", "Source", ""], item.changes.map((c) => [c.field, c.typed === null ? "" : c.typed,
        c.proposed === null ? "" : c.proposed, c.source, c.kind]), { class: "grid changes" }));
    }
    for (const choice of item.name_choices || []) parts.push(names(item, choice));
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
        button("Use this one", () => act(async () => draw(await post("/api/proposal/candidate", { proposal: item.id, index }))))])));
    }
    const editor = h("div", { hidden: true });
    const actions = h("div", { class: "row" });
    if (item.duplicate_of && item.duplicate_in_library) {
      add(actions, button("Remove this typed duplicate", () => act(async () => {
        const done = await post("/api/proposal/remove-duplicate", { proposal: item.id });
        finish(appliedLines(done, verb), done.removed.length > 0);
      })), button("Keep both for the formatter", () => act(skip)));
    } else {
      add(actions, button("Accept", () => act(async () => {
        const done = await post("/api/proposal/accept", { proposal: item.id });
        if (done.evidence_stored === false) {
          // the entry is written; what is still owed stays on the page
          typedInEditor = () => false;
          clear(card, note("good", list(appliedLines(done, verb))),
            note("bad", "The entry " + done.key + " was written, but the model reading's evidence could not be stored with it: " + done.evidence_error));
          if (settled) settled(found.id);
          return;
        }
        finish(appliedLines(done, verb), done.written.length > 0);
      }), { class: "primary", disabled: !item.acceptable, "data-action": "accept" }),
      button("Edit", () => { editor.hidden = !editor.hidden; if (!editor.hidden) editor.querySelector("textarea").focus(); }, { "data-action": "edit" }),
      button("Skip", () => act(skip), { "data-action": "skip" }));
    }
    if (!item.acceptable && item.cannot_accept) parts.push(h("p", { class: "muted", text: item.cannot_accept }));
    const base = item.proposed_raw || item.typed_raw || "";
    const text = h("textarea", { class: "mono", rows: "12", spellcheck: "false" });
    text.value = base;
    typedInEditor = () => text.isConnected && text.value !== base;
    add(editor, field("Edit the entry, then check it again", text),
      button("Recheck", () => act(async () => draw(await post("/api/proposal/recheck", { proposal: item.id, raw: text.value }))),
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

// A list of proposal cards with "accept remaining". `aside(proposal)`: something to show
// beside a proposal's card (the first page of the PDF it came from), or null.
export function proposalList({ verb, aside } = {}) {
  const open = new Set();
  const cards = h("div");
  const remaining = button("Accept all remaining", async () => {
    remaining.disabled = true;
    try {
      const done = await post("/api/proposal/accept-remaining", { proposals: [...open] });
      for (const id of done.accepted) {
        const card = cards.querySelector('[data-proposal="' + id + '"]');
        if (card) clear(card, note("good", "Accepted with the remaining proposals."));
        open.delete(id);
      }
      summary.replaceChildren(note(done.written.length ? "good" : "", list(appliedLines(done, verb).concat(
        open.size ? [open.size + " proposal(s) need an individual decision and were left."] : []))));
    } catch (error) {
      showError(error);
    } finally {
      remaining.disabled = false;
      update();
    }
  }, { hidden: true, "data-action": "accept-remaining" });
  const summary = h("div", { "aria-live": "polite" });
  function update() { remaining.hidden = open.size < 1; }
  return {
    el: h("section", { "aria-label": "Proposals" }, h("div", { class: "row" }, remaining), summary, cards),
    open,
    add(found) {
      open.add(found.id);
      const card = proposalCard(found, { verb,
        settled: (id) => { open.delete(id); update(); },
        renewed: (before, after) => { open.delete(before); open.add(after); } });
      const beside = aside ? aside(found) : null;
      cards.prepend(beside ? h("div", { class: "two beside" }, beside, card) : card);
      update();
    },
    errors(found) {
      if (found && found.length) summary.replaceChildren(note("bad", list(found.map(([label, why]) => label + ": " + why))));
    },
  };
}
