import sys
sys.path.append('bibcheck')

from helpers import check_bib, compare_bibs
import typer
import numpy as np
import subprocess

app = typer.Typer()
bibfile = 'cdl.bib'

@app.command()
def verify(fname: str, autofix: bool=False, outfile: str=None, verbose: bool=False):
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
def commit(fname=bibfile, reference='github', verbose: bool=False):
    def get_commit_fname():
        def txt_exists(fname):
            return os.path.exists(fname + '.txt')
        basename = 'commit'
        
        if txt_exists:
            basename += '-' + str(np.random.randint(10))
        while txt_exists(basename):
            basename += str(np.random.randint(10))
        return basename + '.txt'
    
    #check integrity of fname
    errors, corrected = check_bib(fname, autofix=False, outfile=None, verbose=verbose)
    if len(errors) > 0:
        typer.echo('errors found; run verify to view and/or correct.')
        return
    else:
        typer.echo('checks passed; generating commit message...')
    
    commit_fname = get_commit_fname()
    compare(reference, fname, outfile=commit_fname, verbose=verbose)
        
    #commit the changes
    subprocess(f'git commit -F {commit_fname} -m "updated bibliography" {bibfile}')
    
    if os.path.exists(commit_fname):
        os.remove(commit_fname)

if __name__ == "__main__":
    app()