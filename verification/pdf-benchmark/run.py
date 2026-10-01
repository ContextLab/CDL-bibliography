"""Run the PDF-evidence benchmark and (optionally) the offline coverage dry run.

    python verification/pdf-benchmark/run.py [--library PATH] [--coverage]

Benchmark: every case in cases.json is verified by bibcheck/pdf_evidence.py
against the recorded local PDF (its SHA-256 must match).  Reported:

* true accepts    -- expected accept, verifier passes;
* missed matches  -- expected accept, verifier does not pass (abstention);
* false accepts   -- expected reject, verifier passes (must be zero);
* field false supports -- planted case whose perturbed field is reported
  'supported' even if another field happened to block the entry (must be zero).

Coverage (--coverage): offline dry run over the entries that the portable
verification snapshot lists as needs_review; candidate PDFs come from the
existing local-library inventory (file named by cite key, or title/DOI hit
recorded in candidates.json).  Nothing is approved; a report is written to
verification/pdf-benchmark/coverage.json.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdf_evidence as P  # noqa: E402

HERE = Path(__file__).resolve().parent
CACHE = ROOT / ".bibcheck" / "pdf-benchmark" / "layout"
RESULTS = ROOT / ".bibcheck" / "pdf-benchmark" / "results.json"


def run_benchmark(library):
    spec = json.loads((HERE / "cases.json").read_text())
    known = spec["known_journals"]
    layouts = {}
    rows = []
    for case in spec["cases"]:
        path = library / case["pdf"]
        if case["pdf"] not in layouts:
            layout = P.cached_layout(path, CACHE)
            if layout["pdf_sha256"] != case["pdf_sha256"]:
                raise SystemExit(f"{case['pdf']}: PDF bytes changed since the benchmark was built")
            layouts[case["pdf"]] = P.prepare_pages(layout["pages"])
        result = P.verify_entry_pdf(case["fields"], layouts[case["pdf"]], known)
        field = case.get("perturbed_field")
        field_status = result["fields"].get(field, {}).get("status") if field else None
        if field and field not in case["fields"]:
            field_status = "removed"
        rows.append({
            "id": case["id"], "variant": case["variant"], "expected": case["expected"], "heldout": case.get("heldout", False),
            "passed": result["pass"], "perturbed_field": field, "perturbed_status": field_status,
            "fields": {k: v["status"] for k, v in result["fields"].items()},
            "identity": result["identity"], "version_flags": [f["flag"] for f in result["version_flags"]],
            "detail": {k: v.get("detail") for k, v in result["fields"].items() if v["status"] != "supported"},
        })
    return rows


def summarize(rows):
    tally = Counter()
    per = defaultdict(Counter)
    for r in rows:
        if r["expected"] == "accept":
            outcome = "true_accept" if r["passed"] else "missed_match"
        else:
            outcome = "false_accept" if r["passed"] else "true_reject"
        tally[outcome] += 1
        per[r["variant"]][outcome] += 1
        if r["perturbed_field"] and r["perturbed_status"] == "supported":
            tally["field_false_support"] += 1
            per[r["variant"]]["field_false_support"] += 1
    return tally, per


def load_needs_review():
    rows = [json.loads(line) for line in gzip.open(ROOT / "verification" / "baseline.jsonl.gz", "rt")]
    return {r["key"]: r for r in rows[1:] if r.get("status") == "needs_review"}


def coverage(library):
    from verification import load_entries
    entries = load_entries(ROOT / "cdl.bib")
    known = sorted({e["fields"]["journal"] for e in entries.values() if e["fields"].get("journal")})
    review = load_needs_review()
    manifest = json.loads((ROOT / ".bibcheck" / "local-library" / "manifest.json").read_text())
    by_stem = defaultdict(list)
    for f in manifest["files"]:
        by_stem[Path(f["path"]).stem].append(f["path"])
    candidates = defaultdict(set)
    for c in json.loads((ROOT / ".bibcheck" / "local-library" / "candidates.json").read_text()):
        candidates[c["key"]].add(c["source"]["path"])
    report = []
    counts = Counter()
    for key, row in sorted(review.items()):
        entry = entries.get(key)
        if entry is None:
            counts["not_in_current_bib"] += 1
            continue
        stale = entry["fingerprint"] != row["fingerprint"]
        pdfs = sorted(set(by_stem.get(key, [])) | candidates.get(key, set()))
        if not pdfs:
            counts["no_local_pdf"] += 1
            continue
        counts["with_local_pdf"] += 1
        best = None
        for rel in pdfs:
            path = library / rel
            try:
                layout = P.cached_layout(path, CACHE)
            except Exception as exc:  # unreadable PDF: abstain, never approve
                result = {"pass": False, "fields": {}, "error": f"{type(exc).__name__}"}
            else:
                result = P.verify_entry_pdf(entry["fields"], layout["pages"], known)
            summary = {"pdf": rel, "pass": result["pass"],
                       "fields": {k: v["status"] for k, v in result.get("fields", {}).items()},
                       "unchecked": result.get("unchecked_fields", []),
                       "version_flags": sorted({f["flag"] for f in result.get("version_flags", [])})}
            if best is None or summary["pass"]:
                best = summary
            if summary["pass"]:
                break
        counts["would_accept" if best["pass"] else "would_not_accept"] += 1
        if best["pass"] and stale:
            counts["accept_but_fingerprint_changed_since_snapshot"] += 1
        counts[f"type:{entry['fields']['ENTRYTYPE']}:{'accept' if best['pass'] else 'no'}"] += 1
        report.append({"key": key, "fingerprint": entry["fingerprint"], "snapshot_fingerprint_matches": not stale,
                       **best})
    return counts, report


def stress(library):
    """Planted single-field errors (build.variants) on every key-named article PDF.

    No labels: the base entries are only mostly correct, so every perturbed field
    reported 'supported' is listed for manual review rather than counted.
    """
    import build
    from verification import load_entries
    entries = load_entries(ROOT / "cdl.bib")
    known = sorted({e["fields"]["journal"] for e in entries.values() if e["fields"].get("journal")})
    manifest = json.loads((ROOT / ".bibcheck" / "local-library" / "manifest.json").read_text())
    counts, flagged = Counter(), []
    for f in manifest["files"]:
        key = Path(f["path"]).stem
        if f["status"] != "indexed" or key not in entries or entries[key]["fields"]["ENTRYTYPE"] != "article":
            continue
        fields = dict(entries[key]["fields"])
        pages = P.prepare_pages(P.cached_layout(library / f["path"], CACHE)["pages"])
        counts["pdfs"] += 1
        counts["base_pass"] += P.verify_entry_pdf(fields, pages, known)["pass"]
        for v in build.variants(key, fields, pages):
            r = P.verify_entry_pdf(v["fields"], pages, known)
            counts["variants"] += 1
            status = r["fields"].get(v["perturbed_field"], {}).get("status")
            if status == "supported" or r["pass"]:
                flagged.append({"key": key, "variant": v["variant"], "status": status, "pass": r["pass"],
                                "value": v["fields"].get(v["perturbed_field"])})
    return counts, flagged


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--library", type=Path,
                        default=Path(json.loads((HERE / "cases.json").read_text())["library_default"]))
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--stress", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    rows = run_benchmark(args.library)
    tally, per = summarize(rows)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps({"summary": tally, "per_variant": per, "rows": rows}, indent=1, ensure_ascii=False))
    expected_accept = sum(r["expected"] == "accept" for r in rows)
    print(f"cases: {len(rows)}  (expected accept {expected_accept}, expected reject {len(rows) - expected_accept})")
    for k in ("true_accept", "missed_match", "true_reject", "false_accept", "field_false_support"):
        print(f"  {k}: {tally.get(k, 0)}")
    print(f"  missed-match rate: {tally.get('missed_match', 0) / max(expected_accept, 1):.1%}")
    held = [r for r in rows if r["heldout"]]
    if held:
        ht, _ = summarize(held)
        ha = sum(r["expected"] == "accept" for r in held)
        print(f"  held-out subset: {len(held)} cases, expected accept {ha}: true_accept {ht.get('true_accept', 0)}, "
              f"missed {ht.get('missed_match', 0)}, false_accept {ht.get('false_accept', 0)}, "
              f"field_false_support {ht.get('field_false_support', 0)}")
    print("per variant (true_accept/missed_match/true_reject/false_accept/field_false_support):")
    for v in sorted(per):
        c = per[v]
        print(f"  {v:42s} {c['true_accept']:3d} {c['missed_match']:3d} {c['true_reject']:3d} "
              f"{c['false_accept']:3d} {c['field_false_support']:3d}")
    for r in rows:
        if (r["expected"] == "reject" and r["passed"]) or (r["perturbed_field"] and r["perturbed_status"] == "supported"):
            print("FALSE ACCEPT / FIELD SUPPORT:", r["id"], r["perturbed_field"], r["perturbed_status"])
    for r in rows:
        if r["expected"] == "accept" and not r["passed"]:
            print("missed:", r["id"], {k: v for k, v in r["detail"].items()}, r["version_flags"] or "")
    if args.coverage:
        counts, report = coverage(args.library)
        out = HERE / "coverage.json"
        out.write_text(json.dumps({"note": "Offline dry run; no approvals were written.",
                                   "counts": counts, "entries": report}, indent=1, ensure_ascii=False) + "\n")
        print("coverage:", json.dumps(counts, indent=1))
    if args.stress:
        counts, flagged = stress(args.library)
        print("stress:", dict(counts))
        for f in flagged:
            print("  review:", f)
    print(f"seconds: {time.monotonic() - started:.1f}")
    failures = tally.get("false_accept", 0) + tally.get("field_false_support", 0)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
