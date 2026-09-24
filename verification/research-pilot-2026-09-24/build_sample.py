"""Stratified 50-entry pilot sample of held entries for agent research.

Excludes entries that already have a correction proposal and correction-notice
cases (those need the user's acknowledgement, not research). Packets carry the
current fields, the open issues and any records already found, as leads.
"""
import json, random, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import Cache, load_entries, current_results

class RO(Cache):
    def __init__(self, f): self.path = Path(f); self.db = sqlite3.connect(f"file:{f}?mode=ro", uri=True, timeout=30)

PLAN = {"article-no-record": 8, "article-more-given-names": 4, "article-too-many-fields": 4, "article-sources-disagree": 4,
        "article-value-held": 3, "article-author-count": 3, "article-relation-or-update": 2, "incollection-unresolved": 6,
        "book-unresolved": 5, "inproceedings-unresolved": 4, "misc-unresolved": 3, "inbook-unresolved": 2,
        "conference-unresolved": 1, "techreport-unresolved": 1}
SEED = 20260924

entries = load_entries(ROOT / "cdl.bib")
cache = RO(ROOT / ".bibcheck/verification.sqlite3")
results = current_results(str(ROOT / "cdl.bib"), cache, entries)
proposed = {p["key"] for p in json.load(open(ROOT / "verification/fixes-2026-09-24/proposals.json"))["proposals"]}
proposed |= {p["key"] for p in json.load(open(ROOT / "verification/catalogue-phase0-2026-09-22/proposals.json"))["proposals"]}
groups = json.load(open(ROOT / "verification/fixes-2026-09-24/groups.json"))["groups"]
groups = groups if isinstance(groups, list) else list(groups.values())
leads = {}
try:
    er = json.load(open(ROOT / "verification/extra-sources-2026-09-23/results.json"))
    rows = er.get("entries", er.get("results", er)) if isinstance(er, dict) else er
    for r in (rows.values() if isinstance(rows, dict) else rows):
        if isinstance(r, dict) and r.get("key"):
            leads[r["key"]] = {k: r[k] for k in r if k in ("outcome", "group", "records", "leads", "pmid", "doi", "best")}
except FileNotFoundError:
    pass
rng = random.Random(SEED)
sample = []
for g in groups:
    n = PLAN.get(g["group"])
    if not n: continue
    pool = sorted(k for k in g["keys"] if k in results and results[k]["status"] == "needs_review" and k not in proposed)
    for k in rng.sample(pool, min(n, len(pool))):
        r = results[k]
        cands = [{"source": c.get("source"), "doi": c.get("doi"), "pmid": c.get("pmid") or c.get("pubmed_id"),
                  "mismatched": sorted(f for f, ev in (c.get("evidence") or {}).items() if not ev.get("match"))}
                 for c in (r.get("candidates") or [])[:4]]
        sample.append({"key": k, "stratum": g["group"], "fields": {a: b for a, b in entries[k]["fields"].items() if a != "ID"},
                       "fingerprint": entries[k]["fingerprint"], "issues": r.get("issues"), "known_records": cands,
                       "extra_source_leads": leads.get(k)})
for i, s in enumerate(sample): s["batch"] = i % 5 + 1
(HERE / "sample.json").write_text(json.dumps(sample, indent=1, ensure_ascii=False) + "\n")
print(len(sample), {b: sum(s["batch"] == b for s in sample) for b in range(1, 6)})
