# CDL bibliography manager (`cdlbib`)

![autocheck](https://github.com/ContextLab/CDL-bibliography/workflows/autocheck/badge.svg) ![citation check](https://github.com/ContextLab/CDL-bibliography/actions/workflows/citation-check.yml/badge.svg) [![DOI](https://zenodo.org/badge/69401856.svg)](https://zenodo.org/badge/latestdoi/69401856)

`cdlbib` manages the shared [BibTeX bibliography](https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/cdl.bib) used by the [Contextual Dynamics Lab](https://www.context-lab.com/) at [Dartmouth College](https://www.dartmouth.edu/). It downloads and updates a local library, helps add references from source records, checks formatting and citation accuracy, records human reviews, and sends contributions through GitHub pull requests.

`cdlbib` has a **command line**, a **terminal interface** (`cdlbib tui`) and a **local web interface** (`cdlbib web`), all backed by a shared Python API. `cdlbib setup` [makes the library available to every LaTeX manuscript](#using-the-bibtex-file-as-a-common-bibliography-for-all-local-latex-files) on the computer, and `cdlbib export` [writes the entries a paper cites](#frozen-manuscript-copies-and-exports) as a `.bib` of its own or as its compiled `.bbl`. See [Current capabilities and design](#current-capabilities-and-design) and the [tutorials](docs/tutorials.md).

For CDL members, the goal is one accurate, consistent bibliography across written documents. Other groups are welcome to adapt the approach for their own libraries.

As of September 30, 2026, every one of the 6,384 entries in `cdl.bib` has been checked against the published record. 6,348 entries match their source's metadata, and a person reviewed and approved the remaining 36 against the source itself. New and edited entries are checked automatically on every pull request. "Verified" means the citation agrees with the published record. It does not guarantee the record is error-free, so please still look over the rendered bibliography of anything you submit.

## Contents

- [Current capabilities and design](#current-capabilities-and-design)
- [Installation](#installation)
- [Managed-library updates](#managed-library-updates)
- [Overview](#overview)
- [Suggested workflow](#suggested-workflow)
- [Tutorials](docs/tutorials.md)
- [What belongs in `cdl.bib`](#what-belongs-in-cdlbib)
- [Command reference](#additional-information-and-usage-instructions)
  - [`cdlbib add`](#add)
  - [`cdlbib verify`](#verify)
  - [`cdlbib compare`](#compare)
  - [`cdlbib send`](#send)
  - [`cdlbib web`](#web)
  - [`cdlbib setup`](#automated-setup-cdlbib-setup)
  - [`cdlbib export`](#frozen-manuscript-copies-and-exports)
  - [`cdlbib crossref`: citation verification](#crossref-citation-verification)
- [System-wide LaTeX use](#using-the-bibtex-file-as-a-common-bibliography-for-all-local-latex-files)
- [Overleaf](#using-the-bibtex-file-on-overleaf)
- [Optional Git submodule](#using-the-bibtex-file-as-a-submodule-of-a-papers-repository)
- [Frozen manuscript copies and exports](#frozen-manuscript-copies-and-exports)
- [Python API](#using-it-from-python)
- [Tests](#running-the-tests)
- [Acknowledgements](#acknowledgements)

## Current capabilities and design

| Available in this version | Where |
| --- | --- |
| Installable `cdlbib` package, CLI and shared Python API | `cdlbib`, `cdlbib.api` |
| Local web interface: browse, search, edit, check, review, add, send, library state and setup in the browser | `cdlbib web` |
| Automatic library download, updates during command use, backups and undo | `cdlbib update`; web: Library state |
| DOI/PMID/arXiv and title-with-author lookup; review, edit or skip source-supported entries | `cdlbib add`; web: Add |
| Search by title, authors or both, with a list of candidates to choose from | web: Add, "Search" tab |
| PDF intake: the first page beside what was read, lookup of the source record, reading with a language model, and a manual-entry form filled from the PDF | web: Add, "PDF" and "Manual" tabs |
| Entries built from source records: journal articles, arXiv preprints, papers in conference proceedings and book chapters | `cdlbib add`; web: Add |
| House-format and citation checks, source evidence, GitHub-attributed human approvals and revocations | `cdlbib verify`, `cdlbib crossref`; web: Check, Library, Review |
| Contributions through your own fork and an opened or updated PR | `cdlbib send`; web: Send |
| System-wide LaTeX setup: one link in your TeX tree | `cdlbib setup`; web: Setup |
| Cited-key `.bib` export, and `.bbl` generation from manuscript/style inputs | `cdlbib export`; web: Setup (`.bib` only) |
| Optional Dartmouth Chat/OpenAI research adapters and keychain credentials | `cdlbib crossref research`; web: Add, "PDF" tab |
| Terminal interface (TUI) with the same views as the web interface (of a PDF it shows the text read; the page itself is shown in the web interface) | `cdlbib tui`; [tutorial](docs/tutorials/terminal-interface.md) |
| Tutorials, screenshots and recorded demonstrations | [docs/tutorials.md](docs/tutorials.md) |

The web interface uses the same formatting, verification, identity and library
services as the CLI. Accepting proposed metadata remains separate from a human
approval. When an update is available and there are unsent changes, the web
interface asks the same question as the command line.

[Issue #95](https://github.com/ContextLab/CDL-bibliography/issues/95) records the
full design, the work supplied by [PR #94](https://github.com/ContextLab/CDL-bibliography/pull/94),
and remaining milestones. PyPI publication is a separate, manual maintainer step; see
[Releasing](docs/releasing.md).

The former `bibcheck.py` and `bibverify.py` entry points are now `cdlbib` and
`cdlbib crossref`. `commit` is now `send`. The old `magic` command is replaced by
source-supported completion in `add`, `verify` and `send`, using the existing house
formatter. The older fuzzy-matching verifier and its `--workers` option are retired.

## Installation

`cdlbib` is used on macOS with Python 3.11 and tested automatically on Linux (Ubuntu) with Python 3.11 and 3.13. Windows is untested.

Install with Python 3.11 or later:

```bash
python -m pip install cdlbib
cdlbib --help
```

Git must be installed for the managed download and updates. No manual clone is needed.
`--help` and `--version` do not download a library. When a command needs a library
and you have not selected one, `cdlbib` downloads the bibliography on first use. The managed copy is stored in:

- macOS: `~/Library/Application Support/cdlbib/library/`
- Linux: `$XDG_DATA_HOME/cdlbib/library/`, or `~/.local/share/cdlbib/library/` when `XDG_DATA_HOME` is unset.
- Other platforms currently use the Linux-style location; Windows is untested.

Set `CDLBIB_HOME` to choose a different data folder; the library is its `library/`
subfolder. Run `cdlbib where` to see which bibliography a command will use.

The lookup order is a named bibliography file (for commands that accept one),
`--library PATH`, `CDLBIB_LIBRARY`, `cdl.bib` in the current folder or the nearest
folder above it, then the managed library. If you already work in a clone, the tool
uses it and never updates it. A named folder without `cdl.bib` remains an error:

```text
--library points to FOLDER, which has no cdl.bib
```

The same error begins with `CDLBIB_LIBRARY` when that variable named the folder.
Global options go before the command, for example:

```bash
cdlbib --library "/absolute/path/to/library" verify --no-citations
```

The dependencies are listed in `pyproject.toml`. Three optional extras add packages
that only some features need:

|Extra|Package|Needed for|
|-|-|-|
|`research`|`pypdf`|reading PDFs (`cdlbib crossref research`, and the "PDF" tab of the web interface)|
|`pdf`|`pypdfium2`|showing the first page of a PDF as an image in the web interface|
|`tui`|`textual`|the terminal interface (`cdlbib tui`)|

Install them ahead of time with `python -m pip install "cdlbib[research,pdf,tui]"`, or
not at all: if an optional package is missing when a command needs it, the tool
prints a line saying so and installs it, for example

```text
installing pypdf (needed for: Reading PDF files) ...
```

Use `cdlbib --ask COMMAND` to be asked first; without a terminal,
`--ask` leaves it uninstalled and prints the manual installation command.

`cdlbib export --bbl` treats a missing `biber` or `bibtex` the same way where the TeX
installation's own package manager can install it without an administrator:

|TeX installation|A missing `biber` or `bibtex`|
|-|-|
|TeX Live in a folder you can write to (for example TinyTeX)|installed with `tlmgr install biber` or `tlmgr install bibtex`|
|Homebrew `texlive`|`biber` is installed with `brew install biber`|
|TeX Live in a folder you cannot write to, TeX from `apt-get`, `dnf` or `pacman`, MiKTeX|not installed; the message names the command, for example `Run: sudo tlmgr install biber`|

`cdlbib` never runs `sudo`. See
[the LaTeX tutorial](docs/tutorials/latex-setup-and-export.md#when-biber-or-bibtex-is-not-installed).

`cdlbib setup` and `cdlbib export --bbl` use a TeX installation (TeX Live or
MacTeX), which is installed separately. `cdlbib setup` lists what it found on the
computer.

## Managed-library updates

When a command uses the managed library, it checks for updates at most once a day
when the command runs. There is no background updater. `cdlbib update` checks now.
If the upstream cannot be reached, the command uses the downloaded copy and prints
a notice. Failed automatic checks retry when a command runs after about an hour.
A first download needs a connection and Git.

Before an update changes the managed library, it saves a backup. Run
`cdlbib update --list` to list backups, or `cdlbib update --undo STAMP` to restore
one named in that list. Without a stamp, undo restores an interrupted operation’s
backup first, then the latest completion command’s checkpoint, or otherwise the
newest backup. Backups are kept under `backups/` in the data folder.

If a newer version is available and you have unsent edits, the tool asks what to do.
For one changed entry and two new upstream commits, the question reads:

```text
A newer version of the bibliography is available (2 new commits), and you have changes that have not been sent:
  cdl.bib (1 entry changed)
What would you like to do?
  [k] Keep working without updating (ask again tomorrow)
  [u] Update and keep my changes
  [s] Send my changes first (runs `cdlbib send`)
  [d] Discard my changes and update (they are saved first; `cdlbib update --undo` brings them back)
```

After a sent PR merges, the next managed-library update can return to the main
branch and bring in the merged version. An open PR is left in place; a closed PR
or further local edits may require a choice. An unreachable GitHub service leaves
the send branch intact.

The files, counts and available choices depend on your changes. Without a terminal,
no choice is made and your files are left as they were. Keeping your copy postpones
the question until tomorrow; `cdlbib update` asks again now.

`send`, `crossref approve` and `crossref revoke` take your identity from the [GitHub CLI](https://cli.github.com) (`gh`); install it and run `gh auth login` before using them.

The accuracy checker contacts Crossref and other public services, which ask that you identify yourself. Set a real contact address before running it (or pass `--mailto`):

```bash
export CROSSREF_MAILTO='your.name@dartmouth.edu'
```

## Overview

`cdlbib` has the following commands (a summary; run `cdlbib --help` for the full list):

```bash
Commands:
  add       Look up entries, then accept, edit or skip each proposal
  verify    Format check, then citation verification of new/edited entries
  compare   Show the differences between two .bib files
  send      Run the verify gate, then send the change as a pull request from your fork
  crossref  Check citation accuracy against external evidence (never edits BibTeX)
  web       Open the local web interface (this computer only) on the library in use
  tui       Open the terminal interface on the library
  where     Show which bibliography the command will use
  update    Check the managed library now; list or restore its backups
  setup     Link cdl.bib into your TeX tree so every manuscript finds it; report what cdlbib can use here
  export    Write the entries a paper cites as a .bib of its own, or its compiled .bbl
```

Run `cdlbib COMMAND --help` for the options of any command.

Step-by-step tutorials, one for each task, are listed in [docs/tutorials.md](docs/tutorials.md). Each shows the command-line way and, where there is one, the web-interface way.

# Suggested workflow

Start from a folder outside an existing bibliography checkout to use the managed
library, or select your own library with `--library`. Install the
[GitHub CLI](https://cli.github.com) and run `gh auth login` before recording a
human review or sending a contribution. Set your Crossref contact address as
shown above.

1. **Find your library and add a reference.**

   ```bash
   cdlbib where
   cdlbib add 10.1002/tea.3660271011
   ```

   `where` prints the library folder, how it was selected, and any download or
   update notices. `add` looks up the source, reports duplicates, and lets you accept,
   edit or skip the proposed entry. You can also use a PMID, arXiv identifier or
   title with `--author`. No change is sent to GitHub yet. To modify an existing
   reference directly, edit `cdl.bib` in the folder shown by `where` with your
   preferred text editor, then run the checks below.

2. **Check your changes.**

   ```bash
   cdlbib verify --verbose
   ```

   Completion is offered for new or edited entries before the checks run. The
   format check covers the whole file; citation checks normally cover entries
   changed from upstream. Resolve the reported problems and rerun. If a correct
   entry cannot be checked automatically, follow [Human review](#human-review).
   Accepting a completion proposal is not a human approval.

3. **Send the contribution.**

   ```bash
   cdlbib send --verbose
   ```

   `send` checks the final bibliography and evidence, commits bibliography and
   verification changes, pushes to your own fork, and opens or updates a PR into
   the upstream repository. It preserves unrelated working files and refuses
   unrelated outgoing commits. The same fork route applies to maintainers and
   other contributors; no direct push access to ContextLab is needed.

4. **Review the PR and keep your copy current.**

   CI checks formatting, tests and citations. Review and merge happen on GitHub.
   Subsequent sends on the contribution branch update the same PR. For the
   managed library, `cdlbib update` checks its state now; normal command use also
   performs the daily update check. Your own clone remains yours to update.

[The tutorials](docs/tutorials.md) walk through adding, modifying and searching
references, verification, human review, sending a PR, LaTeX setup and export,
the web interface and credentials. Adding, checking and sending can also be done
in the browser: run `cdlbib web` ([the web interface](docs/tutorials/web-interface.md)).
This recording shows
reviewing, editing, rechecking and accepting an entry in a scratch library:

![CLI entry review, edit, recheck and acceptance](docs/media/add.gif)

# What belongs in `cdl.bib`

These are the lab's rules for what an entry must look like and when an entry is left out. The full decision log, with the reasoning and every case they were applied to, is in [docs/decision-log.md](docs/decision-log.md).

- **Cite the work as printed.** Every field should match the official published record, up to the formatting conventions below. If the published version and a preprint differ, cite the one you actually mean.
- **The printed paper wins.** Normally the publisher's metadata (e.g., in Crossref) is taken as the record. When there is reason to doubt it, such as a correction notice, sources that disagree with each other, or a lab member's flag, the paper as printed decides.
- **No conference abstracts.** Short meeting abstracts are not citable publications and are not kept. Full papers in conference *proceedings* are fine. Before dropping something as an abstract, check that it really is one.
- **If it can't be verified, leave it out.** An entry that can't be verified, even after searching the web for evidence, is dropped. So is an entry whose details stay ambiguous after research. It can always be added back once the evidence turns up.

# Additional information and usage instructions

## `add`

Look up a paper by DOI, PMID, arXiv identifier or title:

```bash
cdlbib add 10.1002/tea.3660271011
cdlbib add PMID:13896567
cdlbib add arXiv:2208.02957
cdlbib add "Students' misunderstandings and misconceptions in college freshman chemistry (general and organic)" --author Zoller --year 1990
```

Use `--from FILE` for a UTF-8 file with one query per line. With no query arguments,
`add` also reads BibTeX from standard input. Set `CROSSREF_MAILTO` or pass `--mailto`
so the citation services can identify your requests.

The tool can build journal articles, arXiv preprints, papers in conference
proceedings and book chapters from their source records. A chapter is built
without its book's editors and place of publication, and a proceedings paper
without a publisher or place: the record does not state them, or the citation
check has no test for them, and the proposal lists them as unfilled. It does not
build books, theses, reports, software or datasets automatically. Enter those
yourself and use `verify`. A linked published version
is offered when the source records identify one. An identifier or close title
alone does not establish that a proposal is the work you meant.

Before writing, `add` shows the typed and proposed entries, each field's source,
unfilled fields and their reasons, the verification outcome, and any duplicate
or key rename. Read these before choosing:

```text
[a] accept   [e] edit   [s] skip   [A] accept all remaining   [q] stop
```

`a` writes that entry; `s` leaves it out. `q` ends the session and keeps entries
already accepted. `A` accepts remaining complete proposals that need no decision;
it still asks about candidates, names or other findings that need your choice.
Duplicates, unsupported types, missing required fields and format/key conflicts
must be resolved before an entry can be accepted. Accepting a proposal writes
BibTeX; it does not record a human approval or send a pull request.

A duplicate already typed into the library has separate choices: `r` removes that
typed entry, and `k` keeps both entries for the formatter to report. Removal checks
that the typed entry and the matching work are still present. Ordinary `s` never
deletes an entry; a duplicate found by a new `add` query is never added.

When several works match, choose a numbered candidate or `0` for none. A questioned
name offers `k` to keep the typed name or `u` to use the source's spelling. If name
lists cannot be paired, edit the entry yourself.

`e` opens a temporary BibTeX file in `$VISUAL`, then `$EDITOR` if `VISUAL` is unset,
or `vi` if neither is set. Save exactly one entry and exit. The tool checks the
saved text again and returns to the choices. A parse error reopens the editor;
an unchanged file or editor error returns to the choices. The temporary file is
removed afterwards.

Without a terminal, `add` prints proposals and `nothing was changed`; it writes
no entries and does not open an editor. Accepted additions in the managed library
share one command checkpoint, shown as `Batch backup: STAMP`. Each acceptance is
saved immediately. [Managed-library undo](#managed-library-updates) restores the
state before the command’s accepted changes, including after stopping or a later
lookup failure. The checkpoint survives backup retention while the command runs.
Your own clone is not backed up by the tool.

The web interface's Add view also searches by title, authors or both, reads a PDF,
and has a form for typing an entry by hand; see
[the add tutorial](docs/tutorials/adding-references.md), which also has a
[recorded example](docs/tutorials/adding-references.md#recorded-addedit-session).

## `verify`

You can run the `verify` command using:
```bash
cdlbib verify --fname <fname>
```
where `<fname>` is the name of the .bib file whose integrity you want to check (the default is `cdl.bib`).
For help, run:
```bash
cdlbib verify --help
```

Normal `verify` first offers the same review choices as `add` for new or changed
entries that lack required fields or have supported source corrections. An entry
whose exact current text already has an accepted verification result is not
proposed. Syntactically invalid BibTeX goes to the format check rather than a
completion proposal. Accepted changes are written before the ordinary checks run;
accepting a proposal does not bypass those checks. The proposal's displayed status
comes from its first check, while `verify` runs the full citation gate.

Use `--no-complete` to skip these offers. Without a terminal, proposals are shown
and the checks continue on the entries as typed. `--no-citations` skips completion
and runs only the offline format check. `--autofix` or `--outfile` also skips
completion so you can review the output copy before running normal `verify` on it.

After the completion step, `verify` runs three checks in order:
1. The **formatting check** described below, on every entry.
2. The **accuracy check** (`crossref verify --auto-review`) on the entries that are new or edited compared with the GitHub `master` version of `cdl.bib`. An entry whose only change is its key is not re-checked.
3. A **status line** summarizing how many entries in the whole library are verified.

It exits with `1` if the formatting check fails or any new or edited entry can't be verified, and prints each problem entry with its issues. It exits with `2` if the accuracy check can't run at all (for example, no contact address is set or a service is down). Useful options: `--no-citations` for an offline, formatting-only check; `--all` to check the accuracy of every entry, not just changed ones; `--reference other.bib` to compare against a different base file.

The formatting check verifies the following:
- Proper bibtex key naming:
  - Keys for single-author papers are named with the first four letters of the author's surname, plus the last two digits of the publication year (e.g., Mann21)
  - Keys for dual-author papers are named with the first four letters of the first author's surname, followed by the first four letters of the second author's surname, followed by the last two digits of the publication year (e.g., MannKaha21)
  - Keys for papers with three or more authors are named with the first four letters of the first author's surname, followed by "Etal", followed by the last two digits of the publication year (e.g. MannEtal21)
  - Surnames with fewer than four letters result in shorter keys (e.g. LeeEtal21)
  - Titles (e.g., Dr., Hon., etc.) and suffixes (e.g., Jr., Sr., II, III, etc.) are omitted from key names
  - Multi-word surnames (e.g., y Cajal, van der Meer, etc.) are concatenated into a single "word" without changing any capitalization, for the purposes of generating a key (e.g., yCaj05, vandEtal21, etc.)
  - An organization or group author (written fully in curly braces, e.g., `{{R Core Team}}`) counts as one author. Its part of the key uses the letters of successive words of the name until four letters are reached. A dotted abbreviation counts as the words it stands for (U.S. is "United States", U.K. is "United Kingdom"). For example, `{R Core Team}` gives RCor12 and `{U.S. Food and Drug Administration}` gives Unit20
  - All unicode characters are converted to their nearest ASCII counterparts (e.g., "é" is converted to "e", etc.)
  - In-press, submitted, under revision, or other "unpublished" manuscripts should use the last two digits of the *submission* year
  - Bibtex keys may not be duplicated.  If two or more entries share the same "base" bibtex key, they should be renamed to make each key unique by adding a suffix to the key: MannEtal21a, MannEtal21b, etc.  If a bibtex key requires a suffix, *all* bibtex keys that share the same base must also have suffixes.  Suffixes must be assigned in order (e.g., if MannEtal21a and MannEtal21c are in the .bib file, then either MannEtal21b must also be in the .bib file, or MannEtal21c must be renamed to MannEtal21b).  Likewise, a key that no longer shares its base with any other entry drops its suffix.
  - Every entry in `cdl.bib` follows these rules, with no exceptions.  When a correction changes an entry's authors or year, its key changes with it, and the rename is logged in [verification/key-renames.json](verification/key-renames.json) so that an old `\cite` key can be looked up.
- Proper formatting of author and editor names:
  - The name must appear in the following order with no commas: First Middle Surname(s) Suffixes
  - Multi-word surnames should be enclosed in curly braces (e.g., "{van der Meer}")
  - Latex accents (e.g. "\\'{e}" or "{\\' e}") are supported
  - Initials must be separated (e.g., "AA" becomes "A A")
  - Hyphenated initials and/or names should *not* be separated (e.g., "H-T" is correct as is)
  - For multi-author (or multi-editor) papers, names should be separated by the string " and " (note single spaces on either side)
- Detection of duplicate entries.  Entries are considered to be duplicates if they share the same author last names *and* the publications also share the same title.  Importantly, publication year, journal name, and other fields are *not* considered in detecting duplicates; this enables the duplicate checker to catch problems like a publication being entered for a preprint that is already in the database, rather than updating the existing entry.  Inspect proposed duplicate removals carefully.
- Page numbering must be properly formatted:
  - Articles with single pages should contain only one page number (e.g. "3--3" should be "3")
  - Page ranges are denoted using an n-dash with no spaces (e.g., "3--10")
  - The first page in the given range must be strictly smaller than the last page in the given range
  - For journals with page-number prefixes (e.g., "e2910"), the same prefix must be used for both the start and end of the page range, and the numbering must be valid (i.e., the first page must be strictly smaller than the last page)
  - Roman numerals are supported and subjected to the same constraints as integer pages.  They may be uppercase or lowercase, but may not be mixed case.
  - Article numbers and electronic locators that a journal prints instead of page numbers are kept as printed
  - Some types of errors may be autocorrected, although this must be treated with caution to ensure accuracy (e.g. "1002 - 15" may be autocorrected to "1002--1015")
- Journal names must be properly capitalized and written out in full (e.g., "J. Neurosci" becomes "The Journal of Neuroscience").
- Book titles must be properly capitalized and written out in full.
- Article titles must be capitalized in sentence case, including the first word after a colon (e.g., "Memory: the review", not "Memory: The review").  Proper nouns and acronyms are protected with curly braces (e.g., "{fMRI} of the {Stroop} task").  Titles may not be (fully) enclosed in curly braces and may not end in '.'.  The checker can't tell a proper noun from an ordinary word, and it doesn't catch a capital "A" after a colon ("Memory: A review" passes), so check titles against the source.
- Publisher names must be written out in full.
- Addresses must be formatted properly:
  - US states are abbreviated with their two-letter codes, in curly braces (e.g., "Cambridge, Massachusetts" and "Cambridge, Mass." both become "Cambridge, {MA}")
  - City names should be written out in full (e.g., "New York, {NY}", not "NY, NY").  The checker doesn't catch this one, or a spelled-out state it doesn't recognize, so please write these carefully.
  - The checker never adds a country the source doesn't print.  It does drop the country after some well-known cities (e.g., "Berlin, Germany" becomes "Berlin").
  - Abbreviations should not contain periods (".")
- Only the following fields are allowed (see [keep_fields.txt](src/cdlbib/data/keep_fields.txt)): author, title, year, journal, booktitle, volume, number, pages, doi, publisher, editor, edition, series, chapter, school, institution, organization, address, type, howpublished, and force
- To override autoformatting or checks for a given entry, add an additional field, "force", to that bibtex entry and set its value to "True".  Most formatting checks are skipped for that entry (duplicate detection and malformed page ranges are still checked).  This is useful if the above rules cannot be properly applied to a given entry.  `force` does **not** skip the accuracy check.  The library itself uses none: no entry in `cdl.bib` carries a `force` field.

If errors are found, they are printed to the terminal along with suggested corrections (if available).

***Danger zone***: `autofix`

The bibtex checker can attempt to automatically correct formatting issues using the `--autofix` and `--outfile` flags.  The `--verbose` flag is also strongly encouraged when the `--autofix` flag is used.  Autocorrect mode may be used as follows:
```bash
cdlbib verify --autofix --verbose --no-citations --outfile=cleaned.bib
```
This will create a new .bib file, cleaned.bib, based on cdl.bib-- but with all fields and entries autocorrected where possible.  After manually checking the new "autocorrected" .bib file, cdl.bib may be overwritten with `cleaned.bib`:
```bash
mv cleaned.bib cdl.bib
```

This mode can easily introduce errors if not checked (manually!) carefully.  It is included for convenience (e.g., to facilitate very large numbers of simple changes), but it should not normally be used.


## `compare`
You can run the `compare` command using:
```bash
cdlbib compare <fname1> <fname2>
```
where `<fname1>` is the name of the "original" .bib file and `<fname2>` is the
name of the "new" .bib file.  The `compare` function will run a check to
determine if there are any differences between fname2 and fname1.  For help, run:
```bash
cdlbib compare --help
```

Given two .bib files, any *differences* between the files are detected and printed.  Differences can include:
- New or deleted items
- Modified entries (e.g., new, deleted, or modified fields)

## `send`
You can run the `send` command using:
```bash
cdlbib send
```
For help, run:
```bash
cdlbib send --help
```

Sending requires the tracked `cdl.bib` in the selected library. Use `verify` or
`compare` to check a bibliography with another filename.

The `send` command runs the same checks as `verify` (formatting, plus the
accuracy of new and edited entries), and sends nothing if any of them fail.
It offers completion before those checks, using the same choices as `add`.
`cdlbib send --no-complete` skips the offers while keeping the full verify gate.
Any accepted completion is part of the bibliography that `send` checks and sends.
If the checks pass, the `compare` command is used to compare the local cdl.bib
file to the version stored in the `master` branch of the `ContextLab` fork.
The changes to `cdl.bib` and to files under `verification/` are then committed on
a new branch named `cdlbib/<your GitHub login>/<date>-<summary>`, with a commit
message describing what was added, removed, and changed. Other files with
uncommitted changes are neither committed nor pushed; they are left as they are, and
`send` lists them on a final line beginning `left uncommitted:`. Existing local
commits are also checked against the upstream pull request base. If any outgoing
commit includes another path, sending stops; deleting the file in a later commit
does not remove it from that history. Keep the original branch and prepare a
bibliography-only branch from the upstream base before trying again.

After selecting the send branch, the bibliography and evidence must still match
the checked files. A changed candidate stops the send. A summary `--outfile` must
be separate from the bibliography, reference, verification data and Git controls.

The branch is pushed to your own fork of the repository, and a pull request is
opened from it into the repository your checkout was cloned from (or into its
parent, if you cloned a fork). If you have no fork yet, `send` prints a notice
and creates one. Use `cdlbib --ask send` to be asked first. The pull request's
title is the `--summary` text when `--summary` is given, and otherwise the first
line of the change summary; either is cut to 100 characters. When it finishes, `send` prints the pull request's
address and leaves your checkout on the new branch; running `send` again from
that branch adds to the same pull request.

With `--ask`, the question about creating a fork is asked only at a terminal.
Without a terminal, or when the answer is no,
`send` prints the line below with your login and the repository's name, exits
with `1`, and sends nothing.

```
@LOGIN has no fork of OWNER/NAME. Create one with: gh repo fork OWNER/NAME --clone=false
```

## `web`

```bash
cdlbib web
```

`web` serves the library in use to a browser on this computer and opens the page.
It prints the address, which holds a token made for that run, and runs until it is
stopped with Ctrl-C:

```text
cdlbib web: /absolute/path/to/library/cdl.bib
open: http://127.0.0.1:8765/#token=<TOKEN>
This address works on this computer only, and until this command is stopped (Ctrl-C).
```

`--no-open` prints the address without opening a browser, and `--port` chooses the
port. The page has the views Library, Check, Review, Add, Send, Library state and
Setup. Files are uploaded in the browser (a PDF; a paper's `.tex`, `.aux` or `.bcf`
files); the page takes no file paths, and it does not make a `.bbl`.
[The web-interface tutorial](docs/tutorials/web-interface.md) describes each view.

![The Library view of the web interface: a search box, status filters, the list of entries, and the selected entry with its fields and BibTeX text](docs/media/web-library.png)

## `crossref`: citation verification

`cdlbib crossref` is the accuracy checker on its own, with more control than `verify` gives you. It never edits `cdl.bib`; it only reports. Run the relative-path examples below from the library folder printed by `cdlbib where`.

```bash
# Check new and edited entries (and retry any that hit a network error)
cdlbib crossref verify cdl.bib --auto-review

# Check the whole library, starting from the lab's saved results
cdlbib crossref restore verification/baseline.jsonl.gz
cdlbib crossref verify cdl.bib --auto-review

# Offline: how many entries are verified right now?
cdlbib crossref status cdl.bib

# Only the references in your manuscript (one citation key per line)
cdlbib crossref status cdl.bib --keys manuscript-keys.txt
```

`cdlbib crossref --help` lists the subcommands:

|Subcommand|What it does|
|-|-|
|`discover-review`|Try twenty title-search candidates; apply the existing strict source checks.|
|`auto-review`|Automatically review cached findings; batch PubMed lookups through Europe PMC.|
|`fulltext-review`|Review remaining entries using publisher front matter from open-access PMC XML.|
|`verify`|Verify new/modified entries; save every result so interrupted runs resume.|
|`status`|Offline check: recompute fingerprints and fail on every unresolved entry.|
|`snapshot`|Export a portable compressed JSONL audit snapshot for backup or sharing.|
|`restore`|Restore matching reviews from a trusted snapshot; changed entries stay pending.|
|`review-packet`|Export source evidence and exact fingerprint for PDF/LLM/human review.|
|`attach-evidence`|Attach optional external research findings; human review remains required.|
|`research`|Run optional LLM web search, download PDF, extract and check quoted evidence.|
|`research-batch`|Collect actual PDF evidence in a bounded, resumable batch; never human-approve.|
|`approve`|Record an explicit human decision, bound to the exact reviewed entry.|
|`revoke`|Withdraw a human approval: audited, bound to its fingerprint, never restored.|

### How an entry is checked

The checker first looks up the entry's DOI in Crossref. If there's no DOI, it searches Crossref by title and authors and compares the top candidates. A close title alone is never enough: to be verified, the entry's title, full author list (in order), year, and venue must match the source, and so must every other field the entry has (volume, issue, pages, publisher, DOI, and so on). If a DOI points to a different paper, the conflict is reported.

When Crossref can't settle an entry, the checker tries the other free sources in turn: PubMed records (through Europe PMC), the publisher's own front matter in open-access full text, library catalogues for books, preprint servers (arXiv, bioRxiv, PsyArXiv), DataCite for software and datasets, the ACL Anthology, and the Society for Neuroscience abstract archive (which can identify an abstract, though [abstracts themselves aren't kept](#what-belongs-in-cdlbib)). Each source is only trusted for what it actually records. For example, a preprint server's record can verify a preprint but not the journal version.

If a correction, erratum, retraction, or expression of concern is linked to an entry, the entry is flagged for review. A retraction or expression of concern keeps it flagged. A correction that couldn't be read can be accepted when Crossref and Europe PMC show no retraction; the result then records that the notice was not read.

### What the results mean

| Status | Meaning | Counts as verified? |
|-|-|-|
| `metadata_verified` | Every field agrees with a trusted source (automatically, or through the research evidence described below) | Yes |
| `human_verified` | A named person checked this exact entry against the source and recorded their approval | Yes |
| `needs_review` | Missing evidence, a disagreement with the source, ambiguity, or an unsupported field | No |
| `provider_error` | A network or service failure prevented the check; it is retried next time | No |
| `pending` | Not checked yet (e.g., the entry was just edited) | No |

`crossref verify` and `crossref status` exit with `0` when every selected entry is verified, `1` when some aren't, and `2` for a configuration, parsing, or network error. Add `--require-human` to `status` if you want to accept only `human_verified` entries.

### Saved results and automatic re-checking

Results are saved in `.bibcheck/verification.sqlite3` (a local, git-ignored file), so each entry is checked only once. Every entry has a fingerprint of its exact text (ignoring the key). Editing an entry in any way, even just its formatting, invalidates its result, and it is checked again next time. Renaming a key does not.

The lab's results for the whole library are shared in [verification/baseline.jsonl.gz](verification/baseline.jsonl.gz). `crossref restore` loads them into your local database; `crossref snapshot` writes a new one. A restored result applies only to an entry whose text is exactly the same.

### Automatic checks on pull requests

The `Citation verification` workflow runs on every pull request to `master`, and on every push to `master`. It takes the base branch's `cdl.bib` and its saved results, and checks every entry that is new or edited in the pull request. The check fails unless all of them are verified. Unchanged entries are not checked again. Saved approvals come only from the base branch (the workflow also reuses its own cache of earlier checks), so a pull request can't approve its own entries. That covers the approvals in `verification/approvals.jsonl` too: the workflow reads the base branch's copy of that file, not the pull request's. If a push to `master` rewrites history, so that there is no earlier commit to compare against, the workflow instead checks that every entry in the pushed `cdl.bib` has a verified result in the pushed `verification/baseline.jsonl.gz`. Running the workflow by hand from the Actions tab checks the whole library.

Both workflows use the public CI contact in [`.github/actions/crossref-contact/mailto.txt`](.github/actions/crossref-contact/mailto.txt). A repository Actions variable named `CROSSREF_MAILTO` overrides it when available. Fork pull requests can run without configuring a variable; the shared contact remains available when GitHub supplies an empty value. If you adapt this repository for another group, replace that address with your group's contact.

### Human review

Some entries can't be verified automatically: an old book with no online record, a scanned chapter, a record with an error you can see in the printed paper. If you have checked the entry against the actual source, you can record that:

```bash
# 1. Export the entry, its fingerprint, and what the checker found
cdlbib crossref review-packet CiteKey --output review-packet.json

# 2. After checking the source, record your approval
#    (the reviewer is recorded from the GitHub login of the gh CLI)
cdlbib crossref approve CiteKey \
  --fingerprint HASH_FROM_REVIEW_PACKET \
  --source 'URL or physical edition you checked' \
  --note 'Which fields you checked, and why the automatic check failed'
```

The approval is tied to the entry's exact text: if the entry is edited later, it has to be approved again. `approve` refuses a source longer than 4,000 characters, a note longer than 8,000, a review whose line in `verification/approvals.jsonl` would be longer than 32,768 bytes, or one that would take that file over 8,388,608 bytes, and says which; lines and files over those sizes are not read. An approval recorded in error can be withdrawn with `cdlbib crossref revoke CiteKey --reason 'Why'` (who revokes is recorded from the GitHub login of the `gh` CLI). The revocation is logged in `verification/revocations.jsonl` and the entry goes back to `needs_review`. Restoring an older snapshot can't bring the approval back, but a new `approve` with a new note can; `approve` refuses the revoked review again when its source and note are the same apart from spacing and capitals.

`cdlbib send` shares an approval. Before it decides whether there is anything to send, it appends one line to `verification/approvals.jsonl` for each current approval in your local database that was recorded under your own GitHub login (the login of the `gh` CLI, compared by its numeric id), has not been revoked, and is not in that file yet, and prints a line for each. An approval recorded under another login (one restored from a snapshot, for example) is not added; `send` prints `approval of KEY not sent: recorded under @login`, and refuses with those lines when nothing else is to be sent. The file is committed with the rest of the change, and the pull request's text names each approval and its reviewer. An approval is a change by itself: `send` goes ahead when nothing else has changed, and the Send views of the terminal and web interfaces list the approvals that will be sent. If the send stops before the commit is made, the lines are taken out of the file again and stay in your database for the next send; a send that is killed is settled the same way the next time a `cdlbib` command locks the library. If another program changed the file in the meantime, `send` does not write to it and says that it was not put back and which approvals it had added. `send` refuses when the file holds uncommitted lines that are not valid or were recorded under another login, or when a committed line was changed or removed.

Each line holds the entry's key and fingerprint, the review as it was recorded (reviewer, GitHub login and id, source, note), the time it was recorded, the checker's policy version, and a digest of the review. Lines are only ever appended. Anyone whose copy of the library has the line sees the entry as `human_verified`, with no command to run, as long as the entry's text still has that fingerprint, the line is valid (reviewer, source, note and GitHub login, with a digest that matches the review), and the approval has not been revoked. A line that is not valid is ignored and reported by `cdlbib crossref status` and in the Library state views. A revocation in `verification/revocations.jsonl` takes precedence over a line in `verification/approvals.jsonl`: a line that repeats a revoked review (the same source and note, however spaced, signed or dated) or is dated no later than the revocation approves nothing, and a new review with a new note recorded afterwards does.

The pull request check reads `verification/approvals.jsonl`, like the saved results, from `master` only. The checks that `cdlbib verify` and `cdlbib send` run on new and edited entries also read that file from the reference they compare with (GitHub's `master`), not from your working copy. A pull request that only adds approvals changes no entry, so the check has no entry to examine. A pull request that edits an entry and approves the new text still fails the check for that entry. Say so in the pull request; a maintainer who has checked your approval can merge it, and from then on the entry counts as verified.

### Research evidence

When the library was checked in September 2026, 1,221 entries that no automatic source could settle were verified from quoted evidence: each field was matched to a quotation from an official source (a publisher's page, a scanned table of contents, a library catalogue record, and so on). Each entry's saved result in [verification/baseline.jsonl.gz](verification/baseline.jsonl.gz) holds the quotation and source URL for every field, and `crossref restore` checks them again when it loads the results. These entries have status `metadata_verified` and count as verified like any other. The working records of that check are kept on the [CDL-bibliography-stacks](https://github.com/ContextLab/CDL-bibliography-stacks) archive repository.

There is also an optional tool that uses a language model to find a paper's PDF and quote the relevant passages (`crossref research` and `research-batch`). Its findings are evidence for a person to review; it never approves an entry by itself. See [docs/verification.md](docs/verification.md).

Both commands reach the language model through an adapter: an executable, named with `--adapter`, that reads one JSON request on its standard input and prints one JSON object. Two adapters are installed with the package as commands, `cdlbib-adapter-dartmouth` (Dartmouth Chat) and `cdlbib-adapter-openai` (OpenAI):

```bash
cdlbib crossref research CiteKey --adapter cdlbib-adapter-dartmouth --allow-host HOST
cdlbib crossref research-batch cdl.bib --adapter cdlbib-adapter-dartmouth --allow-host HOST
```

`--allow-host` gives an exact host that PDFs may be downloaded from; repeat it for redirects. `cdlbib-adapter-dartmouth --check-model` checks that the model is available. Each adapter needs its service's API key ([API keys](docs/tutorials/api-keys.md)); without one, `cdlbib-adapter-dartmouth --check-model` prints where to put the key and exits with `2`.

### Being polite to Crossref

Requests go out one at a time, with at least half a second between them (one second by default), and the checker backs off when a service asks it to. Responses are cached, so re-running a check doesn't repeat requests. Please don't run several checks at once from the same machine. See [Crossref's guidance for API users](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/).

More detail on how verification works, including every acceptance rule, is in [docs/verification.md](docs/verification.md).

# Using the bibtex file as a common bibliography for all *local* LaTeX files

The library download is automatic, and `cdlbib setup` connects the library to TeX.
Install TeX separately. The manual methods after it do the same by hand.

All of these methods make the bibliography available across projects for your user
account. They do not need administrator access or another clone. LaTeX compilation
does not run `cdlbib` or check for library updates; use `cdlbib update` when you want
the latest shared version.

## Automated setup: `cdlbib setup`

```bash
cdlbib setup
```

`setup` makes one symbolic link, `bibtex/bib/cdl.bib` in your personal TeX tree
(the folder `kpsewhich -var-value=TEXMFHOME` prints), that points to the `cdl.bib`
of the library in use. It then prints a report: the library, the TeX tree, the
link, what `kpsewhich cdl.bib` resolves to, and what `cdlbib` can use on the
computer (Git, the GitHub login, TeX, BibTeX, biber, optional packages and API
keys). When the link works, the report has this line:

```text
state: linked: TeX finds this library's cdl.bib from any folder (\bibliography{cdl} or \addbibresource{cdl.bib})
```

The link names the file's path, so it follows the library through updates.

- `cdlbib setup --check` prints the report and changes nothing in the TeX tree. As
  with every command, the library `cdlbib` manages is downloaded or updated first when it
  is the one in use. It exits with `1` when `cdl.bib` is not linked.
- `cdlbib setup --remove` removes the link that `cdlbib` made.
- `cdlbib setup --replace` is for a `cdl.bib` in the TeX tree that `cdlbib` did not
  put there: without it `setup` leaves that file alone and exits with `1`; with it,
  the file is moved aside to `cdl.bib.cdlbib-saved-<time>` in the same folder and
  the link is made.
- `cdlbib --ask setup` asks before making the link.

When there is no link, the report also prints an `export BIBINPUTS=...` line for
your shell that does the same; `cdlbib` does not write that line to any file.
The Setup view of the web interface shows the same report and makes or removes
the link. [The setup tutorial](docs/tutorials/latex-setup-and-export.md) shows
the output of each case.

## Manual methods

For the methods below, run `cdlbib where` and use the **library-folder path it
prints** as the library path. Do not capture the entire output as a path: it also
contains status lines. If you change `CDLBIB_HOME` or switch libraries later,
update your TeX configuration to match.

## General Unix/Linux Setup (Command Line Compilation)

Add a line like this to the startup file your shell reads (for example `~/.zshrc`
or `~/.bashrc`), replacing the example folder with the one from `cdlbib where`:

```bash
export BIBINPUTS=".:/absolute/path/to/library:${BIBINPUTS}:"
```

The leading `.` checks the manuscript folder first, the quotes preserve spaces,
and the trailing colon retains TeX's default search locations. Open a new terminal
or source the startup file you edited.
From your manuscript folder, check which file TeX finds:

```bash
kpsewhich cdl.bib
```

It should resolve to the intended library. A `cdl.bib` already in the manuscript
folder takes precedence with this setting; keep it there only when you want that
frozen copy.
See the [Kpathsea manual](https://www.tug.org/texinfohtml/kpathsea.html) for TeX's
search-path rules.

For a BibTeX manuscript, select its bibliography style and the shared library:

```latex
\bibliographystyle{plain} % or the style required by your venue
\bibliography{cdl}
```

Compile with your usual toolchain; a basic BibTeX example is:

```bash
pdflatex filename
bibtex filename
pdflatex filename
pdflatex filename
```

For a `biblatex` manuscript, use its `\addbibresource{cdl.bib}` configuration and
its chosen backend instead of mixing it with the BibTeX example above.

## MacOS Setup with TeXShop and TeX Live

GUI editors may not inherit shell variables. With TeX Live, link the selected
bibliography into the personal TeX tree instead. `cdlbib setup` makes this link;
the commands below make it by hand. `kpsewhich` reports the location
used by your TeX installation; it need not be the same on every Mac.

Run these commands in Terminal after replacing the example library path with the
absolute folder printed by `cdlbib where`:

```bash
cdlbib_library="/absolute/path/to/library"
cdlbib_texmf="$(kpsewhich -var-value=TEXMFHOME)"
mkdir -p "$cdlbib_texmf/bibtex/bib"
ln -s "$cdlbib_library/cdl.bib" "$cdlbib_texmf/bibtex/bib/cdl.bib"
kpsewhich cdl.bib
```

If the destination already exists, inspect it before changing it; the command
above does not replace an existing file or link. The final command should locate
the linked bibliography. Use `\bibliography{cdl}` with your manuscript's BibTeX
style, or its `biblatex` configuration. The link follows library updates without
copying the file. This method also works with command-line TeX Live on Linux;
`BIBINPUTS` is unnecessary when the personal-tree link resolves correctly.

# Using the bibtex file on Overleaf
Overleaf projects [can't contain git submodules](https://docs.overleaf.com/integrations-and-add-ons/git-integration-and-github-synchronization/github-synchronization), so (unlike what earlier versions of this readme suggested) you can't add this repository to an Overleaf project as a submodule.  Instead, either:
- Upload `cdl.bib` to your project, or
- Use Overleaf's [Add from External URL](https://docs.overleaf.com/managing-projects-and-files/adding-files-to-a-project/adding-a-file-from-a-url) option with the [raw bibliography](https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/cdl.bib).  The linked file is updated only when you refresh it, so refresh it when you want the latest version (and check the resulting citations).

Either way, change the `\bibliography{...}` line in your .tex file to `\bibliography{cdl}`.

# Using the bibtex file as a submodule of a paper's repository
As an alternative to the managed-library setup, if you write your paper in a Git
repository of your own (outside Overleaf), you can use a [git submodule](https://github.blog/2016-02-01-working-with-submodules/) to keep a reference to this repository that you can easily keep in sync with the latest version:
1. Navigate to your paper's repository (in Terminal) and then run
```
git submodule add https://github.com/ContextLab/CDL-bibliography.git
```
2. Inside your .tex source file, change the `\bibliography{cdl}` line to `\bibliography{CDL-bibliography/cdl}`.
3. Commit your changes (`git commit -a -m "added CDL bibliography as a submodule"`) and then push them (`git push`).
4. To pull the latest changes from the CDL-bibliography repository, run `git submodule update --remote CDL-bibliography` inside your paper's repository, then commit the updated submodule.
5. When you clone a fresh repository that includes this repository (or others) as a submodule, run the following commands to download the contents of the submodule repositories:
```
git submodule init
git submodule update
```

# Frozen manuscript copies and exports

Keep a bibliography snapshot with each submitted manuscript so later library
updates do not alter its references. Review the rendered bibliography using the
manuscript's actual style.

`cdlbib export` writes that snapshot. Name the paper by its folder, its main `.tex`
file, or a `.aux` or `.bcf` file:

```bash
cdlbib export /absolute/path/to/paper
```

```text
citations read from a fresh LaTeX run of the paper: 2 keys
wrote /absolute/path/to/paper/cdl.bib: 2 entries from /absolute/path/to/library/cdl.bib
```

The output is a `.bib` that holds just the entries the paper cites, as the library
has them. It is written as `cdl.bib` beside the paper unless `--out FILE` names
another file, and an existing file is replaced only with `--force`. When a folder
holds several main files, name one with `--main`. A cited key that is not in the
library is listed, and the command exits with `1`.

With `--bbl`, the command compiles the paper's `.bbl` instead. It runs LaTeX and
then BibTeX or biber, whichever the paper uses, on a temporary copy of the paper's
files:

```bash
cdlbib export /absolute/path/to/paper --bbl
```

```text
wrote /absolute/path/to/paper/main.bbl: bibtex, style plain, pdflatex, 2 cited keys
```

- `--inputs PATH` names a style or class file the paper needs, or a folder of them.
  Repeat it for several. Styles in your personal TeX tree are found without it.
- `--engine` chooses `pdflatex`, `xelatex`, `lualatex` or `latex`. Without it, the
  program the paper asks for is used, otherwise `pdflatex`.
- A missing input is named and no style is chosen in its place, for example
  `BibTeX could not find: labstyle.bst. Supply the file, or the folder that holds it, as an input (--inputs PATH).`
- A paper that asks for LuaLaTeX is compiled only with `--engine lualatex`, and a
  `biblatex` source map that contains code is refused.

The web interface's Setup view makes the `.bib` from uploaded `.tex`, `.aux` or
`.bcf` files; it does not make a `.bbl`.
[The export tutorial](docs/tutorials/latex-setup-and-export.md#export-the-cited-entries-as-a-bib)
shows each message. Your usual TeX build also generates a `.bbl`, and copying the
library's `cdl.bib` into the manuscript folder (or pinning the optional submodule
to a commit) also keeps a snapshot.

# Using it from Python

The functions behind the commands are in the module `cdlbib.api`. They return result objects and raise subclasses of `cdlbib.errors.CdlbibError`. They do not print or prompt. `api.status` writes `.bibcheck/verification.sqlite3` and `.bibcheck/report.jsonl` in the library folder.

```python
from cdlbib import api

ws = api.ensure_library()  # existing selection/checkout, otherwise download the managed library
print(api.check_format(ws).errors)
status = api.status(ws)
print(status.counts, status.ok)
```

For a specific library, construct `workspace.Workspace("/absolute/path/to/library")`
after importing `workspace` from `cdlbib`. Front ends use the shared API for
updates, proposals and decisions rather than parsing CLI output. `ensure_library`
selects/downloads a workspace; long-running clients must also handle update
results and decisions through `api.update`.

In a clone where `cdlbib crossref restore verification/baseline.jsonl.gz` had been run, this printed (October 2, 2026):

```
[]
{'metadata_verified': 6348, 'human_verified': 36} True
```

Before the restore, the second line was `{'pending': 6384} False`.

# Running the tests

From a development checkout, install the package and test tools:
```bash
python -m pip install ".[research,pdf,tui]" pytest uv playwright
python -m playwright install chromium
export CROSSREF_MAILTO='your.name@dartmouth.edu'
python -m pytest -q -rs tests
cdlbib verify --no-citations
```

The tests of `cdlbib setup`, `cdlbib export` and PDF intake run the real programs:
`kpsewhich`, `pdflatex`, `xelatex`, `lualatex`, `bibtex` and `biber` from a TeX
installation, Ghostscript (`gs`), `pdftoppm` and `tesseract`. The browser tests of
the web interface use Playwright's Chromium. A test whose program is not installed
is skipped, and the skip names the program. CI installs these programs
([autocheck.yml](.github/workflows/autocheck.yml)). The tests in
`tests/test_texinstall.py` that install biber and BibTeX for real download a TeX Live
(TinyTeX) and biber, about 140 MB, into pytest's temporary folder, and run only with
`CDLBIB_TEST_TEX_INSTALL=1`.

Almost all tests use saved copies of real source records, so they run offline. Tests in `tests/test_machinery_2026_09_25.py`, `tests/test_api.py` and `tests/test_publish.py` check new entries against the live Crossref API, so they need `CROSSREF_MAILTO` and a network connection, and can fail temporarily if Crossref is down. Without `CROSSREF_MAILTO` (or a local `.bibcheck` cache that recorded a contact address), they fail with a message saying to set it. Tests in `tests/test_identity.py`, `tests/test_revoke_ledger.py` and `tests/test_publish.py` that need a GitHub login are skipped when `gh` is not installed or not logged in. The tests in `tests/test_publish.py` that open a pull request do so only inside your own fork of this repository, on its `cdlbib-test-base` branch, and are skipped when you have no fork. Tests that fetch evidence pages save them in a temporary directory (the suite sets `BIBCHECK_RESEARCH_BODIES`), never in your `.bibcheck/` cache. The tests in `tests/test_pdf_evidence.py` that read PDFs from a local paper library are skipped when it isn't available. `cdlbib verify --no-citations` runs the formatting check on `cdl.bib`.

The CI workflows use a shared checked-in Crossref contact default, with an optional
repository variable override, so fork PRs can run the checks. Local users should
set their own `CROSSREF_MAILTO`. Skips are reported explicitly for unavailable
credentials, Keychain access, local PDFs and opt-in GUI checks.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add a citation, and [docs/verification.md](docs/verification.md) for how verification works.

# Acknowledgements
This bibtex file is built on a large bibtex file authored by Michael Kahana's
[Computational Memory Lab at the University of Pennsylvania](https://memory.psych.upenn.edu/).
However, this version is not kept in sync with the CML's version.  [Several members](https://github.com/ContextLab/CDL-bibliography/graphs/contributors) of the [Contextual Dynamics Lab](https://www.context-lab.com/) have contributed to the current version.

This repository is provided as a courtesy, and we make no claims with respect to accuracy, completeness, etc.
