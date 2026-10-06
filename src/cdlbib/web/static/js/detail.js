// One entry: its text, its issues and its evidence; approving and revoking.
import { get, post } from "./api.js";
import { h, clear, button, kv, list, table, tabs, status, data, note, ask, run, info, announce, add, bib } from "./dom.js";

function compact(value) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(compact).filter(Boolean).join("; ");
  if (typeof value === "object") {
    if ("family" in value || "given" in value) return [value.given, value.family].filter(Boolean).join(" ");
    return JSON.stringify(value);
  }
  return String(value);
}

function comparison(candidate) {
  const rows = Object.entries(candidate.evidence || {}).map(([name, found]) => [
    name, compact(found.local),
    compact(found.source),
    h("span", { class: found.match ? "agrees" : "differs", text: found.match ? "agrees" : "differs" }),
    found.detail || "",
  ]);
  return table(["Field", "This entry", "The source", "", "Detail"], rows);
}

function source(candidate) {
  return [candidate.source, candidate.doi].filter(Boolean).join(" ");
}

function findings(detail) {
  if (!detail.format || !detail.format.length) return null;
  return table(["Field", "Now", "House format", "Finding"], detail.format.map((f) => [
    f.field || "(entry)", f.current === null ? "" : f.current, f.corrected === null ? "(removed)" : f.corrected, f.message]));
}

function approval(review) {
  return kv([["Reviewer", review.reviewer], ["Source", review.source], ["Note", review.note],
    ["Recorded", review.reviewed_at || review.at || review.timestamp],
    ...Object.entries(review).filter(([name]) => !["reviewer", "source", "note", "reviewed_at", "at", "timestamp"].includes(name))
      .map(([name, value]) => [name, data(value)])]);
}

function modelEvidence(evidence) {
  const fields = evidence.fields || {};
  const rows = Object.entries(fields).map(([name, found]) => [name, compact(found.value), found.page === undefined ? "" : String(found.page),
    found.quote ? h("q", { text: found.quote }) : ""]);
  const rest = Object.fromEntries(Object.entries(evidence).filter(([name]) => name !== "fields"));
  return [rows.length ? table(["Field", "Value", "Page", "Quoted from the PDF"], rows) : null, data(rest)];
}

function entryTab(panel, detail) {
  add(panel, kv(Object.entries(detail.fields).filter(([name]) => !["ENTRYTYPE", "ID"].includes(name)).map(([name, value]) => [name, value])),
    h("h3", { text: "Text in the library" }), bib(detail.raw));
}

function issuesTab(panel, detail) {
  const result = detail.result || {};
  const issues = result.issues || [];
  add(panel, h("h3", { text: "Verification" }), issues.length ? list(issues) : h("p", { class: "muted", text: "No issues recorded." }));
  if (detail.advisories && detail.advisories.length) add(panel, h("h3", { text: "Remarks" }), list(detail.advisories));
  const format = findings(detail);
  add(panel, h("h3", { text: "House format" }), format || h("p", { class: "muted", text: detail.format === null ? "Not computed." : "No findings." }));
  if (detail.closest) {
    add(panel, h("h3", { text: "Closest source: " + source(detail.closest) }),
      detail.closest.issues && detail.closest.issues.length ? list(detail.closest.issues) : null, comparison(detail.closest));
  }
}

function evidenceTab(panel, detail) {
  const result = detail.result || {};
  if (result.human_review) add(panel, h("h3", { text: "Human approval" }), approval(result.human_review));
  if (result.revoked_approval) {
    add(panel, h("h3", { text: "Revoked approval" }), kv([["Reason", result.revoked_approval.reason],
      ["Revoked by", result.revoked_approval.revoked_by || result.revoked_approval.reviewer],
      ["Revoked", result.revoked_approval.revoked_at]]),
    result.revoked_approval.human_review ? approval(result.revoked_approval.human_review) : null);
  }
  if (result.external_evidence) {
    add(panel, h("h3", { text: result.external_evidence.kind === "model-assisted-choice"
      ? "Book title chosen with a model, unconfirmed (evidence, not an approval)"
      : "Model reading of a PDF (evidence, not an approval)" }), modelEvidence(result.external_evidence));
  }
  const candidates = result.candidates || [];
  add(panel, h("h3", { text: "Source records compared (" + candidates.length + ")" }));
  for (const candidate of candidates) {
    add(panel, h("details", { class: "card" }, h("summary", { text: source(candidate) + (candidate.issues && candidate.issues.length ? " — " + candidate.issues.length + " issue(s)" : " — agrees") }),
      comparison(candidate), h("details", null, h("summary", { text: "The source's record" }), data(candidate.record))));
  }
  const attempts = result.attempts || [];
  add(panel, h("h3", { text: "Lookups made (" + attempts.length + ")" }), attempts.length ? list(attempts.map((item) => data(item))) : h("p", { class: "muted", text: "None recorded." }));
  const known = new Set(["status", "issues", "candidates", "attempts", "human_review", "revoked_approval", "external_evidence"]);
  const rest = Object.entries(result).filter(([name]) => !known.has(name));
  if (rest.length) add(panel, h("details", null, h("summary", { text: "Everything else in the stored result" }), data(Object.fromEntries(rest))));
}

function who(ctx) {
  const known = ctx.identity();
  if (known && known.available) return "It is recorded under the GitHub login of this computer: " + known.detail + ".";
  return "It is recorded under the GitHub login of this computer (gh), which is asked when the record is made. The header's \"check\" shows it.";
}

export async function approve(ctx, detail) {
  const said = await ask({
    title: "Record a human approval of " + detail.key,
    body: [who(ctx), "The approval is bound to the entry's text as shown now."],
    fields: [{ name: "source", label: "Source you checked the entry against", required: true },
      { name: "note", label: "Note (what you checked)", multiline: true, required: true }],
    confirm: "Record the approval",
  });
  if (!said) return false;
  await post("/api/approve", { key: detail.key, fingerprint: detail.fingerprint, source: said.values.source, note: said.values.note });
  info("Approval of " + detail.key + " recorded.");
  return true;
}

export async function revoke(ctx, detail) {
  const said = await ask({
    title: "Withdraw the approval of " + detail.key,
    body: [who(ctx)],
    fields: [{ name: "reason", label: "Reason", multiline: true, required: true }],
    confirm: "Withdraw the approval", danger: true,
  });
  if (!said) return false;
  const done = await post("/api/revoke", { key: detail.key, fingerprint: detail.fingerprint, reason: said.values.reason });
  info("Approval of " + detail.key + " withdrawn; the entry is now: " + String(done.status).replaceAll("_", " ") + ".");
  return true;
}

// Fill `el` with the entry `key`. `changed()` is called after an approval or revocation.
export async function renderDetail(el, ctx, key, changed) {
  clear(el, h("p", { class: "muted", text: "Reading " + key + "…" }));
  const detail = await get("/api/entry", { key });
  const result = detail.result || {};
  const again = async () => { if (changed) await changed(); await renderDetail(el, ctx, key, changed); };
  const actions = h("div", { class: "row" },
    button("Edit", () => ctx.go("edit/" + encodeURIComponent(key))),
    button("Check this entry", () => { ctx.selected = key; ctx.go("check"); }),
    result.human_review
      ? button("Withdraw approval…", (event) => run(event.currentTarget, async () => { if (await revoke(ctx, detail)) await again(); }), { class: "danger" })
      : button("Approve…", (event) => run(event.currentTarget, async () => { if (await approve(ctx, detail)) await again(); })));
  const view = tabs("Entry " + key, [
    ["Entry", (panel) => entryTab(panel, detail)],
    ["Issues (" + ((result.issues || []).length + (detail.format || []).length) + ")", (panel) => issuesTab(panel, detail)],
    ["Evidence", (panel) => evidenceTab(panel, detail)],
  ]);
  clear(el, h("div", { class: "detail-head" }, h("h2", { text: detail.key }), h("span", { class: "tag", text: detail.fields.ENTRYTYPE || "" }), status(result.status)),
    result.human_review ? note("good", "Approved by " + (result.human_review.reviewer || "a reviewer") + ".") : null,
    actions, view.el);
  announce("Entry " + key + ": " + String(result.status || "").replaceAll("_", " "));
  return detail;
}
