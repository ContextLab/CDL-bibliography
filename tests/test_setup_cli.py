"""`cdlbib setup` and `cdlbib export` as real subprocesses, and api.features(): a HOME, a
TEXMFHOME and a data folder of the test; the real TeX programs."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import plain_output

from cdlbib import api, tex
from cdlbib.errors import CdlbibError
from texhelpers import (FIXTA, LIBRARY, ZOLL90, bibtex_bbl, make_library, need,
                        nothing_of_the_users_touched, paper, texenv)   # noqa: F401  (fixtures)

_SIBLING = Path(sys.executable).parent / "cdlbib"
CDLBIB = str(_SIBLING) if _SIBLING.exists() else shutil.which("cdlbib")
PLAIN = "\\bibliographystyle{plain}\n\\bibliography{cdl}"
FEATURES = ["git", "gh login", "TeX", "bibtex", "biber", "pypdf", "Dartmouth Chat key", "OpenAI key", "textual"]


def cdlbib(*args, cwd, **env):
    return plain_output(subprocess.run([CDLBIB, *args], cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                       env=dict(os.environ, **env)))


@pytest.fixture
def ws(tmp_path, texenv):
    return make_library(tmp_path / "library")


def files_under(folder):
    """Every file under ``folder``, except the state file gh itself writes (under HOME) when it
    is asked who is logged in."""
    found = sorted(str(path.relative_to(folder)) for path in Path(folder).rglob("*") if not path.is_dir())
    return [name for name in found if not name.startswith(os.path.join(".local", "state", "gh") + os.sep)]


# --- features -----------------------------------------------------------------------------

def test_features_without_probes_looks_only_at_programs_packages_and_the_environment(texenv, monkeypatch, tmp_path):
    """Passive: nothing here asks gh or the keychain, whatever this computer has stored."""
    secret = "sk-test-do-not-print-0123456789"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.delenv("DARTMOUTH_CHAT_API_KEY", raising=False)
    said = []
    found = api.features(progress=said.append)
    assert said == [] and [feature.name for feature in found] == FEATURES
    by_name = {feature.name: feature for feature in found}
    for feature in found:
        assert feature.available in (True, False, None) and feature.detail and secret not in repr(feature)
        assert bool(feature.how) != (feature.available is True), feature   # instructions unless it is known to be there
    assert by_name["OpenAI key"].available is True
    assert by_name["OpenAI key"].detail == "set in the environment variable OPENAI_API_KEY"
    dartmouth = by_name["Dartmouth Chat key"]
    assert dartmouth.available is None and dartmouth.detail.startswith("not checked: DARTMOUTH_CHAT_API_KEY is not set")
    assert "DARTMOUTH_CHAT_API_KEY" in dartmouth.how
    for name, program in (("git", "git"), ("TeX", "kpsewhich"), ("bibtex", "bibtex"), ("biber", "biber")):
        assert by_name[name].available == bool(shutil.which(program))
        assert by_name[name].detail == (shutil.which(program) or f"{program} was not found on PATH")
    assert by_name["pypdf"].available is True and by_name["pypdf"].detail == "installed"
    login = by_name["gh login"]
    assert (login.available, login.detail[:12]) == ((None, "not checked:") if shutil.which("gh") else (False, "gh was not f"))
    assert "gh auth login" in login.how

    monkeypatch.setenv("DARTMOUTH_CHAT_API_KEY", "two words")                  # known from the environment alone
    malformed = {feature.name: feature for feature in api.features()}["Dartmouth Chat key"]
    assert malformed.available is False and "single token" in malformed.detail and "two words" not in repr(malformed)

    monkeypatch.setenv("PATH", str(tmp_path))                                  # nothing installed: every program is named
    missing = {feature.name: feature for feature in api.features()}
    for name in ("git", "gh login", "TeX", "bibtex", "biber"):
        assert missing[name].available is False and missing[name].how
    assert "tug.org/texlive" in missing["TeX"].how and "cli.github.com" in missing["gh login"].how
    with pytest.raises(CdlbibError) as wrong:
        api.features(probe=("keychain",))
    assert "Unknown check: keychain" in str(wrong.value)


def test_a_probe_is_announced_and_gives_a_definite_answer(texenv, monkeypatch, tmp_path):
    """The gh probe under a HOME of the test: gh has no login there (or is not installed)."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "no gh config"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-do-not-print-0123456789")
    said = []
    found = {feature.name: feature for feature in api.features(probe=("github", "openai"), progress=said.append)}
    assert said == (["asking gh who is logged in (gh api user) ..."] if shutil.which("gh") else [])   # the key is in the environment
    assert found["gh login"].available in (True, False) and found["OpenAI key"].available is True
    assert found["Dartmouth Chat key"].available is None or os.environ.get("DARTMOUTH_CHAT_API_KEY")
    report = api.setup_report(make_library(tmp_path / "lib"))
    assert {feature.name: feature for feature in report.features}["gh login"].available is not True     # passive by default


def test_the_keychain_probe_reads_a_real_keychain(usable_keychain, monkeypatch):
    """Only where a usable keychain exists (tests/conftest.py); it reads, never writes."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    said = []
    found = {feature.name: feature for feature in api.features(probe=("openai",), progress=said.append)}
    assert said == ["reading the system keychain for the OpenAI key ..."]
    assert found["OpenAI key"].available in (True, False) and "not checked" not in found["OpenAI key"].detail


# --- setup --------------------------------------------------------------------------------

def test_setup_check_reports_and_changes_nothing(ws, texenv, tmp_path):
    need("kpsewhich")
    home, texmf, data = texenv
    out = cdlbib("--library", str(ws.root), "setup", "--check", cwd=tmp_path, OPENAI_API_KEY="sk-test-do-not-print-0123456789")
    link = texmf / "bibtex" / "bib" / "cdl.bib"
    assert out.returncode == 1, out.stdout + out.stderr
    lines = out.stdout.splitlines()
    assert lines[:6] == [f"library: {ws.root}", "chosen by: --library", f"TeX tree: {texmf}", f"link: {link}",
                         "state: not linked", "kpsewhich cdl.bib: not found"]
    assert lines[6] == ("without a link, this shell line does the same (cdlbib does not write it anywhere): "
                        + tex.bibinputs_line(ws))
    assert lines[7] == "available on this computer:"
    assert [line.strip().split(":")[0] for line in lines[8:]] == FEATURES
    assert "  OpenAI key: yes (set in the environment variable OPENAI_API_KEY)" in lines
    assert "sk-test-do-not-print" not in out.stdout + out.stderr and "Traceback" not in out.stderr
    assert not texmf.exists() and not data.exists() and files_under(home) == []


def test_setup_links_and_a_paper_elsewhere_compiles_then_remove_takes_only_the_link(ws, texenv, tmp_path):
    need("kpsewhich", "pdflatex", "bibtex")
    home, texmf, data = texenv
    link = texmf / "bibtex" / "bib" / "cdl.bib"
    out = cdlbib("--library", str(ws.root), "setup", cwd=tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert f"link: {link} -> {ws.bib}" in out.stdout and f"linked {link} -> {ws.bib}" in out.stdout
    assert "state: linked: TeX finds this library's cdl.bib from any folder" in out.stdout
    assert f"kpsewhich cdl.bib: {link}" in out.stdout and "BIBINPUTS" not in out.stdout
    assert os.readlink(link) == str(ws.bib) and files_under(data) == ["tex-link.json"]
    assert files_under(home) == []                                             # no shell file was written

    bbl, _ = bibtex_bbl(paper(tmp_path / "paper", "\\cite{Zoll90}\n" + PLAIN))
    assert "\\bibitem{Zoll90}" in bbl

    again = cdlbib("--library", str(ws.root), "setup", cwd=tmp_path)           # already linked: nothing is done again
    assert again.returncode == 0 and "linked " + str(link) not in again.stdout and "state: linked" in again.stdout
    assert cdlbib("--library", str(ws.root), "setup", "--check", cwd=tmp_path).returncode == 0

    gone = cdlbib("setup", "--remove", cwd=tmp_path)
    assert gone.returncode == 0 and gone.stdout.splitlines()[0] == f"removed {link}"
    assert not os.path.lexists(link) and files_under(data) == [] and ws.bib.read_text(encoding="utf-8") == LIBRARY
    gone = cdlbib("setup", "--remove", cwd=tmp_path)
    assert gone.returncode == 0 and gone.stdout.strip() == f"nothing removed at {link}: there is no link"


def test_setup_leaves_a_file_it_did_not_make_and_replace_moves_it_aside(ws, texenv, tmp_path):
    need("kpsewhich")
    _, texmf, _ = texenv
    link = texmf / "bibtex" / "bib" / "cdl.bib"
    link.parent.mkdir(parents=True)
    link.write_text("my own bibliography\n", encoding="utf-8")
    out = cdlbib("--library", str(ws.root), "setup", cwd=tmp_path)
    assert out.returncode == 1 and f"state: not linked: {link} exists and was not made by cdlbib" in out.stdout
    assert "it was left as it is" in out.stderr and out.stderr.strip().endswith("Run: cdlbib setup --replace")
    assert link.read_text(encoding="utf-8") == "my own bibliography\n" and not link.is_symlink()
    gone = cdlbib("setup", "--remove", cwd=tmp_path)
    assert "nothing removed" in gone.stdout and link.read_text(encoding="utf-8") == "my own bibliography\n"

    out = cdlbib("--library", str(ws.root), "setup", "--replace", cwd=tmp_path)
    saved = [item for item in link.parent.iterdir() if item.name.startswith(tex.SAVED)]
    assert out.returncode == 0 and len(saved) == 1 and saved[0].read_text(encoding="utf-8") == "my own bibliography\n"
    assert f"moved the existing {link} aside to {saved[0]}" in out.stdout and os.readlink(link) == str(ws.bib)


def test_setup_with_ask_and_no_terminal_makes_no_link(ws, texenv, tmp_path):
    need("kpsewhich")
    _, texmf, data = texenv
    out = cdlbib("--ask", "--library", str(ws.root), "setup", cwd=tmp_path)
    assert out.returncode == 1 and "the link was not made (not confirmed)" in out.stdout
    assert not texmf.exists() and not data.exists()
    assert cdlbib("--library", str(ws.root), "setup", "--check", "--remove", cwd=tmp_path).returncode == 2


def test_setup_links_the_managed_library_it_downloads(texenv, tmp_path):
    need("kpsewhich", "pdflatex", "bibtex")
    _, texmf, data = texenv
    out = cdlbib("setup", cwd=tmp_path)
    managed = (data / "library").resolve()
    assert out.returncode == 0, out.stdout + out.stderr
    assert f"library: {managed}" in out.stdout and "this is the copy cdlbib downloads and manages" in out.stdout
    assert os.readlink(texmf / "bibtex" / "bib" / "cdl.bib") == str(managed / "cdl.bib")
    bbl, _ = bibtex_bbl(paper(tmp_path / "paper", "\\cite{Zoll90}\n" + PLAIN))
    assert "\\bibitem{Zoll90}" in bbl


def test_setup_without_tex_says_so_and_still_links(ws, texenv, tmp_path):
    home, _, _ = texenv
    programs = "/usr/bin:/bin"
    if shutil.which("kpsewhich", path=programs):
        pytest.skip("kpsewhich is in /usr/bin or /bin, so a PATH without TeX cannot be made from them")
    default = home / "Library" / "texmf" if sys.platform == "darwin" else home / "texmf"
    out = cdlbib("--library", str(ws.root), "setup", cwd=tmp_path, PATH=programs, TEXMFHOME="")
    link = default / "bibtex" / "bib" / "cdl.bib"
    assert out.returncode == 0, out.stdout + out.stderr
    assert f"TeX tree: {default}" in out.stdout and os.readlink(link) == str(ws.bib)
    assert "state: linked; TeX was not found, so it could not be shown that TeX resolves it" in out.stdout
    assert "kpsewhich cdl.bib" not in out.stdout and "  TeX: no (kpsewhich was not found on PATH) Install TeX Live" in out.stdout
    check = cdlbib("--library", str(ws.root), "setup", "--check", cwd=tmp_path, PATH=programs, TEXMFHOME="")
    assert check.returncode == 1                                               # not shown to resolve: not reported as linked


# --- export -------------------------------------------------------------------------------

def test_export_writes_the_frozen_bib_beside_the_paper(ws, texenv, tmp_path):
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{FixtA21} \\cite{Zoll90}\n" + PLAIN)
    out = cdlbib("--library", str(ws.root), "export", str(file), cwd=tmp_path)
    made = tmp_path / "paper" / "cdl.bib"
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.splitlines() == ["citations read from a fresh LaTeX run of the paper: 2 keys",
                                       f"wrote {made.resolve()}: 2 entries from {ws.bib}"]
    assert made.read_bytes() == (ZOLL90 + "\n\n" + FIXTA + "\n").encode("utf-8")
    assert sorted(item.name for item in (tmp_path / "paper").iterdir()) == ["cdl.bib", "main.tex"]

    again = cdlbib("--library", str(ws.root), "export", str(tmp_path / "paper"), cwd=tmp_path)
    assert again.returncode == 1 and "already exists; --force replaces it" in again.stderr and again.stdout == ""
    forced = cdlbib("--library", str(ws.root), "export", str(tmp_path / "paper"), "--force", cwd=tmp_path)
    assert forced.returncode == 0 and "wrote" in forced.stdout
    onto = cdlbib("--library", str(ws.root), "export", str(file), "-o", str(ws.bib), "--force", cwd=tmp_path)
    assert onto.returncode == 1 and "is the library's own file" in onto.stderr
    assert ws.bib.read_text(encoding="utf-8") == LIBRARY


def test_export_lists_missing_keys_and_exits_1(ws, texenv, tmp_path):
    need("pdflatex", "bibtex")
    ws.key_renames.write_text('[{"old_key": "Fixt21", "new_key": "FixtA21"}]', encoding="utf-8")
    file = paper(tmp_path / "paper", "\\cite{Zoll90} \\cite{Fixt21} \\cite{Nobody99}\n" + PLAIN)
    out = cdlbib("--library", str(ws.root), "export", str(file), "--out", str(tmp_path / "cited.bib"), cwd=tmp_path)
    assert out.returncode == 1 and f"wrote {(tmp_path / 'cited.bib').resolve()}: 1 entry from {ws.bib}" in out.stdout
    assert out.stderr.strip() == "cited, but not in the library: Fixt21 (now FixtA21), Nobody99"
    assert (tmp_path / "cited.bib").read_text(encoding="utf-8") == ZOLL90 + "\n"
    bbl = cdlbib("--library", str(ws.root), "export", str(file), "--bbl", cwd=tmp_path)
    assert bbl.returncode == 1 and "Cited, but in no bibliography of the paper: Fixt21 (now FixtA21), Nobody99." in bbl.stderr
    assert not (tmp_path / "paper" / "main.bbl").exists()


def test_export_bbl_with_inputs_main_and_engine(ws, texenv, tmp_path):
    need("pdflatex", "bibtex", "kpsewhich")
    folder = tmp_path / "paper"
    paper(folder, "\\cite{Zoll90}\\labnote\n\\bibliographystyle{labstyle}\n\\bibliography{cdl}", "\\usepackage{labmacros}", name="article.tex")
    paper(folder, "\\cite{FixtA21}\n" + PLAIN, name="supplement.tex")
    several = cdlbib("--library", str(ws.root), "export", str(folder), "--bbl", cwd=tmp_path)
    assert several.returncode == 1 and "article.tex, supplement.tex" in several.stderr and "--main FILE" in several.stderr
    missing = cdlbib("--library", str(ws.root), "export", str(folder), "--bbl", "--main", "article.tex", cwd=tmp_path)
    assert missing.returncode == 1 and "pdflatex could not find: labmacros.sty" in missing.stderr

    styles, macros = tmp_path / "styles", tmp_path / "macros" / "labmacros.sty"
    styles.mkdir()
    macros.parent.mkdir()
    shutil.copyfile(subprocess.run(["kpsewhich", "plain.bst"], capture_output=True, text=True).stdout.strip(), styles / "labstyle.bst")
    macros.write_text("\\ProvidesPackage{labmacros}\n\\newcommand{\\labnote}{ (lab)}\n", encoding="utf-8")
    one = cdlbib("--library", str(ws.root), "export", str(folder), "--bbl", "--main", "article.tex", "--inputs", str(macros), cwd=tmp_path)
    assert one.returncode == 1 and "BibTeX could not find: labstyle.bst" in one.stderr
    out = cdlbib("--library", str(ws.root), "export", str(folder), "--bbl", "--main", "article.tex", "--inputs", str(macros),
                 "--inputs", str(styles), "--engine", "pdflatex", "-o", str(tmp_path / "made.bbl"), cwd=tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.strip() == f"wrote {(tmp_path / 'made.bbl').resolve()}: bibtex, style labstyle, pdflatex, 1 cited key"
    assert "\\bibitem{Zoll90}" in (tmp_path / "made.bbl").read_text(encoding="utf-8")
    assert sorted(item.name for item in folder.iterdir()) == ["article.tex", "supplement.tex"]
    wrong = cdlbib("--library", str(ws.root), "export", str(folder), "--bbl", "--main", "supplement.tex", "--engine", "sh", cwd=tmp_path)
    assert wrong.returncode == 1 and "sh is not one of the LaTeX programs used here" in wrong.stderr
    hostile = paper(tmp_path / "hostile", "\\cite{Zoll90}\n\\bibliographystyle{plain}\n\\bibliography{../library/cdl}")
    refused = cdlbib("--library", str(ws.root), "export", str(hostile), "--bbl", cwd=tmp_path)
    assert refused.returncode == 1 and "not a plain file name: ../library/cdl" in refused.stderr


def test_export_with_biber_and_the_linked_library_in_use(ws, texenv, tmp_path):
    need("pdflatex", "biber", "kpsewhich")
    assert cdlbib("--library", str(ws.root), "setup", cwd=tmp_path).returncode == 0
    file = paper(tmp_path / "paper", "\\textcite{FixtB22}\\nocite{*}\n\\printbibliography",
                 "\\usepackage[backend=biber]{biblatex}\n\\addbibresource{cdl.bib}")
    out = cdlbib("--library", str(ws.root), "export", str(file), "--bbl", cwd=tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.strip() == (f"wrote {(tmp_path / 'paper' / 'main.bbl').resolve()}: biber, pdflatex, 1 cited key "
                                  "and every other entry (\\nocite{*})")
    text = (tmp_path / "paper" / "main.bbl").read_text(encoding="utf-8")
    assert all(f"\\entry{{{key}}}{{article}}" in text for key in ("Zoll90", "FixtA21", "FixtB22", "FixtC23"))
    bib = cdlbib("--library", str(ws.root), "export", str(file), cwd=tmp_path)
    assert bib.returncode == 0 and "citations read from a fresh LaTeX run of the paper: 1 key and \\nocite{*} (every entry)" in bib.stdout
    assert (tmp_path / "paper" / "cdl.bib").read_bytes() == LIBRARY.encode("utf-8")


def test_export_out_that_is_a_link_to_the_library_is_refused_even_with_force(ws, texenv, tmp_path):
    need("pdflatex", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{Zoll90}\n" + PLAIN)
    link = tmp_path / "paper" / "refs.bib"
    os.symlink(ws.bib, link)
    for extra in ([], ["--force"], ["--bbl"], ["--bbl", "--force"]):
        out = cdlbib("--library", str(ws.root), "export", str(file), "-o", str(link), *extra, cwd=tmp_path)
        assert out.returncode == 1 and "is a symbolic link" in out.stderr and "Not written" in out.stderr, out.stderr
    assert ws.bib.read_text(encoding="utf-8") == LIBRARY and os.readlink(link) == str(ws.bib)


def test_export_does_not_run_lualatex_unless_it_is_named(ws, texenv, tmp_path):
    need("pdflatex", "bibtex")
    written = tmp_path / "written-by-lua.txt"
    file = paper(tmp_path / "paper", f'\\directlua{{local f = io.open("{written}", "w") if f then f:write("x") f:close() end}}'
                                     "\\cite{Zoll90}\n" + PLAIN)
    out = cdlbib("--library", str(ws.root), "export", str(file), "--bbl", cwd=tmp_path)
    assert out.returncode == 1 and "asks for lualatex" in out.stderr and "pass --engine lualatex" in out.stderr
    assert not written.exists() and not (tmp_path / "paper" / "main.bbl").exists()
    bib = cdlbib("--library", str(ws.root), "export", str(file), cwd=tmp_path)
    assert bib.returncode == 0 and "citations read from the .tex source: 1 key" in bib.stdout and not written.exists()
    wrong = cdlbib("--library", str(ws.root), "export", str(file), "--bbl", "--engine", "luatex", cwd=tmp_path)
    assert wrong.returncode == 1 and "luatex is not one of the LaTeX programs used here" in wrong.stderr


def test_setup_announces_each_probe_and_export_says_when_it_read_the_source(ws, texenv, tmp_path):
    need("kpsewhich", "pdflatex", "bibtex")
    out = cdlbib("--library", str(ws.root), "setup", "--check", cwd=tmp_path, OPENAI_API_KEY="sk-test-do-not-print-0123456789",
                 DARTMOUTH_CHAT_API_KEY="dc-test-do-not-print")
    assert "not checked" not in out.stdout                                     # the setup command checks everything
    if shutil.which("gh"):
        assert "asking gh who is logged in (gh api user) ..." in out.stderr
    assert "keychain" not in out.stderr                                        # both keys were in the environment

    file = paper(tmp_path / "paper", "\\cite{Zoll90}\n" + PLAIN, "\\usepackage{notinstalledanywhere}")
    made = cdlbib("--library", str(ws.root), "export", str(file), cwd=tmp_path)
    lines = made.stdout.splitlines()
    assert made.returncode == 0 and lines[0] == "citations read from the .tex source: 1 key"
    assert "could not be compiled" in lines[1] and "notinstalledanywhere.sty" in lines[1]
    assert lines[1].endswith("citations were read from the source; citations made by custom macros are not seen")
