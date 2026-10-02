"""The front-end boundary. Nothing here prints, prompts or exits."""
import contextlib
import io
import sys
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


def update(ws=None, decision=None, force=False, progress=None):
    """Bring the managed library up to date and return a library.UpdateResult. Without
    ``force`` this is the daily check: nothing is fetched when the last check is under 24
    hours old, nor within an hour of an automatic attempt that failed, and the upstream is
    given 15 seconds. A front end calls it, before a command's own work, only when the
    library in use is the managed one (``is_managed``); ``ws`` None means the managed library
    whatever library is in use (CdlbibError when it has not been downloaded). ``progress``
    receives one line when another command holds the lock and this one has to wait.
    The library is changed only by a fast-forward, after a backup (``result.backup``);
    ``result.message`` is the line to show and ``result.notes`` are non-fatal remarks. Any
    other library than the managed one is a CdlbibError, and nothing is done to it."""
    from . import library
    return library.update(_managed("so there is nothing to update") if ws is None else ws,
                          force=force, decision=decision, progress=progress)


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


def undo(stamp=None):
    """undo_update(), returning an UndoResult: also the backup taken just before, and the
    branches the undo took off commits that no local branch and no branch of the upstream
    leads to (``before`` keeps those commits and is never deleted while it alone does)."""
    from . import library
    restored, before = library.undo(_managed(), stamp)
    return UndoResult(restored=restored, before=before, taken_off=library.taken_off(before))


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
    """Put the managed library back as it was at the newest backup, or at the one named
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
    lines = []
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
                                                        all_entries=all_entries, mailto=mailto, echo=echo)
            finally:
                printed.close_line()
    except (ValueError, OSError, ProviderError) as exc:
        raise GateFailed(f"citation check failed: {type(exc).__name__}: {exc}") from exc
    result = CitationResult(ok=ok, unresolved=unresolved, library=library, lines=lines)
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


def compare(a, b, verbose=False, outfile=None, bars=None):
    from .helpers import compare_bibs
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
    the checkout as it was. A failure after that (commit, push, pull request) says where
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

    not_upstream(fork, upstream)
    here = publish.require_branch(ws, base)
    if not publish.pending(ws) and not here.startswith("cdlbib/"):
        raise PublishRefused(publish.NO_CHANGES)       # before anything outward: no login, no fork, for nothing
    publish.require_identity(ws)
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
    if progress:
        progress("checks passed; generating commit message...")
    comparison = compare(reference, str(ws.bib), verbose=verbose, outfile=outfile, bars=bars)
    if progress:
        for line in comparison.log.splitlines():
            progress(line)
    changes = comparison.summary.strip() or "update bibliography"
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
    branch = here if resumed else publish.branch_name(me.login, summary or changes.splitlines()[0][:100],
                                                      datetime.date.today())
    if fork:                             # this branch's pull request may be finished already
        earlier = publish.earlier_pr(upstream, f"{fork.split('/')[0]}:{branch}")
        if earlier and resumed:
            raise PublishRefused(
                f"You are on branch {branch}, whose pull request {earlier[0]} is {earlier[1]}; a new change needs a "
                f"new branch. Nothing was changed. Go back to {base}, bring it up to date and send again:\n"
                f"  git switch {base}\n  git pull https://github.com/{upstream}.git {base}\n  cdlbib send\n"
                "Your uncommitted edits to cdl.bib and verification/ are carried along by `git switch`; "
                "nothing is lost.")
        if earlier:
            raise PublishRefused(
                f"Branch {branch} was already used for pull request {earlier[0]}, which is {earlier[1]}; a new "
                "change needs a new branch. Nothing was changed. Send again with a different --summary (the branch "
                "is named after it and today's date).")
    body = changes + approvals_note(ws, reference=reference, database=database)
    title = (summary or changes.splitlines()[0])[:100]
    if not fork:
        if not allow_fork_creation:
            raise PublishRefused(f"{me.handle} has no fork of {upstream}.", needs_fork=True, upstream=upstream)
        fork, created = publish.create_fork(upstream), True
    files = publish.deliver(ws, branch, changes, f"https://github.com/{fork}.git", target=fork)
    try:
        url = publish.open_or_update_pr(upstream, base, f"{fork.split('/')[0]}:{branch}", title, body,
                                        retitle=bool(summary))   # an open pull request keeps its title unless one is given
    except PublishRefused as exc:
        raise PublishRefused(
            f"The change is committed on branch {branch} and pushed to {fork}, but the pull request could not be "
            f"opened or updated. Run `cdlbib send` again to resume from there.{publish.go_back(here, branch)}\n{exc}") from exc
    return SendResult(url=url, branch=branch, fork=fork, created_fork=created, files=files,
                      left=publish.unrelated_changes(ws))


def _message(exc):
    # str(KeyError('Nope')) is "'Nope'"; the CLI printed exactly that, so the text is kept as is.
    return str(exc)
