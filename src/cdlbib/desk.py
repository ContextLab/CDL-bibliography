"""The desk: what an interactive front end shows and edits. Browse, search, one entry with its
evidence, the preview and the saving of a hand edit, the review queue, and the state of the
library. Nothing here prints, prompts or exits; front ends reach it through cdlbib.api.

Only the parsing of cdl.bib is cached, by (path, mtime_ns, size). Verification results are
read from the cache database on every call, so a front end refreshes by calling again
(``revision`` says cheaply whether anything it shows may have changed).
"""
import contextlib
import difflib
import os
import re
import sqlite3
import tempfile
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .errors import CdlbibError, EditRefused
from .library import serialized


# --- reading the library ----------------------------------------------------------------------

_PARSED = {}       # str(path) -> ((mtime_ns, size), entries, {name: something derived from entries})


def _stat(path):
    try:
        found = os.stat(path)
    except OSError:
        return None
    return found.st_mtime_ns, found.st_size


def _scan(data):
    """load_entries of ``data`` (the bytes of a bibliography); {} when it holds nothing."""
    from .verification import load_entries
    if not data.decode("utf-8-sig").strip():
        return {}
    with tempfile.TemporaryDirectory(prefix="cdlbib-desk-") as folder:
        path = Path(folder) / "cdl.bib"
        path.write_bytes(data)
        return load_entries(path)


def _snapshot(ws):
    """(the entries of ws.bib, the bytes they were read from). The entries are parsed from
    exactly those bytes, and parsed again only when the file's (mtime_ns, size) changed.
    Callers do not change what they are given."""
    path = str(ws.bib)
    try:
        before = _stat(path)
        data = ws.bib.read_bytes()
        held = _PARSED.get(path)
        if held and before is not None and held[0] == before and _stat(path) == before:
            return held[1], data
        entries = _scan(data)
    except (OSError, ValueError) as exc:
        raise CdlbibError(f"{ws.bib} could not be read: {exc}") from exc
    if before is not None and _stat(path) == before:
        _PARSED[path] = (before, entries, {})
    return entries, data


def parsed(ws):
    """The entries of the library as verification.load_entries gives them ({} for an empty
    file), parsed once per state of the file. CdlbibError when the file cannot be read."""
    return _snapshot(ws)[0]


def _derived(ws, entries, name, build):
    """``build(entries)``, kept with the parse it was made from."""
    held = _PARSED.get(str(ws.bib))
    if held and held[1] is entries:
        if name not in held[2]:
            held[2][name] = build(entries)
        return held[2][name]
    return build(entries)


@contextlib.contextmanager
def _cache(ws, database=None):
    """The verification cache of the library; one in memory when there is no database yet,
    so that looking at a library creates nothing."""
    from .verification import Cache, revocation_ledger
    path = Path(database or ws.database)
    try:
        cache = Cache(path if path.is_file() else ":memory:", ledger=revocation_ledger(str(ws.bib), None))
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise CdlbibError(f"The verification results could not be read: {exc}") from exc
    try:
        yield cache
    except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        raise CdlbibError(f"The verification results could not be read: {exc}") from exc
    finally:
        cache.close()


def revision(ws, database=None):
    """A value that changes whenever the bibliography, the verification database (or its
    write-ahead log) or the revocation ledger changes on disk: their (mtime_ns, size), None for
    one that is not there. Reads no file."""
    from .verification import revocation_ledger
    database = Path(database or ws.database)
    return tuple(_stat(path) for path in (ws.bib, database, Path(str(database) + "-wal"),
                                          revocation_ledger(str(ws.bib), None)))


# --- browse and search -------------------------------------------------------------------------

@dataclass(frozen=True)
class EntrySummary:
    key: str
    type: str
    authors: str         # the author field as written (the editors when there is no author)
    year: str
    title: str
    venue: str           # journal, else booktitle, publisher, school, institution, howpublished
    doi: str
    status: str          # the verifier's current status; "pending" when it has none for this content
    issues: tuple = ()


VENUES = ("journal", "booktitle", "publisher", "school", "institution", "howpublished")


def _summary(entry, result):
    fields = entry["fields"]
    return EntrySummary(
        key=entry["key"], type=str(fields.get("ENTRYTYPE") or ""),
        authors=str(fields.get("author") or fields.get("editor") or ""), year=str(fields.get("year") or ""),
        title=str(fields.get("title") or ""), venue=next((str(fields[name]) for name in VENUES if fields.get(name)), ""),
        doi=str(fields.get("doi") or ""), status=result["status"],
        issues=tuple(str(issue) for issue in result.get("issues") or ()))


def entries(ws, database=None):
    """One EntrySummary per entry, in the file's order. Offline: the parse (cached) and the
    stored verification results (read now)."""
    from .verification import current_results
    found = parsed(ws)
    with _cache(ws, database) as cache:
        results = current_results(str(ws.bib), cache, found)
    return [_summary(entry, results[key]) for key, entry in found.items()]


_PLAIN = str.maketrans({"ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "æ": "ae", "Æ": "AE",
                        "œ": "oe", "Œ": "OE", "ı": "i", "đ": "d", "Đ": "D",
                        "{": None, "}": None, "~": " "})


@lru_cache(maxsize=1 << 17)
def fold(text):
    """``text`` as searching compares it: TeX accents and commands read as their letters,
    braces dropped, accents removed, case folded, runs of white space as one space."""
    text = str(text)
    if "\\" in text:
        try:
            from pylatexenc.latex2text import LatexNodes2Text
            text = LatexNodes2Text(math_mode="text").latex_to_text(text)
        except Exception:      # noqa: BLE001 - text TeX cannot read is searched as it is written
            pass
    text = unicodedata.normalize("NFKD", text.translate(_PLAIN))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).casefold().split())


SEARCHED = ("key", "authors", "title", "venue", "year", "doi")    # where a plain word is looked for
FIELDS = {"key": "key", "author": "authors", "authors": "authors", "title": "title", "venue": "venue",
          "journal": "venue", "year": "year", "doi": "doi", "type": "type", "status": "status"}
_TERM = re.compile(r'(?:([A-Za-z]+):)?(?:"([^"]*)"|(\S+))')


def search(source, text="", status=None):
    """The summaries that match ``text``, in their order. ``source`` is a workspace or a list
    of EntrySummary (then nothing is read). Every word must be found (as part of a word, in
    any order) in the key, authors, title, venue, year or DOI; ``field:word`` looks in one of
    key, author, title, venue (or journal), year, doi, type, status; "two words" in quotes
    are found together. Case, accents, TeX accents and braces make no difference. ``status``
    (a status or several) keeps only entries with that status."""
    summaries = source if isinstance(source, (list, tuple)) else entries(source)
    wanted = None if status is None else {status} if isinstance(status, str) else set(status)
    terms = []
    for name, quoted, word in _TERM.findall(text or ""):
        value = quoted if not word else word
        if name and name.lower() in FIELDS:
            terms.append(((FIELDS[name.lower()],), fold(value)))
        else:
            terms.append((SEARCHED, fold(f"{name}:{value}" if name else value)))
    terms = [(where, value) for where, value in terms if value]
    return [item for item in summaries
            if (wanted is None or item.status in wanted)
            and all(any(value in fold(getattr(item, name)) for name in where) for where, value in terms)]


# --- one entry ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class FormatFinding:
    field: str | None    # "key", a field name; None when the check could not judge the entry at all
    current: str | None
    corrected: str | None   # what the house formatter would write; None: it would remove the field
    message: str


@dataclass
class EntryDetail:
    key: str
    raw: str             # the exact text of the entry in the file
    fields: dict
    fingerprint: str     # names this exact content: pass it to save_edit, approve and revoke
    result: dict         # the verifier's current result (status, issues, candidates, attempts,
                         # human_review, revoked_approval, external_evidence, ... as stored)
    closest: dict | None # the candidate source the gate prints as "closest source"
    advisories: list     # non-blocking remarks (e.g. "missing DOI: ...")
    format: list | None  # FormatFinding per house-format finding; None when not computed (review_queue)

    @property
    def status(self):
        return self.result["status"]

    @property
    def issues(self):
        return list(self.result.get("issues") or [])

    @property
    def candidates(self):
        return list(self.result.get("candidates") or [])

    @property
    def attempts(self):
        return list(self.result.get("attempts") or [])

    @property
    def human_review(self):
        return self.result.get("human_review")

    @property
    def revoked_approval(self):
        return self.result.get("revoked_approval")

    @property
    def external_evidence(self):
        return self.result.get("external_evidence")


def _parents(fields):
    return [name.strip() for kind in ("crossref", "xdata") for name in str(fields.get(kind) or "").split(",")
            if name.strip()]


def _bases(found):
    """{key: the house key without its suffix letter} for the entries a key can be made for."""
    from .helpers import authors2key, key_names
    fields = {key: entry["fields"] for key, entry in found.items()}
    bases = {}
    for (key, data), names in zip(fields.items(), key_names(fields)):
        try:
            if names.strip() and data.get("year"):
                bases[key] = authors2key(names, data["year"])
        except Exception:      # noqa: BLE001 - helpers raise plain exceptions on names they cannot key
            continue
    return bases


_BLOCK = re.compile(r"@([A-Za-z]+)\s*([({])")


def _definitions(data):
    """The @string and @preamble blocks of a bibliography (``data``: its bytes), each as its
    exact text, in the file's order; [] when it has none or cannot be scanned."""
    text = data.decode("utf-8-sig", errors="replace")
    if not _DEFINITIONS.search(text):
        return []
    found, at = [], 0
    while at < len(text):
        if text[at].isspace():
            at += 1
            continue
        if text[at] == "%":
            end = text.find("\n", at)
            at = len(text) if end < 0 else end + 1
            continue
        head = _BLOCK.match(text, at)
        if not head:
            return found
        start, depth, quoted = at, 0, False
        at = head.end()
        while at < len(text):
            c = text[at]
            if c == "\\":
                at += 2
                continue
            if c == '"' and depth == 0:
                quoted = not quoted
            if not quoted:
                if depth == 0 and c == ("}" if head[2] == "{" else ")"):
                    break
                depth += (c == "{") - (c == "}")
            at += 1
        if at >= len(text):        # never closed: the file does not scan, and the reader says so
            return found
        at += 1
        if head[1].lower() in ("string", "preamble"):
            found.append(text[start:at])
    return found


def _bases_beside(ws, found, others):
    """_bases of ``others``, taken from what was worked out for the library as it is
    (``found``) for every entry that is still the same object."""
    known = _derived(ws, found, "bases", _bases)
    changed = {name: item for name, item in others.items() if found.get(name) is not item}
    same = {name: known[name] for name in others if name in known and name not in changed}
    return {**same, **_bases(changed)} if changed else same


def _format(entry, others, bases, definitions=()):
    """([FormatFinding], the entry as the formatter would write it or None) for one entry.
    The house checker judges a whole file (key suffixes depend on the other entries with the
    same authors and year), so it is given this entry, those entries, any entry this one
    inherits from and the file's @string/@preamble definitions (an entry may use them), in a
    file of their own; only what it says about this entry is returned."""
    import io
    from .helpers import check_bib
    from .verification import load_entries
    key, fields = entry["key"], entry["fields"]
    own = _bases({key: entry}).get(key)
    beside = {name: others[name] for name, base in bases.items() if own and base == own and name in others}
    todo = _parents(fields)
    while todo:
        name = todo.pop()
        if name in others and name not in beside:
            beside[name] = others[name]
            todo += _parents(others[name]["fields"])
    with tempfile.TemporaryDirectory(prefix="cdlbib-desk-") as folder:
        path, out = Path(folder) / "entry.bib", Path(folder) / "formatted.bib"
        path.write_text("\n\n".join([*definitions, *(item["raw"] for item in beside.values()), entry["raw"]]) + "\n",
                        encoding="utf-8")
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                errors, _ = check_bib(str(path), autofix=True, outfile=str(out), verbose=False)
            mine = errors.get(key, {})
            formatted = load_entries(out)
            written = formatted.get(mine.get("ID", key)) or formatted.get(key)
        except Exception as exc:  # noqa: BLE001 - check_bib raises plain exceptions on entries it cannot judge
            return [FormatFinding(None, None, None, f"The format check could not judge this entry "
                                                    f"({type(exc).__name__}: {exc})")], None
    findings = [FormatFinding("key" if name == "ID" else name, key if name == "ID" else fields.get(name), value,
                              f"the format checker would write {'the key' if name == 'ID' else name} as {value}")
                for name, value in sorted(mine.items())]
    if written is not None and "force" not in fields:
        findings += [FormatFinding(name, fields[name], None, f"{name} is not a field the library keeps; the format "
                                                             "checker would remove it")
                     for name in sorted(set(fields) - set(written["fields"]))]
    return findings, written["raw"] if written is not None else None


def _detail(entry, result, findings):
    from .verification import result_advisories
    from .verification_cli import closest_candidate
    return EntryDetail(key=entry["key"], raw=entry["raw"], fields=dict(entry["fields"]), fingerprint=entry["fingerprint"],
                       result=result, closest=closest_candidate(entry["fields"], result),
                       advisories=result_advisories(entry["fields"], result), format=findings)


def entry(ws, key, database=None):
    """Everything about one entry: its exact text, fields and fingerprint, the verifier's
    current result with its evidence, the closest source, advisories, and the house-format
    findings field by field. CdlbibError when the library has no such key."""
    from .verification import current_results
    found, data = _snapshot(ws)
    if key not in found:
        raise CdlbibError(f"There is no entry {key} in {ws.bib}.")
    with _cache(ws, database) as cache:
        result = current_results(str(ws.bib), cache, {key: found[key]})[key]
    others = {name: item for name, item in found.items() if name != key}
    return _detail(found[key], result, _format(found[key], others, _derived(ws, found, "bases", _bases),
                                               _derived(ws, found, "definitions", lambda _: _definitions(data)))[0])


def review_queue(ws, reference="github", all_entries=False, database=None):
    """The entries waiting for a person: those that differ from ``reference`` (the GitHub
    master cdl.bib, or a path; key-only renames do not count), or every entry with
    ``all_entries``, whose current status is not an accepted one. An EntryDetail each, in the
    file's order, without format findings (``format`` is None; ``entry`` gives them).
    Offline with ``all_entries`` or a local reference."""
    from .verification import ACCEPTED, current_results
    from .verification_cli import reference_bib, select_keys
    found = parsed(ws)
    if not found:
        return []
    try:
        with tempfile.TemporaryDirectory(prefix="cdlbib-reference-") as folder:
            against = None if all_entries else reference_bib(reference, folder)
            selected = select_keys(str(ws.bib), None, against, entries=found)
    except (OSError, ValueError) as exc:
        raise CdlbibError(f"The entries to review could not be selected: {exc}") from exc
    with _cache(ws, database) as cache:
        results = current_results(str(ws.bib), cache, {key: found[key] for key in found if key in selected})
    return [_detail(found[key], result, None) for key, result in results.items() if result["status"] not in ACCEPTED]


# --- editing one entry -------------------------------------------------------------------------

@dataclass(frozen=True)
class KeyChange:
    old: str
    new: str
    kind: str            # "rename" (recorded in the key-rename ledger when saved) | "collision" (refused)


@dataclass(frozen=True)
class Affected:
    key: str             # another entry whose fingerprint the edit changes (it inherits from the edited one)
    status_now: str
    status: str          # the status it will have


@dataclass
class EditPreview:
    key: str | None              # the entry being edited; None for a new entry
    new_key: str | None          # the key in the edited text
    fingerprint: str | None      # of the entry as it is now: the ``expected_fingerprint`` of save_edit
    new_fingerprint: str | None
    changed: bool                # False: the text is what the file already holds
    diff: str                    # unified diff, the entry now against the edited text
    format: list                 # FormatFinding per house-format finding on the edited text
    corrected_raw: str | None    # the edited entry as the house formatter would write it
    key_change: KeyChange | None
    duplicate_of: str | None     # another entry that is the same work (same identifier, or title and surnames)
    status_now: str | None       # the entry's status now
    status: str | None           # the status the edited content will have (an earlier result for exactly it, else pending)
    invalidates: str | None      # the accepted status the edit loses, when it loses one
    affected: list = field(default_factory=list)
    problems: list = field(default_factory=list)   # why this cannot be saved as it is ([]: it can)

    @property
    def ok(self):
        return not self.problems


@dataclass
class _Plan:
    new_key: str | None = None
    written: str = ""            # the entry text as it goes into the file
    data: bytes = b""            # the whole file as it would be
    entries: dict | None = None  # the library as it would be; None when it cannot be planned
    changed: bool = True
    alone: bool = False          # every other entry of ``entries`` is the very object it was
    problems: list = field(default_factory=list)


_HEAD = re.compile(r"@([A-Za-z]+)\s*[({]\s*([^,\s})]+)")     # as complete._key_token reads the key
_DEFINITIONS = re.compile(r"@\s*(?:string|preamble)\b", re.IGNORECASE)
_INHERITS = re.compile(r"\b(?:crossref|xdata)\s*=", re.IGNORECASE)


def _plan(original, found, key, raw):
    """What saving ``raw`` as entry ``key`` (None: a new entry) would write, worked out on
    copies: the one entry's exact text put in place of the old one (appended, for a new
    one), every other byte kept; UTF-8 BOM, line endings and the final newline as they are.
    Reasons it cannot be saved are returned in ``problems``, never raised."""
    plan = _Plan()
    bom = original.startswith(b"\xef\xbb\xbf")
    text = original.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    plan.written = written = str(raw).strip().replace("\r\n", "\n").replace("\n", newline)
    head = _HEAD.match(written)
    if not head or head[1].lower() in ("comment", "string", "preamble"):
        plan.problems.append("The text must be one BibTeX entry, starting with @type{Key,")
        return plan
    plan.new_key = new_key = head[2]
    if key is None:
        if new_key in found:
            plan.problems.append(f"The key {new_key} is already in use; a new entry needs a key of its own")
            return plan
        candidate = text + (newline * (2 if not text.endswith(newline) else 1 if not text.endswith(newline * 2) else 0)
                            if text else "") + written + (newline if text.endswith("\n") else "")
    else:
        if key not in found:
            plan.problems.append(f"{key} is no longer in the library")
            return plan
        old = found[key]["raw"]
        plan.changed = written != old
        if text.count(old) != 1:
            plan.problems.append(f"The text of {key} appears {text.count(old)} times in the file, so it cannot be "
                                 "replaced safely")
        if new_key != key and new_key in found:
            plan.problems.append(f"The key {new_key} already belongs to another entry")
        if plan.problems:
            return plan
        candidate = text.replace(old, written, 1)
    plan.data = (b"\xef\xbb\xbf" if bom else b"") + candidate.encode("utf-8")
    # Every other entry is byte-for-byte what it was. When nothing ties their fingerprints to
    # this one (no @string/@preamble in the file, no entry inheriting from the old or new key,
    # no inheritance in the new text), reading the one new entry gives exactly what reading
    # the whole new file would; otherwise the whole new file is read.
    plan.alone = alone = (not _DEFINITIONS.search(text) and not _INHERITS.search(written)
             and not any(parent in (key, new_key) for name, item in found.items() if name != key
                         for parent in _parents(item["fields"])))
    try:
        if alone:
            one = _scan(written.encode("utf-8"))
            if list(one) != [new_key] or one[new_key]["raw"] != written:
                raise ValueError("the text must contain exactly one entry and nothing else")
            plan.entries = dict(found, **one) if key is None else {
                (new_key if name == key else name): (one[new_key] if name == key else item)
                for name, item in found.items()}
        else:
            plan.entries = _scan(plan.data)
            if (new_key not in plan.entries or plan.entries[new_key]["raw"] != written
                    or len(plan.entries) != len(found) + (key is None)):
                plan.entries = None
                raise ValueError("the text must contain exactly one entry and nothing else")
    except (ValueError, UnicodeError) as exc:
        plan.problems.append(f"The edited text cannot be read as one entry: {exc}")
    return plan


def _works(found, progress=None):
    """{key: (the entry, its work identifiers, its title and surnames)}: what tells two entries
    of one work apart from two works (complete._work_ids, complete._title_byline).
    ``progress`` receives a line every 500 entries."""
    from .complete import _title_byline, _work_ids
    works = {}
    for number, (key, item) in enumerate(found.items(), 1):
        works[key] = (item, _work_ids(item["fields"]), _title_byline(item["fields"]))
        if progress and number % 500 == 0:
            progress(f"indexed {number} of {len(found)} entries")
    return works


@dataclass
class Prepared:
    entries: int         # how many entries the library holds
    seconds: float       # how long the preparation took (near 0 when it was already prepared)
    revision: tuple      # revision(ws) of the state that was prepared


def prepare(ws, progress=None):
    """Read the library and work out, once for this state of cdl.bib, what an entry's detail
    and an edit's preview need: the parse, the citation-key groups, the @string definitions
    and the index of works that duplicate detection reads. They are kept with the parse (so
    by path, mtime_ns and size), reused by every preview, and carried over by save_edit.
    ``progress`` receives a line per step, and every 500 entries during the index."""
    import time
    say = progress or (lambda line: None)
    started = time.monotonic()
    say(f"reading {ws.bib.name} ...")
    found, data = _snapshot(ws)
    say(f"read {len(found)} entries")
    say("grouping citation keys ...")
    _derived(ws, found, "bases", _bases)
    _derived(ws, found, "definitions", lambda _: _definitions(data))
    say("indexing the works for duplicate detection ...")
    _derived(ws, found, "works", lambda entries: _works(entries, say))
    seconds = time.monotonic() - started
    say(f"ready: {len(found)} entries prepared in {seconds:.1f} s")
    return Prepared(len(found), seconds, revision(ws))


def _same_work(new, others, known):
    """The key among ``others`` of the same work as ``new`` (complete.duplicates' rule: a
    shared DOI, PMID or arXiv identifier, or the same title and ordered surnames). ``known``
    is _works of the library as it is: an entry it holds unchanged is not worked out again."""
    ids, byline = _works({"": new})[""][1:]
    if not ids and byline is None:
        return None
    for name, item in others.items():
        held = known.get(name)
        theirs = held[1:] if held and held[0] is item else _works({name: item})[name][1:]
        if ids & theirs[0] or (byline is not None and byline == theirs[1]):
            return name
    return None


def preview_edit(ws, key, raw, database=None):
    """What saving ``raw`` as the entry ``key`` (None: a new hand-typed entry) would do,
    without writing anything to the library: the diff, the house-format findings with the
    formatter's values, a changed key as a rename or a collision, whether the work is already
    in the library under another key, the status the new content will have (an earlier result
    for exactly that content is found again; anything else is pending), the accepted status
    it loses, and the other entries whose fingerprint changes with it. Text that cannot be
    read, and anything else that stops a save, is in ``problems``. (Looking up a status may do
    the cache's own bookkeeping in the verification database, as every status read.)"""
    from .verification import ACCEPTED, current_results
    found, original = _snapshot(ws)
    now = found.get(key) if key is not None else None
    plan = _plan(original, found, key, raw)
    preview = EditPreview(key=key, new_key=plan.new_key, fingerprint=now["fingerprint"] if now else None,
                          new_fingerprint=None, changed=plan.changed, diff="", format=[], corrected_raw=None,
                          key_change=None, duplicate_of=None, status_now=None, status=None, invalidates=None,
                          problems=list(plan.problems))
    preview.diff = "\n".join(difflib.unified_diff(
        now["raw"].splitlines() if now else [], plan.written.splitlines(), fromfile=key or "(new entry)",
        tofile=plan.new_key or "(edited)", lineterm=""))
    if key is not None and plan.new_key and plan.new_key != key:
        preview.key_change = KeyChange(key, plan.new_key, "collision" if plan.new_key in found else "rename")
    elif key is None and plan.new_key in found:
        preview.key_change = KeyChange(plan.new_key, plan.new_key, "collision")
    with _cache(ws, database) as cache:
        if now:
            preview.status_now = current_results(str(ws.bib), cache, {key: now})[key]["status"]
        if plan.entries is None:
            return preview
        new = plan.entries[plan.new_key]
        others = {name: item for name, item in plan.entries.items() if name != plan.new_key}
        preview.new_fingerprint = new["fingerprint"]
        preview.status = current_results(str(ws.bib), cache, {plan.new_key: new})[plan.new_key]["status"]
        if preview.status_now in ACCEPTED and preview.status not in ACCEPTED:
            preview.invalidates = preview.status_now
        moved = {name: item for name, item in others.items()
                 if name in found and found[name]["fingerprint"] != item["fingerprint"]}
        if moved:
            before = current_results(str(ws.bib), cache, {name: found[name] for name in moved})
            after = current_results(str(ws.bib), cache, moved)
            preview.affected = [Affected(name, before[name]["status"], after[name]["status"]) for name in moved]
    preview.duplicate_of = _same_work(new, others, _derived(ws, found, "works", _works))
    preview.format, preview.corrected_raw = _format(
        new, others, _bases_beside(ws, found, others),
        _derived(ws, found, "definitions", lambda _: _definitions(original)))
    return preview


@serialized
def save_edit(ws, key, raw, expected_fingerprint=None, *, batch=None):
    """Write ``raw`` as the entry ``key`` (None: a new hand-typed entry, whose key must not be
    in use) and return a complete.Applied: ``written`` is [the entry's key], ``renamed`` the
    key change when the key was edited (also appended to the key-rename ledger), ``backup``
    or ``saved_copy`` the state before. Exactly this entry's text is replaced; every other
    byte of the file, comments included, stays as it is, and no other entry's key is touched.
    Entries of any type are saved, whatever the format check says of them (the gate judges
    that when the change is sent). No approval is recorded, and an approval of the old content
    does not carry over: the new content has the status ``preview_edit`` shows.

    The library's write lock is held throughout. Under it the entry's fingerprint is compared
    with ``expected_fingerprint`` (EntryDetail.fingerprint, as the person was shown it), and
    a difference, a key collision or text that is not one entry raises EditRefused with
    nothing written. Text identical to what the file holds writes nothing. The files go
    through writer.commit, like complete.apply."""
    from . import writer
    from .complete import Applied
    try:
        writer.require_protectable(ws)
        from . import library
        result = Applied(notes=library.settled(ws) + writer.recover(ws))
        found, original = _snapshot(ws)
        if key is not None:
            if key not in found:
                raise EditRefused(f"{key} is no longer in the library; nothing was written.")
            if found[key]["fingerprint"] != expected_fingerprint:
                raise EditRefused(f"{key} was changed since it was opened; nothing was written. Open it again and "
                                  "make the edit on the text as it is now.")
        plan = _plan(original, found, key, raw)
        if plan.problems:
            raise EditRefused("; ".join(plan.problems) + "; nothing was written.", problems=plan.problems)
        if not plan.changed:
            result.notes.append("the text is what the library already holds; nothing was written")
            return result
        writes, expected = [(ws.bib, plan.data)], {ws.bib: original}
        if key is not None and plan.new_key != key:
            result.renamed = {key: plan.new_key}
            ledger, expected[ws.key_renames], data = writer.renames_recorded(ws, result.renamed,
                                                                           "Citation key edited by hand")
            writes.append((ledger, data))
        done = writer.commit(ws, writes, expected, batch=batch, operation="entry edit")
        result.written, result.backup, result.saved_copy = [plan.new_key], done.backup, done.saved_copy
    except CdlbibError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise CdlbibError(f"The entry could not be saved: {exc}") from exc
    # The file now holds exactly the planned bytes: the planned entries are its parse.
    path = str(ws.bib)
    with contextlib.suppress(OSError):
        before = _stat(path)
        if before is not None and ws.bib.read_bytes() == plan.data and _stat(path) == before:
            held, kept = _PARSED.get(path), {}
            derived = held[2] if held and held[1] is found and plan.alone else {}
            # What was worked out for the entries that are still the same objects is kept.
            if "works" in derived:
                works = derived["works"]
                kept["works"] = {name: works[name] if name in works and works[name][0] is item
                                 else _works({name: item})[name] for name, item in plan.entries.items()}
            if "bases" in derived:
                bases = derived["bases"]
                kept["bases"] = {**{name: bases[name] for name, item in plan.entries.items()
                                    if name in bases and found.get(name) is item},
                                 **_bases({plan.new_key: plan.entries[plan.new_key]})}
            if "definitions" in derived:
                kept["definitions"] = derived["definitions"]
            _PARSED[path] = (before, plan.entries, kept)
    return result


@serialized
def recover(ws):
    """Settle a write to a library cdlbib does not manage that was killed part-way (see
    writer.recover); the lines saying what was done, [] when there was nothing to settle. The
    next save does this by itself. For the managed library an interrupted write is a
    CdlbibError naming the backup that `cdlbib update --undo` restores."""
    from . import library, writer
    try:
        return library.settled(ws) + writer.recover(ws)
    except OSError as exc:
        raise CdlbibError(f"The interrupted write could not be settled: {exc}") from exc


# --- the state of the library ------------------------------------------------------------------

@dataclass
class LibraryState:
    root: Path
    origin: str                      # a workspace.Origin value: how this library is the one in use
    managed: bool                    # the library cdlbib downloads and updates
    branch: str | None = None        # None: not a git checkout, or on no branch
    pending: list | None = None      # changed paths a send would commit (None: not a git checkout)
    unrelated: list | None = None    # other changed paths, which a send leaves alone
    new_commits: int | None = None   # managed: commits the upstream has that the library does not (as last fetched)
    new_entries: int | None = None   # managed: entries of the upstream's cdl.bib the library's commit lacks
    local_commits: int | None = None # managed: commits the library has that the upstream does not
    last_check: object = None        # managed: when the upstream was last consulted by the daily check (UTC)
    pull_request: object = None      # publish.PullRequest of the send branch the library is on (refresh only)
    interrupted: str | None = None   # a write or update that did not finish: the backup or copy from before it
    refreshed: bool = False          # the upstream answered just now
    notes: list = field(default_factory=list)   # why something could not be told


def library_state(ws, refresh=False, progress=None):
    """What a front end shows about the library as a whole. Without ``refresh`` nothing leaves
    this machine and nothing is written: git is read (branch, changed files, the counts
    against the upstream as last fetched). With ``refresh``, for the managed library the
    upstream is fetched first as the daily check fetches it (library.behind: remote-tracking
    refs only, within library.AUTO_FETCH_TIMEOUT), and for a library on a branch a send made,
    GitHub is asked for that branch's pull request through the same lookup an update uses,
    within the same time. Nothing here updates the library or records a check. What could not
    be told is None, with the reason in ``notes``."""
    from . import api, library, publish, workspace, writer
    managed = api.is_managed(ws)
    try:
        chosen, origin = workspace.origin_of(None)
        origin = origin if Path(chosen.root).resolve() == Path(ws.root).resolve() else workspace.Origin.NAMED
    except CdlbibError:
        origin = workspace.Origin.NAMED
    state = LibraryState(root=ws.root, origin=workspace.Origin.MANAGED if managed else origin, managed=managed)
    if not managed and writer.interrupted(ws) is not None:
        # A write killed part-way: it is settled under the lock before anything is reported
        # (the library is put back whole), or the refusal is the note and ``interrupted`` stays.
        try:
            with library.transaction(ws, progress=progress):
                state.notes += library.settled(ws)
        except CdlbibError as exc:
            state.notes.append(str(exc))
    state.interrupted = library.interrupted() if managed else writer.interrupted(ws)
    try:
        top = publish._run(["git", "rev-parse", "--show-toplevel"], cwd=ws.root, check=False)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(ws.root).resolve():
            state.notes.append(f"{ws.root} is not a git checkout of its own, so there is no branch and nothing to send")
        else:
            here = publish.current_branch(ws)
            state.branch = None if here == "HEAD" else here
            state.pending, state.unrelated = publish.pending(ws), publish.unrelated_changes(ws)
    except CdlbibError as exc:
        state.notes.append(f"git could not be asked about {ws.root}: {' '.join(str(exc).split())[:300]}")
    if managed:
        state.last_check = library.read_state().last_check
        try:
            at = library.behind(ws, fetch=refresh, progress=progress)
        except (CdlbibError, OSError, ValueError) as exc:
            state.notes.append(f"the upstream could not be compared: {exc}")
        else:
            state.new_commits, state.local_commits, state.new_entries = at.new_commits, at.local_commits, at.new_entries
            state.refreshed = at.fetched
            if not at.target:
                state.new_commits = state.local_commits = None
                state.notes.append(f"the upstream has no branch {at.default}")
            if at.problem:
                state.notes.append(f"the upstream was not asked: {at.problem}")
    if refresh and state.branch and state.branch.startswith(library.SEND_BRANCHES):
        try:
            hosted = library._github_origin(ws.root)
            looked = library._look_up(hosted, state.branch, library.AUTO_FETCH_TIMEOUT) if hosted else None
            state.pull_request = looked[1] if looked else None
        except CdlbibError as exc:
            state.notes.append(f"the pull request of {state.branch} could not be looked up: "
                               f"{' '.join(str(exc).split())[:300]}")
    return state
