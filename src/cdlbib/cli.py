"""The cdlbib command. Parsing and formatting only; the work is in cdlbib.api."""
import re
import sys
from pathlib import Path

import typer

from . import __version__, api, deps
from .errors import CdlbibError, GateFailed, LibraryUnavailable, MissingDependency, PublishRefused, WorkspaceNotFound
from . import workspace
from .verification_cli import app as crossref_app, library, named
from .workspace import BIB_NAME

app = typer.Typer()
app.add_typer(crossref_app, name="crossref")


def _version(value: bool):
    if value:
        typer.echo(f"cdlbib {__version__}")
        raise typer.Exit()


@app.callback()
def root(library_path: str = typer.Option(None, "--library", help="Folder containing cdl.bib."),
         version: bool = typer.Option(False, "--version", callback=_version, is_eager=True,
                                      help="Show the version and exit."),
         ask: bool = typer.Option(False, "--ask", help="Ask before installing a missing package or creating your fork.")):
    workspace.select_library(library_path)
    deps.set_ask(ask)


def report_format(result, ws, fname):
    """Print the format check's log; a check that could not finish (check_bib raised) is
    shown and exits nonzero.

    A bare ``except`` used to print only 'errors found' and return success,
    which hid e.g. 'page numbers are ambiguous or incorrect: KothEtal25'.
    """
    # The log names the file as the user would from here, when that is the file checked.
    named = fname if Path(fname).resolve() == ws.bib else str(ws.bib)
    typer.echo(result.log.replace(f"loading {ws.bib}...", f"loading {named}...", 1), nl=False)
    if result.failure:
        typer.echo(f"errors found: {result.failure}", err=True)
        raise typer.Exit(code=1)


def report_check(check, verbose, autofix, outfile):
    if outfile:
        typer.echo(f"saved updated bibliography to {outfile}")
    if check.format.ok:
        typer.echo("format: looks good!")
        return
    if autofix:
        typer.echo(f"errors found; autocorrected and saved to {outfile}" if outfile
                   else "errors found; specify outfile to save autocorrections")
    typer.echo("errors found; see log for details" if verbose
               else "errors found; run with verbose flag for details")
    if check.needs_review_of_autofix:
        typer.echo("citations not checked: review the autocorrected file, then run verify on it")


def run_gate(ctx, fname, reference="github", citations=True, all_entries=False, autofix=False,
             outfile=None, verbose=False, database=None, mailto=None):
    """The gate of api.check_library, reported as it runs: the format log and verdict
    first, then each line of the citation check as it is produced."""
    ws = library(ctx, fname)
    fmt = api.check_format(ws, autofix=autofix, outfile=outfile, verbose=verbose, bars=sys.stderr)
    report_format(fmt, ws, fname)
    check = api.gate_after_format(fmt, citations=citations, autofix=autofix, outfile=outfile)
    report_check(check, verbose, autofix, outfile)
    if check.citations_due:
        check = api.check_citations(ws, fmt, reference=reference, all_entries=all_entries,
                                    database=database, mailto=mailto, progress=typer.echo,
                                    bars=sys.stderr)
    return check


@app.command()
def verify(ctx: typer.Context, fname: str = BIB_NAME, autofix: bool = False, outfile: str = None, verbose: bool = False,
           reference: str = "github",
           no_citations: bool = typer.Option(False, "--no-citations",
                                             help="Offline, format-only check (no citation verification)."),
           all: bool = typer.Option(False, "--all", help="Verify the citations of every entry, not only changed ones."),
           database: str = typer.Option(None, "--database", help="Verification cache (default .bibcheck/verification.sqlite3)."),
           mailto: str = typer.Option(None, "--mailto", envvar="CROSSREF_MAILTO", help="Contact email for Crossref.")):
    """Format check, then citation verification of new/edited entries."""
    check = run_gate(ctx, fname, reference=reference, citations=not no_citations, all_entries=all, autofix=autofix,
                     outfile=outfile, verbose=verbose, database=database, mailto=mailto)
    if not check.ok:
        raise typer.Exit(code=1)
    typer.echo("looks good!")


@app.command()
def compare(fname1: str, fname2: str, verbose: bool = False, outfile: str = None):
    """Show the differences between two .bib files."""
    result = api.compare(fname1, fname2, verbose=verbose, outfile=outfile, bars=sys.stderr)
    typer.echo(result.log, nl=False)
    if result.match:
        typer.echo("files match!")
    else:
        typer.echo("files do not match; see log for details" if verbose
                   else "files do not match; run with verbose flag for details")


@app.command()
def send(ctx: typer.Context, fname: str = BIB_NAME, reference: str = "github", verbose: bool = False,
           outfile: str = None,
           summary: str = typer.Option(None, "--summary", help="One line describing the change."),
           database: str = typer.Option(None, "--database", help="Verification cache (default .bibcheck/verification.sqlite3)."),
           mailto: str = typer.Option(None, "--mailto", envvar="CROSSREF_MAILTO", help="Contact email for Crossref.")):
    """Run the verify gate, then send the change as a pull request from your fork."""
    ws = library(ctx, fname)

    def shown(check):
        report_format(check.format, ws, fname)
        report_check(check, verbose, False, None)

    def attempt(report=None, progress=None, allow_fork_creation=False):
        return api.send(ws, summary=summary, reference=reference, mailto=mailto, database=database,
                        progress=progress, bars=sys.stderr, report=report, allow_fork_creation=allow_fork_creation,
                        outfile=outfile, verbose=verbose)

    try:
        try:
            result = attempt(report=shown, progress=typer.echo)
        except PublishRefused as exc:
            if not exc.needs_fork:
                raise
            if not fork_wanted(exc):
                typer.echo(f"{exc} Create one with: gh repo fork {exc.upstream} --clone=false", err=True)
                raise typer.Exit(code=1)
            result = attempt(allow_fork_creation=True)  # the gate runs again, from its cache, unreported
    except GateFailed as exc:
        if exc.check is None:  # the check could not be done; main() reports it
            raise
        typer.echo(str(exc))  # "not sent: fix the format errors and resolve every new/edited entry first ..."
        raise typer.Exit(code=1)
    if result.created_fork:
        typer.echo(f"created fork {result.fork}")
    if result.files:
        typer.echo("committed: " + ", ".join(result.files))
    typer.echo(f"pull request: {result.url}")
    typer.echo(f"you are now on branch {result.branch}")
    if result.left:
        typer.echo("left uncommitted: " + ", ".join(result.left))


CHOSEN_BY = {
    workspace.Origin.NAMED: "the file you named",
    workspace.Origin.OPTION: "--library",
    workspace.Origin.ENVIRONMENT: "CDLBIB_LIBRARY",
    workspace.Origin.FOUND: f"{BIB_NAME} found in or above the current folder",
    workspace.Origin.MANAGED: "no library named or found; this is the copy cdlbib downloads and manages",
}


@app.command()
def where(ctx: typer.Context, fname: str = BIB_NAME):
    """Show which library is in use and how it was chosen."""
    library(ctx, fname)  # as every command: the managed library is downloaded when it is the one in use
    found = api.where(fname if named(ctx) else None)
    typer.echo(str(found.root))
    typer.echo(f"chosen by: {CHOSEN_BY[found.origin]}")
    if found.origin == workspace.Origin.MANAGED:
        typer.echo("last update check: " + (found.last_check.strftime("%Y-%m-%d %H:%M UTC") if found.last_check else "never"))


def _backup_line(backup):
    changed = len(backup.changed)
    return (f"{backup.when}: " + (f"branch {backup.branch}" if backup.branch else "no branch")
            + f" at {backup.commit[:8]}, {changed} changed file{'' if changed == 1 else 's'}"
            + (", local commits saved" if backup.has_bundle else ""))


@app.command()
def update(show: bool = typer.Option(False, "--list", help="Show the backups of the library cdlbib manages."),
           undo: bool = typer.Option(False, "--undo",
                                     help="Put that library back as it was at the newest backup.")):
    """Backups of the library cdlbib downloads and manages: --list shows them, --undo restores the newest."""
    if show and undo:
        raise typer.BadParameter("--list and --undo cannot be used together")
    if undo:
        restored = api.undo_update()
        typer.echo(f"restored the backup of {_backup_line(restored)}")
        typer.echo(f"the library as it was just before is saved in {api.backups()[0].path}")
        typer.echo("run `cdlbib update --undo` again to return to it")
    elif show:
        saved = api.backups()
        root = api.managed_root()
        if not saved:
            typer.echo(f"no backups of {root} yet")
            return
        typer.echo(f"{len(saved)} backup{'' if len(saved) == 1 else 's'} of {root}, newest first "
                   f"(kept in {saved[0].path.parent}):")
        for backup in saved:
            typer.echo("  " + _backup_line(backup).replace(": ", "  ", 1))
        typer.echo("`cdlbib update --undo` puts the library back as it was at the newest one.")
    else:
        typer.echo("updating the library is not available yet; `cdlbib update --list` shows the backups "
                   "and `cdlbib update --undo` restores the newest")


def fork_wanted(exc):
    """Whether to create the user's fork now. By default it is, after saying so; with --ask the
    user is asked first (no terminal means no)."""
    if deps.ask():
        return _confirmed(f"{exc} Create one now?")
    login = re.match(r"@(\S+) has no fork of ", str(exc))
    name = exc.upstream.split("/", 1)[1] if exc.upstream and "/" in exc.upstream else "the upstream repository"
    typer.echo(f"creating your fork {login.group(1)}/{name} ..." if login else f"creating your fork of {exc.upstream} ...")
    return True


def install_wanted(exc):
    """Whether to install the missing package now: by default yes, after saying so; with --ask
    the user is asked first (no terminal means no)."""
    if deps.ask():
        return _confirmed(f"{exc.feature} needs '{exc.package}'. Install it now?")
    typer.echo(f"installing {exc.package} (needed for: {exc.feature}) ...")
    return True


def _run_once(argv):
    try:
        app(args=argv)
    except (WorkspaceNotFound, LibraryUnavailable) as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(2)
    except GateFailed as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(2)
    except MissingDependency:
        raise  # main() offers the install
    except CdlbibError as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1)


def main(argv=None):
    """Run the command. A missing optional package is installed (after a question with --ask)
    and the command is run again once; click keeps reporting its own usage errors."""
    for attempt in (1, 2):
        try:
            _run_once(argv)
            return
        except MissingDependency as exc:
            if attempt == 2 or not install_wanted(exc):
                typer.echo(str(exc), err=True)
                raise SystemExit(1)
            try:
                deps.install(exc.extra, package=exc.package)
            except CdlbibError as failure:
                typer.echo(str(failure), err=True)
                raise SystemExit(1)


def _confirmed(question):
    """Ask only at a terminal; with none, the caller prints the manual command and exits."""
    if not sys.stdin.isatty():
        return False
    try:
        return typer.confirm(question, default=False)
    except typer.Abort:  # Ctrl-C or end of input at the prompt
        typer.echo("Aborted.", err=True)
        raise SystemExit(1)
