# Formatting guidelines

All citation information should be entered using [BibDesk](https://bibdesk.sourceforge.io/) or a similar tool.  If you are already familiar with BibTeX (but haven't used BibDesk), please read this [Quick Start Guide](https://bibdesk.sourceforge.io/manual/BibDeskHelp_1.html#SEC5).  If you haven't used BibTeX before, you should carefully read this [BibTeX Introduction](https://bibdesk.sourceforge.io/manual/BibDeskHelp_2.html#SEC12) for instructions on how to enter citation data.  You may also find [this BibTeX guide](https://mirrors.ctan.org/biblio/bibtex/base/btxdoc.pdf) useful.  Make sure that you have carefully researched how to enter information into BibDesk before modifying cdl.bib to help avoid typos, compilation errors, incorrect information, etc. to the extent possible.  *If you're not sure whether you're doing something correctly, please ask another lab member for help!*

Please follow the formatting conventions specified [here](README.md#verify), and the rules for what belongs in the bibliography specified [here](README.md#what-belongs-in-cdlbib).  In short: copy every field from the published version of the paper (ideally starting from its DOI), and don't add conference abstracts or anything you can't verify.

# Procedure for adding a citation to the BibTeX file
## Fork this repository
1. Create a personal fork of the CDL-bibliography repository by pressing the "Fork" button in the upper right of the repository's page (when viewed on GitHub)
2. Clone the fork to your local machine
3. Set the ContextLab fork of the repository as a "remote" of your copy: `git remote add upstream https://github.com/ContextLab/CDL-bibliography.git`
4. Install the checker (see [Installation](README.md#installation)), and set `CROSSREF_MAILTO` to your email address

## Modifying the BibTex file
1. Before making any changes, make sure you're working with the latest version: `git pull upstream master`.  If you modify cdl.bib *after* someone has made changes to the master branch, you'll need to resolve merge conflicts.
2. Search cdl.bib (by title and by the first author's surname) to make sure the paper isn't already there, possibly under a key with a suffix (e.g., `MannEtal21b`) or as a preprint that should be updated to the published version.
3. Add an entry for the article (using the [citation key naming system](README.md#verify)) and fill in the relevant information, including the DOI if the paper has one.
4. If the citation key (let's call it `<KEYNAME>`) already exists in the database, do the following:

  - Rename the existing `<KEYNAME>` entry to `<KEYNAME>a`
  - Rename the new `<KEYNAME>` entry to `<KEYNAME>b`
  - If `<KEYNAME>b` already exists, rename the new entry to `<KEYNAME>c` (and so on).
5. Verify the formatting of the modified .bib file and the accuracy of your new entry (correct any problems until this passes):
```
cdlbib verify --verbose
```
   If your entry can't be verified automatically, see [Human review](README.md#human-review).
6. Generate a change log and send the change(s) as a pull request into the main CDL fork:
```
cdlbib commit --verbose
```
   `commit` pushes a new branch to your personal fork and opens the pull request; it prints the pull request's address.
7. The pull request is checked automatically; once an admin reviews it, it'll be incorporated into the main fork and shared with the world (go science)!
