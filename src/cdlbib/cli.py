"""The cdlbib command. Parsing and formatting only; the work is in cdlbib.api."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer

from . import __version__, api
from .errors import CdlbibError, GateFailed, WorkspaceNotFound
from . import workspace
from .verification_cli import app as crossref_app, library
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
                                      help="Show the version and exit.")):
    workspace.select_library(library_path)


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
    """Format check, then citation verification of new/edited entries (see check_library)."""
    check = run_gate(ctx, fname, reference=reference, citations=not no_citations, all_entries=all, autofix=autofix,
                     outfile=outfile, verbose=verbose, database=database, mailto=mailto)
    if not check.ok:
        raise typer.Exit(code=1)
    typer.echo("looks good!")


@app.command()
def magic(ctx: typer.Context, fname: str = BIB_NAME, verbose: bool = True):
    # Autofix the format in place, then commit. Potentially unsafe.
    typer.echo("WARNING: potentially unsafe")
    ws = library(ctx, fname)
    cleaned = ws.bib.with_name("cleaned.bib")
    report_format(api.check_format(ws, autofix=True, outfile=str(cleaned), verbose=verbose, bars=sys.stderr),
                  ws, fname)
    shutil.move(str(cleaned), str(ws.bib))
    commit(ctx, fname=fname, database=None, mailto=os.environ.get("CROSSREF_MAILTO"))


@app.command()
def compare(fname1: str, fname2: str, verbose: bool = False, outfile: str = None):
    result = api.compare(fname1, fname2, verbose=verbose, outfile=outfile, bars=sys.stderr)
    typer.echo(result.log, nl=False)
    if result.match:
        typer.echo("files match!")
    else:
        typer.echo("files do not match; see log for details" if verbose
                   else "files do not match; run with verbose flag for details")


@app.command()
def commit(ctx: typer.Context, fname=BIB_NAME, reference="github", verbose: bool = False, outfile=None,
           database: str = typer.Option(None, "--database", help="Verification cache (default .bibcheck/verification.sqlite3)."),
           mailto: str = typer.Option(None, "--mailto", envvar="CROSSREF_MAILTO", help="Contact email for Crossref.")):
    """Run the verify gate, then commit only the bibliography file."""
    ws = library(ctx, fname)
    if not run_gate(ctx, fname, reference=reference, verbose=verbose, database=database, mailto=mailto).ok:
        typer.echo("not committed: fix the format errors and resolve every new/edited entry first "
                   "(see `cdlbib verify`).")
        raise typer.Exit(code=1)
    typer.echo("checks passed; generating commit message...")

    comparison = api.compare(reference, str(ws.bib), outfile=outfile, verbose=verbose, bars=sys.stderr)
    typer.echo(comparison.log, nl=False)

    # Commit only the bibliography (no shell, no quoting hazards, nothing else staged).
    run = subprocess.run(["git", "commit", "-m", comparison.summary or "update bibliography", "--", str(ws.bib)],
                         cwd=ws.bib.parent, capture_output=True, text=True)
    typer.echo(run.stdout + run.stderr)
    if run.returncode != 0:
        raise typer.Exit(code=run.returncode)


def main():
    try:
        app()
    except WorkspaceNotFound as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(2)
    except GateFailed as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(2)
    except CdlbibError as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1)
