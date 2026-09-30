# User surname decisions of 2026-09-30 (batch surnames0930c)

The user's rule (2026-09-30): "one source is sufficient; manual entry is the weakest part. notify
user if mismatch is found and ask how they want to resolve it". The 137 mismatches it produced
([surnames.json](../2026-09-30-user-review/surnames.json), 136 author positions in 100 entries)
were put to the user on the review page https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM
(collection `review0930`). What was decided, by whom and when: decision log,
[resolution-plan README](../resolution-plan-2026-09-22/README.md), "User surname decisions
2026-09-30".

## Inputs kept here

- [answers/](answers/): all 62 documents of `review0930`, read with the ArtifactData tool on
  2026-09-30 (after 17:28 UTC, the last answer). Sections C, E, F, G, H and I are used here.
- [printed/printed.json](printed/printed.json): the printed-byline evidence for 73 rows,
  collected through the Dartmouth VPN (id, key, position, printed, class, quote, page, url,
  pdf_sha256, how). [printed/text/](printed/text/): the text extracted from each PDF's first
  pages. The PDFs themselves are not kept (copyright); each is identified by its sha256.
- The page's sources (build_page.py, build_final.py, classify.py, surnames-classified.json,
  template.html, open-questions.html) are in
  [../2026-09-30-user-review/page/](../2026-09-30-user-review/page/). build_final.py and
  classify.py name the session scratch paths they were run from.
- [build_decisions.py](build_decisions.py) → [decisions.json](decisions.json): one row per
  mismatch with its decision, the deciding document(s) and the printed evidence. It asserts
  that every document of sections C, E, F, G, H and I is used, except the three group documents
  answered "show" (corrupt, format, shorter), whose rows were then settled one by one by the
  printed bylines and section I.

## Decisions

123 keep, 13 change, 1 held.

| Entry | Author | Before | After | Decided by |
|-|-|-|-|-|
| KragEtal19 | 9 | L F Barrett | L {Feldman Barrett} | surname-KragEtal19-9 "source" |
| LopeEtal73 | 4 | W S {van Leeuwen} | W {Storm van Leeuwen} | surname-LopeEtal73-4 "source" (Crossref given "W", family "Storm van Leeuwen"; the S initial was the first surname, as in LopeStor77, "W {Storm Van Leeuwen}") |
| LopeEtal73 | 1 | F H {Lopes Da Silva} | F H {Lopes da Silva} | manual-surname1-LopeEtal73-1, the user's text "{Lopes da Silva}" |
| PennEtal94 | 3 | F H {Lopes Da Silva} | F H {Lopes da Silva} | manual-surname1-PennEtal94-3, the user's text |
| dBakEtal08 | 1 | R S J {d Baker} | R S J {d} Baker | surname-dBakEtal08-1 "source" (Crossref given "Ryan S. J. d.", family "Baker") |
| MurdVomS67 → MurdvomS67 | 2 | W {Vom {S}aal} | W {vom Saal} | surname-group-longer "except", note "Vom{S}aal should be \"{vom Saal}\"" |
| IshiEtal75 | 3 | N Yoshimasu | N Yoshimasa | surname-IshiEtal75-3 and manual-recheck-IshiEtal75-3 "source" (the user checked the print) |
| FreuEtal09 | 6 | J Klosterk{\"o}tter | J Klosterkoetter | printed byline, rule-unify "per-paper" |
| LatiEtal10 | 7 | F D'Agata | F Dagata | printed byline, rule-unify "per-paper" |
| NadeEtal00 | 3 | J E LeDoux | J E {Le Doux} | printed byline, rule-unify "per-paper" |
| ConwEtal00 | 4 | M Racsm\'{a}ny | M Racsma'ny | manual-surname1-ConwEtal00-4 "source" and the user's message (below) |
| MillEtal07c | 2 | M {den Nijs} | M denNijs | manual-surname1-MillEtal07c-2 "source" and the user's message |
| MillEtal07d | 5 | M {den Nijs} | M denNijs | manual-surname1-MillEtal07d-5 "source" and the user's message |

The user's message resolving the last three (2026-09-30, relayed verbatim by the orchestrating
session): "1. ConwEtal00 had an apostrophe, not an accent / 2. denNijs is printed as one word in
the example pub".

Kept (no edit): the 12 round-1 "entry" answers; the four rows where the printed paper equals
the entry and overrides the user's earlier Crossref pick (AndeEtal66#3 Hamberger, KatzEtal89#3
Kong, MallEtal97#3 Sch{\"o}lkopf, MeyeEtal88#4 Kounios); RebeEtal02#3 Gitelman (printed
"Gitleman"; the user chose "correct", a user-approved exception to the as-printed rule); the
47 "longer" rows other than MurdVomS67; the 43 printed rows classed PRINTED=ENTRY (the four
above included); the six name-suffix rows (EngeEtal10#6, GomeEtal96#3, IyyeEtal15#4,
PollGero68#2, Roed08#1, Warr98#1) under the user's rule "No name suffixes (Jr, Sr, II, III,
IV): never added; the 27 existing ones are stripped; the comparator ignores suffixes" (decision
log, "Spot-check completed (2026-09-24/25) and resulting decisions"); the 12 section I "entry"
answers; SchaEtal11#3 and StJaEtal12#1, answered "source" ("St. Jacques"), which in house form
(periods stripped) is "{St Jacques}", the entry's spelling, so no edit.

### Two departures from the literal instructions, with the evidence

1. **dBakEtal08 is "R S J {d} Baker", not "R S J d Baker".** BibTeX reads an unbraced lowercase
   word before the surname as a particle, so "R S J d Baker" renders as "d Baker". Checked with
   `bibtex` and apalike.bst on 2026-09-30: `R S J d Baker` gave `\bibitem[d~Baker and Corbett,
   2008]` / `d~Baker, R. S.~J.`; `R S J {d} Baker` gave `\bibitem[Baker and Corbett, 2008]` /
   `Baker, R. S. J.~d.`, which is Crossref's given "Ryan S. J. d." and family "Baker". The key
   stays **dBakEtal08**: `helpers.authors2key` gives dBakEtal08 for both forms, because
   `helpers.last_name` treats a lowercase "d" as a surname prefix. A key of BakeEtal08 would
   need that rule changed or a key override; that is the user's call.
2. **WatkPeyn83 is held, unchanged.** The user's text "Peyn\dot{i}rc\dot{i}o\u{g}lu" uses
   `\dot`, a math-mode accent. In text mode it stops LaTeX (pdflatex, 2026-09-30:
   `! Missing $ inserted.` and `! Please use \mathaccent for accents in math mode.` at
   `Peyn\dot{i}rc\dot{i}o\u{g}`), so every paper citing the entry would fail to build, and the
   checker's normalizer rejects it ("Unknown LaTeX command needs source review"). Extending the
   checker to accept it would pass a string LaTeX cannot typeset, so it was not done. The
   entry keeps "Z F Peynircio\u{g}lu" (plain "i" is the dotted i; the text-mode dot accent is
   `\.{i}`) and stays `metadata_verified`; the user decides.

## Run

    python verification/apply-2026-09-30c-surnames/build_decisions.py
    python verification/apply-2026-09-30c-surnames/apply.py --freeze   # once: surnames0930c-batch.json
    python verification/apply-2026-09-30c-surnames/apply.py --apply
    python verification/apply-2026-09-30c-surnames/restore_check.py <new empty database path>

[apply.py](apply.py) stages the 12 Author edits in a copy (only those fields and the one key
change; `check_bib` clean; the key of every edited entry equals `authors2key` plus its suffix),
backs up cdl.bib and the results under `.bibcheck/apply-2026-09-30c-surnames/`, logs the rename
in verification/key-renames.json (commit `surnames0930c`), runs the production pipeline, records
the approvals, runs the negative controls, repeats the pipeline and exports
`verification/baseline.jsonl.gz` and `verification/review-queue.jsonl.gz`. Log:
[attempt1.log](attempt1.log); results: [surnames0930c-results.json](surnames0930c-results.json).

Batch: 20 entries (the 12 edited, and the 8 that were `needs_review`).

| Stage | Requests | Review writes | Result |
|-|-|-|-|
| pipeline | 1 | 36 | 6 edited entries verify on Crossref (KragEtal19, MurdvomS67, NadeEtal00, MillEtal07c, MillEtal07d, IshiEtal75); 6 edited entries `needs_review` (their research-evidence approval was for the old text); the 8 stay `needs_review`; nothing accepted outside the batch changed |
| approvals | 0 | 12 | `human_verified`: ConwEtal00, dBakEtal08, LopeEtal73, PennEtal94, MeyeEtal88, BragEtal99, RobeEtal99, NoldEtal98, SchaEtal11, StJaEtal08, StJaEtal12, StJaScha13 |
| negative controls | 0 | 0 | approving each of the 12 edited entries on its pre-edit fingerprint is refused ("Entry changed since review; approval rejected"); WatkPeyn83's result is unchanged |
| repeat | 0 | 0 | identical to the state after the approvals |

Why four edited entries needed an approval: ConwEtal00, dBakEtal08, LopeEtal73 and PennEtal94
had been verified on research evidence, an approval bound to the old text. After the edit, their
entry-level issues are only "No unambiguous, fully supported metadata match"; the Crossref
record of each agrees on every surname (so the comparator reads "Racsma'ny", "{d} Baker",
"{Storm van Leeuwen}" and "{Lopes da Silva}" as the source's names) and differs only in what
the research evidence had already covered: "author: Missing or incomplete given names"
(ConwEtal00, LopeEtal73, PennEtal94: Crossref gives initials or partial given names) and, for
dBakEtal08, the proceedings type, booktitle and publisher. The approval rests on that earlier
verification plus the user's surname decision.

Each approval: reviewer "Jeremy Manning"; source: the page, collection, doc id(s), choice and
answer time, or, for an entry settled by the printed byline alone (BragEtal99, RobeEtal99,
NoldEtal98, StJaEtal08, StJaScha13), the page and the user's rule of 2026-09-28 ("the printed
paper is the source of truth"); note: the spelling chosen at each position and the printed
evidence (URL, page, quote) where printed.json has it.

### Still `needs_review` (not approved: another issue is open)

- **FreuEtal09**: "DOI-linked source correction/retraction notice requires adjudication". The
  notice is the erratum 10.1001/archneurol.2011.75 (Arch Neurol 68(4):421, 2011), which corrects
  a sentence in the Methods ("an error occurred in the eighth line of the first paragraph of the
  "Surgical Procedure" subsection"), not the byline. The research evidence (wave 2, batch-004)
  had adjudicated it as "a correction notice, not a retraction; no change to the citation", but
  that approval was bound to the old text.
- **LatiEtal10**: the same issue, and here the notice is about this very name. The erratum
  10.1007/s00426-016-0761-6 (Psychol Res 80(4):727, 2016) corrects it; PubMed's record says
  "Dagata, Federico [corrected to D’Agata, Federico]". The printed article says "Dagata", the
  publisher's own correction says "D'Agata". The user's per-paper answer was given without
  this erratum on the page, so the user should decide whether the entry follows the printed
  article (Dagata, applied) or its published correction (D'Agata, the previous text).

## Library after the batch

`bibcheck.py crossref status cdl.bib`: `6384 entries: human_verified=35, metadata_verified=6347, needs_review=2` (the 2: FreuEtal09, LatiEtal10).
Checks after the batch: `python -m pytest -q tests` 2200 passed; `python bibcheck/test.py` (repo root) exit 0;
verification/benchmark/run.py 60/60, 0 false acceptances; verification/pdf-benchmark/run.py false_accept 0;
`bibcheck.py verify --no-citations` "looks good!". A restore of
the exported baseline into an empty database gives the same status line and the same result for
every entry ([restore_check.py](restore_check.py)).
