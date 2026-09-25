# PR check, 2026-09-25: PRs #88 and #87 as tests of the verification machinery

Both PR branches were read with `git show`. Each was checked against its merge base
with master (30df0bb) using the `bib-crossref-verification` working-tree code:
`crossref verify <pr.bib> --against <base.bib> --auto-review` with a scratch cache.
No tracked file, the main cdl.bib, or the main cache was touched. Per-entry
results, with the source mismatch and a diagnosis for each unverified entry, are in
`pr88.json` and `pr87.json`. `status_after_entry_fixes` is the status after a
second scratch run in which the ENTRY-WRONG fixes and the missing DOIs were applied.

## Results

| PR | Checked | Verified | Needs review | Repeat run |
|-|-|-|-|-|
| #88 nightwarden-refs | 47 (31 new, 16 edited) | 35 | 12 | 0 network requests, same statuses |
| #87 add-feature-representation-refs | 30 of 31 new (YangEtal25a skipped as a key-only rename) | 18 | 12 (+1 pending) | 0 network requests, same statuses |

After the entry fixes: #88 had 37 verified (KonkEtal21 and KothEtal25 now pass) and #87 had
20 verified (YangEtal25a and SchaAbel77 now pass).

## Machinery defects found (false rejections or gaps)

1. The author comparator treats degrees in Crossref's `suffix` field as name suffixes
   (`MD, FACP`, `PhD`, `Ph. D.`, `BA`), which gives "Author suffix differs". Affected: FeliEtal98, Schr03.
2. A journal name with a leading "The" does not match, and a zero-padded issue (`09`) does not match `9`. Affected: PigeEtal12.
3. A benign `has-preprint` relation on the published article still blocks as "related versions". Affected: ChenEtal21, SchwEtal22.
4. Proceedings names: Crossref booktitles carry the year and acronym (`2017 IEEE Conference ... (CVPR)`), which the house form omits. Affected: BauEtal17, DalaTrig05, HeusMann18, ReimGure19.
5. Container titles that include a subtitle or series are not normalized (`Intracranial EEG`, `Automata Studies. (AM-34)`, `..., Two Volume Pack`). Affected: Mann23, Klee56, Mann24.
6. The publisher's same-firm rule is not applied to Crossref publishers (`Springer International Publishing`), and dotted acronyms are not normalized (LoC `M.I.T. Press`). Affected: Mann23, Chom65.
7. Journals whose names changed historically: Crossref gives the current `IEEE Transactions on Information Theory` for the 1956 `IRE` volume. Affected: Chom56.
8. Print-year rule: when the print year (2026) differs from the issued/online year (2025), the entry is not accepted. The Crossref byline is also duplicated at the source. Affected: LantEtal26.
9. The catalogue edition check rejects the house edition form `3\textsuperscript{rd}` ("Unknown LaTeX command"). Affected: Sips13.
10. The bibcheck formatter crashes on a source-backed article number `IMAG.a.136` ("page numbers are ambiguous"). The failure is hidden by a bare `except` in `bibcheck.py verify`. Affected: KothEtal25.
11. The formatter does not detect duplicate `Doi` fields in one entry. This happens in the #88 merge (OwenMann24, HeusEtal21).
12. The latest-version rule for preprints is not enforced. WangEtal22 verifies with year 2022 even though the arXiv v2 is dated 2024-02-22 and the repository reports version 2.
13. Verification succeeds without adding available DOIs. Affected: 4 entries in #88 and 16 in #87.
14. Known gaps: there is no comparison for DataCite/Zenodo software (Spee22, Mann26), PsyArXiv (FitzEtal26a), ACL Anthology (ReimGure19, where Crossref's pages 3980-3990 are wrong and ACL gives "Pages: 3982–3992"), or web pages (Hass16).

## Merge prediction against bib-crossref-verification (HEAD 4cb7741; same result at 04668ee)

- #88: 1 textual conflict (MannEtal11 author line). HEAD has full given names
  (`Jeremy R Manning and Sean M Polyn ...`, from db310f3), which violates the initials rule. The PR has
  `J R Manning and S M Polyn and G H Baltuch ...` plus a DOI. The merge also silently produces duplicate
  `Doi` fields in OwenMann24 and HeusEtal21: HEAD appended the DOI at the end and the PR inserted it alphabetically.
  HEAD's FitzEtal26 page fix (2055) is already in the PR's FitzEtal26b.
- #87: merges cleanly (cdl.bib and bibcheck/caps.txt `IRE`). Without the caps.txt line the formatter fails on Chom56.
