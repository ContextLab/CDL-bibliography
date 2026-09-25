"""Build held001-proposals.json: the 30 edits held in stage 2A (classes001 ``skipped``),
re-expressed under the user's rules (resolution-plan-2026-09-22/README.md):

- keys always follow corrected metadata: a key the ID rule demands is a rename, checked
  unused in cdl.bib and logged in verification/key-renames.json;
- editions in house form ``N\\textsuperscript{..}``; catalogue titles without LoC's " : "
  statement of responsibility; editors in initials; ``{EEG}`` braced (house formatter);
- house address form ``City, {ST}`` stays: catalogue L-class edits that only remove the
  state/country suffix are dropped; a city change is kept in house form;
- RuggEtal96 stays held (single-source surname change without corroboration).

Every changed value comes from the frozen classes001 proposal (source-stated); only its
form changes. A proposal is kept only when helpers.check_bib then accepts the entry
(with the rename); anything else stays held.

    .venv/bin/python verification/apply-2026-09-26b/build_held.py
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import os  # noqa: E402
os.chdir(ROOT)
from verification import load_entries  # noqa: E402
import helpers  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("apply0923", ROOT / "verification/apply-2026-09-23/apply.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

SOURCE = ROOT / "verification/apply-2026-09-26/classes001-proposals.json"
EDITIONS = {"1": "1\\textsuperscript{st}", "2": "2\\textsuperscript{nd}", "3": "3\\textsuperscript{rd}"}

# Form changes under the user's rules; the values themselves are the source-stated ones.
FORM = {
    "HastEtal01": {"title": ("The elements of statistical learning: data mining, inference, and prediction",
                             "LoC title 'The elements of statistical learning : data mining, inference, and "
                             "prediction : with 200 full-color illustrations' without the ISBD ' : ' and its "
                             "statement 'with 200 full-color illustrations'")},
    "vandGlas00": {"editor": ("W J van der Linden and C A W Glas", "editors in initials (house form)")},
    "Free75": {"title": ("Mass action in the nervous system: examination of the neurophysiological basis of "
                         "adaptive behavior through the {EEG}", "{EEG} braced (house formatter)")},
    "UndeShul60": {"address": ("Chicago, {IL}", "LoC city Chicago in house form City, {ST}")},
    "TulvDona72": {"address": ("New York, {NY}", "LoC city New York in house form City, {ST}")},
}
HELD_BY_RULE = {"RuggEtal96": "single-source surname change 'G Patchin' -> 'G R Patching' lacks corroboration "
                              "(user rule 2026-09-25; stays held)"}


def suffix_only(before, after):
    """True when an address edit only drops the house ', {ST}'/', {UK}' suffix."""
    return bool(before) and bool(after) and re.fullmatch(re.escape(after) + r", \{[A-Z]{2,3}\}", before) is not None


def reshape(row):
    """Return (changes, notes, drop_reason)."""
    key, changes, notes = row["key"], deepcopy(row["changes"]), {}
    if key in HELD_BY_RULE:
        return None, None, HELD_BY_RULE[key]
    address = changes.get("address")
    if address and suffix_only(address["before"], address["after"]):
        del changes["address"]
        notes["address"] = "dropped: catalogue edit only removes the house {ST}/{UK} suffix (house form stays)"
    for field, (value, why) in FORM.get(key, {}).items():
        changes[field]["after"] = value
        notes[field] = why
    edition = changes.get("edition")
    if edition and re.fullmatch(r"\d+", edition["after"]):
        n = edition["after"]
        edition["after"] = EDITIONS.get(n, n + "\\textsuperscript{th}") if not n.endswith(("11", "12", "13")) \
            else n + "\\textsuperscript{th}"
        notes["edition"] = f"LoC edition {n} in house form"
    if not changes:
        return None, notes, "every change dropped: " + "; ".join(notes.values())
    return changes, notes, None


def formatter_demands(raw):
    with tempfile.NamedTemporaryFile("w", suffix=".bib", dir=ROOT / ".bibcheck", delete=False) as f:
        f.write(raw + "\n")
    try:
        errors, _ = helpers.check_bib(f.name, verbose=False)
    finally:
        os.unlink(f.name)
    return errors


def main():
    entries = load_entries(ROOT / "cdl.bib")
    text = (ROOT / "cdl.bib").read_text()
    held_rows = json.loads(SOURCE.read_text())["skipped"]["guard_or_fingerprint"]
    assert len(held_rows) == 30
    proposals, held, dropped = [], [], []
    for row in held_rows:
        key = row["key"]
        entry = entries[key]
        for field, change in row["changes"].items():
            assert entry["fields"].get(field) == change["before"], (key, field)
        changes, notes, reason = reshape(row)
        if reason:
            (held if key in HELD_BY_RULE else dropped).append({"key": key, "class": row["class"],
                                                               "changes": row["changes"], "reason": reason})
            continue
        new = base.apply_change_all(entry["raw"], {"changes": changes})
        demands = formatter_demands(new).get(key, {})
        rename = demands.pop("ID", None)
        if rename:
            assert rename not in entries and not re.search(r"\b" + re.escape(rename) + r"\b", text), rename
            new = new.replace("{" + key + ",", "{" + rename + ",", 1)
            again = formatter_demands(new)
            demands.update(again.get(rename, {}))
        if demands:
            held.append({"key": key, "class": row["class"], "changes": changes,
                         "reason": "check_bib (house formatter) still demands " + json.dumps(demands, ensure_ascii=False)})
            continue
        proposal = {"key": key, "fingerprint": entry["fingerprint"], "class": row["class"], "changes": changes,
                    "stated_by": {f: row["stated_by"][f] for f in changes}, "form_notes": notes,
                    "approved_in": "verification/apply-2026-09-26/classes001-proposals.json (skipped)"}
        if rename:
            proposal["rename"] = rename
            proposal["rename_reason"] = ("ID rule after the corrected " +
                                         ", ".join(f for f in changes if f in {"author", "editor", "year"}))
        proposals.append(proposal)
    out = {"batch": "held001", "count": len(proposals),
           "renames": {p["key"]: p["rename"] for p in proposals if p.get("rename")},
           "skipped": {"held": held, "dropped_house_address": dropped}, "proposals": proposals}
    (HERE / "held001-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"proposals": len(proposals), "renames": out["renames"],
                      "held": [h["key"] + ": " + h["reason"] for h in held],
                      "dropped": [d["key"] for d in dropped]}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
