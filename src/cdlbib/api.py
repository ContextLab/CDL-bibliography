"""The front-end boundary. Nothing here prints, prompts or exits."""
import contextlib
import os
import io
import sys
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ApprovalRefused, CdlbibError, GateFailed


@dataclass
class FormatResult:
    errors: list
    corrected: object
    outfile: Path | None = None
    log: str = ""        # what helpers.check_bib printed (its verbose log)
    failure: str = ""    # set when check_bib raised instead of returning findings
    forced: list = field(default_factory=list)   # keys of entries that carry a Force field (each is an error)
    corrections: dict = field(default_factory=dict)   # {key: {field: the formatter's value}}; "ID" is the key itself

    @property
    def ok(self):
        return len(self.errors) == 0


@dataclass
class CitationResult:
    ok: bool
    unresolved: dict
    library: dict
    lines: list = field(default_factory=list)
    checked: dict = field(default_factory=dict)


@dataclass
class LibraryCheck:
    format: FormatResult
    citations: CitationResult | None
    ok: bool
    needs_review_of_autofix: bool = False
    citations_due: bool = False   # format passed and the citation check has not run yet
    scope: str = "library"        # what the format check covered: "library" (every entry) or "keys" (check_keys)


@dataclass
class Comparison:
    match: bool
    summary: str
    log: str = ""        # what helpers.compare_bibs printed


@dataclass
class Status:
    counts: dict
    ok: bool

    @property
    def total(self):
        return sum(self.counts.values())


@dataclass
class RevokeResult:
    records: list
    status: str


@dataclass
class SendResult:
    url: str             # the pull request
    branch: str          # the branch the change was committed on; the checkout is left on it
    fork: str
    created_fork: bool = False
    files: list = field(default_factory=list)   # the paths committed by this send ([] when only resuming)
    left: list = field(default_factory=list)    # other changed files, left exactly as they were
    approvals: list = field(default_factory=list)   # keys of the human approvals this send added to the approvals ledger


@dataclass
class Where:
    root: Path                     # the library's folder (for a named file: the file itself)
    origin: str                    # a workspace.Origin value
    last_check: object = None      # managed library only: when the upstream was last consulted (UTC), or None


@contextlib.contextmanager
def _quiet(bars=None):
    """helpers.py prints its log and draws tqdm bars on stderr; the api stays silent and
    keeps the log. A front end that wants the bars passes a stream for them (``bars``)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(bars or io.StringIO()):
        yield out


class _Lines(io.TextIOBase):
    """A stdout stand-in that hands each complete printed line to a callback."""

    def __init__(self, emit):
        self.emit, self.pending = emit, ""

    def writable(self):
        return True

    def write(self, text):
        self.pending += text
        *lines, self.pending = self.pending.split("\n")
        for line in lines:
            self.emit(line)
        return len(text)

    def close_line(self):
        if self.pending:
            self.emit(self.pending)
            self.pending = ""


def ensure_library(progress=None):
    """The library a front end works on when the user names no file: --library, CDLBIB_LIBRARY,
    the nearest cdl.bib from the current folder up, else the managed library, which is
    downloaded first when it is not there (``progress`` receives the one line saying so).
    Raises LibraryUnavailable when that download fails."""
    from . import workspace
    return workspace.resolve(None, managed=True, progress=progress)


def where(fname=None):
    """Which library a command would work on and how it was chosen. Downloads nothing: for a
    managed library not yet downloaded, ``root`` is where it will be."""
    from . import library, workspace
    ws, origin = workspace.origin_of(fname)
    managed = origin == workspace.Origin.MANAGED
    return Where(root=ws.bib if origin == workspace.Origin.NAMED else ws.root, origin=origin,
                 last_check=library.read_state().last_check if managed else None)


def _managed(so="so there are no backups and nothing to undo"):
    from . import library, workspace
    if not library.exists():
        raise CdlbibError(f"cdlbib has not downloaded a library yet (it would be at {library.path()}), {so}.")
    return workspace.Workspace(library.path())


def update(ws=None, decision=None, force=False, progress=None, seen=None):
    """Bring the managed library up to date and return a library.UpdateResult. Without
    ``force`` this is the daily check: nothing is fetched when the last check is under 24
    hours old, nor within an hour of an automatic attempt that failed, and the upstream is
    given 15 seconds. A front end calls it, before a command's own work, only when the
    library in use is the managed one (``is_managed``); ``ws`` None means the managed library
    whatever library is in use (CdlbibError when it has not been downloaded). ``progress``
    receives one line when another command holds the lock and this one has to wait.

    A library without unsent work is changed only by a fast-forward, after a backup
    (``result.backup``); ``result.message`` is the line to show and ``result.notes`` are
    non-fatal remarks. When an update is available and the library holds unsent work,
    nothing is changed and errors.UpdateNeedsDecision is raised (it never asks): the front end
    asks the user and calls again with ``decision`` (one of the exception's ``choices``:
    "keep", "update", "send", "discard") and ``seen`` (the exception's ``seen``). "update" and
    "discard" take a backup first and are undone by ``undo_update``; "update" raises
    errors.UpdateConflict, with nothing changed, when the user's changes and the upstream's
    collide; "send" only records the choice, and the front end runs ``send``.

    A library that a send left on its branch (cdlbib/<login>/...) is handled by that branch's
    pull request, which is asked of GitHub (read-only, with the same short time limit): still
    open, or GitHub cannot be asked: nothing is changed, and the message says so; merged, with
    nothing else on the branch: after a backup the library goes back to the default branch and
    is updated (action ``returned_to_main``); closed, or more on the branch than was sent:
    errors.UpdateNeedsDecision, whose ``branch`` is set.

    When an earlier update was killed before it finished, nothing is updated and no backup is
    deleted until it is undone: the action is ``interrupted``, and the message names the
    backup and the command that restores it (``undo`` with no stamp then restores that
    backup). See library.update. Any other library than the managed one is a CdlbibError, and nothing is
    done to it."""
    from . import library
    return library.update(_managed("so there is nothing to update") if ws is None else ws,
                          force=force, decision=decision, progress=progress, seen=seen)


def is_managed(ws):
    """Is ``ws`` the library cdlbib downloads and manages (its folder, however it was reached)?"""
    from . import library
    return library.exists() and Path(ws.root).resolve() == library.path().resolve()


def holds_only_copy(backup):
    """Does this backup alone keep a commit (one no local branch and no branch of the upstream
    leads to)? Such a backup is never deleted to make room for newer ones."""
    from . import library
    return library.holds_only_copy(backup)


def managed_root():
    """The folder of the managed library; CdlbibError when it has not been downloaded."""
    return _managed().root


def backups():
    """The backups of the managed library (library.Backup), newest first. Whatever library
    the user is working in, this is about the one cdlbib downloads and manages."""
    from . import library
    _managed()
    return library.backups()


@dataclass
class UndoResult:
    restored: object               # the library.Backup the library was put back to
    before: object                 # the backup of the state just before (restoring it undoes the undo)
    taken_off: list = field(default_factory=list)   # (branch, commit): branches now off a commit only ``before`` keeps
    notes: list = field(default_factory=list)       # non-fatal lines (an old backup that could not be removed)


def undo(stamp=None):
    """undo_update(), returning an UndoResult: also the backup taken just before, and the
    branches the undo took off commits that no local branch and no branch of the upstream
    leads to (``before`` keeps those commits and is never deleted while it alone does)."""
    from . import library
    notes = []
    restored, before = library.undo(_managed(), stamp, notes)
    return UndoResult(restored=restored, before=before, taken_off=library.taken_off(before), notes=notes)


def completion_undo_checkpoint():
    """Stamp of the last managed completion command's undo target, if still current."""
    from . import library
    return library._completion_target()


def backups_folder():
    """The folder the backups of the managed library are kept in."""
    from . import library
    return library.backups_folder()


def unreadable_backups():
    """[(stamp, reason)] of the folders among the backups that cannot be read as one."""
    from . import library
    _managed()
    return library.unreadable_backups()


def undo_update(stamp=None):
    """Put the managed library back at its command checkpoint (otherwise newest backup), or the one named
    ``stamp`` (Backup.stamp, as --list shows it), and return that Backup. The current state
    is backed up first (it is then the newest backup), so calling this again undoes the undo.
    Branch, commit and file bytes are restored exactly; changes that were staged come back
    unstaged. CdlbibError when there is no such backup or the restore is refused."""
    return undo(stamp).restored


def check_format(ws, autofix=False, outfile=None, verbose=False, bars=None):
    from .helpers import check_bib
    with _quiet(bars) as sink:
        try:
            errors, corrected = check_bib(str(ws.bib), autofix=autofix, outfile=outfile, verbose=verbose)
        except CdlbibError:
            raise
        except Exception as exc:
            # check_bib raises on some malformed entries (e.g. ambiguous page ranges);
            # that is a format finding, not a crash.
            failure = f"{type(exc).__name__}: {exc}"
            return FormatResult(errors=[failure], corrected=None, outfile=None,
                                log=sink.getvalue(), failure=failure)
    from .complete import has_force
    from .prompts import FORCE_REFUSED
    # The checker leaves an entry that carries Force unchecked. No entry is exempt from the
    # house rules, so each such entry fails the check by name, whatever else it holds.
    forced = [str(item.get("ID")) for item in corrected or () if isinstance(item, dict) and has_force(item)]
    corrections = {key: dict(found) for key, found in errors.items()}
    for key in forced:
        corrections.setdefault(key, {})["force"] = None
    return FormatResult(errors=list(errors) + [key for key in forced if key not in errors], corrected=corrected,
                        outfile=Path(outfile) if outfile else None,
                        log=sink.getvalue() + "".join(f"{key}: {FORCE_REFUSED}\n" for key in forced),
                        corrections=corrections, forced=forced)


def gate_after_format(fmt, citations=True, autofix=False, outfile=None):
    """The gate's state once the format check is done. ``citations_due`` says whether the
    citation check still has to run; when it does not, ``ok`` is final."""
    if not fmt.ok:
        fixed = bool(autofix and outfile and not fmt.failure)
        return LibraryCheck(format=fmt, citations=None, ok=fixed, needs_review_of_autofix=fixed)
    return LibraryCheck(format=fmt, citations=None, ok=True, citations_due=bool(citations))


def check_citations(ws, fmt, reference="github", all_entries=False, database=None, mailto=None,
                    progress=None, bars=None, keys=None):
    """Citation verification of the new/edited entries (or all; or exactly ``keys``, an
    iterable of citation keys); ``progress`` receives each report line as it is produced."""
    from .verification import ProviderError
    from .verification_cli import citation_gate
    lines, selected_results = [], {}
    out, err = sys.stdout, sys.stderr

    def echo(line, **_):
        lines.append(line)
        if progress:
            # the front end's callback writes where the caller's streams point, not into the capture
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                progress(line)

    # The review layers print progress lines of their own; they join the gate's lines in order.
    printed = _Lines(echo)
    try:
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(bars or io.StringIO()):
            try:
                ok, unresolved, library = citation_gate(str(ws.bib), reference=reference, database=database,
                                                        all_entries=all_entries, mailto=mailto, echo=echo,
                                                        selected_results=selected_results, keys=keys)
            finally:
                printed.close_line()
    except (ValueError, OSError, ProviderError) as exc:
        raise GateFailed(f"citation check failed: {type(exc).__name__}: {exc}") from exc
    result = CitationResult(ok=ok, unresolved=unresolved, library=library, lines=lines, checked=selected_results)
    return LibraryCheck(format=fmt, citations=result, ok=ok)


def check_library(ws, reference="github", citations=True, all_entries=False, autofix=False,
                  outfile=None, verbose=False, database=None, mailto=None, progress=None, bars=None):
    """The shared gate of `verify` and `commit` (user decisions 2026-09-25 07:42 and 07:44 EDT).

    (1) the format check (check_bib); (2) citation verification of the added/edited
    entries relative to ``reference`` (the GitHub master cdl.bib by default, the file
    compare_bibs uses; key-only renames excluded), or of every entry with
    ``all_entries``; (3) an offline library-wide status line. ``ok`` is True when the
    format is clean and every checked entry is verified; the library-wide backlog is
    reported but does not fail the gate. ``citations=False`` is the offline,
    format-only check.
    """
    fmt = check_format(ws, autofix=autofix, outfile=outfile, verbose=verbose, bars=bars)
    check = gate_after_format(fmt, citations=citations, autofix=autofix, outfile=outfile)
    if not check.citations_due:
        return check
    return check_citations(ws, fmt, reference=reference, all_entries=all_entries, database=database,
                           mailto=mailto, progress=progress, bars=bars)


def validate_summary_path(outfile, *, ws=None, inputs=(), database=None):
    """Refuse aliases of inputs, evidence, cache and git controls before helper writes."""
    if outfile is None:
        return
    output = Path(outfile).resolve()
    protected = [Path(value) for value in inputs if value and value != "github"]
    folders = []
    if ws is not None:
        db = Path(database or ws.database)
        protected += [ws.bib, db, Path(str(db) + "-wal"), Path(str(db) + "-shm")]
        folders += [ws.work, ws.root / "verification", ws.root / ".git", ws.research_bodies]
        from . import publish
        for flag in ("--git-dir", "--git-common-dir"):
            found = publish._run(["git", "rev-parse", flag], cwd=ws.root, check=False)
            if found.returncode == 0:
                folders.append((ws.root / found.stdout.strip()).resolve())
    for folder in folders:
        resolved = folder.resolve()
        if output == resolved or resolved in output.parents:
            raise CdlbibError("Summary output would overwrite library evidence, cache or git controls")
        if folder.is_dir():
            protected.extend(path for path in folder.rglob("*") if path.is_file())
        elif folder.exists():
            protected.append(folder)
    for path in protected:
        if output == path.resolve() or (output.exists() and path.exists() and output.samefile(path)):
            raise CdlbibError("Summary output would overwrite a bibliography, reference, database or protected library file")


def compare(a, b, verbose=False, outfile=None, bars=None):
    from .helpers import compare_bibs
    validate_summary_path(outfile, inputs=(a, b))
    with _quiet(bars) as sink:
        try:
            match, summary = compare_bibs(a, b, verbose=verbose, outfile=outfile, return_summary=True)
        except (ValueError, OSError) as exc:  # a missing file, or the GitHub copy out of reach
            raise CdlbibError(f"comparison failed: {type(exc).__name__}: {exc}") from exc
    return Comparison(match=bool(match), summary=summary or "", log=sink.getvalue())


def status(ws, database=None, report=None, require_human=False, keys=None, against=None):
    from .verification import ACCEPTED, Cache, ProviderError, validate_output_path, write_report
    from .verification import revocation_ledger
    from .verification_cli import select_keys
    database = database or str(ws.database)
    report = report or str(ws.report)
    try:
        cache = Cache(database, ledger=revocation_ledger(str(ws.bib), None))
        try:
            for selection_input in (keys, against):
                if selection_input:
                    validate_output_path(selection_input, report, cache)
            results = write_report(str(ws.bib), cache, report)
            selected = select_keys(str(ws.bib), keys, against, entries=results)
            results = {key: results[key] for key in selected}
        finally:
            cache.close()
    except (ValueError, OSError, ProviderError) as exc:
        raise GateFailed(str(exc)) from exc
    counts = dict(Counter(r["status"] for r in results.values()))
    accepted = {"human_verified"} if require_human else ACCEPTED
    return Status(counts=counts, ok=all(r["status"] in accepted for r in results.values()))


def approve(ws, key, fingerprint, source, note, database=None):
    """Record a human approval under the GitHub login of the gh CLI (the only source of the
    reviewer's name). Raises IdentityUnavailable before anything is opened or written. The
    library's write lock is held while ``fingerprint`` (the content the reviewer was shown)
    is compared with the entry on disk and the approval is stored, so an edit cannot slip
    in between; content that changed is refused (ApprovalRefused)."""
    from . import identity, library
    from .verification import Cache, record_approval
    from .verification import revocation_ledger
    me = _me()
    review = {"reviewer": me.handle, "source": source, "note": note,
              "github_login": me.login, "github_id": me.id}
    with library.transaction(ws):
        try:
            cache = Cache(database or str(ws.database), ledger=revocation_ledger(str(ws.bib), None))
            try:
                return record_approval(cache, str(ws.bib), key, fingerprint, review)
            finally:
                cache.close()
        except (ValueError, KeyError, OSError) as exc:
            raise ApprovalRefused(_message(exc)) from exc


def revoke(ws, key, reason, fingerprints=None, ledger=None, database=None, expected_fingerprint=None):
    """Withdraw a human approval, recorded under the GitHub login of the gh CLI. The library's
    write lock is held throughout. ``expected_fingerprint``: the fingerprint of the entry as
    the person was shown it; when given and the entry on disk has another, nothing is revoked
    (ApprovalRefused)."""
    from . import identity, library
    from .verification import Cache, load_entries, record_revocation
    from .verification import revocation_ledger
    me = _me()
    ledger_path = revocation_ledger(str(ws.bib), ledger)  # resolved once for the cache and the writer
    with library.transaction(ws):
        try:
            if expected_fingerprint is not None and load_entries(ws.bib)[key]["fingerprint"] != expected_fingerprint:
                raise ValueError("Entry changed since review; revocation rejected")
            cache = Cache(database or str(ws.database), ledger=ledger_path)
            try:
                records, state = record_revocation(cache, str(ws.bib), key, reason, me.handle,
                                                   fingerprints=fingerprints, ledger=ledger_path)
            finally:
                cache.close()
        except (ValueError, KeyError, OSError) as exc:
            raise ApprovalRefused(_message(exc)) from exc
    return RevokeResult(records=records, status=state)


def approvals_note(ws, reference=None, database=None, ledgered=()):
    """The pull request's record of human approvals: '\n\nApproved by @login: KEY, KEY' per
    reviewer, for entries whose current status is human_verified under a GitHub login: the
    entries that differ from ``reference`` (every entry, when none is given), and the entries
    whose current approval is one of the approvals-ledger rows ``ledgered`` (the rows a pull
    request adds), changed or not; '' when there are none."""
    from .verification import Cache, ProviderError, approval_digest, current_results, revocation_ledger
    from .verification_cli import reference_bib, select_keys
    database = Path(database or ws.database)
    if not database.is_file() and not ledgered:
        return ""
    try:
        cache = Cache(str(database) if database.is_file() else ":memory:",
                      ledger=revocation_ledger(str(ws.bib), None))
        try:
            results = current_results(str(ws.bib), cache)
        finally:
            cache.close()
        against = reference_bib(reference, database.parent) if reference else None
        selected = set(select_keys(str(ws.bib), None, against, entries=results))
    except (ValueError, OSError, ProviderError) as exc:
        raise CdlbibError(f"could not read the approvals: {type(exc).__name__}: {exc}") from exc
    added = {(row["fingerprint"], approval_digest(row["human_review"])) for row in ledgered}
    selected |= {key for key, result in results.items()
                 if (result["fingerprint"], approval_digest(result.get("human_review"))) in added}
    by_login = {}
    for key in sorted(selected):
        review = results[key].get("human_review") or {}
        if results[key]["status"] == "human_verified" and review.get("github_login"):
            by_login.setdefault(str(review["github_login"]), []).append(key)
    return "".join(f"\n\nApproved by @{login}: {', '.join(keys)}" for login, keys in sorted(by_login.items()))


APPROVALS_PATH = "verification/approvals.jsonl"


_identity = None    # the GitHub user gh named last, in this process (for what is shown; a send always asks)


def _me(timeout=None):
    """identity.current(), remembered for ``known_identity``."""
    global _identity
    from . import identity
    _identity = None
    _identity = identity.current() if timeout is None else identity.current(timeout=timeout)
    return _identity


def known_identity():
    """The GitHub user gh named the last time this process asked (an approval, a revocation, a
    send, a refreshed library state), or None. Asks nobody."""
    return _identity


def _same_person(review, me):
    """Was ``review`` recorded under the GitHub user ``me``? By the numeric id when the review
    has one, else by the login, whatever its case."""
    recorded = review.get("github_id")
    if isinstance(recorded, int) and not isinstance(recorded, bool):
        return recorded == me.id
    return str(review.get("github_login") or "").lower() == me.login.lower()


def approvals_waiting(ws, database=None, entries=None, me=None):
    """(rows, unsent) for the human approvals in the verification database that
    verification/approvals.jsonl does not hold yet.

    ``rows``: the ledger row (key, fingerprint, human_review, approval_digest, approved_at,
    policy) of each approval a send adds to the ledger: current, for exactly the entry's
    text, not revoked, recorded under a GitHub login, writable as a row and, when ``me`` (an
    identity.Identity) is given, recorded under that user. A send passes the logged-in user:
    it ledgers nobody else's approval.

    ``unsent``: [{"key", "login", "why"}] for each approval under a GitHub login that a send
    does not add: "recorded under @login" (another user's, when ``me`` is given), or why it
    cannot be written as a row.

    ([], []) when there is no verification database. The database is asked through a
    read-only connection first, and opened as the verifier opens it only when a stored human
    approval is there to be read. ``entries``: the parsed library, when the caller holds it."""
    from .verification import Cache, approval_candidates, ledger_bytes, load_entries, unshared_approvals
    database = Path(database or ws.database)
    if not database.is_file():
        return [], []
    try:
        ledger_bytes(ws.approvals)       # a link in the place of the ledger or its folder is refused before any read
        entries = entries if entries is not None else load_entries(str(ws.bib))
        try:
            held = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                if not approval_candidates(held, str(ws.bib), entries):
                    return [], []
            finally:
                held.close()
        except sqlite3.OperationalError:
            pass                         # a database the verifier has not set up yet, or a busy one: read as usual
        cache = Cache(str(database), ledger=ws.revocations)
        try:
            rows, unwritable = unshared_approvals(str(ws.bib), cache, ws.approvals, entries=entries)
        finally:
            cache.close()
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        raise CdlbibError(f"could not read the approvals: {type(exc).__name__}: {exc}") from exc
    unsent = [{"key": key, "login": login, "why": f"it cannot be written to {APPROVALS_PATH}: {why}"}
              for key, login, why in unwritable]
    if me is not None:
        mine = [row for row in rows if _same_person(row["human_review"], me)]
        unsent += [{"key": row["key"], "login": row["human_review"]["github_login"],
                    "why": f"recorded under @{row['human_review']['github_login']}"}
                   for row in rows if not _same_person(row["human_review"], me)]
        rows = mine
    order = {key: place for place, key in enumerate(entries)}
    return rows, sorted(unsent, key=lambda item: order.get(item["key"], len(order)))


def approvals_to_send(ws, database=None, entries=None, me=None):
    """``approvals_waiting``'s rows: what a send by ``me`` adds to verification/approvals.jsonl
    (without ``me``: what a send by the right user would)."""
    return approvals_waiting(ws, database=database, entries=entries, me=me)[0]


def unsent_line(item):
    """The sentence for one of ``approvals_waiting``'s unsent approvals."""
    return f"approval of {item['key']} not sent: {item['why']}"


def approval_problems(ws):
    """What is ignored in the approvals ledger the library reads (verification/approvals.jsonl,
): a sentence for each line that is not a valid
    row, or for the file when it cannot be read. Such a line approves nothing. [] when all is
    well or there is no ledger."""
    from .verification import approval_ledger, revocation_ledger, scan_approval_ledger
    return scan_approval_ledger(approval_ledger(revocation_ledger(str(ws.bib), None)))[1]


def _approval_login(row):
    return "@" + str(row["human_review"]["github_login"])


APPROVAL_SEND = "approval-send"          # <.bibcheck>/approval-send/pending.json: the record of rows a send added
APPROVAL_SEND_RECORD = "pending.json"


def _sha(data):
    import hashlib
    return None if data is None else hashlib.sha256(data).hexdigest()


def _index_entry(ws):
    """What git's index holds for the approvals ledger ('' when nothing; None when git cannot say)."""
    from . import publish
    run = publish._run(["git", "ls-files", "-s", "--", APPROVALS_PATH], cwd=ws.root, check=False)
    return run.stdout.strip() if run.returncode == 0 else None


def _held_by_commit(ws):
    """Does the commit the checkout is on hold the approvals ledger exactly as the file is now?"""
    from . import publish
    blob = publish._run(["git", "rev-parse", "--verify", "--quiet", f"HEAD:{APPROVALS_PATH}"], cwd=ws.root, check=False)
    now = publish._run(["git", "hash-object", "--no-filters", "--", APPROVALS_PATH], cwd=ws.root, check=False)
    return blob.returncode == 0 and now.returncode == 0 and blob.stdout.strip() == now.stdout.strip() != ""


def _ledger_approvals(ws, rows, progress=None):
    """Add ``rows`` to the library's approvals ledger and say so, a line each. Before the
    ledger is touched, a record of what is about to be added is kept durably under
    <.bibcheck>/approval-send (writer.keep_record), so that ``settle_approval_send`` can put
    the ledger back whether this process goes on, fails, or is killed. The ledger is read
    and replaced whole within its folder held open, refusing links (verification.append_approvals)."""
    import json
    from . import writer
    from .verification import approval_lines, ledger_bytes, write_ledger
    if not rows:
        return
    try:
        before, mode = ledger_bytes(ws.approvals)
        text = approval_lines(before, rows)
        after = (before or b"") + text
        record = {"before_sha": _sha(before), "after_sha": _sha(after), "appended": text.decode("utf-8"),
                  "index": _index_entry(ws), "keys": [row["key"] for row in rows]}
        writer.keep_record(ws, APPROVAL_SEND, APPROVAL_SEND_RECORD, json.dumps(record).encode("utf-8"))
        write_ledger(ws.approvals, after, mode if mode is not None else 0o644)
    except (OSError, ValueError) as exc:
        raise CdlbibError(f"The approvals could not be added to {APPROVALS_PATH}: {exc}") from exc
    if progress:
        for row in rows:
            progress(f"approval of {row['key']} by {_approval_login(row)}: added to {APPROVALS_PATH}")


def settle_approval_send(ws):
    """Settle the rows a send added to the approvals ledger and did not finish with, from the
    record ``_ledger_approvals`` kept. Returns (lines, problem).

    - No record: ([], None).
    - The ledger holds exactly what the send left and the commit the checkout is on holds
      it: the rows were committed; the record is dropped.
    - The ledger holds exactly what the send left, uncommitted: it is put back byte for byte
      as it was before (removed when there was none), git's index entry for it is put back
      as it was, and ``lines`` says so.
    - The ledger is as it was before: only the record (and the index entry) is settled.
    - Anything else (another program changed the ledger since, a link is in its place, the
      record cannot be read): nothing is written to the ledger, the record is dropped, and
      ``problem`` says what was not put back and which rows the send had added.

    Called when a send fails, and whenever the library's lock is taken (library.transaction),
    which is how a send that was killed is settled."""
    import json
    from . import publish, writer
    from .verification import ledger_bytes, write_ledger
    try:
        raw = writer.records(ws, APPROVAL_SEND).get(APPROVAL_SEND_RECORD)
    except (OSError, CdlbibError) as exc:
        return [], f"The record of an unfinished send ({ws.work / APPROVAL_SEND / APPROVAL_SEND_RECORD}) could not be read: {exc}"
    if raw is None:
        return [], None

    def drop():
        with contextlib.suppress(OSError, CdlbibError):
            writer.drop_record(ws, APPROVAL_SEND, APPROVAL_SEND_RECORD)

    try:
        record = json.loads(raw.decode("utf-8"))
        before_sha, after_sha, index, keys = record["before_sha"], record["after_sha"], record["index"], record["keys"]
        appended = record["appended"].encode("utf-8")
        if not (isinstance(after_sha, str) and (before_sha is None or isinstance(before_sha, str)) and appended
                and isinstance(keys, list) and (index is None or isinstance(index, str))):
            raise ValueError("unexpected contents")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        drop()
        return [], (f"A send that did not finish left a record that cannot be read ({exc}); {APPROVALS_PATH} was "
                    "not touched. Look at it with `git diff -- verification/approvals.jsonl`.")
    named = ", ".join(str(key) for key in keys)
    not_put_back = (f"{APPROVALS_PATH} was NOT put back as it was before the send: {{why}}. The send had added the "
                    f"approval{'s' if len(keys) != 1 else ''} of {named}; the file is left as it is now. Look at it "
                    "with `git diff -- verification/approvals.jsonl` and remove those lines, or send again.")
    try:
        current, mode = ledger_bytes(ws.approvals)
    except ValueError as exc:
        drop()
        return [], not_put_back.format(why=str(exc))

    def index_back():
        now = _index_entry(ws)
        if index is None or now is None or now == index:
            return
        if index == "":
            publish._run(["git", "update-index", "--force-remove", "--", APPROVALS_PATH], cwd=ws.root, check=False)
        else:
            meta, _, name = index.partition("\t")
            mode_, blob, _stage = (meta.split() + ["", "", ""])[:3]
            publish._run(["git", "update-index", "--add", "--cacheinfo", f"{mode_},{blob},{name}"], cwd=ws.root, check=False)

    if _sha(current) == after_sha:
        if _held_by_commit(ws):
            drop()
            return [], None
        before = current[:len(current) - len(appended)]
        if not current.endswith(appended) or _sha(before if before_sha is not None else None) != before_sha:
            drop()
            return [], not_put_back.format(why="what it held before could not be worked out from the record")
        try:
            write_ledger(ws.approvals, before if before_sha is not None else None, mode)
        except ValueError as exc:
            drop()
            return [], not_put_back.format(why=str(exc))
        index_back()
        drop()
        return [f"not sent: {APPROVALS_PATH} is as it was before (the approvals stay in the local database)"], None
    if _sha(current) == before_sha:
        index_back()
        drop()
        return [], None
    drop()
    return [], not_put_back.format(why="something else changed the file after the send added its rows")


def _ledger_rows_since(ws, commit):
    """The rows of the library's approvals ledger that the copy in ``commit`` does not hold."""
    import json
    from . import publish
    from .verification import approval_digest, ledger_bytes, scan_approval_ledger
    try:
        if ledger_bytes(ws.approvals)[0] is None:
            return []
    except ValueError as exc:
        raise CdlbibError(str(exc)) from exc
    rows = scan_approval_ledger(ws.approvals)[0]
    held = set()
    for line in (publish.file_at(ws, commit, APPROVALS_PATH) or "").splitlines():
        try:
            row = json.loads(line)
            held.add((row["fingerprint"], approval_digest(row["human_review"])))
        except (ValueError, KeyError, TypeError):
            continue                     # not a row: it holds no approval
    return [row for row in rows if (row["fingerprint"], approval_digest(row["human_review"])) not in held]


def _outgoing_ledger(ws):
    """What the working tree's approvals ledger adds to the copy in the commit the checkout
    is on, checked: (rows, why not). The ledger only grows: the committed bytes must still be
    there, first; every added line must be a valid row. ``why not`` is the sentence of the
    refusal when one of those fails (the rows are then [])."""
    from . import publish
    from .verification import ledger_additions, ledger_bytes
    try:
        current, _ = ledger_bytes(ws.approvals)
    except ValueError as exc:
        raise CdlbibError(str(exc)) from exc
    blob = publish._run(["git", "rev-parse", "--verify", "--quiet", f"HEAD:{APPROVALS_PATH}"], cwd=ws.root, check=False)
    committed = b""
    if blob.returncode == 0 and blob.stdout.strip():
        import subprocess
        from .gitenv import git_env
        committed = subprocess.run(["git", "cat-file", "blob", blob.stdout.strip()], cwd=ws.root, capture_output=True,
                                   env=git_env()).stdout
    if current is None and not committed:
        return [], None
    rows, problems = ledger_additions(committed, current)
    if rows and not problems:            # held to the bibliography as it stands (parsed only when rows were added)
        from .verification import load_entries
        try:
            rows, problems = ledger_additions(committed, current, entries=load_entries(str(ws.bib)))
        except (OSError, ValueError) as exc:
            raise CdlbibError(f"{ws.bib} could not be read: {exc}") from exc
    if problems:
        return [], (f"{APPROVALS_PATH} cannot be sent as it is: {'; '.join(problems)}. A send commits only valid "
                    "rows added after the committed ones. Nothing was changed. Put the file right (`git diff -- "
                    "verification/approvals.jsonl` shows the lines), then send again.")
    return rows, None


def _require_own(rows, me, where):
    """Refuse (PublishRefused) when a ledger row that is about to be sent was not recorded
    under the sender ``me``."""
    from .errors import PublishRefused
    others = [row for row in rows if not _same_person(row["human_review"], me)]
    if others:
        named = "; ".join(f"{row['key']} (recorded under @{row['human_review']['github_login']})" for row in others)
        raise PublishRefused(
            f"{APPROVALS_PATH} holds {'a row' if len(others) == 1 else 'rows'} {where} that {me.handle} did not "
            f"record: {named}. A send adds only the sender's own approvals; nothing was sent. Remove "
            f"{'that line' if len(others) == 1 else 'those lines'}, then send again.")


def _still(me):
    """The logged-in GitHub user, asked again: PublishRefused unless it is still ``me``."""
    from .errors import IdentityUnavailable, PublishRefused
    try:
        now = _me()
    except IdentityUnavailable as exc:
        raise PublishRefused(f"The GitHub login changed during the send: it was {me.handle}, and now nobody is "
                             f"logged in ({exc}). Nothing was sent.") from exc
    if now.id != me.id or now.login.lower() != me.login.lower():
        raise PublishRefused(f"The GitHub login changed during the send: it was {me.handle}, and is now "
                             f"{now.handle}. Nothing was sent.")
    return now


def _send_evidence(ws, *, reference, database=None):
    """Acceptance-bearing state, independent of SQLite page/WAL bookkeeping.

    Use the verifier's current-result authority, including retained negative evidence
    and revocations. Response-cache writes and physical database maintenance are not
    approvals. Reading results also settles the existing legacy fingerprint migration.
    """
    import hashlib
    from .verification import Cache, current_results
    from .errors import PublishRefused
    db = Path(database or ws.database)
    cache = None
    try:
        results, sources = None, None
        if db.exists():
            cache = Cache(db, ledger=ws.revocations)
            cache.index_notices()
            results = current_results(str(ws.bib), cache)
            sources = tuple(tuple(cache.db.execute(
                f"SELECT doi,evidence_hash,candidate FROM {table} ORDER BY doi,evidence_hash"))
                for table in ("source_notices", "source_author_suffixes", "source_article_locators"))
        against = None
        if reference and reference != 'github':
            against = hashlib.sha256(Path(reference).read_bytes()).digest()
        return results, sources, against
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        raise PublishRefused(
            "The verification database or reference changed after the gate or could not be read; "
            f"nothing was pushed. Run send again to check the current evidence. ({exc})") from exc
    finally:
        if cache is not None:
            cache.close()


from .library import serialized


@serialized
def send(ws, summary=None, reference="github", citations=True, mailto=None, database=None, progress=None,
         bars=None, report=None, upstream=None, base="master", fork=None, allow_fork_creation=False,
         outfile=None, verbose=False, *, _test_inside_own_fork=False):
    """The one way a change leaves this machine: the gate, then a commit of cdl.bib and
    verification/ on a branch, pushed to the user's own fork, and a pull request into the
    upstream repository (the checkout's origin, or its parent when the origin is a fork).

    Only cdl.bib and changed files under verification/ are committed and pushed. Every other
    modified, staged or untracked file is left exactly as it was (``SendResult.left``), and
    .bibcheck/ is never sent.

    Human approvals are sent too. Each current human approval in the verification database
    that was recorded under the GitHub login of the gh CLI (asked first, when an approval
    waits; compared by the numeric id, else the login) and is not yet in
    verification/approvals.jsonl (``approvals_waiting``) is appended to that file before the
    gate, and ``progress`` receives a line for each; they alone are a change to send. An
    approval recorded under another login, or one that cannot be written as a row, is never
    added: ``progress`` receives "approval of KEY not sent: why", and when nothing else is
    to be sent the refusal names each. When the send stops before a
    commit holds them, the file is put back as it was (``progress`` receives a line), so a
    refused send leaves the checkout as it was; the approvals stay in the database and the
    next send adds them again. A record of the added rows is kept under .bibcheck/ while
    the send runs, so a send that is killed is settled the next time the library's lock is
    taken. When the file cannot be put back (something else changed it meanwhile), nothing
    is written to it and the refusal says so and names the rows. Rows already in the
    working tree's ledger and not yet committed must be valid rows recorded under the same
    login, and the committed lines must be unchanged, or the send is refused before anything
    is written. gh is asked who is logged in once before the rows are chosen and again
    before publication; a different answer refuses the send. ``SendResult.approvals`` names the entries whose approvals were
    committed, and the pull request's text names them with their reviewers.

    Order: a checkout on no branch refuses; nothing to send refuses; no git author refuses; the
    gate (check_library) refuses; no GitHub login refuses; a branch whose pull request is
    already merged or closed refuses; no fork refuses (PublishRefused.needs_fork) unless
    ``allow_fork_creation``; only then is git written to. A send refused up to there leaves
    the checkout as it was.

    One exception, for the library cdlbib manages only (never for a library the user chose):
    when the branch's pull request is MERGED, the send does not refuse. The library is first
    put back on the default branch and updated, after a backup and with the changes that are
    to be sent kept (library.update's "update": ``progress`` receives its line, and `cdlbib
    update --undo` reverses it); the gate is run again on the result; and the send goes on,
    on a new branch. When that cannot be done (the old branch holds commits that were never
    sent, the changes collide with the new version) it is a PublishRefused or an
    UpdateConflict that says so, with the library as it was. A failure after that (commit, push, pull request) says where
    things stand and how to resume. A send that succeeds leaves the checkout on
    ``SendResult.branch``; a send made from that branch adds to it and updates the same
    pull request.

    ``report`` receives the LibraryCheck once the format check is done (before the citation
    check); ``progress`` each line of the citation check, then of the comparison with
    ``reference`` (its summary is also written to ``outfile``). ``fork`` names the fork to
    push to instead of looking it up; it is never the upstream.

    ``_test_inside_own_fork`` (keyword-only) exists only for the test suite: it lets a send
    be run for real with the pull request opened inside the tester's own fork (``upstream``
    and ``fork`` both name it), so that no shared repository is touched. GitHub must confirm
    that repository is a fork owned by the logged-in user, or the send is refused before
    git is written to. No front end passes it.
    """
    from . import library, publish
    from .errors import PublishRefused

    # Taking the lock settled any write to this library that was killed part-way (or refused):
    # what is checked and sent below is a whole library, never a half-made change.
    for line in library.settled(ws):
        if progress:
            progress(line)

    def not_upstream(candidate, target):
        if candidate and target and candidate.lower() == target.lower() and not _test_inside_own_fork:
            raise PublishRefused(f"{candidate} is the upstream repository, not a fork of it; a change is never "
                                 "pushed to the upstream.")

    publish.require_canonical(ws)
    validate_summary_path(outfile, ws=ws, inputs=(reference,), database=database)
    not_upstream(fork, upstream)
    here = publish.require_branch(ws, base)
    waiting, unsent = approvals_waiting(ws, database=database)
    outgoing, why_not = _outgoing_ledger(ws)
    if why_not:
        raise PublishRefused(why_not)
    me = None
    if waiting or outgoing:
        # Whose they are decides whether they are sent: only the logged-in user's own. gh is
        # asked now, once, and only because an approval waits or the ledger already holds
        # uncommitted rows; that one answer is what every row of this send is held to.
        me = _me()
        waiting, unsent = approvals_waiting(ws, database=database, me=me)
        _require_own(outgoing, me, "not yet committed")
    if progress:
        for problem in approval_problems(ws):
            progress(problem)
        for item in unsent:
            progress(unsent_line(item))
    if not publish.pending(ws) and not waiting and not here.startswith("cdlbib/"):
        # before anything outward: no fork, for nothing. An approval that waits and cannot be
        # sent is named: a send of it alone does not pass for a send.
        raise PublishRefused(publish.NO_CHANGES + "".join(f"\n{unsent_line(item)}" for item in unsent))
    publish.require_identity(ws)
    # The approvals go into the ledger before the gate, which checks the files as they will
    # be committed. A send that stops before a commit holds them takes them out again; one
    # that is killed is settled when the library's lock is next taken (settle_approval_send).
    try:
        _ledger_approvals(ws, waiting, progress)
        result = _send(ws, here, not_upstream, [row["key"] for row in waiting], me,
                       summary=summary, reference=reference, citations=citations, mailto=mailto, database=database,
                       progress=progress, bars=bars, report=report, upstream=upstream, base=base, fork=fork,
                       allow_fork_creation=allow_fork_creation, outfile=outfile, verbose=verbose,
                       _test_inside_own_fork=_test_inside_own_fork)
    except BaseException as exc:
        lines, problem = settle_approval_send(ws)
        if progress:
            for line in lines + ([problem] if problem else []):
                with contextlib.suppress(Exception):     # the callback may be what failed
                    progress(line)
        if problem:
            raise PublishRefused(f"{exc}\n{problem}") from exc
        raise
    settle_approval_send(ws)             # the rows are committed: only the record is dropped
    return result


def _send(ws, here, not_upstream, approvals, sender, *, summary, reference, citations, mailto, database, progress, bars,
          report, upstream, base, fork, allow_fork_creation, outfile, verbose, _test_inside_own_fork):
    """``send`` from the gate on: the changes are in the working tree (see send)."""
    import datetime
    from . import identity, publish
    from .errors import PublishRefused

    def evidence():
        return _send_evidence(ws, reference=reference, database=database)

    def gate():
        """The gate, then the comparison with ``reference``: what the change is, in words."""
        before = publish.candidate(ws)
        fmt = check_format(ws, bars=bars)
        check = gate_after_format(fmt, citations=citations)
        due, passed = bool(check.citations_due), bool(check.ok)      # the gate's own verdict, kept out of reach
        if report:
            import copy
            report(copy.deepcopy(check))      # a callback is shown a copy: nothing it does to it reaches the gate
        if due:
            check = check_citations(ws, fmt, reference=reference, database=database, mailto=mailto,
                                    progress=progress, bars=bars)
            passed = bool(check.ok)
        if not passed:
            raise GateFailed("not sent: fix the format errors and resolve every new/edited entry first "
                             "(see `cdlbib verify`).", check=check)
        publish.require_candidate(ws, before)
        accepted_evidence = evidence()
        if check.citations is not None and any(
            (accepted_evidence[0] or {}).get(key) != result
            for key, result in check.citations.checked.items()
        ):
            raise PublishRefused("The selected verification results changed after the citation gate; nothing was pushed. Run send again to check the current evidence.")
        if progress:
            progress("checks passed; generating commit message...")
        comparison = compare(reference, str(ws.bib), verbose=verbose, outfile=outfile, bars=bars)
        if progress:
            for line in comparison.log.splitlines():
                progress(line)
        publish.require_candidate(ws, before)
        if evidence() != accepted_evidence:
            raise PublishRefused("The verification database or reference changed after the gate; nothing was pushed. Run send again to check the current evidence.")
        return comparison.summary.strip() or "update bibliography", before, accepted_evidence

    changes, checked, checked_evidence = gate()
    me = _still(sender) if sender is not None else _me()    # the one the approvals were chosen by, still
    resumed = here.startswith(publish.branch_prefix(me.login))   # sent from here before: same pull request
    if not publish.pending(ws) and not resumed:
        raise PublishRefused(publish.NO_CHANGES)
    if _test_inside_own_fork and not (upstream and fork and upstream.lower() == fork.lower()
                            and publish.is_own_fork(fork, me.login)):
        raise PublishRefused(f"_test_inside_own_fork needs upstream and fork to name one fork owned by {me.handle}; "
                             f"got upstream {upstream}, fork {fork}.")
    found = None
    if upstream is None:
        upstream, found = publish.resolve(ws, me.login)
    elif not fork:
        found = publish.find_fork(upstream, me.login)
    fork, created = fork or found, False
    not_upstream(fork, upstream)
    def fresh():
        return publish.branch_name(me.login, summary or changes.splitlines()[0][:100], datetime.date.today())

    def finished(name):
        """The pull request from the fork's branch ``name``, when it is merged or closed."""
        found = publish.pull_request(upstream, f"{fork.split('/')[0]}:{name}")
        return found if found and found.state != "open" else None

    branch, returned = here if resumed else fresh(), ""
    if fork:                             # this branch's pull request may be finished already
        earlier = finished(branch)
        if earlier and resumed and earlier.state == "merged" and is_managed(ws):
            # The managed library goes back to the default branch by itself, updated, with the
            # changes kept. They now lie on the new version, so the gate runs again.
            returned = _back_to_main(ws, earlier, progress)
            changes, checked, checked_evidence = gate()
            here, resumed = publish.require_branch(ws, base), False
            branch = fresh()
            earlier = finished(branch)
        if earlier and resumed:
            raise PublishRefused(
                f"You are on branch {branch}, whose pull request {earlier.url} is {earlier.state}; a new change needs a "
                f"new branch. Nothing was changed. Go back to {base}, bring it up to date and send again:\n"
                f"  git switch {base}\n  git pull https://github.com/{upstream}.git {base}\n  cdlbib send\n"
                "Your uncommitted edits to cdl.bib and verification/ are carried along by `git switch`; "
                "nothing is lost.")
        if earlier:
            raise PublishRefused(
                f"Branch {branch} was already used for pull request {earlier.url}, which is {earlier.state}; a new "
                f"change needs a new branch. {returned or 'Nothing was changed.'} Send again with a different "
                "--summary (the branch is named after it and today's date).")
    def revalidate():
        if evidence() != checked_evidence:
            raise PublishRefused("The verification database or reference changed after the gate; nothing was pushed. Run send again to check the current evidence.")

    revalidate()
    body = changes + approvals_note(ws, reference=reference, database=database)
    revalidate()
    title = (summary or changes.splitlines()[0])[:100]
    if not fork:
        if not allow_fork_creation:
            raise PublishRefused(f"{me.handle} has no fork of {upstream}.", needs_fork=True, upstream=upstream)
        fork, created = publish.create_fork(upstream), True
    if os.path.lexists(ws.approvals):
        # Approvals the pull request adds for entries it does not change are named in its
        # text too: the ledger's rows that the upstream's copy does not hold. Every one of
        # them must be the sender's own, and the sender must still be who was asked.
        added = _ledger_rows_since(ws, publish.upstream_base(ws, f"https://github.com/{upstream}.git", base))
        if added:
            me = _still(me)
            _require_own(added, me, f"that {upstream} does not have")
            body = changes + approvals_note(ws, reference=reference, database=database, ledgered=added)
            revalidate()
    files = publish.deliver(ws, branch, changes, f"https://github.com/{fork}.git", target=fork,
                            upstream_url=f"https://github.com/{upstream}.git", base=base, expected=checked, revalidate=revalidate)
    try:
        url = publish.open_or_update_pr(upstream, base, f"{fork.split('/')[0]}:{branch}", title, body,
                                        retitle=bool(summary))   # an open pull request keeps its title unless one is given
    except PublishRefused as exc:
        raise PublishRefused(
            f"The change is committed on branch {branch} and pushed to {fork}, but the pull request could not be "
            f"opened or updated. Run `cdlbib send` again to resume from there.{publish.go_back(here, branch)}\n{exc}") from exc
    return SendResult(url=url, branch=branch, fork=fork, created_fork=created, files=files,
                      left=publish.unrelated_changes(ws),
                      approvals=approvals if APPROVALS_PATH in files else [])


def _back_to_main(ws, merged, progress=None):
    """For a send from the managed library's old send branch, whose pull request (``merged``, a
    publish.PullRequest) GitHub says is merged: put the library back on the default branch,
    updated, with the changes that are to be sent kept (library.update on a send branch, with
    the decision "update" when there are changes; a backup is taken first). Returns the
    sentence saying what was done, which ``progress`` also receives. PublishRefused when the
    library could not be returned (it is then as it was) or nothing is left to send;
    UpdateConflict when the changes collide with the new version (nothing changed)."""
    from . import library, publish
    from .errors import PublishRefused, UpdateNeedsDecision
    try:
        result = library._after_send(ws, merged.state, url=merged.url, head=merged.head, matching=merged.matching,
                                     decision="update" if publish.pending(ws) else None)
    except UpdateNeedsDecision as exc:
        raise PublishRefused(f"not sent: {str(exc)[0].lower()}{str(exc)[1:]} Run `cdlbib update` to choose what "
                             "to do with them.") from exc
    if result.action != "returned_to_main":
        raise PublishRefused(f"not sent: {result.message}")
    said = result.message[0].upper() + result.message[1:] + "."
    if progress:
        for note in result.notes:
            progress(note)
        progress(result.message)
    if not publish.pending(ws):
        raise PublishRefused(f"{publish.NO_CHANGES} {said}")
    return said


def _message(exc):
    # str(KeyError('Nope')) is "'Nope'"; the CLI printed exactly that, so the text is kept as is.
    return str(exc)


# --- reference intake ---

def find_candidates(ws, title=None, authors=(), year=None, mailto=None, database=None, progress=None,
                    limit=None, per_source=None):
    """Leads for a title, one or several authors, or both; see intake.find_candidates.
    A lead becomes an entry only through propose_new([candidate_query(lead)]). ``limit``
    (leads returned; default intake.CANDIDATE_LIMIT) and ``per_source`` (records asked of
    each source; default intake.PER_SOURCE) are intake's own, and bounded there: never more
    than intake.MAX_CANDIDATES and intake.MAX_PER_SOURCE, whatever is passed."""
    from . import intake
    return intake.find_candidates(ws, title=title, authors=authors, year=year, mailto=mailto,
                                  database=database, progress=progress,
                                  limit=intake.CANDIDATE_LIMIT if limit is None else limit,
                                  per_source=intake.PER_SOURCE if per_source is None else per_source)


def candidate_query(candidate):
    """The query that names a lead by its identifier, for propose_new."""
    from . import intake
    return intake.query_for(candidate)


def read_pdf(path, ocr=True, progress=None, ocr_seconds=None, name=None):
    """The first pages of a PDF, its identifiers and a title guess; see intake.read_pdf."""
    from . import intake
    return intake.read_pdf(path, ocr=ocr, progress=progress, ocr_seconds=ocr_seconds, name=name)


def render_first_page(path, width=800):
    """Page 1 of a PDF as PNG bytes; see intake.render_first_page."""
    from . import intake
    return intake.render_first_page(path, width)


def propose_from_pdf(ws, pdf, mailto=None, database=None, progress=None):
    """The source record of a read PDF, built and checked; see intake.propose_from_pdf."""
    from . import intake
    return intake.propose_from_pdf(ws, pdf, mailto=mailto, database=database, progress=progress)


def model_routes(probe=()):
    """The model routes and whether each is set up; see intake.model_routes."""
    from . import intake
    return intake.model_routes(probe=probe)


def read_pdf_with_model(ws, pdf, route="dartmouth", progress=None):
    """A model's reading of a PDF as an unverified proposal; see intake.read_pdf_with_model."""
    from . import intake
    return intake.read_pdf_with_model(ws, pdf, route=route, progress=progress)


def draft_manual(ws, fields, entry_type="article", prefill=None):
    """A hand-typed entry in house format, unverified; see intake.draft_manual."""
    from . import intake
    return intake.draft_manual(ws, fields, entry_type=entry_type, prefill=prefill)


def manual_prefill(pdf, proposal=None):
    """Fields for a manual form from what was read of a PDF; see intake.prefill_from."""
    from . import intake
    return intake.prefill_from(pdf, proposal)


def model_evidence(proposal, pdf):
    """The evidence record of a model-read proposal; see intake.evidence_for."""
    from . import intake
    return intake.evidence_for(proposal, pdf)


def attach_model_evidence(ws, key, evidence, fingerprint, database=None):
    """Store a model reading's evidence with a written entry, bound to its fingerprint; never
    an approval. accept_draft does this itself; this is the retry. See intake.attach_model_evidence."""
    from . import intake
    return intake.attach_model_evidence(ws, key, evidence, fingerprint, database=database)


def accept_draft(ws, proposal, pdf=None, database=None):
    """Write an accepted model-read or hand-typed draft and store its model evidence, in one
    action under the write lock; returns intake.Accepted. Never an approval. See intake.accept_draft."""
    from . import intake
    return intake.accept_draft(ws, proposal, pdf=pdf, database=database)


def intake_data(value):
    """Anything intake returned (candidates, a read PDF, a PDF result, a proposal, an
    acceptance) as plain data for json.dumps, with nothing dropped. See intake.to_data."""
    from . import intake
    return intake.to_data(value)


class ProposalResults(list):
    """Proposals plus incremental (query/key, reason) errors; successes are retained."""
    def __init__(self):
        super().__init__()
        self.errors = []


def _proposals(ws, queries, mailto=None, database=None, progress=None, client=None):
    from . import complete, extra_sources
    from .verification import ProviderError
    results = ProposalResults()
    queries = list(queries)
    if not queries:
        return results
    owns_client = client is None
    try:
        if owns_client:
            path = database or ws.database
            contact = mailto or extra_sources.contact_email(path)
            client = extra_sources.make_client(path, contact=contact)
        for label, query in queries:
            try:
                query = query if isinstance(query, complete.Query) else complete.Query.parse(query)
                proposal = complete.propose(query, client, client.cache, ws=ws, batch=results)
                results.append(proposal)
                if proposal_failed(proposal):
                    results.errors.append((label, '; '.join(proposal.issues)))
                if progress:
                    progress(f'{label}: {proposal.status or "needs review"}')
            except (CdlbibError, OSError, ValueError, TypeError, ProviderError, sqlite3.Error) as exc:
                results.errors.append((label, str(exc)))
                results.append(complete.Proposal(issues=[str(exc)], needs_decision=True))
                if progress:
                    progress(f'{label}: {exc}')
        return results
    except (OSError, ValueError, TypeError, ProviderError, sqlite3.Error) as exc:
        raise CdlbibError(f'Entry completion could not start: {exc}') from exc
    finally:
        if owns_client and client is not None:
            client.cache.close()


def propose_new(ws, queries, mailto=None, database=None, progress=None):
    """Find/build/check queries; list-compatible result.errors retains per-query failures.

    Nothing is written or approved. ``progress`` receives one line per processed query.
    """
    return _proposals(ws, ((str(query), query) for query in queries), mailto, database, progress)


def completion_keys(ws, keys=None, reference='github', database=None):
    """Select changed, currently unaccepted entries without provider lookups or writes."""
    import tempfile
    from .verification import ACCEPTED, Cache, current_results, load_entries
    from .verification_cli import reference_bib, select_keys
    try:
        entries = load_entries(ws.bib)
        with tempfile.TemporaryDirectory(prefix='cdlbib-reference-') as folder:
            against = reference_bib(reference, folder) if reference is not None and keys is None else None
            selected = select_keys(ws.bib, keys=keys, against=against, entries=entries)
        cache = Cache(database or ws.database, ledger=ws.revocations)
        try:
            statuses = current_results(ws.bib, cache, entries=entries)
        finally:
            cache.close()
        return [key for key in entries if key in selected and statuses[key]['status'] not in ACCEPTED]
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        raise CdlbibError(f'Entries could not be selected for completion: {exc}') from exc


def propose(ws, keys=None, reference='github', mailto=None, database=None, progress=None):
    """Propose changed entries lacking current accepted verification; never write or prompt."""
    from . import complete
    from .verification import load_entries
    selected = completion_keys(ws, keys=keys, reference=reference, database=database)
    try:
        entries = load_entries(ws.bib)
        return _proposals(ws, ((key, complete.Query.from_entry(entries[key])) for key in selected),
                          mailto, database, progress)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        raise CdlbibError(f'Entries could not be selected for completion: {exc}') from exc


def apply_proposals(ws, accepted, *, batch=None):
    """Write only the explicitly accepted proposals; see complete.apply."""
    from .complete import apply
    return apply(ws, accepted, batch=batch)


def recheck_proposal(ws, proposal, raw, mailto=None, database=None, resolved_fields=()):
    """Check exact edited text and retain review evidence for untouched values.

    Malformed saved text raises EditedEntryParseError; workspace/client failures
    raise CdlbibError. Neither case mutates the input proposal or bibliography.
    """
    import tempfile
    from dataclasses import replace
    from . import complete, extra_sources
    from .errors import EditedEntryParseError
    from .verification import load_entries, ProviderError
    client = None
    try:
        with tempfile.TemporaryDirectory(prefix='cdlbib-edited-') as folder:
            path = Path(folder) / 'edited.bib'
            path.write_text(raw, encoding='utf-8')
            try:
                entries = load_entries(path)
            except ValueError as exc:
                raise EditedEntryParseError(str(exc)) from exc
        if len(entries) != 1:
            raise EditedEntryParseError('The edited text must contain exactly one entry')
        entry = next(iter(entries.values()))
        if entry['raw'].strip() != raw.strip():
            raise EditedEntryParseError('The edited text must contain only one entry')
        fields = dict(entry['fields'])
        if complete.has_force(fields):
            from .errors import CompletionRefused
            from .prompts import FORCE_REFUSED
            raise CompletionRefused(f"{entry['key']}: {FORCE_REFUSED}")
        before = complete._completion_fields(proposal)
        evidence = {change.field: change for change in proposal.changes}
        changes = []
        for name in sorted((set(before) | set(fields) | set(evidence)) - {'ENTRYTYPE', 'ID'}):
            previous, value = before.get(name), fields.get(name)
            change = evidence.get(name)
            if previous == value and change:
                if name in resolved_fields and change.kind == 'question':
                    changes.append(replace(change, proposed=value, kind='kept',
                                   source=f'typed (source alternative: {change.source}: {change.proposed})'))
                else:
                    changes.append(replace(change))
            else:
                changes.append(complete.FieldChange(name, previous, value, 'user edit',
                                                    'changed' if value is not None else 'dropped'))
        unfilled = [replace(missing) for missing in proposal.unfilled
                    if before.get(missing.field) == fields.get(missing.field) or not fields.get(missing.field)]
        missing_names = {missing.field for missing in unfilled}
        for change in changes:
            if change.kind == 'dropped' and change.field not in missing_names:
                old = evidence.get(change.field)
                unfilled.append(complete.Unfilled(change.field, 'Removed in editor',
                                {old.source: str(old.proposed)} if old and old.proposed else {}))
        item = replace(proposal, proposed_raw=raw, changes=changes, unfilled=unfilled, notes=list(proposal.notes), issues=[], candidates=[],
                       duplicate_of=None, renames={}, unsupported=None, needs_decision=False,
                       status=None, entry_type=fields['ENTRYTYPE'], edited_fields=fields)
        query = complete.Query.from_entry(entry)
        existing = complete._library_entries(ws)
        if entry['key'] in existing and entry['key'] != proposal.key_typed:
            item.issues.append(f"The edited key {entry['key']} already exists in the library")
            item.needs_decision = True
        if proposal.typed_raw is not None:
            query.key, query.raw = proposal.key_typed, proposal.typed_raw
        placeholder = entry['key'] == complete.NO_KEY and not proposal.key_typed
        if not placeholder:
            complete._set_complete(item, fields)
        complete._plan_proposal(ws, item, query, ())
        if placeholder:
            # The text still carries the placeholder of a proposal that had no key. When a key
            # can be planned now (the authors and the year are there), it takes the
            # placeholder's place, and only then is the entry judged complete or not.
            if item.key_proposed:
                raw = complete._key_token(raw, item.key_proposed)
                entry = dict(entry, key=item.key_proposed)
            complete._set_complete(item, fields)
        item.proposed_raw = raw
        if item.key_proposed and entry['key'] != item.key_proposed:
            item.issues.append(f"The edited key {entry['key']} does not match the key plan {item.key_proposed}; edit the key before accepting")
            item.needs_decision = True
        # ``unsupported`` is about the builder: it makes the types of ``complete.KINDS`` only. An
        # entry a person typed (a manual proposal) is theirs to write in any type the manual form offers.
        from .intake import DRAFT_TYPES
        kind = str(fields['ENTRYTYPE']).lower()
        if kind not in complete.KINDS and not (getattr(proposal, 'manual', False) and kind in DRAFT_TYPES):
            item.unsupported = fields['ENTRYTYPE']
            item.needs_decision = True
        path = database or ws.database
        client = extra_sources.make_client(path, contact=mailto or extra_sources.contact_email(path))
        return complete.checked(item, client)
    except CdlbibError:
        raise
    except (OSError, ValueError, TypeError, KeyError, ProviderError, sqlite3.Error) as exc:
        raise CdlbibError(f'Edited entry could not be rechecked: {exc}') from exc
    finally:
        if client is not None:
            try:
                client.cache.close()
            except (OSError, sqlite3.Error) as exc:
                raise CdlbibError(f'Edited entry cache could not be closed: {exc}') from exc


# --- the desk and the shared workflows (issue #95, M2) ------------------------------------------
# What the terminal and web interfaces call. Each is one action; the reading ones are offline
# unless they say otherwise. Front ends never pass ``outfile`` or ``autofix`` to anything.

def entries(ws):
    """[desk.EntrySummary] of the library, in the file's order: key, type, authors, year,
    title, venue, doi, status, issues. See desk.entries."""
    from . import desk
    return desk.entries(ws)


def search(source, text="", status=None):
    """The summaries matching ``text`` (``source``: a workspace, or the list ``entries`` gave).
    Words are ANDed; ``field:word`` restricts to key, author, title, venue, year, doi, type or
    status; case, accents and TeX braces are ignored. See desk.search."""
    from . import desk
    return desk.search(source, text, status=status)


def entry(ws, key):
    """desk.EntryDetail of one entry: raw text, fields, fingerprint, the verifier's result with
    its evidence, the closest source, advisories and per-field format findings."""
    from . import desk
    return desk.entry(ws, key)


def preview_edit(ws, key, raw):
    """desk.EditPreview of saving ``raw`` as entry ``key`` (None: a new entry). Writes nothing
    to the library; problems are data, not exceptions. See desk.preview_edit."""
    from . import desk
    return desk.preview_edit(ws, key, raw)


def save_edit(ws, key, raw, expected_fingerprint=None):
    """Write one hand-edited entry through the shared writer and return complete.Applied.
    ``expected_fingerprint`` is the fingerprint the person was shown (None only for a new
    entry); errors.EditRefused, with nothing written, when the entry changed since, the key is
    in use or the text is not one entry. See desk.save_edit."""
    from . import desk
    return desk.save_edit(ws, key, raw, expected_fingerprint)


def review_queue(ws, reference="github", all_entries=False):
    """[desk.EntryDetail] of the changed (or all) entries that are not verified or approved."""
    from . import desk
    return desk.review_queue(ws, reference=reference, all_entries=all_entries)


def revision(ws):
    """Changes whenever cdl.bib, the verification database or the revocation ledger changes on
    disk; a front end refreshes what it shows when this differs. See desk.revision."""
    from . import desk
    return desk.revision(ws)


def library_state(ws, refresh=False, progress=None):
    """desk.LibraryState: branch, unsent and unrelated changes, new upstream commits and
    entries, the last check, an interrupted write, and with ``refresh`` (which fetches, and
    asks GitHub, within the daily check's time limit) the send branch's pull request."""
    from . import desk
    return desk.library_state(ws, refresh=refresh, progress=progress)


def prepare(ws, progress=None):
    """Read the library and work out what previews need (the parse, the key bases, the index
    of works for duplicate detection), so that the first preview_edit is as quick as the
    later ones. A front end runs this as a job when it opens a library and again when
    ``revision`` changed; what is prepared is kept for exactly that state of cdl.bib, and a
    save carries it over. ``progress`` receives a line per step and, for the long step, a
    line every few hundred entries. Returns desk.Prepared (entries, seconds). Offline.

    Model evidence that an accepted draft's entry was written without (``pending_evidence``)
    is tried once more here, and ``progress`` receives a line for each: stored, not stored
    (why), or left because the entry has changed since."""
    from . import desk
    prepared = desk.prepare(ws, progress=progress)
    try:
        waiting = pending_evidence(ws)
    except CdlbibError as exc:
        waiting = []
        if progress:
            progress(f"model evidence waiting to be stored could not be read: {exc}")
    for item in waiting:
        try:
            again = retry_evidence(ws, item.key)     # also drops evidence whose entry was never written
            said = ("stored" if again.evidence_stored
                    else "dropped: the entry it was read for was not written" if "evidence was dropped" in again.evidence_error
                    else "not stored: the entry has changed since the evidence was read" if item.stale
                    else f"not stored: {again.evidence_error}")
        except CdlbibError as exc:
            said = f"not stored: {exc}"
        if progress:
            progress(f"model evidence for {item.key}: {said}")
    return prepared


@dataclass
class PendingEvidence:
    key: str             # the entry the evidence is for
    fingerprint: str     # the fingerprint the entry had when it was written (the evidence is bound to it)
    stale: bool          # the entry is gone or has another fingerprint now: the evidence can no longer be stored


def pending_evidence(ws):
    """[PendingEvidence] of the model evidence that ``accept_draft`` could not store after it
    wrote the entry: kept in <library>/.bibcheck/pending-evidence/<key>.json until it is
    stored (``retry_evidence``; ``prepare`` tries too). Offline; reads only."""
    from . import intake
    return intake.pending_evidence(ws)


def retry_evidence(ws, key, database=None):
    """Store the model evidence waiting for the entry ``key``, under the write lock, bound to
    the fingerprint it was read for. Returns intake.Accepted (``applied`` None; ``key``,
    ``fingerprint``, ``evidence``; ``evidence_stored`` True and the record removed, or False
    with ``evidence_error``, the record kept). CdlbibError when nothing waits for ``key``.
    Never an approval."""
    from . import intake
    return intake.retry_evidence(ws, key, database=database)


@dataclass
class CompletionDue:
    keys: list = field(default_factory=list)   # the changed, not yet accepted entries completion would look at
    reachable: bool = True                     # False: the reference could not be read, so nothing could be selected
    problem: str | None = None                 # why, when not reachable

    def __bool__(self):
        return bool(self.keys)


def completion_due(ws, reference="github", database=None):
    """Which entries the completion flow (``completion_offers``) would look at now: the
    entries that differ from ``reference`` and hold no accepted result. No source is asked
    about any entry; only the reference is read (the GitHub master cdl.bib by default, a
    download; a path is read locally). Returns CompletionDue, true when there are such
    entries; when the reference cannot be reached it says so (``reachable`` False,
    ``problem``) instead of raising, and an unreadable library gives none (the format check
    reports that).

    Where a front end runs the offers flow, as the command line does:
    - before "check" (`cdlbib verify`): offers first, one entry at a time, each decision
      written before the next; then the format check; then the citation check. Skipped when
      the check is format-only or writes an autofixed copy (--no-citations, --autofix,
      --outfile), or on request (--no-complete).
    - before "send" (`cdlbib send`): after the refusals that need no work (not the canonical
      cdl.bib, no branch, no git author), offers first; then send's own gate. Skipped on
      request (--no-complete).
    An entry already offered in the same sitting is not offered again (``seen``), and "stop"
    ends the offers for that sitting."""
    from .verification import load_entries
    try:
        load_entries(ws.bib)
    except (OSError, ValueError):
        return CompletionDue()
    try:
        return CompletionDue(keys=completion_keys(ws, reference=reference, database=database))
    except CdlbibError as exc:
        return CompletionDue(reachable=False, problem=str(exc))


def consent(exc, allow=None, progress=None):
    """Whether to go on after ``exc``, a MissingDependency (install the package) or a
    PublishRefused with ``needs_fork`` (create the user's fork): the one decision every front
    end uses. ``allow`` True or False is the person's answer. Without one: when the user did
    not ask to be asked (deps.ask() false) it is yes, and ``progress`` receives the line
    saying what is being done; when they did (--ask), errors.NeedsConfirmation is raised
    carrying the question to put to them. Nothing is installed or created here."""
    from . import deps, prompts
    from .errors import MissingDependency, NeedsConfirmation
    install = isinstance(exc, MissingDependency)
    if allow is not None:
        return bool(allow)
    if deps.ask():
        if install:
            raise NeedsConfirmation("install", prompts.install_question(exc), package=exc.package, extra=exc.extra,
                                    feature=exc.feature) from exc
        raise NeedsConfirmation("fork", prompts.fork_question(exc), upstream=exc.upstream) from exc
    if progress:
        progress(prompts.install_line(exc) if install else prompts.fork_line(exc))
    return True


def attempt(run, allow_install=None, allow_fork=None, progress=None):
    """Call ``run(allow_fork_creation=False)`` and return what it returns, dealing with the two
    things a command can stop for, once each: a missing optional package (MissingDependency:
    it is installed with deps.install and ``run`` is called again) and a missing fork
    (PublishRefused with ``needs_fork``: ``run(allow_fork_creation=True)`` is called). Whether
    to go on is ``consent``'s answer: ``allow_install`` / ``allow_fork`` True or False when
    the person has answered; None means go on and say so through ``progress`` unless the user
    asked to be asked, in which case errors.NeedsConfirmation is raised (nothing done; ask
    ``.question`` and call again with the answer). A refusal that is declined, or that
    comes back after the one retry, is raised as it is."""
    from . import deps
    from .errors import MissingDependency, PublishRefused
    installed = fork = False
    while True:
        try:
            return run(allow_fork_creation=fork)
        except MissingDependency as exc:
            if installed or not consent(exc, allow_install, progress):
                raise
            deps.install(exc.extra, package=exc.package)
            installed = True
        except PublishRefused as exc:
            if not exc.needs_fork or fork or not consent(exc, allow_fork, progress):
                raise
            fork = True


def as_data(value):
    """``value`` as plain data that json.dumps takes as it is, with nothing lost: every result
    a front end is given (dataclasses, nested) becomes a dict of its fields; a list that
    carries ``errors`` (ProposalResults) becomes {"items": [...], "errors": [...]}; paths
    become text, times ISO 8601 text, tuples and sets lists, bytes UTF-8 text, an exception
    {"error_kind", "error"}; dict keys become text. Anything else is its ``str``."""
    import dataclasses
    import datetime
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        names = [item.name for item in dataclasses.fields(value)] + list(getattr(type(value), "DATA_PROPERTIES", ()))
        data = {name: as_data(getattr(value, name)) for name in names}
        if isinstance(value, BaseException):
            data.update(error_kind=type(value).__name__, error=str(value))
        return data
    if isinstance(value, dict):
        return {str(key): as_data(item) for key, item in value.items()}
    if isinstance(value, list) and hasattr(value, "errors"):
        return {"items": [as_data(item) for item in value], "errors": as_data(list(value.errors))}
    if isinstance(value, tuple) and hasattr(value, "_asdict"):       # a named tuple keeps its names
        return {name: as_data(item) for name, item in value._asdict().items()}
    if isinstance(value, (list, tuple)):
        return [as_data(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((as_data(item) for item in value), key=repr)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, BaseException):
        return {"error_kind": type(value).__name__, "error": str(value)}
    return str(value)


def recover_interrupted(ws):
    """Settle a killed write to a library cdlbib does not manage; the lines saying what was
    done. See desk.recover."""
    from . import desk
    return desk.recover(ws)


def proposal_failed(proposal):
    """Did the lookup behind ``proposal`` fail: a source that did not answer, or no entry
    proposed and a reason why (what ProposalResults.errors lists)?"""
    return proposal.status == 'provider_error' or bool(not proposal.proposed_raw and proposal.issues)


@dataclass
class CompletionOffer:
    key: str                       # the changed, unaccepted entry
    proposals: list = field(default_factory=list)   # what is worth showing for it ([]: nothing to decide)
    error: str | None = None       # the lookup failed (the message); nothing is proposed for this key
    error_kind: str | None = None  # the name of the error's class (e.g. "CdlbibError", "CompletionRefused")


def worth_showing(proposal):
    """Does a completion proposal give the person something to decide: a duplicate, an
    incomplete entry, candidates to choose from, or a field a source would fill or change?"""
    return bool(proposal.duplicate_of or not proposal.complete or proposal.candidates
                or any(change.typed != change.proposed and change.kind in ('filled', 'changed', 'question')
                       and change.source not in ('typed', 'house format')
                       for change in proposal.changes))


def completion_offers(ws, reference="github", database=None, mailto=None, seen=None):
    """The completion proposals for the changed entries that are not yet accepted, one
    CompletionOffer per entry, produced one at a time: each entry is read and looked up only
    when the caller asks for the next offer, from the library as it then is, so a decision can
    be written (apply_proposals) before the next entry is proposed. Proposals with nothing to
    decide are left out (``worth_showing``). ``seen``: a set of (str(ws.bib), key, fingerprint)
    the caller keeps; entries in it are passed over. A lookup that fails is an offer with
    ``error`` (its message) and ``error_kind`` set, and the others still come. Raises CdlbibError when the entries cannot be
    selected at all; an unreadable library gives no offers (the format check reports it).
    Nothing is written or approved here."""
    from .verification import load_entries
    try:
        load_entries(ws.bib)
    except (OSError, ValueError):
        return iter(())
    keys = completion_keys(ws, reference=reference, database=database)

    def offers():
        for key in keys:
            current = load_entries(ws.bib)
            if key not in current or (seen is not None and (str(ws.bib), key, current[key]['fingerprint']) in seen):
                continue
            try:
                results = propose(ws, keys=[key], database=database, mailto=mailto)
                results[:] = [item for item in results if worth_showing(item)]
            except CdlbibError as exc:
                yield CompletionOffer(key, [], str(exc), type(exc).__name__)
                continue
            yield CompletionOffer(key, results)
    return offers()


def choose_candidate(ws, item, candidate, mailto=None, database=None, in_library=False):
    """The proposal for the candidate a person picked from ``item.candidates``, looked up by
    complete.Query.from_candidate (the one rule: an arXiv lead by its arXiv id; otherwise DOI,
    PMID, arXiv id, title), keeping what was typed. ``in_library``: ``item`` completes
    an entry of the library (a completion offer), whose fields are read from the file now; a
    CdlbibError when that entry is no longer there. Otherwise the typed text, if any, is the
    entry given to `add`. ``proposal_failed`` says whether the lookup failed. Nothing is written."""
    import tempfile
    from .complete import Query
    from .verification import load_entries
    try:
        query = Query.from_candidate(candidate)
    except ValueError as exc:
        raise CdlbibError(str(exc)) from exc
    if in_library:
        query.raw, query.key = item.typed_raw, item.key_typed
        current = load_entries(ws.bib)
        if item.key_typed not in current:
            raise CdlbibError('The selected entry changed on disk; review a new proposal')
        query.fields = dict(current[item.key_typed]['fields'])
    elif item.typed_raw:
        query.raw, query.key = item.typed_raw, item.key_typed
        with tempfile.TemporaryDirectory(prefix='cdlbib-candidate-') as folder:
            path = Path(folder) / 'typed.bib'
            path.write_text(item.typed_raw, encoding='utf-8')
            typed = next(iter(load_entries(path).values()))
        query.fields = dict(typed['fields'])
    return propose_new(ws, [query], mailto=mailto, database=database)[0]


def check_keys(ws, keys, progress=None, database=None, mailto=None, bars=None):
    """Check chosen entries now, and only them: each one's house format by the one-entry
    format check that ``entry`` and ``preview_edit`` use (no pass over the whole library),
    then the citation gate (check_citations, the one gate) for exactly ``keys``, whatever
    has changed. Returns a LibraryCheck with ``scope`` "keys": ``format`` covers the chosen
    entries only (``errors``: those with a finding; ``corrections``: the formatter's value
    per field, None for a field it would remove; ``failure``: an entry it could not judge),
    ``citations`` is the gate's result (``checked``: the refreshed result of each key).
    ``ok`` is True when none of ``keys`` has a format finding and every one is verified or
    approved. ``progress`` receives a line per entry for the format, then the gate's lines.
    ``mailto`` defaults to CROSSREF_MAILTO. GateFailed when a key is not in the library or
    the check cannot be done. The whole-library check is check_library, which is what a send
    runs; this one never stands in for it."""
    from . import library
    keys = list(keys)
    with library.transaction(ws):     # a write killed part-way is settled first, or this refuses (CdlbibError)
        for line in library.settled(ws):
            if progress:
                progress(line)
    from . import verification
    with verification.read_once() as parses:     # the library is parsed once for the format part and the gate
        return _check_keys(ws, keys, progress, database, mailto, bars, parses)


def _check_keys(ws, keys, progress, database, mailto, bars, parses):
    import os
    from . import desk
    try:
        judged = desk.format_findings(ws, keys, progress=progress)
        desk.lend_parse(ws, parses)
    except CdlbibError as exc:
        raise GateFailed(str(exc)) from exc
    unjudged = [f"{key}: {item.message}" for key, found in judged.items() for item in found if item.field is None]
    fmt = FormatResult(errors=[key for key, found in judged.items() if found], corrected=None,
                       failure="; ".join(unjudged),
                       corrections={key: {("ID" if item.field == "key" else item.field): item.corrected
                                          for item in found if item.field is not None}
                                    for key, found in judged.items() if any(item.field for item in found)})
    check = check_citations(ws, fmt, database=database, mailto=mailto or os.environ.get("CROSSREF_MAILTO"),
                            progress=progress, bars=bars, keys=keys)
    check.scope = "keys"
    check.ok = bool(check.ok and fmt.ok)
    return check


def send_checked(ws, summary=None, progress=None, report=None, allow_fork_creation=False):
    """``send`` as an interactive front end may call it: the whole gate always runs (format,
    then the citations of every new or edited entry against the GitHub master), and nothing
    about where the change goes or what it is compared with can be passed. The contact for
    Crossref is CROSSREF_MAILTO. See send for what is committed, pushed and returned."""
    import os
    return send(ws, summary=summary, reference="github", citations=True, mailto=os.environ.get("CROSSREF_MAILTO"),
                progress=progress, report=report, allow_fork_creation=allow_fork_creation)


# --- TeX integration and manuscript export ---

GH_TIMEOUT = 10   # seconds features() gives `gh api user`, its one question to the network


@dataclass
class Feature:
    """One thing cdlbib uses when it is there. ``available`` is True or False when that is
    known, and None when it was not checked (finding out needs a probe: the network, or the
    system keychain, which may ask the user). ``detail`` says what was found, never a key's
    value; ``how`` is what makes it available, and is empty when it is."""
    name: str
    available: bool | None
    detail: str = ""
    how: str = ""
    version: str = ""       # of a program whose version matters (biber: with the biblatex TeX finds)


@dataclass
class SetupReport:
    where: Where
    tex: object          # tex.TexStatus
    features: list


PROBES = ("github", "dartmouth-chat", "openai")     # what features() only finds out when asked to


def features(probe=(), progress=None):
    """What this computer has of the things cdlbib can use: git, the gh login, TeX, bibtex,
    biber, pypdf, the Dartmouth Chat and OpenAI keys, textual.

    By default only what can be seen without asking anyone: programs on PATH, installed
    packages, environment variables, and the version bibtex and biber report (``version``; for
    biber with the biblatex TeX finds). It never prompts or uses the network; the gh login
    and a key that is not in the environment are then ``available=None`` ("not checked").
    ``probe`` names the checks to make as well, from PROBES, or "all": "github" asks gh who is
    logged in (the network, GH_TIMEOUT seconds); "dartmouth-chat" and "openai" read the system
    keychain (macOS may show an access dialog and wait for it). ``progress`` receives one line
    before each probe. Nothing is installed."""
    import importlib.util
    import os
    import shutil
    from . import deps, identity, secrets, texinstall
    from .errors import IdentityUnavailable, SecretNotFound
    wanted = PROBES if probe == "all" else tuple([probe] if isinstance(probe, str) else probe)
    unknown = [name for name in wanted if name not in PROBES]
    if unknown:
        raise CdlbibError(f"Unknown check: {', '.join(unknown)}. The checks are: {', '.join(PROBES)}, or \"all\".")
    say = progress or (lambda line: None)
    tex_how = "Install TeX Live (https://tug.org/texlive/) or, on macOS, MacTeX (https://tug.org/mactex/)."
    found = []

    def program(name, command, how):
        path = shutil.which(command)
        found.append(Feature(name, bool(path), path or f"{command} was not found on PATH", "" if path else how))

    def package(name, module, extra):
        there = importlib.util.find_spec(module) is not None
        found.append(Feature(name, there, "installed" if there else "not installed",
                             "" if there else deps.manual_command(extra, module)))

    def key(name, label):
        variable = secrets.KEYS[name].env
        value = os.environ.get(variable) or ""
        if value:       # known without the keychain; the value itself is never shown
            usable = not any(char.isspace() for char in value)
            return Feature(label, usable, f"set in the environment variable {variable}" if usable
                           else f"the environment variable {variable} holds whitespace; a key is a single token",
                           "" if usable else secrets.places(name))
        if name not in wanted:
            return Feature(label, None, f"not checked: {variable} is not set, and the system keychain was not read",
                           secrets.places(name))
        say(f"reading the system keychain for the {label} ...")
        try:
            secrets.get(name)
            return Feature(label, True, "stored in the system keychain")
        except SecretNotFound as exc:
            return Feature(label, False, str(exc).replace(secrets.places(name), "").strip(), secrets.places(name))

    program("git", "git", "Install git (https://git-scm.com/downloads).")
    if not shutil.which("gh"):
        found.append(Feature("gh login", False, "gh was not found on PATH", identity.HOW))
    elif "github" not in wanted:
        found.append(Feature("gh login", None, "not checked: gh is installed; whether a user is logged in was not asked",
                             identity.HOW))
    else:
        say("asking gh who is logged in (gh api user) ...")
        try:
            found.append(Feature("gh login", True, _me(timeout=GH_TIMEOUT).handle))
        except IdentityUnavailable as exc:
            found.append(Feature("gh login", False, str(exc).replace(identity.HOW, "").strip(), identity.HOW))
    program("TeX", "kpsewhich", tex_how)
    for name in ("bibtex", "biber"):
        path = shutil.which(name)
        found.append(Feature(name, bool(path), path or f"{name} was not found on PATH", "" if path else texinstall.how(name),
                             version=(texinstall.versions_line() if name == "biber" else texinstall.version(name)) if path else ""))
    package("pypdf", "pypdf", "research")
    found.append(key("dartmouth-chat", "Dartmouth Chat key"))
    found.append(key("openai", "OpenAI key"))      # the key only; whether the route is usable: model_routes (.detail)
    package("textual", "textual", "tui")
    return found


def setup_report(ws, probe=(), progress=None):
    """Which library is in use, the state of its TeX link, and features(probe, progress)."""
    from . import tex, workspace
    found = where()
    if found.root != ws.root:       # a library handed in, not the one the lookup rule gives now
        found = Where(root=ws.root, origin=workspace.Origin.NAMED, last_check=None)
    return SetupReport(where=found, tex=tex.status(ws), features=features(probe=probe, progress=progress))


def tex_link(ws, replace=False):
    """Link the library's cdl.bib into the user's TeX tree (tex.link); the status afterwards."""
    from . import tex
    return tex.link(ws, replace=replace)


def tex_unlink():
    """Remove the link cdlbib made in the TeX tree, and nothing else (tex.unlink)."""
    from . import tex
    return tex.unlink()


def export_bib(ws, paper, out=None, main=None, inputs=(), engine=None, force=False):
    """Write the frozen .bib of what ``paper`` cites (export.cited, export.frozen_bib).
    Default ``out``: beside the paper, named as the library (cdl.bib)."""
    from . import export
    found = export.cited(paper, main=main, inputs=inputs, engine=engine)
    if out is None:
        out = (found.folder or Path(paper).expanduser().resolve().parent) / ws.bib.name
    return export.frozen_bib(ws, found, out, force=force)


def export_bbl(ws, paper, out=None, inputs=(), main=None, engine=None, force=False):
    """Compile the paper's .bbl from the library with the paper's own style (export.bbl)."""
    from . import export
    return export.bbl(ws, paper, out=out, inputs=inputs, main=main, engine=engine, force=force)


# --- front-end helpers added for the interactive interfaces ---

def acceptable(proposal):
    """May ``proposal`` be accepted as it stands: it is complete, has an entry to write, is
    no duplicate, is of a type that can be written, and has no issue about its key or its
    format? The one test every front end applies before it writes an accepted proposal
    (``needs_decision`` is separate: such a proposal is never accepted with the remaining
    ones, only by the person looking at it)."""
    return not why_not_acceptable(proposal)


def why_not_acceptable(proposal):
    """Why ``proposal`` cannot be accepted as it stands, as sentences ([] when it can: the
    predicate ``acceptable`` is ``not why_not_acceptable``). One reason each for: no entry
    proposed; no key; every required field of the entry's type that is missing or still a
    question, by name; the work being in the library already (the key it has there); a type
    that is not written; and each issue about the key or the format."""
    from . import complete
    reasons = []
    if not proposal.proposed_raw:
        reasons.append("no entry is proposed")
    if not proposal.complete:
        fields = {}
        if proposal.proposed_raw:      # the fields of the text that would be written, whoever made the proposal
            from . import intake
            try:
                fields = {str(name).lower(): value for name, value in intake.scan_entry(proposal.proposed_raw)[2].items()}
            except (CdlbibError, ValueError):
                fields = complete._completion_fields(proposal)
        asked = {change.field for change in proposal.changes if change.kind == "question"}
        kind = str(proposal.entry_type or "article").lower()
        required = complete.KINDS.get(kind, complete.KINDS["article"]).required
        if not (proposal.key_typed or proposal.key_proposed):
            reasons.append("it has no key yet (a key is made from the authors and the year)")
        for name in required:
            if not fields.get(name):
                reasons.append(f"{name} is missing (required for an entry of type {kind})")
            elif name in asked:
                reasons.append(f"{name} is still a question: choose between what was typed and what the source has")
        if len(reasons) == (not proposal.proposed_raw):
            reasons.append("a required field is missing")
    if proposal.duplicate_of:
        reasons.append(f"it is the same work as {proposal.duplicate_of}, which is already in the library")
    if proposal.unsupported:
        reasons.append(f"an entry of type {proposal.unsupported} is not written from a source record")
    reasons += [issue for issue in proposal.issues
                if "already exists in the library" in issue or "does not match the key plan" in issue
                or issue.startswith("format:") or "format check could not run" in issue]
    return reasons


def draft_form():
    """What a manual-entry form offers: {"types": the entry types a hand-typed draft may
    have (intake.DRAFT_TYPES), "fields": the field names a reading can fill
    (intake.MODEL_FIELDS)}. Other field names may be typed too."""
    from . import intake
    return {"types": list(intake.DRAFT_TYPES), "fields": list(intake.MODEL_FIELDS)}


def completion_batch(ws):
    """The context manager that makes every acceptance of one sitting share one backup of the
    managed library (library.completion_batch): pass what it yields as ``batch`` to
    ``apply_proposals``. Entered and left on the same thread."""
    from . import library
    return library.completion_batch(ws)


def name_choices(proposal):
    """[(field, typed names, source names)] for each author or editor list of ``proposal``
    that is a question and has as many names typed as the source gives: the lists a person
    settles name by name (``resolve_names``)."""
    found = []
    for change in proposal.changes:
        if change.kind == 'question' and change.field in ('author', 'editor') and change.typed and change.proposed:
            typed, source = change.typed.split(' and '), change.proposed.split(' and ')
            if len(typed) == len(source):
                found.append((change.field, typed, source))
    return found


def resolve_names(ws, proposal, field, names, mailto=None, database=None, recheck=None):
    """``proposal`` with its ``field`` (author or editor) set to ``names``, the list the person
    chose name by name, rechecked (``recheck_proposal``); the field is then no longer a
    question. Nothing is written. ``recheck``: a front end's own
    ``recheck(proposal, raw, resolved_fields=...)`` to call in place of recheck_proposal
    (``ws``, ``mailto`` and ``database`` are then not used)."""
    from . import complete
    fields = complete._completion_fields(proposal)
    fields[field] = ' and '.join(names)
    raw = complete.render(proposal.entry_type, proposal.key_typed or proposal.key_proposed, fields)
    if recheck is not None:
        return recheck(proposal, raw, resolved_fields=(field,))
    return recheck_proposal(ws, proposal, raw, mailto=mailto, database=database, resolved_fields=(field,))


def draft_types():
    """The entry types a hand-typed draft may have (intake.DRAFT_TYPES), "article" first."""
    from . import intake
    return tuple(intake.DRAFT_TYPES)


def draft_fields():
    """The field names a manual form offers, in the order to show them: the house format's
    fields (keep_fields.txt) without the entry type, the key and ``force``."""
    from .helpers import read
    first = ("author", "title", "year", "journal", "booktitle", "volume", "number", "pages", "publisher", "address",
             "editor", "doi")
    kept = [name for name in read("keep_fields.txt") if name not in ("ENTRYTYPE", "ID", "force")]
    return tuple([name for name in first if name in kept] + sorted(name for name in kept if name not in first))
