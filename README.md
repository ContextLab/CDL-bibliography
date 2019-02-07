# CDL-bibliography

This bibtex file is shared by all documents produced by the [Contextual Dynamics Lab](http://www.context-lab.com) at [Dartmouth College](http://www.dartmouth.edu).

### What can I use this repo for?
You may find this bibtex file and/or readme file useful for any of the following:
- Provides a "pre seeded" bibtex file that you can configure to be referenced in your LaTeX documents
- A means of organizing a set of papers related to psychology, neuroscience, math, and machine learning
- A template for a new bibtex file that you want to start
- Instructions for configuring a system-referenced bibtex file that can be referenced by any LaTeX file on your local machine
- Instructions for adding this repo (or another similar repo) as a sub-module to Overleaf projects, so that you can share a common bibtex file across your Overleaf projects

### Credit
This bibtex file is built on a similarly named file authored by Michael Kahana's [Computational Memory Lab at the University of Pennsylvania](http://memory.psych.upenn.edu).  However, this version is not kept in sync with the CML's version.  This file is provided as a courtesy, and we make no claims with respect to accuracy, completeness, etc.

# Using the bibtex file as a common bibliography for all *local* LaTeX files
1. Check out this repository to your home directory
2. Add the following lines to your `~/.bash_profile`:
```
export TEXINPUTS=~/CDL-bibliography:$TEXINPUTS
export BIBINPUTS=~/CDL-bibliography:$BIBINPUTS
export BSTINPUTS=~/CDL-bibliography:$BSTINPUTS
```
3. Run (in terminal): `source ~/.bash_profile`
4. In your .tex file, use the line `\bibliography{memlab}` to generate a bibliography using the citation keys that were defined in memlab.bib and used in the current file.
5. To compile your document (filename.tex), generate a .bib (bibliography) file (filename.bib), and a pdf (filename.pdf), run:
```
latex filename
bibtex filename
latex filename
latex filename
pdflatex filename
```

# Using the bibtex file on Overleaf
You can use [git submodules](https://blog.github.com/2016-02-01-working-with-submodules/) to maintain a reference to the memlab.bib file in this repository that you can easily keep in sync with latest version.  This avoids the need to maintain a separate .bib file in each Overleaf project.

To set this up, you first need to access the GitHub repository associated with your Overleaf project.  Instructions may be found [here](https://www.overleaf.com/learn/how-to/How_do_I_connect_an_Overleaf_project_with_a_repo_on_GitHub,_GitLab_or_BitBucket%3F).
1. Clone your Overleaf project's GitHub repository to your local computer
2. Navigate to the repository's directory (in Terminal) and then run
```
git submodule add https://github.com/ContextLab/CDL-bibliography.git
```
3. Inside your .tex source file, change the `\bibliography{memlab}` line to `\bibliography{CDL-bibliography/memlab}`.  Now the LaTeX compiler will reference the copy of memlab.bib contained in the CDL-bibliography repository, rather than your (potentially separately maintained) local copy.
4. Commit your changes (`git commit -a -m "added CDL bibliography as a submodule"`) and then push them (`git push`).  Your project should now be updated on Overleaf, and the automatic compiler should now have access to memlab.bib.
5. To update your local copy, or to pull changes from the CDL-bibliography repository, run `git pull --recurse-submodules` inside your Overleaf project's repository directory.  Then `git push` your changes to upload them back onto Overleaf.
