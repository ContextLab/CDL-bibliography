"""Collect the route test fixtures from real sources (or the routes cache).

Run from the repository root:
    CROSSREF_MAILTO=<real contact> .venv/bin/python verification/routes-2026-09-25/build_fixtures.py
Every raw document is the unmodified response envelope (URL, body, SHA-256,
retrieval time) that the route saved; controls change only citation fields.
The PR entries (FitzEtal26a, Spee22, Mann26, ReimGure19) are read from the PR
branches' cdl.bib with git show; everything else from the working-tree cdl.bib.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bibcheck'))
from verification import Cache, PoliteClient, load_entries  # noqa: E402
import osf_review, datacite_review, acl_review, sfn_abstracts  # noqa: E402

HERE = Path(__file__).parent
PR_BRANCHES = {'origin/nightwarden-refs': ['FitzEtal26a'],
               'origin/add-feature-representation-refs': ['Spee22', 'Mann26', 'ReimGure19']}


def citations():
    fields = {k: e['fields'] for k, e in load_entries(ROOT / 'cdl.bib').items()}
    env = dict(os.environ, DEVELOPER_DIR='/Library/Developer/CommandLineTools')
    for branch, keys in PR_BRANCHES.items():
        text = subprocess.run(['git', 'show', branch + ':cdl.bib'], cwd=ROOT, env=env, check=True,
                              capture_output=True).stdout
        with tempfile.NamedTemporaryFile(suffix='.bib', delete=False) as handle:
            handle.write(text)
        branch_entries = load_entries(handle.name); os.unlink(handle.name)
        for key in keys:
            fields[key] = branch_entries[key]['fields']
    return fields


def contact(cache):
    if os.environ.get('CROSSREF_MAILTO'):
        return os.environ['CROSSREF_MAILTO']
    raise SystemExit('Set CROSSREF_MAILTO to a real contact address')


def spec(F):
    """(module, case name, citation fields) for every fixture."""
    osf_v = dict(F['FranLiu18'], ID='ControlOsfVersion', title='Adaptive search promotes asymmetrical learning',
                 doi='10.31234/osf.io/vbc87_v1', year='2026')
    osf_w = dict(F['FranLiu18'], ID='ControlOsfWithdrawn', title='The Algebra of Experience - Recursive Semantic Operator Theory',
                 doi='10.31234/osf.io/fp2dy_v1', year='2026')
    osf_t = dict(F['ZimaEtal23'], ID='ControlOsfOtherWork', title=F['FranLiu18']['title'])
    dc_v = dict(F['Spee22'], ID='ControlDataciteVersion', doi='10.5281/zenodo.998161')
    dc_t = dict(F['Mann21d'], ID='ControlDataciteOtherWork', title='Storytelling with Data', doi='10.17605/osf.io/hyds8')
    acl_p = dict(F['ReimGure19'], ID='ControlAclCrossrefPages', pages='3980--3990')
    acl_t = dict(F['ReimGure19'], ID='ControlAclOtherWork', title=F['Etha19']['title'])
    return [(osf_review, k, F[k]) for k in ('FitzEtal26a', 'ZimaEtal23', 'GralFinn21', 'LuriEtal18', 'NussEtal18',
                                              'FranLiu18', 'MannEtal23a')] + [
        (osf_review, 'ControlOsfVersion', osf_v), (osf_review, 'ControlOsfWithdrawn', osf_w),
        (osf_review, 'ControlOsfOtherWork', osf_t)] + [
        (datacite_review, k, F[k]) for k in ('Spee22', 'Mann26', 'Mann21b', 'Mann21d', 'FitzEtal25')] + [
        (datacite_review, 'ControlDataciteVersion', dc_v), (datacite_review, 'ControlDataciteOtherWork', dc_t)] + [
        (acl_review, k, F[k]) for k in ('ReimGure19', 'MikoEtal13b', 'Etha19')] + [
        (acl_review, 'ControlAclCrossrefPages', acl_p), (acl_review, 'ControlAclOtherWork', acl_t)] + [
        (sfn_abstracts, k, F[k]) for k in ('RamaEtal12b', 'SommEtal12', 'KrauEtal12', 'DerdEtal06')]


def main():
    cache = Cache(ROOT / '.bibcheck/routes-2026-09-25.sqlite3')
    client = PoliteClient(cache, contact(cache), interval=1.0)
    out = {}
    try:
        for module, name, fields in spec(citations()):
            out.setdefault(module.__name__, {})[name] = {'fields': fields, 'raw': module.collect(cache, client, fields)}
    finally:
        cache.close()
    for route, cases in out.items():
        (HERE / 'fixtures' / (route + '.json')).write_text(json.dumps(cases, indent=1, ensure_ascii=False) + '\n')
    print('network requests:', client.requests)


if __name__ == '__main__':
    main()
