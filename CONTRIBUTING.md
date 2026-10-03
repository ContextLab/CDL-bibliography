# Formatting guidelines

All citation information should be entered using [BibDesk](https://bibdesk.sourceforge.io/) or a similar tool.  If you are already familiar with BibTeX (but haven't used BibDesk), please read this [Quick Start Guide](https://bibdesk.sourceforge.io/manual/BibDeskHelp_1.html#SEC5).  If you haven't used BibTeX before, you should carefully read this [BibTeX Introduction](https://bibdesk.sourceforge.io/manual/BibDeskHelp_2.html#SEC12) for instructions on how to enter citation data.  You may also find [this BibTeX guide](https://mirrors.ctan.org/biblio/bibtex/base/btxdoc.pdf) useful.  Make sure that you have carefully researched how to enter information into BibDesk before modifying cdl.bib to help avoid typos, compilation errors, incorrect information, etc. to the extent possible.  *If you're not sure whether you're doing something correctly, please ask another lab member for help!*

Please follow the formatting conventions specified [here](README.md#verify), and the rules for what belongs in the bibliography specified [here](README.md#what-belongs-in-cdlbib).  In short: copy every field from the published version of the paper (ideally starting from its DOI), and don't add conference abstracts or anything you can't verify.

# Procedure for adding a citation to the BibTeX file
## Get the bibliography

Install `cdlbib` and set `CROSSREF_MAILTO` to your email address as described in
[Installation](README.md#installation). No clone is needed. Run `cdlbib where` to
find the bibliography to edit. If you already work in a clone, the tool uses it
and never updates it.

## Modifying the BibTex file
1. For the managed library, run `cdlbib update` before editing. See
   [Managed-library updates](README.md#managed-library-updates) for unsent edits,
   backups and undo. If you use your own clone, update it yourself.
2. Search cdl.bib (by title and by the first author's surname) to make sure the paper isn't already there, possibly under a key with a suffix (e.g., `MannEtal21b`) or as a preprint that should be updated to the published version.
3. Run `cdlbib add` with the paper's DOI, PMID, arXiv identifier or title. Review
   the source-backed proposal and choose accept, edit or skip; see
   [add](README.md#add). For a type the tool does not build automatically, enter
   it yourself using the [citation key naming system](README.md#verify).
4. Review any duplicate or key-renaming message before accepting. The tool plans
   suffixes and records accepted renames in `verification/key-renames.json`.
5. Verify the formatting of the modified .bib file and the accuracy of your new entry (correct any problems until this passes):
```
cdlbib verify --verbose
```
   `verify` can offer source-backed completions before its checks. Review them as
   you would an `add` proposal; use `--no-complete` to check the entry as typed.
   If your entry can't be verified automatically, see [Human review](README.md#human-review).
6. Generate a change log and send the change(s) as a pull request into the main CDL fork:
```
cdlbib send --verbose
```
   `send` pushes a new branch to your personal fork and opens the pull request; it prints the pull request's address.
7. The pull request is checked automatically; once an admin reviews it, it'll be incorporated into the main fork and shared with the world (go science)!
