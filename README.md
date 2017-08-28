# CDL-bibliography

This Bibtex file is shared by all documents produced by the [Contextual Dynamics Lab](http://www.context-lab.com) at [Dartmouth College](http://www.dartmouth.edu).  *Please read the instructions below **in full** before modifying this shared lab resource.*

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
1. Add an entry to for the article (using the citation key naming system described above) and fill in the relevant information.
2. If the citation key (let's call it `<KEYNAME>`) already exists in the database, do the following:

  - Rename the existing `<KEYNAME>` entry to `<KEYNAME>a`
  - Rename the new `<KEYNAME>` entry to `<KEYNAME>b`
  - If `<KEYNAME>b` already exists, rename the new entry to `<KEYNAME>c` (and so on).
3. Commit the change (`git add *; git commit -a -m "<KEYNAME>a, <KEYNAME>b"`).  Make sure to note any citation keys that were altered.
4. Push the change (`git push`).
