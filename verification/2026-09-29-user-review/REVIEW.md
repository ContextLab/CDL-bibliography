# Entries awaiting your review (2026-09-29)

Nothing here needs you to re-approve work you already did. Each item below is a decision only you can make.

- **12 approvals revoked.** The 2026-09-29 attribution audit found approvals recorded under your name for text you never saw as applied. On eleven of them your research-pilot verdict was "wrong" and you asked for a fix. Palm78's approval rested on a "keep unchanged" decision you never made. You chose "Revoke, I'll review (Recommended)" (AskUserQuestion, 2026-09-29 17:51 EDT). `crossref revoke` withdrew each approval and logged who, when and why in [verification/revocations.jsonl](../revocations.jsonl), so restoring an older baseline cannot bring them back.
- **5 approvals lapsed** in the braces batch ([apply-2026-09-29-braces/REVIEW.md](../apply-2026-09-29-braces/REVIEW.md)): Bart32, KahaEtal24, MikoEtal13b, Mink15 and Youn61. MikoEtal13b and Mink15 are also among the revoked twelve, so each is counted once.

Before the revocation, every automated route was tried on the twelve: Crossref and the `--auto-review` layers, `discover-review`, and `research-approve`. Only the research route, which checks field-by-field quotations from official records, verified any of them. It verified 8: Palm78, MikoEtal13b, vanEEtal18, AndeEtal66, PuceEtal99, BiswEtal95, ParaEtal04, Jame90. They are now `metadata_verified` and need no approval ([research-approve.json](research-approve.json)). Palm78 is one of them, but it still has an open DOI question for you.

**8 entries follow**: Palm78, ScotEtal07, Mink15, KahaMill13, Hook69, Bart32, KahaEtal24, Youn61. For each entry you get the current text, what you said and when (verbatim from the page database or the session record), what was applied and its evidence, a review packet, and an `approve` command with the current fingerprint. Before you run the command, write what you actually checked into the note. Any later edit to the entry reopens it. At the end, a table shows the seven route-verified entries against what you said about them.

Times are EDT (UTC-4), converted from the records' UTC timestamps.

## Palm78

Status now: `metadata_verified` (revoked approval). Fingerprint `v2:c2cb1560ba3267d42b4af49e7c6a285368e2ecd97a7c3d7a20c69aed034882d1`.

Entry now:

```bibtex
@incollection{Palm78,
	Address = {Hillsdale, {NJ}},
	Author = {S E Palmer},
	Booktitle = {Cognition and Categorization},
	Editor = {E Rosch and B B Lloyd},
	Pages = {259--303},
	Publisher = {Erlbaum},
	Title = {Fundamental aspects of cognitive representation},
	Year = {1978}}
```

What you said:

- Research-pilot page, 2026-09-25 00:06 EDT (2026-09-25T04:06:47.518Z), row `Palm78`: verdict "wrong", note "again, add DOI".
- Message, 2026-09-25 00:08 EDT (04:08:13Z): "for the already correct group: they all need DOIs for the published articles (peer reviewed versions as available) / (all papers need DOI fields when available)".
- AskUserQuestion answer, 2026-09-25 13:49 EDT (17:49:37Z). Question: "About 40 entries you already marked Correct on the pilot page (or whose fixes you approved) can't be verified by any automated source [...] Record your verdicts as signed-off human approvals (named reviewer: you, bound to each entry's exact current text)?" Answer: "Yes, record my sign-off (Recommended)". The approval recorded after this answer is the one revoked.
- You never said to keep Palm78 unchanged. "Keep unchanged" was an instruction the orchestrator gave an agent (2026-09-25 11:10 EDT); it was not your decision.

What was applied:

- Nothing. The entry is unchanged since the pilot.
- Researcher's note (research-pilot followup.json): No DOI exists for the cited 1978 Erlbaum edition. The only DOI is the Routledge 2024 reissue chapter 10.4324/9781032633275-13 (Crossref: publisher 'Routledge', issued 2024-02-26, publisher-location London) - a different edition, so it is NOT added. Crossref bibliographic search for the chapter (2026-09-25) returns only the 2024 reissue.

**The DOI question.** You asked for a DOI ("again, add DOI"). The cited 1978 Erlbaum edition (Hillsdale, NJ) has no DOI. The only DOI for this chapter belongs to the 2024 Routledge reissue of *Cognition and Categorization*: `10.4324/9781032633275-13` (Crossref: publisher "Routledge", issued 2024-02-26, London). That is a different edition, so adding its DOI to the 1978 entry would be wrong. **Which do you want?** (a) Keep the 1978 Erlbaum edition with no DOI (the entry as shown above). (b) Cite the 2024 Routledge reissue with its DOI; the entry would change (year, publisher, address, DOI) and go through verification again. (c) Something else.

Review packet: `verification/2026-09-29-user-review/review-packet-Palm78.json`, written by:

```sh
python bibcheck.py crossref review-packet Palm78 --output verification/2026-09-29-user-review/review-packet-Palm78.json
```

If you choose (a), nothing more is needed: the research route already verified the 1978 text. If you want your own approval on record anyway:

```sh
python bibcheck.py crossref approve Palm78 --fingerprint v2:c2cb1560ba3267d42b4af49e7c6a285368e2ecd97a7c3d7a20c69aed034882d1 --reviewer 'Jeremy Manning' --source 'research-pilot review page (verification/research-pilot-2026-09-24/review.html) and verification/research-pilot-2026-09-24/followup.json' --note 'Checked by Jeremy Manning on <DATE>: <which fields you checked, against what>'
```

## ScotEtal07

Status now: `needs_review` (revoked approval). Fingerprint `v2:102c440cae9315c9f607386dcf3b2f25d9cc7dc68d27b66bba862a207af164bc`.

Entry now:

```bibtex
@incollection{ScotEtal07,
	Address = {Mahwah, {NJ}},
	Author = {P Scott and H Asoko and J Leach},
	Booktitle = {Handbook of Research on Science Education},
	Editor = {S K Abell and N G Lederman},
	Publisher = {Erlbaum},
	Title = {Student conceptions and conceptual learning in science},
	Year = {2007}}
```

What you said:

- Research-pilot page, 2026-09-24 23:52 EDT (2026-09-25T03:52:52.589Z), row `ScotEtal07`: verdict "wrong", note "this is a book; shouldn't be a pages field".
- AskUserQuestion answer, 2026-09-25 00:32 EDT (04:32Z). Question: "ScotEtal07: cite the chapter in the Handbook of Research on Science Education (@incollection) or the whole book?" Answer: "The chapter (Recommended)".
- AskUserQuestion answer, 2026-09-25 13:49 EDT (17:49:37Z). Question: "About 40 entries you already marked Correct on the pilot page (or whose fixes you approved) can't be verified by any automated source [...] Record your verdicts as signed-off human approvals (named reviewer: you, bound to each entry's exact current text)?" Answer: "Yes, record my sign-off (Recommended)". The approval recorded after this answer is the one revoked.

What was applied:

- pilot001 (commit 689de07, `verification/apply-2026-09-28/pilot001-proposals.json`; origin recorded as "followup.json"):
  - `ENTRYTYPE`: `inbook` -> `incollection`
    - evidence: https://catdir.loc.gov/catdir/enhancements/fy0701/2006031809-t.html quotes `P. Scott, H. Asoko, J. Leach, Student Conceptions and Conceptual Learning in Science.`
  - `title`: `Handbook of research on science education` -> `Student conceptions and conceptual learning in science`
    - evidence: https://catdir.loc.gov/catdir/enhancements/fy0701/2006031809-t.html quotes `P. Scott, H. Asoko, J. Leach, Student Conceptions and Conceptual Learning in Science.`
  - `chapter`: `Student conceptions and conceptual learning in science` -> (none)
    - evidence: https://catdir.loc.gov/catdir/enhancements/fy0701/2006031809-t.html quotes `P. Scott, H. Asoko, J. Leach, Student Conceptions and Conceptual Learning in Science.`
  - `booktitle`: (none) -> `Handbook of Research on Science Education`
    - evidence: https://lccn.loc.gov/2006031809/mods quotes `<title>Handbook of research on science education</title>`
  - `editor`: `S K Abell and K Appleton and D Hanuscin` -> `S K Abell and N G Lederman`
    - evidence: https://lccn.loc.gov/2006031809/mods quotes `edited by Sandra K. Abell and Norman G. Lederman.`
  - `publisher`: `Routledge` -> `Erlbaum`
    - evidence: https://lccn.loc.gov/2006031809/mods quotes `<namePart>Lawrence Erlbaum Associates</namePart>`
  - `address`: (none) -> `Mahwah, {NJ}`
    - evidence: https://lccn.loc.gov/2006031809/mods quotes `<placeTerm type="text">Mahwah, N.J</placeTerm>`
- Researcher's note (research-pilot followup.json): No pages field (user: 'shouldn't be a pages field'); the pilot's 31--56 came only from the 2013 Taylor & Francis digital reissue and is dropped. The LoC table of contents for the 2007 handbook confirms the chapter and its three authors. No DOI for the 2007 edition: the T&F chapter DOI 10.4324/9780203824696-3 does not resolve (doi.org: 404 / handle not found) and the book DOI 10.4324/9780203824696 is the Routledge reissue. NEEDS USER: if the intent is to cite the whole handbook (not the chapter), the entry would instead be @book with editors and no authors; the cited authors Scott, Asoko and Leach are chapter authors, so @incollection is proposed.

Review packet: `verification/2026-09-29-user-review/review-packet-ScotEtal07.json`, written by:

```sh
python bibcheck.py crossref review-packet ScotEtal07 --output verification/2026-09-29-user-review/review-packet-ScotEtal07.json
```

To approve after checking, replace `<DATE>` and the note text with what you checked:

```sh
python bibcheck.py crossref approve ScotEtal07 --fingerprint v2:102c440cae9315c9f607386dcf3b2f25d9cc7dc68d27b66bba862a207af164bc --reviewer 'Jeremy Manning' --source https://catdir.loc.gov/catdir/enhancements/fy0701/2006031809-t.html --note 'Checked by Jeremy Manning on <DATE>: <which fields you checked, against what>'
```

## Mink15

Status now: `needs_review` (revoked approval, lapsed in braces0929). Fingerprint `v2:91136b0010930ba1ba3850e1ef80d253f27f73cdf34a9149154ce40ad27e253c`.

Entry now:

```bibtex
@incollection{Mink15,
	Address = {Philadelphia, {PA}},
	Author = {J W Mink},
	Booktitle = {Parkinson's Disease and Movement Disorders},
	Edition = {6\textsuperscript{th}},
	Editor = {J Jankovic and E Tolosa},
	Publisher = {Wolters Kluwer},
	Title = {Functional organization of the basal ganglia},
	Year = {2015}}
```

What you said:

- Research-pilot page, 2026-09-25 00:05 EDT (2026-09-25T04:05:20.290Z), row `Mink07`: verdict "wrong", note "use text superscript for "th" in "5th"".
- AskUserQuestion answer, 2026-09-25 00:32 EDT (04:32Z). Question: "Mink07: only the 6th edition names J W Mink as the chapter's author; no 5th-edition table of contents was found. How should it be handled?" Answer: "Cite the 6th edition".
- AskUserQuestion answer, 2026-09-25 13:49 EDT (17:49:37Z). Question: "About 40 entries you already marked Correct on the pilot page (or whose fixes you approved) can't be verified by any automated source [...] Record your verdicts as signed-off human approvals (named reviewer: you, bound to each entry's exact current text)?" Answer: "Yes, record my sign-off (Recommended)". The approval recorded after this answer is the one revoked.

What was applied:

- pilot001 (commit 689de07, `verification/apply-2026-09-28/pilot001-proposals.json`; origin recorded as "user 2026-09-25: cite the 6th edition (verified LoC + LWW)"):
  - `author`: `Jonathan W Mink` -> `J W Mink`
    - evidence: https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&maximumRecords=1&recordSchema=mods&query=bath.lccn%3D2015458479 quotes `<edition>Sixth edition.</edition> ... <namePart>Wolters Kluwer,</namePart> ... <dateIssued>[2015]</dateIssued> ... <tableOfContents type="Contents">Functional organization of the basal ganglia -- ...`
    - evidence: https://shop.lww.com/Parkinson-s-Disease-and-Movement-Disorders/p/9781608311767 quotes `CONTENTS 1. Functional Organization of the Basal Ganglia Jonathan W. Mink ... Edition 6 Publication Date May 21, 2015`
  - `edition`: (none) -> `6\textsuperscript{th}`
    - evidence: https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&maximumRecords=1&recordSchema=mods&query=bath.lccn%3D2015458479 quotes `<edition>Sixth edition.</edition> ... <namePart>Wolters Kluwer,</namePart> ... <dateIssued>[2015]</dateIssued> ... <tableOfContents type="Contents">Functional organization of the basal ganglia -- ...`
    - evidence: https://shop.lww.com/Parkinson-s-Disease-and-Movement-Disorders/p/9781608311767 quotes `CONTENTS 1. Functional Organization of the Basal Ganglia Jonathan W. Mink ... Edition 6 Publication Date May 21, 2015`
  - `editor`: `Joseph Jankovic and Eduardo Tolosa` -> `J Jankovic and E Tolosa`
    - evidence: https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&maximumRecords=1&recordSchema=mods&query=bath.lccn%3D2015458479 quotes `<edition>Sixth edition.</edition> ... <namePart>Wolters Kluwer,</namePart> ... <dateIssued>[2015]</dateIssued> ... <tableOfContents type="Contents">Functional organization of the basal ganglia -- ...`
    - evidence: https://shop.lww.com/Parkinson-s-Disease-and-Movement-Disorders/p/9781608311767 quotes `CONTENTS 1. Functional Organization of the Basal Ganglia Jonathan W. Mink ... Edition 6 Publication Date May 21, 2015`
  - `publisher`: `Lippincott, Williams, and Wilkins` -> `Wolters Kluwer`
    - evidence: https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&maximumRecords=1&recordSchema=mods&query=bath.lccn%3D2015458479 quotes `<edition>Sixth edition.</edition> ... <namePart>Wolters Kluwer,</namePart> ... <dateIssued>[2015]</dateIssued> ... <tableOfContents type="Contents">Functional organization of the basal ganglia -- ...`
    - evidence: https://shop.lww.com/Parkinson-s-Disease-and-Movement-Disorders/p/9781608311767 quotes `CONTENTS 1. Functional Organization of the Basal Ganglia Jonathan W. Mink ... Edition 6 Publication Date May 21, 2015`
  - `year`: `2007` -> `2015`
    - evidence: https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&maximumRecords=1&recordSchema=mods&query=bath.lccn%3D2015458479 quotes `<edition>Sixth edition.</edition> ... <namePart>Wolters Kluwer,</namePart> ... <dateIssued>[2015]</dateIssued> ... <tableOfContents type="Contents">Functional organization of the basal ganglia -- ...`
    - evidence: https://shop.lww.com/Parkinson-s-Disease-and-Movement-Disorders/p/9781608311767 quotes `CONTENTS 1. Functional Organization of the Basal Ganglia Jonathan W. Mink ... Edition 6 Publication Date May 21, 2015`
  - key renamed Mink07 -> Mink15 (verification/key-renames.json)
- braces0929 (commit 4cdc644, `verification/apply-2026-09-29-braces/braces0929-proposals.json`): braces only
  - `booktitle`: `{Parkinson's} Disease and Movement Disorders` -> `Parkinson's Disease and Movement Disorders`
- Researcher's note (research-pilot followup.json): Chapter author for the 5th edition still NOT confirmed from a 5th-edition source. Checked 2026-09-25: LoC TOC (https://catdir.loc.gov/catdir/toc/ecip0615/2006018969.html) lists '1 Functional Organization of the Basal Ganglia' with no authors; the Internet Archive scan of this exact edition (parkinsonsdiseas0000unse_q1k2, ISBN 0781778816, LCCN 2006018969) has a MARC 505 contents note with titles only, and its text/search-inside is access-restricted; Open Library OL9410655M has no TOC; Google Books API quota exhausted. Only the 6th edition (2015) LWW page names Jonathan W. Mink as chapter 1 author. Author (and 'Jonathan W Mink' vs house 'J W Mink') left unchanged; pages not found. Resolving needs a physical/PDF copy of the 5th edition or an institutional Ovid login.

Review packet: `verification/2026-09-29-user-review/review-packet-Mink15.json`, written by:

```sh
python bibcheck.py crossref review-packet Mink15 --output verification/2026-09-29-user-review/review-packet-Mink15.json
```

To approve after checking, replace `<DATE>` and the note text with what you checked:

```sh
python bibcheck.py crossref approve Mink15 --fingerprint v2:91136b0010930ba1ba3850e1ef80d253f27f73cdf34a9149154ce40ad27e253c --reviewer 'Jeremy Manning' --source 'https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&maximumRecords=1&recordSchema=mods&query=bath.lccn%3D2015458479' --note 'Checked by Jeremy Manning on <DATE>: <which fields you checked, against what>'
```

## KahaMill13

Status now: `needs_review` (revoked approval). Fingerprint `v2:1eb0c55689b963c66d15ca9b144be738997c099aa75cdb26bb20ca0a3171b382`.

Entry now:

```bibtex
@incollection{KahaMill13,
	Author = {M J Kahana and J F Miller},
	Booktitle = {Encyclopedia of the Mind},
	Doi = {10.4135/9781452257044.n183},
	Editor = {H Pashler},
	Pages = {493--497},
	Publisher = {{SAGE} Publications},
	Title = {Memory recall, dynamics},
	Volume = {2},
	Year = {2013}}
```

What you said:

- Research-pilot page, 2026-09-25 00:04 EDT (2026-09-25T04:04:54.110Z), row `KahaMill13`: verdict "wrong", note "add doi too".
- Message, 2026-09-25 00:08 EDT (04:08:13Z): "for the already correct group: they all need DOIs for the published articles (peer reviewed versions as available) / (all papers need DOI fields when available)".
- AskUserQuestion answer, 2026-09-25 13:49 EDT (17:49:37Z). Question: "About 40 entries you already marked Correct on the pilot page (or whose fixes you approved) can't be verified by any automated source [...] Record your verdicts as signed-off human approvals (named reviewer: you, bound to each entry's exact current text)?" Answer: "Yes, record my sign-off (Recommended)". The approval recorded after this answer is the one revoked.

What was applied:

- pilot001 (commit 689de07, `verification/apply-2026-09-28/pilot001-proposals.json`; origin recorded as "followup.json"):
  - `doi`: (none) -> `10.4135/9781452257044.n183`
    - evidence: https://api.crossref.org/works/10.4135/9781452257044.n183 quotes `"DOI":"10.4135\/9781452257044.n183"`
    - evidence: https://api.crossref.org/works/10.4135/9781452257044.n183 quotes `"container-title":["Encyclopedia of the Mind"]`
    - evidence: https://api.crossref.org/works/10.4135/9781452257044.n183 quotes `"published-print":{"date-parts":[[2013]]}`
  - `title`: `Memory, recall dynamics` -> `Memory recall, dynamics`
    - evidence: https://api.crossref.org/works/10.4135/9781452257044.n183 quotes `"title":["Memory Recall, Dynamics"]`
- Researcher's note (research-pilot followup.json): DOI confirmed via Crossref: reference-entry 'Memory Recall, Dynamics' in Encyclopedia of the Mind, SAGE Publications, Inc., 2013. Title changed to SAGE's published form per user. Crossref gives no authors/pages; authors, editor, volume 2 and pp. 493-497 stay as verified in the pilot (lab publication page and Kahana CV). The SAGE Knowledge landing page (sk.sagepub.com/reference/encyclopedia-of-the-mind/n183.xml) redirects scripts to an SSO login, so it cannot serve as evidence.

Review packet: `verification/2026-09-29-user-review/review-packet-KahaMill13.json`, written by:

```sh
python bibcheck.py crossref review-packet KahaMill13 --output verification/2026-09-29-user-review/review-packet-KahaMill13.json
```

To approve after checking, replace `<DATE>` and the note text with what you checked:

```sh
python bibcheck.py crossref approve KahaMill13 --fingerprint v2:1eb0c55689b963c66d15ca9b144be738997c099aa75cdb26bb20ca0a3171b382 --reviewer 'Jeremy Manning' --source https://api.crossref.org/works/10.4135/9781452257044.n183 --note 'Checked by Jeremy Manning on <DATE>: <which fields you checked, against what>'
```

## Hook69

Status now: `needs_review` (revoked approval). Fingerprint `v2:01574f36dc7f4df2e4a1bcd3f87f3cffbee0be26ee196c3928c296f40dbd4e9c`.

Entry now:

```bibtex
@book{Hook69,
	Address = {New York, {NY}},
	Author = {R Hooke},
	Publisher = {Johnson Reprint Corporation},
	Title = {The posthumous works of {R}obert {H}ooke},
	Year = {1969}}
```

What you said:

- Research-pilot page, 2026-09-24 23:53 EDT (2026-09-25T03:53:38.218Z), row `Hook69`: verdict "wrong", note "title should be "The posthumous works of Robert Hooke"".
- AskUserQuestion answer, 2026-09-25 13:49 EDT (17:49:37Z). Question: "About 40 entries you already marked Correct on the pilot page (or whose fixes you approved) can't be verified by any automated source [...] Record your verdicts as signed-off human approvals (named reviewer: you, bound to each entry's exact current text)?" Answer: "Yes, record my sign-off (Recommended)". The approval recorded after this answer is the one revoked.

What was applied:

- pilot001 (commit 689de07, `verification/apply-2026-09-28/pilot001-proposals.json`; origin recorded as "followup.json"):
  - `title`: `The posthumous works of {R}obert {H}ooke: with a new introduction by {R}ichard {S.} {W}estfall` -> `The posthumous works of {R}obert {H}ooke`
    - evidence: https://openlibrary.org/books/OL21113026M.json quotes `"title": "The posthumous works of Robert Hooke"`
    - evidence: https://lccn.loc.gov/68026912/mods quotes `<title>posthumous works of Robert Hooke</title>`
  - `address`: (none) -> `New York, {NY}`
    - evidence: https://lccn.loc.gov/68026912/mods quotes `<placeTerm type="text">New York</placeTerm>`
- Researcher's note (research-pilot followup.json): Title per user; 'With a new introd. by Richard S. Westfall' is LoC's statement of responsibility, not title text. No DOI for the 1969 Johnson Reprint edition (the 2019 Routledge reissue 10.4324/9780429060717 is a different edition). Address carried over from the pilot (LoC: New York).

Review packet: `verification/2026-09-29-user-review/review-packet-Hook69.json`, written by:

```sh
python bibcheck.py crossref review-packet Hook69 --output verification/2026-09-29-user-review/review-packet-Hook69.json
```

To approve after checking, replace `<DATE>` and the note text with what you checked:

```sh
python bibcheck.py crossref approve Hook69 --fingerprint v2:01574f36dc7f4df2e4a1bcd3f87f3cffbee0be26ee196c3928c296f40dbd4e9c --reviewer 'Jeremy Manning' --source https://openlibrary.org/books/OL21113026M.json --note 'Checked by Jeremy Manning on <DATE>: <which fields you checked, against what>'
```

## Bart32

Status now: `needs_review` (lapsed in braces0929). Fingerprint `v2:537f60bccc4037785323fe93bac5b5b37d46b55052006916a4520aa9c9ca8a58`.

Entry now:

```bibtex
@book{Bart32,
	Author = {F C Bartlett},
	Publisher = {Cambridge University Press},
	Title = {Remembering: a study in experimental and social psychology},
	Year = {1932}}
```

What you said:

- Research-pilot page, 2026-09-24 23:53 EDT (2026-09-25T03:53:55.025Z), row `Bart32`: verdict "correct", no note.
- AskUserQuestion answer, 2026-09-25 13:49 EDT (17:49:37Z). Question: "About 40 entries you already marked Correct on the pilot page (or whose fixes you approved) can't be verified by any automated source [...] Record your verdicts as signed-off human approvals (named reviewer: you, bound to each entry's exact current text)?" Answer: "Yes, record my sign-off (Recommended)". The approval recorded after this answer is the one that lapsed in braces0929.

What was applied:

- pilot001 (commit 689de07, `verification/apply-2026-09-28/pilot001-proposals.json`; origin recorded as "pilot-proposals.json (user: correct)"):
  - `publisher`: `{Oxford} {University} Press` -> `Cambridge {University} Press`
    - evidence: https://lccn.loc.gov/39016008/mods quotes `Cambridge [Eng.] The University press 1932`
    - evidence: https://lccn.loc.gov/33014008/mods quotes `Cambridge, Eng The Macmillan company The University press 1932`
- braces0929 (commit 4cdc644, `verification/apply-2026-09-29-braces/braces0929-proposals.json`): braces only
  - `publisher`: `Cambridge {University} Press` -> `Cambridge University Press`

Review packet: `verification/2026-09-29-user-review/review-packet-Bart32.json`, written by:

```sh
python bibcheck.py crossref review-packet Bart32 --output verification/2026-09-29-user-review/review-packet-Bart32.json
```

To approve after checking, replace `<DATE>` and the note text with what you checked:

```sh
python bibcheck.py crossref approve Bart32 --fingerprint v2:537f60bccc4037785323fe93bac5b5b37d46b55052006916a4520aa9c9ca8a58 --reviewer 'Jeremy Manning' --source https://lccn.loc.gov/39016008/mods --note 'Checked by Jeremy Manning on <DATE>: <which fields you checked, against what>'
```

## KahaEtal24

Status now: `needs_review` (lapsed in braces0929). Fingerprint `v2:825421e71de43c17a96c3dfe31b0a92cc9ff3f042c106f311b8776633a37baff`.

Entry now:

```bibtex
@incollection{KahaEtal24,
	Author = {M J Kahana and N B Diamond and A Aka},
	Booktitle = {The Oxford Handbook of Human Memory},
	Doi = {10.1093/oxfordhb/9780190917982.013.2},
	Editor = {M J Kahana and A D Wagner},
	Pages = {29--63},
	Publisher = {Oxford University Press},
	Title = {Laws of human memory},
	Year = {2024}}
```

What you said:

- Research-pilot page, 2026-09-24 23:54 EDT (2026-09-25T03:54:22.528Z), row `KahaEtal22`: verdict "correct", no note.
- AskUserQuestion answer, 2026-09-25 13:49 EDT (17:49:37Z). Question: "About 40 entries you already marked Correct on the pilot page (or whose fixes you approved) can't be verified by any automated source [...] Record your verdicts as signed-off human approvals (named reviewer: you, bound to each entry's exact current text)?" Answer: "Yes, record my sign-off (Recommended)". The approval recorded after this answer is the one that lapsed in braces0929.

What was applied:

- pilot001 (commit 689de07, `verification/apply-2026-09-28/pilot001-proposals.json`; origin recorded as "pilot-proposals.json (user: correct)"):
  - `booktitle`: `Handbook of Human Memory` -> `The {Oxford} Handbook of Human Memory`
    - evidence: https://api.crossref.org/works/10.1093/oxfordhb/9780190917982.013.2 quotes `"container-title":["The Oxford Handbook of Human Memory, Two Volume Pack"]`
  - `year`: `2022` -> `2024`
    - evidence: https://api.crossref.org/works/10.1093/oxfordhb/9780190917982.013.2 quotes `"published":{"date-parts":[[2024,7,18]]}`
    - evidence: https://api.crossref.org/works/10.1093/oxfordhb/9780190917982.001.0001 quotes `"published-print":{"date-parts":[[2024,6,25]]}`
  - `pages`: (none) -> `29--63`
    - evidence: https://api.crossref.org/works/10.1093/oxfordhb/9780190917982.013.2 quotes `"page":"29-63"`
  - `doi`: (none) -> `10.1093/oxfordhb/9780190917982.013.2`
    - evidence: https://api.crossref.org/works/10.1093/oxfordhb/9780190917982.013.2 quotes `"DOI":"10.1093\/oxfordhb\/9780190917982.013.2"`
  - key renamed KahaEtal22 -> KahaEtal24 (verification/key-renames.json)
- braces0929 (commit 4cdc644, `verification/apply-2026-09-29-braces/braces0929-proposals.json`): braces only
  - `booktitle`: `The {Oxford} Handbook of Human Memory` -> `The Oxford Handbook of Human Memory`
  - `publisher`: `{Oxford} {University} Press` -> `Oxford University Press`

Review packet: `verification/2026-09-29-user-review/review-packet-KahaEtal24.json`, written by:

```sh
python bibcheck.py crossref review-packet KahaEtal24 --output verification/2026-09-29-user-review/review-packet-KahaEtal24.json
```

To approve after checking, replace `<DATE>` and the note text with what you checked:

```sh
python bibcheck.py crossref approve KahaEtal24 --fingerprint v2:825421e71de43c17a96c3dfe31b0a92cc9ff3f042c106f311b8776633a37baff --reviewer 'Jeremy Manning' --source https://api.crossref.org/works/10.1093/oxfordhb/9780190917982.013.2 --note 'Checked by Jeremy Manning on <DATE>: <which fields you checked, against what>'
```

## Youn61

Status now: `needs_review` (lapsed in braces0929). Fingerprint `v2:f5ef047a64900114b437a210e4d2cac25b42c5547309eaadb3fb8e93fbeeeb40`.

Entry now:

```bibtex
@article{Youn61,
	Author = {R K Young},
	Doi = {10.2307/1419662},
	Journal = {The American Journal of Psychology},
	Number = {4},
	Pages = {517--528},
	Title = {The stimulus in serial verbal learning},
	Volume = {74},
	Year = {1961}}
```

What you said:

- Research-pilot page, 2026-09-24 23:59 EDT (2026-09-25T03:59:15.483Z), row `Youn61`: verdict "correct", no note.
- AskUserQuestion answer, 2026-09-25 13:49 EDT (17:49:37Z). Question: "About 40 entries you already marked Correct on the pilot page (or whose fixes you approved) can't be verified by any automated source [...] Record your verdicts as signed-off human approvals (named reviewer: you, bound to each entry's exact current text)?" Answer: "Yes, record my sign-off (Recommended)". The approval recorded after this answer is the one that lapsed in braces0929.

What was applied:

- pilot001 (commit 689de07, `verification/apply-2026-09-28/pilot001-proposals.json`; origin recorded as "pilot-proposals.json (user: correct)"):
  - `journal`: `{American} Journal of Psychology` -> `The {American} Journal of Psychology`
    - evidence: https://api.crossref.org/works/10.2307/1419662 quotes `"container-title":["The American Journal of Psychology"]`
  - `number`: (none) -> `4`
    - evidence: https://api.crossref.org/works/10.2307/1419662 quotes `"issue":"4"`
  - `doi`: (none) -> `10.2307/1419662`
    - evidence: https://api.crossref.org/works/10.2307/1419662 quotes `"DOI":"10.2307\/1419662"`
- braces0929 (commit 4cdc644, `verification/apply-2026-09-29-braces/braces0929-proposals.json`): braces only
  - `journal`: `The {American} Journal of Psychology` -> `The American Journal of Psychology`

Review packet: `verification/2026-09-29-user-review/review-packet-Youn61.json`, written by:

```sh
python bibcheck.py crossref review-packet Youn61 --output verification/2026-09-29-user-review/review-packet-Youn61.json
```

To approve after checking, replace `<DATE>` and the note text with what you checked:

```sh
python bibcheck.py crossref approve Youn61 --fingerprint v2:f5ef047a64900114b437a210e4d2cac25b42c5547309eaadb3fb8e93fbeeeb40 --reviewer 'Jeremy Manning' --source https://api.crossref.org/works/10.2307/1419662 --note 'Checked by Jeremy Manning on <DATE>: <which fields you checked, against what>'
```

## Verified by the research route (no action needed)

The research route checks each field against quoted official records. It does not read your research-pilot verdicts, so your "wrong" did not block it. The table puts each note beside the fields pilot001 changed, so you can see that each requested fix is in the entry.

| Key | What you said (research-pilot page) | Applied in pilot001 | Now |
|-|-|-|-|
| MikoEtal13b | 2026-09-25 00:02 EDT: "wrong", note "again, omit year in conference proceedings book name" | `ENTRYTYPE`, `journal`, `booktitle`, `address`, `publisher` | `metadata_verified` (research route) |
| vanEEtal18 | 2026-09-24 23:40 EDT: "wrong", note "add doi for elife (published/peer reviewed) version" | `doi` | `metadata_verified` (research route) |
| AndeEtal66 | 2026-09-24 23:49 EDT: "wrong", note "use double hyphen for range for "number" field ("3--4")" | `number`, `title`, `author`, `doi` | `metadata_verified` (research route) |
| PuceEtal99 | 2026-09-25 00:07 EDT: "wrong", note "need DOI" | `doi` | `metadata_verified` (research route) |
| BiswEtal95 | 2026-09-25 00:07 EDT: "wrong", note "need DOI" | `doi` | `metadata_verified` (research route) |
| ParaEtal04 | 2026-09-24 23:37 EDT: "wrong", note "add DOI; otherwise looks correct" | `doi` | `metadata_verified` (research route) |
| Jame90 | 2026-09-24 23:47 EDT: "wrong", note "Where's the "volume I" part?" | `volume`, `doi`, `author` | `metadata_verified` (research route) |
