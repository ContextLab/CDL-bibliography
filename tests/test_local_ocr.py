from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from local_library import find_candidates, index_library
from local_ocr import index_failed_pdfs

PROFILE = {"ocr_policy": 1, "pages": 3, "tools": {"tesseract": "test-v1"}}


def no_text(path):
    raise ValueError("No extractable text")


def setup(tmp_path):
    root = tmp_path / "papers"; root.mkdir()
    source = root / "scan.pdf"; source.write_bytes(b"original scan")
    base = tmp_path / "text"; index_library(root, base, extractor=no_text)
    return root, source, base, tmp_path / "ocr"


def test_ocr_cache_tracks_bytes_and_profile_but_reuses_after_rename(tmp_path):
    root, source, base, output = setup(tmp_path)
    calls = []
    def extract(path, profile):
        calls.append((path.name, deepcopy(profile)))
        return [{"page": 1, "text": "Science and Statistics"}]
    original_manifest = (base / "manifest.json").read_bytes()
    first = index_failed_pdfs(base, output, profile=PROFILE, extractor=extract)
    assert first["extractions"] == 1
    assert (base / "manifest.json").read_bytes() == original_manifest
    assert source.read_bytes() == b"original scan"
    source.rename(root / "renamed.pdf"); source = root / "renamed.pdf"
    index_library(root, base, extractor=no_text)
    assert index_failed_pdfs(base, output, profile=PROFILE, extractor=extract)["cache_hits"] == 1
    source.write_bytes(b"modified scan")
    stale = index_failed_pdfs(base, output, profile=PROFILE, extractor=extract)
    assert stale["files"][0]["status"] == "unreadable" and len(calls) == 1
    index_library(root, base, extractor=no_text)
    assert index_failed_pdfs(base, output, profile=PROFILE, extractor=extract)["extractions"] == 1
    updated = dict(PROFILE, tools={"tesseract": "test-v2"})
    assert index_failed_pdfs(base, output, profile=updated, extractor=extract)["extractions"] == 1
    assert len(calls) == 3


def test_ocr_errors_are_cached_and_explicitly_retryable(tmp_path):
    root, source, base, output = setup(tmp_path)
    def fail(path, profile):
        raise ValueError("Unreadable scan")
    first = index_failed_pdfs(base, output, profile=PROFILE, extractor=fail)
    assert first["files"][0]["status"] == "error"
    def good(path, profile):
        return [{"page": 1, "text": "Recovered title"}]
    assert index_failed_pdfs(base, output, profile=PROFILE, extractor=good)["cache_hits"] == 1
    assert index_failed_pdfs(base, output, profile=PROFILE, extractor=good,
                             retry_errors=True)["files"][0]["status"] == "indexed"


def test_concurrent_edit_does_not_cache_text_under_old_hash(tmp_path):
    root, source, base, output = setup(tmp_path)
    def changing(path, profile):
        path.write_bytes(b"different bytes")
        return [{"page": 1, "text": "old text"}]
    result = index_failed_pdfs(base, output, profile=PROFILE, extractor=changing)
    assert result["files"][0]["status"] == "unreadable"
    assert not list((output / "objects").glob("*.json"))


def test_source_and_text_indexes_are_never_ocr_output(tmp_path):
    root, source, base, output = setup(tmp_path)
    for destination in [root, root / "ocr", base]:
        with pytest.raises(ValueError, match="separate"):
            index_failed_pdfs(base, destination, profile=PROFILE)


def test_ocr_reference_and_filename_matches_remain_unverified(tmp_path):
    root, source, base, output = setup(tmp_path)
    index_failed_pdfs(base, output, profile=PROFILE, extractor=lambda p, cfg: [
        {"page": 1, "text": "An unrelated title"},
        {"page": 2, "text": "References: Science and Statistics. 10.1234/other"}])
    entries = {"RenamedKey": {"fingerprint": "entry-bytes", "fields": {
        "title": "Science and Statistics", "doi": "10.1234/other"}}}
    candidate, = find_candidates(output, entries)
    assert candidate["status"] == "candidate_only"
    assert candidate["title_pages"] == candidate["doi_pages"] == [2]
    assert candidate["source"]["verification"] == "unverified"
    assert candidate["source"]["source_kind"] == "ocr"
