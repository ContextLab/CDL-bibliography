// Setup: what cdlbib can use on this computer, the TeX link, and a paper's frozen .bib.
import { get, post, upload, blob, ApiError } from "./api.js";
import { h, clear, button, field, list, table, note, kv, logPane, run, ask, info, download, announce } from "./dom.js";

const PROBE = { "gh login": "github", "Dartmouth Chat key": "dartmouth-chat", "OpenAI key": "openai" };

export async function show(main, ctx) {
  const features = h("div", { class: "panel" });
  const tex = h("div", { class: "panel" });
  const exported = h("div", { class: "stack", "aria-live": "polite" });
  const log = logPane("Setup log");

  function draw(found) {
    if (ctx.showIdentity) ctx.showIdentity(found.features.find((item) => item.name === "gh login" && item.available !== null));
    clear(features, h("h2", { text: "Available on this computer" }),
      kv([["Library", found.where.root], ["Chosen by", found.chosen_by]]),
      table(["", "", "What was found", "How to set it up", ""], found.features.map((item) => [
        h("strong", { text: item.name }),
        h("span", { class: (item.available ? "agrees" : item.available === null ? "muted" : "differs") + " nowrap", text: item.available === null ? "not checked" : item.available ? "yes" : "no" }),
        item.detail, item.how,
        PROBE[item.name] && item.available !== true ? button("check", (event) => run(event.currentTarget, () => checking(PROBE[item.name])),
          { "aria-label": "Check " + item.name }) : ""])),
      h("div", { class: "row" }, button("Check everything", (event) => run(event.currentTarget, () => checking("all")))),
      h("p", { class: "muted", text: "A check of the GitHub login asks gh over the network; a check of a key reads the system keychain, which may ask for permission." }));
    const s = found.tex;
    clear(tex, h("h2", { text: "cdl.bib for every manuscript" }), list(found.tex_lines, { class: "plain tex-lines" }),
    h("div", { class: "row" },
      s.present === "linked" ? null : button("Link cdl.bib into the TeX tree", (event) => run(event.currentTarget, () => linking(false)), { class: "primary" }),
      s.present === "absent" ? null : button("Remove the link", (event) => run(event.currentTarget, unlinking))));
  }

  async function checking(probe) {
    log.clear();
    draw(await post("/api/setup/check", { probe }, log.add));
    announce("Checked.");
  }

  async function linking(replace) {
    try {
      const made = await post("/api/tex/link", { replace });
      info(made.lines.join("\n"));
    } catch (error) {
      if (!(error instanceof ApiError) || error.kind !== "TexLinkRefused" || replace) throw error;
      const said = await ask({ title: "Something is already there", body: [error.message, "It can be moved aside (it is kept) and the link made."],
        confirm: "Move it aside and link", danger: true });
      if (!said) return;
      await linking(true);
      return;
    }
    draw(await get("/api/setup"));
  }

  async function unlinking() {
    const said = await ask({ title: "Remove the link?", body: "Only the link cdlbib made is removed.", confirm: "Remove", danger: true });
    if (!said) return;
    const done = await post("/api/tex/unlink");
    info(done.removed ? "removed " + done.link : "nothing removed at " + done.link + ": " + done.reason);
    draw(await get("/api/setup"));
  }

  const files = h("input", { type: "file", id: "export-files", multiple: true, accept: ctx.session.manuscript_types.join(",") });
  const mainFile = h("select", { id: "export-main" });
  const mainField = field("Main file", mainFile);
  mainField.hidden = true;           // asked only when several files were chosen
  let bundle = null;
  files.addEventListener("change", () => run(files, async () => {
    bundle = null;
    clear(exported);
    let listed = [];
    for (const file of files.files) {
      const sent = await upload("/api/export/upload", { bundle, name: file.name }, file, "application/octet-stream");
      bundle = sent.bundle;
      listed = sent.files;
    }
    clear(mainFile, h("option", { value: "", text: listed.length > 1 ? "(the file with \\documentclass)" : listed[0] || "" }),
      listed.length > 1 ? listed.map((name) => h("option", { value: name, text: name })) : null);
    mainField.hidden = listed.length < 2;
    announce(listed.length + " file(s) uploaded.");
  }));

  async function exporting() {
    if (!bundle) throw new Error("Choose the paper's files first.");
    log.clear();
    const done = await post("/api/export/run", { bundle, main: mainFile.value || null }, log.add);
    clear(exported, note(done.missing.length ? "warn" : "good", list([
      "citations read from " + done.read_from + ": " + done.cited + " key" + (done.cited === 1 ? "" : "s") + (done.all_entries ? " and \\nocite{*} (every entry)" : ""),
      ...done.notes,
      done.written + " entr" + (done.written === 1 ? "y" : "ies") + " from the library",
      done.parents.length ? "included because a cited entry inherits from them: " + done.parents.join(", ") : null,
      done.missing.length ? "cited, but not in the library: " + done.missing.join(", ") : null,
    ].filter(Boolean))),
    button("Download " + done.name, (event) => run(event.currentTarget, async () => download(await blob("/api/export/" + done.export + "/file"), done.name)),
      { class: "primary", "data-action": "download" }));
    announce("The .bib is ready to download.");
  }

  clear(main, h("div", { class: "stack" }, h("h1", { text: "Setup" }), features, tex,
    h("div", { class: "panel" }, h("h2", { text: "A paper's own .bib" }),
      h("p", { class: "muted", text: "Upload the paper's .tex, .aux or .bcf file (several files when the paper is split); the entries it cites are written as a .bib to download. The files are kept only while cdlbib web runs." }),
      field("The paper's files", files), mainField,
      h("div", { class: "row" }, button("Make the .bib", (event) => run(event.currentTarget, exporting), { class: "primary" })),
      exported, note("", ctx.session.no_bbl)),
    log.el));
  draw(await get("/api/setup"));
}
