"""Research route: record entries the research waves verified field by field.

Design and counts: verification/research-route-2026-09-27/README.md.

Evidence (read-only, from the repository):

* researcher rows: ``verification/research-pilot-2026-09-24/batch-*.json`` and
  ``verification/research-2026-09-25/wave*/batch-*.json`` (schema: the pilot's PROTOCOL.md);
* the pilot's applied proposals (``pilot-proposals.json``, ``followup.json``);
* each wave's ``merged.json`` (post-check final values with provenance; ``needs_user``,
  ``remove_entry``, verdict);
* the user's cross-wave decisions (``crosswave/applied-decisions.json``);
* the resolution batches (``verification/resolution-2026-09-26/batch-*.json``);
* the manual research of 2026-09-26 (``research-2026-09-26-manual/proposals.json``).

Row keys are followed through ``verification/key-renames.json`` in log order and never
from a key listed in ``verification/key-deletions.json`` (that work was deleted; the key
may since name another work).

An entry is approved (status ``metadata_verified``, ``accepted_source`` = SOURCE) only when

1. a research row exists for it, its verdict is ``verified``/``correction`` (or a
   resolution decision ``apply``/``keep`` settled it), no row marks it ``needs_user`` or
   for removal, and the identity quote is found at its URL;
2. every field of the CURRENT entry (except ``ID`` and ``ENTRYTYPE``, and the fields in
   NOT_REQUIRED) equals an evidenced value after the house normalisation (``canon``), and
   that value is supported by its quote(s) under validate.py's matching
   (``value_supported``), each quote found in the fetched body that validate.py saved
   under ``.bibcheck/research-pilot/`` (the body's sha256 is stored with the evidence);
3. an ``ENTRYTYPE`` that any evidence names equals the entry's type;
4. no DOI-linked notice, suffix or coordinate conflict and no registry update notice is
   known for the entry's DOI (``preprint_review.context_issues``, as for every other
   route approval; ``Cache.retain_notices`` then applies to research approvals exactly as
   it does to the others).

Quotes the user accepted without a fetched body (read in a real browser, transcribed from
an image-only scan: resolution-plan README, round 2) count only for resolution and manual
rows whose notes say so, only when the quote itself contains the value's words, and are
flagged ``browser_or_scan`` in the saved evidence.

Nothing here makes a network request.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import unicodedata

from verification import normalize_doi, outcome

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'research-evidence'
POLICY = '1'
NAME = 'research_route'
BODY_DIR = ROOT / '.bibcheck' / 'research-pilot'
VALIDATE_PY = ROOT / 'verification/research-pilot-2026-09-24/validate.py'
POSTCHECK_PY = ROOT / 'verification/research-2026-09-25/postcheck.py'

PILOT = 'verification/research-pilot-2026-09-24'
WAVES = 'verification/research-2026-09-25'
RESOLUTIONS = 'verification/resolution-2026-09-26'
MANUAL = 'verification/research-2026-09-26-manual/proposals.json'
RENAMES = 'verification/key-renames.json'
DELETIONS = 'verification/key-deletions.json'

# Structural fields: the key is not metadata, and the entry type is a judgment the
# validator does not quote-check (validate.py JUDGMENT); any evidence naming a type
# must agree with the entry (rule 3).
STRUCTURAL = ('ID', 'ENTRYTYPE')
# Fields no house rule requires a source for. Each is a locator or a comment the
# bibliography keeps for the reader, never part of the work's identity or of the
# citation's coordinates. (Decided 2026-09-27; see the README.) Everything else must be
# evidenced: title, author, editor, year, journal, booktitle, volume, number, pages,
# doi, publisher, address, edition, series, chapter, school, institution, type,
# organization, howpublished, url, note, month, ...
NOT_REQUIRED = {}
# validate.py's judgment fields: evidenced by an equal value whose quote is found (a
# page at that address was read), without the word test.
JUDGMENT = ('url', 'howpublished')
# The notes must say the evidence itself was read that way: "read in a (real) browser",
# "via a browser", "browser-only", "(browser; ...)", Playwright, "transcribed", a scan,
# a page image. A negation just before ("no scan found") or a lending-only scan after
# does not count, nor does a scripted fetch "with a browser UA" or "searches returned no
# match in the scripted/browser views" (Mann06). Calibrated on every resolution and
# manual note on 2026-09-27 (README).
BROWSER_OR_SCAN = re.compile(r"(?:\b(?:in|via|through|with)\s+a\s+(?:real\s+)?(?:web\s+)?browser\b(?!\s+UA)"
                             r"|\bbrowser[- ]only\b|\bbrowser\s+fetcher\b|\(browser\b|\bplaywright\b"
                             r"|\btranscri(?:bed|ption|pt)\b|\bscan(?:ned|s)?\b|\bpage\s+images?\b)", re.I)
_NEGATED_BEFORE = re.compile(r"\b(?:no|not|never|without)\b[^.;()]{0,30}$", re.I)
_UNREAD_AFTER = re.compile(r"^[^.;]{0,20}\b(?:lending-only|unavailable|not available|not found)\b", re.I)


def says_browser_or_scan(notes):
    """True when the notes say a quote was read in a real browser or transcribed from a scan."""
    notes = str(notes or '')
    return any(not _NEGATED_BEFORE.search(notes[:m.start()]) and not _UNREAD_AFTER.search(notes[m.end():])
               for m in BROWSER_OR_SCAN.finditer(notes))
_MODULES = {}


def _module(name, path):
    if name not in _MODULES:
        cwd = os.getcwd()
        bibcheck = str(ROOT / 'bibcheck')
        if bibcheck not in sys.path:
            sys.path.insert(0, bibcheck)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        finally:
            os.chdir(cwd)
        _MODULES[name] = mod
    return _MODULES[name]


def validator():
    """verification/research-pilot-2026-09-24/validate.py (its matching only; never fetches here)."""
    return _module('research_route_validate', VALIDATE_PY)


def postcheck():
    """verification/research-2026-09-25/postcheck.py (its house normalisers only)."""
    return _module('research_route_postcheck', POSTCHECK_PY)


# ------------------------------------------------------------------ house form

def _text(value):
    V = validator()
    text = V.delatex(V.json_unescape(str(value or '')))
    text = unicodedata.normalize('NFKC', text.translate(V.PRE_FOLD)).translate(V.FOLD)
    text = re.sub(r'\s*-{1,3}\s*', '-', text)
    text = re.sub(r'\s+', ' ', text).strip().rstrip('.').strip()
    return text.casefold()


LATEX_LETTER = re.compile(r"\\(?:[.'`^\"~=]\s*\{?\\?[A-Za-z]\}?|[cvuHkr]\s*\{[A-Za-z]\}|(?:ss|ae|AE|oe|OE|aa|AA|[lLoOij])(?![A-Za-z]))")


def _latex_letters(value):
    """LaTeX accent and letter macros to Unicode, with their own braces, other braces kept."""
    V = validator()
    value = re.sub(r"\{\\[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", lambda m: V.delatex(m[0]), value)
    return LATEX_LETTER.sub(lambda m: V.delatex(m[0]), value)


def canon(field, value, cities=None):
    """The house form of ``value`` for comparison: the post-check's normalisers for the
    field (names, pages, issue ranges, ordinals, proceedings booktitles, em dashes,
    US addresses), then LaTeX accents to Unicode, braces dropped, dashes and
    whitespace folded, case folded. Two values with one canon are one value."""
    P = postcheck()
    field = field.lower()
    v = str(value if value is not None else '').strip()
    if field == 'entrytype':
        v = v.lower().lstrip('@')
        return 'inproceedings' if v == 'conference' else v
    if field == 'doi':
        try:
            return normalize_doi(v)
        except ValueError:
            return v.lower()
    if field in ('author', 'editor'):
        # LaTeX letters first ({\\L}, {\\.I}, J{\\"o}rnsten): the name normaliser garbles
        # them; other braces (corporate names, particles) are kept for it.
        v = P.normalise_names(_latex_letters(v))[0]
    elif field == 'pages':
        v = P.normalise_pages(v)[0]
    elif field == 'number':
        v = P.normalise_number(v)[0]
    elif field == 'booktitle':
        v = P.normalise_emdash(P.normalise_booktitle(v)[0])[0]
    elif field in ('title', 'chapter'):
        v = P.normalise_ordinals(P.normalise_emdash(v)[0])[0]
    elif field == 'edition':
        v = P.normalise_edition(v)[0]
    elif field == 'address':
        v = P.normalise_address(v, cities or {})[0]
    elif field in P.ORDINAL_FIELDS:
        v = P.normalise_ordinals(v)[0]
    return _text(v)


# ------------------------------------------------------------------ evidence files

def _items(spec):
    """{url, quote} items of one evidence value (researcher list, or resolution set)."""
    if isinstance(spec, list):
        return [{'url': i.get('url'), 'quote': i.get('quote')} for i in spec if isinstance(i, dict)]
    items = []
    if spec.get('url') or spec.get('quote'):
        items.append({'url': spec.get('url'), 'quote': spec.get('quote')})
    for name in ('evidence', 'extra_evidence'):
        extra = spec.get(name) or []
        for x in [extra] if isinstance(extra, dict) else extra:
            if isinstance(x, dict):
                items.append({'url': x.get('url'), 'quote': x.get('quote')})
    return items


def _claim(field, value, items, origin, row_key, lenient=False, next_start=None, all_items=False, kind='value'):
    """One piece of research about one field: ``kind`` 'value' (the field is ``value``;
    ``items`` quote it, possibly none), 'remove' (the field must go) or 'withdraw' (a
    research change to the field was withdrawn: the cited value stays)."""
    field = 'ENTRYTYPE' if field.lower() == 'entrytype' else field.lower()
    return {'field': field, 'kind': kind, 'value': None if value is None else str(value), 'items': items,
            'origin': origin, 'row_key': row_key, 'lenient': bool(lenient), 'next_start': next_start,
            'all_items': bool(all_items)}


def rename_walk(renames, deleted):
    """old key -> current key, following key-renames.json in log order; a deleted key
    maps to None (never followed)."""
    def walk(key):
        if key in deleted:
            return None
        cur = key
        for r in renames:
            if r['old_key'] == cur:
                cur = r['new_key']
        return cur
    return walk


def evidence_files(root=ROOT):
    """Every research file the route reads, as paths relative to ``root``, in read order."""
    root = Path(root)
    waves = sorted((root / WAVES).glob('wave*'), key=lambda p: int(re.sub(r'\D', '', p.name) or 0))
    files = sorted((root / PILOT).glob('batch-*.json'))
    for wave in waves:
        files += sorted(wave.glob('batch-*.json'))
    files += [root / PILOT / 'pilot-proposals.json', root / PILOT / 'followup.json']
    files += [wave / name for wave in waves for name in ('merged.json', 'review.json')]
    files += [root / WAVES / 'crosswave/applied-decisions.json']
    for wave in waves:
        files += sorted((wave / 'decisions').glob('*.json'))
    files += sorted((root / RESOLUTIONS).glob('batch-*.json'))
    files += [root / MANUAL, root / RENAMES, root / DELETIONS]
    return [f.relative_to(root).as_posix() for f in files if f.exists()]


def load_evidence(root=ROOT, bib_keys=None, exclude=()):
    """{current key: bundle} from the research files under ``root`` (same layout as the
    repository), leaving out the relative paths in ``exclude`` (a file another session
    is still writing is never read). A bundle is JSON: researcher rows (origin, key,
    verdict, notes, identity quote), gate records (post-check ``needs_user`` /
    ``remove_entry``, the user's wave-1 and cross-wave decisions, resolution decisions)
    and every field claim with its evidence items. ``bib_keys`` limits the output to
    keys present in the bibliography."""
    root = Path(root)
    exclude = set(exclude)
    files = [f for f in evidence_files(root) if f not in exclude]

    def read(rel):
        return json.loads((root / rel).read_text(encoding='utf-8')) if rel in files else None

    renames = read(RENAMES) or []
    deleted = {r['key'] for r in (read(DELETIONS) or [])}
    walk = rename_walk(renames, deleted)
    bundles = {}

    def bundle(key):
        cur = walk(key)
        if cur is None or (bib_keys is not None and cur not in bib_keys):
            return None
        return bundles.setdefault(cur, {'rows': [], 'claims': [], 'merged': [], 'resolutions': [],
                                        'decisions': []})

    for rel in files:
        path = Path(rel)
        parts = path.parts
        if rel.startswith(PILOT + '/batch-') or (rel.startswith(WAVES + '/wave') and path.name.startswith('batch-')):
            origin = ('pilot/' if rel.startswith(PILOT) else parts[-2] + '/') + path.stem
            for row in read(rel):
                b = bundle(row['key'])
                if b is None:
                    continue
                ident = row.get('identity') or {}
                b['rows'].append({'origin': origin, 'key': row['key'], 'verdict': row.get('verdict'),
                                  'identity': {'url': ident.get('url'), 'quote': ident.get('quote')},
                                  'notes': row.get('notes') or ''})
                for field, f in (row.get('fields') or {}).items():
                    if f.get('status') in ('confirmed', 'corrected') and f.get('value') not in (None, ''):
                        b['claims'].append(_claim(field, f['value'], _items(f.get('evidence') or []),
                                                  origin, row['key']))
                for field in row.get('remove') or []:
                    b['claims'].append(_claim(field, None, [], origin, row['key'], kind='remove'))
        elif rel.startswith(PILOT + '/') and path.name in ('pilot-proposals.json', 'followup.json'):
            for row in read(rel):
                b = bundle(row['key'])
                if b is None:
                    continue
                for field, ch in (row.get('changes') or {}).items():
                    if isinstance(ch, dict) and ch.get('after') not in (None, ''):
                        b['claims'].append(_claim(field, ch['after'], _items(ch.get('evidence') or []),
                                                  'pilot/' + path.stem, row['key']))
        elif path.name == 'merged.json':
            wave = parts[-2]
            for row in read(rel):
                b = bundle(row['key'])
                if b is None:
                    continue
                b['merged'].append({'origin': wave + '/merged', 'key': row['key'], 'verdict': row.get('verdict'),
                                    'needs_user': bool(row.get('needs_user')),
                                    'remove_entry': row.get('remove_entry')})
                for ch in row.get('final_changes') or []:
                    if ch.get('proposed') not in (None, ''):
                        b['claims'].append(_claim(ch['field'], ch['proposed'], _items(ch.get('evidence') or []),
                                                  wave + '/merged:' + str(ch.get('source')), row['key'],
                                                  all_items=ch.get('source') == 'resolution'))
                for field in row.get('removals') or {}:
                    b['claims'].append(_claim(field, None, [], wave + '/merged', row['key'], kind='remove'))
        elif path.name == 'review.json':
            wave = parts[-2]
            for row in read(rel):
                b = None if row.get('key') == '_summary' else bundle(row['key'])
                if b is None:
                    continue
                for field, value in (row.get('suggested_value') or {}).items():
                    origin = wave + '/review'
                    if value in (None, ''):
                        b['claims'].append(_claim(field, None, [], origin, row['key'], kind='withdraw'))
                    elif str(value).strip().lower() in ('remove', 'delete'):
                        b['claims'].append(_claim(field, None, [], origin, row['key'], kind='remove'))
                    elif field.lower() != 'key':
                        b['claims'].append(_claim(field, value, [], origin, row['key']))
        elif path.name == 'applied-decisions.json':
            for key, d in sorted((read(rel) or {}).get('entries', {}).items()):
                b = bundle(key)
                if b is None:
                    continue
                b['decisions'].append({'origin': 'crosswave', 'key': key, 'remove_entry': d.get('remove_entry'),
                                       'verdict': None})
                for field, spec in (d.get('set') or {}).items():
                    if isinstance(spec, dict) and spec.get('value') not in (None, ''):
                        b['claims'].append(_claim(field, spec['value'], _items(spec), 'crosswave', key,
                                                  all_items=True))
                for field in d.get('withdraw') or []:
                    b['claims'].append(_claim(field, None, [], 'crosswave', key, kind='withdraw'))
        elif parts[-2] == 'decisions':
            d = read(rel)
            b = bundle(d['key'])
            if b is not None:
                b['decisions'].append({'origin': parts[-3] + '/decisions', 'key': d['key'],
                                       'remove_entry': None, 'verdict': d.get('verdict')})
        elif rel.startswith(RESOLUTIONS + '/batch-'):
            origin = 'resolution/' + path.stem
            for row in read(rel):
                b = bundle(row['key'])
                if b is None:
                    continue
                notes = row.get('notes') or ''
                b['resolutions'].append({'origin': origin, 'key': row['key'], 'decision': row.get('decision'),
                                         'notes': notes})
                if row.get('entrytype'):
                    b['claims'].append(_claim('ENTRYTYPE', row['entrytype'], [], origin, row['key']))
                for field, spec in (row.get('set') or {}).items():
                    if isinstance(spec, dict) and spec.get('value') not in (None, ''):
                        b['claims'].append(_claim(field, spec['value'], _items(spec), origin, row['key'],
                                                  lenient=says_browser_or_scan(notes),
                                                  next_start=spec.get('next_start'), all_items=True))
                for field in row.get('withdraw') or []:
                    b['claims'].append(_claim(field, None, [], origin, row['key'], kind='withdraw'))
                for field in row.get('remove') or []:
                    b['claims'].append(_claim(field, None, [], origin, row['key'], kind='remove'))
        elif rel == MANUAL:
            for row in read(rel):
                b = bundle(row['key'])
                if b is None:
                    continue
                notes = row.get('notes') or ''
                notes = ' '.join(map(str, notes)) if isinstance(notes, list) else notes
                b['rows'].append({'origin': 'manual', 'key': row['key'], 'verdict': 'manual', 'identity': {},
                                  'notes': notes})
                if row.get('entrytype'):
                    b['claims'].append(_claim('ENTRYTYPE', row['entrytype'], [], 'manual', row['key']))
                for field, spec in (row.get('fields') or {}).items():
                    if isinstance(spec, dict) and spec.get('value') not in (None, ''):
                        b['claims'].append(_claim(field, spec['value'], _items(spec), 'manual', row['key'],
                                                  lenient=says_browser_or_scan(notes), all_items=True))
                for field in row.get('remove') or []:
                    b['claims'].append(_claim(field, None, [], 'manual', row['key'], kind='remove'))
    return bundles


# ------------------------------------------------------------------ bodies

class Bodies:
    """validate.py's saved fetched bodies: ``<dir>/<sha256(url)>.txt``. Never fetches."""

    def __init__(self, directory=None):
        self.directory = Path(BODY_DIR if directory is None else directory)

    def get(self, url):
        """(text, sha256) of the saved body, or (None, None) when validate.py saved none
        (or saved a transient server error reply, which it never trusts either)."""
        path = self.directory / (hashlib.sha256(url.encode()).hexdigest() + '.txt')
        text = path.read_text() if path.exists() else None
        if text is None or validator().transient_error(text):
            return None, None
        return text, hashlib.sha256(text.encode()).hexdigest()

    def found(self, url, quote):
        """(found, body sha256) for one quote under validate.py's matching."""
        V = validator()
        text, sha = self.get(url)
        if text is None:
            return False, None
        return V.hyphen_joined(V.norm(quote)) in _normalised_body(sha, text), sha


_NORMALISED = OrderedDict()


def _normalised_body(sha, text, keep=64):
    """validate.py's normalised form of a body (hyphen_joined(norm(text))), by sha256;
    the most recent ``keep`` are remembered (bodies are read again for every field)."""
    if sha in _NORMALISED:
        _NORMALISED.move_to_end(sha)
        return _NORMALISED[sha]
    V = validator()
    _NORMALISED[sha] = V.hyphen_joined(V.norm(text))
    while len(_NORMALISED) > keep:
        _NORMALISED.popitem(last=False)
    return _NORMALISED[sha]


class SavedBodies:
    """Offline re-check without the body cache (a fresh clone): each (url, quote) is
    taken as the saved evidence recorded it; everything else is re-derived."""

    def __init__(self, candidate):
        self.saved = {}
        for item in _saved_items(candidate):
            self.saved[(item['url'], item['quote'])] = (item['found'], item['body_sha256'])

    def found(self, url, quote):
        return self.saved.get((url, quote), (False, None))


def _saved_items(candidate):
    ident = candidate.get('identity') or {}
    if ident.get('url'):
        yield ident
    for f in (candidate.get('fields') or {}).values():
        for item in f.get('evidence', []):
            yield item
        if f.get('next_start'):
            yield f['next_start']


# ------------------------------------------------------------------ assessment

def _support(field, value, claim, bodies):
    """(ok, record, why) for one claim of ``value``."""
    V, P = validator(), postcheck()
    items = [i for i in claim['items'] if i.get('url') and i.get('quote')]
    record = {'origin': claim['origin'], 'row_key': claim['row_key'], 'claimed': claim['value'], 'evidence': []}
    if not items:
        return False, record, 'no quoted evidence'
    for item in items:
        ok, sha = bodies.found(item['url'], item['quote'])
        record['evidence'].append({'url': item['url'], 'quote': item['quote'], 'found': bool(ok),
                                   'body_sha256': sha})
    found = [e for e in record['evidence'] if e['found']]
    lenient = False
    if claim['all_items'] and len(found) != len(record['evidence']) or not found:
        if not claim['lenient']:
            return False, record, ('quote not found in the saved body' if any(e['body_sha256'] for e in record['evidence'])
                                   else 'no saved body for the quoted URL')
        lenient = True  # read in a browser / transcribed from a scan (user rule, round 2)
        found = record['evidence']
    quotes, urls = [e['quote'] for e in found], [e['url'] for e in found]
    nxt = claim.get('next_start')
    if nxt:
        if field != 'pages' or not isinstance(nxt, dict) or not nxt.get('url') or not nxt.get('quote'):
            return False, record, 'next_start needs a pages value and its own URL and quote'
        ok, sha = bodies.found(nxt['url'], nxt['quote'])
        record['next_start'] = {'url': nxt['url'], 'quote': nxt['quote'], 'found': bool(ok), 'body_sha256': sha}
        if not ok and not claim['lenient']:
            return False, record, 'next_start quote not found in the saved body'
        lenient = lenient or not ok
    if lenient:
        record['flag'] = 'browser_or_scan'
    if field in JUDGMENT:
        return True, record, None
    supported, missing = V.value_supported(field, value, quotes, urls)
    if supported:
        return True, record, None
    if field == 'pages' and nxt:
        ok, why = P.inferred_end_page(V, value, quotes, urls, nxt['quote'])
        if ok:
            record['rule'] = "end page = next item's printed start - 1"
            return True, record, None
    if field == 'pages':
        ok, _ = P.catalogue_extent(V, value, quotes)
        if ok:
            record['rule'] = "monograph pages 1--N from the catalogue extent 'N p.'"
            return True, record, None
    if field == 'volume':
        ok, _ = P.roman_page_prefix(V, value, quotes)
        if ok:
            record['rule'] = 'volume from the roman page prefix'
            return True, record, None
    return False, record, 'value words %s are not in the quotes' % missing


def _rank(claim):
    """Later decisions first: resolution batches (newest first), the user's cross-wave
    decisions, the manual research, then each wave (newest first: its post-check final
    values, its reviewer, its researcher rows), then the pilot."""
    o = claim['origin']
    number = int((re.search(r'\d+', o) or ['0'])[0])
    if o.startswith('resolution/'):
        return (0, -number, 0, o)
    if o.startswith('crosswave'):
        return (1, 0, 0, o)
    if o == 'manual':
        return (2, 0, 0, o)
    if o.startswith('wave'):
        part = o.split('/', 1)[1]
        return (3, -number, 0 if part.startswith('merged') else 1 if part == 'review' else 2, o)
    return (4, 0, 0, o)


def gates(bundle):
    """Issues that stop an approval whatever the fields say."""
    issues = []
    rows = [r for r in bundle['rows'] if r['origin'] != 'manual']
    manual = any(r['origin'] == 'manual' for r in bundle['rows'])
    decisions = {r['decision'] for r in bundle['resolutions']}
    if not bundle['rows'] and not decisions & {'apply', 'keep'}:
        # A resolution batch may research an entry no wave queued (batch 27); its
        # quotes then carry the evidence and its title quote the identity.
        issues.append('research: no researcher row or resolution decision for this entry')
    if 'drop' in decisions:
        issues.append('research: a resolution decision drops this entry')
    if len(decisions) > 1:
        issues.append('research: conflicting resolution decisions %s' % sorted(decisions))
    settled = (bool(decisions & {'apply', 'keep'}) and 'drop' not in decisions) or manual
    for r in rows:
        if r['verdict'] not in ('verified', 'correction') and not settled:
            issues.append('research: verdict %s (%s) and no resolution decision' % (r['verdict'], r['origin']))
    user = {(d['origin'].split('/')[0], d['key']): d['verdict'] for d in bundle['decisions'] if d.get('verdict')}
    for (wave, key), verdict in sorted(user.items()):
        if verdict != 'correct' and not settled:
            issues.append('research: the user answered %r on the %s row (%s)' % (verdict, wave, key))
    for m in bundle['merged']:
        wave = m['origin'].split('/')[0]
        # The wave-1 page asked the user about every wave-1 row; a row the user marked
        # correct was applied as proposed (apply-2026-09-28-wave1), which settles its
        # needs_user. Held fields stayed as cited and are checked like any other field.
        if m['needs_user'] and user.get((wave, m['key'])) != 'correct':
            issues.append('research: needs_user (%s)' % m['origin'])
        if m['remove_entry']:
            issues.append('research: marked for removal (%s)' % m['origin'])
    for d in bundle['decisions']:
        if d.get('remove_entry'):
            issues.append('research: the user marked it for removal (%s)' % d['origin'])
    return issues


def _field(field, value, claims, bodies, cities):
    """(record, issue) for one field of the entry. The latest research decision on the
    field must be its current value; that value must then be quoted and supported."""
    here = canon(field, value, cities)
    ranked = sorted((c for c in claims if c['field'] == field), key=_rank)
    live = []
    for c in ranked:
        if c['kind'] == 'withdraw':
            # A withdrawn change leaves the cited value: older claims of other values go.
            live = [x for x in live if x['kind'] != 'value' or canon(field, x['value'], cities) == here]
            ranked_below = [x for x in ranked if _rank(x) > _rank(c)]
            live += [x for x in ranked_below if x['kind'] == 'value' and canon(field, x['value'], cities) == here]
            break
        live.append(c)
    if not live:
        return None, 'no research evidence for this field'
    top = live[0]
    if top['kind'] == 'remove':
        return None, 'the research removed this field (%s)' % top['origin']
    if canon(field, top['value'], cities) != here:
        return None, 'the entry value differs from the latest evidenced value (%s)' % top['origin']
    same = [c for c in live if c['kind'] == 'value' and canon(field, c['value'], cities) == here]
    why = 'no quoted evidence'
    for c in same:
        ok, record, why = _support(field, value, c, bodies)
        if ok:
            return dict(record, value=value), None
    return None, why


def assess_research(fields, bundle, bodies=None, cities=None):
    """Outcome for one entry from its research bundle. ``bodies`` answers quote lookups
    (default: the saved bodies under .bibcheck/research-pilot/)."""
    bodies = bodies or Bodies()
    cities = relevant_cities(fields, bundle, cities or {})
    candidate = {'source': SOURCE, 'policy': POLICY, 'doi': None, 'checked_fields': deepcopy(fields),
                 'raw_record': deepcopy(bundle), 'cities': cities, 'identity': {}, 'fields': {},
                 'not_required': {}, 'flags': [], 'issues': [], 'evidence': {}, 'category': 'held'}
    issues = candidate['issues']
    try:
        if fields.get('doi'):
            candidate['doi'] = normalize_doi(fields['doi'])
    except ValueError as exc:
        issues.append('doi: ' + str(exc))
    issues += gates(bundle)
    claims = bundle['claims']
    types = sorted((c for c in claims if c['field'] == 'ENTRYTYPE' and c['kind'] == 'value'), key=_rank)
    if types and canon('entrytype', types[0]['value']) != canon('entrytype', fields.get('ENTRYTYPE')):
        issues.append('ENTRYTYPE: the latest evidence names @%s, the entry is @%s (%s)'
                      % (types[0]['value'], fields.get('ENTRYTYPE'), types[0]['origin']))
    for field in sorted(f for f in fields if f not in STRUCTURAL):
        if field in NOT_REQUIRED:
            candidate['not_required'][field] = NOT_REQUIRED[field]
            continue
        record, why = _field(field, fields[field], claims, bodies, cities)
        if why:
            issues.append(field + ': ' + why)
            continue
        candidate['fields'][field] = record
        candidate['evidence'][field] = {'local': fields[field], 'source': record['claimed'], 'match': True}
        if record.get('flag'):
            candidate['flags'].append(field + ': ' + record['flag'])
    # Identity: a researcher row's identity quote found in its saved body; else the title
    # as quoted by a resolution, the user's decision or the manual research (their quote
    # locates the work at its own URL).
    for r in bundle['rows']:
        ident = r.get('identity') or {}
        if ident.get('url') and ident.get('quote'):
            ok, sha = bodies.found(ident['url'], ident['quote'])
            candidate['identity'] = {'origin': r['origin'], 'url': ident['url'], 'quote': ident['quote'],
                                     'found': bool(ok), 'body_sha256': sha}
            if ok:
                break
    if not candidate['identity'].get('found'):
        title = candidate['fields'].get('title')
        if title and title['origin'].startswith(('resolution/', 'crosswave', 'manual')):
            candidate['identity'] = {'origin': title['origin'], 'from_field': 'title'}
            if title.get('flag'):
                candidate['flags'].append('identity: ' + title['flag'])
        else:
            issues.append('identity: no identity quote found in a saved body')
    candidate['issues'] = list(dict.fromkeys(issues))
    if not candidate['issues']:
        candidate['category'] = 'verified'
    result = outcome('needs_review' if candidate['issues'] else 'metadata_verified', candidate['issues'], [candidate])
    if not candidate['issues']:
        result.update(accepted_source=SOURCE, accepted_record_id=evidence_id(candidate))
        if candidate['doi']:
            result['accepted_doi'] = candidate['doi']
    return result


def evidence_id(candidate):
    """Stable id of an approval: the sha256 of the checked fields and the evidence used."""
    keep = {k: candidate[k] for k in ('checked_fields', 'identity', 'fields')}
    return 'research:' + hashlib.sha256(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def relevant_cities(fields, bundle, cities):
    """The part of the bibliography's city -> US state table (postcheck.city_states) that
    the entry's addresses use, saved with the evidence so a re-check needs no bibliography."""
    P = postcheck()
    values = [fields.get('address') or ''] + [c['value'] for c in bundle['claims']
                                               if c['field'] == 'address' and c['kind'] == 'value']
    wanted = set()
    for v in values:
        parts = str(v).split(',')
        wanted.update(P.fold(','.join(parts[:i + 1])) for i in range(len(parts)))
    return {k: cities[k] for k in sorted(wanted) if k in cities}


# ------------------------------------------------------------------ cache rows

PRESERVED = ('auto_review', 'discovery_review', 'catalogue_review', 'preprint_review', 'arxiv_review',
             'research_attempt', 'datacite_review', 'acl_review', 'sfn_review', 'osf_review')
HELD_BY_CONTEXT = ('Research evidence verifies every field; the approval is held by known DOI-linked evidence '
                   '(resolution-plan rule: retractions go to the user; a content-only erratum is auto-verified '
                   'only once its text is read)')


def merge(previous, result):
    """The research outcome on top of the entry's previous review (as osf_review.merge):
    earlier candidates are kept, the research candidate replaces an older one, and an
    approval that known DOI-linked evidence contradicts (notice, suffix or coordinate
    conflict, registry update notice) stays needs_review, as for every route approval."""
    from preprint_review import context_issues
    result = deepcopy(result)
    result['candidates'] = [c for c in previous.get('candidates', []) if c.get('source') != SOURCE] + result['candidates']
    result['attempts'] = previous.get('attempts', []) + [{'source': SOURCE, 'url': None}]
    candidate = result['candidates'][-1]
    if result['status'] == 'metadata_verified':
        issues = context_issues(candidate['checked_fields'], result['candidates'], result.get('accepted_doi'))
        if issues:
            result.update(status='needs_review', issues=issues + [HELD_BY_CONTEXT] + [
                i for i in previous.get('issues', []) if i not in issues])
            for name in ('accepted_doi', 'accepted_source', 'accepted_record_id'):
                result.pop(name, None)
    for name in PRESERVED:
        if name in previous:
            result[name] = deepcopy(previous[name])
    result[NAME] = {'policy': POLICY, 'category': candidate['category']}
    return result


def recheck(candidate, bodies=None):
    """Re-derive a saved research candidate: with the saved bodies when this clone has
    validate.py's body cache, else from the quote results the candidate recorded."""
    if bodies is None:
        bodies = Bodies() if BODY_DIR.is_dir() else SavedBodies(candidate)
    return assess_research(candidate['checked_fields'], candidate['raw_record'], bodies, candidate.get('cities'))


def _saved_consistent(result, c):
    """The approval's own record is complete and self-consistent: every checked field
    (except ID/ENTRYTYPE) has a record of that exact value backed by a quote found in a
    body of recorded sha256 (or flagged as read in a browser / from a scan), the identity
    is established, nothing is open, and the accepted id is the hash of that evidence."""
    fields = c['checked_fields']
    if c.get('category') != 'verified' or c.get('issues') or result.get('issues'):
        return False
    if result['accepted_record_id'] != evidence_id(c):
        return False
    doi = normalize_doi(fields['doi']) if fields.get('doi') else None
    if c.get('doi') != doi or result.get('accepted_doi') != doi:
        return False
    required = set(fields) - set(STRUCTURAL) - set(c.get('not_required') or {})
    if set(c['fields']) != required:
        return False
    for name in required:
        record = c['fields'][name]
        if record.get('value') != fields[name] or not record.get('evidence'):
            return False
        found = [e for e in record['evidence'] if e.get('found') and re.fullmatch(r'[0-9a-f]{64}', e.get('body_sha256') or '')]
        if not found and record.get('flag') != 'browser_or_scan':
            return False
    ident = c.get('identity') or {}
    if not (ident.get('found') and ident.get('body_sha256')) and not (
            ident.get('from_field') == 'title' and 'title' in c['fields']
            and c['fields']['title']['origin'].startswith(('resolution/', 'crosswave', 'manual'))):
        return False
    return True


def valid_research_approval(result):
    """A research approval re-checked offline from the evidence saved in ``result``.

    Always: the saved record is complete and self-consistent (``_saved_consistent``) and
    no known DOI-linked evidence contradicts it (preprint_review.context_issues, as for
    the other route approvals). Then, where this clone can: with validate.py's body cache
    (.bibcheck/research-pilot/) the saved candidate must re-assess to the same approval,
    every quote searched again in its saved body and each body's sha256 the recorded one
    (a missing or changed body fails); without the cache (a fresh clone, CI) the
    re-assessment uses the recorded quote results, and where validate.py and the
    post-check's normalisers cannot be imported (the minimal verification requirements
    lack pandas) the self-consistency check stands alone, the same trust the snapshot
    import gives a saved Crossref candidate."""
    if result.get('accepted_source') != SOURCE or result.get('external_evidence'):
        return False
    try:
        from preprint_review import context_issues
        saved = [c for c in result['candidates'] if c.get('source') == SOURCE]
        if len(saved) != 1:
            return False
        c = saved[0]
        if context_issues(c['checked_fields'], result['candidates'], result.get('accepted_doi')):
            return False
        if not _saved_consistent(result, c):
            return False
        if BODY_DIR.is_dir():
            checked = recheck(c, Bodies())
        else:
            try:
                validator(), postcheck()
            except ImportError:
                return True
            checked = recheck(c, SavedBodies(c))
        return (checked['status'] == 'metadata_verified'
                and checked['accepted_record_id'] == result['accepted_record_id']
                and checked.get('accepted_doi') == result.get('accepted_doi')
                and checked['candidates'][0] == c)
    except (ValueError, KeyError, TypeError, AttributeError, ImportError, OSError):
        return False


def reason_class(issue):
    """A short class for grouping the reasons an entry is not approved."""
    field, _, why = issue.partition(': ')
    if field == 'research':
        for text, name in (('needs_user', 'needs_user (post-check residue)'),
                           ('verdict', 'verdict ambiguous/no_source, no resolution'),
                           ('removal', 'marked for removal'), ('no researcher row', 'no research row'),
                           ('answered', 'user answered wrong/unsure (wave 1)'),
                           ('drops', 'resolution drops it')):
            if text in why:
                return name
        return 'research gate: ' + why
    if field == 'identity':
        return 'identity quote not found'
    for text, name in (('no research evidence', 'field never researched'),
                       ('differs from the latest', 'value differs from the latest evidence'),
                       ('no quoted evidence', 'value has no verbatim quote (reviewer/user prose only)'),
                       ('quote not found', 'quote not found in the saved body'),
                       ('no saved body', 'no saved body for the quoted URL'),
                       ('value words', 'value words not in the quotes'),
                       ('removed this field', 'field the research removed is still present'),
                       ('latest evidence names', 'entry type differs from the evidence'),
                       ('next_start', 'inferred end page not supported')):
        if text in why or text in issue:
            return name + ('' if field == 'ENTRYTYPE' else ' (%s)' % field)
    return issue


def run_research_approve(filename, cache, report=None, dry_run=False, root=ROOT, exclude=(), bodies=None,
                         keys=None):
    """Approve every needs_review entry the research verifies (see the module docstring).

    Reads only saved files; never makes a network request. Writes each approval (and each
    all-fields-verified entry held by a DOI-linked notice, which keeps needs_review with
    the research evidence attached) through ``Cache.put``. An entry whose latest review
    already carries this research candidate is not rewritten, so a repeat run writes
    nothing. Returns {'rows': {key: row}, 'counts': ...}."""
    from verification import load_entries, run_lock, write_report
    bodies = bodies or Bodies()
    rows = {}
    with run_lock(cache):
        entries = load_entries(filename)
        if keys is not None and set(keys) - entries.keys():
            raise ValueError('research-approve keys must name existing citations')
        P = postcheck()
        cities = P.city_states({k: e['fields'] for k, e in entries.items()})
        bundles = load_evidence(root, set(entries), exclude)
        writes = 0
        try:
            for key, entry in entries.items():
                if keys is not None and key not in keys:
                    continue
                previous = cache.get(filename, entry)
                if previous and previous['status'] == 'metadata_verified' and previous.get('accepted_source') == SOURCE:
                    # An earlier research approval is re-assessed: evidence files, rules or
                    # saved bodies may have changed. One that no longer holds is reopened.
                    if key in bundles:
                        again = merge(previous, assess_research(entry['fields'], bundles[key], bodies, cities))
                        own = [c for c in previous['candidates'] if c.get('source') == SOURCE]
                        if own == [again['candidates'][-1]] and again['status'] == 'metadata_verified':
                            continue
                    else:
                        again = merge(previous, outcome('needs_review', ['research: no research row for this entry']))
                        again['candidates'] = [c for c in again['candidates'] if c.get('source') != SOURCE]
                    if again['status'] == 'metadata_verified':
                        predicted = cache.retain_notices(entry, again)
                    else:
                        predicted = dict(again, issues=['Research approval withdrawn: the research evidence no longer '
                                                        'verifies every field'] + again.get('issues', []))
                    if not dry_run:
                        predicted = cache.put(filename, entry, predicted)
                        writes += 1
                    rows[key] = {'status_before': 'metadata_verified', 'status': predicted['status'],
                                 'outcome': 'reapproved' if predicted['status'] == 'metadata_verified' else 'withdrawn',
                                 'reasons': [] if predicted['status'] == 'metadata_verified' else predicted['issues'],
                                 'flags': again['candidates'][-1].get('flags', []) if key in bundles else []}
                    continue
                if not previous or previous['status'] != 'needs_review':
                    continue
                row = {'status_before': previous['status']}
                if previous.get('external_evidence'):
                    row.update(outcome='skipped', reasons=['external evidence attached: human review required'])
                    rows[key] = row
                    continue
                if key not in bundles:
                    row.update(outcome='not_researched', reasons=['research: no research row for this entry'])
                    rows[key] = row
                    continue
                result = merge(previous, assess_research(entry['fields'], bundles[key], bodies, cities))
                candidate = result['candidates'][-1]
                row['flags'] = candidate['flags']
                if candidate['category'] != 'verified':
                    row.update(outcome='not_approved', reasons=candidate['issues'])
                    rows[key] = row
                    continue
                # What Cache.put would store: retain_notices may reopen an approval.
                predicted = cache.retain_notices(entry, result)
                own = [c for c in previous.get('candidates', []) if c.get('source') == SOURCE]
                if own == [candidate] and previous.get('status') == predicted['status']:
                    row.update(outcome='unchanged', status=previous['status'])
                    rows[key] = row
                    continue
                if not dry_run:
                    predicted = cache.put(filename, entry, result)
                    writes += 1
                row.update(status=predicted['status'],
                           outcome='approved' if predicted['status'] == 'metadata_verified' else 'held_by_notice',
                           reasons=[] if predicted['status'] == 'metadata_verified' else predicted.get('issues', []))
                rows[key] = row
        finally:
            if report and not dry_run:
                write_report(filename, cache, report)
    counts = {'outcomes': {}, 'first_reason': {}, 'all_reasons': {}, 'flags': {}, 'writes': writes}
    for row in rows.values():
        counts['outcomes'][row['outcome']] = counts['outcomes'].get(row['outcome'], 0) + 1
        if row['outcome'] in ('not_approved', 'not_researched', 'skipped', 'withdrawn'):
            classes = list(dict.fromkeys(reason_class(i) for i in row['reasons']))
            counts['first_reason'][classes[0]] = counts['first_reason'].get(classes[0], 0) + 1
            for c in classes:
                counts['all_reasons'][c] = counts['all_reasons'].get(c, 0) + 1
        for f in row.get('flags', []):
            counts['flags'][f] = counts['flags'].get(f, 0) + 1
    for name in ('first_reason', 'all_reasons', 'flags'):
        counts[name] = dict(sorted(counts[name].items(), key=lambda kv: (-kv[1], kv[0])))
    return {'rows': rows, 'counts': counts}


def uncommitted_evidence(root=ROOT):
    """Evidence files with uncommitted changes (another session may still be writing
    them): git status of the research folders. Raises when git cannot answer."""
    import subprocess
    env = dict(os.environ)
    if 'DEVELOPER_DIR' not in env and Path('/Library/Developer/CommandLineTools').is_dir():
        env['DEVELOPER_DIR'] = '/Library/Developer/CommandLineTools'
    dirs = [PILOT, WAVES, RESOLUTIONS, str(Path(MANUAL).parent), RENAMES, DELETIONS]
    out = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all', '--'] + dirs, cwd=root, env=env,
                         check=True, capture_output=True, text=True).stdout
    changed = {line[3:].strip().strip('"') for line in out.splitlines() if line.strip()}
    return sorted(set(evidence_files(root)) & changed)


from verification import register_approval_validator  # noqa: E402  (hook contract 2026-09-25)
register_approval_validator(valid_research_approval)
