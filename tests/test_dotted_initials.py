"""Regression and rejection boundaries for space-free dotted given initials."""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from verification import author_evidence, given_name_tokens


@pytest.mark.parametrize("local,source,expected", [
    ("Y-C", "Yi-Chieh", True), ("K.-H.", "Karl-Heinz", True),
    ("Jean-P", "Jean-Pierre", True), ("Y-C", "Yi-Ching", True),
    ("Y-C", "Yi-Hua", False), ("C-Y", "Yi-Chieh", False),
    ("Yi-Chieh", "Y-C", False), ("YC", "Yi-Chieh", False),
    ("Y C", "Yi-Chieh", False), ("Y-C", "Yi Chieh", False),
    ("Jo-P", "John-Pierre", False), ("J-P-C", "Jean-Pierre", False),
])
def test_explicit_hyphenated_initials(local, source, expected):
    assert author_evidence(local + " Smith", [{"family": "Smith", "given": source}])[0] is expected


@pytest.mark.parametrize("local,source,expected", [
    ("M A A Meer", "Matthijs A.A.", True),
    ("M A A Meer", "Matthijs A.A", True),
    ("Matthijs A A Meer", "Matthijs A.A.", True),
    ("M.E. J. Meer", "M E J", True),
    ("Y K Meer", "Y.K.", True),
    ("É A Meer", "É.A.", True),
    ("M A Meer", "Matthijs A.A.", False),
    ("M A B Meer", "Matthijs A.A.", False),
    ("M B A Meer", "Matthijs A.B.", False),
    ("M A A Meer", "Matthijs AA", False),
    ("M Ann Meer", "Matthijs A.A.", False),
    ("Matthijs Ann Alice Meer", "Matthijs A.A.", False),
    ("Matthijs A A Meer", "Michael A.A.", False),
    ("M A A Meer", "M.A.", False),
    ("M A A Meer", "", False),
])
def test_dotted_initials_preserve_complete_identity(local, source, expected):
    assert author_evidence(local, [{"family": "Meer", "given": source}])[0] is expected


@pytest.mark.parametrize("value,expected", [
    ("Matthijs A.A.", ["matthijs", "a", "a"]),
    ("M.E. J.", ["m", "e", "j"]),
    ("Jean-Pierre", ["jean-pierre"]),
    ("J.-P.", ["j-p"]),
    ("St.John", ["stjohn"]),
    ("Ann AA", ["ann", "aa"]),
])
def test_tokenization_is_limited_to_explicit_initial_runs(value, expected):
    assert given_name_tokens(value) == expected


def test_dotted_initials_do_not_relax_author_order_or_suffixes():
    source = [{"family": "Meer", "given": "A.B."}, {"family": "Other", "given": "C.D."}]
    assert not author_evidence("C D Other and A B Meer", source)[0]
    # Suffixes are ignored on both sides (user decision 2026-09-24/25).
    assert author_evidence("Meer, Jr, A B and C D Other", source)[0]
    assert not author_evidence("Other, Jr, C D and A B Meer", source)[0]


def test_resolver_reopens_only_new_secondary_targets(tmp_path):
    from auto_review import run_auto_review
    from verification import Cache, load_entries

    bib = tmp_path / "a.bib"
    bib.write_text("@article{A,author={A A Smith},title={Local title typo},year={2020},journal={Journal},volume={2},pages={1--9}}")
    cache = Cache(tmp_path / "v.sqlite3")
    entry = load_entries(bib)["A"]
    record = {"DOI": "10.1234/new", "type": "journal-article", "title": ["Correct title"],
              "author": [{"family": "Smith", "given": "A.A."}], "published": {"date-parts": [[2020]]},
              "container-title": ["Journal"], "volume": "2", "page": "1-9"}
    previous = {"status": "needs_review", "candidates": [{"source": "crossref", "doi": "10.1234/new", "record": record,
                "evidence": {"author": {"match": False}, "title": {"match": False}}}],
                "auto_review": {"policy": "2", "resolver_version": 3, "epmc_checked": True,
                                "epmc_checked_dois": ["10.1234/old"], "fulltext_checked": True,
                                "publisher_year_policy": "1"}}
    cache.put(bib, entry, previous)

    class Client:
        calls = 0
        requests = 0

        def get(self, url, params):
            self.calls += 1
            self.requests += 1
            assert params["query"] == 'DOI:"10.1234/new"'
            return {"url": url, "http_status": 200, "retrieved_at": "2026-09-15", "body": {"hitCount": 0, "resultList": {"result": []}}}

    client = Client()
    try:
        first = run_auto_review(bib, cache, tmp_path / "report.jsonl", client)
        assert first["A"]["status"] == "needs_review"  # The title still differs.
        checkpoint = first["A"]["auto_review"]
        assert checkpoint["epmc_checked_dois"] == ["10.1234/new", "10.1234/old"]
        assert "fulltext_checked" not in checkpoint
        assert "publisher_year_policy" not in checkpoint
        assert run_auto_review(bib, cache, tmp_path / "report.jsonl", client) == first
        assert client.calls == 1
    finally:
        cache.close()
