"""Research route (bibcheck/research_route.py): approvals from the research waves' evidence.

Everything is real and frozen (tests/fixtures/research_route/build.py, 2026-09-27): the
entries as cdl.bib printed them, the research rows, post-check rows, reviewer rows, user
decisions and resolution rows that mention them (the repository's layout, trimmed to
these works), and validate.py's saved fetched bodies. No test reads the live cdl.bib, the
live research folders or .bibcheck/.
"""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bibcheck'))
import research_route as R  # noqa: E402
import verification as v  # noqa: E402

FIX = ROOT / 'tests/fixtures/research_route'
EVIDENCE = FIX / 'root'
BODIES = FIX / 'bodies'
APPROVED = ['Tulv74', 'vanPEtal21', 'AschEben62', 'YingEtal93', 'Post62', 'HartWong79', 'Zar10', 'Gomu53',
            'DamaEtal96', 'Pyly73', 'KahaEtal08b']


@pytest.fixture(scope='module')
def entries():
    return v.load_entries(FIX / 'entries.bib')


@pytest.fixture(scope='module')
def bundles(entries):
    return R.load_evidence(EVIDENCE, set(entries))


@pytest.fixture(scope='module')
def cities(entries):
    return R.postcheck().city_states({k: e['fields'] for k, e in entries.items()})


@pytest.fixture(autouse=True)
def frozen_bodies(monkeypatch):
    # The offline validator reads validate.py's body cache; point it at the frozen bodies.
    monkeypatch.setattr(R, 'BODY_DIR', BODIES)


def assess(entries, bundles, cities, key, fields=None, bodies=None):
    return R.assess_research(fields or entries[key]['fields'], bundles[key], bodies or R.Bodies(BODIES), cities)


def roundtrip(result):
    return json.loads(v.dumps(result))


def test_validator_registered_and_cli_imports_route():
    assert R.valid_research_approval in v.APPROVAL_VALIDATORS
    import verification_cli
    assert verification_cli.research_route is R
    assert 'research-approve' in [c.name for c in verification_cli.app.registered_commands]


@pytest.mark.parametrize('key', APPROVED)
def test_real_entries_approve_with_every_field_quoted(entries, bundles, cities, key):
    result = assess(entries, bundles, cities, key)
    assert result['status'] == 'metadata_verified', result['issues']
    c = result['candidates'][0]
    fields = entries[key]['fields']
    assert set(c['fields']) == set(fields) - {'ID', 'ENTRYTYPE'}
    for name, record in c['fields'].items():
        assert record['value'] == fields[name]
        for item in record['evidence']:
            if item['found']:
                body = (BODIES / (hashlib.sha256(item['url'].encode()).hexdigest() + '.txt')).read_text()
                assert item['body_sha256'] == hashlib.sha256(body.encode()).hexdigest()
    assert result['accepted_source'] == R.SOURCE and result['accepted_record_id'].startswith('research:')
    if fields.get('doi'):
        assert result['accepted_doi'] == v.normalize_doi(fields['doi'])


def test_title_and_journal_quotes_tulv74(entries, bundles, cities):
    c = assess(entries, bundles, cities, 'Tulv74')['candidates'][0]
    assert c['identity']['found'] and c['identity']['origin'].startswith('wave')
    assert all(r['origin'].startswith(('wave', 'pilot')) for r in c['fields'].values())


def test_renamed_key_follows_the_rename_log(entries, bundles):
    # YingEtal92 -> YingEtal93 (wave 9, resolution batch-26); ChanEtal12b -> ChanEtal12.
    assert {r['key'] for r in bundles['YingEtal93']['rows']} == {'YingEtal92'}
    assert {r['key'] for r in bundles['ChanEtal12']['rows']} == {'ChanEtal12b'}
    assert 'YingEtal92' not in bundles


def test_deleted_key_is_never_followed(entries, bundles):
    # KahaEtal08b was deleted (duplicate of KahaEtal08a); its key now names the former
    # KahaEtal08c. The rows about the deleted work (wave 8 and resolution batch-19 'drop')
    # must not apply to the entry that carries the key today.
    rows = json.loads((EVIDENCE / 'verification/research-2026-09-25/wave8/batch-081.json').read_text())
    assert 'KahaEtal08b' in {r['key'] for r in rows}
    b = bundles['KahaEtal08b']
    assert {r['key'] for r in b['rows']} == {'KahaEtal08c'}
    assert {r['key'] for r in b['resolutions']} == {'KahaEtal08c'}
    assert R.rename_walk([], {'KahaEtal08b'})('KahaEtal08b') is None


def test_identity_from_a_resolution_title_when_no_wave_queued_it(entries, bundles, cities):
    # Zar10 was researched only in resolution batch 27 (the spot-check entries never queued).
    assert not bundles['Zar10']['rows'] and {r['decision'] for r in bundles['Zar10']['resolutions']} == {'apply'}
    c = assess(entries, bundles, cities, 'Zar10')['candidates'][0]
    assert c['identity'] == {'origin': 'resolution/batch-27', 'from_field': 'title'}


def test_browser_read_quote_is_flagged(entries, bundles, cities):
    c = assess(entries, bundles, cities, 'HartWong79')['candidates'][0]
    assert c['flags'] == ['pages: browser_or_scan']
    pages = c['fields']['pages']
    assert pages['origin'].startswith('resolution/') and not any(e['found'] for e in pages['evidence'])
    assert R.says_browser_or_scan(next(r['notes'] for r in bundles['HartWong79']['resolutions']))


def test_browser_rule_needs_the_notes_to_say_so(entries, bundles, cities):
    b = deepcopy(bundles['HartWong79'])
    for c in b['claims']:
        c['lenient'] = False
    result = R.assess_research(entries['HartWong79']['fields'], b, R.Bodies(BODIES), cities)
    assert result['status'] == 'needs_review'
    assert any(i.startswith('pages: ') for i in result['issues'])


def test_catalogue_extent_rule(entries, bundles, cities):
    c = assess(entries, bundles, cities, 'Gomu53')['candidates'][0]
    assert c['fields']['pages']['rule'] == "monograph pages 1--N from the catalogue extent 'N p.'"


def test_value_changed_after_research_is_not_approved(entries, bundles, cities):
    fields = dict(entries['Tulv74']['fields'], year=str(int(entries['Tulv74']['fields']['year']) + 1))
    result = assess(entries, bundles, cities, 'Tulv74', fields=fields)
    assert result['status'] == 'needs_review'
    assert [i for i in result['issues'] if not i.startswith('year: the entry value differs')] == []
    assert len(result['issues']) == 1
    assert 'accepted_source' not in result


def test_unresearched_field_is_not_approved(entries, bundles, cities):
    fields = dict(entries['Tulv74']['fields'], note='Reprinted 1980')
    result = assess(entries, bundles, cities, 'Tulv74', fields=fields)
    assert result['status'] == 'needs_review'
    assert 'note: no research evidence for this field' in result['issues']


def test_quote_missing_from_body_is_not_approved(entries, bundles, cities, tmp_path):
    c = assess(entries, bundles, cities, 'Tulv74')['candidates'][0]
    item = next(e for e in c['fields']['title']['evidence'] if e['found'])
    shutil.copytree(BODIES, tmp_path / 'bodies')
    name = hashlib.sha256(item['url'].encode()).hexdigest() + '.txt'
    body = (tmp_path / 'bodies' / name).read_text()
    V = R.validator()
    # Remove every occurrence of the quoted words from the saved body (the page changed).
    words = [w for w in item['quote'].split() if len(w) > 3]
    edited = body
    for w in words:
        edited = edited.replace(w, '')
    assert V.hyphen_joined(V.norm(item['quote'])) not in V.hyphen_joined(V.norm(edited))
    (tmp_path / 'bodies' / name).write_text(edited)
    result = assess(entries, bundles, cities, 'Tulv74', bodies=R.Bodies(tmp_path / 'bodies'))
    assert result['status'] == 'needs_review'
    assert any(i.startswith('title: ') for i in result['issues'])


def test_no_saved_body_is_not_approved(entries, bundles, cities, tmp_path):
    (tmp_path / 'empty').mkdir()
    result = assess(entries, bundles, cities, 'Tulv74', bodies=R.Bodies(tmp_path / 'empty'))
    assert result['status'] == 'needs_review'
    assert 'identity: no identity quote found in a saved body' in result['issues']
    assert any('no saved body for the quoted URL' in i for i in result['issues'])


def test_needs_user_is_not_approved(entries, bundles, cities):
    result = assess(entries, bundles, cities, 'ChanEtal12')
    assert result['status'] == 'needs_review'
    assert result['issues'] == ['research: needs_user (wave2/merged)']


def test_needs_user_negative_control_on_an_approved_entry(entries, bundles, cities):
    b = deepcopy(bundles['Tulv74'])
    assert b['merged'] and not any(m['needs_user'] for m in b['merged'])
    b['merged'][0]['needs_user'] = True
    result = R.assess_research(entries['Tulv74']['fields'], b, R.Bodies(BODIES), cities)
    assert result['status'] == 'needs_review'
    assert result['issues'] == ['research: needs_user (%s)' % b['merged'][0]['origin']]


def test_ambiguous_verdict_without_resolution_is_not_approved(entries, bundles, cities):
    b = deepcopy(bundles['Tulv74'])
    b['rows'][0]['verdict'] = 'ambiguous'
    result = R.assess_research(entries['Tulv74']['fields'], b, R.Bodies(BODIES), cities)
    assert any(i.startswith('research: verdict ambiguous') for i in result['issues'])


def test_resolution_drop_and_removed_field_block(entries, bundles, cities):
    b = deepcopy(bundles['Post62'])
    b['resolutions'][0]['decision'] = 'drop'
    result = R.assess_research(entries['Post62']['fields'], b, R.Bodies(BODIES), cities)
    assert 'research: a resolution decision drops this entry' in result['issues']
    b = deepcopy(bundles['Post62'])
    b['claims'].append(R._claim('pages', None, [], 'resolution/batch-99', 'Post62', kind='remove'))
    result = R.assess_research(entries['Post62']['fields'], b, R.Bodies(BODIES), cities)
    assert 'pages: the research removed this field (resolution/batch-99)' in result['issues']


def test_house_form_comparison():
    assert R.canon('author', 'G {van Rossum} and {\\L} Langa') == R.canon('author', 'G {van Rossum} and Ł Langa')
    assert R.canon('author', 'Colin Raffel') == R.canon('author', 'C Raffel')
    assert R.canon('author', 'C Raffel') != R.canon('author', 'C A Raffel')
    assert R.canon('pages', '347-76') == R.canon('pages', '347--376')
    assert R.canon('title', 'A — b') == R.canon('title', 'a---b')
    assert R.canon('doi', 'https://doi.org/10.1037/H0034650') == '10.1037/h0034650'
    assert R.canon('entrytype', 'conference') == 'inproceedings'


def test_offline_revalidation_with_saved_bodies(entries, bundles, cities):
    for key in APPROVED:
        result = roundtrip(assess(entries, bundles, cities, key))
        assert v.route_approval_valid(result), key


def test_offline_revalidation_without_body_cache(entries, bundles, cities, monkeypatch, tmp_path):
    # A clone without .bibcheck/research-pilot/ (CI restore): the recorded quote results.
    result = roundtrip(assess(entries, bundles, cities, 'Tulv74'))
    monkeypatch.setattr(R, 'BODY_DIR', tmp_path / 'absent')
    assert v.route_approval_valid(result)
    tampered = deepcopy(result)
    c = [x for x in tampered['candidates'] if x['source'] == R.SOURCE][0]
    c['checked_fields']['year'] = '1975'
    assert not v.route_approval_valid(tampered)


def test_offline_revalidation_rejects_changed_body_and_tampering(entries, bundles, cities, monkeypatch, tmp_path):
    result = roundtrip(assess(entries, bundles, cities, 'Tulv74'))
    c = [x for x in result['candidates'] if x['source'] == R.SOURCE][0]
    # A body whose sha256 differs from the recorded one (refetched, edited) fails.
    shutil.copytree(BODIES, tmp_path / 'bodies')
    item = next(e for e in c['fields']['title']['evidence'] if e['found'])
    path = tmp_path / 'bodies' / (hashlib.sha256(item['url'].encode()).hexdigest() + '.txt')
    path.write_text(path.read_text() + '\n')
    monkeypatch.setattr(R, 'BODY_DIR', tmp_path / 'bodies')
    assert not v.route_approval_valid(result)
    monkeypatch.setattr(R, 'BODY_DIR', BODIES)
    for mutate in (lambda r: r.update(accepted_record_id='research:0'),
                   lambda r: r.update(accepted_source='crossref'),
                   lambda r: r.update(external_evidence={'x': 1}),
                   lambda r: r['candidates'].append(deepcopy(c)),
                   lambda r: [x for x in r['candidates'] if x['source'] == R.SOURCE][0]['raw_record']['merged'][0]
                   .update(needs_user=True)):
        bad = deepcopy(result)
        mutate(bad)
        assert not v.route_approval_valid(bad)
    assert v.route_approval_valid(result)


@pytest.mark.parametrize('key,issue', [('DamaEtal96', 'Known DOI-linked source evidence requires adjudication'),
                                       ('Pyly73', 'DOI registry notice requires adjudication')])
def test_doi_linked_notice_holds_the_approval_like_other_routes(entries, bundles, cities, key, issue):
    context = json.loads((FIX / 'context.json').read_text())[key]
    previous = v.outcome('needs_review', ['DOI-linked source correction/retraction notice requires adjudication'],
                         context)
    result = R.merge(previous, assess(entries, bundles, cities, key))
    assert result['status'] == 'needs_review' and result['issues'][0] == issue
    assert R.HELD_BY_CONTEXT in result['issues'] and 'accepted_source' not in result
    assert result['candidates'][-1]['category'] == 'verified'
    # The validator refuses the approval with the notice beside it, as for OSF/arXiv/bioRxiv.
    approval = roundtrip(dict(assess(entries, bundles, cities, key)))
    approval['candidates'] = context + approval['candidates']
    assert not v.route_approval_valid(approval)


def test_retain_notices_downgrades_a_research_approval(entries, bundles, cities, tmp_path):
    # Cache.retain_notices treats a research approval like any other machine approval: a
    # DOI-linked notice learned later reopens it; a human approval would be exempt.
    context = json.loads((FIX / 'context.json').read_text())['DamaEtal96']
    notice = [c for c in context if c['source'] == 'europepmc']
    assert notice
    cache = v.Cache(tmp_path / 'db.sqlite3')
    try:
        entry = entries['DamaEtal96']
        approval = assess(entries, bundles, cities, 'DamaEtal96')
        assert approval['status'] == 'metadata_verified'
        cache.remember_notices(notice)
        stored = cache.put(FIX / 'entries.bib', entry, approval)
        assert stored['status'] == 'needs_review'
        assert 'DOI-linked source correction/retraction notice requires adjudication' in stored['issues']
    finally:
        cache.close()


def write_bib(tmp_path, entries, keys):
    bib = tmp_path / 'lib.bib'
    bib.write_text('\n\n'.join(entries[k]['raw'] for k in keys) + '\n', encoding='utf-8')
    return bib


def seed(cache, bib):
    loaded = v.load_entries(bib)
    for key, entry in loaded.items():
        cache.put(bib, entry, v.outcome('needs_review', ['No unambiguous, fully supported metadata match']))
    return loaded


def test_backfill_writes_through_the_cache_and_repeats_with_no_writes(entries, tmp_path):
    keys = ['Tulv74', 'YingEtal93', 'ChanEtal12', 'Zar10']
    bib = write_bib(tmp_path, entries, keys)
    cache = v.Cache(tmp_path / '.bibcheck' / 'verification.sqlite3')
    try:
        loaded = seed(cache, bib)
        dry = R.run_research_approve(bib, cache, dry_run=True, root=EVIDENCE, bodies=R.Bodies(BODIES))
        assert dry['counts']['writes'] == 0
        assert {k: r['outcome'] for k, r in dry['rows'].items()} == {
            'Tulv74': 'approved', 'YingEtal93': 'approved', 'Zar10': 'approved', 'ChanEtal12': 'not_approved'}
        assert all(cache.get(bib, e)['status'] == 'needs_review' for e in loaded.values())
        before = cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
        report = tmp_path / 'report.jsonl'
        run = R.run_research_approve(bib, cache, report, root=EVIDENCE, bodies=R.Bodies(BODIES))
        assert run['counts']['writes'] == 3
        assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0] == before + 3
        results = v.current_results(bib, cache)
        assert {k: r['status'] for k, r in results.items()} == {
            'Tulv74': 'metadata_verified', 'YingEtal93': 'metadata_verified', 'Zar10': 'metadata_verified',
            'ChanEtal12': 'needs_review'}
        assert results['Tulv74']['research_route'] == {'policy': R.POLICY, 'category': 'verified'}
        assert results['ChanEtal12']['issues'] == ['No unambiguous, fully supported metadata match']
        assert len(report.read_text().splitlines()) == 4
        repeat = R.run_research_approve(bib, cache, report, root=EVIDENCE, bodies=R.Bodies(BODIES))
        assert repeat['counts']['writes'] == 0
        assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0] == before + 3
        # The approvals travel in a snapshot and restore into a fresh cache.
        snap = tmp_path / 'snap.jsonl.gz'
        v.export_snapshot(bib, cache, snap)
        with gzip.open(snap, 'rt') as stream:
            rows = [json.loads(line) for line in stream][1:]
        assert sum(r.get('accepted_source') == R.SOURCE for r in rows) == 3
    finally:
        cache.close()
    fresh = v.Cache(tmp_path / 'fresh.sqlite3')
    try:
        assert v.import_snapshot(bib, fresh, snap) == 4
        assert {k: r['status'] for k, r in v.current_results(bib, fresh).items()} == {
            k: r['status'] for k, r in results.items()}
    finally:
        fresh.close()


def test_backfill_keeps_notice_held_entry_needs_review_and_is_idempotent(entries, tmp_path):
    bib = write_bib(tmp_path, entries, ['Pyly73'])
    context = json.loads((FIX / 'context.json').read_text())['Pyly73']
    cache = v.Cache(tmp_path / 'db.sqlite3')
    try:
        entry = v.load_entries(bib)['Pyly73']
        cache.put(bib, entry, v.outcome('needs_review', ['No unambiguous, fully supported metadata match'], context))
        run = R.run_research_approve(bib, cache, root=EVIDENCE, bodies=R.Bodies(BODIES))
        assert run['rows']['Pyly73']['outcome'] == 'held_by_notice' and run['counts']['writes'] == 1
        stored = cache.get(bib, entry)
        assert stored['status'] == 'needs_review'
        assert [c for c in stored['candidates'] if c['source'] == R.SOURCE][0]['category'] == 'verified'
        repeat = R.run_research_approve(bib, cache, root=EVIDENCE, bodies=R.Bodies(BODIES))
        assert repeat['rows']['Pyly73']['outcome'] == 'unchanged' and repeat['counts']['writes'] == 0
    finally:
        cache.close()


def test_excluded_evidence_file_is_not_read(entries):
    # A file another session is still writing is left out: without resolution batch 27,
    # Zar10 has no research at all.
    b = R.load_evidence(EVIDENCE, set(entries), exclude={'verification/resolution-2026-09-26/batch-27.json'})
    assert 'Zar10' not in b and 'Tulv74' in b


def test_offline_revalidation_with_minimal_requirements(entries, bundles, cities, monkeypatch, tmp_path):
    # CI restores the baseline with requirements-research.txt only: no body cache and no
    # pandas for the post-check's normalisers. The saved record's self-consistency and
    # the DOI-linked context still decide; tampering is still refused.
    result = roundtrip(assess(entries, bundles, cities, 'YingEtal93'))

    def missing():
        raise ImportError('No module named pandas')
    monkeypatch.setattr(R, 'BODY_DIR', tmp_path / 'absent')
    monkeypatch.setattr(R, 'postcheck', missing)
    assert v.route_approval_valid(result)
    for mutate in (lambda c: c['checked_fields'].update(year='1999'),
                   lambda c: c['fields'].pop('title'),
                   lambda c: c['fields']['title'].update(value='Another title'),
                   lambda c: [e.update(found=False) for e in c['fields']['title']['evidence']],
                   lambda c: c['identity'].update(found=False),
                   lambda c: c.update(issues=['x'])):
        bad = deepcopy(result)
        mutate([x for x in bad['candidates'] if x['source'] == R.SOURCE][0])
        assert not v.route_approval_valid(bad)


def test_backfill_repeat_writes_nothing_when_retain_notices_reopens_the_approval(entries, tmp_path):
    # The notice is known to the cache (source_notices) but not among the entry's own
    # candidates: the research approval passes merge() and Cache.retain_notices reopens it.
    # A repeat must recognise the stored outcome instead of writing it again.
    bib = write_bib(tmp_path, entries, ['DamaEtal96'])
    notice = [c for c in json.loads((FIX / 'context.json').read_text())['DamaEtal96'] if c['source'] == 'europepmc']
    cache = v.Cache(tmp_path / 'db.sqlite3')
    try:
        entry = v.load_entries(bib)['DamaEtal96']
        cache.put(bib, entry, v.outcome('needs_review', ['No unambiguous, fully supported metadata match']))
        cache.remember_notices(notice)
        dry = R.run_research_approve(bib, cache, dry_run=True, root=EVIDENCE, bodies=R.Bodies(BODIES))
        assert dry['rows']['DamaEtal96']['outcome'] == 'held_by_notice' and dry['counts']['writes'] == 0
        run = R.run_research_approve(bib, cache, root=EVIDENCE, bodies=R.Bodies(BODIES))
        assert run['rows']['DamaEtal96']['outcome'] == 'held_by_notice' and run['counts']['writes'] == 1
        assert cache.get(bib, entry)['status'] == 'needs_review'
        repeat = R.run_research_approve(bib, cache, root=EVIDENCE, bodies=R.Bodies(BODIES))
        assert repeat['rows']['DamaEtal96']['outcome'] == 'unchanged' and repeat['counts']['writes'] == 0
    finally:
        cache.close()


@pytest.mark.parametrize('notes,says', [
    # Real notes (resolution batches and the manual research, 2026-09-26).
    ("the JSTOR page (read in a browser 2026-09-26; blocks plain scripts) prints pp. 100-108", True),
    ("Scholar result read in a real browser (plain fetch blocked); abstracting-index citation accepted", True),
    ("Publisher page (browser; citation_publication_date=2011/12/15, 'Pages 514-536')", True),
    ("Title page of the DTIC AD0043237 scan (image-only; quote transcribed from the page image)", True),
    ("Publisher page (neurology.org, browser-only; 403 to scripts) prints 'Pages: 1596-1603'", True),
    ("SpringerLink chapter page (read in a browser) prints 'Chapter pp 23-35' with no chapter number", True),
    ("ScholarWorks and WorldCat searches returned no match in the scripted/browser views", False),
    ("OUP chapter page is bot-blocked and no scan found.", False),
    ("confirmed only by printed reference lists (vol. I scans lending-only; Scholar CAPTCHA)", False),
    ("Cambridge Core book page (fetched with a browser UA, HTTP 200) lists the series", False),
    ("Project Euclid now serves the article page to a browser UA: DOI, title", False),
])
def test_browser_or_scan_notes(notes, says):
    assert R.says_browser_or_scan(notes) is says


def test_backfill_withdraws_an_approval_the_evidence_no_longer_supports(entries, tmp_path):
    bib = write_bib(tmp_path, entries, ['HartWong79'])
    cache = v.Cache(tmp_path / 'db.sqlite3')
    try:
        entry = v.load_entries(bib)['HartWong79']
        cache.put(bib, entry, v.outcome('needs_review', ['No unambiguous, fully supported metadata match']))
        run = R.run_research_approve(bib, cache, root=EVIDENCE, bodies=R.Bodies(BODIES))
        assert run['rows']['HartWong79']['outcome'] == 'approved'
        # The browser-read JSTOR quote is the only evidence for pages. Once the notes no
        # longer say it was read in a browser, the next run must reopen the approval.
        root = tmp_path / 'root'
        shutil.copytree(EVIDENCE, root)
        path = root / 'verification/resolution-2026-09-26/batch-07.json'
        rows = json.loads(path.read_text())
        for row in rows:
            row['notes'] = 'Pages from the JSTOR page.'
        path.write_text(json.dumps(rows))
        again = R.run_research_approve(bib, cache, root=root, bodies=R.Bodies(BODIES))
        assert again['rows']['HartWong79']['outcome'] == 'withdrawn' and again['counts']['writes'] == 1
        stored = cache.get(bib, entry)
        assert stored['status'] == 'needs_review' and stored['issues'][0].startswith('Research approval withdrawn')
        assert R.run_research_approve(bib, cache, root=root, bodies=R.Bodies(BODIES))['counts']['writes'] == 0
    finally:
        cache.close()
