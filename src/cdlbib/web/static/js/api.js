// Requests to this server. The run's token is kept in this module's memory only and sent as a
// header; it is never put in an address.
import { ask, h, clear } from "./dom.js";

let token = null;
let active = 0;

export function setToken(value) { token = value; }
export function hasToken() { return token !== null; }

export class ApiError extends Error {
  constructor(found) {
    super(found.message || "The request failed.");
    this.kind = found.kind;
    this.data = found;
  }
}

const queued = new Set();        // jobs of this page that wait behind the one that is running

function busy(change) {
  active += change;
  const el = document.getElementById("activity");
  if (!el) return;
  el.classList.toggle("on", active > 0);
  if (active <= 0) { el.textContent = ""; return; }
  if (!queued.size) { el.textContent = "Working…"; return; }
  if (el.querySelector("button")) return;
  clear(el, "Waiting for the job that is running… ", h("button", { type: "button", text: "Cancel what is waiting",
    on: { click: () => { for (const job of [...queued]) cancel(job).catch(() => {}); } } }));
}

// Cancel a job that has not started (one that runs is left to finish).
export async function cancel(job) {
  const response = await send("POST", "/api/jobs/" + job + "/cancel", { json: {} });
  return (await response.json()).result;
}

async function send(method, path, { query, json, body, type } = {}) {
  const headers = { "X-CDLBIB-Token": token };
  let payload;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(json); }
  if (body !== undefined) { headers["Content-Type"] = type; payload = body; }
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(query || {})) {
    if (value === null || value === undefined || value === "") continue;
    search.set(name, value === true ? "1" : String(value));
  }
  const text = search.toString();
  let response;
  try {
    response = await fetch(path + (text ? "?" + text : ""), {
      method, headers, body: payload, cache: "no-store", credentials: "omit", redirect: "error", referrerPolicy: "no-referrer",
    });
  } catch (error) {
    throw new ApiError({ kind: "Unreachable", message: "The cdlbib server did not answer. It runs while `cdlbib web` is running in the terminal." });
  }
  return response;
}

async function answer(response, onLine) {
  let found;
  try { found = await response.json(); } catch (error) { found = { error: { kind: "BadAnswer", message: "The server's answer could not be read." } }; }
  if (found.error) throw new ApiError(found.error);
  if (found.job) return follow(found.job, onLine);
  return found.result;
}

// Poll a job until it is done; each new progress line goes to onLine.
export async function follow(job, onLine) {
  let after = 0;
  for (;;) {
    const response = await send("GET", "/api/jobs/" + job, { query: { after } });
    const found = await response.json();
    if (found.error) throw new ApiError(found.error);
    const view = found.result;
    for (const line of view.lines) if (onLine) onLine(line);
    after = view.next;
    const waits = !view.done && !view.running;
    if (waits !== queued.has(job)) {
      if (waits) queued.add(job); else queued.delete(job);
      busy(0);
    }
    if (view.done) {
      if (view.error) throw new ApiError(view.error);
      return view.result;
    }
  }
}

async function call(method, path, options, onLine) {
  busy(1);
  try {
    return await answer(await send(method, path, options), onLine);
  } finally {
    busy(-1);
  }
}

export function get(path, query, onLine) {
  return call("GET", path, { query }, onLine);
}

// A POST. When the server stops to ask (a package to install, a fork to create: `--ask`),
// the question is put to the person and the request is sent again with the explicit flag.
export async function post(path, json, onLine) {
  try {
    return await call("POST", path, { json: json || {} }, onLine);
  } catch (error) {
    const wanted = error instanceof ApiError && error.data.needs_confirmation;
    const flag = { install: "allow_install", fork: "allow_fork_creation" }[wanted];
    if (!flag || (json && json[flag])) throw error;
    const said = await ask({ title: "cdlbib asks", body: error.data.question, confirm: "Yes" });    // the core's question, word for word
    if (!said) throw error;
    return post(path, { ...(json || {}), [flag]: true }, onLine);
  }
}

export function upload(path, query, file, type) {
  return call("POST", path, { query, body: file, type });
}

export async function blob(path) {
  busy(1);
  try {
    const response = await send("GET", path);
    if (!response.ok) {
      let found = null;
      try { found = (await response.json()).error; } catch (error) { found = null; }
      throw new ApiError(found || { kind: "BadAnswer", message: "The file could not be fetched." });
    }
    return await response.blob();
  } finally {
    busy(-1);
  }
}
