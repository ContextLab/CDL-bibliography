import sys
from pathlib import Path

import typer
import os
from cdlbib.verification_cli import app as crossref_app

app = typer.Typer()
app.add_typer(crossref_app, name='crossref')
bibfile = 'cdl.bib'

def run_check(fname, **kwargs):
    """check_bib, with any failure shown and turned into a nonzero exit.

    A bare ``except`` used to print only 'errors found' and return success,
    which hid e.g. 'page numbers are ambiguous or incorrect: KothEtal25'.
    """
    from cdlbib.helpers import check_bib
    try:
        return check_bib(fname, **kwargs)
    except Exception as exc:
        typer.echo(f'errors found: {type(exc).__name__}: {exc}', err=True)
        raise typer.Exit(code=1) from exc


def check_library(fname, reference='github', citations=True, all_entries=False, autofix=False,
                  outfile=None, verbose=False, database=None, mailto=None):
    """The shared gate of `verify` and `commit` (user decisions 2026-09-25 07:42 and 07:44 EDT).

    (1) the format check (check_bib); (2) citation verification of the added/edited
    entries relative to ``reference`` (the GitHub master cdl.bib by default, the file
    compare_bibs uses; key-only renames excluded), or of every entry with
    ``all_entries``; (3) an offline library-wide status line. Returns True when the
    format is clean and every checked entry is verified; the library-wide backlog is
    reported but does not fail the gate. ``citations=False`` is the offline,
    format-only check.
    """
    errors, corrected = run_check(fname, autofix=autofix, outfile=outfile, verbose=verbose)
    if outfile:
        typer.echo(f'saved updated bibliography to {outfile}')
    format_ok = len(errors) == 0
    if format_ok:
        typer.echo('format: looks good!')
    else:
        if autofix:
            if outfile:
                typer.echo(f'errors found; autocorrected and saved to {outfile}')
            else:
                typer.echo('errors found; specify outfile to save autocorrections')
        if verbose:
            typer.echo('errors found; see log for details')
        else:
            typer.echo('errors found; run with verbose flag for details')
        if not (autofix and outfile):
            return False
        typer.echo('citations not checked: review the autocorrected file, then run verify on it')
        return True
    if not citations:
        return format_ok
    from cdlbib.verification_cli import citation_gate
    from cdlbib.verification import ProviderError
    try:
        ok, _, _ = citation_gate(fname, reference=reference, database=database, all_entries=all_entries,
                                 mailto=mailto)
    except (ValueError, OSError, ProviderError) as exc:
        typer.echo(f'citation check failed: {type(exc).__name__}: {exc}', err=True)
        raise typer.Exit(code=2) from exc
    return ok and format_ok


@app.command()
def verify(fname: str='cdl.bib', autofix: bool=False, outfile: str=None, verbose: bool=False,
           reference: str='github',
           no_citations: bool=typer.Option(False, '--no-citations',
                                           help='Offline, format-only check (no citation verification).'),
           all: bool=typer.Option(False, '--all', help='Verify the citations of every entry, not only changed ones.'),
           database: str=typer.Option(None, '--database', help='Verification cache (default .bibcheck/verification.sqlite3).'),
           mailto: str=typer.Option(None, '--mailto', envvar='CROSSREF_MAILTO', help='Contact email for Crossref.')):
    """Format check, then citation verification of new/edited entries (see check_library)."""
    if check_library(fname, reference=reference, citations=not no_citations, all_entries=all,
                     autofix=autofix, outfile=outfile, verbose=verbose, database=database, mailto=mailto):
        typer.echo('looks good!')
    else:
        raise typer.Exit(code=1)


@app.command()
def magic(fname: str='cdl.bib', verbose: bool=True):
    from cdlbib.helpers import check_bib
    typer.echo('WARNING: potentially unsafe')
    
    outfile = 'cleaned.bib'
    
    errors, corrected = run_check(fname, autofix=True, outfile=outfile, verbose=verbose)

    
    os.system(f'mv {outfile} {fname}')
    
    commit(fname=fname, database=None, mailto=os.environ.get('CROSSREF_MAILTO'))
        
    
@app.command()
def compare(fname1: str, fname2: str, verbose: bool=False, outfile: str=None):
    from cdlbib.helpers import compare_bibs
    if compare_bibs(fname1, fname2, verbose=verbose, outfile=outfile):
        typer.echo('files match!')
    else:
        if verbose:
            typer.echo('files do not match; see log for details')
        else:
            typer.echo('files do not match; run with verbose flag for details')
        

@app.command()
def commit(fname=bibfile, reference='github', verbose: bool=False, outfile=None,
           database: str=typer.Option(None, '--database', help='Verification cache (default .bibcheck/verification.sqlite3).'),
           mailto: str=typer.Option(None, '--mailto', envvar='CROSSREF_MAILTO', help='Contact email for Crossref.')):
    """Run the verify gate, then commit only the bibliography file."""
    from cdlbib.helpers import compare_bibs
    import subprocess

    if not check_library(fname, reference=reference, verbose=verbose, database=database, mailto=mailto):
        typer.echo('not committed: fix the format errors and resolve every new/edited entry first '
                   '(see `bibcheck.py verify`).')
        raise typer.Exit(code=1)
    typer.echo('checks passed; generating commit message...')

    _, changes = compare_bibs(reference, fname, outfile=outfile, verbose=verbose, return_summary=True)

    # Commit only the bibliography (no shell, no quoting hazards, nothing else staged).
    run = subprocess.run(['git', 'commit', '-m', changes or 'update bibliography', '--', fname],
                         cwd=Path(fname).resolve().parent, capture_output=True, text=True)
    typer.echo(run.stdout + run.stderr)
    if run.returncode != 0:
        raise typer.Exit(code=run.returncode)


if __name__ == "__main__":
    app()
