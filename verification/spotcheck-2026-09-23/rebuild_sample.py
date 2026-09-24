"""Rebuild the spot-check sample after the 2026-09-24 rule fixes.

Keeps every sampled key. An entry whose proposal is unchanged keeps its verdict;
one whose proposal changed is marked "revised" (its earlier verdict is shown but
no longer counts); one with no proposal any more is dropped. Adds five seeded
draws from the TWO-SOURCE proposals that are new since the fixes (they reorder or
add authors). Each changed field lists the sources that state its new value.
Writes sample.json (the previous one is kept as sample-v1.json).
"""
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SEED = 20260924
NEW_TWO_SOURCE = 5


def main():
    old_path = HERE / "sample.json"
    v1 = HERE / "sample-v1.json"
    if not v1.exists():
        v1.write_text(old_path.read_text())
    old = json.loads(v1.read_text())
    props = json.loads((ROOT / "verification/fixes-2026-09-24/proposals.json").read_text())["proposals"]
    by_key = {}
    for p in props:
        entry = by_key.setdefault(p["key"], {**p, "changes": {}, "stated_by": {}})
        entry["changes"].update(p.get("changes") or {})
        entry["stated_by"].update(p.get("stated_by") or {})
    sizes = {}
    for p in props:
        sizes[p["class"]] = sizes.get(p["class"], set()) | {p["key"]}
    diff = json.loads((ROOT / "verification/fixes-2026-09-24/diff.json").read_text())["entries"]
    sample, dropped = [], []
    for s in old["sample"]:
        if s["origin"] == "catalogue":
            sample.append(dict(s, revised=False))
            continue
        new = by_key.get(s["key"])
        if not new:
            dropped.append(s["key"])
            continue
        revised = new["changes"] != s["changes"]
        sample.append(dict(s, cls_before=s["class"], **{
            "class": new["class"], "class_size": len(sizes[new["class"]]),
            "changes": new["changes"], "stated_by": new["stated_by"], "revised": revised,
            "previous_changes": s["changes"] if revised else None}))
    taken = {s["key"] for s in sample}
    new_keys = sorted(row["key"] for row in diff
                      if not row.get("before") and not row.get("class_before")
                      and by_key.get(row["key"], {}).get("class") == "TWO-SOURCE" and row["key"] not in taken)
    rng = random.Random(SEED)
    template = old["sample"][0]
    for key in rng.sample(new_keys, min(NEW_TWO_SOURCE, len(new_keys))):
        p = by_key[key]
        sample.append({"id": "", "key": key, "class": "TWO-SOURCE", "stratum": "new-two-source",
                       "class_size": len(sizes["TWO-SOURCE"]), "origin": "article", "rule": p.get("rule"),
                       "source": p.get("source"), "doi": p.get("doi"), "pubmed_id": p.get("pubmed_id"),
                       "catalogue_record": None, "fields": None, "changes": p["changes"],
                       "stated_by": p["stated_by"], "evidence": None, "revised": False})
    # Fill fields for new draws from the current bibliography.
    import sys
    sys.path.insert(0, str(ROOT / "bibcheck"))
    from verification import load_entries
    entries = load_entries(ROOT / "cdl.bib")
    for s in sample:
        if s["key"] in entries:
            s["fields"] = {k: v for k, v in entries[s["key"]]["fields"].items() if k != "ID"}
    for i, s in enumerate(sample, 1):
        s["id"] = f"{i:02d}"
    old_path.write_text(json.dumps({"seed": old["seed"], "reseed": SEED, "design": __doc__.strip(),
                                    "dropped": dropped, "sample": sample}, indent=1, ensure_ascii=False) + "\n")
    print(len(sample), "entries;", sum(s["revised"] for s in sample), "revised;", "dropped", dropped,
          "; new two-source draws", [s["key"] for s in sample if s["stratum"] == "new-two-source"],
          "; candidates", len(new_keys))


if __name__ == "__main__":
    main()
