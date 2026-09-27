"""Freeze real entries, research rows and saved bodies for tests/test_research_route.py.

Run once from the repository root (2026-09-27); the outputs are committed and the tests
never read the live cdl.bib, the live research folders or .bibcheck/:

    .venv/bin/python tests/fixtures/research_route/build.py

* entries.bib: the entries as they are in cdl.bib at build time (raw BibTeX);
* root/: every research file that mentions a selected key, trimmed to the rows about the
  selected works (plus the full key-renames.json and key-deletions.json), same layout as
  the repository;
* bodies/: validate.py's saved bodies (.bibcheck/research-pilot/<sha256(url)>.txt) for
  every URL those rows quote;
* context.json: for the notice cases, the entry's stored DOI-linked candidates (the
  Europe PMC / Crossref records that carry the notice), taken from the verification cache.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'bibcheck'))

from verification import Cache, load_entries, normalize_doi  # noqa: E402
import research_route as R  # noqa: E402

# plain wave approvals; a renamed key (YingEtal92 -> YingEtal93); a resolution value;
# a browser-read quote; identity from a resolution title (batch 27, never queued); a
# user inference rule (catalogue extent); needs_user (ChanEtal12, renamed from
# ChanEtal12b); DOI-linked notices (Europe PMC erratum, Crossref correction); the
# deleted-and-reused key KahaEtal08b (the old work's rows must not apply).
KEYS = ['Tulv74', 'vanPEtal21', 'AschEben62', 'YingEtal93', 'Post62', 'HartWong79', 'Zar10', 'Gomu53',
        'ChanEtal12', 'DamaEtal96', 'Pyly73', 'KahaEtal08b']
NOTICE = ['DamaEtal96', 'Pyly73']


def main():
    entries = load_entries(ROOT / 'cdl.bib')
    (HERE / 'entries.bib').write_text('\n\n'.join(entries[k]['raw'] for k in KEYS) + '\n', encoding='utf-8')
    renames = json.loads((ROOT / R.RENAMES).read_text())
    deleted = {r['key'] for r in json.loads((ROOT / R.DELETIONS).read_text())}
    walk = R.rename_walk(renames, deleted)
    wanted = set(KEYS)

    def mine(key):
        return key in wanted or walk(key) in wanted

    out = HERE / 'root'
    if out.exists():
        shutil.rmtree(out)
    for rel in R.evidence_files(ROOT):
        src = ROOT / rel
        data = json.loads(src.read_text(encoding='utf-8'))
        if rel in (R.RENAMES, R.DELETIONS):
            kept = data
        elif isinstance(data, list):
            kept = [row for row in data if mine(row.get('key', ''))]
            if not kept:
                continue
        elif rel.endswith('applied-decisions.json'):
            kept = dict(data, entries={k: v for k, v in data['entries'].items() if mine(k)})
        elif '/decisions/' in rel:
            if not mine(data.get('key', '')):
                continue
            kept = data
        else:
            raise ValueError('unexpected evidence file ' + rel)
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(kept, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    bundles = R.load_evidence(out, set(KEYS))
    bodies = HERE / 'bodies'
    if bodies.exists():
        shutil.rmtree(bodies)
    bodies.mkdir()
    urls = set()
    for b in bundles.values():
        urls |= {r['identity'].get('url') for r in b['rows'] if r.get('identity')}
        for c in b['claims']:
            urls |= {i['url'] for i in c['items']}
            if isinstance(c.get('next_start'), dict):
                urls.add(c['next_start'].get('url'))
    for url in sorted(u for u in urls if u):
        name = hashlib.sha256(url.encode()).hexdigest() + '.txt'
        if (R.BODY_DIR / name).exists():
            shutil.copyfile(R.BODY_DIR / name, bodies / name)
    cache = Cache(ROOT / '.bibcheck/verification.sqlite3')
    try:
        context = {}
        for key in NOTICE:
            doi = normalize_doi(entries[key]['fields']['doi'])
            previous = cache.get(ROOT / 'cdl.bib', entries[key])
            context[key] = [c for c in previous['candidates']
                            if c.get('source') in ('europepmc', 'crossref', 'pmc-jats') and c.get('doi')
                            and normalize_doi(c['doi']) == doi]
        (HERE / 'context.json').write_text(json.dumps(context, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    finally:
        cache.close()


if __name__ == '__main__':
    main()
