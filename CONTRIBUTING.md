# Formatting guidelines

All citation information should be entered using [BibDesk](http://bibdesk.sourceforge.net/) or a similar tool.  If you are already familiar with BibTeX (but haven't used BibDesk), please read this [Quick Start Guide](http://bibdesk.sourceforge.net/manual/BibDeskHelp_1.html#SEC5).  If you haven't used BibTeX before, you should carefully read this [BibTeX Introduction](http://bibdesk.sourceforge.net/manual/BibDeskHelp_2.html#SEC12) for instructions on how to enter citation data.  You may also find [this BibTeX guide](http://mirror.hmc.edu/ctan/biblio/bibtex/contrib/doc/btxdoc.pdf) useful.  Make sure that you have carefully researched how to enter information into BibDesk before modifying memlab.bib to help avoid typos, compilation errors, incorrect information, etc. to the extent possible.  *If you're not sure whether you're doing something correctly, please ask another lab member for help!*

Please follow the formatting conventions specified [here](https://github.com/ContextLab/CDL-bibliography#verify).

# Procedure for adding a citation to the BibTeX file
## Fork this repository
1. Create a personal fork of the CDL-bibliography repository by pressing the "Fork" button in the upper right of the repository's page (when viewed on GitHub)
2. Clone the fork to your local machine
3. Set the ContextLab fork of the repository as a "remote" of your copy: `git remote add upstream https://github.com/ContextLab/CDL-bibliography.git`

## Modifying the BibTex file
1. Before making any changes, make sure you're working with the latest version: `git pull upstream master`.  If you modify memlab.bib *after* someone has made changes to the master branch, you'll need to resolve merge conflicts.  (Recommended tool for resolving merge conflicts: [Atom](https://github.atom.io/).)
2. Add an entry for the article (using the citation key naming system described above) and fill in the relevant information.
3. If the citation key (let's call it `<KEYNAME>`) already exists in the database, do the following:

  - Rename the existing `<KEYNAME>` entry to `<KEYNAME>a`
  - Rename the new `<KEYNAME>` entry to `<KEYNAME>b`
  - If `<KEYNAME>b` already exists, rename the new entry to `<KEYNAME>c` (and so on).
4. Verify the integrity of the modified .bib file (correct any changes until this passes):
```
python bibcheck.py verify --verbose
```
5. Generate a change log and commit the change(s):
```
python bibcheck.py commit --verbose
```
6. Push the change (`git push`).
7. To incorporate your changes into the main CDL fork, submit a pull request (press the "Pull request" button on your personal fork's GitHub page).  Once an admin reviews your pull request it'll be incorporated into the main fork and shared with the world (go science)!
