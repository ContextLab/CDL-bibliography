"""Blind extraction of two visually inspected local publisher PDF covers.

This is source-extraction evidence, never citation approval. No bibliography or
expected answers are supplied to the model. Full PDFs stay in the local library.
"""
import hashlib
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bibcheck'))
from dartmouth_models import PREFERRED_TEXT_MODEL, fetch_models, require_free
from dartmouth_research_adapter import complete, configuration

spec = importlib.util.spec_from_file_location('pilot_audit', ROOT / 'verification/pilot50/audit.py')
pilot = importlib.util.module_from_spec(spec); spec.loader.exec_module(pilot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    work = ROOT / '.bibcheck/local-library'
    manifest = json.loads((work / 'manifest.json').read_text())
    model = PREFERRED_TEXT_MODEL
    session = requests.Session()
    confirmed = False
    results = []
    for name in ('Box76', 'Salz59'):
        source = next(r for r in manifest['files'] if r['path'] == name + '.pdf')
        obj = json.loads((work / 'objects' / source['object']).read_text())
        data = {'source_kind': 'publisher PDF cover', 'pages': obj['pages'][:1]}
        identity = hashlib.sha256(json.dumps([data, pilot.SCHEMA, pilot.INSTRUCTIONS, model],
                                            sort_keys=True).encode()).hexdigest()
        path = work / ('audit-' + identity + '.json')
        if path.exists():
            result = json.loads(path.read_text()); cached = True
        else:
            if args.offline:
                raise ValueError('Missing cached extraction for ' + name)
            if not confirmed:
                key, _ = configuration(os.environ)
                require_free(fetch_models(key, session), model); confirmed = True
            finding, trace = complete(data, pilot.SCHEMA, pilot.INSTRUCTIONS, session, key, model)
            result = {'finding': finding, 'trace': trace, 'pdf_sha256': source['pdf_sha256'],
                      'input_hash': identity, 'pages': [1], 'status': 'extraction_only'}
            path.write_text(json.dumps(result, indent=2) + '\n'); cached = False
        pilot.validate_finding(result['finding'])
        expected = json.loads(Path(__file__).with_name('local-pdf-audit-expected.json').read_text())['entries'][name]
        differences = pilot.differences(expected, result['finding'])
        results.append({'key': name, 'cached': cached, 'differences': differences, **result})
        print(json.dumps({'key': name, 'cached': cached, 'finding': result['finding']}), flush=True)
        (Path(__file__).parent / 'local-pdf-audit-results.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
