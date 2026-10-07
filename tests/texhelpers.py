"""Shared by the TeX-link, export and setup tests: small libraries of fixture entries, real
manuscripts, real TeX runs, and the check that nothing of the user's own was touched."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import conftest
from cdlbib import workspace
from cdlbib.workspace import Workspace

ZOLL90 = conftest.ZOLL90
# Entries that exist only for these tests, in the house format. FIXTB keeps TeX accents and a
# non-ASCII letter, so that "byte for byte" is tested on more than ASCII.
FIXTA = ("@article{FixtA21,\n\tAuthor = {A Fixture and B Sample},\n\tJournal = {Journal of Test Fixtures},\n"
         "\tNumber = {1},\n\tPages = {1--10},\n\tTitle = {A first entry that exists only for the tests},\n"
         "\tVolume = {3},\n\tYear = {2021}}")
FIXTB = ("@article{FixtB22,\n\tAuthor = {C G{\\\"o}del and D Na{\\\"\\i}ve and E Çelik},\n"
         "\tJournal = {Journal of Test Fixtures},\n\tNumber = {2},\n\tPages = {11--20},\n"
         "\tTitle = {A second entry, with {B}races and 100\\% of its bytes},\n\tVolume = {4},\n\tYear = {2022}}")
FIXTC = ("@article{FixtC23,\n\tAuthor = {F Third},\n\tJournal = {Journal of Test Fixtures},\n\tNumber = {3},\n"
         "\tPages = {21--30},\n\tTitle = {A third entry that no fixture paper cites},\n\tVolume = {5},\n\tYear = {2023}}")
LIBRARY = "\n\n".join((ZOLL90, FIXTA, FIXTB, FIXTC)) + "\n"

REAL_HOME = Path.home()                      # read at import, before any test substitutes HOME
TEX_VARIABLES = ("BIBINPUTS", "BSTINPUTS", "TEXINPUTS")
FLAGS = ("-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error")


def need(*programs):
    """Skip, naming the program, when a TeX tool these tests run for real is not installed."""
    for program in programs:
        if not shutil.which(program):
            pytest.skip(f"{program} is not installed (these tests run the real program)")


def make_library(folder, text=LIBRARY):
    folder = Path(folder)
    (folder / "verification").mkdir(parents=True)
    (folder / "cdl.bib").write_text(text, encoding="utf-8")
    return Workspace(folder)


def _own(path):
    """What is at a path of the user's own that this code could write: its link target or bytes."""
    if os.path.islink(path):
        return "link:" + os.readlink(path)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if os.path.isfile(path) else None


def users_own():
    """The real data folder's link record and the real TeX-tree link paths, as they are now."""
    places = [conftest._REAL_DATA_FOLDER / "tex-link.json", REAL_HOME / "Library/texmf/bibtex/bib/cdl.bib",
              REAL_HOME / "texmf/bibtex/bib/cdl.bib"]
    return {str(place): _own(place) for place in places}


@pytest.fixture(autouse=True, scope="module")
def nothing_of_the_users_touched():
    before = users_own()
    yield
    assert users_own() == before, "a test changed the user's own TeX link or its record"
    conftest.no_real_library_touched()


@pytest.fixture
def texenv(tmp_path, monkeypatch):
    """HOME, TEXMFHOME and cdlbib's data folder in tmp_path; no TeX search-path variables; no
    library chosen. Gives (home, texmf, data)."""
    home, texmf, data = tmp_path / "home", tmp_path / "tex tree", tmp_path / "données cdlbib"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TEXMFHOME", str(texmf))
    monkeypatch.setenv("CDLBIB_HOME", str(data))
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(conftest.build_upstream(tmp_path / "up")))
    monkeypatch.delenv("CDLBIB_LIBRARY", raising=False)
    for name in TEX_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    if sys.platform == "darwin":
        monkeypatch.setenv("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")
    workspace.select_library(None)
    yield home, texmf, data
    workspace.select_library(None)


def paper(folder, body, preamble="", name="main.tex", documentclass="\\documentclass{article}"):
    """A real manuscript: <folder>/<name> with the given preamble and body."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / name
    file.write_text(f"{documentclass}\n{preamble}\n\\begin{{document}}\n{body}\n\\end{{document}}\n", encoding="utf-8")
    return file


def run(program, *args, cwd):
    return subprocess.run([program, *args], cwd=cwd, capture_output=True, text=True, errors="replace")


def bibtex_bbl(file):
    """Compile the manuscript where it is with the real pdflatex and bibtex; (the .bbl text, bibtex's log)."""
    latex = run("pdflatex", *FLAGS, "-draftmode", file.name, cwd=file.parent)
    assert latex.returncode == 0, latex.stdout[-2000:]
    done = run("bibtex", file.stem, cwd=file.parent)
    bbl = file.with_suffix(".bbl")
    return (bbl.read_text(encoding="utf-8") if bbl.exists() else ""), done.stdout


def biber_bbl(file):
    """The same with biber; (the .bbl text, biber's output)."""
    latex = run("pdflatex", *FLAGS, "-draftmode", file.name, cwd=file.parent)
    assert latex.returncode == 0, latex.stdout[-2000:]
    done = run("biber", file.stem, cwd=file.parent)
    bbl = file.with_suffix(".bbl")
    return (bbl.read_text(encoding="utf-8") if bbl.exists() else ""), done.stdout


def advance(upstream, message, **files):
    """A new commit on the local upstream's master holding the given files."""
    work = Path(upstream).parent / "upstream-work"
    for name, text in files.items():
        (work / name).write_text(text, encoding="utf-8")
        conftest._git("add", name, cwd=work)
    conftest._git("commit", "--quiet", "-m", message, cwd=work)
    conftest._git("push", "--quiet", str(upstream), "master", cwd=work)
