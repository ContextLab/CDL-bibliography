"""Read-only, content-addressed indexing of a local PDF collection.

This collects candidate source text, never citation approvals. All output belongs
in an ignored local directory; filenames and extracted paper text stay local.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import unicodedata


POLICY = 1


def search_text(text):
    """Loose discovery normalization only; never a metadata equality test."""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def find_candidates(output, entries):
    """Find front-matter mentions, preserving where each weak match occurred.

    A filename or reference-list mention cannot establish publication identity.
    The caller must inspect the source, and recheck the current entry fingerprint.
    """
    output = Path(output)
    manifest = json.loads((output / 'manifest.json').read_text())
    needles = {key: (search_text(e['fields'].get('title', '')), e['fields'].get('doi', '').lower())
               for key, e in entries.items()}
    found = []
    for source in manifest['files']:
        if source['status'] != 'indexed':
            continue
        obj = json.loads((output / 'objects' / source['object']).read_text())
        if obj['pdf_sha256'] != source['pdf_sha256'] or obj['policy'] != POLICY:
            raise ValueError('Inconsistent PDF index object')
        pages = [(p['page'], search_text(p['text']), p['text'].lower()) for p in obj['pages']]
        for key, (title, doi) in needles.items():
            title_pages = [n for n, text, raw in pages if len(title) >= 12 and title in text]
            doi_pages = [n for n, text, raw in pages if doi and doi in raw]
            filename = Path(source['path']).stem == key
            if title_pages or doi_pages or filename:
                found.append({'key': key, 'fingerprint': entries[key]['fingerprint'],
                              'source': source, 'title_pages': title_pages, 'doi_pages': doi_pages,
                              'filename_match': filename, 'status': 'candidate_only'})
    return found


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def extract_front(path):
    result = subprocess.run(
        ['pdftotext', '-f', '1', '-l', '3', '-layout', '-enc', 'UTF-8', str(path), '-'],
        capture_output=True, timeout=45, check=True,
    )
    text = result.stdout.decode('utf-8')
    if len(text) > 300_000:
        raise ValueError('Front matter exceeds text limit')
    chunks = text.split('\f')
    if chunks and not chunks[-1].strip():
        chunks.pop()
    pages = [{'page': n, 'text': value} for n, value in enumerate(chunks, 1)]
    if not any(p['text'].strip() for p in pages):
        raise ValueError('No extractable text; scan requires visual review or OCR')
    return pages


def index_library(root, output, *, extractor=extract_front, retry_errors=False, progress=None):
    root, output = Path(root).resolve(strict=True), Path(output).resolve()
    if output == root or root in output.parents:
        raise ValueError('Index output must be outside the source library')
    output.mkdir(parents=True, exist_ok=True)
    objects = output / 'objects'; objects.mkdir(exist_ok=True)
    paths = sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() == '.pdf')
    rows, reused, extracted = [], 0, 0
    for number, path in enumerate(paths, 1):
        row = {'path': str(path.relative_to(root))}
        try:
            sha = file_hash(path)
            destination = objects / f'{sha}-v{POLICY}.json'
            prior = json.loads(destination.read_text()) if destination.exists() else None
            if prior is not None and not (retry_errors and prior.get('error')):
                record = prior; reused += 1
            else:
                record = {'pdf_sha256': sha, 'policy': POLICY, 'extractor': 'pdftotext -layout; first three pages'}
                try:
                    record['pages'] = extractor(path)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    record['error'] = f'{type(exc).__name__}: {exc}'
                # Never bind text to a different version of a concurrently edited PDF.
                if file_hash(path) != sha:
                    raise ValueError('Source changed during extraction; retry required')
                temporary = destination.with_suffix('.tmp')
                temporary.write_text(json.dumps(record, ensure_ascii=False) + '\n')
                temporary.replace(destination)
                extracted += 1
            row.update(pdf_sha256=sha, object=destination.name, status='error' if record.get('error') else 'indexed')
            if record.get('error'):
                row['error'] = record['error']
        except (OSError, ValueError) as exc:
            row.update(status='unreadable', error=f'{type(exc).__name__}: {exc}')
        rows.append(row)
        if progress and (number % 50 == 0 or number == len(paths)):
            progress({'processed': number, 'total': len(paths), 'extractions': extracted, 'cache_hits': reused})
    manifest = {'root': str(root), 'policy': POLICY, 'files': rows,
                'extractions': extracted, 'cache_hits': reused}
    temporary = output / 'manifest.tmp'
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(output / 'manifest.json')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, default=Path('.bibcheck/local-library'))
    parser.add_argument('--retry-errors', action='store_true')
    parser.add_argument('--bibliography', type=Path, help='Also search entry titles and DOIs; emits candidates only')
    args = parser.parse_args()
    started = time.monotonic()
    result = index_library(args.root, args.output, retry_errors=args.retry_errors,
                           progress=lambda row: print(json.dumps(row), flush=True))
    print(json.dumps({'files': len(result['files']), 'seconds': round(time.monotonic()-started, 2),
                      'errors': sum(r['status'] != 'indexed' for r in result['files']),
                      'extractions': result['extractions'], 'cache_hits': result['cache_hits']}), flush=True)
    if args.bibliography:
        from verification import load_entries
        candidates = find_candidates(args.output, load_entries(args.bibliography))
        (args.output / 'candidates.json').write_text(json.dumps(candidates, indent=2) + '\n')
        print(json.dumps({'candidates': len(candidates), 'entries': len({r['key'] for r in candidates})}), flush=True)


if __name__ == '__main__':
    main()
