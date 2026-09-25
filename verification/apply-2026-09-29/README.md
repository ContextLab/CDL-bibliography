# Stage 2D (2026-09-29 folder, run 2026-09-25): SfN abstracts, preprint replacements, pilot sign-off

These batches apply three user decisions recorded in
[../resolution-plan-2026-09-22/README.md](../resolution-plan-2026-09-22/README.md): the SfN planner as a
source for conference abstracts, "Replacements approved" and "Sign-off of pilot verdicts" (both 2026-09-25).

The runner is [`apply.py`](apply.py). It reuses `../apply-2026-09-28/apply.py` and keeps its discipline:

1. Proposals are frozen with entry fingerprints (`<batch>-proposals.json`).
2. The staging diff is limited to the batch, and `helpers.check_bib` must pass.
3. A backup and a snapshot go under `.bibcheck/apply-2026-09-29/`, then the batch is applied.
4. The production pipeline runs for the batch keys. A repeat run must make 0 requests and 0 review writes.
5. No accepted result outside the batch may change.
6. `verification/baseline.jsonl.gz` and `review-queue.jsonl.gz` are exported.
7. `.bibcheck/validate-current-checkpoint.py` must give an exact fresh restore. It now reads
   [`library-changes.json`](library-changes.json) in this folder (same removals and PR additions as stage 2C,
   `last_staged` set to this stage's last batch).
8. The full pytest suite and `verification/benchmark/run.py` (60/60) must pass, then the batch is committed.

One addition: an `edit` proposal with no field changes and a `rename` is a pure key rename. Fingerprints do
not include the cite key, so staging asserts that the fields and the fingerprint stay the same.

| Step | Entries | Status change in batch | Requests (run / repeat) | Review writes (run / repeat) | Library after | Commit |
|-|-|-|-|-|-|-|
| start | | | | | 4,471 / 2,010 (6,481) | 8234b5f |
| sfn001 | 2 | +2 verified (SfN planner route) | 0 / 0 | 2 / 0 | 4,473 / 2,008 (6,481) | b64b17d |
| replace001 | 9 (8 replacements + 1 rename) | 6 of 9 verified (3 newly: BetzEtal20, GralFinn22, NussEtal20; 3 kept verified: ChieHone20, LeeEtal20b, SilvEtal19) | 12 / 0 | 25 / 0 | 4,476 / 2,005 (6,481) | ba37f81 |
| signoff001 | 31 | 31 needs_review → human_verified | 0 / 0 (repeat pipeline) | 31 approvals / 0 | 4,476 verified + 31 human_verified / 1,974 | the commit that adds this README |

Counts are metadata_verified / needs_review from the batch runs and `bibcheck.py crossref status cdl.bib`.

## sfn001: RamaEtal12b and SommEtal12

Built by [`build_sfn.py`](build_sfn.py) from `../research-pilot-2026-09-24/followup.json`. Both were held in
stage 2C because the SfN route raised `KeyError: 'accepted_doi'`; the fix is in 1b91591.

- **RamaEtal12b:** Baltuch before Kahana (planner: "C.T. Weidemann: None. G.H. Baltuch: None. M.J. Kahana:
  None."), `number = {800.09}` ("Program#/Poster#: 800.09/BBB40").
- **SommEtal12:** `@conference` → `@inproceedings`, booktitle `Society for Neuroscience Abstracts`,
  `number = {746.04}` ("Program#/Poster#: 746.04/D27"), address `New Orleans, {LA}`, `publisher` moved to
  `organization`.

Both verify with `accepted_source: sfn-abstract-planner` ([`sfn001-results.json`](sfn001-results.json)).

## replace001: preprints replaced by their published versions

Built by [`build_replace.py`](build_replace.py) from `../apply-2026-09-28/replacement-candidates.json`. Each
entry is written in house form from its Crossref record, saved in [`crossref/`](crossref/): initials without
periods, lowercase DOI, sentence-case title, the journal name cdl.bib already uses (`{NeuroImage}`,
`Proceedings of the National Academy of Sciences, {USA}`), full page ranges.

| Old key | New key | Published version | Status |
|-|-|-|-|
| LeeEtal20 (Lee, Bellana & Chen; unchanged) | LeeEtal20a | (rename only, suffix rule) | needs_review, as before |
| BetzEtal19 | BetzEtal20 | NeuroImage 213:116687 (2020), 10.1016/j.neuroimage.2020.116687 | verified |
| ChieHone19 | ChieHone20 | Neuron 106(4):675--686.e11 (2020), 10.1016/j.neuron.2020.02.013 | verified |
| GralFinn21 | GralFinn22 | Soc Cogn Affect Neurosci 17(6):598--608 (2022), 10.1093/scan/nsac019 | verified |
| LeeEtal19 | LeeEtal20b | Cell 183(3):620--635.e22 (2020), 10.1016/j.cell.2020.09.024 | verified |
| LuriEtal18 | LuriEtal20 | Network Neuroscience 4(1):30--69 (2020), 10.1162/netn_a_00116 | needs_review |
| NussEtal18 | NussEtal20 | J Exp Psychol Gen 149(10):1919--1934 (2020), 10.1037/xge0000753 | verified |
| SilvEtal19 | SilvEtal19 (same key) | J Neurosci 39(43):8538--8548 (2019), 10.1523/jneurosci.0360-19.2019 | verified |
| ZhenEtal19 | ZhenEtal20 | PNAS 117(33):20244--20253 (2020), 10.1073/pnas.1922248117 | needs_review |

All nine are logged in [`../key-renames.json`](../key-renames.json) with the reason "published version
replaces preprint (user-approved 2026-09-25)"; the eight replacements carry `"kind": "replacement"`, and
SilvEtal19 is logged although its key is unchanged, so citing papers know the entry now points at the article.

The two unresolved entries differ from Crossref on the author field only; DOI, title, journal, volume, number,
pages and year all match:

- **LuriEtal20:** the user's decision keeps "S Keilholz"; Crossref prints "Shella Kheilholz". The published
  title differs from the preprint's and is used ("Questions and controversies in the study of time-varying
  functional connectivity in resting {fMRI}").
- **ZhenEtal20:** the fifth author is written `M A Serrano`. Crossref gives "M. Ángeles". `helpers.reformat_author`
  turns every LaTeX form of an accented initial (`\'{A}`, `{\'A}`, `{\'{A}}`) into `\ ' { A }`, so check_bib
  rejects them; the comparator then reports "Author given names differ".

Both need either the user's sign-off or a code change (formatter, or a comparator rule for accented initials).
They were not approved here: they are not pilot entries.

## signoff001: named-human approvals of the pilot verdicts

[`signoff.py`](signoff.py) takes the 46 pilot keys the user listed (31 marked Correct; 16 marked wrong with a
fix the user specified, AndeEtal66 on both lists; KahaEtal22 and Mink07 under their current keys KahaEtal24
and Mink15). 15 were already metadata_verified. The other 31 were needs_review and were each recorded with
`bibcheck.py crossref approve`, reviewer Jeremy Manning, bound to the entry's current fingerprint. Each note
cites the verdict, the date 2026-09-25 and the evidence files (`../research-pilot-2026-09-24/pilot-proposals.json`
or `followup.json`, and `../apply-2026-09-28/pilot001-proposals.json`); the source is the first evidence URL
behind the entry's current text. `approve` needs no review packet, so none was generated.

Approved (31): AndeEtal66, Arch11a, Bart32, BiddMarl87, BiswEtal95, EichMaca06, Gaut08, GelmEtal13, Hook69,
Hume07, Jame90, KahaEtal24, KahaMill13, Kais90, LeVaEtal10, MikoEtal13b, Mink15, NastEtal20, Pach74, Palm78,
ParaEtal04, PhelEtal18, PiefEtal03, PuceEtal99, RaypWall67, RosePaul90, ScotEtal07, Shan20, SilbEtal01, Youn61,
vanEEtal18.

Already verified, not approved (15): CalvEtal97, Curr04, HogeEtal99, HowaEtal08b, LegeEtal69, LiEtal19,
McCrGrac07, NilsEtal75, RovaVirs79, SchwHump73, Unde48a, Weiz66, XiaoEtal10, ZimaEtal23, ZrenEtal11.

Not included: Beaz96, RamaEtal12b, SommEtal12 and every PR #87/#88 entry. The plan and the notes are in
[`signoff001-plan.json`](signoff001-plan.json); statuses in [`signoff001-results.json`](signoff001-results.json).
A production pipeline run over the 31 keys afterwards made 0 requests and 0 review writes, and every result
was unchanged.

## Code changes needed (files this stage does not own)

1. **Formatter:** `helpers.reformat_author` breaks an accented initial (`M \'{A} Serrano` becomes
   `M \ ' { A } Serrano`). It is why ZhenEtal20 uses `M A`, and the preprint entry ZhenEtal19 carried the broken form.

## Final library counts

`bibcheck.py crossref status cdl.bib`: **6481 entries: human_verified=31, metadata_verified=4476, needs_review=1974**. At the start of this stage: 6481 entries, 4,471 / 2,010.

## Checks after each committed batch

After sfn001, replace001 and signoff001:

- `.bibcheck/validate-current-checkpoint.py` gave an exact restore of 6,481 entries, with 0 repeat imports
  and SQLite ok.
- Full pytest passed (1,538).
- `verification/benchmark/run.py` passed 60/60, with 0 false acceptances.
- `bibcheck.py verify --no-citations` printed "looks good!".
