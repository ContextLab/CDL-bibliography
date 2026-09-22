from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from fulltext_review import assess_fulltext, front_record
from auto_review import reassess, select_result
import test_auto_review
from test_auto_review import candidate

sample = test_auto_review.sample

XML = """<article article-type="research-article"><front>
<journal-meta><journal-title-group><journal-title>Memory &amp; Cognition</journal-title></journal-title-group><issn>1234-5678</issn></journal-meta>
<article-meta><article-id pub-id-type="doi">10.1234/a</article-id>
<title-group><article-title>A result: its meaning</article-title></title-group>
<contrib-group><contrib contrib-type="author"><name><surname>Smith</surname><given-names>Alice B</given-names></name></contrib></contrib-group>
<pub-date pub-type="ppub"><year>2020</year></pub-date><pub-date pub-type="epub"><year>2019</year></pub-date>
<volume>2</volume><issue>3</issue><fpage>123</fpage><lpage>129</lpage>
<abstract><p>This must not be included in the portable snapshot.</p></abstract>
</article-meta></front><back><ref-list><ref><element-citation><article-title>Wrong paper</article-title><pub-id pub-id-type="doi">10.1234/wrong</pub-id></element-citation></ref></ref-list></back></article>"""


def assessment(sample, xml=XML):
    fields, record, raw = sample
    return assess_fulltext(
        fields,
        candidate(fields, record),
        raw,
        {
            "body": xml,
            "url": "https://example.test/article.xml",
            "retrieved_at": "2026-09-09",
        },
    )


def test_publisher_front_matter_proves_edition(sample):
    result = assessment(sample)
    assert not result["issues"]
    assert select_result(sample[0], [result], [])["status"] == "metadata_verified"
    assert "<back>" not in result["raw_xml"] and "<abstract>" not in result["raw_xml"]
    assert result["xml_sha256"]


def test_explicit_author_group_and_unqualified_publication_date(sample):
    xml = XML.replace(
        '<contrib-group><contrib contrib-type="author">',
        '<contrib-group content-type="author"><contrib>',
    )
    xml = xml.replace('pub-type="ppub"', "")
    assert not assessment(sample, xml)["issues"]


def test_initial_pmc_archive_version_is_not_a_preprint(sample):
    xml = XML.replace(
        "<article-meta>",
        '<article-meta><article-version article-version-type="pmc-version">1</article-version>',
    )
    assert not assessment(sample, xml)["issues"]
    assert assessment(sample, xml.replace('pmc-version">1', 'pmc-version">2'))["issues"]


@pytest.mark.parametrize(
    "before,after",
    [
        ('doi">10.1234/a', 'doi">10.1234/wrong'),
        ("A result: its meaning", "A result"),
        ("Alice B", "Alice Q"),
        ("<fpage>123", "<fpage>124"),
        ("<volume>2", "<volume>3"),
        ('article-type="research-article"', 'article-type="correction"'),
        ("<year>2020", "<year>2021"),
        ("<article-meta>", "<article-meta><article-version>preprint</article-version>"),
        (
            "<article-meta>",
            '<article-meta><article-id pub-id-type="manuscript">123</article-id>',
        ),
        (
            "<article-meta>",
            '<article-meta><related-article related-article-type="corrected-article"/>',
        ),
        ("its meaning", "its <sub>meaning</sub>"),
    ],
)
def test_fulltext_conflicts_and_versions_never_pass(sample, before, after):
    assert assessment(sample, XML.replace(before, after))["issues"]


def test_reference_list_cannot_supply_missing_front_metadata(sample):
    fields, record, raw = sample
    xml = XML.replace('<article-id pub-id-type="doi">10.1234/a</article-id>', "")
    xml = xml.replace("10.1234/wrong", "10.1234/a")
    with pytest.raises(ValueError):
        front_record(xml, record, raw)


@pytest.mark.parametrize("identifier_type", ["manuscript-id", "manuscript-id-alternative"])
def test_pmc_manuscript_identifiers_require_version_review(sample, identifier_type):
    xml = XML.replace(
        "<article-meta>",
        f'<article-meta><article-id pub-id-type="{identifier_type}">NIHMS38394</article-id>',
    )
    result = assessment(sample, xml)
    assert any("Author manuscript/preprint" in issue for issue in result["issues"])
    assert select_result(sample[0], [result], [])["status"] == "needs_review"


def test_same_paper_requires_pagination_corroboration(sample):
    sample[2]["pageInfo"] = "123-130"
    assert assessment(sample)["issues"]


def test_registry_preprint_cannot_be_overridden_by_final_pdf(sample):
    sample[1]["type"] = "posted-content"
    assert assessment(sample)["issues"]


def test_recheck_uses_raw_front_matter_and_preserves_download_hash(sample):
    fields, record, raw = sample
    original = assessment(sample)
    saved = {
        "status": "metadata_verified",
        "candidates": [candidate(fields, record), original],
    }
    checked = reassess({"fields": fields}, saved)
    assert checked["status"] == "metadata_verified"
    full = next(c for c in checked["candidates"] if c["source"] == "pmc-jats")
    assert full["xml_sha256"] == original["xml_sha256"]
    original["raw_xml"] = original["raw_xml"].replace("Alice B", "Alice Q")
    assert reassess({"fields": fields}, saved)["status"] == "needs_review"


@pytest.mark.parametrize("legacy_status", [200, 404])
def test_new_pmc_target_is_checked_after_legacy_fulltext_pass(tmp_path, sample, legacy_status):
    from copy import deepcopy
    from fulltext_review import run_fulltext_review
    from verification import Cache, load_entries
    from test_auto_review import secondary
    fields, record, raw = sample
    path = tmp_path / "sample.bib"
    path.write_text("@article{A,\n" + ",\n".join(
        key + "={" + value + "}" for key, value in fields.items() if key not in {"ID", "ENTRYTYPE"}
    ) + "}\n")
    entry = load_entries(path)["A"]
    raw.update(pmcid="PMC100", isOpenAccess="Y", pageInfo="999-1000")
    old = secondary(fields, record, raw)
    added = deepcopy(old)
    added["raw_record"]["pmcid"] = "PMC200"
    previous = {"status": "needs_review", "candidates": [candidate(fields, record), old, added],
                "attempts": [{"source": "pmc-jats", "http_status": legacy_status,
                              "url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC100/fullTextXML"}],
                "auto_review": {"fulltext_checked": True, "fulltext_policy": "1"}}
    class Client:
        def __init__(self): self.urls = []
        def get(self, url, **kwargs):
            self.urls.append(url)
            return {"url": url, "http_status": 404, "body": None}
    cache, client = Cache(tmp_path / "cache.sqlite3"), Client()
    try:
        cache.put(path, entry, previous)
        first = run_fulltext_review(path, cache, client, tmp_path / "report.jsonl")
        assert client.urls == ["https://www.ebi.ac.uk/europepmc/webservices/rest/PMC200/fullTextXML"]
        assert first["A"]["auto_review"]["fulltext_checked_pmcids"] == ["PMC100", "PMC200"]
        assert first["A"]["status"] == "needs_review"
        writes = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
        assert run_fulltext_review(path, cache, client, tmp_path / "report.jsonl") == first
        assert len(client.urls) == 1
        assert cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == writes
    finally:
        cache.close()
