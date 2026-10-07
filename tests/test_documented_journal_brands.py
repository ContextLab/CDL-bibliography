"""Real publisher/NLM labels retain field and publication-identity checks."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from cdlbib.auto_review import reassess, run_auto_review
from cdlbib.helpers import format_journal_name
from cdlbib.verification import Cache, normalize_journal, normalize_title

CASES = {r["key"]: r for r in json.loads(
    (Path(__file__).parent / "fixtures/documented_journal_brands.json").read_text())}
ROYAL = "Philosophical Transactions of the Royal Society of London Series {B}: Biological Sciences"


def test_branded_real_journal_and_formatted_royal_title_agree_with_sources():
    case = deepcopy(CASES["WainJord08"])
    # The separately indexed monograph still blocks an unbound citation.
    assert reassess(case["entry"], case["previous"])["status"] == "needs_review"
    case["entry"]["fields"]["doi"] = "10.1561/2200000001"
    assert reassess(case["entry"], case["previous"])["status"] == "metadata_verified"
    case = deepcopy(CASES["WorsEtal05"])
    assert reassess(case["entry"], case["previous"])["status"] == "needs_review"
    assert format_journal_name(ROYAL) == ROYAL
    case["entry"]["fields"]["journal"] = ROYAL
    assert reassess(case["entry"], case["previous"])["status"] == "metadata_verified"
    assert normalize_journal(ROYAL) == normalize_journal(
        "Philosophical transactions of the Royal Society of London. Series B, Biological sciences")


@pytest.mark.parametrize("different", [
    "Foundations and Trends in Information Retrieval",
    "Foundations and Trends in Machine Learning Supplement",
    "Foundations and Trends in Machine Learning Reviews",
    "Foundations and Trends™ in Machine Learning",
    "Philosophical Transactions of the Royal Society A: Mathematical, Physical and Engineering Sciences",
    "Philosophical Transactions of the Royal Society B",
])
def test_exact_journal_variants_do_not_authorize_other_venues(different):
    for key in CASES:
        case = deepcopy(CASES[key])
        case["entry"]["fields"]["journal"] = different
        assert reassess(case["entry"], case["previous"])["status"] == "needs_review"


def test_journal_equivalence_does_not_remove_title_brands_or_other_blockers():
    assert normalize_title("Foundations and Trends® in Machine Learning") != normalize_title(
        "Foundations and Trends in Machine Learning")
    for field, value in [("year", "2009"), ("pages", "1--306"), ("author", "M J Wainwright")]:
        case = deepcopy(CASES["WainJord08"])
        case["entry"]["fields"]["doi"] = "10.1561/2200000001"
        case["entry"]["fields"][field] = value
        assert reassess(case["entry"], case["previous"])["status"] == "needs_review"
    case = deepcopy(CASES["WainJord08"])
    case["entry"]["fields"]["doi"] = "10.1561/2200000001"
    case["previous"]["external_evidence"] = [{"issue": "Unresolved publication version"}]
    assert reassess(case["entry"], case["previous"])["status"] == "needs_review"


def test_additive_resolver_reuses_real_review_without_new_requests(tmp_path):
    from cdlbib.verification import load_entries
    case = CASES["WainJord08"]
    bib = tmp_path / "source.bib"
    bib.write_text(case["entry"]["raw"][:-1] + ",\nDoi = {10.1561/2200000001}}")
    cache = Cache(tmp_path / "cache.sqlite3")
    try:
        entry = load_entries(bib)["WainJord08"]
        cache.put(bib, entry, case["previous"])
        first = run_auto_review(bib, cache, tmp_path / "report.jsonl")
        assert first["WainJord08"]["status"] == "metadata_verified"
        count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
        assert run_auto_review(bib, cache, tmp_path / "report.jsonl") == first
        assert cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == count
    finally:
        cache.close()
