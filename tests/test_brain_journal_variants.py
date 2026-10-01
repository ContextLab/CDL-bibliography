"""Documented section titles must not collapse distinct journals or history."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from cdlbib.auto_review import reassess, run_auto_review
from cdlbib.correction_proposals import field_proposal
from cdlbib.helpers import format_journal_name
from cdlbib.verification import Cache, current_results, export_snapshot, import_snapshot, load_entries, normalize_journal

CASES = {r["key"]: r for r in json.loads(
    (Path(__file__).parent / "fixtures/brain_journal_variants.json").read_text())}


@pytest.mark.parametrize("variant", [
    "Cognitive Brain Research", "Brain research. Cognitive brain research",
    "Brain Research: Cognitive Brain Research", "Brain Research : Cognitive Brain Research",
])
def test_documented_cognitive_section_variants_reassess_real_evidence(variant):
    case = deepcopy(CASES["MeckEtal03"])
    case["entry"]["fields"]["journal"] = variant
    assert reassess(case["entry"], case["previous"])["status"] == "metadata_verified"


@pytest.mark.parametrize("different", [
    "Brain Research", "Brain Research Reviews", "Brain Research: Brain Research Reviews",
    "Experimental Brain Research", "Cognitive Brain Research Reviews",
    "Brain Research Bulletin", "Brain Research: Cognitive Brain Research Supplement",
])
def test_section_alias_does_not_approve_another_journal(different):
    case = deepcopy(CASES["MeckEtal03"])
    case["entry"]["fields"]["journal"] = different
    assert reassess(case["entry"], case["previous"])["status"] == "needs_review"


def test_alias_does_not_erase_other_field_or_external_conflicts():
    case = deepcopy(CASES["MeckEtal03"])
    case["entry"]["fields"]["pages"] = "99--101"
    assert reassess(case["entry"], case["previous"])["status"] == "needs_review"
    case = deepcopy(CASES["MeckEtal03"])
    case["previous"]["external_evidence"] = [{"issue": "Unresolved publication version"}]
    assert reassess(case["entry"], case["previous"])["status"] == "needs_review"


def test_reviews_title_is_a_corroborated_edit_and_not_a_global_alias():
    case = deepcopy(CASES["EtniEtal06"])
    assert reassess(case["entry"], case["previous"])["status"] == "needs_review"
    p = field_proposal(case["entry"], case["previous"], "journal")
    assert p["changes"] == {"journal": {"before": "Brain Research: Brain Research Reviews",
                                      "after": "Brain Research Reviews"}}
    assert normalize_journal("Brain Research Reviews") != normalize_journal("Brain Research: Brain Research Reviews")
    assert format_journal_name("Brain Research Reviews") == "Brain Research Reviews"
    assert format_journal_name("Brain Research: Brain Research Reviews") == "Brain Research: Brain Research Reviews"
    case["previous"]["external_evidence"] = [{"issue": "Unresolved version"}]
    assert field_proposal(case["entry"], case["previous"], "journal") is None


def test_real_alias_cache_survives_rename_and_restore_but_not_metadata_edit(tmp_path):
    case = CASES["MeckEtal03"]
    bib = tmp_path / "source.bib"; bib.write_text(case["entry"]["raw"])
    cache = Cache(tmp_path / "cache.sqlite3")
    fresh = Cache(tmp_path / "fresh.sqlite3")
    try:
        entry = load_entries(bib)["MeckEtal03"]
        cache.put(bib, entry, {"status": "needs_review", "issues": ["held"],
                              "candidates": case["previous"]["candidates"]})
        first = run_auto_review(bib, cache, tmp_path / "report.jsonl")
        assert first["MeckEtal03"]["status"] == "metadata_verified"
        count = cache.db.execute("select count(*) from reviews").fetchone()[0]
        assert run_auto_review(bib, cache, tmp_path / "report.jsonl") == first
        assert cache.db.execute("select count(*) from reviews").fetchone()[0] == count
        snapshot = tmp_path / "snapshot.jsonl.gz"; export_snapshot(bib, cache, snapshot)
        assert import_snapshot(bib, fresh, snapshot) == 1
        assert current_results(bib, fresh) == first
        bib.write_text(case["entry"]["raw"].replace("MeckEtal03", "Renamed03", 1))
        renamed = load_entries(bib)["Renamed03"]
        assert renamed["fingerprint"] == entry["fingerprint"]
        assert cache.get(bib, renamed)["status"] == "metadata_verified"
        bib.write_text(bib.read_text().replace("26--38", "99--101"))
        edited = load_entries(bib)["Renamed03"]
        assert edited["fingerprint"] != entry["fingerprint"]
        assert cache.get(bib, edited) is None
    finally:
        fresh.close(); cache.close()
