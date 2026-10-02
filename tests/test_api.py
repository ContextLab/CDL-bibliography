"""cdlbib.api: the front-end boundary. It returns dataclasses and never prints.

Real .bib files in tmp_path; the citation tests make real Crossref requests into a fresh
cache beside the file. The entries are the frozen Rame72/Zoll90 pair of
tests/test_machinery_2026_09_25.py section 16 (imported, not retyped). No mocks.
"""
import io
import contextlib

from cdlbib import api
from cdlbib.workspace import Workspace

from test_machinery_2026_09_25 import RAME72, ZOLL90, crossref_contact


def bib(tmp_path, text, name="lib.bib"):
    path = tmp_path / name
    path.write_text(text + "\n", encoding="utf-8")
    return Workspace.for_bib(path)


def silent(call):
    """api must not print: run the call with stdout/stderr captured and assert both empty."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = call()
    assert out.getvalue() == "" and err.getvalue() == ""
    return result


def test_check_format_clean_entry(tmp_path):
    result = silent(lambda: api.check_format(bib(tmp_path, ZOLL90)))
    assert result.ok and result.errors == []


def test_check_format_reports_errors_without_raising(tmp_path):
    bad = ZOLL90.replace("1053--1065", "1053--10")
    result = silent(lambda: api.check_format(bib(tmp_path, bad)))
    assert not result.ok and any("Zoll90" in str(e) for e in result.errors)


def test_check_library_format_only(tmp_path):
    check = silent(lambda: api.check_library(bib(tmp_path, ZOLL90), citations=False))
    assert check.ok and check.citations is None


def test_check_library_format_failure_skips_citations(tmp_path):
    bad = ZOLL90.replace("1053--1065", "1053--10")
    check = silent(lambda: api.check_library(bib(tmp_path, bad), citations=True))
    assert not check.ok and check.citations is None


def test_check_library_verifies_a_new_entry_against_a_base(tmp_path):
    base = tmp_path / "base.bib"
    base.write_text(ZOLL90 + "\n", encoding="utf-8")
    ws = bib(tmp_path, ZOLL90 + "\n\n" + RAME72 % "1")
    seen = []
    check = silent(lambda: api.check_library(ws, reference=str(base), mailto=crossref_contact(),
                                             progress=seen.append))
    assert check.ok and check.citations.unresolved == {}
    assert any(line.startswith("citations: 1 of 1") for line in check.citations.lines) and seen == check.citations.lines


def test_check_library_wrong_volume_is_unresolved(tmp_path):
    base = tmp_path / "base.bib"
    base.write_text(ZOLL90 + "\n", encoding="utf-8")
    ws = bib(tmp_path, ZOLL90 + "\n\n" + RAME72 % "2")  # Crossref: volume 1
    check = silent(lambda: api.check_library(ws, reference=str(base), mailto=crossref_contact()))
    assert not check.ok and "Rame72" in check.citations.unresolved


def test_compare(tmp_path):
    a = tmp_path / "a.bib"; a.write_text(ZOLL90 + "\n", encoding="utf-8")
    b = tmp_path / "b.bib"; b.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n", encoding="utf-8")
    assert silent(lambda: api.compare(str(a), str(a))).match
    assert not silent(lambda: api.compare(str(a), str(b))).match


def test_status_counts_an_unverified_library(tmp_path):
    result = silent(lambda: api.status(bib(tmp_path, ZOLL90)))
    assert sum(result.counts.values()) == 1 and not result.ok
