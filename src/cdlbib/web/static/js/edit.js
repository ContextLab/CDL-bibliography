// Editing one entry, or typing a new one: the preview first, then the save of exactly what was previewed.
import { get, post } from "./api.js";
import { h, clear, button, field, list, table, note, status, kv, run, info, announce, drafts, showError, add } from "./dom.js";

export function diffView(text) {
  const el = h("pre", { class: "diff mono panel", "aria-label": "Changes" });
  for (const line of String(text || "").split("\n")) {
    const head = line.startsWith("@@") || line.startsWith("+++") || line.startsWith("---");
    const kind = head ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
    add(el, h("span", { class: kind, text: line || " " }));
  }
  return el;
}

export async function show(main, ctx, key) {
  let original = "";
  if (key) original = (await get("/api/entry", { key })).raw;
  let previewed = null;        // {id, raw, problems}
  const text = h("textarea", { class: "mono", id: "entry-text", spellcheck: "false", rows: "18" });
  text.value = original;
  const out = h("section", { "aria-label": "Preview", "aria-live": "polite" });
  const save = button("Save", () => saving().catch(showError), { class: "primary", disabled: true });
  const preview = button("Preview", (event) => run(event.currentTarget, previewing));

  drafts.add(() => text.isConnected && text.value !== original);

  function stale() {
    previewed = null;
    save.disabled = true;
  }
  text.addEventListener("input", stale);

  async function previewing() {
    const raw = text.value;
    const found = await post("/api/edit/preview", { key: key || null, raw });
    previewed = { id: found.preview, raw };
    save.disabled = found.problems.length > 0 || !found.changed;
    const parts = [h("h2", { text: "Preview" })];
    if (found.problems.length) parts.push(note("bad", h("strong", { text: "This cannot be saved as it is:" }), list(found.problems)));
    if (!found.changed) parts.push(note("", "The text is what the library already holds."));
    parts.push(kv([
      ["Key", found.new_key],
      ["Key change", found.key_change ? found.key_change.old + " → " + found.key_change.new + " (" + found.key_change.kind + ")" : null],
      ["Same work as", found.duplicate_of],
      ["Status now", found.status_now ? status(found.status_now) : null],
      ["Status after saving", found.status ? status(found.status) : null],
      ["Saving loses", found.invalidates ? status(found.invalidates) : null],
    ]));
    if (found.affected.length) {
      parts.push(h("h3", { text: "Other entries whose status changes" }),
        table(["Entry", "Now", "After"], found.affected.map((item) => [item.key, status(item.status_now), status(item.status)])));
    }
    parts.push(h("h3", { text: "Changes" }), found.diff ? diffView(found.diff) : h("p", { class: "muted", text: "None." }));
    parts.push(h("h3", { text: "House format findings (" + found.format.length + ")" }));
    if (found.format.length) {
      parts.push(table(["Field", "As typed", "House format", "Finding"], found.format.map((f) => [f.field || "(entry)", f.current === null ? "" : f.current,
        f.corrected === null ? "(removed)" : f.corrected, f.message])));
      if (found.corrected_raw && found.corrected_raw !== raw) {
        parts.push(h("details", null, h("summary", { text: "The entry as the house formatter would write it" }),
          h("pre", { class: "mono panel", text: found.corrected_raw }),
          button("Put this text in the editor", () => { text.value = found.corrected_raw; stale(); clear(out); text.focus(); })));
      }
      parts.push(h("p", { class: "muted", text: "Format findings do not stop a save; they are checked again before a send." }));
    } else {
      parts.push(h("p", { class: "muted", text: "None." }));
    }
    clear(out, parts);
    announce(found.problems.length ? "Preview: this cannot be saved as it is." : "Preview ready.");
  }

  async function saving() {
    if (!previewed || previewed.raw !== text.value) { stale(); return; }
    const submitted = previewed.raw;        // exactly what the server holds under this preview
    let done;
    save.disabled = true;                   // one save at a time; a new preview enables it again
    text.readOnly = true;                   // nothing is typed into a text that is being saved
    preview.disabled = true;
    try {
      done = await post("/api/edit/save", { preview: previewed.id });
    } catch (error) {
      stale();                              // the preview is used up or refused: preview again
      throw error;
    } finally {
      text.readOnly = false;
      preview.disabled = false;
    }
    const written = done.written[0] || (key || "");
    if (done.written.length) {
      original = submitted;
      key = written;
    }
    const parts = ["Saved " + written + "."];
    for (const [from, to] of Object.entries(done.renamed)) parts.push("Renamed " + from + " to " + to + ".");
    if (done.backup) parts.push("Backup taken first: " + done.backup + ".");
    if (done.saved_copy) parts.push("The file as it was: " + done.saved_copy);
    for (const [refused, why] of done.refused) parts.push("Not written " + refused + ": " + why);
    info(parts.concat(done.notes).join("\n"));
    ctx.selected = written || ctx.selected;
    stale();
    if (text.value !== original) {          // typed since, or the save was refused: the text stays here
      clear(out, note("warn", done.written.length
        ? "Saved " + written + " as it was previewed. The text in the editor differs from what was saved and is not saved; preview it and save again to keep it."
        : "Nothing was saved. The text is still in the editor."));
      heading.textContent = "Edit " + key;
      return;
    }
    ctx.go("library");
  }

  const heading = h("h1", { text: key ? "Edit " + key : "New entry" });
  clear(main, heading, h("div", { class: "two" },
    h("div", null,
      field(key ? "The entry's BibTeX text" : "The new entry's BibTeX text (one entry, with its key)", text),
      h("div", { class: "row" }, preview, save, button("Cancel", () => ctx.go("library"))),
      h("p", { class: "muted", text: "Save writes exactly the text that was previewed. Editing the text again needs a new preview." })),
    out));
  text.focus();
}
