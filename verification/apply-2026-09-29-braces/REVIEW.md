# Human-approved entries awaiting review (braces0929, 2026-09-29)

> **Superseded (2026-09-29).** Use [../2026-09-29-user-review/REVIEW.md](../2026-09-29-user-review/REVIEW.md) instead.
> An attribution audit found that the approval notes quoted below overstate what the user approved.
> For MikoEtal13b and Mink15, "the fix as applied ... is user-approved" is not true: the user marked
> the pilot rows wrong and never saw the applied text. Both approvals were revoked
> (`verification/revocations.jsonl`). Do not run the approve commands below, because they reuse
> those notes. The new REVIEW.md gives current commands with a note for you to fill in.

The braces batch changed only braces in these entries, but each human approval was bound
to the old text, so it lapsed to `needs_review`. Nothing here was re-approved. To restore
an approval after checking the entry, run its `crossref approve` command from the repo root.
Each command reuses the old approval's reviewer and source; the note records the brace change.
Review packets: `review-packet-<KEY>.json` in this folder.

## Bart32

Status now: `needs_review`. Old fingerprint `v2:b03771169d58c48f0cf749165c4238e052587ef0a28c71ce4ec628d856405fb1`, new fingerprint `v2:537f60bccc4037785323fe93bac5b5b37d46b55052006916a4520aa9c9ca8a58`.

- publisher before: `Cambridge {University} Press`
- publisher after: `Cambridge University Press`

Lapsed approval:

- reviewer: Jeremy Manning
- source: https://lccn.loc.gov/39016008/mods
- note: Research-pilot verdict by Jeremy Manning, 2026-09-25: marked Correct on the research-pilot page. Approval bound to the entry's current text. Evidence: verification/research-pilot-2026-09-24/pilot-proposals.json, verification/apply-2026-09-25e/pilot001-proposals.json. No automated route verifies it (closest-source issue: No unique, fully matching catalogue edition).

Entry now:

```bibtex
@book{Bart32,
	Author = {F C Bartlett},
	Publisher = {Cambridge University Press},
	Title = {Remembering: a study in experimental and social psychology},
	Year = {1932}}
```

Approve command:

```sh
python bibcheck.py crossref approve Bart32 --fingerprint v2:537f60bccc4037785323fe93bac5b5b37d46b55052006916a4520aa9c9ca8a58 --reviewer 'Jeremy Manning' --source https://lccn.loc.gov/39016008/mods --note 'Re-approval after braces0929 (2026-09-29): only braces around ordinary words changed (publisher). Previous approval: Research-pilot verdict by Jeremy Manning, 2026-09-25: marked Correct on the research-pilot page. Approval bound to the entry'"'"'s current text. Evidence: verification/research-pilot-2026-09-24/pilot-proposals.json, verification/apply-2026-09-25e/pilot001-proposals.json. No automated route verifies it (closest-source issue: No unique, fully matching catalogue edition).'
```

## KahaEtal24

Status now: `needs_review`. Old fingerprint `v2:a194218093f5f5cc4d34d9b5ba8505976b45bdfd943bde1471a2b3bb66fe2d3d`, new fingerprint `v2:825421e71de43c17a96c3dfe31b0a92cc9ff3f042c106f311b8776633a37baff`.

- booktitle before: `The {Oxford} Handbook of Human Memory`
- booktitle after: `The Oxford Handbook of Human Memory`
- publisher before: `{Oxford} {University} Press`
- publisher after: `Oxford University Press`

Lapsed approval:

- reviewer: Jeremy Manning
- source: https://api.crossref.org/works/10.1093/oxfordhb/9780190917982.013.2
- note: Research-pilot verdict by Jeremy Manning, 2026-09-25: marked Correct on the research-pilot page (pilot key KahaEtal22, renamed per the key rule). Approval bound to the entry's current text. Evidence: verification/research-pilot-2026-09-24/pilot-proposals.json, verification/apply-2026-09-25e/pilot001-proposals.json. No automated route verifies it (closest-source issue: No unambiguous, fully supported metadata match).

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

Approve command:

```sh
python bibcheck.py crossref approve KahaEtal24 --fingerprint v2:825421e71de43c17a96c3dfe31b0a92cc9ff3f042c106f311b8776633a37baff --reviewer 'Jeremy Manning' --source https://api.crossref.org/works/10.1093/oxfordhb/9780190917982.013.2 --note 'Re-approval after braces0929 (2026-09-29): only braces around ordinary words changed (booktitle, publisher). Previous approval: Research-pilot verdict by Jeremy Manning, 2026-09-25: marked Correct on the research-pilot page (pilot key KahaEtal22, renamed per the key rule). Approval bound to the entry'"'"'s current text. Evidence: verification/research-pilot-2026-09-24/pilot-proposals.json, verification/apply-2026-09-25e/pilot001-proposals.json. No automated route verifies it (closest-source issue: No unambiguous, fully supported metadata match).'
```

## MikoEtal13b

Status now: `needs_review`. Old fingerprint `v2:9e20e9893441cd1e17b3c9039e1a80a49334cf24480416772d4f55eb67105d37`, new fingerprint `v2:6746ff202cde361fa04295b9292b69c25b62be034649dddc3a907602e30f2784`.

- booktitle before: `Proceedings of the Conference of the North {American} Chapter of the Association for Computational Linguistics: Human Language Technologies`
- booktitle after: `Proceedings of the Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies`

Lapsed approval:

- reviewer: Jeremy Manning
- source: https://aclanthology.org/N13-1090/
- note: Research-pilot verdict by Jeremy Manning, 2026-09-25: marked wrong on the research-pilot page with a fix the user specified; the fix as applied (pilot001, commit 689de07) is user-approved. Approval bound to the entry's current text. Evidence: verification/research-pilot-2026-09-24/followup.json, verification/apply-2026-09-25e/pilot001-proposals.json. No automated route verifies it (closest-source issue: address: missing evidence or mismatch).

Entry now:

```bibtex
@inproceedings{MikoEtal13b,
	Address = {Atlanta, {GA}},
	Author = {T Mikolov and W-T Yih and G Zweig},
	Booktitle = {Proceedings of the Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies},
	Pages = {746--751},
	Publisher = {Association for Computational Linguistics},
	Title = {Linguistic regularities in continuous space word representations},
	Year = {2013}}
```

Approve command:

```sh
python bibcheck.py crossref approve MikoEtal13b --fingerprint v2:6746ff202cde361fa04295b9292b69c25b62be034649dddc3a907602e30f2784 --reviewer 'Jeremy Manning' --source https://aclanthology.org/N13-1090/ --note 'Re-approval after braces0929 (2026-09-29): only braces around ordinary words changed (booktitle). Previous approval: Research-pilot verdict by Jeremy Manning, 2026-09-25: marked wrong on the research-pilot page with a fix the user specified; the fix as applied (pilot001, commit 689de07) is user-approved. Approval bound to the entry'"'"'s current text. Evidence: verification/research-pilot-2026-09-24/followup.json, verification/apply-2026-09-25e/pilot001-proposals.json. No automated route verifies it (closest-source issue: address: missing evidence or mismatch).'
```

## Mink15

Status now: `needs_review`. Old fingerprint `v2:0c83ad54efbd8e0b9d5861cb788114a53c60bde8fc5ad1dcef171b9dbbc5c53b`, new fingerprint `v2:91136b0010930ba1ba3850e1ef80d253f27f73cdf34a9149154ce40ad27e253c`.

- booktitle before: `{Parkinson's} Disease and Movement Disorders`
- booktitle after: `Parkinson's Disease and Movement Disorders`

Lapsed approval:

- reviewer: Jeremy Manning
- source: https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&maximumRecords=1&recordSchema=mods&query=bath.lccn%3D2015458479
- note: Research-pilot verdict by Jeremy Manning, 2026-09-25: marked wrong on the research-pilot page with a fix the user specified; the fix as applied (pilot001, commit 689de07) is user-approved (pilot key Mink07, renamed per the key rule). Approval bound to the entry's current text. Evidence: verification/research-pilot-2026-09-24/followup.json, verification/apply-2026-09-25e/pilot001-proposals.json. No automated route verifies it (closest-source issue: No unambiguous, fully supported metadata match).

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

Approve command:

```sh
python bibcheck.py crossref approve Mink15 --fingerprint v2:91136b0010930ba1ba3850e1ef80d253f27f73cdf34a9149154ce40ad27e253c --reviewer 'Jeremy Manning' --source 'https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&maximumRecords=1&recordSchema=mods&query=bath.lccn%3D2015458479' --note 'Re-approval after braces0929 (2026-09-29): only braces around ordinary words changed (booktitle). Previous approval: Research-pilot verdict by Jeremy Manning, 2026-09-25: marked wrong on the research-pilot page with a fix the user specified; the fix as applied (pilot001, commit 689de07) is user-approved (pilot key Mink07, renamed per the key rule). Approval bound to the entry'"'"'s current text. Evidence: verification/research-pilot-2026-09-24/followup.json, verification/apply-2026-09-25e/pilot001-proposals.json. No automated route verifies it (closest-source issue: No unambiguous, fully supported metadata match).'
```

## Youn61

Status now: `needs_review`. Old fingerprint `v2:971f9d175dd98c45b4064ba3b647e3e119539e72c962a65c1ae69656565079c0`, new fingerprint `v2:f5ef047a64900114b437a210e4d2cac25b42c5547309eaadb3fb8e93fbeeeb40`.

- journal before: `The {American} Journal of Psychology`
- journal after: `The American Journal of Psychology`

Lapsed approval:

- reviewer: Jeremy Manning
- source: https://api.crossref.org/works/10.2307/1419662
- note: Research-pilot verdict by Jeremy Manning, 2026-09-25: marked Correct on the research-pilot page. Approval bound to the entry's current text. Evidence: verification/research-pilot-2026-09-24/pilot-proposals.json, verification/apply-2026-09-25e/pilot001-proposals.json. No automated route verifies it (closest-source issue: No unambiguous, fully supported metadata match).

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

Approve command:

```sh
python bibcheck.py crossref approve Youn61 --fingerprint v2:f5ef047a64900114b437a210e4d2cac25b42c5547309eaadb3fb8e93fbeeeb40 --reviewer 'Jeremy Manning' --source https://api.crossref.org/works/10.2307/1419662 --note 'Re-approval after braces0929 (2026-09-29): only braces around ordinary words changed (journal). Previous approval: Research-pilot verdict by Jeremy Manning, 2026-09-25: marked Correct on the research-pilot page. Approval bound to the entry'"'"'s current text. Evidence: verification/research-pilot-2026-09-24/pilot-proposals.json, verification/apply-2026-09-25e/pilot001-proposals.json. No automated route verifies it (closest-source issue: No unambiguous, fully supported metadata match).'
```
