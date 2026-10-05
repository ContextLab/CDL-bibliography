// Adding references: by search, by identifier, from a PDF, or typed by hand.
import { get, post, upload, blob } from "./api.js";
import { h, clear, button, field, list, table, note, kv, tabs, logPane, run, announce, ask, drafts, add } from "./dom.js";
import { proposalList, candidateLine } from "./proposal.js";

const MAX_PDF = 50000000;

export async function show(main) {
  const log = logPane("Lookup log");
  const manual = { pdf: null, model: null, prefill: {}, panel: null, typed: () => false };     // the manual form and what it starts from
  const names = new Map();         // pdf id -> the file's name
  const pictures = new Map();      // pdf id -> the first page as a PNG (a promise)
  const files = new Map();         // pdf id -> an object URL of the PDF (a promise)

  // The first page of an uploaded PDF: the PDF itself in the browser's viewer, or, in a browser
  // that shows no PDFs, the page drawn by the server. Shown where the PDF is read and again
  // beside every proposal that came from it.
  function pageView(pdf, beside) {
    const name = names.get(pdf) || "the PDF";
    const el = h("div", { class: "pdf-view" + (beside ? " beside-page" : "") });
    const image = h("div");
    const picture = async () => {
      if (!pictures.has(pdf)) pictures.set(pdf, post("/api/pdf/page", { pdf }));
      let found;
      try { found = await pictures.get(pdf); } catch (error) { pictures.delete(pdf); throw error; }
      clear(image, h("img", { class: "pdf-image", alt: "First page of " + name, src: "data:image/png;base64," + found.png }));
    };
    const asImage = button("Show the first page as an image", (event) => run(event.currentTarget, picture));
    if (beside) add(el, h("h3", { text: "First page of " + name }));
    if (navigator.pdfViewerEnabled === false) {
      add(el, h("p", { class: "muted", text: "This browser does not display PDFs; the first page is shown as an image." }), image);
      picture().catch((error) => clear(image, note("bad", error.message), asImage));
    } else {
      if (!files.has(pdf)) files.set(pdf, blob("/api/pdf/" + pdf + "/file").then((data) => URL.createObjectURL(data)));
      files.get(pdf).then((url) => el.prepend(h("iframe", { class: "pdf-frame", title: "The PDF: " + name, src: url + "#page=1" })),
        (error) => { files.delete(pdf); el.prepend(note("bad", error.message)); });
      add(el, h("div", { class: "row" }, asImage), image);
    }
    return el;
  }

  const proposals = proposalList({ verb: "Added", aside: (found) => (found.pdf ? pageView(found.pdf, true) : null) });

  function took(found) {
    proposals.errors(found.errors);
    for (const item of found.proposals) proposals.add(item);
    announce(found.proposals.length + " proposal(s) below.");
    proposals.el.scrollIntoView({ block: "nearest" });
  }

  function leads(found, searchId) {
    if (!found.length) return h("p", { class: "muted", text: "No records." });
    return list(found.map((lead, index) => [candidateLine(lead), " ",
      lead.sources ? h("span", { class: "tag", text: lead.sources.join(", ") }) : null, " ",
      lead.in_library ? h("span", { class: "tag warn", text: "in the library as " + lead.in_library }) : null, " ",
      button("Use this one", (event) => run(event.currentTarget, async () => took(await post("/api/add/choose", { search: searchId, index }, log.add))))]));
  }

  // --- search ---
  function searchTab(panel) {
    const title = h("input", { type: "text", id: "add-title" });
    const authors = h("input", { type: "text", id: "add-authors" });
    const year = h("input", { type: "text", id: "add-year", inputmode: "numeric", maxlength: "4" });
    const out = h("div", { "aria-live": "polite" });
    add(panel, field("Title (or part of it)", title), field("Authors (separate several with ;)", authors), field("Year (optional)", year),
      h("div", { class: "row" }, button("Search", (event) => run(event.currentTarget, async () => {
        log.clear();
        const found = await post("/api/add/search", { title: title.value.trim(), authors: authors.value.split(";").map((name) => name.trim()).filter(Boolean),
          year: year.value.trim() }, log.add);
        clear(out, h("h3", { text: "Candidates (" + found.items.length + ")" }),
          found.errors.length ? note("warn", list(found.errors.map(([source, why]) => source + ": " + why))) : null,
          leads(found.items, found.search));
        announce(found.items.length + " candidate(s).");
      }), { class: "primary" })), out);
  }

  // --- identifiers ---
  function identifierTab(panel) {
    const text = h("textarea", { id: "add-identifiers", rows: "4", spellcheck: "false" });
    add(panel, field("DOIs, PMIDs or arXiv ids, one per line", text),
      h("div", { class: "row" }, button("Look up", (event) => run(event.currentTarget, async () => {
        log.clear();
        took(await post("/api/add/identifiers", { queries: text.value.split("\n").map((line) => line.trim()).filter(Boolean) }, log.add));
      }), { class: "primary" })));
  }

  // --- PDF ---
  function pdfTab(panel) {
    const file = h("input", { type: "file", id: "add-pdf", accept: "application/pdf,.pdf" });
    const out = h("div", { class: "stack" });
    add(panel, field("A PDF from this computer (up to 50 MB)", file), out);
    file.addEventListener("change", () => run(file, async () => {
      const chosen = file.files[0];
      if (!chosen) return;
      if (chosen.size > MAX_PDF) throw new Error("The file is larger than 50 MB.");
      log.clear();
      clear(out, h("p", { class: "muted", text: "Reading " + chosen.name + "…" }));
      const sent = await upload("/api/pdf/upload", null, chosen, "application/pdf");
      names.set(sent.pdf, chosen.name);
      const read = await post("/api/pdf/read", { pdf: sent.pdf }, log.add);
      await drawPdf(out, read, chosen.name);
    }));
  }

  async function drawPdf(out, read, name) {
    const viewer = pageView(read.pdf, false);
    const result = h("div", { class: "stack", "aria-live": "polite" });
    const models = h("div", { class: "stack" });

    const facts = [kv([["Title read", read.title_guess], ["Read from", read.title_source], ["Pages read", String(read.pages.length)],
      ["Text", read.ocr ? "from OCR, which misreads characters" : null]])];
    if (read.problem) facts.unshift(note("bad", read.problem.replaceAll("_", " ") + (read.detail ? ": " + read.detail : "")));
    if (read.identifiers.length) {
      facts.push(table(["Identifier", "Value", "Page", "Read from"], read.identifiers.map((i) => [i.kind, h("span", { class: "nowrap", text: i.value }), i.page === null ? "metadata" : String(i.page), i.quote])));
    } else {
      facts.push(h("p", { class: "muted", text: "No DOI, arXiv id or PMID was read." }));
    }
    facts.push(h("details", null, h("summary", { text: "Text of the first page" }), h("pre", { class: "mono log", text: read.first_page_text || "(none)" })));

    const lookup = button("Look up the source record", (event) => run(event.currentTarget, async () => {
      const found = await post("/api/pdf/lookup", { pdf: read.pdf }, log.add);
      manual.prefill = found.prefill || {};
      clear(result, note(found.matched ? "good" : "warn", found.message), found.tried.length ? list(found.tried) : null,
        found.search ? [h("h3", { text: "Similar records" }), leads(found.candidates, found.search)] : null);
      if (found.proposal) took({ proposals: [found.proposal], errors: [] });
    }), { class: "primary", "data-action": "pdf-lookup" });

    async function routes(found) {
      clear(models, h("h3", { text: "Read with a language model" }),
        h("p", { class: "muted", text: "A model's reading is a proposal with page quotations; it is not a verification or an approval." }),
        found.routes.map((route) => h("div", { class: "card" },
          h("div", { class: "row" },
            button("Read with " + route.label, (event) => run(event.currentTarget, async () => {
              const item = await post("/api/pdf/model", { pdf: read.pdf, route: route.name }, log.add);
              manual.model = item.id;
              took({ proposals: [item], errors: [] });
            }), { disabled: route.available === false, "data-route": route.name }),
            h("span", { class: "tag" + (route.available ? "" : " warn"), text: route.available === null ? "not checked" : route.available ? "set up" : "not set up" }),
            route.default ? h("span", { class: "tag", text: "default" }) : null,
            route.available === null ? button("check", (event) => run(event.currentTarget, async () => routes(await post("/api/model-routes/check", { route: route.name }))),
              { "aria-label": "Check whether " + route.label + " is set up" }) : null),
          route.available === false && route.detail ? h("p", { class: "differs", text: route.detail }) : null,
          h("p", { class: "muted", text: route.how }))));
    }

    const byHand = button("Type it in by hand", (event) => run(event.currentTarget, async () => {
      if (manual.typed()) {
        const replace = await ask({ title: "Replace the entry you are typing?",
          body: "The manual form holds text you typed. Starting it again from this PDF discards that text.", confirm: "Discard it and start from this PDF", danger: true });
        if (!replace) { view.select(3, true); return; }
      }
      manual.pdf = read.pdf;
      if (manual.panel) await redrawManual();
      view.select(3, true);
    }));

    clear(out, h("div", { class: "two" }, viewer, h("div", { class: "stack" }, h("h3", { text: "What was read from " + name }), facts,
      h("div", { class: "row" }, lookup, byHand), result, models)));
    manual.pdf = read.pdf;
    manual.model = null;
    await routes(await get("/api/model-routes"));
  }

  // --- manual ---
  // The form is drawn once and kept, with what was typed, while the view is open; it starts
  // again only when asked to (the "Start again" button, or "Type it in by hand" for a PDF).
  async function manualTab(panel) {
    manual.panel = panel;
    const form = await get("/api/add/form");
    const from = { pdf: manual.pdf, model: manual.model };
    manual.prefill = from.pdf ? (await get("/api/pdf/prefill", from)).fields : {};
    const prefill = manual.prefill;
    const type = h("select", { id: "manual-type" }, form.types.map((name) => h("option", { value: name, text: name })));
    const inputs = new Map();
    const touched = new Set();
    let drafted = null;          // the values as they were when the entry was last drafted
    const rows = h("div");
    function row(name, value) {
      const input = h("input", { type: "text", "data-field": name });
      input.value = value || "";
      input.addEventListener("input", () => touched.add(name));
      inputs.set(name, input);
      add(rows, field(name + (prefill[name] ? " (read from the PDF)" : ""), input));
    }
    for (const name of [...new Set([...form.fields, ...Object.keys(prefill)])]) row(name, prefill[name]);
    const values = () => JSON.stringify([type.value, [...inputs].map(([name, input]) => [name, input.value])]);
    const untouched = values();
    manual.typed = () => panel.isConnected && values() !== untouched && values() !== drafted;
    const other = h("input", { type: "text", id: "manual-other", placeholder: "editor, address, school, …" });
    clear(panel, from.pdf ? note("", "Fields read from " + (names.get(from.pdf) || "the PDF") + " are filled in; change or empty any of them.") : null,
      field("Entry type", type), rows,
      h("div", { class: "row" }, h("div", { class: "grow" }, field("Another field's name", other)),
        button("Add this field", () => {
          const name = other.value.trim().toLowerCase();
          if (/^[a-z][a-z0-9_-]{0,31}$/.test(name) && !inputs.has(name)) { row(name, ""); inputs.get(name).focus(); other.value = ""; }
        })),
      h("div", { class: "row" }, button("Draft the entry", (event) => run(event.currentTarget, async () => {
        const fields = {};
        const omit = [];
        for (const [name, input] of inputs) {
          const value = input.value.trim();
          const read = prefill[name];
          if (value && (touched.has(name) || !read)) fields[name] = value;
          else if (!value && read) omit.push(name);
        }
        const sent = values();
        const item = await post("/api/add/manual", { entry_type: type.value, fields, pdf: from.pdf, model: from.model, omit });
        drafted = sent;
        took({ proposals: [item], errors: [] });
      }), { class: "primary", "data-action": "draft" }),
      button("Start again", (event) => run(event.currentTarget, async () => {
        if (manual.typed()) {
          const said = await ask({ title: "Discard what you typed?", body: "The manual form is emptied.", confirm: "Discard", danger: true });
          if (!said) return;
        }
        manual.pdf = null;
        manual.model = null;
        await redrawManual();
      }), { "data-action": "manual-discard" })));
  }

  async function redrawManual() {
    manual.typed = () => false;
    clear(manual.panel, h("p", { class: "muted", text: "…" }));
    await manualTab(manual.panel);
  }
  drafts.add(() => manual.typed());

  const view = tabs("Ways to add a reference", [
    ["Search", searchTab], ["Identifiers", identifierTab], ["PDF", pdfTab],
    ["Manual", (panel) => { manualTab(panel).catch((error) => add(panel, note("bad", error.message))); }],
  ]);
  clear(main, h("div", { class: "stack" }, h("h1", { text: "Add references" }), h("div", { class: "panel" }, view.el),
    log.el, h("h2", { text: "Proposals" }),
    h("p", { class: "muted", text: "Nothing is written until a proposal is accepted. An accepted entry is still subject to the checks before a send." }),
    proposals.el));
}
