"""The web interface's endpoints: an explicit table of route -> api function -> the argument
names it takes, each with its type. Nothing is passed through: a request naming any other
argument is refused by name, and no argument is a filesystem path. Each handler is input
checking, one action of cdlbib.api, and the result as plain data."""
import base64
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field, replace

from .. import api, deps, prompts
from ..errors import CdlbibError, UpdateNeedsDecision
from .store import ID, MANUSCRIPT_TYPES, Full, Missing

# Names no endpoint takes, whatever the route: where a change goes, what it is compared
# with, which cache or ledger is used, and anything that names a file.
NEVER = frozenset({"database", "reference", "ledger", "upstream", "fork", "outfile", "autofix", "engine",
                   "citations", "mailto", "path", "file", "out", "inputs", "paper", "force", "base", "bars",
                   "fingerprints", "verbose", "all_entries", "client", "reviewer", "login", "ws"})
NO_BBL = ("A compiled .bbl is not made here. In a terminal: cdlbib export PAPER --bbl "
          "(PAPER is the paper's main .tex file or its folder).")
READ_FROM = {"aux": "the .aux file", "bcf": "the .bcf file", "compiled": "a fresh LaTeX run of the paper",
             "source": "the .tex source"}


class Bad(Exception):
    """A request the table does not allow (HTTP 400)."""


class Refusal(Exception):
    """A refusal of this server's own, with a kind for the page to act on (and more to show)."""

    def __init__(self, kind, message, **extra):
        self.kind, self.extra = kind, extra
        super().__init__(message)


class Reply(Exception):
    """An error of the core with more for the page to show or ask (``extra``)."""

    def __init__(self, cause, **extra):
        self.cause, self.extra = cause, extra
        super().__init__(str(cause))


# --- argument types ------------------------------------------------------------------------------

class Text:
    def __init__(self, limit=2000, pattern=None, optional=False):
        self.limit, self.pattern, self.optional = limit, re.compile(pattern) if pattern else None, optional

    def check(self, name, value):
        if value is None and self.optional:
            return None
        if not isinstance(value, str):
            raise Bad(f"{name} must be text")
        if len(value) > self.limit:
            raise Bad(f"{name} is longer than {self.limit} characters")
        if "\x00" in value or (self.pattern and not self.pattern.fullmatch(value)):
            raise Bad(f"{name} is not of the expected form")
        return value


class Ident(Text):
    """An id this server issued."""

    def __init__(self, optional=False):
        super().__init__(limit=22, pattern=ID.pattern.replace(r"\Z", ""), optional=optional)


class Flag:
    def check(self, name, value):
        if value in (None, False, "0", "false", ""):
            return False
        if value in (True, "1", "true"):
            return True
        raise Bad(f"{name} must be true or false")


class Whole:
    def __init__(self, low=0, high=10 ** 9, default=None):
        self.low, self.high, self.default = low, high, low if default is None else default

    def check(self, name, value):
        if isinstance(value, str) and re.fullmatch(r"\d{1,10}", value):
            value = int(value)
        if value is None:
            return self.default
        if isinstance(value, bool) or not isinstance(value, int) or not self.low <= value <= self.high:
            raise Bad(f"{name} must be a whole number from {self.low} to {self.high}")
        return value


class Choice:
    def __init__(self, *options, optional=False):
        self.options, self.optional = options, optional

    def check(self, name, value):
        if value is None and self.optional:
            return None
        if not isinstance(value, str) or value not in self.options:
            raise Bad(f"{name} must be one of: {', '.join(self.options)}")
        return value


class Texts:
    def __init__(self, most=50, each=None, least=0):
        self.most, self.each, self.least = most, each or Text(500), least

    def check(self, name, value):
        if value is None:
            return []
        if isinstance(value, str):      # a query string gives one value
            value = [value]
        if not isinstance(value, list) or not self.least <= len(value) <= self.most:
            raise Bad(f"{name} must be a list of {self.least} to {self.most} items")
        return [self.each.check(name, item) for item in value]


class Fields:
    """{field name: value} of a hand-typed entry."""
    NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")

    def check(self, name, value):
        if value is None:
            return {}
        if not isinstance(value, dict) or len(value) > 40:
            raise Bad(f"{name} must be at most 40 named fields")
        for key, item in value.items():
            if not self.NAME.fullmatch(str(key)) or not isinstance(item, str) or len(item) > 5000 or "\x00" in item:
                raise Bad(f"{name} holds a field that is not of the expected form")
        return dict(value)


KEY = Text(200, r"[^\s{},\\%#~\"']+")
RAW = Text(100_000)
FINGERPRINT = Text(128, r"[0-9A-Za-z:_-]+")
INSTALL = {"allow_install": Flag()}


@dataclass
class Route:
    method: str
    path: str                    # "{id}" segments are ids this server issued
    api: str                     # the cdlbib.api function(s) the handler calls ("" when none)
    handler: object
    args: dict = field(default_factory=dict)
    wait: float = 0.0            # seconds the request waits for the job; 0: the job's id is returned at once
    body: str = "json"           # "json" | "pdf" | "file" (an upload)
    answer: str = "json"         # "json" | "bytes" (the handler returns (content type, bytes, download name))
    direct: bool = False         # no api call: answered by the request thread (the store, the job list)
    single: bool = False         # a repeat is pointless: a request of this kind that is already waiting is joined


# --- data ----------------------------------------------------------------------------------------

def summaries(app):
    """(tag, [EntrySummary]) of the library as it is now. The snapshot is kept with the
    api.revision it was built from and is rebuilt whenever the revision differs (a save, an
    approval, a check, or another program's edit); nothing else moves that marker, so no
    request can hide a change. The tag names one reading; the page reloads its list when it
    differs."""
    now = api.revision(app.ws)
    if app.cached is None or app.cached[0] != now:
        app.generation += 1
        app.cached = (now, str(app.generation), api.entries(app.ws))
    return app.cached[1], app.cached[2]


STALE = ("This proposal was checked again after the version you acted on was shown. Nothing was done; "
         "the current version is shown now.")


def latest(app, found):
    """The id of the newest version of the proposal ``found`` is a version of."""
    while True:
        after = app.store.get("proposal", found)["replaced"]
        if after is None:
            return found
        found = after


def current(app, found):
    """The stored proposal ``found``, which must be the version that is current: a proposal is
    never changed in place, each recheck or choice makes a new version under a new id, and a
    decision names exactly the version it was made on."""
    held = app.store.get("proposal", found)
    if held["replaced"] is not None:
        raise Refusal("StaleProposal", STALE, current=latest(app, found))
    if held["written"]:
        raise Refusal("AlreadyWritten", f"{held['written']} is written already.")
    return held


def proposal_data(app, found):
    held = app.store.get("proposal", found)
    proposal = held["proposal"]
    data = api.intake_data(proposal)
    data.update(id=found, pdf=held["pdf"], in_library=held["in_library"], acceptable=api.acceptable(proposal),
                why_not=api.why_not_acceptable(proposal), written=held["written"],
                failed=api.proposal_failed(proposal), superseded=held["replaced"],
                name_choices=[{"field": field, "typed": typed, "source": source}
                              for field, typed, source in api.name_choices(proposal)])
    return data


def keep(app, proposal, pdf=None, in_library=False):
    return proposal_data(app, app.store.put("proposal", {"proposal": proposal, "pdf": pdf, "in_library": in_library,
                                                         "replaced": None, "written": None}))


def version(app, found, held, proposal):
    """Keep ``proposal`` as the next version of ``found``; the older id then only says so."""
    data = keep(app, proposal, pdf=held["pdf"], in_library=held["in_library"])
    held["replaced"] = data["id"]
    return data


def kept(app, results, **how):
    return {"proposals": [keep(app, item, **how) for item in results],
            "errors": [list(error) for error in getattr(results, "errors", [])]}


def format_data(fmt):
    return {"ok": fmt.ok, "failure": fmt.failure, "errors": [str(item) for item in fmt.errors][:5000],
            "forced": [f"{key}: {prompts.FORCE_REFUSED}" for key in fmt.forced],
            "corrections": api.as_data(fmt.corrections), "log": fmt.log[-50_000:]}


def check_data(check):
    cited = check.citations
    return {"ok": bool(check.ok), "format": format_data(check.format), "citations_due": check.citations_due,
            "citations": None if cited is None else {
                "ok": bool(cited.ok), "unresolved": api.as_data(cited.unresolved), "library": api.as_data(cited.library),
                "lines": list(cited.lines),
                "checked": {key: {"status": found.get("status"), "issues": api.as_data(found.get("issues") or [])}
                            for key, found in cited.checked.items()}}}


def applied_data(applied):
    return {"written": list(applied.written), "removed": list(applied.removed), "renamed": dict(applied.renamed),
            "refused": [list(item) for item in applied.refused],
            "outcomes": [{"index": o.index, "key": o.key, "status": o.status, "reason": o.reason} for o in applied.outcomes],
            "backup": applied.backup.stamp if applied.backup is not None else None,
            "saved_copy": str(applied.saved_copy) if applied.saved_copy else None, "notes": list(applied.notes)}


def backup_data(backup, only_copy=False):
    return {"line": prompts.backup_line(backup, only_copy=only_copy), "stamp": backup.stamp, "when": backup.when, "branch": backup.branch, "commit": backup.commit[:8],
            "changed": len(backup.changed), "has_bundle": backup.has_bundle}


EXTRA = {"EditRefused": ("problems",), "UpdateConflict": ("entries", "files"),
         "MissingDependency": ("package", "extra", "feature"), "PublishRefused": ("needs_fork", "upstream"),
         "ExportFailed": ("names",), "TexLinkRefused": ("status",),
         "UpdateNeedsDecision": ("changed", "entries_changed", "new_commits", "local_commits", "choices", "branch",
                                 "pull_request", "state", "default", "rewritten")}


def failure(exc):
    """The error a job or a request reports: {kind: the exception's class, message, ...}."""
    if isinstance(exc, Reply):
        return dict(failure(exc.cause), **exc.extra)
    if isinstance(exc, Refusal):
        return dict({"kind": exc.kind, "message": str(exc)}, **exc.extra)
    if isinstance(exc, Full):
        return {"kind": "QuotaExceeded", "message": str(exc)}
    if isinstance(exc, Bad):
        return {"kind": "BadRequest", "message": str(exc)}
    if isinstance(exc, Missing):
        return {"kind": "NotFound", "message": exc.args[0]}
    if not isinstance(exc, CdlbibError):
        return {"kind": "InternalError", "message": f"{type(exc).__name__}: {exc}"}
    plain = api.as_data(exc)
    data = {"kind": plain["error_kind"], "message": plain["error"]}
    for name in EXTRA.get(data["kind"], ()):
        data[name] = api.as_data(getattr(exc, name, None))
    if data["kind"] == "NeedsConfirmation":       # the page asks ``question`` and sends the request again with the allow flag
        data.update(needs_confirmation=exc.kind, question=exc.question, package=exc.package, extra=exc.extra,
                    feature=exc.feature, upstream=exc.upstream)
    if data["kind"] == "ExportFailed":
        data["reason"] = exc.kind
    if data["kind"] == "GateFailed" and exc.check is not None:
        data["check"] = check_data(exc.check)
    return data


def guarded(app, route, args):
    """The job of a request: the handler, run through api.attempt, the core's one rule for a
    missing optional package and a missing fork (go on after saying so; with --ask, stop with
    NeedsConfirmation until the page sends the person's explicit yes). A route that does not
    take the allow flags (a read) is not retried."""
    def call(say):
        if "allow_install" not in route.args:
            return route.handler(app, args, say)

        def run(allow_fork_creation=False):
            return route.handler(app, dict(args, allow_fork_creation=allow_fork_creation), say)
        return api.attempt(run, allow_install=True if args["allow_install"] else None,
                           allow_fork=True if args.get("allow_fork_creation") else None, progress=say)
    return call


def not_managed(app):
    """The sentence for a library the user chose: cdlbib neither updates nor backs it up."""
    return (f"This library ({app.ws.root}) was chosen by: {prompts.CHOSEN_BY[app.origin]}. It is not the copy cdlbib "
            "downloads and manages, so cdlbib does not update it, keeps no backups of it and has nothing to undo.")


def managed_only(app):
    if not api.is_managed(app.ws):
        raise Refusal("NotManaged", not_managed(app))


# --- handlers: the session and the jobs (no api call) -------------------------------------------

def session(app, a, say):
    from .. import __version__
    return {"version": __version__, "root": str(app.ws.root), "bib": str(app.ws.bib), "managed": app.managed,
            "origin": app.origin, "not_managed": None if app.managed else not_managed(app),
            "ask": deps.ask(), "prepare": app.prepare_job, "daily": app.daily_job, "identity": app.identity,
            "chosen_by": dict(prompts.CHOSEN_BY), "probes": list(api.PROBES), "no_bbl": NO_BBL,
            "manuscript_types": list(MANUSCRIPT_TYPES)}


def job(app, a, say):
    found = app.worker.get(a["id"])
    if found is None:
        raise Missing("no job with that id")
    view = found.view(a["after"], seconds=1.0)
    if view["done"] and a["id"] == app.daily_job:
        app.daily_job = None            # the daily check's outcome is shown once, by the page that fetched it
    return view


def job_cancel(app, a, say):
    found = app.worker.cancel(a["id"])
    if found is None:
        raise Missing("no job with that id")
    return {"cancelled": found == "cancelled", "state": found}


# --- handlers: the library -------------------------------------------------------------------------

def entries(app, a, say):
    revision, found = summaries(app)
    return {"revision": revision,
            "columns": ["key", "type", "authors", "year", "title", "venue", "doi", "status", "issues"],
            "rows": [[e.key, e.type, e.authors, e.year, e.title, e.venue, e.doi, e.status, len(e.issues)] for e in found],
            "counts": dict(Counter(e.status for e in found))}


def search(app, a, say):
    revision, found = summaries(app)
    return {"revision": revision, "keys": [e.key for e in api.search(found, a["q"] or "", status=a["status"])]}


def revision(app, a, say):
    return {"revision": summaries(app)[0]}


def entry(app, a, say):
    return api.as_data(api.entry(app.ws, a["key"]))


def review_queue(app, a, say):
    tag, listed = summaries(app)
    found = api.review_queue(app.ws, all_entries=a["all"])
    if a["q"]:
        wanted = {item.key for item in api.search(listed, a["q"])}
        found = [detail for detail in found if detail.key in wanted]
    page = found[a["offset"]:a["offset"] + a["limit"]]
    return {"all": a["all"], "revision": tag, "total": len(found), "offset": a["offset"], "limit": a["limit"], "entries": [
        {"key": d.key, "fingerprint": d.fingerprint, "status": d.result.get("status"),
         "issues": api.as_data(d.result.get("issues") or []), "title": d.fields.get("title", ""),
         "authors": d.fields.get("author") or d.fields.get("editor") or "", "year": d.fields.get("year", "")}
        for d in page]}


def preview_edit(app, a, say):
    """``opened``: the fingerprint the entry had when the editor was opened. The save that
    follows is bound to it, not to the entry as it is at preview time, so a change made on
    disk in between is refused by the writer instead of becoming the new baseline."""
    preview = api.preview_edit(app.ws, a["key"], a["raw"])
    data = api.as_data(preview)
    expected = a["opened"] if a["key"] and a["opened"] else preview.fingerprint
    data["changed_on_disk"] = expected != preview.fingerprint
    data["preview"] = app.store.put("preview", {"key": a["key"], "raw": a["raw"], "fingerprint": expected})
    return data


def save_edit(app, a, say):
    held = app.store.get("preview", a["preview"])
    applied = api.save_edit(app.ws, held["key"], held["raw"], held["fingerprint"])
    app.store.drop("preview", a["preview"])
    return applied_data(applied)


def check_keys(app, a, say):
    return check_data(api.check_keys(app.ws, a["keys"], progress=say))


def check_changed(app, a, say):
    return check_data(api.check_library(app.ws, progress=say))


def check_format(app, a, say):
    return format_data(api.check_format(app.ws))


def approve(app, a, say):
    return {"stored": api.as_data(api.approve(app.ws, a["key"], a["fingerprint"], a["source"], a["note"]))}


def revoke(app, a, say):
    return api.as_data(api.revoke(app.ws, a["key"], a["reason"], expected_fingerprint=a["fingerprint"]))


def identity(app, a, say):
    found = next(item for item in api.features(probe=("github",), progress=say) if item.name == "gh login")
    app.identity = api.as_data(found)
    return app.identity


# --- handlers: adding ------------------------------------------------------------------------------

def add_search(app, a, say):
    found = api.find_candidates(app.ws, title=a["title"] or None, authors=a["authors"], year=a["year"] or None,
                                progress=say)
    data = api.intake_data(found)
    data["search"] = app.store.put("search", {"leads": list(found), "pdf": None})
    return data


def add_choose(app, a, say):
    """The proposal for a chosen lead. A lead that was found for an uploaded PDF keeps that
    PDF with it, so the proposal is shown beside the PDF's first page like any other from it."""
    held = app.store.get("search", a["search"])
    if a["index"] >= len(held["leads"]):
        raise Bad("index: no such candidate")
    return kept(app, api.propose_new(app.ws, [api.candidate_query(held["leads"][a["index"]])], progress=say), pdf=held["pdf"])


def add_identifiers(app, a, say):
    queries = [text.strip() for text in a["queries"] if text.strip()]
    if not queries:
        raise Bad("queries: give at least one DOI, PMID, arXiv id or title")
    return kept(app, api.propose_new(app.ws, queries, progress=say))


def _read(app, found):
    held = app.store.get("pdf", found)
    if held["intake"] is None:
        raise Bad("pdf: this PDF has not been read yet")
    return held["intake"]


def add_manual(app, a, say):
    prefill = None
    if a["pdf"]:
        model = app.store.get("proposal", a["model"])["proposal"] if a["model"] else None
        prefill = {name: value for name, value in api.manual_prefill(_read(app, a["pdf"]), model).items()
                   if name not in a["omit"]}
    return keep(app, api.draft_manual(app.ws, a["fields"], entry_type=a["entry_type"], prefill=prefill), pdf=a["pdf"])


def draft_form(app, a, say):
    return api.draft_form()


def model_routes(app, a, say):
    return {"routes": api.as_data(api.model_routes())}


def model_routes_check(app, a, say):
    return {"routes": api.as_data(api.model_routes(probe=(a["route"],)))}


def pdf_upload(app, a, say, body):
    if not body.startswith(b"%PDF-"):
        raise Bad("The file does not start as a PDF (no %PDF- header).")
    return {"pdf": app.store.add_pdf(body), "bytes": len(body)}


def _intake_data(read, found):
    data = api.intake_data(read)
    data.pop("path", None)
    data["pdf"] = found
    return data


def pdf_read(app, a, say):
    held = app.store.get("pdf", a["pdf"])
    held["intake"] = api.read_pdf(held["path"], progress=say)
    return _intake_data(held["intake"], a["pdf"])


def pdf_lookup(app, a, say):
    result = api.propose_from_pdf(app.ws, _read(app, a["pdf"]), progress=say)
    return {"pdf": a["pdf"], "message": result.message, "tried": list(result.tried), "matched": result.matched,
            "found_by": api.intake_data(result.found_by), "prefill": dict(result.prefill),
            "proposal": keep(app, result.proposal, pdf=a["pdf"]) if result.proposal is not None else None,
            "candidates": api.intake_data(result.candidates),
            "search": app.store.put("search", {"leads": list(result.candidates), "pdf": a["pdf"]}) if result.candidates else None}


def pdf_model(app, a, say):
    return keep(app, api.read_pdf_with_model(app.ws, _read(app, a["pdf"]), route=a["route"], progress=say), pdf=a["pdf"])


def pdf_prefill(app, a, say):
    model = app.store.get("proposal", a["model"])["proposal"] if a["model"] else None
    return {"fields": api.manual_prefill(_read(app, a["pdf"]), model)}


def pdf_file(app, a, say):
    return "application/pdf", app.store.get("pdf", a["id"])["path"].read_bytes(), None


def pdf_page(app, a, say):
    png = api.render_first_page(app.store.get("pdf", a["pdf"])["path"])
    return {"png": base64.b64encode(png).decode("ascii")}


# --- handlers: one proposal ------------------------------------------------------------------------

def proposal(app, a, say):
    return proposal_data(app, a["proposal"])


def _accepted(app, found, held, data):
    """A proposal is done with once the writer confirms it (its outcome is "written" or
    "removed"). One whose entry is written while its model evidence could not be stored
    stays, marked as written, so that the page keeps showing what is still owed."""
    done = [item for item in data["outcomes"] if item["status"] in ("written", "removed")]
    if data.get("evidence_stored") is False:
        held["written"] = data.get("key")
    elif done:
        app.store.drop("proposal", found)
    return data


def proposal_accept(app, a, say):
    held = current(app, a["proposal"])
    item = held["proposal"]
    why = api.why_not_acceptable(item)
    if why:
        raise Refusal("NotAcceptable", "; ".join(why), why_not=why)
    if item.manual:
        done = api.accept_draft(app.ws, item, pdf=_read(app, held["pdf"]) if held["pdf"] else None)
        data = dict(applied_data(done.applied), key=done.key, fingerprint=done.fingerprint,
                    evidence_stored=done.evidence_stored, evidence_error=done.evidence_error)
    else:
        data = applied_data(api.apply_proposals(app.ws, [item]))
    return _accepted(app, a["proposal"], held, data)


def proposal_remove_duplicate(app, a, say):
    held = current(app, a["proposal"])
    item = held["proposal"]
    if not (item.duplicate_of and item.duplicate_in_library):
        raise Bad("proposal: this is not a typed duplicate of a library entry")
    return _accepted(app, a["proposal"], held, applied_data(api.apply_proposals(app.ws, [replace(item, remove_duplicate=True)])))


def proposal_accept_remaining(app, a, say):
    chosen, stale = [], []
    for found in dict.fromkeys(a["proposals"]):
        held = app.store.get("proposal", found)
        item = held["proposal"]
        if held["replaced"] is not None or held["written"]:
            stale.append(found)                 # not the version on the page: left for a decision of its own
        elif api.acceptable(item) and not item.needs_decision and not item.manual:
            chosen.append((found, item))
    data = applied_data(api.apply_proposals(app.ws, [item for _, item in chosen]))
    # The writer says what it did with each accepted proposal, by its place in the list.
    by_place = {item["index"]: item for item in data["outcomes"]}
    data["accepted"] = [found for place, (found, _) in enumerate(chosen)
                        if by_place.get(place, {}).get("status") in ("written", "removed")]
    data["not_written"] = [{"id": found, "key": by_place[place]["key"], "reason": by_place[place]["reason"]}
                           for place, (found, _) in enumerate(chosen)
                           if place in by_place and by_place[place]["status"] == "refused"]
    data["stale"] = stale
    for found in data["accepted"]:
        app.store.drop("proposal", found)
    return data


def proposal_recheck(app, a, say):
    held = current(app, a["proposal"])
    return version(app, a["proposal"], held, api.recheck_proposal(app.ws, held["proposal"], a["raw"]))


def proposal_candidate(app, a, say):
    held = current(app, a["proposal"])
    leads = held["proposal"].candidates
    if a["index"] >= len(leads):
        raise Bad("index: no such candidate")
    return version(app, a["proposal"], held,
                   api.choose_candidate(app.ws, held["proposal"], leads[a["index"]], in_library=held["in_library"]))


def proposal_names(app, a, say):
    """The author or editor list settled name by name: for each name the typed one or the
    source's (the page sends which, never the names)."""
    held = current(app, a["proposal"])
    for field, typed, source in api.name_choices(held["proposal"]):
        if field == a["field"]:
            if len(a["picks"]) != len(typed):
                raise Bad("picks: one choice for each name")
            names = [theirs if pick == "source" else mine for pick, mine, theirs in zip(a["picks"], typed, source)]
            return version(app, a["proposal"], held, api.resolve_names(app.ws, held["proposal"], field, names))
    raise Bad("field: this proposal has no such list of names to settle")


def proposal_skip(app, a, say):
    current(app, a["proposal"])
    app.store.drop("proposal", a["proposal"])
    return {"skipped": a["proposal"]}


# --- handlers: sending -----------------------------------------------------------------------------

def offers_next(app, a, say):
    """The next completion offer for a changed entry that is not yet accepted. An entry that
    was offered is not offered again in this run while its content stays the same (the CLI's
    rule for `verify` followed by `send`), whatever was decided about it."""
    if app.offered is not None:
        try:
            app.seen.add((str(app.ws.bib), app.offered, api.entry(app.ws, app.offered).fingerprint))
        except CdlbibError:
            pass                                # the entry is gone or renamed: nothing to remember
        app.offered = None
    if a["restart"] or app.offers is None:
        app.offers = api.completion_offers(app.ws, seen=app.seen)
    for offer in app.offers:
        app.offered = offer.key
        if offer.error is not None:
            return {"done": False, "offer": {"key": offer.key, "error": offer.error, "error_kind": offer.error_kind,
                                             "proposals": []}}
        if offer.proposals:
            return {"done": False, "offer": {"key": offer.key, "error": None,
                                             "proposals": [keep(app, item, in_library=True) for item in offer.proposals]}}
    app.offers = app.offered = None
    return {"done": True, "offer": None}


def completion_due(app, a, say):
    return api.as_data(api.completion_due(app.ws))


def send(app, a, say):
    def report(check):
        for line in ([] if check.format.ok else format_data(check.format)["forced"]):
            say(line)
        say("format: looks good!" if check.format.ok else f"errors found: {check.format.failure or 'see the format check'}")

    return api.as_data(api.send_checked(app.ws, summary=a["summary"] or None, progress=say, report=report,
                                        allow_fork_creation=a["allow_fork_creation"]))


def evidence_pending(app, a, say):
    return {"pending": api.as_data(api.pending_evidence(app.ws))}


def evidence_retry(app, a, say):
    done = api.retry_evidence(app.ws, a["key"])
    if done.evidence_stored and a["proposal"]:
        app.store.drop("proposal", a["proposal"])       # the card that waited for this is done with
    return {"key": done.key, "fingerprint": done.fingerprint, "evidence_stored": done.evidence_stored,
            "evidence_error": done.evidence_error}


# --- handlers: the state of the library --------------------------------------------------------------

def _state(app, found):
    data = api.as_data(found)
    data["not_managed"] = None if found.managed else not_managed(app)
    # as `cdlbib where` prints it
    data["last_check_text"] = found.last_check.strftime("%Y-%m-%d %H:%M UTC") if found.last_check else "never"
    return data


def state(app, a, say):
    return _state(app, api.library_state(app.ws))


def state_refresh(app, a, say):
    return _state(app, api.library_state(app.ws, refresh=True, progress=say))


def backups(app, a, say):
    managed_only(app)
    saved = api.backups()
    return {"root": str(api.managed_root()), "folder": str(api.backups_folder()),
            "backups": [backup_data(item, only_copy=api.holds_only_copy(item)) for item in saved],
            "unreadable": [list(item) for item in api.unreadable_backups()],
            "checkpoint": api.completion_undo_checkpoint()}


def asks(app, exc):
    """UpdateNeedsDecision as the page is given it: the question and the answers in the
    words of ``prompts``, and the id under which what the question is about is kept."""
    asked = prompts.answers(exc)
    # prompts.unsent_question is the terminal's text: the sentences, then one "[letter] answer"
    # line per choice. A page shows the answers as buttons (the same words, from prompts.answers),
    # so those lines are left out here; every other line is the core's, unchanged.
    lettered = {f"  [{letter}] {words}" for letter, words in asked.values()}
    question = "\n".join(line for line in prompts.unsent_question(exc).splitlines() if line not in lettered)
    return Reply(exc, question=question, answers={choice: asked[choice][1] for choice in exc.choices},
                 decision=app.store.put("decision", {"seen": exc.seen, "choices": tuple(exc.choices)}))


def update(app, a, say):
    managed_only(app)
    try:
        return api.as_data(api.update(app.ws, force=True, progress=say))
    except UpdateNeedsDecision as exc:
        raise asks(app, exc) from exc


def daily(app):
    """The job run once when the server starts on the managed library: the daily check of
    every command (api.update without force: nothing is fetched when the last check is under
    a day old). Unsent work is never touched: the page asks, as for an update asked for."""
    def call(say):
        try:
            return api.as_data(api.update(app.ws, progress=say))
        except UpdateNeedsDecision as exc:
            raise asks(app, exc) from exc
    return call


def update_decide(app, a, say):
    managed_only(app)
    held = app.store.get("decision", a["decision"])
    if a["choice"] not in held["choices"]:
        raise Bad("choice: not one of the choices that were offered")
    result = api.update(app.ws, decision=a["choice"], force=True, progress=say, seen=held["seen"])
    app.store.drop("decision", a["decision"])
    return dict(api.as_data(result), decision=a["choice"])


def undo(app, a, say):
    managed_only(app)
    if a["stamp"] is not None and a["stamp"] not in {item.stamp for item in api.backups()}:
        raise Bad("stamp: no backup of that name")
    done = api.undo(a["stamp"])
    return {"restored": backup_data(done.restored), "before": backup_data(done.before),
            "taken_off": [[branch, commit[:8]] for branch, commit in done.taken_off], "notes": list(done.notes)}


# --- handlers: setup and export ----------------------------------------------------------------------

def _setup(app, report):
    data = api.as_data(report)
    data["tex_lines"] = prompts.tex_state_lines(report.tex)
    data["chosen_by"] = prompts.CHOSEN_BY[report.where.origin]
    for item in report.features:
        if item.name == "gh login" and item.available is not None:
            app.identity = api.as_data(item)
    return data


def setup(app, a, say):
    return _setup(app, api.setup_report(app.ws))


def setup_check(app, a, say):
    return _setup(app, api.setup_report(app.ws, probe=a["probe"], progress=say))


def tex_link(app, a, say):
    status = api.tex_link(app.ws, replace=a["replace"])
    return dict(api.as_data(status), lines=prompts.tex_state_lines(status))


def tex_unlink(app, a, say):
    return api.as_data(api.tex_unlink())


def export_upload(app, a, say, body):
    try:
        found, name, files = app.store.add_manuscript(a["bundle"], a["name"], body)
    except ValueError as exc:
        raise Bad(f"name: {exc}") from exc
    return {"bundle": found, "name": name, "files": files}


def export_run(app, a, say):
    held = app.store.get("bundle", a["bundle"])
    files, main = held["files"], a["main"]
    if not files:
        raise Bad("bundle: no file was uploaded")
    if main is not None and main not in files:
        raise Bad("main: not one of the uploaded files")
    if main is None and len(files) == 1:
        main = files[0]
    sources = [name for name in files if name.endswith(".tex")]
    if main is not None and not main.endswith(".tex"):
        paper, named = held["folder"] / main, None
    elif sources:
        paper, named = held["folder"], main
    else:
        raise Bad("main: several .aux/.bcf files were uploaded; say which is the paper's")
    target = app.store.new_folder()
    made = api.export_bib(app.ws, paper, out=target / app.ws.bib.name, main=named)
    cited = made.cited
    try:        # what was made is kept only when it fits; otherwise it is removed again and the refusal says why
        kept_as = app.store.put("export", {"folder": target, "path": made.path}, size=made.path.stat().st_size)
    except Full:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return {"export": kept_as, "name": made.path.name,
            "written": len(made.written), "cited": len(cited.keys), "all_entries": cited.all_entries,
            "read_from": READ_FROM[cited.how], "missing": [str(item) for item in made.missing],
            "parents": list(made.parents), "notes": list(made.notes)}


def export_file(app, a, say):
    path = app.store.get("export", a["id"])["path"]
    return "application/x-bibtex", path.read_bytes(), path.name


# --- the table -------------------------------------------------------------------------------------

def _routes():
    P, G, quick = "POST", "GET", 20.0
    with_install = lambda **args: dict(args, **INSTALL)                     # noqa: E731
    return [
        Route(G, "/api/session", "", session, direct=True),
        Route(G, "/api/jobs/{id}", "", job, {"after": Whole()}, direct=True),
        Route(P, "/api/jobs/{id}/cancel", "", job_cancel, direct=True),
        # the library
        Route(G, "/api/entries", "revision, entries", entries, wait=quick, single=True),
        Route(G, "/api/search", "revision, entries, search", search,
              {"q": Text(500, optional=True), "status": Text(40, r"[a-z_]+", optional=True)}, wait=quick),
        Route(G, "/api/revision", "revision, entries", revision, wait=quick, single=True),
        Route(G, "/api/entry", "entry", entry, {"key": KEY}, wait=quick),
        Route(G, "/api/review-queue", "revision, entries, review_queue, search", review_queue,
              {"all": Flag(), "q": Text(500, optional=True), "offset": Whole(0, 10 ** 6), "limit": Whole(1, 200, 100)},
              wait=quick),
        Route(P, "/api/edit/preview", "preview_edit", preview_edit,
              with_install(key=Text(200, KEY.pattern.pattern, optional=True), raw=RAW,
                           opened=Text(128, FINGERPRINT.pattern.pattern, optional=True))),
        Route(P, "/api/edit/save", "save_edit", save_edit, with_install(preview=Ident())),
        Route(P, "/api/check/keys", "check_keys", check_keys, with_install(keys=Texts(500, KEY, least=1))),
        Route(P, "/api/check/changed", "check_library", check_changed, with_install()),
        Route(P, "/api/check/format", "check_format", check_format, with_install()),
        Route(P, "/api/approve", "approve", approve,
              with_install(key=KEY, fingerprint=FINGERPRINT, source=Text(2000), note=Text(5000))),
        Route(P, "/api/revoke", "revoke", revoke, with_install(key=KEY, fingerprint=FINGERPRINT, reason=Text(5000))),
        Route(P, "/api/identity/check", "features", identity, with_install()),
        # adding
        Route(P, "/api/add/search", "find_candidates", add_search,
              with_install(title=Text(500, optional=True), authors=Texts(10, Text(100)),
                           year=Text(4, r"\d{4}|", optional=True))),
        Route(P, "/api/add/choose", "candidate_query, propose_new", add_choose,
              with_install(search=Ident(), index=Whole(0, 1000))),
        Route(P, "/api/add/identifiers", "propose_new", add_identifiers, with_install(queries=Texts(50, Text(600)))),
        Route(P, "/api/add/manual", "manual_prefill, draft_manual", add_manual,
              with_install(entry_type=Text(20, r"[a-z]+"), fields=Fields(), pdf=Ident(optional=True),
                           model=Ident(optional=True), omit=Texts(40, Text(32, Fields.NAME.pattern)))),
        Route(G, "/api/add/form", "draft_form", draft_form, wait=quick),
        Route(G, "/api/model-routes", "model_routes", model_routes, wait=quick),
        Route(P, "/api/model-routes/check", "model_routes", model_routes_check,
              with_install(route=Choice("dartmouth", "openai"))),
        Route(P, "/api/pdf/upload", "", pdf_upload, body="pdf", direct=True),
        Route(P, "/api/pdf/read", "read_pdf", pdf_read, with_install(pdf=Ident())),
        Route(P, "/api/pdf/lookup", "propose_from_pdf", pdf_lookup, with_install(pdf=Ident())),
        Route(P, "/api/pdf/model", "read_pdf_with_model", pdf_model,
              with_install(pdf=Ident(), route=Choice("dartmouth", "openai"))),
        Route(P, "/api/pdf/page", "render_first_page", pdf_page, with_install(pdf=Ident())),
        Route(G, "/api/pdf/prefill", "manual_prefill", pdf_prefill, {"pdf": Ident(), "model": Ident(optional=True)},
              wait=quick),
        Route(G, "/api/pdf/{id}/file", "", pdf_file, answer="bytes", direct=True),
        # one proposal
        Route(G, "/api/proposal", "acceptable, why_not_acceptable, proposal_failed, intake_data, name_choices", proposal, {"proposal": Ident()},
              wait=quick),
        Route(P, "/api/proposal/accept", "why_not_acceptable, apply_proposals | accept_draft", proposal_accept,
              with_install(proposal=Ident())),
        Route(P, "/api/proposal/remove-duplicate", "apply_proposals", proposal_remove_duplicate,
              with_install(proposal=Ident())),
        Route(P, "/api/proposal/accept-remaining", "acceptable, apply_proposals", proposal_accept_remaining,
              with_install(proposals=Texts(500, Ident()))),
        Route(P, "/api/proposal/recheck", "recheck_proposal", proposal_recheck, with_install(proposal=Ident(), raw=RAW)),
        Route(P, "/api/proposal/candidate", "choose_candidate", proposal_candidate,
              with_install(proposal=Ident(), index=Whole(0, 1000))),
        Route(P, "/api/proposal/names", "name_choices, resolve_names", proposal_names,
              with_install(proposal=Ident(), field=Choice("author", "editor"),
                           picks=Texts(200, Choice("typed", "source"), least=1))),
        Route(P, "/api/proposal/skip", "", proposal_skip, {"proposal": Ident()}, direct=True),
        # sending
        Route(P, "/api/send/offers", "entry, completion_offers", offers_next, with_install(restart=Flag())),
        Route(G, "/api/send/due", "completion_due", completion_due, wait=quick, single=True),
        Route(G, "/api/evidence/pending", "pending_evidence", evidence_pending, wait=quick, single=True),
        Route(P, "/api/evidence/retry", "retry_evidence", evidence_retry, with_install(key=KEY, proposal=Ident(optional=True))),
        Route(P, "/api/send", "send_checked", send, with_install(summary=Text(100, optional=True),
                                                                  allow_fork_creation=Flag())),
        # the state of the library
        Route(G, "/api/state", "library_state", state, wait=quick, single=True),
        Route(P, "/api/state/refresh", "library_state", state_refresh, with_install(), single=True),
        Route(G, "/api/backups", "is_managed, backups, unreadable_backups, holds_only_copy, completion_undo_checkpoint",
              backups, wait=quick, single=True),
        Route(P, "/api/update", "is_managed, update", update, with_install()),
        Route(P, "/api/update/decide", "is_managed, update", update_decide,
              with_install(decision=Ident(), choice=Choice("keep", "update", "send", "discard"))),
        Route(P, "/api/undo", "is_managed, backups, undo", undo,
              with_install(stamp=Text(64, r"[0-9A-Za-z][0-9A-Za-z._-]*", optional=True))),
        # setup and export
        Route(G, "/api/setup", "setup_report", setup, wait=quick, single=True),
        Route(P, "/api/setup/check", "setup_report", setup_check,
              with_install(probe=Choice(*api.PROBES, "all"))),
        Route(P, "/api/tex/link", "tex_link", tex_link, with_install(replace=Flag())),
        Route(P, "/api/tex/unlink", "tex_unlink", tex_unlink, with_install()),
        Route(P, "/api/export/upload", "", export_upload, {"bundle": Ident(optional=True), "name": Text(200)},
              body="file", direct=True),
        Route(P, "/api/export/run", "export_bib", export_run, with_install(bundle=Ident(), main=Text(80, optional=True))),
        Route(G, "/api/export/{id}/file", "", export_file, answer="bytes", direct=True),
    ]


ROUTES = _routes()
CHANGES_LIBRARY = {"/api/edit/save", "/api/proposal/accept", "/api/proposal/remove-duplicate",
                   "/api/proposal/accept-remaining", "/api/update", "/api/update/decide", "/api/undo"}


def find(method, path):
    """(route, {path argument: value}) for a request; (None, allowed methods) when the path
    is known under another method; (None, None) when it is not known at all."""
    parts, allowed = path.split("/"), []
    for route in ROUTES:
        shape = route.path.split("/")
        if len(shape) != len(parts):
            continue
        held = {}
        for want, got in zip(shape, parts):
            if want == "{id}":
                if not ID.match(got):
                    break
                held["id"] = got
            elif want != got:
                break
        else:
            if route.method == method:
                return route, held
            allowed.append(route.method)
    return None, allowed or None


def arguments(route, given, held=None):
    """The handler's arguments: every name the route declares (None when absent), checked by
    its type. A name the route does not declare is refused by name."""
    for name in given:
        if name in NEVER or name.startswith("_"):
            raise Bad(f"argument not accepted here: {name}")
        if name not in route.args:
            raise Bad(f"unknown argument: {name}")
    found = {name: kind.check(name, given.get(name)) for name, kind in route.args.items()}
    found.update(held or {})
    return found
