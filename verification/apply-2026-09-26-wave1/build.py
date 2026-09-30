"""Build wave1-proposals.json: the user's wave-1 research decisions plus the approved cross-wave
removals, duplicate merges and journal-alias repairs (verification/resolution-plan-2026-09-22/README.md,
sections "Cross-wave decisions" and "Wave 1 decisions", both 2026-09-26).

Inputs (read only):
- ../research-2026-09-25/wave1/merged.json      post-checked final changes, removals and key plans
- ../research-2026-09-25/wave1/decisions/*.json the user's page answers (correct / wrong / unsure)
- ../research-2026-09-25/crosswave/removals.json the 45 approved conference-abstract removals
- ../research-2026-09-25/crosswave/decisions/dup-*.json, j-*.json
- ../journal-alias-audit-2026-09-26.json         journal values for the approved alias repairs

Rules:
- Wave-1 rows marked correct: every ``final_changes`` value and every field in ``removals`` is applied,
  with the key plan (``rename``; ``collision``: the new key plus the existing entry's ``also_rename``).
  Held fields (flags with action ``held``) are not in ``final_changes`` and stay as cited.
- Wave-1 rows marked wrong are handled only by the user's note (all 13 are removals except
  HealKaha14b, replaced by the published HealKaha16).
- Kolo13 (unsure, note: check "EdX"): the Chronicle's own og:title and edx.org's <title> both print
  "edX", so the proposed title is applied.
- DougPeuc73 and Mann06 (unsure, no note) stay unchanged.
- Removed: the 16 unanswered wave-1 no_source rows (rule: no source -> drop); every conference
  abstract (crosswave/removals.json, plus the two SfN abstracts verified by the planner, RamaEtal12b and
  SommEtal12: "drop *all* conference abstracts ... including SfN abstracts verified by the planner");
  the explicit wave-1 drops; the Wechsler editions other than the one kept (see WECHSLER); the
  merged-away half of each of the 9 approved duplicates. No keeper is in wave 1 (the only approved
  wave), so no keeper changes fields. KahaEtal08a keeps its suffix: KahaEtal08c remains.

    .venv/bin/python verification/apply-2026-09-26-wave1/build.py
"""
import glob
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import load_entries  # noqa: E402

RESEARCH = ROOT / "verification/research-2026-09-25"
PLAN = "verification/resolution-plan-2026-09-22/README.md"
DATE = "2026-09-26"

NO_SOURCE_UNANSWERED = ("RaghEtal99 WilsEtal79 WilsEtal80 Khan04 Kaha09 Devl76 Kapl76 ShifRaai92 Cofe71 "
                        "Este76 Kami69 MoscWino92 Greg76 Post76 Adey67b KinsWood75").split()
EXPLICIT_DROPS = ("BranEtal04 ContPrev24 Gede24 GreeEtal13 HeraCE Keck07 Land95 MerzEtal12 Nati24a Nati24b "
                  "LongKaha14").split()
SFN_PLANNER_ABSTRACTS = ["RamaEtal12b", "SommEtal12"]
LEAVE = {"DougPeuc73": "unsure, no note: left unchanged", "Mann06": "unsure, no note: left unchanged"}

# Wech81 (user: "we seem to have several of these entries-- pick ONE and drop the others").
# cdl.bib has four Wechsler test entries by D Wechsler:
#   Wech45 Wechsler memory scale (WMS)                   -> a different test: kept once (wave 1, user: correct)
#   Wech81 Wechsler adult intelligence scale--revised    -> WAIS-R, no source (wave 1)
#   Wech97 Wechsler adult intelligence scale-III         -> WAIS-III (wave 9, not yet reviewed)
#   Wech08 Wechsler adult intelligence scale             -> WAIS-IV, Crossref PsycTESTS 10.1037/t15169-000
#                                                           "Wechsler Adult Intelligence Scale--Fourth Edition"
#                                                           (wave 1, user: correct; edition 4th added)
# WAIS, WAIS-R, WAIS-III and WAIS-IV are editions of one test; the WMS is a separate test.
# Kept: Wech08 (the only WAIS edition the verified research supports) and Wech45.
WECHSLER = {
    "Wech81": "Wechsler: WAIS-R (1981), an earlier edition of the WAIS kept as Wech08 (WAIS-IV, verified); "
              "no source found (user: keep ONE WAIS entry, drop the others)",
    "Wech97": "Wechsler: WAIS-III (1997), an earlier edition of the WAIS kept as Wech08 (WAIS-IV, verified) "
              "(user on Wech81: keep ONE WAIS entry, drop the others)",
}
DUPLICATES = [("CronEtal98c", "CronEtal98a"), ("DawKenj06", "DawDoya06"), ("GoenEtal08", "GoenLogo08"),
              ("KahaEtal08b", "KahaEtal08a"), ("KahaMill10", "KahaMill13"), ("LimoEtal95c", "LimoEtal95a"),
              ("Rugg00", "RuggAlla00"), ("Wayn96", "Dona96"), ("WhitEtal96", "WitmEtal96")]
JOURNAL_REPAIRS = ["DiazEtal06", "Murd68", "MurdVomS67"]

# helpers.check_bib house forms of approved values (the formatter's fixed point for the same text).
HOUSE_FORM = {
    # the formatter lowercases a braced acronym that is not in caps.txt (precedent: CarvEtal22a "({comsnets})")
    ("Kipp01", "booktitle"): "7\\textsuperscript{th} {European} Conference on Speech Communication and Technology ({eurospeech})",
    ("ScheEtal02", "booktitle"): "Proceedings of the 25\\textsuperscript{th} Annual International {ACM} {sigir} Conference on "
                                 "Research and Development in Information Retrieval",
    ("Tulv07", "booktitle"): "Memory and Mind: {A} Festschrift for {Gordon} {H}. {Bower}",
    # the post-check's brace form garbles the name ("{e}ssays ... {h}enry ... {r}oediger")
    ("KleiEtal07b", "booktitle"): "The Foundations of Remembering: Essays in Honor of Henry {L}. Roediger, {III}",
    ("Rayp68", "publisher"): "Ferdinand {Berger}",
    # the source prints "Horn, Austria" (country printed, so it stays); "{AT}" is not an address code
    ("Rayp68", "address"): "Horn, Austria",
}
# Approved fields helpers.check_bib cannot accept; they stay as cited and are reported.
HELD = {
    ("FoodAdmi20a", "force"): "Force is check_bib's skip flag in this repo: without it the formatter rewrites the "
                              "corporate author as '{ U S Food and Drug Administration}'",
    ("FoodAdmi20b", "force"): "Force is check_bib's skip flag in this repo: without it the formatter rewrites the "
                              "corporate author and title ('513({F})(2)')",
    ("BirdEtal09", "publisher"): "the publisher formatter lowercases every form of O'Reilly (O'reilly, {o'reilly}, O'{r}eilly)",
    ("Galt83", "address"): "country dropped per the cross-wave rule, but the address formatter re-adds it (London -> London, {UK})",
    ("Yate66", "address"): "country dropped per the cross-wave rule, but the address formatter re-adds it (London -> London, {UK})",
    ("BancEtal65", "address"): "country dropped per the cross-wave rule, but the address formatter re-adds it (Paris -> Paris, {FR})",
}
# helpers.check_bib's suffix rule after this batch's removals (check_key_suffixes): a lone suffixed key
# loses its suffix and suffixes close up. KahaEtal08b and JacoEtal05b are REUSED for different works.
SUFFIX_RENAMES = {
    "Adey67a": ("Adey67", "Adey67b removed"),
    "HealKaha14a": ("HealKaha14", "HealKaha14b replaced by HealKaha16"),
    "JacoEtal05d": ("JacoEtal05b", "JacoEtal05b removed (conference abstract); key reused for a different work"),
    "JohnRedi07a": ("JohnRedi07", "JohnRedi07b removed (conference abstract)"),
    "KahaEtal08c": ("KahaEtal08b", "KahaEtal08b removed (duplicate of KahaEtal08a); key reused for a different work"),
    "MannEtal09a": ("MannEtal09", "MannEtal09b removed (conference abstract)"),
    "PolyEtal05a": ("PolyEtal05", "PolyEtal05b removed (conference abstract)"),
}

HEALKAHA16_RAW = """@article{HealKaha16,
	Author = {M K Healey and M J Kahana},
	Doi = {10.1037/rev0000015},
	Journal = {Psychological Review},
	Number = {1},
	Pages = {23--69},
	Title = {A four-component model of age-related memory change},
	Volume = {123},
	Year = {2016}}"""


def crossref_healkaha16():
    path = HERE / "crossref" / "10.1037_rev0000015.json"
    record = json.loads(path.read_text())["message"]
    assert record["DOI"].lower() == "10.1037/rev0000015"
    assert record["title"] == ["A four-component model of age-related memory change."]
    assert record["container-title"] == ["Psychological Review"]
    assert (record["volume"], record["issue"], record["page"]) == ("123", "1", "23-69")
    assert record["issued"]["date-parts"][0][0] == 2016
    assert [a["family"] for a in record["author"]] == ["Healey", "Kahana"]
    return [{"url": "https://api.crossref.org/works/10.1037/rev0000015",
             "quote": "title A four-component model of age-related memory change.; container Psychological Review; "
                      "volume 123 issue 1 page 23-69; issued [[2016]]; authors M. Karl Healey, Michael J. Kahana"},
            {"url": "https://doi.org/10.1037/rev0000015", "quote": "HTTP 302 location: https://doi.apa.org/doi/10.1037/rev0000015"}]


def main():
    entries = load_entries(ROOT / "cdl.bib")
    rows = {r["key"]: r for r in json.loads((RESEARCH / "wave1/merged.json").read_text())}
    decisions = {}
    for path in glob.glob(str(RESEARCH / "wave1/decisions/*.json")):
        d = json.loads(Path(path).read_text())
        decisions[d["key"]] = d
    assert len(rows) == 200 and len(decisions) == 184
    unanswered = sorted(set(rows) - set(decisions))
    assert unanswered == sorted(NO_SOURCE_UNANSWERED), unanswered
    assert all(rows[k]["verdict"] == "no_source" for k in unanswered)
    wrong = sorted(k for k, d in decisions.items() if d["verdict"] == "wrong")
    assert wrong == sorted(EXPLICIT_DROPS + ["HealKaha14b", "Wech81"]), wrong
    unsure = sorted(k for k, d in decisions.items() if d["verdict"] == "unsure")
    assert unsure == ["DougPeuc73", "Kolo13", "Mann06"], unsure

    removals_doc = json.loads((RESEARCH / "crosswave/removals.json").read_text())
    abstracts = {e["key"]: e for e in removals_doc["entries"]}
    assert removals_doc["count"] == len(abstracts) == 45
    for a, b in DUPLICATES:
        d = json.loads((RESEARCH / f"crosswave/decisions/dup-{a}-{b}.json").read_text())
        assert d["entry"] == f"{a} → {b}", d
    assert sorted(e for e in entries if e.startswith("KahaEtal08")) == ["KahaEtal08a", "KahaEtal08b", "KahaEtal08c"]

    # ------------------------------------------------------------- removals --
    drops = {}   # key -> (reason, decision source, keeper)

    def drop(key, reason, source, keeper=None):
        assert key in entries, key
        drops.setdefault(key, (reason, source, keeper))

    for key in NO_SOURCE_UNANSWERED:
        drop(key, "no source found (wave 1 no_source, unanswered); rule: any entry without a source is dropped",
             f"{PLAN} (Wave 1 decisions)")
    for key in EXPLICIT_DROPS:
        note = decisions[key]["note"]
        drop(key, f"user (wave 1, wrong): {note!r}", f"research-2026-09-25/wave1/decisions/{key}.json")
    for key, reason in WECHSLER.items():
        drop(key, reason, "research-2026-09-25/wave1/decisions/Wech81.json")
    for key, e in sorted(abstracts.items()):
        drop(key, "conference abstract (approved removal)", "research-2026-09-25/crosswave/removals.json "
             f"({'; '.join(e['decisions'])})")
    for key in SFN_PLANNER_ABSTRACTS:
        f = entries[key]["fields"]
        assert f["booktitle"] == "Society for Neuroscience Abstracts", key
        drop(key, "conference abstract (SfN abstract verified by the planner); rule: drop all conference abstracts",
             f"{PLAN} (Wave 1 decisions; LongKaha14 note)")
    for a, b in DUPLICATES:
        assert b in entries
        drop(a, f"duplicate of {b} (approved merge; keeper unchanged)",
             f"research-2026-09-25/crosswave/decisions/dup-{a}-{b}.json", keeper=b)

    proposals, skipped = [], {}
    for key in sorted(drops):
        proposals.append({"key": key, "fingerprint": entries[key]["fingerprint"], "kind": "remove",
                          "reason": drops[key][0], "decision": drops[key][1],
                          **({"keeper": drops[key][2]} if drops[key][2] else {})})

    # ---------------------------------------------------------- replacement --
    assert "HealKaha16" not in entries and "rev0000015" not in (ROOT / "cdl.bib").read_text()
    proposals.append({"key": "HealKaha14b", "fingerprint": entries["HealKaha14b"]["fingerprint"],
                      "kind": "replace", "new_key": "HealKaha16", "raw": HEALKAHA16_RAW,
                      "reason": "user (wave 1, wrong): 'replace with replacement candidate HealKaha16 "
                                "(Psych Rev 123:23-69, 10.1037/rev0000015)'; published version replaces the "
                                "undated-venue 2014 entry",
                      "evidence": crossref_healkaha16()})

    # ---------------------------------------------------------------- edits --
    renamed_existing, held = {}, {}
    for key in sorted(rows):
        r = rows[key]
        d = decisions.get(key)
        if key in drops or key == "HealKaha14b":
            continue
        if key in LEAVE:
            skipped[key] = LEAVE[key]
            continue
        assert d and (d["verdict"] == "correct" or key == "Kolo13"), (key, d)
        fields = entries[key]["fields"]
        changes = {}
        for c in r["final_changes"]:
            field = c["field"]
            before = fields.get(field) if field != "ENTRYTYPE" else fields["ENTRYTYPE"]
            assert before == c["current"], (key, field, before, c["current"])
            if (key, field) in HELD:
                held[f"{key}.{field}"] = HELD[key, field]
                continue
            after = HOUSE_FORM.get((key, field), c["proposed"])
            changes[field] = {"before": before, "after": after, "source": c["source"],
                              "evidence": c.get("evidence", []),
                              **({"proposed": c["proposed"], "house_form": "check_bib"} if after != c["proposed"] else {})}
        for field, why in r["removals"].items():
            assert field not in changes and field in fields, (key, field)
            if (key, field) in HELD:
                held[f"{key}.{field}"] = HELD[key, field]
                continue
            changes[field] = {"before": fields[field], "after": None, "reason": why}
        plan = r["key_plan"]
        rename = None
        if plan["action"] in ("rename", "collision"):
            rename = plan["new_key"]
        elif plan["action"] == "duplicate":
            raise AssertionError(f"{key}: duplicate not in DUPLICATES")
        for old, new in plan.get("also_rename", {}).items():
            renamed_existing[old] = (new, key)
        if not changes and not rename:
            skipped[key] = ("no change left: every approved change is held (held_fields)"
                            if any(h.startswith(key + ".") for h in held)
                            else "no change: research confirmed the entry as cited")
            continue
        row = {"key": key, "fingerprint": entries[key]["fingerprint"], "kind": "edit",
               "origin": f"wave1 merged.json (user: {d['verdict']}{', note ' + repr(d['note']) if d['note'] else ''})",
               "changes": changes}
        if rename:
            row["rename"] = rename
            row["rename_reason"] = plan.get("rename_reason", "") + (f"; {plan['detail']}" if plan.get("detail") else "")
        proposals.append(row)
    for old, (new, cause) in sorted(renamed_existing.items()):
        assert old in entries and old not in rows and old not in drops
        proposals.append({"key": old, "fingerprint": entries[old]["fingerprint"], "kind": "edit", "changes": {},
                          "rename": new, "origin": f"wave1 key plan of {cause} (collision, house suffix rule)",
                          "rename_reason": f"suffix rule: {cause} becomes {rows[cause]['key_plan']['new_key']}"})

    for old, (new, why) in sorted(SUFFIX_RENAMES.items()):
        assert old in entries and old not in rows and old not in drops and old not in renamed_existing
        assert new not in entries or new in drops, (old, new)
        proposals.append({"key": old, "fingerprint": entries[old]["fingerprint"], "kind": "edit", "changes": {},
                          "rename": new, "origin": "house suffix rule (helpers.check_key_suffixes) after this batch",
                          "rename_reason": f"suffix rule: {why}"})
    assert set(HELD) == {tuple(k.split(".")) for k in held}, set(HELD) ^ {tuple(k.split(".")) for k in held}

    # ------------------------------------------------------ journal repairs --
    audit = json.loads((ROOT / "verification/journal-alias-audit-2026-09-26.json").read_text())
    audit_rows = {x["key"]: x for x in audit["likely_corrupted_cdl_entries"] if x.get("field") == "journal"}
    for key in JOURNAL_REPAIRS:
        d = json.loads((RESEARCH / f"crosswave/decisions/j-{key}.json").read_text())
        assert d["verdict"] == "correct"
        a = audit_rows[key]
        assert a["status"] == "confirmed" and entries[key]["fields"]["journal"] == a["current_journal"], key
        assert key not in rows and key not in drops
        proposals.append({"key": key, "fingerprint": entries[key]["fingerprint"], "kind": "edit",
                          "origin": f"cross-wave j-{key}: correct (journal-alias audit 2026-09-26)",
                          "changes": {"journal": {"before": a["current_journal"], "after": a["probable_true_journal"],
                                                  "evidence": [{"source": "journal-alias-audit-2026-09-26.json",
                                                                "quote": a["evidence"]}]}}})

    assert len({p["key"] for p in proposals}) == len(proposals)
    out = {"batch": "wave1", "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "count": len(proposals),
           "counts": {kind: sum(p["kind"] == kind for p in proposals) for kind in ("edit", "remove", "replace")},
           "renames": {p["key"]: p["rename"] for p in proposals if p.get("rename")},
           "skipped": skipped, "held_fields": held, "proposals": proposals}
    (HERE / "wave1-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: out[k] for k in ("count", "counts", "renames")}), len(skipped), "skipped")


if __name__ == "__main__":
    main()
