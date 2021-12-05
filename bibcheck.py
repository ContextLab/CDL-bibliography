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
    try:
        errors, corrected = check_bib(fname, autofix=autofix, outfile=outfile, verbose=verbose)
    except:
        if verbose:
            typer.echo('errors found; see log for details')
        else:
            typer.echo('errors found; run with verbose flag for details')
        return
        
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
def magic(fname: str='cdl.bib', verbose: bool=True):
    typer.echo('WARNING: potentially unsafe')
    
    outfile = 'cleaned.bib'
    
    try:
        errors, corrected = check_bib(fname, autofix=True, outfile=outfile, verbose=verbose)
    except:
        if verbose:
            typer.echo('errors found; see log for details')
        else:
            typer.echo('errors found; run with verbose flag for details')
        return
    
    
    os.system(f'mv {outfile} {fname}')
    
    commit(fname=fname)
        
    
@app.command()
def compare(fname1: str, fname2: str, verbose: bool=False, outfile: str=None):
    if compare_bibs(fname1, fname2, verbose=verbose, outfile=outfile):
        typer.echo('files match!')
    else:
        if verbose:
            typer.echo('files do not match; see log for details')
        else:
            typer.echo('files do not match; run with verbose flag for details')
        

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
    try:
        errors, corrected = check_bib(fname, autofix=False, outfile=outfile, verbose=verbose)
    except:
        typer.echo('errors found; run verify to view and/or correct.')
        return
    
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