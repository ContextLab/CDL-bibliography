# Add references

How to add a reference to the library: from an identifier, from a search by title and
author, from a PDF, or typed by hand. The [README](../../README.md#add) describes the
`add` command; `cdlbib add --help` lists its options.

- [Before you start](#before-you-start)
- [From a DOI, PMID or arXiv identifier](#from-a-doi-pmid-or-arxiv-identifier)
- [From a title and authors](#from-a-title-and-authors)
- [From a PDF](#from-a-pdf)
- [Reading a PDF with a language model](#reading-a-pdf-with-a-language-model)
- [Typing an entry by hand](#typing-an-entry-by-hand)
- [Which kinds of entry are built](#which-kinds-of-entry-are-built)
- [Recorded add/edit session](#recorded-addedit-session)

|Way to add|Command line|Web interface (`cdlbib web`, **Add** view)|
|-|-|-|
|DOI, PMID or arXiv identifier|`cdlbib add IDENTIFIER`|"Identifiers" tab|
|A book, by ISBN or LCCN|`cdlbib add "ISBN 9780195333244"`, `cdlbib add "LCCN 2012007685"`|"Identifiers" tab|
|A book, by title and first author|`cdlbib add --book "TITLE" --author NAME [--year YEAR]`|"Search" tab (catalogue records are among the leads)|
|Title, with author and year|`cdlbib add "TITLE" --author NAME --year YEAR`|"Search" tab|
|Authors without a title|not available|"Search" tab|
|PDF|not available|"PDF" tab|
|Typed by hand|edit `cdl.bib` (see [Modify references](modifying-references.md))|"Manual" tab|

Except where a section says otherwise, the output shown was recorded with `cdlbib 2.0.0`
on October 5, 2026, in temporary copies of the library chosen with `--library`. Counts and
candidates will differ when you run the commands.

In [the terminal interface](terminal-interface.md) (`cdlbib tui`), press `F4` for the Add
view. It has the same four tabs as the web interface: Search, Identifier, PDF and Manual.
`esc`, then `left` or `right`, then `enter` changes tabs. Each tab ends in a proposal:
`a` accepts it, `e` edits it, `s` skips it, `A` accepts it and the remaining ones that
need no decision, and `q` stops.

## Before you start

After [installation](../../README.md#installation), set your contact address. The lookup
services ask for one:

```bash
export CROSSREF_MAILTO='you@example.org'
```

Set it in the same terminal before starting `cdlbib web` as well; the web interface has
no box for it.

Nothing is written to the library until you accept a proposal. Accepting a proposal
writes BibTeX. It does not record a human approval and it does not send a pull request.

## From a DOI, PMID or arXiv identifier

### Command line

```bash
cdlbib add 10.1002/tea.3660271011
cdlbib add PMID:13896567
cdlbib add arXiv:2208.02957
```

The command proposes Zoller’s 1990 journal article. If it is already in your
library, the duplicate message gives its key and another copy is not added.
In a library without it, review the fields, sources and verification result before
answering `a`. Use `e` to edit first, `s` to skip, or `q` to stop. A capital `A`
accepts remaining complete proposals that need no decision.

For a duplicate already typed into the library, choose `r` to remove that typed
entry or `k` to keep both for the formatter. In the managed library, accepted
changes in one command share the printed `Batch backup` checkpoint;
`cdlbib update --undo` restores the state before those changes.

In a library that already holds the article, the display includes:

```text
Duplicate: Zoll90
Verification: metadata_verified
This work is already in the library or batch as Zoll90
```

### Web interface

Open the **Add** view and its "Identifiers" tab. Type DOIs, PMIDs or arXiv identifiers,
one per line, and press "Look up". Each proposal appears under "Proposals" as a card with
the typed and proposed entries, a table of fields with the source of each, the
verification outcome, and the buttons "Accept", "Edit" and "Skip". "Accept all remaining"
is above the cards.

![The Add view of the web interface with one proposal card for Zoll90: "source: crossref", "Verification: metadata verified", the typed entry "(no typed entry)" beside the proposed @article, a table of fields in which every field but the DOI was filled from crossref, and the buttons Accept, Edit and Skip](../media/web-add-identifier.png)

The page says under "Proposals":

```text
Nothing is written until a proposal is accepted. An accepted entry is still subject to the checks before a send.
```

## From a title and authors

### Command line

Give the title as the query, with `--author` and, optionally, `--year`:

```bash
cdlbib add "Matplotlib: A 2D graphics environment" --author Hunter --year 2007
```

When one record matches, the display includes a line that says so:

```text
One record matches the title, the first author and the year: 10.1109/mcse.2007.55.
```

When several works match, the command lists numbered candidates; choose one, or `0` for
none. `cdlbib add` needs a query: with `--author` alone it stops with

```text
Invalid value: Provide a query, --from FILE, or BibTeX on standard input
```

### Web interface

The "Search" tab of the **Add** view has three boxes: "Title (or part of it)", "Authors
(separate several with ;)" and "Year (optional)". A search may give authors without a
title. "Search" lists the candidates from Crossref, PubMed and arXiv. A search for the
authors `Polyn; Kahana` and the year `2009` listed ten candidates, beginning:

```text
Candidates (10)
Sean M. Polyn; Kenneth A. Norman; Michael J. Kahana 2009: Task context and organization in free recall · Neuropsychologia · 10.1016/j.neuropsychologia.2009.02.013 crossref, pubmed in the library as PolyEtal09 Use this one
Sean M. Polyn; Kenneth A. Norman; Michael J. Kahana 2009: A context maintenance and retrieval model of organizational processes in free recall. · Psychological Review · 10.1037/a0014420 crossref, pubmed Use this one
```

Each line names the sources that returned the record, and says "in the library as KEY"
when the work is already there. "Use this one" looks the chosen record up and adds its
proposal card under "Proposals". A candidate is not an entry until its proposal is
accepted. After "Accept", the page lists the key that was written and where the file as it
was before is kept:

```text
Added: PolyEtal09
The file as it was: ~/demo/small/.bibcheck/edits/20261005T101035.833350Z-cdl.bib
```

(`~/demo` stands for the temporary folder used for the recording.)

## From a PDF

The command line has no option for a PDF. In the web interface, open the "PDF" tab of the
**Add** view and choose a PDF from this computer (up to 50 MB). The file is uploaded to
the `cdlbib web` program running on the same computer. The page then shows the PDF, or in
a browser that does not display PDFs its first page as an image, beside what was read
from it: the title, where the title was read from, the number of pages read, and any DOI,
arXiv identifier or PMID with the page and the text it was read from.

![The PDF tab of the Add view after choosing doi.pdf: the first page of the PDF as an image on the left; on the right "What was read from doi.pdf" with the title, "largest text on page 1", 2 pages read and a DOI read from page 1, the buttons "Look up the source record" and "Type it in by hand", the note "A source record was found by the doi read from the PDF", and the "Read with a language model" panel](../media/web-add-pdf.png)

"Look up the source record" searches by the identifiers read from the PDF, then by the
title. A record that is found becomes a proposal card, as for an identifier. For a PDF
that no source knows, the page says:

```text
No source record was found for this PDF. It can be read with a language model, or typed in by hand.
```

"Type it in by hand" opens the "Manual" tab with the fields read from the PDF filled in.

Reading a PDF needs the `pypdf` package, and showing the first page as an image needs
`pypdfium2`. When they are missing, they are installed when the first PDF is read, and
the "Lookup log" says:

```text
installing pypdf (needed for: Reading PDF files) ...
```

After `cdlbib --ask web`, the page asks first ("Reading PDF files needs 'pypdf'. Install
it now?"). After "Cancel" nothing is installed and the page shows:

```text
Reading PDF files needs the package 'pypdf' (install: pip install 'pypdf<7,>=6.0')
```

## Reading a PDF with a language model

Under "Read with a language model", the "PDF" tab has one card for each model service:
Dartmouth Chat, which is marked "default", and OpenAI. The panel says:

```text
A model's reading is a proposal with page quotations; it is not a verification or an approval.
```

Each card has a "Read with ..." button and a tag that says "set up", "not set up" or "not
checked". The card of a service that is not set up, or not checked, also gives the steps to
set it up. "not checked" means that the environment
variable is not set and the system keychain has not been read; the "check" button reads
the keychain. The button of a service that is not set up cannot be pressed.
[API keys](api-keys.md) describes how to set up each service.

`cdlbib` treats an entry read by a model as it treats an entry typed by hand: the entry
has no source record, and it stays unverified until a source confirms it or a logged-in
person approves it. The next section shows the card of an entry typed by hand.

With Dartmouth Chat set up, "Read with Dartmouth Chat" adds lines to the lookup log while
the model reads, and then a proposal card beside the PDF's first page. Recorded on
October 5, 2026 with the PDF of arXiv:2310.06825, uploaded as `real.pdf`; the reading took
about three minutes. The log names the file as it was uploaded:

```text
Asking Dartmouth Chat to read 2 pages of real.pdf
Checking each quotation against the PDF's pages
```

The card is marked "model reading: evidence, not an approval" and "needs your decision".
Its table gives, for each field the model read, the page and the text quoted from it:

```text
title	Mistral 7{B}	model reading, p.1: "Mistral 7B"	filled
year	2023	model reading, p.1: "arXiv:2310.06825v1 [cs.CL] 10 Oct 2023"	question
```

The year is a question because the quoted text is an arXiv version stamp. The card listed
`journal`, `pages` and `volume` under "Unfilled" as "not given", and said:

```text
Accept is not available:
journal is missing (required for an entry of type article)
year is still a question: choose between what was typed and what the source has
```

The first reading after the model has been idle can take longer: `cdlbib` waits up to 240
seconds for an answer and, if none came, asks once more.

## Typing an entry by hand

The "Manual" tab of the **Add** view has a list of entry types and a box for each of the
fields `title`, `author`, `year`, `journal`, `booktitle`, `volume`, `number`, `pages`,
`publisher`, `doi`, `isbn`, `issn` and `edition`. "Add this field" adds a box for another
field. "Draft the entry" writes the typed fields in the house format and shows the
proposal card.

For an article typed with the authors `Ada Q. Example and Bo R. Sample`, the card read:

```text
Entry: ExamSamp19
typed by hand: no source record
needs your decision
Verification: needs review
No source record: these fields were not confirmed by Crossref, PubMed or arXiv. The entry stays unverified until a source confirms it or a logged-in person approves it.
author: written in house format (Ada Q. Example and Bo R. Sample -> Ada Q Example and Bo R Sample)
```

"Accept" writes the entry to the library. After that, `cdlbib crossref status` counts the
entry as `pending`, which is not a verified status. With the key `ExamSamp19` on a line
of `keys.txt`, run from the library folder:

```bash
cdlbib crossref status cdl.bib --keys keys.txt
```

```text
1 entries: pending=1
```

`cdlbib verify` and `cdlbib send` check a new entry before it can be sent
([Check the library](checking.md)). An entry that no source confirms can be approved by
a person who has checked it against the source ([Human review](human-review.md)).

## Which kinds of entry are built

`cdlbib` builds journal articles, arXiv preprints, papers in conference proceedings and
book chapters from their source records, and books from their Library of Congress
catalogue records. It does not build theses, reports, software or datasets; the
[README](../../README.md#add) has the full statement. The output in the two subsections
on books and on a chapter's book title was recorded on October 6, 2026.

A paper in conference proceedings, added to a library without it:

```bash
cdlbib add 10.18653/v1/N19-1423
```

The session ended:

```text
pages: None -> 4171--4186 (source: acl-anthology)
title: None -> {BERT}: pre-training of deep bidirectional transformers for language understanding (source: crossref)
year: None -> 2019 (source: crossref)
Verification: metadata_verified
[a] accept   [e] edit   [s] skip   [A] accept all remaining   [q] stop
Your choice [a/e/s/A/q]: a
Added: DevlEtal19
```

This is a paper of the ACL Anthology, so its pages are read from the Anthology's own
record (`source: acl-anthology`), which the citation check reads too. If the Anthology
cannot be read, the pages Crossref gives are proposed as a question to decide.

The entry written to `cdl.bib`:

```bibtex
@inproceedings{DevlEtal19,
	Author = {J Devlin and M-W Chang and K Lee and K Toutanova},
	Booktitle = {Proceedings of the Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, Volume 1 (Long and Short Papers)},
	Doi = {10.18653/v1/N19-1423},
	Pages = {4171--4186},
	Title = {{BERT}: pre-training of deep bidirectional transformers for language understanding},
	Year = {2019}}
```

A book chapter:

```bash
cdlbib add 10.1007/978-3-319-10590-1_53
```

This chapter's record names two titles for the place it appeared in: the series
("Lecture Notes in Computer Science") and the book. The tool looks up the book's own
record and writes the title that record gives the book. The proposal says where the title
came from, and lists the fields that no source record filled, with the reason for each:

```text
booktitle: None -> Computer Vision -- {ECCV} 2014 (source: crossref (the book's own Crossref record))
Unfilled editor: editor: no source record states it
Unfilled address: address: no source record states it
Verification: metadata_verified
booktitle: the record names two titles, "Lecture Notes in Computer Science" and "Computer Vision – ECCV 2014"; "Computer Vision – ECCV 2014" is taken as the book's. The book's own Crossref record (10.1007/978-3-319-10590-1, ISBN 9783319105895) has the title "Computer Vision – ECCV 2014" and names "Lecture Notes in Computer Science" as its series.
```

The acronym keeps its capitals, in braces. Press `e` to correct a value in your editor;
the edited entry is checked again before you can accept it.

When no record of the book settles which title is the book's, the book title is left
unfilled and the reason is given, for example:

```text
Unfilled booktitle: booktitle: no single registry title: no record of the book says which is its title; no model route is set up, so no model was asked. To have a model read the publisher's page for it, set up a model route (`cdlbib setup` lists them; Dartmouth Chat is the default) and run the lookup again.
```

A chapter needs its book's title. Answering `a` before the title is filled in prints:

```text
Cannot accept: complete required fields and resolve duplicate or unsupported entries first.
```

With a model route set up, the command first prints a line that says a model is being
asked (one request, which can take a few minutes), or, with `cdlbib --ask add ...`, asks
you first. The model may only pick one of the record's two titles, from a line of the
publisher's page that it quotes. The proposal then shows the source as
`crossref (model-assisted choice)` with the quoted line and the page's address, and waits
for your decision. It is not a verification.

### A book

```bash
cdlbib add "ISBN 9780195333244"
```

The proposal is built from the book's Library of Congress record, and every field names
that source:

```text
Proposed:
@book{Kaha12,
	Address = {New York, {NY}},
	Author = {M J Kahana},
	Publisher = {Oxford University Press},
	Title = {Foundations of human memory},
	Year = {2012}}
address: None -> New York, {NY} (source: loc-catalogue)
author: None -> M J Kahana (source: loc-catalogue)
publisher: None -> Oxford University Press (source: loc-catalogue)
title: None -> Foundations of human memory (source: loc-catalogue)
year: None -> 2012 (source: loc-catalogue)
Verification: metadata_verified
Built from the Library of Congress catalogue record LCCN 2012007685 (ISBN 9780195333244, 0195333241).
```

`cdlbib add "LCCN 2012007685"` gives the same proposal. By title, name the first author
(or the first editor) as well:

```bash
cdlbib add --book "Numerical optimization" --author Nocedal
```

The catalogue has two editions of this book, so nothing is proposed until you choose one:

```text
Verification: not checked
2 catalogue records match the title and the first author: editions are distinct works, and one has to be chosen.
```

At a terminal the two records are listed with their year, publisher, edition and LCCN.
Adding `--year 2006` builds the second edition, because one record has that year. In the
web and terminal interfaces, type `ISBN 9780195333244` or `LCCN:2012007685` in the
Identifier tab; a search by title and author in the Search tab lists catalogue records
among the leads, with `loc-catalogue` as their source.

A book whose catalogue record the accuracy check cannot read gives no entry, and the
message says why; enter it by hand ([Typing an entry by hand](#typing-an-entry-by-hand)).

For the DOI of a book, nothing is proposed (use its ISBN or LCCN instead):

```bash
cdlbib add 10.1093/acprof:oso/9780195140132.001.0001
```

```text
Unsupported: monograph
Verification: not checked
A record of type monograph is not built automatically; the entry is left as typed
nothing was changed
```

The last line is printed because the command was run without a terminal. The command
exits with `1`.

## Recorded add/edit session

This section was recorded on October 2, 2026.

The recording uses an empty scratch library and saved source responses. The entry
is verified against those records, edited to omit the optional issue number,
checked again, then accepted:

```text
Verification: metadata_verified
[a] accept   [e] edit   [s] skip   [A] accept all remaining   [q] stop
Your choice [a/e/s/A/q]: e
Saved entry.bib with the optional issue number omitted.
```

After the edit, the field display includes:

```text
number: 10 -> None (source: user edit)
Unfilled number: Removed in editor
Verification: metadata_verified
[a] accept   [e] edit   [s] skip   [A] accept all remaining   [q] stop
Your choice [a/e/s/A/q]: a
Added: Zoll90
```

The [full terminal transcript](../media/add-session.txt) includes both entry displays
and the retained sources of the unchanged fields.

![Recorded cdlbib add session: review, edit, recheck and accept Zoll90](../media/add.gif)

To regenerate this recording from a development checkout, run
`.venv/bin/python scripts/record_add.py --output-dir docs/media`. The recorder
creates an isolated library and cache from the saved responses.

See [the README](../../README.md#add) for input forms, editor settings, supported
types, name questions and key renames. Accepting an entry writes the bibliography;
run `cdlbib verify` afterwards, then `cdlbib send` when ready to contribute it.
