from helpers import check_bib, compare_bibs
import typer

app = typer.Typer()

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

if __name__ == "__main__":
    app()