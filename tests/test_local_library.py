from pathlib import Path
import sys

import pytest

from cdlbib.local_library import index_library, find_candidates


def test_content_cache_rename_edit_delete(tmp_path):
    root = tmp_path / 'papers'; root.mkdir()
    output = tmp_path / 'index'
    source = root / 'old.pdf'; source.write_bytes(b'original')
    calls = []
    def extract(path):
        calls.append(path)
        return [{'page': 1, 'text': path.read_text()}]
    first = index_library(root, output, extractor=extract)
    source.rename(root / 'new.pdf'); source = root / 'new.pdf'
    second = index_library(root, output, extractor=extract)
    assert second['cache_hits'] == 1 and len(calls) == 1
    assert second['files'][0]['path'] == 'new.pdf'
    assert second['files'][0]['pdf_sha256'] == first['files'][0]['pdf_sha256']
    source.write_bytes(b'changed!')  # Same length still invalidates the text cache.
    third = index_library(root, output, extractor=extract)
    assert third['extractions'] == 1 and len(calls) == 2
    assert third['files'][0]['pdf_sha256'] != first['files'][0]['pdf_sha256']
    source.unlink()
    assert index_library(root, output, extractor=extract)['files'] == []


def test_errors_explicitly_retryable(tmp_path):
    root = tmp_path / 'papers'; root.mkdir(); (root / 'scan.pdf').write_bytes(b'scan')
    def failed(path):
        raise ValueError('No text')
    first = index_library(root, tmp_path / 'index', extractor=failed)
    assert first['files'][0]['status'] == 'error'
    def good(path):
        return [{'page': 1, 'text': 'OCR evidence'}]
    repeat = index_library(root, tmp_path / 'index', extractor=good)
    assert repeat['cache_hits'] == 1 and repeat['files'][0]['status'] == 'error'
    retried = index_library(root, tmp_path / 'index', extractor=good, retry_errors=True)
    assert retried['extractions'] == 1 and retried['files'][0]['status'] == 'indexed'


def test_concurrent_source_edit_never_saves_misattributed_text(tmp_path):
    root = tmp_path / 'papers'; root.mkdir(); source = root / 'x.pdf'; source.write_bytes(b'old')
    def changing(path):
        path.write_bytes(b'new')
        return [{'page': 1, 'text': 'old'}]
    result = index_library(root, tmp_path / 'index', extractor=changing)
    assert result['files'][0]['status'] == 'unreadable'
    assert not list((tmp_path / 'index' / 'objects').glob('*.json'))


def test_output_cannot_modify_paper_library(tmp_path):
    with pytest.raises(ValueError, match='outside'):
        index_library(tmp_path, tmp_path / 'index')


def test_candidate_mentions_do_not_approve_or_require_same_key(tmp_path):
    root = tmp_path / 'papers'; root.mkdir(); (root / 'WrongKey.pdf').write_bytes(b'pdf')
    pages = [{'page': 1, 'text': 'A different paper'},
             {'page': 2, 'text': 'References: Science and Statistics. 10.1234/example'}]
    index_library(root, tmp_path / 'index', extractor=lambda p: pages)
    entries = {'NewKey': {'fingerprint': 'current-content', 'fields': {
        'title': 'Science and Statistics', 'doi': '10.1234/example'}},
        'WrongKey': {'fingerprint': 'other-content', 'fields': {'title': 'Unrelated work title'}}}
    candidates = {r['key']: r for r in find_candidates(tmp_path / 'index', entries)}
    assert candidates['NewKey']['title_pages'] == [2]
    assert candidates['NewKey']['doi_pages'] == [2]
    assert not candidates['NewKey']['filename_match']
    assert candidates['NewKey']['fingerprint'] == 'current-content'
    assert candidates['WrongKey']['title_pages'] == []
    assert all(r['status'] == 'candidate_only' for r in candidates.values())
