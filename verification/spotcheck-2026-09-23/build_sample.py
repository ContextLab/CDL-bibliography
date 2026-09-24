"""Draw the pooled spot-check sample for the Phase 0 correction proposals.

Design (user decisions, 2026-09-22/23): the user reviews ~50 entries in total.
- 10 random entries from S1-TWO-FIELDS-RISKY and 10 from S1-AUTHOR-NAMES
  (the two riskiest article classes);
- 30 pooled draws across every other article and catalogue class: one per
  class, the remainder proportional to class size.
A wrong proposal in a sample reopens its whole class's rule.

Reads proposals from the phase0 and catalogue folders, entry fields from the
bibliography at the commit the proposals were generated against, and source
evidence from the main cache opened read-only. Writes sample.json only.
"""
import json
import random
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import Cache, load_entries  # noqa: E402

COMMIT = "964405a"
SEED = 20260923
RISKY = {"S1-TWO-FIELDS-RISKY": 10, "S1-AUTHOR-NAMES": 10}
POOLED = 30


class ReadOnlyCache(Cache):
    def __init__(self, filename):
        self.path = Path(filename)
        self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)


def authors(source):
    if isinstance(source, list):
        return "; ".join(" ".join(x for x in (a.get("given"), a.get("family") or a.get("name")) if x)
                         if isinstance(a, dict) else str(a) for a in source)
    return source


def evidence(result, doi, pmid):
    for cand in (result or {}).get("candidates", []):
        if (doi and (cand.get("doi") or "").lower() == doi.lower()) or (pmid and str(cand.get("pmid") or cand.get("pubmed_id") or "") == str(pmid)):
            rows = {}
            for field, ev in (cand.get("evidence") or {}).items():
                src = ev.get("source")
                rows[field] = {"cited": ev.get("local"), "source": authors(src) if field == "author" else src,
                               "match": ev.get("match"), "detail": ev.get("detail")}
            return {"source": cand.get("source"), "doi": cand.get("doi"), "fields": rows}
    return None


def main():
    bib = HERE / f".cdl-{COMMIT}.bib"
    env = {"DEVELOPER_DIR": "/Library/Developer/CommandLineTools", "PATH": "/usr/bin:/bin"}
    bib.write_bytes(subprocess.run(["git", "show", f"{COMMIT}:cdl.bib"], cwd=ROOT, env=env,
                                   check=True, capture_output=True).stdout)
    try:
        entries = load_entries(bib)
        cache = ReadOnlyCache(ROOT / ".bibcheck/verification.sqlite3")
        classes = defaultdict(lambda: defaultdict(list))
        for p in json.load(open(ROOT / "verification/phase0-2026-09-22/proposals.json"))["proposals"]:
            classes[p["class"]][p["key"]].append({"origin": "article", **p})
        for p in json.load(open(ROOT / "verification/catalogue-phase0-2026-09-22/proposals.json"))["proposals"]:
            cls = "CAT " + p["class"]
            classes[cls][p["key"]].append({"origin": "catalogue",
                                           "changes": {p["field"]: {"before": p["before"], "after": p["after"]}}, **p})
        rng = random.Random(SEED)
        picks = []
        for cls, n in RISKY.items():
            keys = sorted(classes[cls])
            picks += [(cls, k, "risky") for k in rng.sample(keys, min(n, len(keys)))]
        pooled = [c for c in sorted(classes) if c not in RISKY]
        chosen = {c: [k] for c in pooled for k in [rng.choice(sorted(classes[c]))]}
        extra = POOLED - len(chosen)
        weights = {c: len(classes[c]) - 1 for c in pooled}
        remaining = [(c, k) for c in pooled for k in sorted(classes[c]) if k not in chosen[c]]
        rng.shuffle(remaining)
        # Proportional without replacement: draw uniformly from the remaining entries.
        for c, k in remaining[:max(extra, 0)]:
            chosen[c].append(k)
        picks += [(c, k, "pooled") for c in pooled for k in chosen[c]]
        sample = []
        for cls, key, stratum in picks:
            rows = classes[cls][key]
            entry = entries[key]
            result = cache.get(str(bib), entry) or cache.get("cdl.bib", entry)
            first = rows[0]
            changes = {}
            for r in rows:
                changes.update(r.get("changes") or {})
            sample.append({
                "id": f"{len(sample)+1:02d}", "key": key, "class": cls, "stratum": stratum,
                "class_size": len(classes[cls]), "origin": first["origin"],
                "rule": first.get("rule"), "source": first.get("source"),
                "doi": first.get("doi"), "pubmed_id": first.get("pubmed_id"),
                "catalogue_record": first.get("source_record_id"),
                "fields": {k: v for k, v in entry["fields"].items() if k not in {"ID"}},
                "changes": changes,
                "evidence": evidence(result, first.get("doi"), first.get("pubmed_id")) if first["origin"] == "article" else None,
            })
        (HERE / "sample.json").write_text(json.dumps({
            "seed": SEED, "commit": COMMIT, "design": __doc__.strip(),
            "class_sizes": {c: len(v) for c, v in sorted(classes.items())},
            "sample": sample}, indent=1, ensure_ascii=False) + "\n")
        print(len(sample), "sampled from", len(classes), "classes")
    finally:
        bib.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
