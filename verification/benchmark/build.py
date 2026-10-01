"""Freeze 30 named real citations and documentary metadata into a benchmark.

Expected outcomes are explicitly reviewed metadata-support expectations, not a
claim that registry data is infallible or that these papers were human approved.
"""

import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bibcheck"))
from verification import Cache, load_entries

CONTROLS = """YeshEtal21 KaraEtal21 ChiEtal08 ShafEtal14 RaccEtal24 MoraGosh14
ClewEtal19 BoniEtal22 MeinEtal20 ShipAeon19 ParkEtal17 JossTone20 SotoBlan04
HuntKing03 GlerEtal12 KawaEtal21 MoseEtal21 GarrRasm14 SwarEtal12 MeyeEtal19a
McNeEtal06 Golo21 McInEtal18b BeliEtal10 ElSo18""".split()
ABSTAIN = {
    "Thor13": "Book title/volume/publisher differ from the deposited edition metadata.",
    "FranLiu18": "Posted-content record cannot establish a final journal publication.",
    "BirdEtal09": "Search candidates are book reviews, not the cited book itself.",
    "VaswEtal17": "Later posted-content copies cannot establish the 2017 proceedings edition.",
    "BateEtal15b": "Preprint identification/version needs evidence beyond journal metadata matching.",
}


def main():
    entries = load_entries("cdl.bib")
    cache = Cache(".bibcheck/verification.sqlite3")
    cases = []
    mutations = ["year", "title", "pages", "author_order", "doi", "type"]
    try:
        for i, key in enumerate(CONTROLS + list(ABSTAIN)):
            entry = entries[key]
            previous = cache.get("cdl.bib", entry)
            if not previous:
                raise ValueError("Missing cached source evidence for " + key)
            # Only documentary inputs are retained; cached verdicts are not gold.
            previous = {
                "status": "needs_review",
                "candidates": previous["candidates"],
                "attempts": previous.get("attempts", []),
            }
            for candidate in previous["candidates"]:
                for field in ["evidence", "issues", "advisories"]:
                    candidate.pop(field, None)
            case = {
                "id": key + ":original",
                "key": key,
                "fields": entry["fields"],
                "base_fingerprint": entry["fingerprint"],
                "previous": previous,
                "expected": "needs_review" if key in ABSTAIN else "metadata_verified",
                "reason": ABSTAIN.get(
                    key,
                    "All supported citation fields agree with the retained documentary source(s).",
                ),
                "kind": "abstention_control" if key in ABSTAIN else "matching_control",
            }
            cases.append(case)
            changed = copy.deepcopy(case)
            field = mutations[i % len(mutations)]
            fields = changed["fields"]
            if key == "BoniEtal22":
                field = "accent_loss"
                fields["author"] = fields["author"].replace("M\\'{e}ot", "Meot")
            elif key == "YeshEtal21":
                field = "subtitle_loss"
                fields["title"] = fields["title"].split(":")[0]
            elif key == "Thor13":
                field = "edition"
                fields["edition"] = "2"
            elif field == "year":
                fields["year"] = str(int(fields["year"]) + 7)
            elif field == "title":
                fields["title"] += ": deliberately incorrect subtitle"
            elif field == "pages":
                fields["pages"] = "99991--99999"
            elif field == "author_order":
                names = fields["author"].split(" and ")
                fields["author"] = (
                    " and ".join(reversed(names)) if len(names) > 1 else "Wrong Author"
                )
            elif field == "doi":
                fields["doi"] = "10.99999/bibcheck-deliberately-wrong"
            elif field == "type":
                fields["ENTRYTYPE"] = (
                    "book" if fields["ENTRYTYPE"] != "book" else "article"
                )
            changed.update(
                id=key + ":" + field,
                expected="needs_review",
                kind="deliberate_perturbation",
                reason="Deliberately altered "
                + field
                + "; original documentary evidence is unchanged.",
            )
            if fields == case["fields"]:
                raise ValueError("Perturbation did not change " + key)
            cases.append(changed)
    finally:
        cache.close()
    target = Path(__file__).parent / "cases.json"
    target.write_text(
        json.dumps(
            {"schema": 1, "works": 30, "cases": cases}, ensure_ascii=False, indent=2
        )
        + "\n"
    )
    print(f"Wrote {len(cases)} cases from 30 real citations")


if __name__ == "__main__":
    main()
