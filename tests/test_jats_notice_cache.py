"""A saved PMC correction cannot disappear after an edit or cache restore."""

from copy import deepcopy

import pytest

import test_notice_cache
from auto_review import reassess, secondary_notice_flags
import verification as v


def setup(tmp_path):
    bib, old, entry, clean = test_notice_cache.setup(tmp_path)
    old.close()
    cache = v.Cache(tmp_path / "jats.sqlite3")
    med = next(c["raw_record"] for c in clean["candidates"] if c["source"] == "europepmc")
    doi = med["doi"]
    notice = {"source": "pmc-jats", "doi": doi, "medline_record": deepcopy(med),
              "raw_xml": '<article article-type="research-article"><front><article-meta>'
              f'<article-id pub-id-type="doi">{doi}</article-id>'
              '<related-article related-article-type="correction-forward"/>'
              '</article-meta></front></article>',
              "url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC123/fullTextXML",
              "retrieved_at": "2026-09-17", "xml_sha256": "test-document",
              "issues": ["Correction notice"], "evidence": {}}
    cache.put(bib, entry, v.outcome("needs_review", ["Correction notice"], [notice]))
    return bib, cache, entry, clean, notice


def test_jats_notice_survives_edit_rename_and_repeat(tmp_path, monkeypatch):
    bib, cache, entry, clean, _ = setup(tmp_path)
    bib.write_text(bib.read_text().replace(entry["fields"]["pages"], "315--324").replace(entry["key"], "Renamed", 1))
    calls = []
    monkeypatch.setattr(v, "verify_entry", lambda entry, client: calls.append(entry["key"]) or clean)
    after = v.run_verification(bib, cache, object(), tmp_path / "report.jsonl")
    assert after["Renamed"]["status"] == "needs_review"
    assert any("notice" in x for x in after["Renamed"]["issues"])
    assert reassess(v.load_entries(bib)["Renamed"], after["Renamed"])["status"] == "needs_review"
    count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
    assert v.run_verification(bib, cache, object(), tmp_path / "report.jsonl") == after
    assert calls == ["Renamed"]
    assert cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == count
    cache.close()


def test_jats_notice_snapshot_survives_no_matching_fingerprint(tmp_path):
    bib, cache, entry, clean, _ = setup(tmp_path)
    snapshot = tmp_path / "baseline.jsonl.gz"
    v.export_snapshot(bib, cache, snapshot)
    bib.write_text(bib.read_text().replace(entry["fields"]["pages"], "315--324"))
    fresh = v.Cache(tmp_path / "fresh.sqlite3")
    assert v.import_snapshot(bib, fresh, snapshot) == 0
    new = v.load_entries(bib)[entry["key"]]
    assert fresh.put(bib, new, clean)["status"] == "needs_review"
    assert fresh.db.execute("SELECT count(*) FROM source_notices").fetchone()[0] == 1
    cache.close()
    fresh.close()


def test_jats_migration_is_incremental_and_independent_of_old_pubmed_checkpoint(tmp_path):
    bib, cache, entry, clean, notice = setup(tmp_path)
    cache.db.execute("DELETE FROM source_notices")
    end = cache.db.execute("SELECT max(id) FROM reviews").fetchone()[0]
    cache.db.execute("INSERT OR REPLACE INTO notice_checkpoint VALUES (1,?)", (end,))
    cache.db.commit()
    cache.index_notices()
    assert cache.db.execute("SELECT count(*) FROM source_notices").fetchone()[0] == 1
    cache.index_notices()
    assert cache.db.execute("SELECT count(*) FROM source_notices").fetchone()[0] == 1
    assert cache.retain_notices(entry, clean)["status"] == "needs_review"
    cache.close()


@pytest.mark.parametrize("change", ["wrong-doi", "wrong-medline", "references-only", "commentary", "manuscript"])
def test_unrelated_or_nonnotice_xml_cannot_hold_a_doi(tmp_path, change):
    _, cache, _, _, notice = setup(tmp_path)
    if change == "wrong-doi":
        notice["doi"] = "10.1234/other"
    elif change == "wrong-medline":
        notice["medline_record"]["doi"] = "10.1234/other"
    elif change == "references-only":
        notice["raw_xml"] = notice["raw_xml"].replace("<front>", "<back>").replace("</front>", "</back>")
    elif change == "commentary":
        notice["raw_xml"] = notice["raw_xml"].replace("correction-forward", "commentary")
    else:
        notice["raw_xml"] = notice["raw_xml"].replace('<related-article related-article-type="correction-forward"/>',
            '<article-id pub-id-type="manuscript-id">NIHMS1</article-id>')
    assert not secondary_notice_flags([notice])
    cache.close()


@pytest.mark.parametrize("legacy_direct", [False, True])
def test_new_notice_for_rejected_search_alternative_never_rewrites_approval(tmp_path, legacy_direct):
    bib, cache, entry, clean, notice = setup(tmp_path)
    cache.db.execute('DELETE FROM source_notices')
    cache.db.commit()
    good = deepcopy(clean)
    if legacy_direct:
        good.pop('accepted_doi', None)
        good.pop('accepted_source', None)
        primary = next(c for c in good['candidates'] if c['source'] == 'crossref')
        primary['issues'] = []
    wrong = deepcopy(good['candidates'][0])
    wrong['doi'] = '10.1234/unrelated'
    wrong['issues'] = ['title: missing evidence or mismatch']
    good['candidates'].append(wrong)
    approved = cache.put(bib, entry, good)
    assert approved['status'] == 'metadata_verified'
    original_doi = notice['doi']
    notice['doi'] = '10.1234/unrelated'
    notice['medline_record']['doi'] = notice['doi']
    notice['raw_xml'] = notice['raw_xml'].replace(original_doi, notice['doi'])
    cache.remember_notices([notice])
    writes = cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert cache.get(bib, entry) == approved
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0] == writes
    # A subsequently learned notice for the actual accepted DOI must reopen it.
    notice['raw_xml'] = notice['raw_xml'].replace(notice['doi'], original_doi)
    notice['doi'] = notice['medline_record']['doi'] = original_doi
    cache.remember_notices([notice])
    assert cache.get(bib, entry)['status'] == 'needs_review'
    cache.close()
