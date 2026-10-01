"""Research route: record entries the research waves verified field by field.

On this branch the module's job is to re-check saved research approvals
(``valid_research_approval``, run by ``crossref restore`` on every row of
verification/baseline.jsonl.gz): each saved approval carries its quotes, URLs and body
hashes, and is re-derived from them offline. The research folders the approvals were
built from, the route's design notes and the ``crossref research-approve`` command that
read them are on the archive branch ``verification-records-2026-09``
(https://github.com/ContextLab/CDL-bibliography/tree/verification-records-2026-09).
``load_evidence`` and ``run_research_approve`` still read that layout under any
``root`` (the tests use a frozen copy in tests/fixtures/research_route/).

Evidence layout (relative to ``root``):

* researcher rows: ``verification/research-pilot-2026-09-24/batch-*.json`` and
  ``verification/research-2026-09-25/wave*/batch-*.json`` (schema: the pilot's PROTOCOL.md);
* the pilot's applied proposals (``pilot-proposals.json``, ``followup.json``);
* each wave's ``merged.json`` (post-check final values with provenance; ``needs_user``,
  ``remove_entry``, verdict);
* the user's cross-wave decisions (``crosswave/applied-decisions.json``);
* the resolution batches (``verification/resolution-2026-09-26/batch-*.json``, 01-39; a file
  that is not valid JSON is refused, never read as "no decision");
* the manual research of 2026-09-26 (``research-2026-09-26-manual/proposals.json``);
* the notice classification of 2026-09-27 (``verification/resolution-2026-09-27/
  notices-classified.json``): what each DOI-linked notice that held an entry actually is.

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
   route approval), unless the notice classification settles every such notice under the
   resolution-plan rules (``notice_adjudication``): a content-only erratum, a metadata
   correction whose corrected value the entry already carries, an unread notice with no
   retraction or expression of concern recorded (flag ``notice_unread``), a same-DOI new
   version, a notice that is the cited work itself, a PubMed record that is no notice or
   belongs to another work, or a coordinate conflict the Crossref value (already in the
   entry) wins. A retraction or expression of concern, classified or signalled by any
   saved record, is never approved.

Evidence forms (the post-check's own, ``postcheck.evidence_items`` / ``inferred_end_page`` /
``catalogue_extent`` / ``roman_page_prefix``): several quotes whose union covers the value
(``evidence`` / ``extra_evidence``), end page = next item's printed start - 1
(``next_start``), catalogue extent 'N p.' for pages 1--N, a roman page prefix for the
volume. A chapter's page range whose start page an official contents list confirms, kept
under the partial-confirmation default, is approved with the flag ``pages_start_only``.
Author and editor lists compare braced group names ({RNS System in Epilepsy Study Group})
equal to the same name unbraced.

Quotes the user accepted without a fetched body (read in a real browser, transcribed from
an image-only scan: resolution-plan README, round 2) count only for resolution and manual
rows whose notes say so, only when the quote itself contains the value's words, and are
flagged ``browser_or_scan`` in the saved evidence.

Nothing here makes a network request.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

from verification import normalize_doi, notice_record_identity, outcome

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'research-evidence'
POLICY = '1'
NAME = 'research_route'
# validate.py's fetched bodies. BIBCHECK_RESEARCH_BODIES points both at another directory
# (the test suite sets it, so live fetches in tests never write into this clone's cache).
BODY_DIR = Path(os.environ.get('BIBCHECK_RESEARCH_BODIES') or ROOT / '.bibcheck' / 'research-pilot')

PILOT = 'verification/research-pilot-2026-09-24'
WAVES = 'verification/research-2026-09-25'
RESOLUTIONS = 'verification/resolution-2026-09-26'
MANUAL = 'verification/research-2026-09-26-manual/proposals.json'
NOTICES = 'verification/resolution-2026-09-27/notices-classified.json'
RENAMES = 'verification/key-renames.json'
DELETIONS = 'verification/key-deletions.json'
# The mop-up resolution batch (2026-09-27, research route final): resolution rows in the
# batch schema for entries the route still held, kept beside the route's own records. It
# is read as resolution batch 40 (newest), keyed as committed like batches 27 on.
MOPUP = 'verification/research-route-2026-09-27/batch-40.json'
MOPUP_BATCH = 'batch-40'

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


def validator():
    """The research validator's quote matching (bibcheck/research_quotes.py, copied from
    validate.py; never fetches)."""
    import research_quotes
    return research_quotes


def postcheck():
    """The research post-check's house normalisers (bibcheck/research_forms.py, copied
    from postcheck.py)."""
    import research_forms
    return research_forms


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


def _group_inner(name):
    """The text of a name that is one braced group ({RNS System in Epilepsy Study Group},
    {{Jupyter Development Team}}), else None. A braced particle inside a personal name
    (R {La Joie}) is not a group."""
    name = name.strip()
    while name.startswith('{') and name.endswith('}'):
        inner, depth = name[1:-1], 0
        for ch in inner:
            depth += (ch == '{') - (ch == '}')
            if depth < 0:
                return None  # '{A} and {B}' style: the outer braces are not one pair
        if depth:
            return None
        name = inner.strip()
        if not (name.startswith('{') and name.endswith('}')):
            return name
    return None


def braced_groups(value):
    """The folded texts of the braced group names in an author/editor list (formatter
    fix 9f84506 keeps whole-braced group names as given)."""
    P = postcheck()
    out = set()
    for name in P.split_names(str(value or '')):
        inner = _group_inner(name)
        if inner:
            out.add(_text(inner))
    return frozenset(out)


def canon(field, value, cities=None, groups=()):
    """The house form of ``value`` for comparison: the post-check's normalisers for the
    field (names, pages, issue ranges, ordinals, proceedings booktitles, em dashes,
    US addresses), then LaTeX accents to Unicode, braces dropped, dashes and
    whitespace folded, case folded. Two values with one canon are one value.

    ``groups`` (author/editor): the folded group names the entry prints braced; the same
    name written unbraced in the evidence is read as that group, not as given names and
    a surname (the name normaliser would initial it: 'R N S S I E S Group')."""
    P = postcheck()
    field = field.lower()
    v = str(value if value is not None else '').strip()
    if field in ('author', 'editor'):
        names = P.split_names(v)
        groups = set(groups) | {g for g in (_group_inner(n) for n in names) if g}
        groups = {_text(g) for g in groups}
        v = ' and '.join('{%s}' % (_group_inner(n) or n) if _text(_group_inner(n) or n) in groups else n
                         for n in names)
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
    """{url, quote} items of one evidence value: a researcher's evidence list, or a
    resolution/manual/cross-wave set read by the post-check's own ``evidence_items`` (its
    url/quote, then every item of ``evidence`` and ``extra_evidence``; the union of the
    quotes covers the value). An item without a URL or quote is kept (as None), so a set
    whose items must all be found is refused, as ``resolution_quote`` refuses it."""
    if isinstance(spec, list):
        return [{'url': i.get('url'), 'quote': i.get('quote')} for i in spec if isinstance(i, dict)]
    return postcheck().evidence_items(spec)


def _claim(field, value, items, origin, row_key, lenient=False, next_start=None, all_items=False, kind='value'):
    """One piece of research about one field: ``kind`` 'value' (the field is ``value``;
    ``items`` quote it, possibly none), 'remove' (the field must go) or 'withdraw' (a
    research change to the field was withdrawn: the cited value stays)."""
    field = 'ENTRYTYPE' if field.lower() == 'entrytype' else field.lower()
    return {'field': field, 'kind': kind, 'value': None if value is None else str(value), 'items': items,
            'origin': origin, 'row_key': row_key, 'lenient': bool(lenient), 'next_start': next_start,
            'all_items': bool(all_items)}


def rename_walk(renames, deleted):
    """old key -> current key, following key-renames.json in log order from entry
    ``start`` (default: the whole log); a deleted key maps to None (never followed)."""
    def walk(key, start=0):
        if key in deleted:
            return None
        cur = key
        for r in renames[start:]:
            if r['old_key'] == cur:
                cur = r['new_key']
        return cur
    return walk


# Resolution batches from number 27 on were written against the cdl.bib of their commit:
# each row's key names the entry as it was then (apply-2026-09-27b-final README: "Every key
# was found in cdl.bib as written"). Their rows follow only the renames logged after the
# batch was committed. Batch 30's Frie08 is Friendly's handbook chapter (keyed Frie08 since
# the wave-8 renames); following the whole log took it through Frie08 -> Frie08a -> Frie12
# to Friedman's chapter. Earlier batches name entries by older keys (batch 23's Frie08 is
# the Frie08 that became Frie12) and follow the whole log.
KEYED_AS_COMMITTED_FROM = 27


def _git(root, *args):
    import subprocess
    env = dict(os.environ)
    if 'DEVELOPER_DIR' not in env and Path('/Library/Developer/CommandLineTools').is_dir():
        env['DEVELOPER_DIR'] = '/Library/Developer/CommandLineTools'
    return subprocess.run(['git', *args], cwd=root, env=env, capture_output=True, text=True)


def renames_when_committed(root, rel, renames):
    """How many entries key-renames.json had in the commit that added ``rel``: the rows of
    ``rel`` follow only the renames after them. None when ``root`` is not the top of a git
    work tree (a frozen test layout) or ``rel`` was never committed; then the whole log is
    followed. Raises when the log of that commit is not a prefix of the current one (the
    log is append-only: a rewritten log would silently re-key rows)."""
    try:
        top = _git(root, 'rev-parse', '--show-toplevel')
    except OSError:
        return None
    if top.returncode or Path(top.stdout.strip()).resolve() != Path(root).resolve():
        return None
    added = _git(root, 'log', '--diff-filter=A', '--format=%H', '--', rel).stdout.split()
    if not added:
        return None
    then = _git(root, 'show', '%s:%s' % (added[-1], RENAMES))
    old = json.loads(then.stdout) if then.returncode == 0 else []
    if [(r['old_key'], r['new_key']) for r in old] != [(r['old_key'], r['new_key']) for r in renames[:len(old)]]:
        raise ValueError('%s: the rename log of the commit that added %s is not a prefix of the current log'
                         % (RENAMES, rel))
    return len(old)


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
    files += [root / MOPUP]
    files += [root / MANUAL, root / NOTICES, root / RENAMES, root / DELETIONS]
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
        if rel not in files:
            return None
        try:
            return json.loads((root / rel).read_text(encoding='utf-8'))
        except ValueError as exc:
            # A half-written file must never be read as "no research" (postcheck.load_resolutions).
            raise ValueError('research evidence file %s is not valid JSON (%s); leave it out with exclude'
                             % (rel, exc)) from exc

    renames = read(RENAMES) or []
    deleted = {r['key'] for r in (read(DELETIONS) or [])}
    walk = rename_walk(renames, deleted)
    bundles = {}

    def bundle(key, start=0):
        cur = walk(key, start)
        if cur is None or (bib_keys is not None and cur not in bib_keys):
            return None
        return bundles.setdefault(cur, {'rows': [], 'claims': [], 'merged': [], 'resolutions': [],
                                        'decisions': []})

    # The user's answers on the wave pages, read first: a merged needs_user row the user
    # did not mark correct keeps the reasons the post-check left it to the user.
    answers = {}
    for rel in files:
        parts = Path(rel).parts
        if len(parts) >= 3 and parts[-2] == 'decisions' and rel.startswith(WAVES + '/wave'):
            d = read(rel)
            answers[(parts[-3], d['key'])] = d.get('verdict')

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
                m = {'origin': wave + '/merged', 'key': row['key'], 'verdict': row.get('verdict'),
                     'needs_user': bool(row.get('needs_user')), 'remove_entry': row.get('remove_entry')}
                if m['needs_user'] and answers.get((wave, row['key'])) != 'correct':
                    m['residue'] = needs_user_residue(row, walk(row['key']))
                b['merged'].append(m)
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
        elif rel.startswith(RESOLUTIONS + '/batch-') or rel == MOPUP:
            stem = MOPUP_BATCH if rel == MOPUP else path.stem
            origin = 'resolution/' + stem
            number = re.fullmatch(r'batch-(\d+)', stem)
            start = (renames_when_committed(root, rel, renames)
                     if number and int(number[1]) >= KEYED_AS_COMMITTED_FROM else None) or 0
            for row in read(rel):
                b = bundle(row['key'], start)
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
    # The notice classification is attached to entries that have research (it is no
    # research of its own); it never creates a bundle.
    for row in read(NOTICES) or []:
        cur = walk(row.get('key', ''))
        if cur in bundles:
            bundles[cur].setdefault('notices', []).append(
                {k: row.get(k) for k in ('key', 'notice_doi', 'class', 'quote', 'url', 'corrected_fields', 'notes',
                                          'records')
                 if k in row})
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


class CachedOrSavedBodies:
    """Offline re-check with a body cache that may be partial: a body the cache holds is
    searched again (a changed body changes its sha256 and fails the re-check); a URL whose
    body it does not hold is taken as the saved evidence recorded it, exactly as a clone
    without the cache does. A missing file is not evidence against the approval: an empty
    or partial .bibcheck/research-pilot/ (made by a test or a validate.py run that fetched
    a few URLs) used to reject every research approval, so `crossref restore` restored
    nothing (2026-09-30)."""

    def __init__(self, candidate, bodies=None):
        self.local = bodies or Bodies()
        self.saved = SavedBodies(candidate)

    def found(self, url, quote):
        text, _ = self.local.get(url)
        if text is None:
            return self.saved.found(url, quote)
        return self.local.found(url, quote)


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
    if claim['all_items'] and len(items) != len(claim['items']):
        # postcheck.resolution_quote refuses a set with an item lacking its URL or quote.
        return False, record, 'an evidence item has no URL or quote'
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
    # The user's inference rules, in postcheck.resolution_quote's order: with a
    # next_start only the end-page rule applies.
    if field == 'pages' and nxt:
        ok, why = P.inferred_end_page(V, value, quotes, urls, nxt['quote'])
        if ok:
            record['rule'] = "end page = next item's printed start - 1"
            return True, record, None
        return False, record, 'value words %s are not in the quotes; %s' % (missing, why)
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


def needs_user_residue(row, current_key):
    """Why the post-check left a merged row to the user (postcheck.needs_user): the
    resolution's residue lines, else the unresolved verdict, each held or open flag and a
    key plan other than 'keep'. ``current_key`` is the entry the row's key now names."""
    if row.get('resolution'):
        return [{'kind': 'residue', 'detail': str(line)} for line in row['resolution'].get('residue') or []]
    out = []
    if row.get('verdict') in ('ambiguous', 'no_source') and not row.get('user_resolved'):
        out.append({'kind': 'verdict', 'detail': row['verdict']})
    plan = row.get('key_plan') or {}
    for f in row.get('flags') or []:
        if f.get('action') in ('held', 'flag'):
            out.append({'kind': 'flag', 'code': f.get('code'), 'field': f.get('field'),
                        'merged_into': plan.get('merge_into') == current_key != row.get('key')})
    if plan.get('action') != 'keep':
        out.append({'kind': 'key_plan', 'code': plan.get('action'),
                    'merged_into': plan.get('merge_into') == current_key != row.get('key')})
    return out


# Residue a later resolution decision settles under the recorded rules (resolution-plan
# README). Anything else stays with the user.
DOI_RESIDUE = re.compile(r"^(?:doi: the resolution's value .* did not survive the post-check|"
                         r"doi_title_unavailable on doi is held)")


def residue_settled(reason, fields):
    """True when one needs_user reason (``needs_user_residue``) is settled for an entry
    whose resolution decision is apply/keep:

    - an unresolved verdict: the resolution decision settles it (as for any row);
    - ``field_not_found``: the every-field rule quotes each field the entry has, so a
      field the researcher did not find is either quoted by later evidence or absent;
    - ``not_in_bib`` / ``duplicate`` flags and a ``duplicate`` key plan, when the row's key
      was merged into the entry now assessed (the cross-wave duplicate decision; the row
      key walks to this entry and the plan named it);
    - the DOI residue of an unavailable Crossref record (``doi_title_unavailable``), when
      the entry carries its DOI: the (default) "A DOI that doi.org registers and the
      publisher's own article page prints ... keep it" (McCaEtal06), with the DOI value
      itself quoted by the every-field rule."""
    kind, code = reason.get('kind'), reason.get('code')
    if kind == 'verdict':
        return True
    if kind == 'flag' and code == 'field_not_found':
        return True
    if kind in ('flag', 'key_plan') and code in ('not_in_bib', 'duplicate'):
        return bool(reason.get('merged_into'))
    if (kind == 'flag' and code == 'doi_title_unavailable') or (
            kind == 'residue' and DOI_RESIDUE.match(reason.get('detail') or '')):
        return bool(str(fields.get('doi') or '').strip())
    return False


def gates(bundle, fields=None):
    """Issues that stop an approval whatever the fields say."""
    fields = fields or {}
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
    if 'drop' in decisions and len(decisions) > 1:
        # 'apply' and 'keep' both settle the entry (a later batch re-evidencing a kept
        # entry applies its values); a drop beside either is a real conflict.
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
        # correct was applied as proposed (apply-2026-09-26-wave1), which settles its
        # needs_user. Held fields stayed as cited and are checked like any other field.
        if m['needs_user'] and user.get((wave, m['key'])) != 'correct':
            if not (settled and m.get('residue') and all(residue_settled(r, fields) for r in m['residue'])):
                issues.append('research: needs_user (%s)' % m['origin'])
        if m['remove_entry']:
            issues.append('research: marked for removal (%s)' % m['origin'])
    for d in bundle['decisions']:
        if d.get('remove_entry'):
            issues.append('research: the user marked it for removal (%s)' % d['origin'])
    return issues


# The partial-confirmation default (resolution-plan README): "Chapter pages where an
# official contents list confirms the start page but nothing shows the end page or the
# next chapter's start: keep the cited range if its start page matches". A resolution or
# manual row invokes it in its notes ("confirms the start page", "the start page 64 is
# confirmed", "partly-confirmed"); a negated or unconfirmed start page does not match.
PARTIAL_PAGES = re.compile(r"(?:\bconfirm(?:s|ed|ing)?\s+(?:the\s+|its\s+)?start\s+page"
                           r"|\bstart\s+page\s+(?:\d+\s+)?(?:is\s+)?(?:now\s+)?confirmed"
                           r"|\bstart\s+\d+\s+confirmed|\bpart(?:ly|ially)[- ]confirmed|\bpartial[- ]confirmation)", re.I)
CHAPTER_TYPES = ('incollection', 'inbook')
START_ONLY_RULE = 'chapter start page confirmed by an official contents list (partial-confirmation default)'


def _start_only(value, claims, bundle, fields, bodies):
    """(record, issue) for a chapter page range S--E whose start page S a found quote
    prints, when a resolution or manual row keeps the range under the partial-confirmation
    default. The quotes are the pages claims' own; when no row quotes the pages at all,
    a found quote of that row's other fields that its notes name as the contents line
    ('R A RESCORLA A R WAGNER 64': the notes give the start page). A quote printing a
    range from S to another end refuses it; so does any other start page."""
    V, P = validator(), postcheck()
    if canon('entrytype', fields.get('ENTRYTYPE')) not in CHAPTER_TYPES:
        return None, 'the entry is not a chapter'
    m = P.PAGE_RANGE.match(str(value or ''))
    if not m or int(m[2]) < int(m[1]):
        return None, 'the value is not one page range S--E'
    start, end = m[1], m[2]
    rows = [r for r in bundle.get('resolutions', []) + [r for r in bundle.get('rows', []) if r['origin'] == 'manual']
            if PARTIAL_PAGES.search(r.get('notes') or '')]
    if not rows:
        return None, 'no resolution keeps the range under the partial-confirmation default'
    pools = [c for c in claims if c['kind'] == 'value']
    if not pools:
        # The row's own quotes of other fields, when its notes cite the start page.
        origins = {r['origin'] for r in rows
                   if re.search(r'(?<!\d)%s(?!\d)' % start, r.get('notes') or '')}
        pools = [c for c in bundle['claims'] if c['kind'] == 'value' and c['origin'] in origins]
    contrary = re.compile(r'(?<!\d)%s\s*(?:-{1,3}|\u2013|\u2014)\s*(\d+)' % start)
    for c in pools:
        items = [i for i in c['items'] if i.get('url') and i.get('quote')]
        record = {'origin': c['origin'], 'row_key': c['row_key'], 'claimed': value, 'evidence': [],
                  'flag': 'pages_start_only', 'rule': START_ONLY_RULE}
        for item in items:
            ok, sha = bodies.found(item['url'], item['quote'])
            if not ok and not c['lenient']:
                continue
            if any(int(x) != int(end) for x in contrary.findall(V.norm(item['quote']))):
                return None, 'a quote prints the start page %s with another end page' % start
            if V.value_supported('pages', start, [item['quote']], [item['url']])[0]:
                record['evidence'].append({'url': item['url'], 'quote': item['quote'], 'found': bool(ok),
                                           'body_sha256': sha})
        if record['evidence']:
            if not any(e['found'] for e in record['evidence']):
                # Read in a browser / transcribed from a scan (the row's notes say so).
                record['read'] = 'browser_or_scan'
            return record, None
    return None, 'no found quote prints the start page %s' % start


def _field(field, value, claims, bodies, cities, fields=None, bundle=None):
    """(record, issue) for one field of the entry. The latest research decision on the
    field must be its current value; that value must then be quoted and supported."""
    groups = braced_groups(value) if field in ('author', 'editor') else ()
    here = canon(field, value, cities, groups)

    def same_value(x):
        return canon(field, x['value'], cities, groups) == here
    ranked = sorted((c for c in claims if c['field'] == field), key=_rank)
    live = []
    for c in ranked:
        if c['kind'] == 'withdraw':
            # A withdrawn change leaves the cited value: older claims of other values go.
            live = [x for x in live if x['kind'] != 'value' or same_value(x)]
            ranked_below = [x for x in ranked if _rank(x) > _rank(c)]
            live += [x for x in ranked_below if x['kind'] == 'value' and same_value(x)]
            break
        live.append(c)
    start_only = field == 'pages' and fields is not None and bundle is not None
    if not live:
        if start_only:
            record, _ = _start_only(value, [], bundle, fields, bodies)
            if record:
                return dict(record, value=value), None
        return None, 'no research evidence for this field'
    top = live[0]
    if top['kind'] == 'remove':
        return None, 'the research removed this field (%s)' % top['origin']
    if not same_value(top):
        return None, 'the entry value differs from the latest evidenced value (%s)' % top['origin']
    same = [c for c in live if c['kind'] == 'value' and same_value(c)]
    whys = []
    for c in same:
        ok, record, why = _support(field, value, c, bodies)
        if ok:
            return dict(record, value=value), None
        whys.append(why)
    # The latest claim's failure is the reason (an older row's may only repeat less).
    why = whys[0] if whys else 'no quoted evidence'
    if start_only:
        record, _ = _start_only(value, same, bundle, fields, bodies)
        if record:
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
    issues += gates(bundle, fields)
    claims = bundle['claims']
    types = sorted((c for c in claims if c['field'] == 'ENTRYTYPE' and c['kind'] == 'value'), key=_rank)
    if types and canon('entrytype', types[0]['value']) != canon('entrytype', fields.get('ENTRYTYPE')):
        issues.append('ENTRYTYPE: the latest evidence names @%s, the entry is @%s (%s)'
                      % (types[0]['value'], fields.get('ENTRYTYPE'), types[0]['origin']))
    for field in sorted(f for f in fields if f not in STRUCTURAL):
        if field in NOT_REQUIRED:
            candidate['not_required'][field] = NOT_REQUIRED[field]
            continue
        record, why = _field(field, fields[field], claims, bodies, cities, fields, bundle)
        if why:
            issues.append(field + ': ' + why)
            continue
        candidate['fields'][field] = record
        candidate['evidence'][field] = {'local': fields[field], 'source': record['claimed'], 'match': True}
        if record.get('flag'):
            candidate['flags'].append(field + ': ' + record['flag'])
        if record.get('read'):
            candidate['flags'].append(field + ': ' + record['read'])
    # Identity: a researcher row's identity quote found in its saved body. When none is
    # (its quote has no saved body: read in a browser or from a scan; or no wave queued
    # the entry), the title as quoted by a resolution, the user's decision or the manual
    # research serves (resolution-plan README, (plan) line): that quote was found at its
    # own URL, or read in a browser / from a scan and flagged so. (Since 2026-09-27 the
    # substitute also stands when the researcher's quote is missing from a saved body;
    # README lists those approvals.)
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
    if bundle.get('notices'):
        candidate['notice'] = notice_adjudication(fields, bundle['notices'], cities)
        candidate['flags'] += ['notice: ' + f for f in candidate['notice']['flags']]
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
    """Stable id of an approval: the sha256 of the checked fields and the evidence used
    (with the notice adjudication, for an entry that has one)."""
    keep = {k: candidate[k] for k in ('checked_fields', 'identity', 'fields', 'notice') if k in candidate}
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


# ------------------------------------------------------------------ notices

# Classes of verification/resolution-2026-09-27/notices-classified.json (NOTICES.md) and
# what each means for an entry whose fields the research verifies (resolution-plan
# README: retractions go to the user; the (default) on unread notices; round 1: the
# publisher/Crossref record wins a coordinate conflict).
NEVER = ('retraction', 'expression_of_concern')
NOTICE_FLAGS = {'content_only': 'notice_content_only', 'unread': 'notice_unread',
                'metadata_correction': 'notice_metadata_correction', 'new_version': 'notice_new_version',
                'cited_work_is_notice': 'notice_is_the_cited_work', 'coordinate_conflict': 'notice_crossref_wins',
                'unrelated': 'notice_unrelated', 'no_notice': 'notice_none'}
# The classifier's notes must record that no retraction / expression of concern exists.
NO_RETRACTION = re.compile(r"\bnot\s+(?:a\s+)?retraction\b|\bno\s+retraction\b|\bno\s+(?:erratum/)?retraction\b", re.I)
SAME_DOI_VERSION = re.compile(r"\bno citation field changes\b", re.I)
CROSSREF_PAGE = re.compile(r'Crossref page\s+"([^"]+)"')


def _names(value, groups=()):
    P = postcheck()
    return [canon('author', n, None, groups) for n in P.split_names(str(value or ''))]


def notice_adjudication(fields, rows, cities=None):
    """{'classes', 'flags', 'issues'} for the classified notices of one entry. No issue
    means every notice is settled under the rules above; an issue holds the approval."""
    classes, flags, issues = [], [], []
    for row in rows:
        kind = str(row.get('class') or '')
        where = ' (%s)' % (row.get('notice_doi') or row.get('url') or '?')
        classes.append(kind)
        notes = str(row.get('notes') or '')
        if kind in NEVER:
            issues.append('notice: classified %s%s: never approved; the user decides' % (kind, where))
            continue
        if kind not in NOTICE_FLAGS:
            issues.append('notice: unknown classification %r%s' % (kind, where))
            continue
        for field, fix in (row.get('corrected_fields') or {}).items():
            field = field.lower()
            new = (fix or {}).get('new')
            if not (fix or {}).get('entry_already_matches') or not fields.get(field):
                issues.append('notice: the corrected %s is not yet in the entry%s' % (field, where))
            elif field in ('author', 'editor'):
                groups = braced_groups(fields[field])
                have = set(_names(fields[field], groups))
                if not set(_names(new, groups)) <= have:
                    issues.append('notice: the corrected %s %r is not in the entry%s' % (field, new, where))
            elif canon(field, new, cities) != canon(field, fields[field], cities):
                issues.append('notice: the corrected %s %r is not in the entry%s' % (field, new, where))
        if kind == 'unread' and not NO_RETRACTION.search(notes):
            issues.append('notice: unread, and no absence of a retraction/expression of concern recorded%s' % where)
        elif kind == 'new_version' and not SAME_DOI_VERSION.search(notes):
            issues.append('notice: new version with citation field changes%s' % where)
        elif kind == 'coordinate_conflict' and not row.get('corrected_fields'):
            m = CROSSREF_PAGE.search(str(row.get('quote') or ''))
            if not m or not fields.get('pages') or canon('pages', m[1]) != canon('pages', fields['pages']):
                issues.append('notice: the entry does not carry the Crossref pages of the conflict%s' % where)
        flags.append(NOTICE_FLAGS[kind])
    return {'classes': classes, 'flags': list(dict.fromkeys(flags)), 'issues': list(dict.fromkeys(issues))}


RETRACTION_WORDS = re.compile(r'retract|expression[ _-]of[ _-]concern|withdraw|removal', re.I)


def retraction_signals(candidates, doi=None):
    """Retractions / expressions of concern that any saved record carries (Europe PMC
    isRetracted or a 'Retraction in' / 'Expression of concern in' link or publication
    type, a Crossref update of that type, a JATS related-article of that type): whatever
    the classification says, these are never approved."""
    out = []
    for c in candidates:
        try:
            if doi and normalize_doi(c.get('doi') or '') != doi:
                continue  # another work's record (KeleFent10: a rejected candidate's retraction)
        except ValueError:
            pass
        raw = c.get('raw_record') or {}
        if c.get('source') == 'europepmc' and isinstance(raw, dict):
            labels = list((raw.get('pubTypeList') or {}).get('pubType') or []) + [
                r.get('type', '') for r in ((raw.get('commentCorrectionList') or {}).get('commentCorrection') or [])
                if isinstance(r, dict)]
            if raw.get('isRetracted') == 'Y' or any(RETRACTION_WORDS.search(str(x)) for x in labels):
                out.append('Europe PMC record of %s marks a retraction or expression of concern' % c.get('doi'))
        if c.get('source') == 'crossref':
            record = c.get('record') or {}
            for rel in (record.get('update-to') or []) + (record.get('updated-by') or []):
                if isinstance(rel, dict) and RETRACTION_WORDS.search(str(rel.get('type', ''))):
                    out.append('Crossref record of %s has a %s update' % (c.get('doi'), rel.get('type')))
        if c.get('source') == 'pmc-jats' and re.search(
                r'related-article-type="(?:retract\w*|expression-of-concern|concern)', str(c.get('raw_xml') or '')):
            out.append('JATS record of %s links a retraction or expression of concern' % c.get('doi'))
    return list(dict.fromkeys(out))


def notice_blocks(candidate, candidates):
    """Why the DOI-linked evidence beside a research approval still holds it: [] when the
    notice classification settles it and no saved record signals a retraction."""
    notice = candidate.get('notice')
    if not notice:
        return ['notice: no classification of the DOI-linked evidence (%s)' % NOTICES]
    return list(notice.get('issues') or []) + ['notice: ' + s for s in retraction_signals(candidates, candidate.get('doi'))]


# ------------------------------------------------------------------ cache rows

PRESERVED = ('auto_review', 'discovery_review', 'catalogue_review', 'preprint_review', 'arxiv_review',
             'research_attempt', 'datacite_review', 'acl_review', 'sfn_review', 'osf_review')
HELD_BY_CONTEXT = ('Research evidence verifies every field; the approval is held by known DOI-linked evidence '
                   '(resolution-plan rule: retractions go to the user; a classified content-only erratum, a '
                   'metadata correction already in the entry or an unread notice with no retraction recorded is '
                   'approved, anything unclassified is held)')


RETAINED = ('The research route approves this entry (its notice is settled by the classification), but '
            'Cache.retain_notices reopens every machine approval with a known DOI-linked notice')


def merge(previous, result):
    """The research outcome on top of the entry's previous review (as osf_review.merge):
    earlier candidates are kept, the research candidate replaces an older one, and an
    approval that known DOI-linked evidence contradicts (notice, suffix or coordinate
    conflict, registry update notice) stays needs_review, as for every route approval."""
    from preprint_review import context_issues
    result = deepcopy(result)
    # The research candidate, or None when the entry has lost its research row (a
    # withdrawal: the outcome carries no candidate, and the last earlier candidate is
    # another source's).
    candidate = result['candidates'][-1] if result['candidates'] else None
    result['candidates'] = [c for c in previous.get('candidates', []) if c.get('source') != SOURCE] + result['candidates']
    result['attempts'] = previous.get('attempts', []) + [{'source': SOURCE, 'url': None}]
    adjudicated = False
    if result['status'] == 'metadata_verified':
        issues = context_issues(candidate['checked_fields'], result['candidates'], result.get('accepted_doi'))
        blocks = notice_blocks(candidate, result['candidates']) if issues else []
        if blocks:
            result.update(status='needs_review', issues=issues + blocks + [HELD_BY_CONTEXT] + [
                i for i in previous.get('issues', []) if i not in issues
                and not i.startswith('Research evidence verifies every field; the approval is held')])
            for name in ('accepted_doi', 'accepted_source', 'accepted_record_id'):
                result.pop(name, None)
        adjudicated = bool(issues) and not blocks
    if result['status'] == 'metadata_verified':
        declared = notices_declaration(candidate, result['candidates'])
        if declared:
            result['notices_accounted'] = declared
    for name in PRESERVED:
        if name in previous:
            result[name] = deepcopy(previous[name])
    result[NAME] = {'policy': POLICY, 'category': candidate['category'] if candidate else 'no_research_row'}
    if adjudicated:
        result[NAME]['notice'] = 'settled by the notice classification'
    return result


def _table_dois(candidate):
    """The DOIs under which Cache.remember_notices files ``candidate`` (its notice,
    PubMed-suffix and article-locator tables), normalised as retain_notices queries them."""
    from auto_review import secondary_notice_flags, secondary_suffix_dois
    from source_locators import locator_dois
    out = set()
    for found in (secondary_notice_flags([candidate]), secondary_suffix_dois([candidate]), locator_dois([candidate])):
        if found:
            try:
                out.add(normalize_doi(next(iter(found))))
            except (ValueError, TypeError):
                pass
    return out


# Forward links by which a saved record says that a notice exists for its work: Europe PMC
# commentCorrection types ('Erratum in', 'Retraction in', 'Expression of concern in', ...;
# not 'Comment in' or 'Preprint in') and JATS related-article types ('correction-forward',
# 'retraction-forward', ...; not 'commentary', 'companion' or 'final-edited-article').
NOTICE_LINK_EPMC = re.compile(r'(erratum|corrigendum|correct|retract|concern|withdraw|update|republish)\w*\b.*\bin$', re.I)
NOTICE_LINK_JATS = re.compile(r'(erratum|corrigend|correct|retract|concern|withdraw|addend|update)(?!.*article$)', re.I)
# Classes that stand for a notice of the cited work (the others say the record is none).
NOTICE_SLOTS = ('content_only', 'metadata_correction', 'unread')


def notice_links(candidate):
    """The distinct notice links (kind, type, reference) one saved record carries."""
    links = set()
    raw = candidate.get('raw_record')
    if candidate.get('source') == 'europepmc' and isinstance(raw, dict):
        for r in (raw.get('commentCorrectionList') or {}).get('commentCorrection') or []:
            if isinstance(r, dict) and NOTICE_LINK_EPMC.search(str(r.get('type') or '')):
                links.add(('europepmc', str(r.get('type')), str(r.get('id') or r.get('reference') or '')))
    for tag in re.findall(r'<related-article\b[^>]*>', str(candidate.get('raw_xml') or '')):
        kind = re.search(r'related-article-type="([^"]*)"', tag)
        if kind and NOTICE_LINK_JATS.search(kind[1]):
            href = re.search(r'href="([^"]*)"', tag)
            links.add(('pmc-jats', kind[1], href[1] if href else tag))
    return links


RECORD_IDENTITY = re.compile(r'[0-9a-f]{64}')


def _named_records(rows):
    """{(doi, identity): class} for the exact DOI-linked records the classification rows
    name (``records``: [{'doi', 'identity'}], identity = verification.notice_record_identity,
    the digest of the record as the cache stores it). None when a name is malformed."""
    named = {}
    for row in rows:
        for rec in row.get('records') or []:
            if not isinstance(rec, dict) or not RECORD_IDENTITY.fullmatch(str(rec.get('identity') or '')):
                return None
            try:
                named[(normalize_doi(rec.get('doi')), rec['identity'])] = str(row.get('class') or '')
            except (ValueError, TypeError, AttributeError):
                return None
    return named


def _passive_locator(c, fields):
    """A matching article-locator record, which Cache.retain_notices passes over (it is
    no negative evidence): listed in a declaration, but it needs no classification."""
    from auto_review import secondary_notice_flags, secondary_suffix_dois
    from source_locators import locator_dois, locator_conflicts
    return bool(locator_dois([c]) and not locator_conflicts(fields, [c])
                and not secondary_notice_flags([c]) and not secondary_suffix_dois([c]))


def notices_declaration(candidate, candidates):
    """What this approval accounts for, for Cache.retain_notices (verification.py,
    NOTICE_ACCOUNTING): the notices the classification settled for the entry and the
    DOI-linked records it settled them beside. None when the entry has no classified
    notice, an unsettled one, or a classification row that identifies nothing.

    A row identifies its notice by the notice's DOI (``notice_doi``) or, when the notice
    has no registered DOI or the record is no notice at all (a PubMed author-suffix or
    article-locator record, another work's record), by the exact records it was made
    beside (``records``, the identity the cache stores; never a URL). A record named by
    identity must be one the row's class describes: a record of a no-notice class
    carries no notice link, and an 'unrelated' record is filed under another DOI than
    the cited one. Every DOI-linked record the approval stands beside must be named by a
    row, or (as before, for notices with DOIs) link no more notices (``notice_links``)
    than the classification settled: a notice listed after the classification was made,
    or a record nobody classified, is not accounted for. An entry without a DOI is
    checked against every candidate DOI (as retain_notices does), so each of its
    records must be named."""
    notice = candidate.get('notice')
    rows = (candidate.get('raw_record') or {}).get('notices') or []
    doi = candidate.get('doi')
    if not notice or notice.get('issues') or not rows:
        return None
    named = _named_records(rows)
    if named is None or any(not r.get('notice_doi') and not r.get('records') for r in rows):
        return None
    notice_dois = sorted({str(r.get('notice_doi') or '').lower() for r in rows} - {''}) if doi else []
    if not doi and any(r.get('notice_doi') for r in rows):
        return None
    if not notice_dois and not named:
        return None
    slots = sum(1 for r in rows if r.get('class') in NOTICE_SLOTS)
    records, seen = [], set()
    for c in candidates:
        if c.get('source') == SOURCE:
            continue
        table = _table_dois(c)
        filed = sorted(table & {doi}) if doi else sorted(table)
        if not filed:
            continue
        identity = notice_record_identity(c)
        links = notice_links(c)
        if len(links) > slots:
            return None  # the record links a notice the classification did not see
        for d in filed:
            kind = named.get((d, identity))
            if kind is None:
                if not notice_dois and not _passive_locator(c, candidate.get('checked_fields') or {}):
                    return None  # a record no classification row names
            elif kind not in NOTICE_SLOTS and links:
                return None  # a record classified as no notice links one
            elif kind == 'unrelated' and d == doi:
                return None  # the cited work's own record is not another work's
            elif kind in ('no_notice', 'coordinate_conflict') and d != doi:
                return None
            seen.add((d, identity))
            record = {'doi': d, 'identity': identity}
            if record not in records:
                records.append(record)
    declared = {'source': SOURCE, 'doi': doi, 'notice_dois': notice_dois,
                'records': sorted(records, key=lambda r: (r['identity'], r['doi']))}
    if named:
        # Only the named records the approval stands beside; a name with no such record
        # accounts for nothing (and cannot stand in for a notice DOI).
        used = [{'doi': d, 'identity': i} for d, i in sorted(named) if (d, i) in seen]
        if used:
            declared['notice_records'] = used
        elif not notice_dois:
            return None
    return declared


def accounts_for_notices(entry, result):
    """Cache.retain_notices hook: keep a research approval beside known DOI-linked records
    only when the approval re-validates offline with every such record attached (so the
    classification settles each notice and no saved record signals a retraction), it was
    made for this entry's current fields, and its declaration is the one its own saved
    classification and records give."""
    try:
        own = [c for c in result.get('candidates', []) if c.get('source') == SOURCE]
        if len(own) != 1 or own[0].get('checked_fields') != entry['fields']:
            return False
        if result.get('notices_accounted') != notices_declaration(own[0], result['candidates']):
            return False
        return valid_research_approval(result)
    except (KeyError, TypeError, AttributeError, ValueError):
        return False


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
        if not found and 'browser_or_scan' not in (record.get('flag'), record.get('read')):
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
    the other route approvals). Then, where this clone can: the saved candidate must
    re-assess to the same approval. A quote whose body validate.py's cache
    (.bibcheck/research-pilot/) holds is searched again in it and the body's sha256 must
    be the recorded one (a changed body fails); a quote whose body the cache does not
    hold (no cache at all in a fresh clone or CI, or a partial one) uses its recorded
    quote result (CachedOrSavedBodies). Where validate.py and the post-check's
    normalisers cannot be imported (the minimal verification requirements lack pandas)
    the self-consistency check stands alone, the same trust the snapshot import gives a
    saved Crossref candidate."""
    if result.get('accepted_source') != SOURCE or result.get('external_evidence'):
        return False
    try:
        from preprint_review import context_issues
        saved = [c for c in result['candidates'] if c.get('source') == SOURCE]
        if len(saved) != 1:
            return False
        c = saved[0]
        if (context_issues(c['checked_fields'], result['candidates'], result.get('accepted_doi'))
                and notice_blocks(c, result['candidates'])):
            return False
        if not _saved_consistent(result, c):
            return False
        try:
            validator(), postcheck()
        except ImportError:
            return True
        checked = recheck(c, CachedOrSavedBodies(c) if BODY_DIR.is_dir() else SavedBodies(c))
        return (checked['status'] == 'metadata_verified'
                and checked['accepted_record_id'] == result['accepted_record_id']
                and checked.get('accepted_doi') == result.get('accepted_doi')
                and checked['candidates'][0] == c)
    except (ValueError, KeyError, TypeError, AttributeError, ImportError, OSError):
        return False


def research_rejection_reason(result):
    """The first check of valid_research_approval that ``result`` fails, in words (None
    when it passes); for import_snapshot's error message only."""
    if result.get('accepted_source') != SOURCE:
        return None
    if result.get('external_evidence'):
        return 'a research approval carries external_evidence'
    saved = [c for c in result.get('candidates', []) if c.get('source') == SOURCE]
    if len(saved) != 1:
        return f'{len(saved)} research candidates (exactly one expected)'
    c = saved[0]
    from preprint_review import context_issues
    if (context_issues(c['checked_fields'], result['candidates'], result.get('accepted_doi'))
            and notice_blocks(c, result['candidates'])):
        return 'DOI-linked evidence (a notice) contradicts the saved research record'
    if not _saved_consistent(result, c):
        return 'the saved research record is incomplete or inconsistent (fields, identity or accepted id)'
    try:
        validator(), postcheck()
    except ImportError:
        return None
    if BODY_DIR.is_dir():
        local = Bodies()
        for item in _saved_items(c):
            text, sha = local.get(item['url'])
            if text is not None and sha != item.get('body_sha256'):
                return (f"the body cache {BODY_DIR} holds a different body for {item['url']} "
                        f"(sha256 {sha[:12]}, the approval recorded {(item.get('body_sha256') or 'none')[:12]}): "
                        "a refetched or edited page; move that file away (or the cache) to restore from "
                        "the recorded evidence")
    checked = recheck(c, CachedOrSavedBodies(c) if BODY_DIR.is_dir() else SavedBodies(c))
    if checked['status'] != 'metadata_verified':
        return f"re-assessing the saved evidence gives {checked['status']}: {'; '.join(checked.get('issues') or [])[:300]}"
    if (checked['accepted_record_id'] == result['accepted_record_id']
            and checked.get('accepted_doi') == result.get('accepted_doi') and checked['candidates'][0] == c):
        return None
    return 'the re-assessed research candidate differs from the saved one'


def reason_class(issue):
    """A short class for grouping the reasons an entry is not approved."""
    if issue == RETAINED:
        return 'route approves; Cache.retain_notices reopens it (DOI-linked notice)'
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
        return 'identity quote not in its saved body' if 'not found in its saved body' in why else 'identity quote not found'
    if field == 'notice':
        return 'notice: ' + re.sub(r"\s*(?:\(.*|'.*)$", '', why)
    for text, name in (('no research evidence', 'field never researched'),
                       ('differs from the latest', 'value differs from the latest evidence'),
                       ('no quoted evidence', 'value has no verbatim quote (reviewer/user prose only)'),
                       ('quote not found', 'quote not found in the saved body'),
                       ('no saved body', 'no saved body for the quoted URL'),
                       ('value words', 'value words not in the quotes'),
                       ('removed this field', 'field the research removed is still present'),
                       ('latest evidence names', 'entry type differs from the evidence'),
                       ('next_start', 'inferred end page not supported'),
                       ('no URL or quote', 'an evidence item has no URL or quote')):
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
                if result['status'] == 'metadata_verified' and predicted['status'] != 'metadata_verified':
                    row['route_granted'] = True
                own = [c for c in previous.get('candidates', []) if c.get('source') == SOURCE]
                if own == [candidate] and previous.get('status') == predicted['status']:
                    row.update(outcome='unchanged', status=previous['status'])
                    if row.get('route_granted'):
                        row['reasons'] = [RETAINED] + predicted.get('issues', [])
                    rows[key] = row
                    continue
                if not dry_run:
                    predicted = cache.put(filename, entry, result)
                    writes += 1
                row.update(status=predicted['status'],
                           outcome='approved' if predicted['status'] == 'metadata_verified' else 'held_by_notice',
                           reasons=[] if predicted['status'] == 'metadata_verified' else predicted.get('issues', []))
                if row.get('route_granted'):
                    row['reasons'] = [RETAINED] + row['reasons']
                rows[key] = row
        finally:
            if report and not dry_run:
                write_report(filename, cache, report)
    counts = {'outcomes': {}, 'first_reason': {}, 'all_reasons': {}, 'flags': {}, 'writes': writes}
    for row in rows.values():
        counts['outcomes'][row['outcome']] = counts['outcomes'].get(row['outcome'], 0) + 1
        if row['outcome'] in ('not_approved', 'not_researched', 'skipped', 'withdrawn') or row.get('route_granted'):
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
    dirs = [PILOT, WAVES, RESOLUTIONS, str(Path(MANUAL).parent), NOTICES, RENAMES, DELETIONS, MOPUP]
    out = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all', '--'] + dirs, cwd=root, env=env,
                         check=True, capture_output=True, text=True).stdout
    changed = {line[3:].strip().strip('"') for line in out.splitlines() if line.strip()}
    return sorted(set(evidence_files(root)) & changed)


from verification import register_approval_validator, register_notice_accounting  # noqa: E402
register_approval_validator(valid_research_approval)      # hook contract 2026-09-25
from verification import register_approval_rejection_reason  # noqa: E402
register_approval_rejection_reason(SOURCE, research_rejection_reason)
register_notice_accounting(SOURCE, accounts_for_notices)  # hook contract 2026-09-27
