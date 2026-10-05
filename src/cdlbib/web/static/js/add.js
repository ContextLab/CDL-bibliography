// Adding references: by search, by identifier, from a PDF, or typed by hand.
import { get, post, upload, blob } from "./api.js";
import { h, clear, button, field, list, table, note, kv, tabs, logPane, run, announce } from "./dom.js";
import { proposalList, candidateLine } from "./proposal.js";

const MAX_PDF = 50000000;

export async function show(main, ctx) {
  const proposals = proposalList({ verb: "Added" });
  const log = logPane("Lookup log");
  const manual = { pdf: null, model: null, prefill: {} };     // what the manual form starts from

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
    panel.append(field("Title (or part of it)", title), field("Authors (separate several with ;)", authors), field("Year (optional)", year),
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
    panel.append(field("DOIs, PMIDs or arXiv ids, one per line", text),
      h("div", { class: "row" }, button("Look up", (event) => run(event.currentTarget, async () => {
        log.clear();
        took(await post("/api/add/identifiers", { queries: text.value.split("\n").map((line) => line.trim()).filter(Boolean) }, log.add));
      }), { class: "primary" })));
  }

  // --- PDF ---
  function pdfTab(panel) {
    const file = h("input", { type: "file", id: "add-pdf", accept: "application/pdf,.pdf" });
    const out = h("div", { class: "stack" });
    panel.append(field("A PDF from this computer (up to 50 MB)", file), out);
    file.addEventListener("change", () => run(file, async () => {
      const chosen = file.files[0];
      if (!chosen) return;
      if (chosen.size > MAX_PDF) throw new Error("The file is larger than 50 MB.");
      log.clear();
      clear(out, h("p", { class: "muted", text: "Reading " + chosen.name + "…" }));
      const sent = await upload("/api/pdf/upload", null, chosen, "application/pdf");
      const read = await post("/api/pdf/read", { pdf: sent.pdf }, log.add);
      await drawPdf(out, read, chosen.name);
    }));
  }

  async function drawPdf(out, read, name) {
    const viewer = h("div");
    const result = h("div", { class: "stack", "aria-live": "polite" });
    const models = h("div", { class: "stack" });
    const image = h("div");
    const picture = async () => {
      const found = await post("/api/pdf/page", { pdf: read.pdf });
      clear(image, h("img", { class: "pdf-image", alt: "First page of " + name, src: "data:image/png;base64," + found.png }));
    };
    const asImage = button("Show the first page as an image", (event) => run(event.currentTarget, picture));
    if (navigator.pdfViewerEnabled === false) {
      // this browser shows no PDFs: the first page is drawn by the server instead
      viewer.append(h("p", { class: "muted", text: "This browser does not display PDFs; the first page is shown as an image." }), image);
      picture().catch((error) => clear(image, note("bad", error.message), asImage));
    } else {
      try {
        const url = URL.createObjectURL(await blob("/api/pdf/" + read.pdf + "/file"));
        viewer.append(h("iframe", { class: "pdf-frame", title: "The PDF: " + name, src: url + "#page=1" }));
      } catch (error) {
        viewer.append(note("bad", error.message));
      }
      viewer.append(h("div", { class: "row" }, asImage), image);
    }

    const facts = [kv([["Title read", read.title_guess], ["Read from", read.title_source], ["Pages read", String(read.pages.length)],
      ["Text", read.ocr ? "from OCR, which misreads characters" : null]])];
    if (read.problem) facts.unshift(note("bad", read.problem.replaceAll("_", " ") + (read.detail ? ": " + read.detail : "")));
    if (read.identifiers.length) {
      facts.push(table(["Identifier", "Value", "Page", "Read from"], read.identifiers.map((i) => [i.kind, i.value, i.page === null ? "metadata" : String(i.page), i.quote])));
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
          h("p", { class: "muted", text: route.how }))));
    }

    const byHand = button("Type it in by hand", () => { manual.pdf = read.pdf; view.select(3, true); });

    clear(out, h("div", { class: "two" }, viewer, h("div", { class: "stack" }, h("h3", { text: "What was read from " + name }), facts,
      h("div", { class: "row" }, lookup, byHand), result, models)));
    manual.pdf = read.pdf;
    manual.model = null;
    await routes(await get("/api/model-routes"));
  }

  // --- manual ---
  async function manualTab(panel) {
    const form = await get("/api/add/form");
    const from = { pdf: manual.pdf, model: manual.model };
    manual.prefill = from.pdf ? (await get("/api/pdf/prefill", from)).fields : {};
    const type = h("select", { id: "manual-type" }, form.types.map((name) => h("option", { value: name, text: name })));
    const inputs = new Map();
    const touched = new Set();
    const rows = h("div");
    function row(name, value) {
      const input = h("input", { type: "text", "data-field": name });
      input.value = value || "";
      input.addEventListener("input", () => touched.add(name));
      inputs.set(name, input);
      rows.append(field(name + (manual.prefill[name] ? " (read from the PDF)" : ""), input));
    }
    for (const name of [...new Set([...form.fields, ...Object.keys(manual.prefill)])]) row(name, manual.prefill[name]);
    const other = h("input", { type: "text", id: "manual-other", placeholder: "editor, address, school, …" });
    panel.append(manual.pdf ? note("", "Fields read from the PDF are filled in; change or empty any of them.") : null,
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
          const read = manual.prefill[name];
          if (value && (touched.has(name) || !read)) fields[name] = value;
          else if (!value && read) omit.push(name);
        }
        const item = await post("/api/add/manual", { entry_type: type.value, fields, pdf: from.pdf, model: from.model, omit });
        took({ proposals: [item], errors: [] });
      }), { class: "primary" })));
  }

  const view = tabs("Ways to add a reference", [
    ["Search", searchTab], ["Identifiers", identifierTab], ["PDF", pdfTab],
    ["Manual", (panel) => { manualTab(panel).catch((error) => panel.append(note("bad", error.message))); }, true],
  ]);
  clear(main, h("div", { class: "stack" }, h("h1", { text: "Add references" }), h("div", { class: "panel" }, view.el),
    h("details", null, h("summary", { text: "Lookup log" }), log.el), h("h2", { text: "Proposals" }),
    h("p", { class: "muted", text: "Nothing is written until a proposal is accepted. An accepted entry is still subject to the checks before a send." }),
    proposals.el));
}
