"""Build pilot001-proposals.json: the user's verdicts on the 50-entry research pilot
(verification/research-pilot-2026-09-24).

- 31 marked correct: pilot-proposals.json changes as proposed, with the house rules decided
  since (lowercase bare DOI; edition written 3\\textsuperscript{rd}; an emptied field is dropped).
- 20 marked wrong: followup.json's resolution, with the user's instructions of 2026-09-25:
  Mink07 cites the 6th edition (LoC 2015458479 + LWW contents list, verified 2026-09-25) and is
  renamed Mink15; Beaz05 is replaced by Beazley's 1996 USENIX Tcl/Tk Workshop SWIG paper
  (Beaz96); NetwLab25 is removed (user); Palm78 is kept unchanged (Claude's choice, not the
  user's: the user asked for a DOI; question open in verification/2026-09-29-user-review/REVIEW.md).
- Keys follow corrected metadata: KahaEtal22 -> KahaEtal24 (year 2022 -> 2024).

    .venv/bin/python verification/apply-2026-09-25e/build_pilot.py
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import load_entries  # noqa: E402

PILOT = ROOT / "verification/research-pilot-2026-09-24"
CORRECT = ("AndeEtal66 Arch11a Bart32 BiddMarl87 CalvEtal97 Curr04 EichMaca06 Gaut08 GelmEtal13 "
           "HowaEtal08b Hume07 KahaEtal22 Kais90 LeVaEtal10 LegeEtal69 McCrGrac07 NastEtal20 NilsEtal75 "
           "Pach74 PhelEtal18 PiefEtal03 RaypWall67 RosePaul90 RovaVirs79 SchwHump73 Shan20 SilbEtal01 "
           "Unde48a Weiz66 Youn61 ZrenEtal11").split()
WRONG = ("BiswEtal95 HogeEtal99 PuceEtal99 LiEtal19 ParaEtal04 vanEEtal18 KahaMill13 ZimaEtal23 AndeEtal66 "
         "MikoEtal13b XiaoEtal10 ScotEtal07 Hook69 Jame90 Mink07 Beaz05 NetwLab25 RamaEtal12b SommEtal12 "
         "Palm78").split()
# Held: the SfN route crashes when it verifies an entry (bibcheck/osf_review.py merge() reads
# result['accepted_doi'], which an SfN approval does not carry: KeyError, pilot001 attempt 1).
HELD = {k: "held: SfN route KeyError 'accepted_doi' in osf_review.merge (code fix needed; see README)"
        for k in ("RamaEtal12b", "SommEtal12")}
RENAMES = {"KahaEtal22": "KahaEtal24", "Mink07": "Mink15"}

MINK_EVIDENCE = [
    {"url": "https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&maximumRecords=1&recordSchema=mods&query=bath.lccn%3D2015458479",
     "quote": "<edition>Sixth edition.</edition> ... <namePart>Wolters Kluwer,</namePart> ... <dateIssued>[2015]</dateIssued> ... "
              "<tableOfContents type=\"Contents\">Functional organization of the basal ganglia -- ..."},
    {"url": "https://shop.lww.com/Parkinson-s-Disease-and-Movement-Disorders/p/9781608311767",
     "quote": "CONTENTS 1. Functional Organization of the Basal Ganglia Jonathan W. Mink ... Edition 6 Publication Date May 21, 2015"},
]
MINK = {
    "author": "J W Mink", "edition": "6\\textsuperscript{th}", "editor": "J Jankovic and E Tolosa",
    "publisher": "Wolters Kluwer", "year": "2015",
}
BEAZ96_RAW = """@inproceedings{Beaz96,
	Address = {Monterey, {CA}},
	Author = {D M Beazley},
	Booktitle = {Fourth Annual {USENIX} {Tcl/Tk} Workshop},
	Title = {{SWIG}: an easy to use tool for integrating scripting languages with {C} and {C++}},
	Year = {1996}}"""
BEAZ96_EVIDENCE = [
    {"url": "https://www.usenix.org/legacy/publications/library/proceedings/tcl96/beazley.html",
     "quote": "Fourth Annual USENIX Tcl/Tk Workshop, 1996 SWIG : An Easy to Use Tool For Integrating Scripting Languages "
              "with C and C++ David M. Beazley Department of Computer Science University of Utah"},
    {"url": "https://www.usenix.org/legacy/publications/library/proceedings/tcl96/",
     "quote": "Fourth Annual USENIX Tcl/Tk Workshop, 1996 July 10-13, 1996 Monterey, California"},
    {"url": "https://www.swig.org/doc.html",
     "quote": "SWIG : An Easy to Use Tool for Integrating Scripting Languages with C and C++ . While a little dated, "
              "this is the first SWIG paper. Presented at the 4th Tcl/Tk Workshop, Monterey, California"},
]


def clean(field, after):
    if after == "":
        return None                     # an emptied field is dropped (Arch11a booktitle)
    if field == "doi" and after:
        return after.lower()            # house: lowercase bare DOI
    if field == "edition" and after == "Third":
        return "3\\textsuperscript{rd}"  # house edition form (user, 2026-09-25)
    return HOUSE_FORM.get((field, after), after)


# check_bib house forms of a proposed value (the formatter's output for the same name).
HOUSE_FORM = {
    ("publisher", "{Cambridge} {University} Press"): "Cambridge {University} Press",   # 16 entries use it
    ("publisher", "Chapman and Hall/{CRC}"): "Chapman and {Hall/CRC}",                # caps.txt HallCRC
}
# DOIs everywhere (user, 2026-09-25): the cited book's own Crossref record.
EXTRA = {
    "GelmEtal13": {"doi": {"before": None, "after": "10.1201/b16018", "evidence": [
        {"url": "https://api.crossref.org/works/10.1201/b16018",
         "quote": "type book; title Bayesian Data Analysis; publisher Chapman and Hall/CRC; issued 2013-11-27; "
                  "authors Gelman, Carlin, Stern, Dunson, Vehtari, Rubin"}]}},
}


def main():
    entries = load_entries(ROOT / "cdl.bib")
    pilot = {p["key"]: p for p in json.loads((PILOT / "pilot-proposals.json").read_text())}
    follow = {r["key"]: r for r in json.loads((PILOT / "followup.json").read_text())}
    assert len(set(CORRECT) | set(WRONG)) == 50 == len(pilot) and set(CORRECT) | set(WRONG) == set(pilot)
    proposals, kept = [], {}
    for key in sorted(pilot):
        entry = entries[key]
        fields = entry["fields"]
        row = {"key": key, "fingerprint": entry["fingerprint"]}
        if key == "NetwLab25":
            row.update(kind="remove", reason="user-approved removal (research-pilot verdict, 2026-09-25)")
            proposals.append(row)
            continue
        if key == "Beaz05":
            row.update(kind="replace", new_key="Beaz96", raw=BEAZ96_RAW, evidence=BEAZ96_EVIDENCE,
                       reason="user 2026-09-25: replace the undated SWIG software citation with Beazley's 1996 "
                              "USENIX Tcl/Tk Workshop paper (new key)")
            proposals.append(row)
            continue
        if key in HELD:
            kept[key] = HELD[key]
            continue
        if key == "Palm78":
            kept[key] = ("Claude: keep unchanged (no DOI for the cited 1978 Erlbaum edition); the user asked for a DOI "
                         "(\"again, add DOI\"), question open")
            continue
        if key == "Mink07":
            source = {f: {"before": fields.get(f), "after": v, "evidence": MINK_EVIDENCE} for f, v in MINK.items()}
            origin = "user 2026-09-25: cite the 6th edition (verified LoC + LWW)"
        elif key in follow and key in WRONG:
            source, origin = follow[key]["changes"], "followup.json"
        else:
            source, origin = pilot[key]["changes"], "pilot-proposals.json (user: correct)"
            if key == "AndeEtal66":
                source, origin = follow[key]["changes"], "followup.json"
        changes = {}
        for field, change in {**source, **EXTRA.get(key, {})}.items():
            after = clean(field, change.get("after"))
            before = fields.get(field)
            if before == after:
                continue                # already in cdl.bib (e.g. HogeEtal99's DOI from adddoi002)
            assert before == change.get("before"), (key, field, before, change.get("before"))
            changes[field] = {"before": before, "after": after, "evidence": change.get("evidence", [])}
        if not changes:
            kept[key] = "no change left: the resolution is already in cdl.bib"
            continue
        row.update(kind="edit", origin=origin, changes=changes)
        if key in RENAMES:
            row["rename"] = RENAMES[key]
        proposals.append(row)
    # caps.txt gains HallCRC so "Hall/CRC" keeps its capitals; the formatter then asks the one
    # other entry with that publisher (Altm99, printed "Chapman \\& Hall/crc") for the same form.
    altm = entries["Altm99"]
    assert altm["fields"]["publisher"] == "Chapman \\& Hall/crc"
    proposals.append({"key": "Altm99", "fingerprint": altm["fingerprint"], "kind": "edit",
                      "origin": "house form: caps.txt HallCRC (formatter consequence of GelmEtal13's publisher)",
                      "changes": {"publisher": {"before": "Chapman \\& Hall/crc", "after": "Chapman \\& {Hall/CRC}",
                                                "evidence": []}}})
    out = {"batch": "pilot001", "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "count": len(proposals),
           "skipped": kept, "proposals": proposals}
    (HERE / "pilot001-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(len(proposals), "proposals;", sum(p["kind"] == "edit" for p in proposals), "edits;",
          {p["key"]: p.get("rename") or p.get("new_key") or p["kind"] for p in proposals if p["kind"] != "edit" or p.get("rename")})


if __name__ == "__main__":
    main()
