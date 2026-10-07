from pathlib import Path
import subprocess
import sys

import pytest

from cdlbib.errors import CdlbibError, WorkspaceNotFound
from cdlbib.workspace import Workspace


def library(tmp_path, name="lib"):
    root = tmp_path / name
    (root / "verification").mkdir(parents=True)
    (root / "cdl.bib").write_text("", encoding="utf-8")
    return root


def test_paths_derive_from_the_root(tmp_path):
    root = library(tmp_path)
    ws = Workspace(root)
    assert ws.bib == root / "cdl.bib"
    assert ws.database == root / ".bibcheck" / "verification.sqlite3"
    assert ws.report == root / ".bibcheck" / "report.jsonl"
    assert ws.baseline == root / "verification" / "baseline.jsonl.gz"
    assert ws.revocations == root / "verification" / "revocations.jsonl"
    assert ws.key_renames == root / "verification" / "key-renames.json"
    assert ws.key_deletions == root / "verification" / "key-deletions.json"


def test_explicit_path_beats_environment_beats_cwd(tmp_path):
    a, b, c = (library(tmp_path, n) for n in "abc")
    env = {"CDLBIB_LIBRARY": str(b)}
    assert Workspace.find(a, environ=env, cwd=c).root == a
    assert Workspace.find(None, environ=env, cwd=c).root == b
    assert Workspace.find(None, environ={}, cwd=c).root == c


def test_walks_up_from_a_subfolder(tmp_path):
    root = library(tmp_path)
    deep = root / "verification" / "x" / "y"
    deep.mkdir(parents=True)
    assert Workspace.find(None, environ={}, cwd=deep).root == root


def test_not_found_names_the_three_options(tmp_path):
    with pytest.raises(WorkspaceNotFound) as err:
        Workspace.find(None, environ={}, cwd=tmp_path)
    assert isinstance(err.value, CdlbibError)
    for hint in ("--library", "CDLBIB_LIBRARY", "cdl.bib"):
        assert hint in str(err.value)


def test_explicit_path_without_a_library_is_an_error(tmp_path):
    with pytest.raises(WorkspaceNotFound, match="cdl.bib"):
        Workspace.find(tmp_path, environ={}, cwd=tmp_path)


def test_research_bodies_follow_the_environment(tmp_path):
    root = library(tmp_path)
    assert Workspace(root).research_bodies_for({}) == root / ".bibcheck" / "research-pilot"
    assert Workspace(root).research_bodies_for({"BIBCHECK_RESEARCH_BODIES": str(tmp_path / "b")}) == tmp_path / "b"


def test_for_bib_uses_the_files_own_folder(tmp_path):
    other = tmp_path / "paper" / "refs.bib"
    other.parent.mkdir()
    other.write_text("", encoding="utf-8")
    ws = Workspace.for_bib(other)
    assert ws.bib == other.resolve() and ws.database == other.parent.resolve() / ".bibcheck" / "verification.sqlite3"


def test_root_with_spaces_and_non_ascii(tmp_path):
    root = library(tmp_path, "My Papers – bibliothèque")
    assert Workspace.find(None, environ={}, cwd=root).bib.exists()


def test_importing_the_package_needs_no_library(tmp_path):
    code = "import cdlbib.verification, cdlbib.correction_proposals, cdlbib.research_route, cdlbib.research_forms, cdlbib.research_quotes; print('ok')"
    run = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin"})
    assert run.returncode == 0 and run.stdout.strip() == "ok", run.stderr
