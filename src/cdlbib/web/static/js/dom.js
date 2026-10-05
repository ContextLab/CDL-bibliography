// Building the page. Text from the library, sources, PDFs and models is only ever set as
// text (textContent, or a text node): nothing here parses markup.

// Unsaved work, in one place: each editor, form or dialog that holds typed text adds a test
// that says whether it still does. Leaving a view, and closing or reloading the page, ask first
// while any test says yes; what is typed stays where it is until it is saved or discarded.
export const drafts = new Set();

export function unsaved() {
  for (const test of [...drafts]) {
    let found = false;
    try { found = test(); } catch (error) { found = false; }
    if (found) return true;
  }
  return false;
}

const PROPERTIES = new Set(["value", "checked", "disabled", "hidden", "selected", "multiple", "required", "readOnly"]);

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "text") el.textContent = String(value);
    else if (name === "on") for (const [event, fn] of Object.entries(value)) el.addEventListener(event, fn);
    else if (name === "class") el.className = value;
    else if (PROPERTIES.has(name)) el[name] = value;
    else el.setAttribute(name, value === true ? "" : String(value));
  }
  add(el, kids);
  return el;
}

// Append children; null, undefined and false are left out (never written as text), arrays are flattened.
export function add(el, ...kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export function clear(el, ...kids) {
  el.replaceChildren();
  return add(el, kids);
}

export function button(label, onClick, attrs) {
  return h("button", { type: "button", on: { click: onClick }, ...(attrs || {}) }, label);
}

export function field(label, control) {
  return h("label", { class: "field" }, label, control);
}

export function list(items, attrs) {
  return h("ul", { class: "plain", ...(attrs || {}) }, items.map((item) => h("li", null, item)));
}

export function kv(pairs) {
  return h("dl", { class: "kv" }, pairs.filter((pair) => pair && pair[1] !== null && pair[1] !== undefined && pair[1] !== "")
    .map(([name, value]) => [h("dt", { text: name }), h("dd", null, value)]));
}

export function table(headers, rows, attrs) {
  return h("div", { class: "scroll-x" }, h("table", { class: "grid", ...(attrs || {}) },
    h("thead", null, h("tr", null, headers.map((text) => h("th", { scope: "col", text })))),
    h("tbody", null, rows.map((row) => h("tr", null, row.map((cell) => h("td", null, cell)))))));
}

export function note(kind, ...kids) {
  return h("div", { class: "note " + (kind || "") }, kids);
}

export function words(status) {
  return String(status || "not checked").replaceAll("_", " ");
}

export function status(value) {
  return h("span", { class: "st st-" + String(value || "none").replace(/[^a-z_]/g, ""), text: words(value) });
}

// Any plain data as nested lists: what a source record, an attempt or a review record holds.
export function data(value) {
  if (value === null || value === undefined) return h("span", { class: "muted", text: "none" });
  if (Array.isArray(value)) {
    if (!value.length) return h("span", { class: "muted", text: "none" });
    if (value.every((item) => item === null || typeof item !== "object")) return h("span", { text: value.join("; ") });
    return list(value.map((item) => data(item)));
  }
  if (typeof value === "object") return kv(Object.entries(value).map(([name, item]) => [name, data(item)]));
  return h("span", { text: String(value) });
}

export function announce(text) {
  const region = document.getElementById("status");
  region.textContent = "";
  window.setTimeout(() => { region.textContent = text; }, 30);
}

export function alertBox(text, kind) {
  const region = document.getElementById("alerts");
  const box = h("div", { class: "alert " + (kind || "") }, h("pre", { text }),
    button("Close", () => box.remove(), { "aria-label": "Close this message" }));
  region.append(box);
  while (region.children.length > 4) region.firstChild.remove();
  if (kind === "info") window.setTimeout(() => box.remove(), 8000);
  return box;
}

export function showError(error) {
  alertBox(error && error.message ? error.message : String(error));
}

export function info(text) {
  alertBox(text, "info");
}

// Run an action from a control: the control is disabled while it runs, and a failure is announced.
export async function run(control, action) {
  if (control) control.disabled = true;
  try {
    return await action();
  } catch (error) {
    showError(error);
    return undefined;
  } finally {
    if (control) control.disabled = false;
  }
}

export function logPane(label) {
  const el = h("pre", { class: "log mono", role: "log", "aria-live": "polite", "aria-label": label || "Progress", tabindex: "0" });
  return {
    el,
    add(line) {
      el.append(line + "\n");
      el.scrollTop = el.scrollHeight;
    },
    clear() { el.textContent = ""; },
  };
}

export function tabs(label, items) {
  // items: [[name, render(panel)]]: a panel is drawn when first shown and kept, with whatever
  // was typed in it, for as long as the view is open.
  const buttons = items.map(([name], index) => h("button", {
    type: "button", role: "tab", id: "tab-" + Math.random().toString(36).slice(2), "aria-selected": "false", tabindex: "-1", text: name,
    on: { click: () => select(index) },
  }));
  const panels = buttons.map((tab) => h("div", { role: "tabpanel", tabindex: "0", hidden: true, "aria-labelledby": tab.id }));
  const drawn = new Set();
  function select(index, focus) {
    buttons.forEach((b, i) => {
      b.setAttribute("aria-selected", i === index ? "true" : "false");
      b.tabIndex = i === index ? 0 : -1;
      panels[i].hidden = i !== index;
    });
    if (!drawn.has(index)) {
      drawn.add(index);
      clear(panels[index]);
      items[index][1](panels[index]);
    }
    if (focus) buttons[index].focus();
  }
  const strip = h("div", { role: "tablist", "aria-label": label, on: {
    keydown: (event) => {
      const at = buttons.indexOf(document.activeElement);
      const move = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (at < 0 || !move) return;
      event.preventDefault();
      select((at + move + buttons.length) % buttons.length, true);
    },
  } }, buttons);
  select(0);
  return { el: h("div", null, strip, panels), select };
}

// A modal question. fields: [{name, label, multiline, required, value}];
// choices: [{value, label, kind}] (default: Cancel and one confirming button).
// Resolves to null when dismissed, else {choice, values}.
export function ask({ title, body, fields, confirm, danger, choices }) {
  return new Promise((resolve) => {
    const inputs = (fields || []).map((spec) => {
      const control = spec.multiline ? h("textarea", { name: spec.name, required: spec.required, rows: "4" })
        : h("input", { type: "text", name: spec.name, required: spec.required });
      control.value = spec.value || "";
      return [spec, control];
    });
    const lines = [body].flat().filter((item) => item !== null && item !== undefined);
    let answer = null;
    let warned = false;
    const typed = () => inputs.some(([spec, control]) => control.value.trim() !== (spec.value || "").trim());
    const warning = h("p", { class: "differs", role: "status" });
    const holds = () => dialog.open && typed();
    // Dismissing a dialog that holds typed text takes a second, explicit step.
    const dismiss = () => {
      if (typed() && !warned) {
        warned = true;
        warning.textContent = "What you typed here is not kept. Cancel again to discard it.";
        return false;
      }
      return true;
    };
    const done = (choice) => {
      if (choice === null && !dismiss()) return;
      if (choice !== null) {
        const missing = inputs.find(([spec, control]) => spec.required && !control.value.trim());
        if (missing) { missing[1].focus(); return; }
        answer = { choice, values: Object.fromEntries(inputs.map(([spec, control]) => [spec.name, control.value])) };
      }
      dialog.close();
    };
    const heading = h("h2", { id: "dialog-title", text: title });
    const offered = choices
      ? h("div", { class: "choices" }, choices.map((c) => button(c.label, () => done(c.value), { class: c.kind || "" })),
          button("Cancel", () => done(null)))
      : h("div", { class: "actions" }, button("Cancel", () => done(null)),
          button(confirm || "Continue", () => done("yes"), { class: danger ? "danger" : "primary" }));
    const dialog = h("dialog", { "aria-labelledby": "dialog-title" }, heading,
      lines.map((line) => (line instanceof Node ? line : h("pre", { text: line }))),
      inputs.map(([spec, control]) => field(spec.label, control)), warning, offered);
    dialog.addEventListener("cancel", (event) => { if (!dismiss()) event.preventDefault(); });
    dialog.addEventListener("close", () => { drafts.delete(holds); dialog.remove(); resolve(answer); });
    drafts.add(holds);
    document.body.append(dialog);
    dialog.showModal();
    if (inputs.length) inputs[0][1].focus();
  });
}

export function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = h("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
}
