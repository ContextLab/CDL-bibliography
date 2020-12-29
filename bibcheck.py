import sys
sys.path.append('bibcheck')

from helpers import check_bib, compare_bibs
import typer
import numpy as np
import os

app = typer.Typer()
bibfile = 'cdl.bib'

@app.command()
def verify(fname: str='cdl.bib', autofix: bool=False, outfile: str=None, verbose: bool=False):
    errors, corrected = check_bib(fname, autofix=autofix, outfile=outfile, verbose=verbose)
    
    if outfile:
        typer.echo(f'saved updated bibliography to {outfile}')
    
    if len(errors) == 0:
        typer.echo('looks good!')
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
    
@app.command()
def compare(fname1: str, fname2: str, verbose: bool=False, outfile: str=None):
    compare_bibs(fname1, fname2, verbose=verbose, outfile=outfile)

@app.command()
def commit(fname=bibfile, reference='github', verbose: bool=False, outfile=None):
    def get_commit_fname():
        def log_exists(fname):
            return os.path.exists(fname + '.log')
        basename = 'change'
        
        if log_exists(basename):
            basename += '-' + str(np.random.randint(10))
        while log_exists(basename):
            basename += str(np.random.randint(10))
        return basename + '.log'
    
    #check integrity of fname
    errors, corrected = check_bib(fname, autofix=False, outfile=None, verbose=verbose)
    if len(errors) > 0:
        typer.echo('errors found; run verify to view and/or correct.')
        return
    else:
        typer.echo('checks passed; generating commit message...')
    
    if outfile:
        commit_fname = outfile
    else:
        commit_fname = get_commit_fname()
    
    _, changes = compare_bibs(reference, fname, outfile=outfile, verbose=verbose, return_summary=True)
        
    #commit the changes
    os.system(f'git commit -a -m "{changes}"')

if __name__ == "__main__":
    app()