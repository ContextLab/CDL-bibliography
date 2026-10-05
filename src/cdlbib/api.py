"""The front-end boundary. Nothing here prints, prompts or exits."""
import contextlib
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
    return FormatResult(errors=list(errors), corrected=corrected,
                        outfile=Path(outfile) if outfile else None, log=sink.getvalue())


def gate_after_format(fmt, citations=True, autofix=False, outfile=None):
    """The gate's state once the format check is done. ``citations_due`` says whether the
    citation check still has to run; when it does not, ``ok`` is final."""
    if not fmt.ok:
        fixed = bool(autofix and outfile and not fmt.failure)
        return LibraryCheck(format=fmt, citations=None, ok=fixed, needs_review_of_autofix=fixed)
    return LibraryCheck(format=fmt, citations=None, ok=True, citations_due=bool(citations))


def check_citations(ws, fmt, reference="github", all_entries=False, database=None, mailto=None,
                    progress=None, bars=None):
    """Citation verification of the new/edited entries (or all); ``progress`` receives each
    report line as it is produced."""
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
                                                        selected_results=selected_results)
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
    reviewer's name). Raises IdentityUnavailable before anything is opened or written."""
    from . import identity
    from .verification import Cache, record_approval
    from .verification import revocation_ledger
    me = identity.current()
    review = {"reviewer": me.handle, "source": source, "note": note,
              "github_login": me.login, "github_id": me.id}
    try:
        cache = Cache(database or str(ws.database), ledger=revocation_ledger(str(ws.bib), None))
        try:
            return record_approval(cache, str(ws.bib), key, fingerprint, review)
        finally:
            cache.close()
    except (ValueError, KeyError, OSError) as exc:
        raise ApprovalRefused(_message(exc)) from exc


def revoke(ws, key, reason, fingerprints=None, ledger=None, database=None):
    """Withdraw a human approval, recorded under the GitHub login of the gh CLI."""
    from . import identity
    from .verification import Cache, record_revocation
    from .verification import revocation_ledger
    me = identity.current()
    ledger_path = revocation_ledger(str(ws.bib), ledger)  # resolved once for the cache and the writer
    try:
        cache = Cache(database or str(ws.database), ledger=ledger_path)
        try:
            records, state = record_revocation(cache, str(ws.bib), key, reason, me.handle,
                                               fingerprints=fingerprints, ledger=ledger_path)
        finally:
            cache.close()
    except (ValueError, KeyError, OSError) as exc:
        raise ApprovalRefused(_message(exc)) from exc
    return RevokeResult(records=records, status=state)


def approvals_note(ws, reference=None, database=None):
    """The pull request's record of human approvals: '\n\nApproved by @login: KEY, KEY' per
    reviewer, for entries whose stored status is human_verified under a GitHub login (only
    the entries that differ from ``reference``, when one is given); '' when there are none."""
    from .verification import Cache, ProviderError, current_results, revocation_ledger
    from .verification_cli import reference_bib, select_keys
    database = Path(database or ws.database)
    if not database.is_file():
        return ""
    try:
        cache = Cache(str(database), ledger=revocation_ledger(str(ws.bib), None))
        try:
            results = current_results(str(ws.bib), cache)
        finally:
            cache.close()
        against = reference_bib(reference, database.parent) if reference else None
        selected = select_keys(str(ws.bib), None, against, entries=results)
    except (ValueError, OSError, ProviderError) as exc:
        raise CdlbibError(f"could not read the approvals: {type(exc).__name__}: {exc}") from exc
    by_login = {}
    for key in sorted(selected):
        review = results[key].get("human_review") or {}
        if results[key]["status"] == "human_verified" and review.get("github_login"):
            by_login.setdefault(str(review["github_login"]), []).append(key)
    return "".join(f"\n\nApproved by @{login}: {', '.join(keys)}" for login, keys in sorted(by_login.items()))


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
    import datetime
    from . import identity, publish
    from .errors import PublishRefused

    def not_upstream(candidate, target):
        if candidate and target and candidate.lower() == target.lower() and not _test_inside_own_fork:
            raise PublishRefused(f"{candidate} is the upstream repository, not a fork of it; a change is never "
                                 "pushed to the upstream.")

    publish.require_canonical(ws)
    validate_summary_path(outfile, ws=ws, inputs=(reference,), database=database)
    not_upstream(fork, upstream)
    here = publish.require_branch(ws, base)
    if not publish.pending(ws) and not here.startswith("cdlbib/"):
        raise PublishRefused(publish.NO_CHANGES)       # before anything outward: no login, no fork, for nothing
    publish.require_identity(ws)

    def evidence():
        return _send_evidence(ws, reference=reference, database=database)

    def gate():
        """The gate, then the comparison with ``reference``: what the change is, in words."""
        before = publish.candidate(ws)
        fmt = check_format(ws, bars=bars)
        check = gate_after_format(fmt, citations=citations)
        if report:
            report(check)
        if check.citations_due:
            check = check_citations(ws, fmt, reference=reference, database=database, mailto=mailto,
                                    progress=progress, bars=bars)
        if not check.ok:
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
    me = identity.current()
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
                      left=publish.unrelated_changes(ws))


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

def find_candidates(ws, title=None, authors=(), year=None, mailto=None, database=None, progress=None):
    """Leads for a title, one or several authors, or both; see intake.find_candidates.
    A lead becomes an entry only through propose_new([candidate_query(lead)])."""
    from . import intake
    return intake.find_candidates(ws, title=title, authors=authors, year=year, mailto=mailto,
                                  database=database, progress=progress)


def candidate_query(candidate):
    """The query that names a lead by its identifier, for propose_new."""
    from . import intake
    return intake.query_for(candidate)


def read_pdf(path, ocr=True):
    """The first pages of a PDF, its identifiers and a title guess; see intake.read_pdf."""
    from . import intake
    return intake.read_pdf(path, ocr=ocr)


def render_first_page(path, width=800):
    """Page 1 of a PDF as PNG bytes; see intake.render_first_page."""
    from . import intake
    return intake.render_first_page(path, width)


def propose_from_pdf(ws, pdf, mailto=None, database=None, progress=None):
    """The source record of a read PDF, built and checked; see intake.propose_from_pdf."""
    from . import intake
    return intake.propose_from_pdf(ws, pdf, mailto=mailto, database=database, progress=progress)


def model_routes():
    """The model routes and whether each is set up; see intake.model_routes."""
    from . import intake
    return intake.model_routes()


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


def attach_model_evidence(ws, key, evidence, fingerprint=None, database=None):
    """Store a model reading's evidence with a written entry; never an approval.
    See intake.attach_model_evidence."""
    from . import intake
    return intake.attach_model_evidence(ws, key, evidence, fingerprint=fingerprint, database=database)


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
                if proposal.status == 'provider_error' or (not proposal.proposed_raw and proposal.issues):
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
        complete._set_complete(item, fields)
        complete._plan_proposal(ws, item, query, ())
        item.proposed_raw = raw
        if item.key_proposed and entry['key'] != item.key_proposed:
            item.issues.append(f"The edited key {entry['key']} does not match the key plan {item.key_proposed}; edit the key before accepting")
            item.needs_decision = True
        if str(fields['ENTRYTYPE']).lower() != 'article':
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


# --- TeX integration and manuscript export ---

GH_TIMEOUT = 10   # seconds features() gives `gh api user`, its one question to the network


@dataclass
class Feature:
    """One thing cdlbib uses when it is there. ``detail`` says what was found, never a key's
    value; ``how`` is what makes it available, and is empty when it is."""
    name: str
    available: bool
    detail: str = ""
    how: str = ""


@dataclass
class SetupReport:
    where: Where
    tex: object          # tex.TexStatus
    features: list


def features():
    """What this computer has of the things cdlbib can use: git, the gh login, TeX, bibtex,
    biber, pypdf, the Dartmouth Chat and OpenAI keys, textual. Installs nothing and asks
    nothing; the gh login is the only thing looked up over the network."""
    import importlib.util
    import os
    import shutil
    from . import deps, identity, secrets
    from .errors import IdentityUnavailable, SecretNotFound
    tex_how = "Install TeX Live (https://tug.org/texlive/) or, on macOS, MacTeX (https://tug.org/mactex/)."
    found = []

    def program(name, command, how):
        path = shutil.which(command)
        found.append(Feature(name, bool(path), path or f"{command} was not found on PATH", "" if path else how))

    def package(name, module, extra):
        there = importlib.util.find_spec(module) is not None
        found.append(Feature(name, there, "installed" if there else "not installed",
                             "" if there else deps.manual_command(extra, module)))

    program("git", "git", "Install git (https://git-scm.com/downloads).")
    try:
        found.append(Feature("gh login", True, identity.current(timeout=GH_TIMEOUT).handle))
    except IdentityUnavailable as exc:
        found.append(Feature("gh login", False, str(exc).replace(identity.HOW, "").strip(), identity.HOW))
    program("TeX", "kpsewhich", tex_how)
    program("bibtex", "bibtex", tex_how)
    program("biber", "biber", "biber comes with a full TeX Live or MacTeX; in a smaller one: tlmgr install biber")
    package("pypdf", "pypdf", "research")
    for name, label in (("dartmouth-chat", "Dartmouth Chat key"), ("openai", "OpenAI key")):
        try:
            secrets.get(name)
            found.append(Feature(label, True, f"set in the environment variable {secrets.KEYS[name].env}"
                                 if os.environ.get(secrets.KEYS[name].env) else "stored in the system keychain"))
        except SecretNotFound as exc:
            found.append(Feature(label, False, str(exc).replace(secrets.places(name), "").strip(), secrets.places(name)))
    package("textual", "textual", "tui")
    return found


def setup_report(ws):
    """Which library is in use, the state of its TeX link, and features()."""
    from . import tex, workspace
    found = where()
    if found.root != ws.root:       # a library handed in, not the one the lookup rule gives now
        found = Where(root=ws.root, origin=workspace.Origin.NAMED, last_check=None)
    return SetupReport(where=found, tex=tex.status(ws), features=features())


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
