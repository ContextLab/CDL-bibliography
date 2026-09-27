"""Summarise the research-route runs for the README: grouped reasons for the entries not
approved, the approvals' flags and rules, and the DOI-linked notice entries with their
notice kinds (read from each entry's stored candidates in the verification cache).

    .venv/bin/python verification/research-route-2026-09-27/summarize.py

Reads the run outputs in this folder (dry-run, backfill, backfill-2, repeat) and the
cache (the research approvals it holds now); writes summary.json.
The notice entries are the needs_review entries whose issues named a DOI-linked
correction/retraction notice before the backfill, read from the committed baseline
(`git show <BEFORE>:verification/baseline.jsonl.gz`, BEFORE = the commit the backfill ran on).
"""
from collections import Counter
import gzip
import json
import subprocess
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import Cache, load_entries, normalize_doi  # noqa: E402
import research_route as R  # noqa: E402

BEFORE = "716a122"
BUCKETS = (("needs_user", "gate: post-check needs_user residue"), ("verdict ambiguous", "gate: verdict ambiguous/no_source, no resolution"),
           ("user answered", "gate: user answered wrong/unsure (wave 1)"), ("marked for removal", "gate: marked for removal"),
           ("identity quote", "identity quote not found in a saved body"),
           ("field never researched", "a field no research row covers"),
           ("differs from the latest", "entry value is not the latest researched value"),
           ("no verbatim quote", "value backed only by reviewer/user prose, no verbatim quote"),
           ("quote not found", "quote not found in its saved body"), ("no saved body", "no saved body for the quoted URL"),
           ("value words not in", "value words missing from the quotes"),
           ("removed is still present", "a field the research removed is still present"),
           ("entry type differs", "entry type differs from the evidence"))


def bucket(reason_class):
    return next((name for text, name in BUCKETS if text in reason_class), reason_class)


def notice_kinds(result, doi):
    kinds = set()
    for c in result.get("candidates", []):
        try:
            same = bool(doi) and normalize_doi(c.get("doi") or "") == doi
        except ValueError:
            same = False
        raw = c.get("raw_record") or {}
        if c.get("source") == "europepmc":
            if raw.get("isRetracted") == "Y":
                kinds.add(("europepmc: retracted", same))
            for rel in (raw.get("commentCorrectionList") or {}).get("commentCorrection", []):
                kinds.add(("europepmc: " + str(rel.get("type")), same))
        elif c.get("source") == "crossref":
            rec = c.get("record") or {}
            for u in (rec.get("updated-by") or []) + (rec.get("update-to") or []):
                kinds.add(("crossref: " + str(u.get("type")), same))
        elif c.get("source") == "pmc-jats":
            for t in re.findall(r'related-article-type="([^"]+)"', c.get("raw_xml") or ""):
                kinds.add(("jats: " + t, same))
    return sorted(k + (" (cited DOI)" if same else " (other candidate DOI)") for k, same in kinds)


def main():
    out = {}
    for name in ("dry-run", "backfill", "backfill-2", "repeat"):
        path = HERE / (name + ".json")
        if not path.exists():
            continue
        d = json.loads(path.read_text())
        rows = d["rows"]
        first = Counter()
        for row in rows.values():
            if row["outcome"] in ("not_approved", "not_researched", "skipped"):
                first[bucket(R.reason_class(row["reasons"][0]))] += 1
        out[name] = {"outcomes": d["counts"]["outcomes"], "writes": d["counts"]["writes"],
                     "first_reason_grouped": dict(first.most_common()),
                     "all_reasons": d["counts"]["all_reasons"], "excluded_files": d.get("excluded_files")}
    back = json.loads((HERE / "backfill.json").read_text())["rows"]
    entries = load_entries("cdl.bib")
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    approved = set()
    for key, entry in entries.items():
        res = cache.get("cdl.bib", entry)
        if res and res["status"] == "metadata_verified" and res.get("accepted_source") == R.SOURCE:
            approved.add(key)
    env = dict(os.environ, DEVELOPER_DIR=os.environ.get("DEVELOPER_DIR", "/Library/Developer/CommandLineTools"))
    blob = subprocess.run(["git", "show", BEFORE + ":verification/baseline.jsonl.gz"], cwd=ROOT, env=env,
                          check=True, capture_output=True).stdout
    lines = [x for x in gzip.decompress(blob).decode().split("\n") if x]
    before = {r["key"]: r for r in map(json.loads, lines[1:])}
    try:
        flags, rules, identity = Counter(), Counter(), Counter()
        flagged = {}
        for key in sorted(approved):
            res = cache.get("cdl.bib", entries[key])
            c = [x for x in res["candidates"] if x["source"] == R.SOURCE][0]
            for f in c["flags"]:
                flags[f] += 1
                flagged.setdefault(key, []).append(f)
            for name, rec in c["fields"].items():
                if rec.get("rule"):
                    rules[rec["rule"]] += 1
            identity["identity from a resolution/user/manual title" if c["identity"].get("from_field")
                     else "researcher identity quote"] += 1
        out["approved"] = {"count": len(approved), "flags": dict(flags), "entries_with_browser_or_scan": flagged,
                           "inference_rules": dict(rules), "identity": dict(identity)}
        notices = {}
        for key, entry in entries.items():
            old = before.get(key)
            if not old or old["status"] != "needs_review" or old["fingerprint"] != entry["fingerprint"]:
                continue
            was_notice = any("notice" in i for i in old.get("issues", []))
            row = back.get(key, {})
            if not was_notice and row.get("outcome") != "held_by_notice":
                continue
            doi = normalize_doi(entry["fields"]["doi"]) if entry["fields"].get("doi") else None
            now = cache.get("cdl.bib", entry)
            notices[key] = {"notice_issue_before": was_notice, "doi": doi, "outcome": row.get("outcome"),
                            "status_now": now["status"], "issues_now": now.get("issues", [])[:2],
                            "not_approved_because": row.get("reasons", [])[:3] if row.get("outcome") == "not_approved" else [],
                            "notice_kinds": notice_kinds(now, doi)}
        retractions = sorted(k for k, n in notices.items() if any("retract" in x.lower() and "(cited DOI)" in x
                                                                  for x in n["notice_kinds"]))
        out["notices"] = {
            "notice_entries_before": sum(n["notice_issue_before"] for n in notices.values()),
            "outcomes_of_notice_entries": dict(Counter(n["outcome"] for n in notices.values() if n["notice_issue_before"])),
            "held_by_context_without_notice_issue_before": sorted(k for k, n in notices.items()
                                                                  if not n["notice_issue_before"]),
            "retractions_on_cited_doi": retractions,
            "entries": notices}
    finally:
        cache.close()
    (HERE / "summary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "notices"}, indent=1)[:4000])
    print(json.dumps({k: v for k, v in out["notices"].items() if k != "entries"}, indent=1))


if __name__ == "__main__":
    main()
