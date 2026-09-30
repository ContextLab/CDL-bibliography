# Rules to confirm (2026-09-29)

These six rules were recorded as your decisions, but they were Claude's. You chose "Relabel, you confirm (Recommended)" (AskUserQuestion, 2026-09-29 17:51 EDT). **You answered on 2026-09-30 (EDT)**; each answer is quoted below the question. Rules 1, 2, 3, 4 and 6 are confirmed; rule 5 is replaced by your rule. The decision log records the outcome under "Rules Claude adopted, then confirmed or replaced by the user (2026-09-30)": [../resolution-plan-2026-09-22/README.md](../resolution-plan-2026-09-22/README.md).

1. **Source-stated values only:** should every value a correction proposes have to be stated by an authoritative source record for that work, never carried over from the citation itself? (yes/no)
   - **Answer (2026-09-30):** "yes". Confirmed.
2. **Page ranges never shortened:** should a correction never replace a cited page range with a shorter one (for example 483--490 → 483), even when a source prints only the first page? (yes/no)
   - **Answer (2026-09-30):** "yes". Confirmed.
3. **`City, {ST}` addresses:** should US addresses keep the house form `City, {ST}` (for example `New York, {NY}`), so that catalogue edits that only drop the state are not applied? (yes/no)
   - **Answer (2026-09-30):** "yes". Confirmed.
4. **PsyArXiv DOI in `doi`:** should a PsyArXiv DOI stored in `volume` be moved to the `doi` field, with `volume` dropped (ZimaEtal23)? (yes/no)
   - **Answer (2026-09-30):** "yes". Confirmed.
5. **Surname corroboration:** should a surname change that only one source supports be held until a second source, or your sign-off, confirms it (for example MeyeEtal88 "Kounios" vs Crossref's "Kounois")? (yes/no)
   - **Answer (2026-09-30):** "one source is sufficient; manual entry is the weakest part. notify user if mismatch is found and ask how they want to resolve it". Replaces the corroboration rule: a mismatch is never resolved automatically. Implemented in [../apply-2026-09-30-surnames/](../apply-2026-09-30-surnames/README.md); the mismatches found are in [../2026-09-30-user-review/SURNAMES.md](../2026-09-30-user-review/SURNAMES.md).
6. **Aust14 publisher:** is Aust14's publisher "T Egerton" (Library of Congress: "Printed for T. Egerton, Military Library, Whitehall"), replacing "T Eagerton"? (yes/no)
   - **Answer (2026-09-30):** '"T Egerton" is correct -- the "." after "T" and the "..." after "Egerton" are just formatting differences'. Confirmed; Aust14 already reads "T Egerton".

Folder renames: "yes to folder renames" (2026-09-30) confirms the renames of the eight misdated `apply-*` folders (commit 856d637).
