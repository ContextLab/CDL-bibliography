"""biber and bibtex as dependencies of `cdlbib export --bbl`: which versions are installed,
what is said and done when one is missing, and which control files the allowlist takes.

Nothing is substituted: the programs are this computer's own, "biber is missing" is a PATH
that really lacks it (a folder of links to the other TeX programs), and the installation is a
real one, by a real tlmgr, into a TeX Live of the tests' own.

The installation tests download a small TeX Live (TinyTeX, about 67 MB) and then biber
(about 70 MB) into pytest's temporary folder, so they run only when asked for:

    CDLBIB_TEST_TEX_INSTALL=1 pytest tests/test_texinstall.py

No test here changes the computer's own TeX installation: where its package manager could
install something, the tests stop at the decision and never make the call."""
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import urllib.request
from pathlib import Path

import pytest

import conftest
from cdlbib import api, deps, export, texinstall
from cdlbib.errors import CdlbibError, ExportFailed, MissingDependency, MissingProgram, NeedsConfirmation
from texhelpers import (FLAGS, ZOLL90, make_library, need, nothing_of_the_users_touched,   # noqa: F401  (fixtures)
                        paper, run, texenv)
from test_setup_cli import CDLBIB, cdlbib

BIBLATEX = "\\usepackage[backend=biber]{biblatex}\n\\addbibresource{cdl.bib}"
CITES = "\\cite{Zoll90}\n\\printbibliography"
PLAIN = "\\bibliographystyle{plain}\n\\bibliography{cdl}"
SCHEMAS = json.loads((Path(__file__).parent / "fixtures" / "bcf_schema_names.json").read_text(encoding="utf-8"))
TEX_PROGRAMS = ("kpsewhich", "pdflatex", "latex", "xelatex", "lualatex", "bibtex", "biber", "mktexlsr")


@pytest.fixture
def ws(tmp_path, texenv):
    return make_library(tmp_path / "library")


def path_without(folder, *missing):
    """A folder of links to this computer's TeX programs, all but ``missing``: used as the
    whole PATH, it is a computer where those are not installed."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for program in TEX_PROGRAMS:
        found = shutil.which(program)
        if found and program not in missing:
            os.symlink(found, folder / program)
    return str(folder)


# --- versions ---------------------------------------------------------------------------------

def test_the_versions_are_the_ones_the_programs_report():
    need("biber", "bibtex", "kpsewhich")
    said = subprocess.run(["biber", "--version"], capture_output=True, text=True).stdout
    assert texinstall.version("biber") and said.strip().endswith(texinstall.version("biber"))
    assert re.fullmatch(r"\d+\.\d+", texinstall.version("bibtex"))                  # digits and dots: 0.99 of "0.99d"
    assert texinstall.version("bibtex") in subprocess.run(["bibtex", "--version"], capture_output=True, text=True).stdout
    assert texinstall.version("a-program-that-is-not-installed") == ""
    sty = subprocess.run(["kpsewhich", "biblatex.sty"], capture_output=True, text=True).stdout.strip()
    if sty:
        assert "\\def\\abx@version{" + texinstall.biblatex_version() + "}" in Path(sty).read_text(encoding="utf-8", errors="replace")
        assert texinstall.versions_line() == f"biber {texinstall.version('biber')}, biblatex {texinstall.biblatex_version()}"


def test_features_and_setup_check_report_the_versions(ws, texenv, tmp_path, monkeypatch):
    need("biber", "bibtex", "kpsewhich")
    found = {feature.name: feature for feature in api.features()}
    assert found["biber"].version == texinstall.versions_line() and found["biber"].version.startswith("biber ")
    assert found["bibtex"].version == texinstall.version("bibtex") and found["git"].version == ""
    assert api.as_data(found["biber"])["version"] == found["biber"].version
    out = cdlbib("--library", str(ws.root), "setup", "--check", cwd=tmp_path)
    assert f"  biber: yes ({shutil.which('biber')}; {found['biber'].version})" in out.stdout
    assert f"  bibtex: yes ({shutil.which('bibtex')}; {found['bibtex'].version})" in out.stdout

    monkeypatch.setenv("PATH", path_without(tmp_path / "bin", "biber"))        # not installed: no version, and how to get it
    missing = {feature.name: feature for feature in api.features()}["biber"]
    assert missing.available is False and missing.version == "" and missing.how == texinstall.how("biber")
    assert missing.detail == "biber was not found on PATH"


def test_the_web_setup_report_carries_the_versions(tmp_path, monkeypatch):
    need("biber")
    import web_support as web
    web.isolate(monkeypatch, tmp_path / "env")
    running, client = web.start(web.make_library(tmp_path / "library", ZOLL90))
    try:
        found = {item["name"]: item for item in client.ok("get", "/api/setup")["features"]}
    finally:
        running.stop()
    assert found["biber"]["version"] == texinstall.versions_line() and found["git"]["version"] == ""
    page = (Path(web.__file__).parents[1] / "src" / "cdlbib" / "web" / "static" / "js" / "setup.js").read_text(encoding="utf-8")
    assert 'item.version ? item.detail + " (" + item.version + ")" : item.detail' in page      # the Setup table shows it


def test_the_terminal_setup_view_shows_the_versions(tmp_path, monkeypatch):
    need("biber")
    pytest.importorskip("textual")
    import tui_support as T
    T.isolate(monkeypatch, tmp_path)
    T.offline(monkeypatch)
    library = T.library(tmp_path / "lib", ZOLL90)

    async def journey():
        async with T.opened(library) as pilot:
            await T.press(pilot, "f8")
            report = " ".join(T.shown(pilot.app, "#setup-report").split())
            assert f"biber: yes ({shutil.which('biber')}; {texinstall.versions_line()})" in report
    T.run(journey())
    conftest.no_real_library_touched()


# --- a missing program, where nothing is installed from here -------------------------------------

def test_without_tex_there_is_nothing_to_install_with(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    found = texinstall.plan("biber")
    assert (found.distribution, found.command, found.manual) == ("none", [], texinstall.NO_TEX)
    with pytest.raises(CdlbibError, match="biber cannot be installed from here: no TeX installation was found on PATH"):
        texinstall.install("biber")
    with pytest.raises(CdlbibError, match="cannot be installed from here"):
        deps.install("tex", package="biber")                 # the front ends' one call: the same refusal


def test_the_plan_names_this_computers_own_package_manager():
    """Whatever TeX this computer has, the plan is one of the known kinds, never holds sudo
    as something to run, and runs only the package manager that belongs to the TeX found."""
    need("kpsewhich")
    real = Path(shutil.which("kpsewhich")).resolve()
    for program in ("biber", "bibtex"):
        found = texinstall.plan(program)
        assert found.distribution in ("texlive", "homebrew", "miktex", "system", "unknown") and found.manual
        assert "sudo" not in found.command and bool(found.command) != bool(found.why)
        if found.command:
            assert found.command[1:] in (["install", texinstall.TEXLIVE[program]], ["install", "biber"])
            assert Path(found.command[0]).name in ("tlmgr", "brew") and found.shown in found.manual
        if found.distribution == "texlive" and found.command:
            assert Path(found.command[0]) == real.parent / "tlmgr"             # the tlmgr of the same TeX Live
    if "Cellar" in real.parts:                                                 # Homebrew: biber is a formula of its own
        biber, bibtex = texinstall.plan("biber"), texinstall.plan("bibtex")
        assert (biber.distribution, biber.manual) == ("homebrew", "Run: brew install biber")
        prefix = Path(*real.parts[:real.parts.index("Cellar")])
        assert biber.command == [str(prefix / "bin" / "brew"), "install", "biber"] and biber.shown == "brew install biber"
        assert bibtex.command == [] and "brew reinstall texlive" in bibtex.manual
        said = subprocess.run(["tlmgr", "install", "--dry-run", "biber"], capture_output=True, text=True)
        assert texinstall._restricted(real.parents[1] / "share" / "texmf-config" / "tlmgr" / "config")
        assert "action not allowed in system mode: install" in said.stdout + said.stderr   # why tlmgr is not the way here


def test_a_missing_biber_stops_the_export_naming_the_command(ws, texenv, tmp_path, monkeypatch):
    """With biber really absent from PATH the core never installs: it raises MissingProgram
    (a package manager can be run as this user) or the no_tex refusal with the command."""
    need("pdflatex", "kpsewhich", "biber")
    file = paper(tmp_path / "paper", CITES, BIBLATEX)
    monkeypatch.setenv("PATH", path_without(tmp_path / "bin", "biber"))
    assert shutil.which("biber") is None and shutil.which("pdflatex")
    found = texinstall.plan("biber")
    with pytest.raises((ExportFailed, MissingProgram)) as stopped:
        export.bbl(ws, file)
    assert not file.with_suffix(".bbl").exists() and shutil.which("biber") is None
    if found.command:
        assert isinstance(stopped.value, MissingProgram) and stopped.value.command == found.command
        assert (stopped.value.package, stopped.value.extra, stopped.value.feature) == ("biber", "tex", "Compiling a .bbl")
    else:
        assert stopped.value.kind == "no_tex" and stopped.value.names == ["biber"]
        assert str(stopped.value) == ("biber was not found on PATH. A .bbl needs a TeX installation that has it. "
                                      + texinstall.how("biber"))
        assert found.manual in str(stopped.value) and found.why in str(stopped.value)
        if "Cellar" in Path(shutil.which("kpsewhich")).resolve().parts:
            assert "Run: brew install biber" in str(stopped.value)

    out = cdlbib("--ask", "--library", str(ws.root), "export", str(file), "--bbl", cwd=tmp_path)   # no terminal: not installed
    assert out.returncode == 1 and "biber" in out.stderr and (found.shown if found.command else found.manual) in out.stderr
    assert not file.with_suffix(".bbl").exists()


def test_a_missing_bibtex_stops_the_export_naming_the_command(ws, texenv, tmp_path, monkeypatch):
    need("pdflatex", "kpsewhich", "bibtex")
    file = paper(tmp_path / "paper", "\\cite{Zoll90}\n" + PLAIN)
    monkeypatch.setenv("PATH", path_without(tmp_path / "bin", "bibtex"))
    found = texinstall.plan("bibtex")
    with pytest.raises((ExportFailed, MissingProgram)) as stopped:
        export.bbl(ws, file)
    assert (found.shown if found.command else found.manual) in str(stopped.value) and "bibtex" in str(stopped.value)
    assert not file.with_suffix(".bbl").exists()


def test_the_question_and_the_line_name_the_command():
    from cdlbib import prompts
    missing = MissingProgram("biber", "Compiling a .bbl", ["/somewhere/bin/tlmgr", "install", "biber"], "tlmgr install biber")
    assert isinstance(missing, MissingDependency)
    assert str(missing) == ("Compiling a .bbl needs the TeX program 'biber', which was not found on PATH "
                            "(install: tlmgr install biber)")
    assert prompts.install_question(missing) == ("Compiling a .bbl needs the TeX program 'biber'. Install it now "
                                                 "(tlmgr install biber)?")
    assert prompts.install_line(missing) == "installing biber (needed for: Compiling a .bbl) with: tlmgr install biber ..."
    said = []
    assert api.consent(missing, progress=said.append) is True and said == [prompts.install_line(missing)]
    deps.set_ask(True)
    try:
        with pytest.raises(NeedsConfirmation) as asked:
            api.consent(missing)
    finally:
        deps.set_ask(False)
    assert asked.value.kind == "install" and asked.value.question == prompts.install_question(missing)
    assert asked.value.__cause__ is missing and (asked.value.package, asked.value.extra) == ("biber", "tex")


# --- what is run, how much is read, and what is shown ------------------------------------------------

def decoy(folder, name, marker, says=""):
    """A real executable called ``name`` that leaves ``marker`` behind when anything runs it."""
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / name
    file.write_text(f"#!/bin/sh\necho ran >> '{marker}'\nprintf '{says}'\nexit 0\n", encoding="utf-8")
    file.chmod(0o755)
    return file


def test_the_package_manager_is_the_tex_installations_own_not_the_first_on_path(ws, texenv, tmp_path, monkeypatch):
    """A tlmgr and a brew that come first on PATH, and lie in the folder the command is
    started in, are never the ones named or run: the command is the one beside the TeX found."""
    need("pdflatex", "kpsewhich", "biber")
    real = Path(shutil.which("kpsewhich")).resolve()
    marker = tmp_path / "a decoy ran"
    folder = Path(path_without(tmp_path / "bin", "biber"))
    for name in ("tlmgr", "brew"):
        decoy(folder, name, marker)
        decoy(tmp_path / "paper", name, marker)
    file = paper(tmp_path / "paper", CITES, BIBLATEX)
    monkeypatch.setenv("PATH", str(folder))
    monkeypatch.chdir(tmp_path / "paper")
    assert shutil.which("tlmgr") == str(folder / "tlmgr") and shutil.which("brew") == str(folder / "brew")
    for program in ("biber", "bibtex"):
        found = texinstall.plan(program)
        if found.command:
            manager = Path(found.command[0])
            assert manager.is_absolute() and manager.parent not in (folder, tmp_path / "paper")
            assert manager == real.parent / "tlmgr" or (manager.name == "brew" and manager.parent.parent / "Cellar" in real.parents)
    with pytest.raises((ExportFailed, MissingProgram)) as stopped:
        export.bbl(ws, file)
    if isinstance(stopped.value, MissingProgram):
        assert Path(stopped.value.command[0]).parent not in (folder, tmp_path / "paper")
    out = cdlbib("--ask", "--library", str(ws.root), "export", str(file), "--bbl", cwd=tmp_path / "paper")
    assert out.returncode == 1 and not marker.exists() and not file.with_suffix(".bbl").exists()


def test_a_tex_found_through_a_relative_folder_of_path_gives_nothing_to_run(tmp_path, monkeypatch):
    marker = tmp_path / "a decoy ran"
    for name in ("kpsewhich", "pdflatex", "tlmgr", "biber"):
        decoy(tmp_path / "here", name, marker, says="biber version: 9.99\\n")
    monkeypatch.chdir(tmp_path / "here")
    for relative in (".", "", os.pathsep.join(["", "."])):
        monkeypatch.setenv("PATH", relative)
        found = texinstall.plan("biber")
        assert (found.distribution, found.command) == ("none", []) and (relative == "" or "not an absolute path" in found.why)
        assert texinstall.which("biber") is None and texinstall.version("biber") == "" and texinstall.biblatex_version() == ""
        with pytest.raises(CdlbibError, match="cannot be installed from here"):
            texinstall.install("biber")
    assert texinstall._run(["biber", "--version"]) == (None, "biber is not an absolute path")
    assert not marker.exists()


def test_a_program_gets_a_small_environment_and_an_empty_folder(tmp_path, monkeypatch):
    for name, value in (("TEXMFCNF", str(tmp_path)), ("PERL5LIB", str(tmp_path)), ("BIBER_CONF", "x"), ("CDLBIB_CANARY", "seen"),
                        ("HOMEBREW_NO_ANALYTICS", "1"), ("https_proxy", "http://proxy.invalid:1")):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PATH", os.pathsep.join([".", "relative/bin", "", os.environ["PATH"]]))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a file of the folder the command was started in").write_text("x", encoding="utf-8")
    status, text = texinstall._run([sys.executable, "-c",
                                    "import json, os; print(json.dumps([dict(os.environ), os.getcwd(), os.listdir('.')]))"])
    assert status == 0
    env, folder, inside = json.loads(text)
    given = {name: value for name, value in env.items() if name not in ("__CF_USER_TEXT_ENCODING", "LC_CTYPE") or name in texinstall.KEPT}
    assert set(given) <= set(texinstall.KEPT) | {"PATH"} and env["https_proxy"] == "http://proxy.invalid:1"
    assert env["HOME"] == os.environ["HOME"] and "CDLBIB_CANARY" not in env and "TEXMFCNF" not in env
    folders = env["PATH"].split(os.pathsep)
    assert folders[0] == str(Path(sys.executable).parent) and all(os.path.isabs(part) for part in folders)
    assert inside == [] and Path(folder).resolve() != tmp_path.resolve() and not Path(folder).exists()


def test_what_a_program_prints_and_what_a_file_holds_is_read_up_to_a_limit(tmp_path):
    import time
    big = "import sys; sys.stdout.write('head' + 'x' * 5_000_000 + 'tail'); sys.stderr.write('e' * 1_000_000)"
    status, text = texinstall._run([sys.executable, "-c", big])
    assert status == 0 and len(text) == texinstall.MAX_OUTPUT and text.startswith("headxxx")
    status, text = texinstall._run([sys.executable, "-c", "import sys; sys.stdout.write('x' * 5_000_000 + 'tail')"], keep="tail")
    assert status == 0 and len(text) == texinstall.MAX_OUTPUT and text.endswith("xtail")

    started = time.monotonic()                                # a program that never finishes is stopped, with what it started
    child = tmp_path / "child.pid"
    slow = (f"import subprocess, sys, time; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)']);"
            f"open({str(child)!r}, 'w').write(str(p.pid)); print('started', flush=True); time.sleep(600)")
    assert texinstall._run([sys.executable, "-c", slow], timeout=3) == (None, "it did not finish within 3 seconds")
    assert time.monotonic() - started < 30
    time.sleep(0.5)
    with pytest.raises(ProcessLookupError):
        os.kill(int(child.read_text()), 0)

    large = tmp_path / "config"
    large.write_text("#" * (texinstall.MAX_FILE + 10) + "\nallowed-actions=info\n", encoding="utf-8")
    assert len(texinstall.read(large)) == texinstall.MAX_FILE and texinstall._restricted(large) is False   # not read to its end
    large.write_text("allowed-actions = info, search\n", encoding="utf-8")
    assert texinstall._restricted(large) is True
    large.write_text("allowed-actions=info,install\n", encoding="utf-8")
    assert texinstall._restricted(large) is False
    os.mkfifo(tmp_path / "pipe")                              # nothing writes to it: a read would never return
    started = time.monotonic()
    assert texinstall.read(tmp_path / "pipe") == "" and texinstall.read(tmp_path / "absent") == "" and texinstall.read(tmp_path) == ""
    assert time.monotonic() - started < 5
    assert texinstall._path("/a/" + "b" * texinstall.MAX_PATH) is None and texinstall._path("relative/path\n") is None
    assert texinstall._path("/one\n/two\n") is None and texinstall._path("/a/\x1b[31mb\n") is None
    assert texinstall._path("/usr/share/texlive\n") == Path("/usr/share/texlive")


def test_what_is_shown_of_a_program_is_printable_and_a_version_is_digits_and_dots(tmp_path, monkeypatch):
    """Real programs called biber that print terminal escape sequences: the version is the
    digits and dots or nothing, in the report and on the command line."""
    marker = tmp_path / "ran"
    cases = {"plain": ("biber version: 2.19\\n", "2.19"),
             "escapes after": ("biber version: 2.20\\033[2J\\033]0;title\\007\\n", "2.20"),
             "escapes inside": ("biber version: \\033[31m2\\033[0m.21\\n", ""),
             "no version": ("\\033]0;owned\\007 rm -rf\\n", ""),
             "very long": ("biber version: " + "9" * 300 + ".1\\n", ""),
             "second line": ("hello\\nbiber version: 2.22\\n", "")}
    for label, (says, expected) in cases.items():
        folder = tmp_path / label
        decoy(folder, "biber", marker, says=says)
        monkeypatch.setenv("PATH", os.pathsep.join([str(folder), "/usr/bin", "/bin"]))
        assert texinstall.version("biber") == expected, label
        feature = {item.name: item for item in api.features()}["biber"]
        assert feature.version == (f"biber {expected}" if expected else "") and "\x1b" not in repr(api.as_data(feature))
    assert marker.exists()                                    # the programs really ran

    hostile = "ok \x1b[2J\x1b]0;title\x07\x00 line\r\nnext\ttab ‮ end"
    assert texinstall.shown(hostile) == "ok [2J]0;title line \nnext tab  end"
    assert texinstall.shown(hostile, lines=False) == "ok [2J]0;title line  next tab  end"
    assert len(texinstall.shown("x" * 10_000)) == texinstall.MAX_SHOWN and texinstall.shown("abc" * 1000, 5) == "bcabc"
    status, text = texinstall._run([sys.executable, "-c", "print('\\x1b[31mred\\x1b[0m\\x07' * 2000)"])
    assert status == 0 and "\x1b" in text and texinstall.shown(text).isprintable() and len(texinstall.shown(text)) <= texinstall.MAX_SHOWN


def test_an_interpreter_or_helper_planted_on_path_is_not_what_a_program_finds(tmp_path, monkeypatch):
    """A package manager that starts with `#!/usr/bin/env perl`, as tlmgr does, and one that
    calls a helper by name: a perl and a helper in an absolute folder that comes first on the
    user's PATH (the paper's folder, say) are not the ones that run."""
    if not os.path.exists("/usr/bin/perl"):
        pytest.skip("/usr/bin/perl is not installed (the test runs a real Perl script)")
    marker = tmp_path / "a planted program ran"
    planted = tmp_path / "paper"
    for name in ("perl", "sh", "env", "uname", "curl", "git", "wget", "gpg", "tar", "xz"):
        decoy(planted, name, marker)
    own = tmp_path / "installation" / "bin"
    own.mkdir(parents=True)
    manager = own / "manager"
    manager.write_text("#!/usr/bin/env perl\nprint 'perl ', `/usr/bin/which perl`; print `uname`; print \"PATH $ENV{PATH}\\n\";\n", encoding="utf-8")
    manager.chmod(0o755)
    helper = own / "helper"                                    # a helper beside the program is found, by name
    helper.write_text("#!/bin/sh\necho the helper of the installation\n", encoding="utf-8")
    helper.chmod(0o755)
    calls = own / "calls"
    calls.write_text("#!/bin/sh\nhelper\nuname\n", encoding="utf-8")
    calls.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([str(planted), os.environ["PATH"]]))
    monkeypatch.chdir(planted)
    assert shutil.which("perl") == str(planted / "perl") and shutil.which("uname") == str(planted / "uname")

    status, text = texinstall._run([str(manager)])
    assert status == 0 and not marker.exists(), text
    assert text.splitlines()[0] == "perl /usr/bin/perl" and text.splitlines()[1] == platform.system()
    folders = text.splitlines()[2].removeprefix("PATH ").split(os.pathsep)
    assert folders == [str(own), *texinstall.SYSTEM_PATH] and str(planted) not in folders
    status, text = texinstall._run([str(calls)])
    assert status == 0 and text.splitlines() == ["the helper of the installation", platform.system()] and not marker.exists()
    assert texinstall.environment([str(manager)])["PATH"] == os.pathsep.join([str(own), *texinstall.SYSTEM_PATH])
    linked = tmp_path / "links" / "manager"                    # found through a link: the folder it really lies in, too
    linked.parent.mkdir()
    os.symlink(manager, linked)
    assert texinstall.environment([str(linked)])["PATH"] == os.pathsep.join([str(linked.parent), str(own), *texinstall.SYSTEM_PATH])
    assert subprocess.run(["perl", "-e", "1"], capture_output=True).returncode == 0 and marker.exists()   # the planted perl is real


def test_homebrew_is_run_without_its_update_cleanup_and_dependents_check(tmp_path, monkeypatch):
    """A real program called brew, run as install() runs one: whatever the user's environment
    holds, it is told not to update Homebrew, not to clean up and not to touch dependents."""
    brew = tmp_path / "prefix" / "bin" / "brew"
    brew.parent.mkdir(parents=True)
    brew.write_text("#!/bin/sh\nenv | grep '^HOMEBREW' | sort\n", encoding="utf-8")
    brew.chmod(0o755)
    wanted = ["HOMEBREW_NO_AUTO_UPDATE=1", "HOMEBREW_NO_ENV_HINTS=1", "HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK=1",
              "HOMEBREW_NO_INSTALL_CLEANUP=1"]
    for name in list(os.environ):
        if name.startswith("HOMEBREW"):
            monkeypatch.delenv(name)
    status, text = texinstall._run([str(brew), "install", "biber"])
    assert status == 0 and sorted(text.splitlines()) == sorted(wanted)
    for name, value in (("HOMEBREW_NO_AUTO_UPDATE", "0"), ("HOMEBREW_NO_INSTALL_CLEANUP", ""), ("HOMEBREW_NO_ANALYTICS", "1"),
                        ("HOMEBREW_NO_INSTALL_UPGRADE", "yes"), ("HOMEBREW_CURLRC", "/tmp/x"), ("HOMEBREW_GIT", "/tmp/git"),
                        ("HOMEBREW_CASK_OPTS", "--appdir=/tmp")):
        monkeypatch.setenv(name, value)
    status, text = texinstall._run([str(brew), "install", "biber"])       # the user's opt-outs stay; nothing else of theirs
    assert status == 0 and sorted(text.splitlines()) == sorted(wanted + ["HOMEBREW_NO_ANALYTICS=1", "HOMEBREW_NO_INSTALL_UPGRADE=1"])
    other = tmp_path / "prefix" / "bin" / "tlmgr"
    other.write_text("#!/bin/sh\nenv | grep -c '^HOMEBREW'\n", encoding="utf-8")
    other.chmod(0o755)
    assert texinstall._run([str(other), "install", "biber"]) == (1, "0\n")       # only brew is given them


def test_homebrew_is_asked_about_every_time(ws, texenv, tmp_path, monkeypatch):
    """`brew install` changes software outside the TeX installation, so it is a question even
    without --ask: the core raises NeedsConfirmation, and without a terminal nothing is run
    and the message names the command."""
    from cdlbib import prompts
    brew = MissingProgram("biber", "Compiling a .bbl", ["/opt/homebrew/bin/brew", "install", "biber"], "brew install biber",
                          always_ask=True)
    tlmgr = MissingProgram("biber", "Compiling a .bbl", ["/tex/bin/tlmgr", "install", "biber"], "tlmgr install biber")
    assert deps.ask() is False and tlmgr.always_ask is False
    said = []
    assert api.consent(tlmgr, progress=said.append) is True and said == [prompts.install_line(tlmgr)]
    with pytest.raises(NeedsConfirmation) as asked:
        api.consent(brew, progress=said.append)
    assert asked.value.question == "Compiling a .bbl needs the TeX program 'biber'. Install it now (brew install biber)?"
    assert asked.value.__cause__ is brew and len(said) == 1
    assert api.consent(brew, allow=True) is True and api.consent(brew, allow=False) is False
    ran = []

    def run(allow_fork_creation=False):
        ran.append(1)
        raise brew
    with pytest.raises(NeedsConfirmation):
        api.attempt(run, progress=said.append)                 # asked before anything is installed
    with pytest.raises(MissingProgram):
        api.attempt(run, allow_install=False)
    assert len(ran) == 2 and len(said) == 1

    need("pdflatex", "kpsewhich", "biber")
    real = Path(shutil.which("kpsewhich")).resolve()
    for program in ("biber", "bibtex"):
        found = texinstall.plan(program)
        assert found.confirm == (bool(found.command) and Path(found.command[0]).name == "brew")
    if "Cellar" not in real.parts:
        return                                                 # the rest is this computer's own Homebrew
    file = paper(tmp_path / "paper", CITES, BIBLATEX)
    monkeypatch.setenv("PATH", path_without(tmp_path / "bin", "biber"))
    found = texinstall.plan("biber")
    assert found.confirm and found.shown == "brew install biber"
    assert texinstall.how("biber") == "Run: brew install biber (cdlbib export --bbl asks, then does this, when the program is needed)"
    with pytest.raises(MissingProgram) as stopped:
        export.bbl(ws, file)
    assert stopped.value.always_ask and stopped.value.command == found.command
    before = sorted(path.name for path in (Path(*real.parts[:real.parts.index("Cellar") + 1]) / "biber").iterdir())
    out = cdlbib("--library", str(ws.root), "export", str(file), "--bbl", cwd=tmp_path)      # no --ask, no terminal
    assert out.returncode == 1 and out.stdout == "" and "installing" not in out.stderr
    assert out.stderr.strip() == ("Compiling a .bbl needs the TeX program 'biber', which was not found on PATH "
                                  "(install: brew install biber)")
    assert not file.with_suffix(".bbl").exists()
    assert sorted(path.name for path in (Path(*real.parts[:real.parts.index("Cellar") + 1]) / "biber").iterdir()) == before


CHILD = ("import os, subprocess, sys, time\n"
         "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"     # inherits stdout
         "open(sys.argv[1], 'w').write(f'{os.getpid()} {child.pid}')\n"
         "print('started', flush=True)\n")


def gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_the_time_limit_covers_a_child_that_keeps_the_output_open(tmp_path):
    """A program that starts a sleeping child and exits at once: the child holds the pipe, so
    there is no end of output to read. One time limit covers the exit and the reading, and
    the child is ended with it."""
    import time
    pids = tmp_path / "pids"
    started = time.monotonic()
    status, text = texinstall._run([sys.executable, "-c", CHILD, str(pids)], timeout=4)
    took = time.monotonic() - started
    assert (status, text) == (None, "it did not finish within 4 seconds") and 3.5 < took < 12, took
    parent, child = (int(pid) for pid in pids.read_text().split())
    time.sleep(0.5)
    assert gone(child) and gone(parent)
    assert threading.active_count() < 20 and not [t for t in threading.enumerate() if t.name == "cdlbib-tex-output" and t.is_alive()]

    pids.unlink()                                             # a program that finishes leaves no one behind either
    quiet = CHILD.replace("subprocess.Popen([", "subprocess.Popen(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, args=[")
    started = time.monotonic()
    assert texinstall._run([sys.executable, "-c", quiet, str(pids)], timeout=30) == (0, "started\n")
    assert time.monotonic() - started < 10
    parent, child = (int(pid) for pid in pids.read_text().split())
    time.sleep(0.5)
    assert gone(child) and gone(parent)


def test_an_interrupted_run_leaves_no_program_behind(tmp_path):
    """Ctrl-C while a program is running: it, and the child it started, are ended."""
    import signal
    import time
    pids = tmp_path / "pids"
    slow = CHILD + "time.sleep(600)\n"
    outer = subprocess.Popen([sys.executable, "-c", "import sys; from cdlbib import texinstall\n"
                              f"texinstall._run([sys.executable, '-c', {slow!r}, {str(pids)!r}], timeout=300)"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 60
        while not (pids.exists() and len(pids.read_text().split()) == 2):
            assert time.monotonic() < deadline and outer.poll() is None, "the program did not start"
            time.sleep(0.1)
        parent, child = (int(pid) for pid in pids.read_text().split())
        assert not gone(parent) and not gone(child)
        outer.send_signal(signal.SIGINT)
        _, said = outer.communicate(timeout=60)
    finally:
        if outer.poll() is None:
            outer.kill()
    assert "KeyboardInterrupt" in said and outer.returncode != 0
    time.sleep(0.5)
    assert gone(parent) and gone(child)


# --- the control file: versions in a refusal, and the schemas of other bibers -----------------------

def real_bcf(folder):
    file = paper(folder, CITES, BIBLATEX)
    assert run("pdflatex", *FLAGS, "-draftmode", "main.tex", cwd=file.parent).returncode == 0
    return (file.parent / "main.bcf").read_text(encoding="utf-8")


def test_a_refusal_for_an_unknown_name_says_which_versions_were_found(ws, tmp_path):
    need("pdflatex", "biber")
    real = real_bcf(tmp_path / "paper")
    written = re.search(r'<bcf:controlfile version="([^"]+)" bltxversion="([^"]+)"', real)
    found = (f"Found here: biblatex {written.group(2)} (control file format {written.group(1)}) and biber "
             f"{texinstall.version('biber')}; the names that are passed on were derived from biber 2.22's schema of the file.")
    assert written.group(2) == texinstall.biblatex_version()
    for changed, name in ((real.replace("<bcf:datamodel>", "<bcf:newthing/><bcf:datamodel>"), "newthing"),
                          (real.replace("<bcf:datamodel>", '<bcf:datamodel newattribute="1">'), "newattribute")):
        with pytest.raises(ExportFailed) as refused:
            export.own_bcf(changed.encode("utf-8"), ["cdl"])
        assert refused.value.kind == "control_file" and refused.value.names == [name]
        assert f"this version does not know: {name}. {found} No .bbl was compiled." in str(refused.value)
    odd = real.replace(f'bltxversion="{written.group(2)}"', 'bltxversion="3.21 &lt;x&gt;"').replace("<bcf:datamodel>", "<bcf:newthing/><bcf:datamodel>")
    with pytest.raises(ExportFailed, match="biblatex not stated"):            # only a plain version is repeated
        export.own_bcf(odd.encode("utf-8"), ["cdl"])


def test_every_name_in_bibers_schemas_since_2_14_is_one_the_allowlist_has():
    """The official schema of each biber release from 2.14 to 2.22 (scripts/bcf_schema_names.py
    reads them from biber's repository): no element and no child element is missing here, and
    the only attributes that are missing are the two a source map step is refused for."""
    assert sorted(SCHEMAS) == ["2.14", "2.15", "2.16", "2.17", "2.18", "2.19", "2.20", "2.21", "2.22"]
    for release, elements in SCHEMAS.items():
        assert len(elements) >= 68 and "controlfile" in elements
        for name, (attributes, children, holds_text) in elements.items():
            assert name in export.BCF_SHAPE, (release, name)
            listed, inside, text = export.BCF_SHAPE[name]
            assert set(children) <= set(inside), (release, name)
            assert not holds_text or text, (release, name)
            beyond = set(attributes) - set(listed)
            assert beyond <= ({"map_matches", "map_matchesi"} if name == "map_step" else set()), (release, name, beyond)
    assert all("lang" in SCHEMAS[release]["value"][0] for release in ("2.14", "2.15", "2.16", "2.17", "2.18"))
    assert all("lang" not in SCHEMAS[release]["value"][0] for release in ("2.19", "2.20", "2.21", "2.22"))
    assert set(export.BCF_SHAPE) - set(SCHEMAS["2.22"]) == {"nolabelwidthcount", "nolabelwidthcounts"}
    assert set(SCHEMAS["2.22"]) - set(SCHEMAS["2.19"]) == {"namehashtemplate"}       # all that 2.20 to 2.22 added


def test_a_value_with_the_lang_attribute_of_the_older_schemas_is_passed_on(ws, tmp_path):
    """lang on a value is in biber's schemas up to 2.18. The control file keeps it, and the
    installed biber compiles the same bibliography from that file."""
    need("pdflatex", "biber")
    real = real_bcf(tmp_path / "paper")
    plain = re.search(r'<bcf:key>labelnamespec</bcf:key>\s*<bcf:value order="1">', real)
    assert plain, "biblatex wrote no labelnamespec"
    older = real.replace(plain.group(0), plain.group(0)[:-1] + ' lang="en">', 1)
    rewritten = export.own_bcf(older.encode("utf-8"), ["cdl"]).decode("utf-8")
    assert '<bcf:value lang="en" order="1">' in rewritten

    made = {}
    for label, text in (("as written", real), ("with lang", older)):
        folder = tmp_path / label
        folder.mkdir()
        (folder / "cdl.bib").write_text(ws.bib.read_text(encoding="utf-8"), encoding="utf-8")
        (folder / "job.bcf").write_bytes(export.own_bcf(text.encode("utf-8"), ["cdl"]))
        done = run("biber", "--noconf", "job", cwd=folder)
        assert done.returncode == 0 and "ERROR" not in done.stdout, done.stdout[-1500:]
        made[label] = (folder / "job.bbl").read_text(encoding="utf-8")
    assert "\\entry{Zoll90}" in made["as written"] and made["with lang"] == made["as written"]


# --- a real installation, into a TeX Live of the tests' own ------------------------------------------

TINYTEX = "https://github.com/rstudio/tinytex-releases/releases/download/v2026.10/TinyTeX-1-{system}-v2026.10.tar.xz"
SYSTEMS = {("Darwin", "arm64"): "darwin", ("Darwin", "x86_64"): "darwin", ("Linux", "x86_64"): "linux-x86_64",
           ("Linux", "aarch64"): "linux-arm64"}
installs = pytest.mark.skipif(os.environ.get("CDLBIB_TEST_TEX_INSTALL") != "1",
                              reason="downloads a TeX Live and biber (about 140 MB); set CDLBIB_TEST_TEX_INSTALL=1 to run")


@pytest.fixture(scope="module")
def texlive(tmp_path_factory):
    """A TeX Live this user owns, with LaTeX, bibtex and biblatex but no biber: its bin folder.
    TinyTeX's release of TeX Live 2026; tlmgr refuses to install from a later year's repository."""
    system = SYSTEMS.get((platform.system(), platform.machine()))
    if not system:
        pytest.skip(f"no TinyTeX is published for {platform.system()} {platform.machine()}")
    folder = tmp_path_factory.mktemp("texlive")
    archive = folder / "tinytex.tar.xz"
    with urllib.request.urlopen(TINYTEX.format(system=system), timeout=600) as reply, open(archive, "wb") as out:
        shutil.copyfileobj(reply, out)
    with tarfile.open(archive) as packed:
        packed.extractall(folder, filter="tar")
    archive.unlink()
    (bin_folder,) = [path for path in (folder / "TinyTeX" / "bin").iterdir() if path.is_dir()]
    env = dict(os.environ, PATH=os.pathsep.join([str(bin_folder), "/usr/bin", "/bin"]))
    done = subprocess.run([str(bin_folder / "tlmgr"), "install", "biblatex", "logreq"], env=env, capture_output=True, text=True)
    assert done.returncode == 0 and (folder / "TinyTeX/texmf-dist/tex/latex/biblatex/biblatex.sty").is_file(), done.stderr[-1500:]
    assert (bin_folder / "pdflatex").exists() and (bin_folder / "bibtex").exists() and not (bin_folder / "biber").exists()
    return bin_folder


@pytest.fixture
def on_texlive(texlive, texenv, monkeypatch):
    """This process, and every program it starts, sees only the tests' TeX Live."""
    monkeypatch.setenv("PATH", os.pathsep.join([str(texlive), "/usr/bin", "/bin"]))
    texinstall.version.cache_clear()
    yield texlive
    texinstall.version.cache_clear()


@installs
def test_user_mode_of_tlmgr_does_not_install_biber(on_texlive, tmp_path):
    tree = tmp_path / "user tree"
    env = dict(os.environ, TEXMFHOME=str(tree))
    assert subprocess.run(["tlmgr", "--usermode", "init-usertree"], env=env, capture_output=True, text=True).returncode == 0
    said = subprocess.run(["tlmgr", "--usermode", "install", "biber"], env=env, capture_output=True, text=True)
    assert "package biber is not relocatable, cannot install it in user mode" in said.stdout + said.stderr
    assert shutil.which("biber") is None and not list(tree.rglob("biber*"))


@installs
def test_a_tex_live_that_is_not_writable_is_not_installed_into(on_texlive, ws, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can write anywhere")
    file = paper(tmp_path / "paper", CITES, BIBLATEX)
    database = on_texlive.parents[1] / "tlpkg"
    mode = stat.S_IMODE(database.stat().st_mode)
    database.chmod(mode & ~0o222)
    try:
        found = texinstall.plan("biber")
        assert (found.distribution, found.command, found.manual) == ("texlive", [], "Run: sudo tlmgr install biber")
        assert found.why == f"{database} is not writable by this user, and sudo is never run from here"
        with pytest.raises(ExportFailed) as refused:
            api.attempt(lambda allow_fork_creation=False: api.export_bbl(ws, file))
        assert refused.value.kind == "no_tex" and "Run: sudo tlmgr install biber" in str(refused.value)
        with pytest.raises(CdlbibError, match="biber cannot be installed from here"):
            texinstall.install("biber")
    finally:
        database.chmod(mode)
    assert shutil.which("biber") is None and not file.with_suffix(".bbl").exists()


@installs
def test_a_failed_installation_is_reported_in_printable_bounded_text(on_texlive, tmp_path, monkeypatch):
    """A tlmgr that cannot reach its repository: the real failure, with tlmgr's own words."""
    said = subprocess.run(["tlmgr", "option", "repository"], capture_output=True, text=True).stdout
    repository = re.search(r"\(repository\): (\S+)", said).group(1)
    assert subprocess.run(["tlmgr", "option", "repository", "http://127.0.0.1:9/none"], capture_output=True).returncode == 0
    monkeypatch.setenv("TEXMFCNF", str(tmp_path / "not a texmf.cnf folder"))      # would break kpsewhich; it is not passed on
    try:
        with pytest.raises(CdlbibError) as failed:
            deps.install("tex", package="biber")
    finally:
        assert subprocess.run(["tlmgr", "option", "repository", repository], capture_output=True,
                              env={k: v for k, v in os.environ.items() if k != "TEXMFCNF"}).returncode == 0
    message = str(failed.value)
    assert message.startswith("install failed (tlmgr install biber)") or message.startswith("tlmgr install biber finished, but")
    assert "127.0.0.1" in message and all(char.isprintable() or char == "\n" for char in message)
    assert len(message) < texinstall.MAX_SHOWN + 200 and shutil.which("biber") is None


@installs
def test_with_ask_and_no_terminal_nothing_is_installed(on_texlive, ws, tmp_path):
    file = paper(tmp_path / "paper", CITES, BIBLATEX)
    assert texinstall.plan("biber").command == [str(on_texlive / "tlmgr"), "install", "biber"]
    out = cdlbib("--ask", "--library", str(ws.root), "export", str(file), "--bbl", cwd=tmp_path)
    assert out.returncode == 1 and out.stdout == ""
    assert out.stderr.strip() == ("Compiling a .bbl needs the TeX program 'biber', which was not found on PATH "
                                  "(install: tlmgr install biber)")
    assert shutil.which("biber") is None and not file.with_suffix(".bbl").exists()


@installs
def test_the_terminal_interfaces_worker_asks_then_installs_biber(on_texlive, ws, tmp_path):
    """The job worker of the terminal interface (the same api.attempt the web server's jobs go
    through): with --ask the question comes up; no leaves biber uninstalled; yes installs it
    with tlmgr and the same job writes the .bbl."""
    pytest.importorskip("textual")
    from cdlbib.tui.worker import Runner
    file = paper(tmp_path / "paper", CITES, BIBLATEX)
    question = "Compiling a .bbl needs the TeX program 'biber'. Install it now (tlmgr install biber)?"

    def attempt(answer):
        said, asked, ended, finished = [], [], {}, threading.Event()

        def ask(text):
            asked.append(text)
            return answer
        runner = Runner(on_ui=lambda function, *args: function(*args), say=said.append, ask=ask)
        runner.submit("export", lambda running: api.export_bbl(ws, file),
                      done=lambda made: (ended.update(made=made), finished.set()),
                      failed=lambda exc: (ended.update(failed=exc), finished.set()))
        assert finished.wait(900)
        runner.stop()
        return said, asked, ended

    deps.set_ask(True)
    try:
        said, asked, ended = attempt(False)
        assert asked == [question] and isinstance(ended["failed"], MissingProgram)
        assert shutil.which("biber") is None and not file.with_suffix(".bbl").exists()
        said, asked, ended = attempt(True)
    finally:
        deps.set_ask(False)
    assert asked == [question] and "failed" not in ended, ended
    assert shutil.which("biber") == str(on_texlive / "biber") and ended["made"].backend == "biber"
    assert "\\entry{Zoll90}" in file.with_suffix(".bbl").read_text(encoding="utf-8")
    assert re.fullmatch(r"\d+\.\d+", texinstall.version("biber"))
    out = cdlbib("--library", str(ws.root), "setup", "--check", cwd=tmp_path)
    assert f"  biber: yes ({on_texlive / 'biber'}; biber {texinstall.version('biber')}, biblatex {texinstall.biblatex_version()})" in out.stdout


@installs
def test_without_ask_a_missing_bibtex_is_announced_installed_and_used(on_texlive, ws, tmp_path):
    removed = subprocess.run(["tlmgr", "remove", "--force", "bibtex"], capture_output=True, text=True)
    assert removed.returncode == 0 and shutil.which("bibtex") is None, removed.stdout[-800:] + removed.stderr[-800:]
    file = paper(tmp_path / "paper", "\\cite{Zoll90}\n" + PLAIN)
    marker = tmp_path / "a planted program ran"               # tlmgr is a Perl script found by `env perl`, and calls helpers
    for name in ("perl", "curl", "wget", "xz", "tar", "gpg", "uname"):
        decoy(tmp_path / "planted", name, marker)
    out = cdlbib("--library", str(ws.root), "export", str(file), "--bbl", cwd=tmp_path,
                 PATH=os.pathsep.join([str(tmp_path / "planted"), os.environ["PATH"]]))
    assert out.returncode == 0, out.stderr
    assert not marker.exists()
    assert out.stdout.splitlines()[0] == "installing bibtex (needed for: Compiling a .bbl) with: tlmgr install bibtex ..."
    assert out.stdout.splitlines()[-1] == f"wrote {file.with_suffix('.bbl').resolve()}: bibtex, style plain, pdflatex, 1 cited key"
    assert shutil.which("bibtex") == str(on_texlive / "bibtex")
    assert "\\bibitem{Zoll90}" in file.with_suffix(".bbl").read_text(encoding="utf-8")
    again = cdlbib("--library", str(ws.root), "export", str(file), "--bbl", "--force", cwd=tmp_path)    # nothing left to install
    assert again.returncode == 0 and "installing" not in again.stdout
