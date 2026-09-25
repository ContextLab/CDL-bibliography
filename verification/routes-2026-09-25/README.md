# Source routes, 2026-09-25: PsyArXiv/OSF, DataCite, ACL Anthology, SfN abstract planner

These are four new `verify --auto-review` routes for cases the PR #87/#88 check could not verify
(`verification/pr-check-2026-09-25/README.md`, defect 14). Each route has its own module,
policy constant, `run_*` function and approval validator. The validator is registered through
`verification.register_approval_validator`. The runs never edit BibTeX. A route can verify an
entry, propose source-backed field values, flag a published version for replacement, or hold
the entry.

| Route | Module | Source | Policy |
|-|-|-|-|
| PsyArXiv | `bibcheck/osf_review.py` | OSF API v2 (version list, bibliographic contributors, primary-file revisions) | `OSF_POLICY = '1'` |
| Software/data | `bibcheck/datacite_review.py` | DataCite REST API (`/dois/<doi>`, title search) | `DATACITE_POLICY = '1'` |
| ACL Anthology | `bibcheck/acl_review.py` | `https://aclanthology.org/<id>.bib`; OpenAlex only nominates IDs | `ACL_POLICY = '1'` |
| SfN abstracts | `bibcheck/sfn_abstracts.py` | abstractsonline.com OASIS planner (search + ViewAbstract) | `SFN_POLICY = '1'` |

## Rules applied

- **Latest preprint version** (user, 2026-09-24): OSF has two layers of versions.
  Versioned records (`<id>_vN`) each have their own DOI. Older records were revised in place
  through their primary file. The version date is the later of the latest record's
  `date_published` and the newest primary-file revision. ZimaEtal23: the record is from 2019
  and file revision 3 is dated 2023-04-10, so the year is 2023, which the user confirmed.
  A citation that pins an older version gets a proposal for the latest DOI.
- **The published version replaces the preprint.** When OSF lists an article DOI, the entry
  is classed `replacement` and never verifies, even after every preprint field is repaired.
- **DOIs everywhere.** A DOI stored in `volume` becomes a proposal to move it to `doi`.
- **Initials and no suffixes.** Author proposals use `correction_proposals.house_byline`.
  An entry is held instead of proposed when the source has less detail than the citation
  (`byline_loses_detail`), when a surname change lacks corroboration (`surname_change_hold`),
  or when the source's name shape is uncertain.
- **Proceedings names omit the year.** The house form of an Anthology booktitle drops the
  year and a trailing acronym such as `(EMNLP-IJCNLP)`. A volume label such as
  `(Volume 1: Long Papers)` is kept. The ordinal edition number (`9th`) may also be omitted.
  The Anthology page range outranks Crossref's (ReimGure19).
- **Software titles.** The house title `{Owner}/repo: {version}` matches when it is the
  registry title, or the registry title's `Owner/repo` part (which must equal the record's
  GitHub `IsSupplementTo` repository) followed by the registry `version`. Every creator is
  compared in order. A non-person creator is written as printed and braced (Mann26:
  `J R Manning and {Claude}`).
- **SfN.** The house form comes from `SFN-SOURCE.md`. The author order is the planner's
  Disclosures line, cross-checked name by name against the capitalised Authors line. Titles
  are compared after NFKC normalization, which handles the `ﬁ` ligature. Years without a
  confirmed meeting key are reported as `unsupported`, with no request.

SfN OASIS meeting keys were confirmed on 2026-09-25 from abstract pages found through
Wayback CDX captures of `ViewAbstract.aspx`:

| Year | mKey | Confirmed by |
|-|-|-|
| 2009 | 081F7976-E4CD-4F3D-A0AF-E8387992A658 | footer "2009 Neuroscience Meeting Planner. Chicago, IL" |
| 2010 | E5D5C83F-CE2D-4D71-9DD6-FC7231E090FB | footer "2010 ... San Diego, CA" |
| 2011 | 8334BE29-8911-4991-8C31-32B32DD5E6C8 | footer "2011 ... Washington, DC" |
| 2012 | 70007181-01C9-4DE9-A0A2-EEBFA14CD9F1 | footer "2012 ... New Orleans, LA" (SFN-SOURCE.md) |
| 2013 | 8D2A5BEC-4825-4CD6-9439-B42BB151D1CF | presentation date Nov 11, 2013 (SfN week, San Diego); the checked page has no footer |
| 2014 | 54C85D94-6D69-4B09-AFAA-502C0E680CA7 | presentation date Nov 17, 2014, "WCC", SfN links |
| 2015 | D0FF4555-8574-4FBB-B9D4-04EEC8BA0C84 | presentation date Oct 17, 2015 (SfN week, Chicago) |

No key was found for 2006-2008: the candidates tried answered "Meeting Not found".

## Yield over current needs_review entries (`measure.py`)

The inputs were read-only: the working-tree `cdl.bib` (6,422 entries) and the main cache
(opened `mode=ro`), where 2,388 entries are `needs_review`. The routes ran in
`.bibcheck/routes-2026-09-25.sqlite3`. Per-entry results are in `measurement.json`.

| Route | Applies to | Would verify | Proposals | Replacements | Held | Unsupported |
|-|-|-|-|-|-|-|
| osf_review | 6 | 1 (FranLiu18) | 2 (ZimaEtal23, MannEtal23a) | 3 (GralFinn21, LuriEtal18, NussEtal18) | 0 | - |
| datacite_review | 6 | 0 | 2 (Mann21b, Mann21c) | - | 4 (ChanEtal20, FitzEtal25, Mann21d, MuelEtal18) | - |
| acl_review | 10 | 0 | 8 | - | 2 (ChenEtal22, PennEtal14) | - |
| sfn_review | 28 | 0 | 7 | - | 5 | 16 (years before 2009) |

The PR-branch cases are not in `cdl.bib`. They are fixtures:

| Entry | Result |
|-|-|
| FitzEtal26a | verifies (`10.31234/osf.io/mhxtd_v1`, the only version) |
| Spee22 | verifies |
| ReimGure19 | verifies (pages 3982--3992) |
| Mann26 | proposal: add the second creator, `{Claude}` |

Why entries are held:
- ChanEtal20: title and author mismatch.
- FitzEtal25, PennEtal14, BurkEtal12, MannEtal09b: the source byline has fewer initials than
  the citation.
- Mann21d: the record has no GitHub link to verify `howpublished`.
- MuelEtal18: a DataCite creator is recorded as `, Peter`.
- ChenEtal22: editor initials (`M-C` vs `M C`).
- KrauEtal12: library consensus keeps `{Robinson I I }`.
- WatrEtal09: the planner title reads "human local field potentials" and the citation adds
  "hippocampal".
- LongKaha13: the 2013 author search returned the planner's browse list rather than author
  hits. This is a known gap: the 2013 search form was not verified.

Requests and repeat runs:
- First measurement pass: 22 requests, all SfN (the other routes' documents were already
  cached by development runs, about 80 counted requests).
- Repeat collect-and-assess with a fresh client: **0 requests**, and all 50 outcomes were
  identical.
- Repeat `run_*_review`: **0 requests**, because each entry already carries its route policy
  marker.
- After the SfN 2009-layout fix, the whole measurement was re-run: 0 requests, same
  identical-repeat result.
- Outside the cache there were manual probes (curl): OSF, DataCite, Anthology and OpenAlex
  shape checks, and about 60 SfN pages for meeting keys. DBLP is behind a bot wall.
  Semantic Scholar returned 429 and is not used.

## Tests and fixtures

- `tests/test_osf_review.py`: 17 tests.
- `tests/test_datacite_review.py`: 15 tests.
- `tests/test_acl_review.py`: 14 tests.
- `tests/test_sfn_abstracts.py`: 14 tests.

The tests read `fixtures/*.json`. Every raw document there is the unmodified saved response
(URL, body, SHA-256), built by `build_fixtures.py`; controls change only citation fields.
Negative controls:
- an older OSF version is cited;
- a withdrawn PsyArXiv preprint;
- another work's title under a real DOI (OSF, DataCite, ACL);
- a different software release;
- the Crossref page range;
- a published-version relation;
- a wrong SfN program number, author order, year or abstract.

Other tests cover tampered bodies and approvals, zero-request collection from saved
documents, and a full `run_osf_review` whose repeat makes 0 requests.

Run from the repository root:

```
CROSSREF_MAILTO=<real contact> .venv/bin/python verification/routes-2026-09-25/build_fixtures.py
CROSSREF_MAILTO=<real contact> .venv/bin/python verification/routes-2026-09-25/measure.py
.venv/bin/python -m pytest tests/test_osf_review.py tests/test_datacite_review.py tests/test_acl_review.py tests/test_sfn_abstracts.py
```
