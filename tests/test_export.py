"""Per-paper export: which keys a real manuscript cites, the frozen .bib, and the .bbl compiled
by the real pdflatex, bibtex and biber. Libraries are small fixture files; never the live cdl.bib."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from cdlbib import export, verification
from cdlbib.errors import ExportFailed
from texhelpers import (FIXTA, FIXTB, FIXTC, FLAGS, LIBRARY, ZOLL90, make_library, need,
                        nothing_of_the_users_touched, paper, run, texenv)   # noqa: F401  (fixtures)

PLAIN = "\\bibliographystyle{plain}\n\\bibliography{cdl}"
BIBLATEX = "\\usepackage[backend=biber]{biblatex}\n\\addbibresource{cdl.bib}"


@pytest.fixture
def ws(tmp_path, texenv):
    return make_library(tmp_path / "library")


def raws(path):
    return {key: entry["raw"] for key, entry in verification.load_entries(path).items()}


def names(folder):
    return sorted(item.name for item in Path(folder).iterdir())


# --- bibtex -------------------------------------------------------------------------------

def test_bibtex_paper_cited_keys_frozen_bib_and_bbl(ws, tmp_path):
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "B \\cite{FixtB22}, then Z \\cite{Zoll90,FixtB22}.\n" + PLAIN)
    found = export.cited(file)
    assert found.keys == ["FixtB22", "Zoll90"] and not found.all_entries          # in the order first cited
    assert (found.how, found.backend, found.style, found.bibdata, found.engine) == ("compiled", "bibtex", "plain", ["cdl"], "pdflatex")
    assert found.main == file.resolve() and found.notes == []

    made = export.frozen_bib(ws, found, tmp_path / "paper" / "cited.bib")
    assert made.written == ["Zoll90", "FixtB22"] and made.missing == [] and made.parents == []      # library order
    assert made.path.read_bytes() == (ZOLL90 + "\n\n" + FIXTB + "\n").encode("utf-8")
    assert raws(made.path) == {"Zoll90": ZOLL90, "FixtB22": FIXTB}

    done = export.bbl(ws, file)
    assert done.path == (tmp_path / "paper" / "main.bbl").resolve() and (done.backend, done.engine, done.style) == ("bibtex", "pdflatex", "plain")
    text = done.path.read_text(encoding="utf-8")
    assert "\\bibitem{Zoll90}" in text and "\\bibitem{FixtB22}" in text and "FixtA21" not in text and "G{\\\"o}del" in text
    assert names(tmp_path / "paper") == ["cited.bib", "main.bbl", "main.tex"]     # the compile left nothing else here
    assert ws.bib.read_text(encoding="utf-8") == LIBRARY


def test_the_frozen_file_alone_compiles_the_paper_as_the_library_does(ws, tmp_path):
    """The frozen file is enough: with no link and no library on any search path, real bibtex
    makes the same .bbl from it as the export made from the library."""
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{FixtA21} \\cite{FixtB22}\n" + PLAIN)
    from_library = export.bbl(ws, file).path.read_text(encoding="utf-8")
    (tmp_path / "paper" / "main.bbl").unlink()
    export.frozen_bib(ws, export.cited(file), tmp_path / "paper" / "cdl.bib")
    assert run("pdflatex", *FLAGS, "-draftmode", "main.tex", cwd=file.parent).returncode == 0
    assert run("bibtex", "main", cwd=file.parent).returncode == 0
    assert (tmp_path / "paper" / "main.bbl").read_text(encoding="utf-8") == from_library


def test_natbib_commands_and_style(ws, tmp_path):
    need("pdflatex", "bibtex")
    body = ("As \\citet{Zoll90} say \\citep[see][p.~3]{FixtA21, FixtB22}; \\citeauthor*{Zoll90} \\citeyearpar{FixtA21}.\n"
            "\\bibliographystyle{plainnat}\n\\bibliography{cdl}")
    file = paper(tmp_path / "paper", body, "\\usepackage{natbib}")
    for found in (export.cited(file), export._from_source(file, file.parent)):
        assert found.keys == ["Zoll90", "FixtA21", "FixtB22"] and (found.backend, found.style) == ("bibtex", "plainnat")
    text = export.bbl(ws, file).path.read_text(encoding="utf-8")
    assert "\\bibitem[Zoller(1990)]{Zoll90}" in text and "\\bibitem[Fixture and Sample(2021)]{FixtA21}" in text


# --- biblatex and biber -------------------------------------------------------------------

def test_biblatex_paper_with_biber(ws, tmp_path):
    need("pdflatex", "biber")
    body = "\\parencite[12]{Zoll90} \\textcite{FixtB22} \\cites{FixtA21}[5]{Zoll90} \\autocite{FixtA21}\n\\printbibliography"
    file = paper(tmp_path / "paper", body, BIBLATEX)
    found = export.cited(file)
    assert found.keys == ["Zoll90", "FixtB22", "FixtA21"] and (found.how, found.backend, found.style) == ("compiled", "biber", None)
    assert found.bibdata == ["cdl"]
    assert export._from_source(file, file.parent).keys == found.keys and export._from_source(file, file.parent).backend == "biber"
    done = export.bbl(ws, file, out=tmp_path / "out.bbl")
    text = done.path.read_text(encoding="utf-8")
    assert done.backend == "biber" and all(f"\\entry{{{key}}}{{article}}" in text for key in found.keys)
    assert "FixtC23" not in text and names(tmp_path / "paper") == ["main.tex"]

    frozen = export.frozen_bib(ws, found, tmp_path / "frozen.bib")
    assert raws(frozen.path) == {"Zoll90": ZOLL90, "FixtA21": FIXTA, "FixtB22": FIXTB}


def test_biblatex_with_the_bibtex_backend(ws, tmp_path):
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{FixtA21}\n\\printbibliography",
                 "\\usepackage[backend=bibtex]{biblatex}\n\\addbibresource{cdl.bib}")
    found = export.cited(file)
    assert found.keys == ["FixtA21"] and found.backend == "bibtex" and found.bibdata == ["cdl"]
    assert "\\entry{FixtA21}{article}" in export.bbl(ws, file).path.read_text(encoding="utf-8")


# --- several files, \nocite{*} ------------------------------------------------------------

def test_citations_in_input_and_included_files(ws, tmp_path, monkeypatch):
    need("pdflatex", "bibtex")
    folder = tmp_path / "paper"
    paper(folder, "\\cite{Zoll90}\n\\input{sections/intro}\n\\include{methods}\n% \\cite{Commented99}\n" + PLAIN)
    (folder / "sections").mkdir()
    (folder / "sections" / "intro.tex").write_text("Intro \\cite{FixtA21}. 100\\% \\cite{FixtB22} % \\cite{Hidden00}\n", encoding="utf-8")
    (folder / "methods.tex").write_text("Methods \\cite{FixtC23}.\n", encoding="utf-8")
    found = export.cited(folder)                                               # the folder: its one main file is found
    assert found.how == "compiled" and found.keys == ["Zoll90", "FixtA21", "FixtB22", "FixtC23"]
    assert [path.name for path in found.sources] == ["main.tex", "intro.tex", "methods.tex"]
    text = export.bbl(ws, folder).path.read_text(encoding="utf-8")
    assert all(f"\\bibitem{{{key}}}" in text for key in found.keys)

    monkeypatch.setenv("PATH", str(tmp_path))                                  # no TeX: the same from the source
    parsed = export.cited(folder)
    assert parsed.how == "source" and parsed.keys == found.keys


def test_nocite_star_exports_every_entry(ws, tmp_path):
    need("pdflatex", "bibtex", "biber")
    file = paper(tmp_path / "paper", "\\cite{FixtA21}\\nocite{*}\n" + PLAIN)
    found = export.cited(file)
    assert found.all_entries and found.keys == ["FixtA21"]
    made = export.frozen_bib(ws, found, tmp_path / "all.bib")
    assert made.written == ["Zoll90", "FixtA21", "FixtB22", "FixtC23"] and made.path.read_bytes() == LIBRARY.encode("utf-8")
    text = export.bbl(ws, file).path.read_text(encoding="utf-8")
    assert all(f"\\bibitem{{{key}}}" in text for key in made.written)

    other = paper(tmp_path / "paper b", "\\nocite{*}\n\\printbibliography", BIBLATEX)
    found = export.cited(other)
    assert found.all_entries and found.keys == [] and found.backend == "biber"
    assert export._from_source(other, other.parent).all_entries
    text = export.bbl(ws, other).path.read_text(encoding="utf-8")
    assert all(f"\\entry{{{key}}}{{article}}" in text for key in made.written)


# --- keys the library does not have -------------------------------------------------------

def test_a_missing_key_is_listed_and_fails_the_bbl(ws, tmp_path):
    need("pdflatex", "bibtex", "biber")
    file = paper(tmp_path / "paper", "\\cite{Zoll90} \\cite{Nobody99}\n" + PLAIN)
    made = export.frozen_bib(ws, export.cited(file), tmp_path / "cited.bib")
    assert made.written == ["Zoll90"] and [(item.key, item.renamed_to) for item in made.missing] == [("Nobody99", None)]
    assert raws(made.path) == {"Zoll90": ZOLL90}
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, file)
    assert failed.value.kind == "undefined_keys" and failed.value.names == ["Nobody99"] and "Nobody99" in str(failed.value)
    assert not (tmp_path / "paper" / "main.bbl").exists()

    other = paper(tmp_path / "paper b", "\\cite{Zoll90} \\cite{Nobody99}\n\\printbibliography", BIBLATEX)
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, other)
    assert failed.value.kind == "undefined_keys" and failed.value.names == ["Nobody99"]


def test_a_renamed_key_is_reported_with_the_key_the_library_has_now(ws, tmp_path):
    need("pdflatex", "bibtex")
    ws.key_renames.write_text(json.dumps([
        {"old_key": "Fixt21", "new_key": "FixtureA21", "date": "2026-09-01", "reason": "test", "commit": None},
        {"old_key": "FixtureA21", "new_key": "FixtA21", "date": "2026-09-02", "reason": "test", "commit": None}]), encoding="utf-8")
    file = paper(tmp_path / "paper", "\\cite{Fixt21} \\cite{Zoll90} \\cite{Nobody99}\n" + PLAIN)
    made = export.frozen_bib(ws, export.cited(file), tmp_path / "cited.bib")
    assert [(item.key, item.renamed_to) for item in made.missing] == [("Fixt21", "FixtA21"), ("Nobody99", None)]
    assert [str(item) for item in made.missing] == ["Fixt21 (now FixtA21)", "Nobody99"] and made.written == ["Zoll90"]
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, file)
    assert failed.value.kind == "undefined_keys" and "Fixt21 (now FixtA21)" in str(failed.value)


def test_an_old_copy_of_the_library_in_the_paper_does_not_hide_a_rename(ws, tmp_path):
    need("pdflatex", "bibtex")
    ws.key_renames.write_text(json.dumps([{"old_key": "Fixt21", "new_key": "FixtA21"}]), encoding="utf-8")
    file = paper(tmp_path / "paper", "\\cite{Fixt21}\n" + PLAIN)
    old = FIXTA.replace("FixtA21", "Fixt21") + "\n"
    (tmp_path / "paper" / "cdl.bib").write_text(old, encoding="utf-8")
    made = export.frozen_bib(ws, export.cited(file), tmp_path / "cited.bib")
    assert [str(item) for item in made.missing] == ["Fixt21 (now FixtA21)"]
    done = export.bbl(ws, file)                               # the paper's own cdl.bib is used as it is for the .bbl
    assert "\\bibitem{Fixt21}" in done.path.read_text(encoding="utf-8")
    assert any("cdl.bib in the paper's folder was used as it is" in note for note in done.notes)
    assert (tmp_path / "paper" / "cdl.bib").read_text(encoding="utf-8") == old


# --- inputs the paper needs ---------------------------------------------------------------

def test_a_missing_bst_is_named_and_can_be_supplied(ws, tmp_path):
    need("pdflatex", "bibtex", "kpsewhich")
    file = paper(tmp_path / "paper", "\\cite{Zoll90}\n\\bibliographystyle{labstyle}\n\\bibliography{cdl}")
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, file)
    assert failed.value.kind == "missing_input" and failed.value.names == ["labstyle.bst"] and "labstyle.bst" in str(failed.value)
    assert not (tmp_path / "paper" / "main.bbl").exists()

    plain = subprocess.run(["kpsewhich", "plain.bst"], capture_output=True, text=True).stdout.strip()
    styles = tmp_path / "lab styles" / "deeper"
    styles.mkdir(parents=True)
    shutil.copyfile(plain, styles / "labstyle.bst")
    for given in (tmp_path / "lab styles", styles / "labstyle.bst"):           # a folder holding it, or the file itself
        done = export.bbl(ws, file, inputs=[given], force=True)
        assert done.style == "labstyle" and "\\bibitem{Zoll90}" in done.path.read_text(encoding="utf-8")
    assert names(tmp_path / "paper") == ["main.bbl", "main.tex"]


def test_a_missing_package_or_class_is_named(ws, tmp_path):
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{Zoll90}\n" + PLAIN, "\\usepackage{labmacros}")
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, file)
    assert failed.value.kind == "missing_input" and failed.value.names == ["labmacros.sty"]
    found = export.cited(file)                                # for the citations alone, the source is read instead
    assert found.how == "source" and found.keys == ["Zoll90"] and any(export.SOURCE_NOTE in note for note in found.notes)

    package = tmp_path / "labmacros.sty"
    package.write_text("\\ProvidesPackage{labmacros}\n\\newcommand{\\labcite}[1]{\\cite{#1}}\n", encoding="utf-8")
    assert "\\bibitem{Zoll90}" in export.bbl(ws, file, inputs=[package]).path.read_text(encoding="utf-8")

    other = paper(tmp_path / "paper b", "\\cite{Zoll90}\n" + PLAIN, documentclass="\\documentclass{labjournal}")
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, other)
    assert failed.value.kind == "missing_input" and failed.value.names == ["labjournal.cls"]
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, file, inputs=[tmp_path / "not there"], force=True)
    assert failed.value.kind == "missing_input"


def test_no_bibliographystyle_is_said_and_no_style_is_chosen(ws, tmp_path):
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{Zoll90}\n\\bibliography{cdl}")
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, file)
    assert failed.value.kind == "no_style" and "\\bibliographystyle" in str(failed.value)
    assert names(tmp_path / "paper") == ["main.tex"]
    found = export.cited(file)                                # the frozen .bib needs no style
    assert found.keys == ["Zoll90"] and found.backend is None
    assert export.frozen_bib(ws, found, tmp_path / "cited.bib").written == ["Zoll90"]

    bare = paper(tmp_path / "paper b", "No bibliography at all.")
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, bare)
    assert failed.value.kind == "no_bibliography"


def test_a_bib_file_of_the_papers_own_is_left_alone_and_used(ws, tmp_path):
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{Zoll90} \\cite{Mine24}\n\\bibliographystyle{plain}\n\\bibliography{cdl,extra}")
    mine = "@article{Mine24,\n  author = {A Local},\n  title = {Only in the paper},\n  journal = {J},\n  year = {2024}}\n"
    (tmp_path / "paper" / "extra.bib").write_text(mine, encoding="utf-8")
    found = export.cited(file)
    assert found.bibdata == ["cdl", "extra"]
    made = export.frozen_bib(ws, found, tmp_path / "cited.bib")
    assert made.written == ["Zoll90"] and made.missing == []                  # Mine24 is in the paper's own file
    text = export.bbl(ws, file).path.read_text(encoding="utf-8")
    assert "\\bibitem{Zoll90}" in text and "\\bibitem{Mine24}" in text
    assert (tmp_path / "paper" / "extra.bib").read_text(encoding="utf-8") == mine


# --- hostile input ------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["../x", "../../outside/x.bib", "/tmp/cdlbib-abs/x", "https://example.org/x.bib",
                                  "sub/x", "~/x", "..", ".hidden"])
def test_a_bibliography_name_that_is_not_a_plain_file_name_is_refused_by_name(ws, tmp_path, name):
    need("pdflatex", "bibtex")
    folder = tmp_path / "deep" / "paper"
    for number, (preamble, body) in enumerate([("", f"\\cite{{Zoll90}}\n\\bibliographystyle{{plain}}\n\\bibliography{{cdl,{name}}}"),
                                              (f"\\usepackage{{biblatex}}\n\\addbibresource[location=remote]{{{name}}}",
                                               "\\cite{Zoll90}\n\\printbibliography")]):
        file = paper(folder / str(number), body, preamble)
        for attempt in (lambda: export.cited(file), lambda: export.bbl(ws, file),
                        lambda: export.frozen_bib(ws, export.cited(file), tmp_path / "cited.bib")):
            with pytest.raises(ExportFailed) as failed:
                attempt()
            assert failed.value.kind == "resource_name" and failed.value.names == [name] and name in str(failed.value)
        assert names(file.parent) == ["main.tex"]
    assert names(tmp_path) == sorted(["deep", "library", "home", "up"]) and names(tmp_path / "deep") == ["paper"]
    assert not Path("/tmp/cdlbib-abs").exists()


def test_a_hostile_name_in_an_aux_or_bcf_the_user_names_is_refused(ws, tmp_path):
    aux = tmp_path / "main.aux"
    aux.write_text("\\relax\n\\citation{Zoll90}\n\\bibstyle{plain}\n\\bibdata{cdl,../../x}\n", encoding="utf-8")
    with pytest.raises(ExportFailed) as failed:
        export.cited(aux)
    assert failed.value.kind == "resource_name" and failed.value.names == ["../../x"]
    bcf = tmp_path / "other.bcf"
    bcf.write_text('<bcf:datasource type="file" datatype="bibtex">/etc/x.bib</bcf:datasource>\n'
                   '<bcf:citekey order="1">Zoll90</bcf:citekey>\n', encoding="utf-8")
    with pytest.raises(ExportFailed) as failed:
        export.cited(bcf)
    assert failed.value.names == ["/etc/x.bib"]


def test_shell_escape_and_writing_outside_the_build_folder_are_off(ws, tmp_path):
    need("pdflatex", "bibtex")
    marker, written = tmp_path / "ran-a-command", tmp_path / "written-outside.txt"
    file = paper(tmp_path / "paper", f"\\immediate\\write18{{touch {marker}}}\\cite{{Zoll90}}\n" + PLAIN)
    assert "\\bibitem{Zoll90}" in export.bbl(ws, file).path.read_text(encoding="utf-8")
    assert not marker.exists()
    other = paper(tmp_path / "paper b", f"\\newwrite\\out\\immediate\\openout\\out={written}\n"
                                        f"\\immediate\\write\\out{{x}}\\cite{{Zoll90}}\n" + PLAIN)
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, other)
    assert failed.value.kind == "engine" and not written.exists()


def test_a_link_that_leaves_the_papers_folder_is_not_followed(ws, tmp_path):
    need("pdflatex", "bibtex")
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.tex").write_text("Secret \\cite{FixtA21}.\n", encoding="utf-8")
    file = paper(tmp_path / "paper", "\\cite{Zoll90}\n\\input{secret}\n" + PLAIN)
    os.symlink(outside / "secret.tex", tmp_path / "paper" / "secret.tex")
    os.symlink(outside, tmp_path / "paper" / "more")
    os.symlink(tmp_path / "paper", tmp_path / "paper" / "loop")              # a link back to the folder itself
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, file)
    assert failed.value.kind == "missing_input" and failed.value.names == ["secret.tex"]
    found = export.cited(file)                                # the citations: read from the source, which stays inside too
    assert found.how == "source" and found.keys == ["Zoll90"]

    (tmp_path / "paper" / "secret.tex").unlink()
    (tmp_path / "paper" / "real.tex").write_text("Inside \\cite{FixtA21}.\n", encoding="utf-8")
    os.symlink("real.tex", tmp_path / "paper" / "secret.tex")                 # a link that stays inside is followed
    done = export.bbl(ws, file)
    assert "\\bibitem{FixtA21}" in done.path.read_text(encoding="utf-8")
    assert any("not copied" in note and "more" in note for note in done.notes)


# --- where an export may be written -------------------------------------------------------

def test_an_export_is_never_written_onto_the_library_or_its_records(ws, tmp_path, texenv):
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{Zoll90}\n" + PLAIN)
    found = export.cited(file)
    for folder in (".git", ".bibcheck", "verification", ".git/deeper"):
        (ws.root / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "paper" / ".git").mkdir()
    link, tree = tmp_path / "paper" / "link.bib", texenv[1] / "bibtex" / "bib"
    os.symlink(ws.bib, link)
    tree.mkdir(parents=True)
    os.symlink(ws.bib, tree / "cdl.bib")
    refused = [ws.bib, ws.root / "sub" / ".." / "cdl.bib", link, tree / "cdl.bib", ws.root / ".git" / "x.bib",
               ws.root / ".git" / "deeper" / "x.bib", ws.root / ".bibcheck" / "x.bib", ws.root / "verification" / "x.bib",
               tmp_path / "paper" / ".git" / "x.bib", tmp_path / "paper", tmp_path / "no such folder" / "x.bib"]
    (ws.root / "sub").mkdir()
    for out in refused:
        for attempt in (lambda: export.frozen_bib(ws, found, out, force=True), lambda: export.bbl(ws, file, out=out, force=True)):
            with pytest.raises(ExportFailed) as failed:
                attempt()
            assert failed.value.kind == "output" and "Not written" in str(failed.value), out
    assert ws.bib.read_text(encoding="utf-8") == LIBRARY and os.readlink(link) == str(ws.bib)
    for folder in (".git", ".bibcheck", "verification", ".git/deeper"):
        assert list((ws.root / folder).iterdir()) in ([], [ws.root / ".git" / "deeper"])
    assert export.frozen_bib(ws, found, ws.root / "elsewhere.bib").written == ["Zoll90"]     # beside the library is allowed


def test_an_existing_output_is_replaced_only_with_force(ws, tmp_path):
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{Zoll90}\n" + PLAIN)
    found = export.cited(file)
    for out, write in ((tmp_path / "paper" / "cited.bib", lambda force: export.frozen_bib(ws, found, out, force=force)),
                       (tmp_path / "paper" / "main.bbl", lambda force: export.bbl(ws, file, force=force))):
        out.write_text("my own text\n", encoding="utf-8")
        with pytest.raises(ExportFailed) as failed:
            write(False)
        assert failed.value.kind == "output" and "already exists" in str(failed.value) and "--force" in str(failed.value)
        assert out.read_text(encoding="utf-8") == "my own text\n"
        write(True)
        assert "Zoll90" in out.read_text(encoding="utf-8")
        assert [item.name for item in out.parent.iterdir() if item.name.endswith(".tmp")] == []


# --- the entry text -----------------------------------------------------------------------

def test_every_entry_is_the_librarys_text_byte_for_byte(tmp_path, texenv):
    """Odd spacing, a BOM, CRLF line ends, comments, an @string and an inherited parent."""
    odd = "@ARTICLE{Odd24,\r\n  author={X  Odd},   title = \"Quoted {T}itle\",\r\n\tjournal=jtf, year=2024 }"
    child = "@inproceedings{Child23,\n\tAuthor = {G Child},\n\tTitle = {A talk},\n\tCrossref = {Proc23}}"
    parent = "@proceedings{Proc23,\n\tBooktitle = {Proceedings of the Fixture Meeting},\n\tTitle = {Proceedings of the Fixture Meeting},\n\tYear = {2023}}"
    text = ("\ufeff% a comment at the top\n@string{jtf = \"Journal of Test Fixtures\"}\n\n" + ZOLL90 + "\n% between entries\n"
            + odd + "\r\n\r\n" + child + "\n\n" + FIXTC + "\n" + parent + "\n\n% the end\n")
    ws = make_library(tmp_path / "library", "")
    ws.bib.write_bytes(text.encode("utf-8"))
    library = raws(ws.bib)
    found = export.Cited(keys=["Child23", "Odd24", "Absent00"])
    made = export.frozen_bib(ws, found, tmp_path / "out.bib")
    data = made.path.read_bytes()
    assert made.written == ["Odd24", "Child23", "Proc23"] and made.parents == ["Proc23"]
    assert [item.key for item in made.missing] == ["Absent00"]
    for key in made.written:
        assert library[key].encode("utf-8") in data and raws(made.path)[key] == library[key]
    assert odd.encode("utf-8") in data and b"\r\n  author={X  Odd}" in data
    assert data.startswith(b'% a comment at the top\n@string{jtf = "Journal of Test Fixtures"}\n\n@ARTICLE{Odd24,')
    assert b"Zoll90" not in data and b"FixtC23" not in data and not data.startswith(b"\xef\xbb\xbf")
    assert ws.bib.read_bytes() == text.encode("utf-8")

    everything = export.frozen_bib(ws, export.Cited(keys=[], all_entries=True), tmp_path / "all.bib")
    assert raws(everything.path) == library and everything.parents == []


def test_the_frozen_file_with_strings_and_a_parent_compiles_with_real_bibtex(tmp_path, texenv):
    need("pdflatex", "bibtex")
    child = "@inproceedings{Child23,\n\tAuthor = {G Child},\n\tTitle = {A talk},\n\tCrossref = {Proc23}}"
    parent = "@proceedings{Proc23,\n\tBooktitle = {Proceedings of the Fixture Meeting},\n\tTitle = {Proceedings of the Fixture Meeting},\n\tYear = {2023}}"
    stringed = FIXTA.replace("{Journal of Test Fixtures}", "jtf")
    ws = make_library(tmp_path / "library", "@string{jtf = \"Journal of Strings\"}\n\n" + stringed + "\n\n" + child + "\n\n" + parent + "\n")
    file = paper(tmp_path / "paper", "\\cite{Child23} \\cite{FixtA21}\n" + PLAIN)
    text = export.bbl(ws, file).path.read_text(encoding="utf-8")
    assert "Journal of Strings" in text and "Proceedings of the Fixture Meeting" in text and "\\bibitem{Child23}" in text


# --- which file the citations are read from -----------------------------------------------

def test_an_aux_or_bcf_the_user_names_is_used_as_it_is(ws, tmp_path):
    need("pdflatex", "bibtex", "biber")
    file = paper(tmp_path / "paper", "\\cite{FixtA21}\n" + PLAIN)
    assert run("pdflatex", *FLAGS, "-draftmode", "main.tex", cwd=file.parent).returncode == 0
    file.write_text(file.read_text(encoding="utf-8").replace("FixtA21", "FixtB22"), encoding="utf-8")   # the .tex moved on
    found = export.cited(tmp_path / "paper" / "main.aux")
    assert (found.how, found.keys, found.backend, found.style, found.bibdata) == ("aux", ["FixtA21"], "bibtex", "plain", ["cdl"])
    assert found.sources == [tmp_path / "paper" / "main.aux"] and found.main == file.resolve()
    assert export.frozen_bib(ws, found, tmp_path / "from-aux.bib").written == ["FixtA21"]
    assert export.cited(file).keys == ["FixtB22"]                              # the .tex: compiled afresh
    done = export.bbl(ws, tmp_path / "paper" / "main.aux")                     # a .bbl is always compiled afresh, from the .tex
    assert "\\bibitem{FixtB22}" in done.path.read_text(encoding="utf-8") and done.keys == ["FixtB22"]

    other = paper(tmp_path / "paper b", "\\cite{Zoll90}\\nocite{FixtC23}\n\\printbibliography", BIBLATEX)
    assert run("pdflatex", *FLAGS, "-draftmode", "main.tex", cwd=other.parent).returncode == 0
    for given in ("main.bcf", "main.aux"):                                     # biblatex's .aux: the .bcf beside it is read
        found = export.cited(tmp_path / "paper b" / given)
        assert (found.how, found.keys, found.backend, found.bibdata) == ("bcf", ["Zoll90", "FixtC23"], "biber", ["cdl"])

    alone = tmp_path / "alone.aux"
    alone.write_text("\\relax\n\\citation{Zoll90}\n\\bibstyle{plain}\n\\bibdata{cdl}\n", encoding="utf-8")
    assert export.cited(alone).main is None
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, alone)
    assert failed.value.kind == "no_source"


def test_without_tex_the_source_is_parsed_and_the_result_says_so(ws, tmp_path, monkeypatch):
    file = paper(tmp_path / "paper", "\\seealso{FixtA21} and \\cite{Zoll90} and \\labcite{FixtB22}\n" + PLAIN,
                 "\\newcommand{\\seealso}[1]{\\cite{#1}}\\newcommand{\\labcite}[1]{\\cite{#1}}")
    path = os.environ["PATH"]
    monkeypatch.setenv("PATH", str(tmp_path))
    assert shutil.which("pdflatex") is None
    found = export.cited(file)
    assert found.how == "source" and found.keys == ["Zoll90", "FixtB22"]       # \\seealso's citation is not seen
    assert found.notes == [f"pdflatex was not found on PATH; {export.SOURCE_NOTE}"]
    assert (found.backend, found.style, found.bibdata) == ("bibtex", "plain", ["cdl"])
    assert export.frozen_bib(ws, found, tmp_path / "cited.bib").notes == found.notes
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, file)
    assert failed.value.kind == "no_tex" and failed.value.names == ["pdflatex"]

    if not shutil.which("pdflatex", path=path):
        pytest.skip("pdflatex is not installed: the compiled half of this comparison is not run")
    monkeypatch.setenv("PATH", path)
    compiled = export.cited(file)
    assert compiled.how == "compiled" and compiled.keys == ["FixtA21", "Zoll90", "FixtB22"] and compiled.notes == []


def test_a_paper_that_does_not_compile_is_parsed_and_the_result_says_so(ws, tmp_path):
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{Zoll90} \\undefinedmacro\n" + PLAIN)
    found = export.cited(file)
    assert found.how == "source" and found.keys == ["Zoll90"]
    assert len(found.notes) == 1 and "could not be compiled" in found.notes[0] and "Undefined control sequence" in found.notes[0]
    assert found.notes[0].endswith(export.SOURCE_NOTE)
    with pytest.raises(ExportFailed) as failed:
        export.bbl(ws, file)
    assert failed.value.kind == "engine" and "Undefined control sequence" in str(failed.value)


# --- which file is the paper, which program compiles it -----------------------------------

def test_the_main_file_of_a_folder(ws, tmp_path):
    need("pdflatex", "bibtex")
    folder = tmp_path / "paper"
    paper(folder, "\\cite{Zoll90}\n" + PLAIN, name="article.tex")
    paper(folder, "\\cite{FixtA21}\n" + PLAIN, name="supplement.tex")
    (folder / "notes.tex").write_text("% \\documentclass{article}\nJust notes \\cite{FixtC23}.\n", encoding="utf-8")
    with pytest.raises(ExportFailed) as failed:
        export.cited(folder)
    assert failed.value.kind == "several_main" and failed.value.names == ["article.tex", "supplement.tex"]
    assert export.cited(folder, main="supplement.tex").keys == ["FixtA21"]
    assert export.bbl(ws, folder, main="article.tex").path == (folder / "article.bbl").resolve()
    for wrong in ("nothing.tex", "../library/cdl.bib"):
        with pytest.raises(ExportFailed) as failed:
            export.cited(folder, main=wrong)
        assert failed.value.kind == "no_main"
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ExportFailed) as failed:
        export.cited(empty)
    assert failed.value.kind == "no_main"
    with pytest.raises(ExportFailed) as failed:
        export.cited(tmp_path / "not there")
    assert failed.value.kind == "no_main"


def test_the_latex_program_is_the_one_the_source_asks_for(tmp_path):
    assert export.engine_for(paper(tmp_path / "a", "x")) == "pdflatex"
    assert export.engine_for(paper(tmp_path / "b", "x", "\\usepackage{fontspec}")) == "xelatex"
    assert export.engine_for(paper(tmp_path / "c", "x", "% \\usepackage{fontspec}")) == "pdflatex"
    assert export.engine_for(paper(tmp_path / "d", "x", "\\usepackage{luacode}")) == "lualatex"
    magic = paper(tmp_path / "e", "x", "\\usepackage{fontspec}", documentclass="% !TEX program = lualatex\n\\documentclass{article}")
    assert export.engine_for(magic) == "lualatex" and export.engine_for(magic, "xelatex") == "xelatex"
    odd = paper(tmp_path / "f", "x", documentclass="% !TEX TS-program = arara\n\\documentclass{article}")
    assert export.engine_for(odd) == "pdflatex"
    with pytest.raises(ExportFailed) as failed:
        export.engine_for(magic, "sh")
    assert failed.value.kind == "engine" and "sh is not one of" in str(failed.value)


def test_a_paper_that_asks_for_xelatex_is_compiled_with_it(ws, tmp_path):
    need("xelatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{FixtB22}\n" + PLAIN, documentclass="% !TEX program = xelatex\n\\documentclass{article}")
    done = export.bbl(ws, file)
    assert done.engine == "xelatex" and "\\bibitem{FixtB22}" in done.path.read_text(encoding="utf-8")
