"""Regenerate the Phase 0 proposals under the 2026-09-24 spot-check fixes.

Fixes (verification/resolution-plan-2026-09-22/README.md, "Spot-check findings"):
1. Author after-values are written in house form: initials without periods,
   every initial the source gives (correction_proposals.source_authors).
2. An issue number is written only when a source states it; a split
   ``volume(issue)`` or a changed ``number`` with no statement in Crossref or
   the DOI-linked PubMed record is looked up (PubMed E-utilities, then the
   publisher page's citation_issue) and dropped when nothing states it.
3. Every proposal is audited: each after-value must be stated by a source
   record for its DOI (correction_proposals.after_value_statements).
   Violations are withheld and listed. A source-stated issue missing from the
   corrected citation is added (correction_proposals.complete_issue).

This reuses verification/phase0-2026-09-22/measure.py (read-only main cache,
``mode=ro``; bibcheck modules other than the Phase 0 set come from HEAD). The
only network use is the issue lookup, through PoliteClient with its own cache
(.bibcheck/fixes-2026-09-24.sqlite3) and the contact already used for
Crossref in the main cache. A repeat run makes zero requests.

    .venv/bin/python verification/fixes-2026-09-24/measure.py [--workers 8] [--offline]

Writes proposals.json, groups.json, lookups.json and diff.json next to this file.
"""
import argparse
from collections import Counter, defaultdict
import importlib.util
import json
import multiprocessing
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PHASE0 = ROOT / "verification/phase0-2026-09-22/measure.py"
BASELINE = ROOT / "verification/apply-2026-09-23/measure-phase0/proposals.json"
OWNED = {"correction_proposals.py", "pmc_corrections.py", "publisher_corrections.py", "verification.py",
         "auto_review.py", "publisher_metadata.py"}


def check_unowned_modules_match_head():
    """Phase 0 measure loads its whole module set from the working tree; only
    the modules owned by this fix may differ from HEAD."""
    env = dict(os.environ, DEVELOPER_DIR="/Library/Developer/CommandLineTools")
    for name in ("source_locators.py", "verification_cli.py"):
        head = subprocess.run(["git", "show", "HEAD:bibcheck/" + name], cwd=ROOT, env=env,
                              check=True, capture_output=True).stdout
        if head != (ROOT / "bibcheck" / name).read_bytes():
            raise SystemExit(f"bibcheck/{name} differs from HEAD; refusing to measure mixed work in progress")


def load_phase0():
    sys.argv = [sys.argv[0]]
    spec = importlib.util.spec_from_file_location("measure_phase0", PHASE0)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = None
LOOKUPS = {}


def single_source(entry, previous, explain=None):
    return ORIGINAL_SINGLE(entry, previous, explain, issue_lookups=LOOKUPS)


def finish(key, proposal):
    """Issue completion and the after-value audit for one slim proposal."""
    cp = M.cp
    entry, current = M.ENTRIES[key], M.CURRENT[key]
    working = M.without_publisher(entry) if entry["fields"].get("ENTRYTYPE") == "article" else entry
    previous = M.reassess(working, current)
    completed = cp.complete_issue(working, previous, proposal)
    if completed:
        proposal = completed
    lookup = LOOKUPS.get(proposal.get("doi"))
    stated_by, violations = cp.after_value_statements(working, previous, proposal, lookup)
    proposal = dict(proposal, stated_by=stated_by)
    if violations:
        proposal["violations"] = violations
    return proposal


def assess_one(key):
    out = ORIGINAL_ASSESS(key)
    try:
        if out.get("proposal"):
            out["proposal"] = finish(key, out["proposal"])
            if out["proposal"].get("violations"):
                out["outcome"] = "held"
                out["explain"] = {"reason": "after-value-not-source-stated",
                                  "violations": out["proposal"]["violations"],
                                  "withheld_proposal": out.pop("proposal")}
                out["held_issues"] = out.get("issues", [])
                out["features"] = {}
        repair = (out.get("stale_repair") or {}).get("proposal")
        if repair:
            repair = finish(key, repair)
            out["stale_repair"] = ({"held": {"reason": "after-value-not-source-stated", "violations": repair["violations"]}}
                                   if repair.get("violations") else dict(out["stale_repair"], proposal=repair))
    except Exception as exc:  # an audit failure withholds, never passes
        out["audit_error"] = repr(exc)
        if out.get("proposal"):
            out["outcome"] = "held"
            out["explain"] = {"reason": "audit-error", "detail": repr(exc), "withheld_proposal": out.pop("proposal")}
            out["held_issues"] = out.get("issues", [])
            out["features"] = {}
    return out


def contact_from_main_cache():
    db = sqlite3.connect(f"file:{ROOT / '.bibcheck/verification.sqlite3'}?mode=ro", uri=True)
    try:
        for (body,) in db.execute("SELECT body FROM responses WHERE request LIKE '%api.crossref.org%'"):
            values = parse_qs(urlparse(json.loads(body).get("url", "")).query).get("mailto", [])
            if values:
                return values[0]
    finally:
        db.close()
    raise SystemExit("No Crossref contact in the main cache; set one explicitly")


def needed_lookups(rows):
    """DOIs whose issue no cached source states, with their Crossref record."""
    need = {}
    for r in rows:
        explain = r.get("explain") or (r.get("stale_repair") or {}).get("held") or {}
        if explain.get("reason") == "issue-lookup-required" and explain.get("doi"):
            doi = explain["doi"]
            record = next((c["record"] for c in M.CURRENT[r["key"]].get("candidates", [])
                           if c.get("source") == "crossref" and c.get("record")
                           and M.cp.normalize_doi(c.get("doi", "")) == doi), None)
            if record:
                need.setdefault(doi, (r["key"], record))
    return need


def main():
    global M, ORIGINAL_SINGLE, ORIGINAL_ASSESS, LOOKUPS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--offline", action="store_true", help="use stored lookups only; no network")
    args = parser.parse_args()
    check_unowned_modules_match_head()
    M = load_phase0()
    ORIGINAL_SINGLE, ORIGINAL_ASSESS = M.cp.single_source_proposal, M.assess_one
    M.cp.single_source_proposal = single_source
    M.COARSE_CLASSES["number-dropped-unconfirmed"] = "S1-COORDINATES"
    original_group = M.group_of

    def group_of(row):
        reason = (row.get("explain") or {}).get("reason")
        if reason in {"after-value-not-source-stated", "audit-error"}:
            return "article-after-value-not-source-stated", json.dumps((row["explain"].get("violations")
                                                                      or row["explain"].get("detail")))[:60]
        if reason == "issue-lookup-required":
            return "article-issue-lookup-required", ""
        return original_group(row)
    M.group_of = group_of
    M.GROUP_TEXT["article-after-value-not-source-stated"] = (
        "A generated proposal had an after-value no source record states (general principle, 2026-09-24); withheld.",
        "Fix the generating rule; never apply.")
    M.GROUP_TEXT["article-issue-lookup-required"] = (
        "The issue is stated by no cached source and the lookup is not stored (run without --offline).",
        "Run the issue lookup.")
    M.CLASS_TEXT["S1-COORDINATES"] += "; an issue no source states is dropped after lookup"
    bib = ROOT / "cdl.bib"
    M.ENTRIES = M.load_entries(bib)
    cache = M.ReadOnlyCache(ROOT / ".bibcheck/verification.sqlite3")
    M.CURRENT = {k: cache.get(bib, e) or dict(M.outcome("pending", ["New"]), key=k) for k, e in M.ENTRIES.items()}
    cache.close()

    # Pass 1: which DOIs need an issue lookup (no cached source states the issue)?
    keys = [k for k, r in M.CURRENT.items() if r.get("status") in {"needs_review", "metadata_verified", "human_verified"}]
    with multiprocessing.get_context("fork").Pool(args.workers) as pool:
        rows = pool.map(ORIGINAL_ASSESS, keys, chunksize=8)
    need = needed_lookups(rows)
    from verification import Cache, PoliteClient
    import publisher_corrections as pc
    lookup_cache = Cache(ROOT / ".bibcheck/fixes-2026-09-24.sqlite3")
    client = PoliteClient(lookup_cache, contact_from_main_cache(), interval=1.0)
    if args.offline:
        class NoNetwork:
            def get(self, *a, **k):
                raise SystemExit("offline: lookup not stored: " + str(a[:1]))
        client.session = NoNetwork()
    for doi, (key, record) in sorted(need.items()):
        LOOKUPS[doi] = dict(pc.issue_lookup(lookup_cache, client, doi, record), key=key)
    lookup_cache.close()
    print(f"issue lookups: {len(need)} DOIs, {client.requests} network requests")

    # Pass 2: the Phase 0 measurement with the fixed rules, lookups and audit.
    original_slim = M.slim

    def slim(proposal, rule=None, source=None, extra=None):
        out = original_slim(proposal, rule, source, extra)
        for key in ("field_sources", "issue_evidence"):  # provenance of each value and of the issue
            if proposal.get(key):
                out[key] = proposal[key]
        return out
    M.slim = slim
    M.assess_one = assess_one
    M.HERE = HERE
    M.main()
    summarize(client.requests)


def summarize(requests):
    new = json.loads((HERE / "proposals.json").read_text())
    old = json.loads(BASELINE.read_text())
    old_by, new_by = {p["key"]: p for p in old["proposals"]}, {p["key"]: p for p in new["proposals"]}
    groups = json.loads((HERE / "groups.json").read_text())
    withheld = {}
    rows = {}
    for g in groups["groups"]:
        for k in g["keys"]:
            rows[k] = g["group"]
    diff = defaultdict(lambda: Counter())
    changed = []
    for key in sorted(set(old_by) | set(new_by)):
        a, b = old_by.get(key), new_by.get(key)
        cls = (a or b)["class"]
        if a and b:
            if a["changes"] == b["changes"]:
                diff[cls]["unchanged"] += 1
                continue
            fields = sorted({f for f in set(a["changes"]) | set(b["changes"])
                             if a["changes"].get(f) != b["changes"].get(f)})
            diff[cls]["changed"] += 1
            for f in fields:
                diff[cls]["changed:" + f] += 1
            changed.append({"key": key, "class_before": a["class"], "class_after": b["class"], "fields": fields,
                            "before": a["changes"], "after": b["changes"],
                            "issue_evidence": b.get("issue_evidence"), "issue_completion": b.get("issue_completion"),
                            "stated_by": b.get("stated_by")})
        elif a:
            diff[cls]["withdrawn"] += 1
            changed.append({"key": key, "class_before": a["class"], "withdrawn_to_group": rows.get(key),
                            "before": a["changes"]})
        else:
            diff[cls]["new"] += 1
            changed.append({"key": key, "class_after": b["class"], "after": b["changes"],
                            "issue_evidence": b.get("issue_evidence"), "stated_by": b.get("stated_by")})
    lookups = {doi: v for doi, v in sorted(LOOKUPS.items())}
    yield_ = Counter()
    for doi, v in lookups.items():
        pubmed = [h for h in v["pubmed"]["matched"] if h.get("issue")]
        publisher = v["publisher"]["doi_confirmed"] and v["publisher"]["citation_issue"]
        if [h for h in v["pubmed"]["matched"] if h.get("issue") and not re.fullmatch(r"[1-9]\d*", h["issue"])]:
            yield_["pubmed_issue_not_plain_number(held)"] += 1
        elif pubmed or publisher:
            yield_["confirmed_" + "+".join((["pubmed"] if pubmed else []) + (["publisher"] if publisher else []))] += 1
        else:
            yield_["unconfirmed(dropped)"] += 1
        if v["publisher"].get("error"):
            yield_["publisher_page_unavailable"] += 1
    (HERE / "lookups.json").write_text(json.dumps({"requests_this_run": requests, "yield": dict(yield_),
                                                   "lookups": lookups}, indent=1, ensure_ascii=False) + "\n")
    (HERE / "diff.json").write_text(json.dumps({"baseline": str(BASELINE.relative_to(ROOT)),
                                                "per_class": {k: dict(v) for k, v in sorted(diff.items())},
                                                "entries": changed}, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"lookup_yield": dict(yield_), "per_class": {k: dict(v) for k, v in sorted(diff.items())}}, indent=1))


if __name__ == "__main__":
    main()
