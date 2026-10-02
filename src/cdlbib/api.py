"""The front-end boundary. Nothing here prints, prompts or exits."""
import contextlib
import io
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CdlbibError, GateFailed


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
    from .verification_cli import revocation_ledger, select_keys
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
