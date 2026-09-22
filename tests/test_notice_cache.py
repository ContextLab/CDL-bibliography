"""Edits and portable baseline restores cannot discard known source notices."""

from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
import verification as v
from auto_review import reassess


def setup(tmp_path):
    fixture = json.loads((Path(__file__).parent / "fixtures/pagination_corrections.json").read_text())["MoheEtal14"]
    entry = fixture["entry"]
    bib = tmp_path / "source.bib"
    bib.write_text(entry["raw"])
    entry = v.load_entries(bib)[entry["key"]]
    previous = fixture["previous"]
    notice = deepcopy(next(c for c in previous["candidates"] if c["source"] == "europepmc"))
    notice["raw_record"]["commentCorrectionList"] = {"commentCorrection": [{"type": "Erratum in", "reference": "Correction notice"}]}
    cache = v.Cache(tmp_path / "cache.sqlite3")
    cache.put(bib, entry, v.outcome("needs_review", ["Correction notice"], [notice]))
    # Construct a fresh, otherwise clean provider result, as before the bug fix.
    corrected = dict(entry, fields=dict(entry["fields"], pages="315--324"))
    clean = reassess(corrected, previous)
    assert clean["status"] == "metadata_verified"
    return bib, cache, entry, clean


@pytest.mark.parametrize("rename", [False, True])
def test_new_fingerprint_keeps_negative_evidence_and_repeat_is_cached(tmp_path, monkeypatch, rename):
    bib, cache, entry, clean = setup(tmp_path)
    text = bib.read_text().replace(entry["fields"]["pages"], "315--324")
    if rename:
        text = text.replace(entry["key"], "Renamed", 1)
    bib.write_text(text)
    key = "Renamed" if rename else entry["key"]
    assert v.current_results(bib, cache)[key]["status"] == "pending"
    calls = []
    monkeypatch.setattr(v, "verify_entry", lambda entry, client: calls.append(entry["key"]) or clean)
    after = v.run_verification(bib, cache, object(), tmp_path / "report.jsonl")
    assert after[key]["status"] == "needs_review"
    assert any("notice" in i for i in after[key]["issues"])
    rows = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
    assert v.run_verification(bib, cache, object(), tmp_path / "report.jsonl") == after
    assert calls == [key]
    assert cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == rows
    cache.close()


def test_snapshot_preserves_notice_when_no_fingerprint_matches(tmp_path):
    bib, cache, entry, clean = setup(tmp_path)
    snapshot = tmp_path / "snapshot.jsonl.gz"
    v.export_snapshot(bib, cache, snapshot)
    edited = tmp_path / "edited.bib"
    edited.write_text(bib.read_text().replace(entry["fields"]["pages"], "315--324").replace(entry["key"], "Renamed", 1))
    restored = v.Cache(tmp_path / "restored.sqlite3")
    assert v.import_snapshot(edited, restored, snapshot) == 0
    new = v.load_entries(edited)["Renamed"]
    assert restored.put(edited, new, clean)["status"] == "needs_review"
    cache.close()
    restored.close()


def test_migration_indexes_old_audit_history_once(tmp_path):
    bib, cache, entry, clean = setup(tmp_path)
    cache.db.execute("DELETE FROM source_notices")
    cache.db.commit()
    cache.index_notices()
    assert cache.db.execute("SELECT count(*) FROM source_notices").fetchone()[0] == 1
    cache.index_notices()
    assert cache.db.execute("SELECT count(*) FROM source_notices").fetchone()[0] == 1
    unrelated = deepcopy(clean)
    unrelated["accepted_doi"] = "10.1234/other"
    for c in unrelated["candidates"]:
        c["doi"] = "10.1234/other"
    assert cache.retain_notices(entry, unrelated) == unrelated
    cache.close()


def test_existing_notice_inside_a_premature_approval_is_not_ignored(tmp_path):
    bib, cache, entry, clean = setup(tmp_path)
    notice = json.loads(cache.db.execute("SELECT candidate FROM source_notices").fetchone()[0])
    premature = dict(clean, candidates=clean["candidates"] + [notice])
    assert cache.put(bib, entry, premature)["status"] == "needs_review"
    human = {"status": "human_verified", "human_review": {
        "reviewer": "Reviewer", "source": "Correction notice", "notes": "Explicitly adjudicated"}}
    assert cache.put(bib, entry, human)["status"] == "human_verified"
    cache.close()


def test_invalid_notice_snapshot_is_atomic(tmp_path):
    bib, cache, _, _ = setup(tmp_path)
    snapshot = tmp_path / "snapshot.jsonl.gz"
    v.export_snapshot(bib, cache, snapshot)
    with gzip.open(snapshot, "rt") as stream:
        records = [json.loads(line) for line in stream]
    records[0]["source_notices"].append({"source": "invented"})
    with gzip.open(snapshot, "wt") as stream:
        stream.write("\n".join(json.dumps(r) for r in records) + "\n")
    restored = v.Cache(tmp_path / "restored.sqlite3")
    with pytest.raises(ValueError, match="source notice"):
        v.import_snapshot(bib, restored, snapshot)
    assert restored.db.execute("SELECT count(*) FROM source_notices").fetchone()[0] == 0
    assert restored.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0
    cache.close()
    restored.close()
