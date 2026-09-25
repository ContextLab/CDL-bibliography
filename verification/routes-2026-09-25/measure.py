"""Measure the 2026-09-25 routes over every current needs_review entry they apply to.

Read-only inputs: the working-tree cdl.bib and the main cache
(.bibcheck/verification.sqlite3, opened with mode=ro). Each entry's current
main-cache result is copied into the routes cache
(.bibcheck/routes-2026-09-25.sqlite3), where the routes run. Nothing else is
written. Run from the repository root:
    CROSSREF_MAILTO=<real contact> .venv/bin/python verification/routes-2026-09-25/measure.py
Pass 1 runs each run_*_review; pass 2 (repeat) re-collects and re-assesses every
entry from the routes cache with a fresh client and must make zero requests
and reproduce every outcome.
"""
from collections import Counter
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bibcheck'))
from verification import Cache, PoliteClient, load_entries  # noqa: E402
import osf_review, datacite_review, acl_review, sfn_abstracts  # noqa: E402

ROUTES = [('osf_review', osf_review, osf_review.run_osf_review, osf_review.assess_osf),
          ('datacite_review', datacite_review, datacite_review.run_datacite_review, datacite_review.assess_datacite),
          ('acl_review', acl_review, acl_review.run_acl_review, acl_review.assess_acl),
          ('sfn_review', sfn_abstracts, sfn_abstracts.run_sfn_review, sfn_abstracts.assess_sfn)]
BIB = ROOT / 'cdl.bib'
HERE = Path(__file__).parent


def main_results(entries):
    ro = Cache.__new__(Cache)
    ro.path = ROOT / '.bibcheck/verification.sqlite3'
    ro.db = sqlite3.connect(f'file:{ro.path}?mode=ro', uri=True)
    try:
        return {k: ro.get(str(BIB), e) for k, e in entries.items()}
    finally:
        ro.db.close()


def main():
    contact = os.environ.get('CROSSREF_MAILTO')
    if not contact:
        raise SystemExit('Set CROSSREF_MAILTO to a real contact address')
    entries = load_entries(BIB)
    current = main_results(entries)
    review = {k for k, r in current.items() if r and r['status'] == 'needs_review'}
    cache = Cache(ROOT / '.bibcheck/routes-2026-09-25.sqlite3')
    report = ROOT / '.bibcheck/routes-2026-09-25-report.jsonl'
    summary = {'needs_review_total': len(review), 'routes': {}}
    rows = []
    try:
        for name, module, run, assess in ROUTES:
            keys = sorted(k for k in review if module.applicable(entries[k]['fields']))
            for key in keys:  # start from the main cache's current result
                previous = dict(current[key]); previous.pop(name, None)
                cache.put(str(BIB), entries[key], previous)
            client = PoliteClient(cache, contact, interval=1.0)
            results = run(str(BIB), cache, client, str(report), keys=set(keys))
            first = {}
            for key in keys:
                cand = [c for c in results[key]['candidates'] if c.get('source') == module.SOURCE][-1]
                first[key] = (results[key]['status'], cand.get('category'), cand.get('proposal'), results[key]['issues'])
            repeat = PoliteClient(cache, contact, interval=1.0)
            same = 0
            for key in keys:
                raw = module.collect(cache, repeat, entries[key]['fields'])
                again = assess(entries[key]['fields'], raw)
                cand = again['candidates'][0]
                same += (again['status'], cand.get('category'), cand.get('proposal'), again['issues']) == first[key]
            rerun = PoliteClient(cache, contact, interval=1.0)
            run(str(BIB), cache, rerun, str(report), keys=set(keys))
            cats = Counter(v[1] for v in first.values())
            summary['routes'][name] = {'applicable_needs_review': len(keys), 'categories': dict(cats),
                                       'requests_first_pass': client.requests,
                                       'requests_repeat_collect': repeat.requests,
                                       'requests_repeat_run': rerun.requests,
                                       'repeat_identical': same}
            for key in keys:
                status, cat, proposal, issues = first[key]
                rows.append({'route': name, 'key': key, 'status': status, 'category': cat,
                             'proposal': proposal, 'issues': issues})
            print(name, json.dumps(summary['routes'][name]), flush=True)
    finally:
        cache.close()
    (HERE / 'measurement.json').write_text(json.dumps({'summary': summary, 'entries': rows}, indent=1,
                                                      ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
