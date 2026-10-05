"""The TeX-tree link: real kpsewhich, pdflatex, bibtex, biber and mktexlsr against a TEXMFHOME,
a HOME and a cdlbib data folder that belong to the test. Nothing is replaced by a stand-in."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from cdlbib import api, library, tex, workspace
from cdlbib.errors import TexLinkRefused
from texhelpers import (FIXTA, ZOLL90, advance, biber_bbl, bibtex_bbl, make_library, need,
                        nothing_of_the_users_touched, paper, texenv)   # noqa: F401  (fixtures)

BIBTEX_BODY = "Cited: \\cite{Zoll90}.\n\\bibliographystyle{plain}\n\\bibliography{cdl}"
BIBER_PREAMBLE = "\\usepackage[backend=biber]{biblatex}\n\\addbibresource{cdl.bib}"
BIBER_BODY = "Cited: \\cite{Zoll90}.\n\\printbibliography"


@pytest.fixture
def ws(tmp_path, texenv):
    return make_library(tmp_path / "my library")


def test_before_linking_nothing_is_there_and_tex_finds_nothing(ws, texenv):
    need("kpsewhich")
    _, texmf, data = texenv
    found = tex.status(ws)
    assert found.state == found.present == "absent" and found.resolves_to is None and found.target is None
    assert found.texmf_home == texmf and found.link == texmf / "bibtex" / "bib" / "cdl.bib"
    assert found.kpsewhich == shutil.which("kpsewhich") and found.changes == []
    assert not texmf.exists() and not data.exists()          # looking creates nothing


def test_a_manuscript_outside_the_library_resolves_it_with_bibtex_and_biber(ws, texenv, tmp_path):
    need("kpsewhich", "pdflatex", "bibtex", "biber")
    _, texmf, _ = texenv
    done = tex.link(ws)
    link = texmf / "bibtex" / "bib" / "cdl.bib"
    assert done.state == "linked" and done.resolves_to == link and done.target == ws.bib
    assert link.is_symlink() and os.readlink(link) == str(ws.bib)
    assert done.changes == [f"linked {link} -> {ws.bib}"]

    bbl, log = bibtex_bbl(paper(tmp_path / "paper one", BIBTEX_BODY))
    assert "Database file #1: cdl.bib" in log and "\\bibitem{Zoll90}" in bbl and "Zoller" in bbl
    assert not (tmp_path / "paper one" / "cdl.bib").exists()

    bbl, log = biber_bbl(paper(tmp_path / "paper two", BIBER_BODY, BIBER_PREAMBLE))
    assert f"Found BibTeX data source '{link}'" in log and "\\entry{Zoll90}{article}" in bbl

    again = tex.link(ws)                                      # already linked: nothing to do
    assert again.state == "linked" and again.changes == []


def test_the_link_follows_a_real_update_of_the_managed_library(texenv, tmp_path, monkeypatch):
    need("kpsewhich", "pdflatex", "bibtex", "biber")
    _, texmf, data = texenv
    upstream = os.environ["CDLBIB_UPSTREAM"]
    monkeypatch.chdir(tmp_path)
    managed = workspace.resolve(managed=True)
    assert managed.root == (data / "library").resolve() and api.is_managed(managed)
    assert tex.link(managed).state == "linked"
    body = "Cited: \\cite{Zoll90} and \\cite{FixtA21}.\n"
    before, log = bibtex_bbl(paper(tmp_path / "paper", body + "\\bibliographystyle{plain}\n\\bibliography{cdl}"))
    assert "\\bibitem{Zoll90}" in before and "FixtA21" not in before
    assert "I didn't find a database entry for \"FixtA21\"" in log

    advance(upstream, "Add an entry", **{"cdl.bib": ZOLL90 + "\n\n" + FIXTA + "\n"})
    assert api.update(force=True).action == "updated"

    found = tex.status(managed)                               # nothing was linked again
    assert found.state == "linked" and found.resolves_to == texmf / "bibtex" / "bib" / "cdl.bib"
    after, log = bibtex_bbl(tmp_path / "paper" / "main.tex")
    assert "\\bibitem{Zoll90}" in after and "\\bibitem{FixtA21}" in after and "didn't find" not in log
    bbl, log = biber_bbl(paper(tmp_path / "paper b", body + "\\printbibliography", BIBER_PREAMBLE))
    assert "\\entry{FixtA21}{article}" in bbl and "\\entry{Zoll90}{article}" in bbl


def test_a_file_cdlbib_did_not_make_is_never_removed(ws, texenv):
    need("kpsewhich")
    _, texmf, _ = texenv
    link = texmf / "bibtex" / "bib" / "cdl.bib"
    link.parent.mkdir(parents=True)
    link.write_text("@misc{Mine, title = {my own file}}\n", encoding="utf-8")
    found = tex.status(ws)
    assert found.state == found.present == "foreign" and found.target is None and found.resolves_to == link

    with pytest.raises(TexLinkRefused) as refused:
        tex.link(ws)
    assert str(link) in str(refused.value) and refused.value.status.state == "foreign"
    assert link.read_text(encoding="utf-8") == "@misc{Mine, title = {my own file}}\n" and not link.is_symlink()
    assert tex.unlink().removed is False and link.is_file()

    done = tex.link(ws, replace=True)
    saved = [item for item in link.parent.iterdir() if item.name.startswith(tex.SAVED)]
    assert len(saved) == 1 and saved[0].read_text(encoding="utf-8") == "@misc{Mine, title = {my own file}}\n"
    assert done.state == "linked" and done.changes[0] == f"moved the existing {link} aside to {saved[0]}"
    assert os.readlink(link) == str(ws.bib)

    gone = tex.unlink()                                       # our link goes; the saved file stays
    assert gone.removed and gone.link == link and not os.path.lexists(link) and saved[0].is_file()
    assert tex.unlink().removed is False


def test_a_link_someone_else_made_is_foreign_even_when_it_names_a_library(ws, texenv, tmp_path):
    need("kpsewhich")
    _, texmf, _ = texenv
    link = texmf / "bibtex" / "bib" / "cdl.bib"
    link.parent.mkdir(parents=True)
    os.symlink(str(ws.bib), link)                             # the same link, but no record of ours
    found = tex.status(ws)
    assert found.state == "foreign" and found.target == ws.bib
    assert tex.unlink().removed is False and link.is_symlink()
    with pytest.raises(TexLinkRefused):
        tex.link(ws)
    done = tex.link(ws, replace=True)
    saved = [item for item in link.parent.iterdir() if item.name.startswith(tex.SAVED)]
    assert done.state == "linked" and len(saved) == 1 and os.readlink(saved[0]) == str(ws.bib)


def test_ownership_is_what_the_record_in_the_data_folder_says(ws, texenv):
    need("kpsewhich")
    _, texmf, data = texenv
    tex.link(ws)
    link = texmf / "bibtex" / "bib" / "cdl.bib"
    record = json.loads((data / "tex-link.json").read_text(encoding="utf-8"))
    assert record["link"] == str(link) and record["target"] == str(ws.bib) and record["linked_at"].endswith("+00:00")
    assert sorted(item.name for item in data.iterdir()) == ["tex-link.json"]

    (data / "tex-link.json").write_text(json.dumps(dict(record, target=str(ws.bib) + ".other")), encoding="utf-8")
    assert tex.status(ws).state == "foreign"                  # the record names another target
    (data / "tex-link.json").write_text(json.dumps(dict(record, link=str(link) + ".other")), encoding="utf-8")
    assert tex.status(ws).state == "foreign"                  # the record names another path
    (data / "tex-link.json").write_text("not json", encoding="utf-8")
    assert tex.status(ws).state == "foreign"
    (data / "tex-link.json").unlink()
    assert tex.status(ws).state == "foreign" and tex.unlink().removed is False and link.is_symlink()

    (data / "tex-link.json").write_text(json.dumps(record), encoding="utf-8")
    assert tex.status(ws).state == "linked"
    assert tex.unlink().removed and not (data / "tex-link.json").exists()


def test_a_link_to_another_library_is_reported_and_then_pointed_at_this_one(ws, texenv, tmp_path):
    need("kpsewhich")
    _, texmf, data = texenv
    other = make_library(tmp_path / "other library", FIXTA + "\n")
    tex.link(other)
    link = texmf / "bibtex" / "bib" / "cdl.bib"
    found = tex.status(ws)
    assert found.state == found.present == "other_library" and found.target == other.bib and found.resolves_to == link

    done = tex.link(ws)
    assert done.state == "linked" and done.changes == [f"pointed {link} at {ws.bib} (it named {other.bib})"]
    assert os.readlink(link) == str(ws.bib) and other.bib.read_text(encoding="utf-8") == FIXTA + "\n"
    assert json.loads((data / "tex-link.json").read_text(encoding="utf-8"))["target"] == str(ws.bib)
    assert [item.name for item in link.parent.iterdir()] == ["cdl.bib"]

    shutil.rmtree(ws.root)                                    # the library the link names goes away
    gone = tex.status(other)
    assert gone.state == "other_library" and any("no longer there" in note for note in gone.notes)


def test_a_bibinputs_that_shadows_the_link_is_detected_and_is_what_bibtex_really_uses(ws, texenv, tmp_path, monkeypatch):
    need("kpsewhich", "pdflatex", "bibtex", "biber")
    tex.link(ws)
    old = tmp_path / "old copies"
    old.mkdir()
    (old / "cdl.bib").write_text(FIXTA + "\n", encoding="utf-8")
    monkeypatch.setenv("BIBINPUTS", f"{old}{os.pathsep}")
    found = tex.status(ws)
    assert found.state == "shadowed" and found.present == "linked" and found.resolves_to == old / "cdl.bib"
    assert any("BIBINPUTS" in note and str(old / "cdl.bib") in note for note in found.notes)
    bbl, log = bibtex_bbl(paper(tmp_path / "paper", BIBTEX_BODY))          # the real programs agree with the report
    assert "\\bibitem{Zoll90}" not in bbl and "I didn't find a database entry for \"Zoll90\"" in log
    bbl, log = biber_bbl(paper(tmp_path / "paper b", BIBER_BODY, BIBER_PREAMBLE))
    assert f"Found BibTeX data source '{old / 'cdl.bib'}'" in log and "\\entry{Zoll90}" not in bbl

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("BIBINPUTS", str(empty))               # no empty component: the TeX trees are not searched
    found = tex.status(ws)
    assert found.state == "shadowed" and found.resolves_to is None
    assert any("BIBINPUTS" in note and "no empty component" in note for note in found.notes)

    monkeypatch.setenv("BIBINPUTS", f"{ws.root}{os.pathsep}")              # another way to the same file is not a shadow
    found = tex.status(ws)
    assert found.state == "linked" and found.resolves_to == ws.bib
    assert any("this library's file" in note for note in found.notes)

    monkeypatch.delenv("BIBINPUTS")
    assert tex.status(ws).state == "linked" and tex.status(ws).notes == []


def test_a_tree_with_a_file_name_database_has_it_refreshed(ws, texenv):
    need("kpsewhich", "mktexlsr")
    _, texmf, _ = texenv
    (texmf / "bibtex" / "bib").mkdir(parents=True)
    made = subprocess.run(["mktexlsr", str(texmf)], capture_output=True, text=True)
    assert made.returncode == 0 and "cdl.bib" not in (texmf / "ls-R").read_text()        # a database that predates the link
    done = tex.link(ws)
    assert done.state == "linked" and f"refreshed the file-name database of {texmf} (mktexlsr)" in done.changes
    assert "cdl.bib" in (texmf / "ls-R").read_text()
    gone = tex.unlink()
    assert gone.removed and "cdl.bib" not in (texmf / "ls-R").read_text()
    assert tex.status(ws).state == "absent" and tex.status(ws).resolves_to is None


def test_a_tree_without_a_file_name_database_gets_none(ws, texenv):
    need("kpsewhich")
    _, texmf, _ = texenv
    done = tex.link(ws)
    assert done.state == "linked" and len(done.changes) == 1 and not (texmf / "ls-R").exists()


def test_the_first_folder_of_texmfhome_is_used_and_the_others_are_reported(ws, texenv, tmp_path, monkeypatch):
    need("kpsewhich")
    first, second = tmp_path / "tree-one", tmp_path / "tree-two"
    second.mkdir()                                            # only the second exists: the first is still the one used
    monkeypatch.setenv("TEXMFHOME", "{" + f"{first},{second}" + "}")
    found = tex.status(ws)
    assert found.texmf_home == first and found.other_trees == [second]
    assert any(str(second) in note and "the first is used" in note for note in found.notes)
    done = tex.link(ws)
    assert done.state == "linked" and done.resolves_to == first / "bibtex" / "bib" / "cdl.bib"


def test_without_tex_the_link_is_made_in_the_default_tree(ws, texenv, tmp_path, monkeypatch):
    home, texmf, _ = texenv
    path = os.environ["PATH"]
    nothing = tmp_path / "no programs"
    nothing.mkdir()
    monkeypatch.setenv("PATH", str(nothing))
    assert shutil.which("kpsewhich") is None
    found = tex.status(ws)
    assert found.state == "no_tex" and found.present == "absent" and found.kpsewhich is None
    assert found.texmf_home == texmf and any("TeX was not found" in note for note in found.notes)

    monkeypatch.delenv("TEXMFHOME")
    default = home / "Library" / "texmf" if sys.platform == "darwin" else home / "texmf"
    assert tex.status(ws).texmf_home == default
    done = tex.link(ws)
    link = default / "bibtex" / "bib" / "cdl.bib"
    assert done.state == "no_tex" and done.present == "linked" and os.readlink(link) == str(ws.bib)
    assert done.changes == [f"linked {link} -> {ws.bib}"]

    if not shutil.which("kpsewhich", path=path):
        pytest.skip("kpsewhich is not installed: the part with TeX installed afterwards is not run")
    monkeypatch.setenv("PATH", path)                          # TeX is installed afterwards; its tree may be another one
    later = tmp_path / "later tree"
    monkeypatch.setenv("TEXMFHOME", str(later))
    assert tex.status(ws).state == "absent"
    moved = tex.link(ws)
    assert moved.state == "linked" and not os.path.lexists(link)
    assert moved.changes == [f"removed the earlier link {link} (the TeX tree is now {later})",
                             f"linked {later / 'bibtex' / 'bib' / 'cdl.bib'} -> {ws.bib}"]


def test_the_bibinputs_line_works_in_a_real_shell_and_is_written_nowhere(texenv, tmp_path):
    need("kpsewhich")
    home, texmf, _ = texenv
    ws = make_library(tmp_path / 'lib with "quotes" $and spaces')
    line = tex.bibinputs_line(ws)
    assert line.startswith('export BIBINPUTS="') and line.endswith(':${BIBINPUTS}"')
    empty = tmp_path / "empty"
    empty.mkdir()
    shown = subprocess.run(["sh", "-c", line + "; kpsewhich cdl.bib; kpsewhich plain.bst"], cwd=empty,
                           capture_output=True, text=True)
    found = shown.stdout.splitlines()
    assert found[0] == str(ws.bib) and found[1].endswith("plain.bst"), shown.stdout + shown.stderr    # the default path is kept
    assert tex.status(ws).bibinputs_line == line and tex.status(ws).state == "absent"
    assert list(home.iterdir()) == [] and not texmf.exists()


def test_the_api_passes_the_link_through(ws, texenv):
    need("kpsewhich")
    assert api.tex_link(ws).state == "linked"
    report = api.setup_report(ws)
    assert report.tex.state == "linked" and report.where.root == ws.root
    assert api.tex_unlink().removed and tex.status(ws).state == "absent"
    assert library.home() == texenv[2]
