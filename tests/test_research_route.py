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


# ---------------------------------------------------------------------------------------
# Rules settled after the route was built (resolution-plan README, "(default)" and "(plan)"
# lines; notice classification of 2026-09-27). Frozen by build.py v2 into v2/: real
# entries, the rows of resolution batches 28-39, notices-classified.json rows, saved
# bodies and stored DOI-linked candidates.

V2 = FIX / 'v2'
V2_APPROVED = ['Slam87', 'RescWagn72', 'Frie79', 'Bull90', 'Crai00', 'Perr14', 'Tulv72', 'GonsPall00', 'Brun04',
               'RubiEtal17', 'YoneJaco97']


@pytest.fixture(scope='module')
def entries2():
    return v.load_entries(V2 / 'entries.bib')


@pytest.fixture(scope='module')
def bundles2(entries2):
    return R.load_evidence(V2 / 'root', set(entries2))


@pytest.fixture(scope='module')
def cities2(entries2):
    return R.postcheck().city_states({k: e['fields'] for k, e in entries2.items()})


@pytest.fixture(scope='module')
def context2():
    return json.loads((V2 / 'context.json').read_text())


@pytest.fixture
def v2_bodies(monkeypatch):
    monkeypatch.setattr(R, 'BODY_DIR', V2 / 'bodies')
    return R.Bodies(V2 / 'bodies')


def assess2(entries2, bundles2, cities2, key, fields=None, bundle=None, bodies=None):
    return R.assess_research(fields or entries2[key]['fields'], bundle or bundles2[key],
                             bodies or R.Bodies(V2 / 'bodies'), cities2)


def settle(entries2, bundles2, cities2, context2, key, bundle=None, context=None):
    """The route's outcome beside the entry's stored DOI-linked candidates (merge)."""
    previous = v.outcome('needs_review', ['DOI-linked source correction/retraction notice requires adjudication'],
                         context2[key] if context is None else context)
    return R.merge(previous, assess2(entries2, bundles2, cities2, key, bundle=bundle))


@pytest.mark.parametrize('key', V2_APPROVED)
def test_v2_real_entries_approve_and_revalidate(entries2, bundles2, cities2, context2, v2_bodies, key):
    result = settle(entries2, bundles2, cities2, context2, key) if key in context2 else \
        assess2(entries2, bundles2, cities2, key)
    assert result['status'] == 'metadata_verified', result['issues']
    c = [x for x in result['candidates'] if x['source'] == R.SOURCE][0]
    assert set(c['fields']) == set(entries2[key]['fields']) - {'ID', 'ENTRYTYPE'}
    assert v.route_approval_valid(roundtrip(result)), key


# ---- rule 1: resolution batches 28-39 and the post-check's evidence forms

def test_batches_28_to_39_are_read_with_the_postcheck_evidence_forms(entries2, bundles2, cities2):
    origins = {c['origin'] for b in bundles2.values() for c in b['claims']}
    assert {'resolution/batch-29', 'resolution/batch-35', 'resolution/batch-37'} <= origins
    fields = {k: assess2(entries2, bundles2, cities2, k)['candidates'][0]['fields'] for k in ('Crai00', 'Perr14', 'Tulv72')}
    # next_start (end = next item's printed start - 1), batch 29
    assert fields['Crai00']['pages']['origin'] == 'resolution/batch-29'
    assert fields['Crai00']['pages']['rule'] == "end page = next item's printed start - 1"
    assert fields['Crai00']['pages']['next_start']['found']
    # catalogue extent 'N p.' -> 1--N, batch 35, with an extra quote
    assert fields['Perr14']['pages']['rule'] == "monograph pages 1--N from the catalogue extent 'N p.'"
    # several quotes whose union covers the value (start in one, end in another), batch 37
    pages = fields['Tulv72']['pages']
    assert pages['origin'] == 'resolution/batch-37' and len(pages['evidence']) == 2 and 'rule' not in pages
    assert all(e['found'] for e in pages['evidence'])


def test_resolution_sets_are_read_by_the_postchecks_own_evidence_items(bundles2):
    P = R.postcheck()
    rows = json.loads((V2 / 'root/verification/resolution-2026-09-26/batch-37.json').read_text())
    spec = next(r for r in rows if r['key'] == 'Tulv72')['set']['pages']
    assert R._items(spec) == P.evidence_items(spec) and len(R._items(spec)) == 2
    claim = next(c for c in bundles2['Tulv72']['claims']
                 if c['origin'] == 'resolution/batch-37' and c['field'] == 'pages')
    assert claim['items'] == P.evidence_items(spec) and claim['all_items']


def test_each_quote_of_a_union_must_be_found_and_complete(entries2, bundles2, cities2):
    # Negative controls on the real Tulv72 union: an item without its quote refuses the
    # set (as postcheck.resolution_quote refuses it); a quote missing from its body too.
    for mutate, why in ((lambda i: i.update(quote=None), 'an evidence item has no URL or quote'),
                        (lambda i: i.update(quote='SEMANTIC MEMORY/9999'), 'quote not found in the saved body')):
        b = deepcopy(bundles2['Tulv72'])
        claim = next(c for c in b['claims'] if c['origin'] == 'resolution/batch-37' and c['field'] == 'pages')
        claim['lenient'] = False  # batch 37's notes mention a scan: the browser/scan rule is tested above
        mutate(claim['items'][1])
        result = assess2(entries2, bundles2, cities2, 'Tulv72', bundle=b)
        assert result['status'] == 'needs_review' and any(i.startswith('pages: ') and why in i for i in result['issues'])


def test_next_start_must_be_the_end_page_plus_one(entries2, bundles2, cities2):
    # Crai00's next item starts where the cited range ends + 1; a range one page longer
    # (same claim, same quotes) is refused by postcheck.inferred_end_page.
    b = deepcopy(bundles2['Crai00'])
    fields = dict(entries2['Crai00']['fields'])
    start, end = fields['pages'].split('--')
    fields['pages'] = '%s--%d' % (start, int(end) + 1)
    for c in b['claims']:
        if c['field'] == 'pages' and c['kind'] == 'value':
            c['value'] = fields['pages']
    result = assess2(entries2, bundles2, cities2, 'Crai00', fields=fields, bundle=b)
    assert result['status'] == 'needs_review'
    assert any(i.startswith('pages: ') and 'next_start' in i for i in result['issues'])


def test_apply_after_keep_is_not_a_conflict_but_drop_is(entries2, bundles2, cities2):
    assert {r['decision'] for r in bundles2['Tulv72']['resolutions']} == {'apply', 'keep'}
    assert assess2(entries2, bundles2, cities2, 'Tulv72')['status'] == 'metadata_verified'
    b = deepcopy(bundles2['Tulv72'])
    b['resolutions'][0]['decision'] = 'drop'
    issues = assess2(entries2, bundles2, cities2, 'Tulv72', bundle=b)['issues']
    assert 'research: a resolution decision drops this entry' in issues
    assert any(i.startswith('research: conflicting resolution decisions') for i in issues)


def test_invalid_json_evidence_file_is_refused_unless_left_out(tmp_path, entries2):
    root = tmp_path / 'root'
    shutil.copytree(V2 / 'root', root)
    half = root / 'verification/resolution-2026-09-26/batch-34.json'
    half.write_text('[{"key": "Slam87", "decision": "apply", "set": {')  # a file still being written
    with pytest.raises(ValueError, match='batch-34.json is not valid JSON'):
        R.load_evidence(root, set(entries2))
    b = R.load_evidence(root, set(entries2), exclude={'verification/resolution-2026-09-26/batch-34.json'})
    assert 'Slam87' in b


# ---- rule 2: chapter pages whose start page an official contents list confirms

@pytest.mark.parametrize('key,origin,quote', [
    ('Slam87', 'resolution/batch-21', 'Page 105'),                        # its own pages quote (browser-read)
    ('RescWagn72', 'resolution/batch-19', 'R A RESCORLA A R WAGNER 64'),  # the contents line its notes cite
    ('Frie79', 'wave8/batch-084', None)])                                 # a wave quote; kept by batch 30
def test_start_only_chapter_pages_are_approved_with_a_flag(entries2, bundles2, cities2, key, origin, quote):
    result = assess2(entries2, bundles2, cities2, key)
    assert result['status'] == 'metadata_verified', result['issues']
    c = result['candidates'][0]
    pages = c['fields']['pages']
    assert pages['flag'] == 'pages_start_only' and 'pages: pages_start_only' in c['flags']
    assert pages['rule'] == R.START_ONLY_RULE and pages['origin'] == origin and pages['value'] == entries2[key]['fields']['pages']
    if quote:
        assert [e['quote'] for e in pages['evidence']] == [quote]
    # The full range is not in the quotes: only the start page is confirmed.
    V = R.validator()
    assert not V.value_supported('pages', pages['value'], [e['quote'] for e in pages['evidence']])[0]


def test_start_only_refuses_another_start_page(entries2, bundles2, cities2):
    for key in ('Slam87', 'RescWagn72', 'Frie79'):
        fields = dict(entries2[key]['fields'])
        start, end = fields['pages'].split('--')
        fields['pages'] = '%d--%s' % (int(start) + 1, end)
        b = deepcopy(bundles2[key])
        for c in b['claims']:
            if c['field'] == 'pages' and c['kind'] == 'value':
                c['value'] = fields['pages']
        result = assess2(entries2, bundles2, cities2, key, fields=fields, bundle=b)
        assert result['status'] == 'needs_review', key
        assert any(i.startswith('pages: ') for i in result['issues']), key


def test_start_only_needs_a_chapter_and_the_partial_default(entries2, bundles2, cities2):
    # An article's page range is never approved on its start page alone.
    fields = dict(entries2['RescWagn72']['fields'], ENTRYTYPE='article')
    result = assess2(entries2, bundles2, cities2, 'RescWagn72', fields=fields)
    assert any(i.startswith('pages: ') for i in result['issues'])
    # Without a resolution note keeping the range under the partial-confirmation default.
    b = deepcopy(bundles2['RescWagn72'])
    for r in b['resolutions']:
        r['notes'] = 'Google Books contents print the chapter.'
    result = assess2(entries2, bundles2, cities2, 'RescWagn72', bundle=b)
    assert result['status'] == 'needs_review' and 'pages: no research evidence for this field' in result['issues']


def test_start_only_refuses_a_quote_printing_another_end_page(entries2, bundles2, cities2, tmp_path):
    # Frie79's contents quote, as if the page printed the chapter as 85-140: the saved
    # body (a copy) and the quote both carry the other range, so the quote is found.
    fields = entries2['Frie79']['fields']
    start = fields['pages'].split('--')[0]
    b = deepcopy(bundles2['Frie79'])
    shutil.copytree(V2 / 'bodies', tmp_path / 'bodies')
    changed = 0
    for c in b['claims']:
        if c['field'] == 'pages' and c['kind'] == 'value':
            for item in c['items']:
                path = tmp_path / 'bodies' / (hashlib.sha256(item['url'].encode()).hexdigest() + '.txt')
                if item.get('quote') and path.exists():
                    item['quote'] = item['quote'] + ' pp. %s-140' % start
                    path.write_text(path.read_text() + '\n' + item['quote'] + '\n')
                    changed += 1
    assert changed
    result = R.assess_research(fields, b, R.Bodies(tmp_path / 'bodies'), cities2)
    assert result['status'] == 'needs_review'
    assert 'pages' not in result['candidates'][0]['fields']
    assert any(i.startswith('pages: ') for i in result['issues'])
    # Control: the same copy without the other range approves on the start page.
    assert assess2(entries2, bundles2, cities2, 'Frie79')['candidates'][0]['fields']['pages']['flag'] == 'pages_start_only'


def test_partial_default_notes():
    for notes in ("RECONCILED: an official contents list confirms the start page",
                  "Pages 64--99 not set: the start page 64 is confirmed by the Google Books contents",
                  "Reconciled (partly-confirmed chapter pages default)",
                  "Left as HEAD (default: start page confirmed keeps the cited range)"):
        assert R.PARTIAL_PAGES.search(notes), notes
    for notes in ("the start page could not be confirmed", "the start page is not confirmed",
                  "pages removed: no source prints them"):
        assert not R.PARTIAL_PAGES.search(notes), notes


# ---- rule 3: identity from a resolution title when the researcher's quote has no body

def test_identity_from_a_resolution_title_when_the_researcher_quote_has_no_body(entries2, bundles2, cities2, tmp_path):
    ident = bundles2['Bull90']['rows'][0]['identity']
    shutil.copytree(V2 / 'bodies', tmp_path / 'bodies')
    (tmp_path / 'bodies' / (hashlib.sha256(ident['url'].encode()).hexdigest() + '.txt')).unlink(missing_ok=True)
    bodies = R.Bodies(tmp_path / 'bodies')
    assert bodies.get(ident['url']) == (None, None)
    result = assess2(entries2, bundles2, cities2, 'Bull90', bodies=bodies)
    assert result['status'] == 'metadata_verified', result['issues']
    c = result['candidates'][0]
    assert c['identity'] == {'origin': 'resolution/batch-28', 'from_field': 'title'}
    assert c['fields']['title']['origin'] == 'resolution/batch-28'
    # Negative control: with no resolution/user/manual title quote the identity is open.
    b = deepcopy(bundles2['Bull90'])
    b['claims'] = [x for x in b['claims'] if not (x['field'] == 'title' and x['origin'].startswith('resolution/'))]
    result = assess2(entries2, bundles2, cities2, 'Bull90', bundle=b, bodies=bodies)
    assert result['status'] == 'needs_review'
    assert 'identity: no identity quote found in a saved body' in result['issues']


# ---- rule 4: the notice classification

@pytest.mark.parametrize('key,flag', [('GonsPall00', 'notice_content_only'), ('Brun04', 'notice_unread'),
                                      ('AfraEtal06', 'notice_content_only'), ('BarEtal06', 'notice_metadata_correction'),
                                      ('Fred04', 'notice_crossref_wins'),
                                      ('RubiEtal17', 'notice_new_version'), ('YoneJaco97', 'notice_is_the_cited_work'),
                                      ('TompDava17', 'notice_unread'), ('KeleFent10', 'notice_content_only')])
def test_classified_notices_settle_the_doi_linked_hold(entries2, bundles2, cities2, context2, v2_bodies, key, flag):
    from preprint_review import context_issues
    fields = entries2[key]['fields']
    assert context_issues(fields, context2[key], v.normalize_doi(fields['doi']))  # the hold is real
    result = settle(entries2, bundles2, cities2, context2, key)
    assert result['status'] == 'metadata_verified', result['issues']
    assert result[R.NAME]['notice'] == 'settled by the notice classification'
    c = result['candidates'][-1]
    assert 'notice: ' + flag in c['flags'] and c['notice']['issues'] == []
    assert v.route_approval_valid(roundtrip(result))


@pytest.mark.parametrize('key,kind', [('Este91', 'unrelated'), ('McDoEtal10', 'no_notice')])
def test_records_that_are_no_notice_are_ignored(entries2, bundles2, cities2, key, kind):
    # Held only by a PubMed author-suffix record (Cache.retain_notices' tables), on an
    # unrelated candidate (Este91, no DOI) or on the cited DOI (McDoEtal10, 'Hagler DJ Jr').
    result = assess2(entries2, bundles2, cities2, key)
    assert result['status'] == 'metadata_verified', result['issues']
    c = result['candidates'][0]
    assert c['notice']['classes'] == [kind] and c['notice']['issues'] == []
    assert 'notice: ' + R.NOTICE_FLAGS[kind] in c['flags']


@pytest.mark.parametrize('kind', ['retraction', 'expression_of_concern'])
def test_a_notice_classified_retraction_is_never_approved(entries2, bundles2, cities2, context2, v2_bodies, kind):
    b = deepcopy(bundles2['GonsPall00'])
    b['notices'][0]['class'] = kind
    result = settle(entries2, bundles2, cities2, context2, 'GonsPall00', bundle=b)
    assert result['status'] == 'needs_review' and 'accepted_source' not in result
    assert any(i.startswith('notice: classified %s' % kind) for i in result['issues'])
    approval = roundtrip(assess2(entries2, bundles2, cities2, 'GonsPall00', bundle=b))
    approval['candidates'] = context2['GonsPall00'] + approval['candidates']
    assert not v.route_approval_valid(approval)


def test_a_retraction_on_the_cited_doi_holds_whatever_the_classification(entries2, bundles2, cities2, context2, v2_bodies):
    # KeleFent10's stored candidates include another work's record with a Crossref
    # retraction (the Savine & Braver candidate): ignored. The same record on the cited
    # DOI holds the approval although the notice is classified content-only.
    other = [c for c in context2['KeleFent10'] if R.retraction_signals([c])]
    assert other and all(c['doi'] != entries2['KeleFent10']['fields']['doi'].lower() for c in other)
    assert settle(entries2, bundles2, cities2, context2, 'KeleFent10')['status'] == 'metadata_verified'
    moved = deepcopy(context2['KeleFent10'])
    for c in moved:
        if R.retraction_signals([c]):
            c['doi'] = entries2['KeleFent10']['fields']['doi']
    result = settle(entries2, bundles2, cities2, context2, 'KeleFent10', context=moved)
    assert result['status'] == 'needs_review'
    assert any(i.startswith('notice: Crossref record of') and 'retraction' in i for i in result['issues'])


def test_unread_notice_needs_the_absence_of_a_retraction_recorded(entries2, bundles2, cities2, context2):
    b = deepcopy(bundles2['Brun04'])
    for n in b['notices']:
        n['notes'] = 'Notice text not retrieved: ScienceDirect returns 403.'
    result = settle(entries2, bundles2, cities2, context2, 'Brun04', bundle=b)
    assert result['status'] == 'needs_review'
    assert any('unread, and no absence of a retraction' in i for i in result['issues'])


def test_metadata_correction_must_already_be_in_the_entry(entries2, bundles2, cities2, context2):
    b = deepcopy(bundles2['BarEtal06'])
    b['notices'][0]['corrected_fields']['author']['new'] = 'A M Schmidt'   # the uncorrected printing
    result = settle(entries2, bundles2, cities2, context2, 'BarEtal06', bundle=b)
    assert result['status'] == 'needs_review'
    assert any("the corrected author 'A M Schmidt' is not in the entry" in i for i in result['issues'])


def test_coordinate_conflict_needs_the_crossref_value_in_the_entry(entries2, bundles2, cities2, context2):
    # HeniEtal19: Crossref's article number is not yet in the entry (pending edit).
    result = settle(entries2, bundles2, cities2, context2, 'HeniEtal19')
    assert result['status'] == 'needs_review'
    assert any(i.startswith('notice: the corrected pages is not yet in the entry') for i in result['issues'])
    # Fred04: the entry's 1367--1377 is Crossref's; a PubMed-like 1367--1378 is refused.
    fields = dict(entries2['Fred04']['fields'], pages='1367--1378')
    adj = R.notice_adjudication(fields, bundles2['Fred04']['notices'])
    assert adj['issues'] == ['notice: the entry does not carry the Crossref pages of the conflict (%s)'
                             % bundles2['Fred04']['notices'][0]['url']]
    assert R.notice_adjudication(entries2['Fred04']['fields'], bundles2['Fred04']['notices'])['issues'] == []


def test_unclassified_notice_still_holds(entries2, bundles2, cities2, context2):
    assert not bundles2['BarrEtal18'].get('notices')
    result = settle(entries2, bundles2, cities2, context2, 'BarrEtal18')
    assert result['status'] == 'needs_review' and R.HELD_BY_CONTEXT in result['issues']
    assert any(i.startswith('notice: no classification') for i in result['issues'])


def test_notice_adjudication_is_part_of_the_evidence_id(entries2, bundles2, cities2, context2, v2_bodies, monkeypatch, tmp_path):
    result = roundtrip(settle(entries2, bundles2, cities2, context2, 'GonsPall00'))
    assert v.route_approval_valid(result)
    # Minimal requirements (no body cache, no post-check): tampering with the saved
    # adjudication still fails, through the evidence id.
    monkeypatch.setattr(R, 'BODY_DIR', tmp_path / 'absent')
    def missing():
        raise ImportError('No module named pandas')
    monkeypatch.setattr(R, 'postcheck', missing)
    assert v.route_approval_valid(result)
    bad = deepcopy(result)
    c = [x for x in bad['candidates'] if x['source'] == R.SOURCE][0]
    c['notice']['classes'] = ['content_only', 'retraction']
    assert not v.route_approval_valid(bad)
    bad = deepcopy(result)
    c = [x for x in bad['candidates'] if x['source'] == R.SOURCE][0]
    c['notice']['issues'] = ['notice: classified retraction (x): never approved; the user decides']
    assert not v.route_approval_valid(bad)


def later_erratum(record):
    """The AfraEtal06 Europe PMC record as it would read once PubMed links one more
    erratum: a DOI-linked notice learned after the classification (a new record identity)."""
    later = deepcopy(record)
    later['raw_record']['commentCorrectionList']['commentCorrection'].append(
        {'id': '99999999', 'orderIn': 3, 'reference': 'Nature. 2027 Jan 1;600(1):1', 'source': 'MED',
         'type': 'Erratum in'})
    return later


def afra_bib(entries2, tmp_path):
    bib = tmp_path / 'lib.bib'
    bib.write_text(entries2['AfraEtal06']['raw'] + '\n', encoding='utf-8')
    return bib


def test_backfill_approves_what_the_notice_classification_settles(entries2, v2_bodies, tmp_path):
    # AfraEtal06: the route settles its Europe PMC erratum (content-only) and declares so
    # (notices_accounted); Cache.retain_notices keeps the approval. A repeat writes nothing.
    context = json.loads((V2 / 'context.json').read_text())['AfraEtal06']
    bib = afra_bib(entries2, tmp_path)
    cache = v.Cache(tmp_path / 'db.sqlite3')
    try:
        entry = v.load_entries(bib)['AfraEtal06']
        cache.put(bib, entry, v.outcome('needs_review', ['No unambiguous, fully supported metadata match'], context))
        dry = R.run_research_approve(bib, cache, dry_run=True, root=V2 / 'root', bodies=R.Bodies(V2 / 'bodies'))
        row = dry['rows']['AfraEtal06']
        assert row['outcome'] == 'approved' and not row.get('route_granted') and dry['counts']['writes'] == 0
        assert 'notice: notice_content_only' in row['flags']
        assert cache.get(bib, entry)['status'] == 'needs_review'
        run = R.run_research_approve(bib, cache, root=V2 / 'root', bodies=R.Bodies(V2 / 'bodies'))
        assert run['rows']['AfraEtal06']['outcome'] == 'approved' and run['counts']['writes'] == 1
        stored = cache.get(bib, entry)
        assert stored['status'] == 'metadata_verified' and stored['accepted_source'] == R.SOURCE
        assert stored['notices_accounted']['notice_dois'] == ['10.1038/nature05153']
        repeat = R.run_research_approve(bib, cache, root=V2 / 'root', bodies=R.Bodies(V2 / 'bodies'))
        assert repeat['counts']['writes'] == 0 and 'AfraEtal06' not in repeat['rows']
    finally:
        cache.close()


def test_backfill_reports_the_approval_retain_notices_reopens(entries2, v2_bodies, tmp_path):
    # Negative control: the cache also knows a notice record the classification never saw
    # (a later erratum link). The route approves, retain_notices reopens, the dry run says so.
    context = json.loads((V2 / 'context.json').read_text())['AfraEtal06']
    bib = afra_bib(entries2, tmp_path)
    cache = v.Cache(tmp_path / 'db.sqlite3')
    try:
        entry = v.load_entries(bib)['AfraEtal06']
        cache.put(bib, entry, v.outcome('needs_review', ['No unambiguous, fully supported metadata match'], context))
        cache.remember_notices([later_erratum([c for c in context if c['source'] == 'europepmc'][0])])
        dry = R.run_research_approve(bib, cache, dry_run=True, root=V2 / 'root', bodies=R.Bodies(V2 / 'bodies'))
        row = dry['rows']['AfraEtal06']
        assert row['outcome'] == 'held_by_notice' and row['route_granted'] and row['reasons'][0] == R.RETAINED
        assert 'notice: notice_content_only' in row['flags'] and dry['counts']['writes'] == 0
        assert dry['counts']['first_reason'] == {R.reason_class(R.RETAINED): 1}
    finally:
        cache.close()


def put_later(db, entry, result, extra=()):
    """Cache.put of ``result`` into a fresh cache that already knows the records ``extra``."""
    cache = v.Cache(db)
    try:
        cache.remember_notices(list(extra))
        return cache.put(V2 / 'entries.bib', entry, deepcopy(result))
    finally:
        cache.close()


def test_retain_notices_keeps_a_settled_research_approval(entries2, bundles2, cities2, context2, v2_bodies, tmp_path):
    cache = v.Cache(tmp_path / 'db.sqlite3')
    try:
        result = settle(entries2, bundles2, cities2, context2, 'AfraEtal06')
        assert result['status'] == 'metadata_verified'
        declared = result['notices_accounted']
        assert declared['source'] == R.SOURCE and declared['doi'] == '10.1038/nature04982'
        assert declared['notice_dois'] == ['10.1038/nature05153'] and declared['records']
        stored = cache.put(V2 / 'entries.bib', entries2['AfraEtal06'], result)
        assert stored['status'] == 'metadata_verified'
        assert cache.get(V2 / 'entries.bib', entries2['AfraEtal06'])['status'] == 'metadata_verified'
        assert v.route_approval_valid(roundtrip(stored))   # and the stored row re-validates offline
        # A caller that never imported the route (Cache.get from any script) keeps it too:
        # the hook module is imported on demand. Only this route has a hook.
        assert v.NOTICE_ACCOUNTING_MODULES == {R.SOURCE: 'research_route'}
        assert set(v.NOTICE_ACCOUNTING) == {R.SOURCE}
    finally:
        cache.close()


def test_retain_notices_reopens_on_a_notice_learned_later(entries2, bundles2, cities2, context2, v2_bodies, tmp_path):
    entry = entries2['AfraEtal06']
    result = settle(entries2, bundles2, cities2, context2, 'AfraEtal06')
    later = later_erratum([c for c in context2['AfraEtal06'] if c['source'] == 'europepmc'][0])
    stored = put_later(tmp_path / 'a.sqlite3', entry, result, [later])
    assert stored['status'] == 'needs_review' and 'accepted_source' not in stored
    assert 'DOI-linked source correction/retraction notice requires adjudication' in stored['issues']
    # Also after the approval was stored: the next read reopens it.
    cache = v.Cache(tmp_path / 'b.sqlite3')
    try:
        assert cache.put(V2 / 'entries.bib', entry, deepcopy(result))['status'] == 'metadata_verified'
        cache.remember_notices([later])
        assert cache.get(V2 / 'entries.bib', entry)['status'] == 'needs_review'
    finally:
        cache.close()


def test_retain_notices_reopens_without_a_valid_declaration(entries2, bundles2, cities2, context2, v2_bodies, tmp_path):
    entry = entries2['AfraEtal06']
    result = settle(entries2, bundles2, cities2, context2, 'AfraEtal06')
    assert put_later(tmp_path / 'ok.sqlite3', entry, result)['status'] == 'metadata_verified'
    later = later_erratum([c for c in context2['AfraEtal06'] if c['source'] == 'europepmc'][0])
    undeclared = deepcopy(result)
    del undeclared['notices_accounted']
    no_notice_dois = deepcopy(result)
    no_notice_dois['notices_accounted']['notice_dois'] = []
    # Declaring the later record by hand is refused: the declaration must be the one the
    # saved classification and records give ... (the declaration below is not)
    self_declared = deepcopy(result)
    self_declared['candidates'].insert(0, later)
    self_declared['notices_accounted']['records'].append(
        {'doi': '10.1038/nature04982', 'identity': v.notice_record_identity(later)})
    # ... and an approval made for other field values is not this entry's.
    edited = dict(entry, fields=dict(entry['fields'], pages='692--696'))
    for n, (e, bad) in enumerate(((entry, undeclared), (entry, no_notice_dois), (edited, result))):
        assert put_later(tmp_path / ('%d.sqlite3' % n), e, bad)['status'] == 'needs_review', n
    # self_declared lists every record the cache knows, so it is the route's hook that
    # refuses it: the later record links a second erratum, one notice was classified.
    own = [c for c in self_declared['candidates'] if c['source'] == R.SOURCE][0]
    assert len(R.notice_links(later)) == 2 and R.notices_declaration(own, self_declared['candidates']) is None
    assert not R.accounts_for_notices(entry, self_declared)
    assert put_later(tmp_path / 'self.sqlite3', entry, self_declared, [later])['status'] == 'needs_review'


def test_retain_notices_reopens_on_a_retraction_even_if_declared(entries2, bundles2, cities2, context2, v2_bodies,
                                                               tmp_path):
    entry = entries2['AfraEtal06']
    record = deepcopy([c for c in context2['AfraEtal06'] if c['source'] == 'europepmc'][0])
    record['raw_record']['commentCorrectionList']['commentCorrection'].append(
        {'id': '99999998', 'orderIn': 3, 'reference': 'Nature. 2027 Jan 1;600(1):2', 'source': 'MED',
         'type': 'Retraction in'})
    assert R.retraction_signals([record])
    held = settle(entries2, bundles2, cities2, context2, 'AfraEtal06', context=context2['AfraEtal06'] + [record])
    assert held['status'] == 'needs_review'   # merge refuses it
    # The route declares nothing beside it, and a declaration that lists the retraction
    # record anyway does not keep the approval.
    forged = settle(entries2, bundles2, cities2, context2, 'AfraEtal06')
    forged['candidates'].insert(0, record)
    assert R.notices_declaration([c for c in forged['candidates'] if c['source'] == R.SOURCE][0],
                                 forged['candidates']) is None
    forged['notices_accounted']['records'].append({'doi': '10.1038/nature04982',
                                                   'identity': v.notice_record_identity(record)})
    assert not R.accounts_for_notices(entry, forged)
    assert not R.valid_research_approval(roundtrip(forged))   # retraction_signals, whatever is declared
    stored = put_later(tmp_path / 'db.sqlite3', entry, forged)
    assert stored['status'] == 'needs_review' and 'accepted_source' not in stored


def test_retain_notices_unchanged_for_other_routes(entries2, bundles2, cities2, context2, v2_bodies, tmp_path):
    # Another route's approval carrying the same declaration is reopened as before: no hook
    # is registered for its accepted_source.
    entry = entries2['AfraEtal06']
    result = settle(entries2, bundles2, cities2, context2, 'AfraEtal06')
    for source in ('crossref', 'osf-preprint', 'loc-catalogue'):
        other = deepcopy(result)
        other['accepted_source'] = source
        other['notices_accounted']['source'] = source
        assert put_later(tmp_path / (source + '.sqlite3'), entry, other)['status'] == 'needs_review', source
    with pytest.raises(TypeError):
        v.register_notice_accounting('x', None)


# ---- notice accounting by record identity (no notice DOI)

def own_records(context, doi, source=None):
    """The entry's stored DOI-linked records filed under ``doi`` (the cache's tables)."""
    return [c for c in context if doi in R._table_dois(c) and (source is None or c['source'] == source)]


def named(bundle, records, row=0):
    """``bundle`` with its classification row ``row`` naming ``records`` by the identity
    the cache stores (notices-classified.json ``records``)."""
    b = deepcopy(bundle)
    b['notices'][row]['records'] = [{'doi': d, 'identity': v.notice_record_identity(c)}
                                     for c in records for d in sorted(R._table_dois(c))]
    return b


def test_existing_declarations_are_unchanged_by_record_identity(entries2, bundles2, cities2, context2, v2_bodies):
    # A classification by notice DOI declares exactly what it declared before: stored
    # approvals re-derive the same declaration, so none is reopened by the extension.
    declared = settle(entries2, bundles2, cities2, context2, 'AfraEtal06')['notices_accounted']
    assert set(declared) == {'source', 'doi', 'notice_dois', 'records'}


@pytest.mark.parametrize('key,kind', [('McDoEtal10', 'no_notice'), ('Fred04', 'coordinate_conflict')])
def test_a_record_named_by_identity_keeps_the_approval(entries2, bundles2, cities2, context2, v2_bodies, tmp_path,
                                                        key, kind):
    # McDoEtal10: a PubMed author-suffix record ('Hagler DJ Jr'); Fred04: a PMC
    # article-locator record (1367-1378, Crossref 1367-1377). Neither has a notice DOI.
    entry, doi = entries2[key], v.normalize_doi(entries2[key]['fields']['doi'])
    records = own_records(context2[key], doi)
    assert records and all(not R.notice_links(c) for c in records)
    assert bundles2[key]['notices'][0]['class'] == kind and not bundles2[key]['notices'][0].get('notice_doi')
    # Before: the classification identifies nothing, so nothing is declared and the
    # cache reopens the approval.
    plain = settle(entries2, bundles2, cities2, context2, key)
    assert plain['status'] == 'metadata_verified' and 'notices_accounted' not in plain
    assert put_later(tmp_path / 'plain.sqlite3', entry, plain)['status'] == 'needs_review'
    # Named by the stored record identity: declared, kept, and valid offline.
    b = named(bundles2[key], records)
    result = settle(entries2, bundles2, cities2, context2, key, bundle=b)
    declared = result['notices_accounted']
    assert declared['notice_dois'] == [] and declared['doi'] == doi
    identities = sorted({v.notice_record_identity(c) for c in records})
    assert [r['identity'] for r in declared['notice_records']] == identities
    assert {r['identity'] for r in declared['records']} == set(identities)
    stored = put_later(tmp_path / 'named.sqlite3', entry, result)
    assert stored['status'] == 'metadata_verified' and stored['accepted_source'] == R.SOURCE
    assert v.route_approval_valid(roundtrip(stored))


def other_suffix_record(record):
    """The same PubMed record as it would read with one more suffixed author: another
    record (a new identity) of the cited DOI that no classification row names."""
    later = deepcopy(record)
    later['raw_record']['authorList']['author'].append({'fullName': 'Smith J Jr', 'lastName': 'Smith',
                                                       'initials': 'J', 'firstName': 'John'})
    return later


def test_a_different_record_with_no_classification_still_reopens(entries2, bundles2, cities2, context2, v2_bodies,
                                                                 tmp_path):
    entry, doi = entries2['McDoEtal10'], '10.1016/j.neuroimage.2010.06.069'
    records = own_records(context2['McDoEtal10'], doi)
    result = settle(entries2, bundles2, cities2, context2, 'McDoEtal10', bundle=named(bundles2['McDoEtal10'], records))
    assert result['status'] == 'metadata_verified'
    other = other_suffix_record(records[0])
    assert doi in R._table_dois(other) and v.notice_record_identity(other) != v.notice_record_identity(records[0])
    # Learned before the put, or after it: either way the approval is reopened.
    stored = put_later(tmp_path / 'a.sqlite3', entry, result, [other])
    assert stored['status'] == 'needs_review' and 'accepted_source' not in stored
    cache = v.Cache(tmp_path / 'b.sqlite3')
    try:
        assert cache.put(V2 / 'entries.bib', entry, deepcopy(result))['status'] == 'metadata_verified'
        cache.remember_notices([other])
        assert cache.get(V2 / 'entries.bib', entry)['status'] == 'needs_review'
    finally:
        cache.close()
    # The route itself declares nothing beside an unnamed record, and a hand-made
    # declaration that lists it is refused by the hook.
    forged = deepcopy(result)
    forged['candidates'].insert(0, other)
    own = [c for c in forged['candidates'] if c['source'] == R.SOURCE][0]
    assert R.notices_declaration(own, forged['candidates']) is None
    forged['notices_accounted']['records'].append({'doi': doi, 'identity': v.notice_record_identity(other)})
    assert not R.accounts_for_notices(entry, forged)
    assert put_later(tmp_path / 'c.sqlite3', entry, forged, [other])['status'] == 'needs_review'


def test_a_notice_without_doi_is_named_by_its_records(entries2, bundles2, cities2, context2, v2_bodies, tmp_path):
    # AfraEtal06's erratum as if it had no registered DOI (HubeEtal01's case): the row
    # names the Europe PMC record whose 'Erratum in' link it read. A later erratum link
    # changes the record identity, so the approval reopens (as with a notice DOI).
    entry, doi = entries2['AfraEtal06'], '10.1038/nature04982'
    records = own_records(context2['AfraEtal06'], doi)
    b = named(bundles2['AfraEtal06'], records)
    b['notices'][0]['notice_doi'] = None
    result = settle(entries2, bundles2, cities2, context2, 'AfraEtal06', bundle=b)
    assert result['status'] == 'metadata_verified'
    assert result['notices_accounted']['notice_dois'] == [] and result['notices_accounted']['notice_records']
    assert put_later(tmp_path / 'ok.sqlite3', entry, result)['status'] == 'metadata_verified'
    later = later_erratum(records[0])
    assert put_later(tmp_path / 'later.sqlite3', entry, result, [later])['status'] == 'needs_review'
    # Without the names, a row with no notice DOI identifies nothing.
    b2 = deepcopy(bundles2['AfraEtal06'])
    b2['notices'][0]['notice_doi'] = None
    plain = settle(entries2, bundles2, cities2, context2, 'AfraEtal06', bundle=b2)
    assert 'notices_accounted' not in plain
    assert put_later(tmp_path / 'plain.sqlite3', entry, plain)['status'] == 'needs_review'


def test_record_names_must_fit_the_class(entries2, bundles2, cities2, context2, v2_bodies):
    doi = '10.1038/nature04982'
    records = own_records(context2['AfraEtal06'], doi)
    own = lambda b: [c for c in settle(entries2, bundles2, cities2, context2, 'AfraEtal06', bundle=b)['candidates']
                     if c['source'] == R.SOURCE][0]
    for kind in ('no_notice', 'coordinate_conflict', 'unrelated'):
        # A record that links an erratum is not 'no notice'; the cited work's own record
        # is not another work's ('unrelated').
        b = named(bundles2['AfraEtal06'], records)
        b['notices'][0].update(notice_doi=None, **{'class': kind})
        if kind == 'coordinate_conflict':
            b['notices'][0]['quote'] = 'Crossref page "692-695"'
        c = own(b)
        assert R.notices_declaration(c, context2['AfraEtal06'] + [c]) is None, kind
    # Malformed names (a URL, a short digest, no DOI) identify nothing.
    for bad in ({'doi': doi, 'identity': 'https://europepmc.org/abstract/MED/16929304'},
                {'doi': doi, 'identity': v.notice_record_identity(records[0])[:16]},
                {'doi': None, 'identity': v.notice_record_identity(records[0])}):
        b = deepcopy(bundles2['AfraEtal06'])
        b['notices'][0].update(notice_doi=None, records=[bad])
        c = own(b)
        assert R.notices_declaration(c, context2['AfraEtal06'] + [c]) is None, bad
    # A name for a record the approval does not stand beside accounts for nothing.
    b = deepcopy(bundles2['AfraEtal06'])
    b['notices'][0].update(notice_doi=None, records=[{'doi': doi, 'identity': '0' * 64}])
    c = own(b)
    assert R.notices_declaration(c, context2['AfraEtal06'] + [c]) is None


def test_record_identity_does_not_admit_a_retraction(entries2, bundles2, cities2, context2, v2_bodies, tmp_path):
    entry, doi = entries2['AfraEtal06'], '10.1038/nature04982'
    record = deepcopy(own_records(context2['AfraEtal06'], doi)[0])
    record['raw_record']['commentCorrectionList']['commentCorrection'].append(
        {'id': '99999998', 'orderIn': 3, 'reference': 'Nature. 2027 Jan 1;600(1):2', 'source': 'MED',
         'type': 'Retraction in'})
    # Even with the retraction record named by identity (and the link counted), merge
    # refuses the approval and the offline validator rejects a forged one.
    b = named(bundles2['AfraEtal06'], [record])
    b['notices'][0]['notice_doi'] = None
    b['notices'].append(dict(b['notices'][0], quote='x'))
    held = settle(entries2, bundles2, cities2, context2, 'AfraEtal06', bundle=b, context=[record])
    assert held['status'] == 'needs_review' and 'notices_accounted' not in held
    forged = settle(entries2, bundles2, cities2, context2, 'AfraEtal06', bundle=b)
    forged['candidates'].insert(0, record)
    assert not R.valid_research_approval(roundtrip(forged))
    assert put_later(tmp_path / 'db.sqlite3', entry, forged, [record])['status'] == 'needs_review'


def test_a_no_doi_entry_names_every_record_of_its_candidates(entries2, bundles2, cities2, v2_bodies, tmp_path):
    # Este91 (no DOI): retain_notices checks every candidate DOI, so the author-suffix
    # record of the unrelated Murdock 1963 candidate must be named ('unrelated').
    entry = entries2['Este91']
    assert not entry['fields'].get('doi') and bundles2['Este91']['notices'][0]['class'] == 'unrelated'
    record = {'source': 'europepmc', 'doi': '10.1037/h0046262', 'raw_record': {
        'id': '14087627', 'source': 'MED', 'doi': '10.1037/h0046262', 'pubYear': '1963',
        'title': 'Interpolated recall in short-term memory.',
        'authorList': {'author': [{'fullName': 'MURDOCK BB Jr', 'lastName': 'MURDOCK', 'initials': 'BB'}]}}}
    assert R._table_dois(record) == {'10.1037/h0046262'}
    previous = v.outcome('needs_review', ['No unambiguous, fully supported metadata match'], [record])
    plain = R.merge(previous, assess2(entries2, bundles2, cities2, 'Este91'))
    assert plain['status'] == 'metadata_verified' and 'notices_accounted' not in plain
    assert put_later(tmp_path / 'plain.sqlite3', entry, plain, [record])['status'] == 'needs_review'
    b = named(bundles2['Este91'], [record])
    result = R.merge(previous, assess2(entries2, bundles2, cities2, 'Este91', bundle=b))
    assert result['notices_accounted']['doi'] is None
    assert result['notices_accounted']['notice_records'] == [
        {'doi': '10.1037/h0046262', 'identity': v.notice_record_identity(record)}]
    assert put_later(tmp_path / 'named.sqlite3', entry, result, [record])['status'] == 'metadata_verified'
    # Another candidate's record that nobody named reopens it.
    other = deepcopy(record)
    other['raw_record']['pubYear'] = '1964'
    result2 = deepcopy(result)
    result2['candidates'].insert(0, other)
    assert put_later(tmp_path / 'other.sqlite3', entry, result2, [other])['status'] == 'needs_review'


# ---- rule 5: braced group names

def test_braced_group_author_compares_equal(entries2, bundles2, cities2):
    # KingEtal11's byline as batch 32 sets it (pending in cdl.bib): Morrell + the braced group.
    rows = json.loads((V2 / 'root/verification/resolution-2026-09-26/batch-32.json').read_text())
    value = next(r for r in rows if r['key'] == 'KingEtal11')['set']['author']['value']
    assert value == 'M J Morrell and {RNS System in Epilepsy Study Group}'
    fields = dict(entries2['KingEtal11']['fields'], author=value)
    c = assess2(entries2, bundles2, cities2, 'KingEtal11', fields=fields)['candidates'][0]
    assert c['fields']['author']['origin'] == 'resolution/batch-32' and c['fields']['author']['value'] == value
    # The formatter's double-braced form, and an unbraced claim of the same group.
    for entry_value, claimed in (('M J Morrell and {{RNS System in Epilepsy Study Group}}', value),
                                 (value, 'Martha J Morrell and RNS System in Epilepsy Study Group')):
        b = deepcopy(bundles2['KingEtal11'])
        for claim in b['claims']:
            if claim['field'] == 'author' and claim['origin'] == 'resolution/batch-32':
                claim['value'] = claimed
        c = assess2(entries2, bundles2, cities2, 'KingEtal11', fields=dict(fields, author=entry_value),
                    bundle=b)['candidates'][0]
        assert 'author' in c['fields'], c['issues']
    # Negative controls: another group, or the group's words read as a personal name.
    c = assess2(entries2, bundles2, cities2, 'KingEtal11',
                fields=dict(fields, author='M J Morrell and {RNS System Study Group}'))['candidates'][0]
    assert any(i.startswith('author: the entry value differs') for i in c['issues'])
    assert R.canon('author', 'RNS System in Epilepsy Study Group') != R.canon('author', '{RNS System in Epilepsy Study Group}')
    assert R.canon('author', 'R {La Joie}', groups=R.braced_groups('R {La Joie}')) == R.canon('author', 'R La Joie')
    assert R.braced_groups('R {La Joie} and {Jupyter Development Team}') == {'jupyter development team'}


def test_withdrawal_when_the_research_row_is_gone_and_another_candidate_is_last(entries, bundles, cities, tmp_path):
    # A research approval whose entry later has no research row (its evidence left out),
    # after another route appended a candidate: merge used to take that candidate as the
    # research one (KeyError 'category'). Real run: US20a/b's rename not yet committed.
    approval = assess(entries, bundles, cities, 'Tulv74')
    other = json.loads((FIX / 'context.json').read_text())['DamaEtal96'][0]
    previous = dict(deepcopy(approval), candidates=approval['candidates'] + [other])
    again = R.merge(previous, v.outcome('needs_review', ['research: no research row for this entry']))
    assert again['status'] == 'needs_review' and again[R.NAME]['category'] == 'no_research_row'
    assert [c for c in again['candidates'] if c.get('source') == R.SOURCE] == []
    # through the backfill: the entry is withdrawn, not a crash
    bib = write_bib(tmp_path, entries, ['Tulv74'])
    cache = v.Cache(tmp_path / 'db.sqlite3')
    try:
        entry = v.load_entries(bib)['Tulv74']
        cache.store(bib, entry, dict(previous, checked_at=v.now(), key='Tulv74', fingerprint=entry['fingerprint'],
                                     policy=v.POLICY))
        empty = tmp_path / 'no-evidence'
        empty.mkdir()
        run = R.run_research_approve(bib, cache, root=empty, bodies=R.Bodies(BODIES))
        assert run['rows']['Tulv74']['outcome'] == 'withdrawn' and cache.get(bib, entry)['status'] == 'needs_review'
    finally:
        cache.close()
