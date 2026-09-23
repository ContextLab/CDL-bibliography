#!/usr/bin/env python
"""Offline measurement of the policy-7 catalogue grammar (no network, no writes
to the cache or bibliography).

Reads cdl.bib and the latest review row per entry from
.bibcheck/verification.sqlite3 opened READ-ONLY (SQLite URI mode=ro), re-runs
the catalogue assessment in memory on the cached LC search XML, and writes:

  proposals.json  correction proposals (key, fingerprint, field before/after,
                  source record id, rule) for unresolved book-like entries
  groups.json     every other unresolved book-like entry, grouped by pattern,
                  plus the measured summary and the regression check

Usage: .venv/bin/python verification/catalogue-phase0-2026-09-22/measure.py
"""
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'bibcheck'))

import catalogue_review as cr  # noqa: E402
import verification as v  # noqa: E402

BOOK_LIKE = {'book', 'incollection', 'inbook', 'phdthesis', 'mastersthesis', 'techreport', 'manual'}
COARSE = ROOT / 'verification/resolution-plan-2026-09-22/data/books-coarse.json'

# Remaining catalogue books: the assessment's own reason, mapped to a pattern.
CATALOGUE_GROUPS = {
    'catalogue-byline-et-al': (
        "LC transcribes only the first name and '[et al.]'; the catalogue cannot confirm the full byline.",
        "Confirm the byline from a title page (local PDF / page image); otherwise human sign-off as cited."),
    'catalogue-reissue-translation-or-microform': (
        "LC holds only a reprint/reissue, microform, e-book or translation-note record for this year; "
        "it never substitutes for the cited printed edition.",
        "Keep unresolved in the catalogue route; approve as cited only with title-page evidence (batch human sign-off)."),
    'catalogue-other-editions-only': (
        "Every LC record is another year, title or edition (e.g. later editions, a companion volume); "
        "no record of the cited edition exists in the cached search.",
        "Batch: keep as cited pending another source; a year/edition change needs the user's per-group yes."),
    'catalogue-identity-disagrees': (
        "LC has the work, but more than two of title/author/year/publisher/address/edition disagree, "
        "or the citation is not a monograph (chapter/volume/series).",
        "Human review, one packet per entry (these are likely citation defects)."),
    'catalogue-grammar-unsupported': (
        "The LC record is the right kind but its byline/heading grammar is outside the reviewed rules "
        "(anonymous byline, contributors in 245c, subtitle in 245c, 700 with $t, corporate co-author, "
        "given-name form conflict).",
        "Human sign-off in one batch; no further grammar widening proposed."),
    'catalogue-several-editions': (
        "Two parsed LC records of the cited year differ from the citation in at most two fields.",
        "Human picks the edition (one decision per entry)."),
    'catalogue-transcription-typo': (
        "The only matching LC record misspells a field (e.g. 'Psycholoby Press', 'Oxord University Press').",
        "Approve as cited in one batch (the citation is right; the catalogue is wrong)."),
}

# Book-like entries with no cached catalogue search, by the resolution plan's
# coarse class (verification/resolution-plan-2026-09-22/data/books-coarse.json).
PLAN_GROUPS = [
    ('C-NONE', 'chapter-no-registry-record',
     'Chapter in a (mostly pre-DOI) edited volume with no chapter-level registry record.',
     'No user decision yet: needs the R3 two-layer rule (LC parent-volume search, network) plus a chapter '
     'layer (same-edition chapter DOI or inspected TOC/first-page image). Leftovers go to one batch sign-off.'),
    ('C-INBOOK', 'inbook-chapter-title-in-chapter-field',
     "@inbook whose 'chapter' field holds the chapter title and 'title' the book title.",
     'Apply the already-recorded decision (titled-chapter @inbook -> @incollection) as a frozen batch, '
     'then re-verify; no new decision.'),
    ('C-REG: identity, only structural', 'chapter-needs-editor-address-verifier',
     'Chapter registry identity is right; blocked only by editor/address/absent-pages checks.',
     'No user decision: needs the editor/address hooks in verification.py (see README).'),
    ('C-REG: identity, publisher/container', 'chapter-registry-name-variant',
     'Chapter identity is right; registry publisher/container string differs (archival publisher, set vs volume).',
     'Batch decision: allow one inspected edition binding per volume (book_editions.json pattern).'),
    ('C-REG: identity-like but year', 'chapter-registry-reissue-or-serial',
     'Registry record is a reissue, anthology reprint or serial volume of the cited chapter.',
     'Keep rejected (reissues never substitute); serial-volume cases become booktitle/volume correction proposals.'),
    ('C-REG: identity-like, byline', 'chapter-registry-byline-or-pages-differ',
     'Registry chapter matches title/container but byline or pages differ.',
     'Human review, one packet per entry.'),
    ('B-NONE', 'book-no-catalogue-or-registry-hit',
     'No cached LC hit and no registry identity: mostly citation typos, edition text in the title, '
     'wrong entry types, corporate authors.',
     'Frozen correction batch after source checks (R1); then a fresh LC search per corrected entry.'),
    ('B-REG-only', 'book-registry-reissue-only',
     'Only a later/archival registry record exists (no LC record cached).',
     'Keep rejected; LC search by title+author (network) or human sign-off as cited.'),
    ('T-THESIS', 'thesis',
     'Doctoral/masters theses: no catalogue route.',
     "Human sign-off as cited (the user's own theses first), or repository-record route."),
    ('T-REPORT/MANUAL', 'report-or-manual',
     'Technical reports, PEPs and software manuals.',
     'PEP JSON route for the 4 PEPs; human sign-off for the rest.'),
]


# Correction classes: the unit of one batch decision and one 10-entry spot check.
RULE_CLASS = {
    'publisher-name-form': 'P1 publisher: catalogue form of the same firm',
    'publisher-different': 'P2 publisher: a different firm (cited distributor/later owner/imprint)',
    'title-add-catalogue-subtitle': 'T title: complete from the catalogue',
    'title-leading-article': 'T title: complete from the catalogue',
    'title-article-and-subtitle': 'T title: complete from the catalogue',
    'title-spelling': 'T title: complete from the catalogue',
    'byline-given-names': 'A1 byline: given names/suffix/surname from the title page',
    'byline-suffix': 'A1 byline: given names/suffix/surname from the title page',
    'byline-surname-diacritics': 'A1 byline: given names/suffix/surname from the title page',
    'byline-surname-spelling': 'A1 byline: given names/suffix/surname from the title page',
    'byline-initials-not-on-title-page': 'A2 byline: drop initials the title page does not print',
    'edited-volume-author-to-editor': 'E edited volume: move names from author to editor',
    'edition-from-catalogue': 'D edition: add the edition the catalogue states',
    'address-state-or-country-suffix': 'L place: catalogue place form',
    'address-different': 'L place: catalogue place form',
    'year-from-catalogue-edition': 'Y year: the only catalogue edition\'s year (same publisher)',
}


def classify_catalogue_group(proposal_group, reason, key, result):
    text = reason.lower()
    if 'only part of the byline' in text:
        return 'catalogue-byline-et-al'
    if proposal_group == 'several-plausible-editions':
        return 'catalogue-several-editions'
    if proposal_group == 'catalogue-transcription-typo':
        return 'catalogue-transcription-typo'
    if proposal_group == 'catalogue-only-other-editions':
        return 'catalogue-other-editions-only'
    if proposal_group in ('catalogue-different-edition-or-work', 'correction-would-not-verify'):
        # Separate records that are only other editions from real disagreements.
        years = {c['record'].get('published', {}).get('date-parts', [[None]])[0][0]
                 for c in result['candidates'] if c.get('source') == 'loc-catalogue' and c.get('record')}
        cited = result.get('_cited_year')
        if years and cited and str(cited) not in {str(y) for y in years}:
            return 'catalogue-other-editions-only'
        return 'catalogue-identity-disagrees'
    if ('single-year printed monograph' in text or 'edition note' in text or 'translation or revision' in text
            or 'related editions' in text and 'corporate' not in reason.lower()):
        return 'catalogue-reissue-translation-or-microform'
    return 'catalogue-grammar-unsupported'


def latest_reviews(bib, db_path, entries):
    db = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    path = str(Path(bib).resolve())
    out = {}
    for key, entry in entries.items():
        rows = [db.execute("""SELECT id,result FROM reviews WHERE bibliography=? AND fingerprint=?
                              AND policy=? ORDER BY id DESC LIMIT 1""",
                           (path, entry['fingerprint'], v.POLICY)).fetchone(),
                db.execute("""SELECT id,result FROM reviews WHERE bibliography=? AND key=? AND fingerprint=?
                              AND policy=? ORDER BY id DESC LIMIT 1""",
                           (path, key, entry['legacy_fingerprint'], v.POLICY)).fetchone()]
        row = max((r for r in rows if r), default=None)
        out[key] = json.loads(row[1]) if row else None
    db.close()
    return out


def main():
    bib = ROOT / 'cdl.bib'
    entries = v.load_entries(bib)
    reviews = latest_reviews(bib, ROOT / '.bibcheck/verification.sqlite3', entries)
    coarse = json.loads(COARSE.read_text())
    status = Counter((r or {}).get('status') for r in reviews.values())

    # 1. Regression check over EVERY currently verified entry the catalogue
    #    code can touch (any entry with saved LC candidates).
    regression = {'checked': 0, 'kept': 0, 'regressed': [], 'verified_other_source_with_lc': []}
    for key, result in reviews.items():
        if not result or result['status'] != 'metadata_verified':
            continue
        if not any(c.get('source') == 'loc-catalogue' for c in result.get('candidates', [])):
            continue
        regression['checked'] += 1
        if result.get('accepted_source') != 'loc-catalogue':
            regression['verified_other_source_with_lc'].append(key)
        new = cr.reassess_saved_catalogue(entries[key]['fields'], result)
        accepted = [c for c in result['candidates'] if c.get('record_id') == result.get('accepted_record_id')
                    and c.get('source') == 'loc-catalogue']
        rebuilt = [c for c in new['candidates'] if c.get('record_id') == new.get('accepted_record_id')
                   and c.get('source') == 'loc-catalogue']
        ok = (new['status'] == 'metadata_verified'
              and new.get('accepted_record_id') == result.get('accepted_record_id')
              and cr.valid_catalogue_approval(result) and accepted == rebuilt)
        if ok:
            regression['kept'] += 1
        else:
            regression['regressed'].append(key)

    # 2. Unresolved book-like entries.
    unresolved = {k: r for k, r in reviews.items() if r and r['status'] != 'metadata_verified'
                  and entries[k]['fields']['ENTRYTYPE'].lower() in BOOK_LIKE}
    verified, proposals, grouped = [], [], defaultdict(list)
    for key in sorted(unresolved):
        result, fields = unresolved[key], entries[key]['fields']
        if any(c.get('source') == 'loc-catalogue' for c in result.get('candidates', [])):
            new = cr.reassess_saved_catalogue(fields, result)
            if new['status'] == 'metadata_verified':
                verified.append({'key': key, 'fingerprint': entries[key]['fingerprint'],
                                 'record_id': new['accepted_record_id'],
                                 'grammar': next(c['record'].get('catalogue_grammar', '6') for c in new['candidates']
                                                 if c.get('record_id') == new['accepted_record_id'])})
                continue
            try:
                outcome = cr.propose_corrections(fields, new)
            except ValueError as exc:
                outcome = {'group': 'catalogue-grammar-unsupported', 'reason': str(exc)}
            if 'proposal' in outcome:
                p = outcome['proposal']
                for change in p['changes']:
                    proposals.append({'key': key, 'fingerprint': entries[key]['fingerprint'],
                                      'field': change['field'], 'before': change['before'],
                                      'after': change['after'], 'source': 'loc-catalogue',
                                      'source_record_id': p['record_id'], 'catalogue_url': p['catalogue_url'],
                                      'rule': change['rule'], 'class': RULE_CLASS[change['rule']]})
                continue
            new['_cited_year'] = fields.get('year')
            group = classify_catalogue_group(outcome['group'], outcome['reason'], key, new)
            grouped[group].append({'key': key, 'reason': outcome['reason']})
            continue
        label = coarse.get(key, '')
        match = next((g for g in PLAN_GROUPS if label.startswith(g[0])), None)
        if match is None:
            grouped['unclassified'].append({'key': key, 'reason': label or 'not in books-coarse.json'})
        else:
            grouped[match[1]].append({'key': key, 'reason': label})

    groups = []
    for gid, (description, decision) in CATALOGUE_GROUPS.items():
        if grouped.get(gid):
            groups.append({'id': gid, 'description': description, 'count': len(grouped[gid]),
                           'keys': [x['key'] for x in grouped[gid]], 'suggested_batch_decision': decision,
                           'reasons': {x['key']: x['reason'] for x in grouped[gid]}})
    for _, gid, description, decision in PLAN_GROUPS:
        if grouped.get(gid):
            groups.append({'id': gid, 'description': description, 'count': len(grouped[gid]),
                           'keys': [x['key'] for x in grouped[gid]], 'suggested_batch_decision': decision})
    if grouped.get('unclassified'):
        groups.append({'id': 'unclassified', 'description': 'Not in any plan class', 'count': len(grouped['unclassified']),
                       'keys': [x['key'] for x in grouped['unclassified']], 'suggested_batch_decision': 'Inspect'})

    proposal_keys = sorted({p['key'] for p in proposals})
    rules = Counter(p['rule'] for p in proposals)
    rule_entries = {r: sorted({p['key'] for p in proposals if p['rule'] == r}) for r in rules}
    summary = {
        'baseline_status': dict(status),
        'unresolved_book_like': len(unresolved),
        'unresolved_book_like_by_type': dict(Counter(entries[k]['fields']['ENTRYTYPE'].lower() for k in unresolved)),
        'with_cached_catalogue_search': sum(1 for r in unresolved.values()
                                            if any(c.get('source') == 'loc-catalogue' for c in r.get('candidates', []))),
        'verified_without_edit': len(verified),
        'entries_with_correction_proposals': len(proposal_keys),
        'proposal_rows': len(proposals),
        'proposal_rules_entries': {r: len(k) for r, k in sorted(rule_entries.items())},
        'proposal_classes_entries': {c: len({p['key'] for p in proposals if p['class'] == c})
                                     for c in sorted({p['class'] for p in proposals})},
        'remaining_grouped': sum(g['count'] for g in groups),
        'groups': {g['id']: g['count'] for g in groups},
        'regression': {'verified_entries_with_catalogue_candidates': regression['checked'],
                       'kept_identical': regression['kept'], 'regressed': regression['regressed'],
                       'verified_by_other_source_but_holding_lc_candidates': regression['verified_other_source_with_lc']},
    }
    assert len(verified) + len(proposal_keys) + summary['remaining_grouped'] == len(unresolved)
    (HERE / 'proposals.json').write_text(json.dumps(
        {'generated_by': 'measure.py', 'policy': cr.CATALOGUE_POLICY, 'verified_without_edit': verified,
         'rule_entries': rule_entries, 'proposals': proposals}, indent=1, ensure_ascii=False) + '\n')
    (HERE / 'groups.json').write_text(json.dumps(
        {'generated_by': 'measure.py', 'summary': summary, 'groups': groups}, indent=1, ensure_ascii=False) + '\n')
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
