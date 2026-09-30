# Follow-up to the surname decisions (batch followup0930d, 2026-09-30)

Batch surnames0930c ([../apply-2026-09-30c-surnames](../apply-2026-09-30c-surnames/README.md))
left three items with the user. The orchestrating session asked: (1) keep WatkPeyn83 as
Peynircio\u{g}lu, since `\dot` is a math-only accent and plain i is the dotted i? (2) use
"D'Agata" per the erratum 10.1007/s00426-016-0761-6? (3) re-approve FreuEtal09, whose erratum
concerns only a Methods sentence? The user's answer (2026-09-30, relayed verbatim):

> 1. yes / 2. use D'Agata / 3. Re-confirm

## Applied

1. **WatkPeyn83**: no change. The hold is withdrawn; the entry keeps "Z F Peynircio\u{g}lu" and
   its `metadata_verified` result (unchanged by this batch, asserted).
2. **LatiEtal10** author 7 "F Dagata" → "F D'Agata", the name as corrected by the publisher's
   erratum. Evidence:
   - Crossref, https://api.crossref.org/works/10.1007/s00426-016-0761-6 (fetched 2026-09-30,
     [evidence/](evidence/)): title "Erratum to: Route and survey processing of topographical
     memory during navigation", `update-to` 10.1007/s00426-010-0276-5, type "correction".
   - Publisher's correction text, https://link.springer.com/article/10.1007/s00426-016-0761-6,
     as quoted in the research evidence of wave 6 (batch-051): "Unfortunately, in the original
     publication, the name of the seventh author was incorrectly published as Federico Dagata.
     However, the correct name should read as Federico D'Agata." (Springer's page returned a
     bot-check page to an automated fetch on 2026-09-30, so it was not re-fetched here.)
   - PubMed 20174930 via Europe PMC (fetched 2026-09-30): Erratum in "Psychol Res. 2016
     Jul;80(4):727. doi: 10.1007/s00426-016-0761-6", note "Dagata, Federico [corrected to
     D’Agata, Federico]".
3. **FreuEtal09**: `crossref approve`, reviewer "Jeremy Manning", source the user's answer
   above (item 3), note "User re-confirmed 2026-09-30; the erratum (10.1001/archneurol.2011.75)
   corrects a Methods sentence, not the citation."

LatiEtal10 returns to its text before surnames0930c, so its content fingerprint is the one its
earlier research-evidence verification was recorded for. If the pipeline accepts it on that
record no approval is written; otherwise it is approved with the erratum as evidence
([apply.py](apply.py), `APPROVALS`).

## Run

    python verification/apply-2026-09-30d-followup/apply.py --apply
    python verification/apply-2026-09-30c-surnames/restore_check.py <new empty database path>

Log: [run.log](run.log); results: [followup0930d-results.json](followup0930d-results.json).

| Stage | Requests | Review writes | Result |
|-|-|-|-|
| pipeline (FreuEtal09, LatiEtal10) | 0 | 0 | LatiEtal10 `metadata_verified` (research evidence, the record its D'Agata text was verified on before); FreuEtal09 `needs_review` |
| approvals | 0 | 1 | FreuEtal09 `human_verified`; LatiEtal10 needed none; approving LatiEtal10's "Dagata" text (old fingerprint) is refused ("Entry changed since review; approval rejected"); WatkPeyn83 unchanged |
| repeat | 0 | 0 | identical |

Library after the batch: `6384 entries: human_verified=36, metadata_verified=6348`
(needs_review=0). A restore of the exported baseline into an empty database equals the live
results for every entry.
