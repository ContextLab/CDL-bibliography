"""Outside a library, with no body-cache override, the research validators treat the
saved-bodies directory as absent (no WorkspaceNotFound escapes)."""
import gzip
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from cdlbib import research_route as R
from cdlbib import verification as v

FIX = Path(__file__).resolve().parents[1] / 'tests/fixtures/research_approvals'
ROWS = [json.loads(line) for line in gzip.open(FIX / 'rows.jsonl.gz', 'rt', encoding='utf-8')]


@pytest.fixture
def no_library(monkeypatch, tmp_path):
    monkeypatch.delenv('BIBCHECK_RESEARCH_BODIES', raising=False)
    monkeypatch.delenv('CDLBIB_LIBRARY', raising=False)
    monkeypatch.setattr(R, 'BODY_DIR', None)
    elsewhere = tmp_path / 'not a library'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return elsewhere


def test_body_dir_is_none_outside_a_library(no_library):
    assert R.body_dir() is None and not R.body_dir_exists()


def test_validators_do_not_raise_without_a_library(no_library):
    for row in ROWS:
        result = deepcopy(row)
        assert R.valid_research_approval(result)
        assert v.route_approval_valid(result)
        assert R.research_rejection_reason(result) is None


def test_a_broken_record_is_still_rejected_without_a_library(no_library):
    result = deepcopy(ROWS[0])
    result['accepted_record_id'] = 'not-the-saved-id'
    assert not R.valid_research_approval(result)
    assert R.research_rejection_reason(result)


def test_environment_variable_still_wins(monkeypatch, no_library, tmp_path):
    monkeypatch.setenv('BIBCHECK_RESEARCH_BODIES', str(tmp_path / 'b'))
    assert R.body_dir() == tmp_path / 'b'
    monkeypatch.setattr(R, 'BODY_DIR', tmp_path / 'patched')
    assert R.body_dir() == tmp_path / 'patched'
