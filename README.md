# CDL-bibliography

This Bibtex file is shared by all documents produced by the [Contextual Dynamics Lab](http://www.context-lab.com) at [Dartmouth College](http://www.dartmouth.edu).  *Please read the instructions below **in full** before modifying this shared lab resource.*

Credit: this bibtex file is built on a similarly named file authored by Michael Kahana's [Computational Memory Lab at the University of Pennsylvania](http://memory.psych.upenn.edu).  However, this version is not kept in sync with the CML's version.  This file is provided as a courtesy, and we make no claims with respect to accuracy, completeness, etc.

# Formatting guidelines

All citation information should be entered using [BibDesk](http://bibdesk.sourceforge.net/) or a similar tool.  If you are already familiar with BibTeX (but haven't used BibDesk), please read this [Quick Start Guide](http://bibdesk.sourceforge.net/manual/BibDeskHelp_1.html#SEC5).  If you haven't used BibTeX before, you should carefully read this [BibTeX Introduction](http://bibdesk.sourceforge.net/manual/BibDeskHelp_2.html#SEC12) for instructions on how to enter citation data.  You may also find [this BibTeX guide](http://mirror.hmc.edu/ctan/biblio/bibtex/contrib/doc/btxdoc.pdf) useful.  Make sure that you have carefully researched how to enter information into BibDesk before modifying memlab.bib to help avoid typos, compilation errors, incorrect information, etc. to the extent possible.  *If you're not sure whether you're doing something correctly, please ask another lab member for help!*

We follow the citation key conventions below.

## Material with a single author

The citation key should be the (capitalized) first four letters of the author's name, followed by a two-digit year.  Example: Mann17.

## Material with two authors

The citation key should be the (capitalized) first four letters of the authors' names, followed by a two-digit year. Example: MannHeus17.

## Material with three or more authors

The citation key should be the (capitalized) first four letters of the first author's name, followed by "Etal," followed by a two-digit year.  Example: MannEtal17.

## Conflicting citation keys

If the citation key is not unique (e.g. the same citation key could refer to multiple documents), lower case letters should be added to the end of the citation key to differentiate different documents.  Examples: Mann17a, Mann17b, etc.  Note that when a new non-unique citation key is added to the BibTeX file, older citation keys may need to be updated.
This may break backwards compatibility.  For example, if a previous document used a citation key without a lower case letter, and a new similar citation key is added (which requires renaming a previous citation key without a lower case letter), the old citation key should no longer work.  Importantly, no lettered citation keys should ever be renamed.
In other words, the only time a citation key of an existing entry should be renamed is if a new matching entry needs to be added to the BibTeX file.  The reason this is important is that the document to which a citation key refers should never change (but a citation key may be deleted).

# Procedure for adding a citation to the BibTeX file
## Fork this repository
1. Create a personal fork of the CDL-bibliography repository by pressing the "Fork" button in the upper right of the repository's page (when viewed on GitHub)
2. Clone the fork to your local machine
3. Set the ContextLab fork of the repository as a "remote" of your copy: `git remote add upstream https://github.com/ContextLab/CDL-bibliography.git`

## Modifying the BibTex file
1. Before making any changes, make sure you're working with the latest version: `git pull upstream master`.  If you modify memlab.bib *after* you've made changes, you may need to resolve merge conflicts.
2. Add an entry for the article (using the citation key naming system described above) and fill in the relevant information.
3. If the citation key (let's call it `<KEYNAME>`) already exists in the database, do the following:

  - Rename the existing `<KEYNAME>` entry to `<KEYNAME>a`
  - Rename the new `<KEYNAME>` entry to `<KEYNAME>b`
  - If `<KEYNAME>b` already exists, rename the new entry to `<KEYNAME>c` (and so on).
4. Commit the change (`git commit -a -m "<KEYNAME>a, <KEYNAME>b"`).  Make sure to note any citation keys that were altered or added.
5. Push the change (`git push`).
6. To incorporate your changes into the main CDL fork, submit a pull request (press the "Pull request" button on your personal fork's GitHub page).  Once an admin reviews your pull request it'll be incorporated into the main fork and shared with the world (go science)!

# Using the bibtex file as a common bibliography for all *local* LaTeX files
1. Check out this repository to your home directory
2. Add the following lines to your `~/.bash_profile`:
```
export TEXINPUTS=~/CDL-bibliography:$TEXINPUTS
export BIBINPUTS=~/CDL-bibliography:$BIBINPUTS
export BSTINPUTS=~/CDL-bibliography:$BSTINPUTS
```
3. Run (in terminal): `source ~.bash_profile`
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
