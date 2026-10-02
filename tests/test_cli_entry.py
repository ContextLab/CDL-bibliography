"""The cdlbib console command, run as a real subprocess from outside and inside a library."""
import os
import subprocess
import sys
from pathlib import Path
import shutil

from cdlbib import deps

# The command of the environment running the tests, not another one that is on PATH.
_SIBLING = Path(sys.executable).parent / "cdlbib"
CDLBIB = str(_SIBLING) if _SIBLING.exists() else shutil.which("cdlbib")


def run(*args, cwd, env=None):
    return subprocess.run([CDLBIB, *args], cwd=cwd, capture_output=True, text=True,
                          env=dict(os.environ, **(env or {})))


def test_help_and_version_work_outside_a_library(tmp_path):
    assert run("--help", cwd=tmp_path).returncode == 0
    out = run("--version", cwd=tmp_path)
    assert out.returncode == 0 and out.stdout.strip() == "cdlbib 2.0.0"


def test_library_command_outside_a_library_uses_the_downloaded_one(tmp_path):
    """No library named or found: the managed library is downloaded into CDLBIB_HOME (a folder of
    this test run, from the local upstream of tests/conftest.py) and the command reports on it."""
    managed = Path(os.environ["CDLBIB_HOME"]).resolve() / "library"
    out = run("verify", "--no-citations", cwd=tmp_path, env={"CDLBIB_LIBRARY": ""})
    assert out.returncode == 0 and "looks good!" in out.stdout, out.stdout + out.stderr
    assert f"loading {managed / 'cdl.bib'}...done" in out.stdout and "Traceback" not in out.stderr
    assert (managed / ".git").is_dir() and (managed / "cdl.bib").is_file()


def test_library_option_and_spaces_in_the_path(tmp_path):
    root = tmp_path / "My Papers – lib"
    root.mkdir()
    (root / "cdl.bib").write_text("", encoding="utf-8")
    out = run("--library", str(root), "verify", "--no-citations", cwd=tmp_path)
    assert out.returncode == 0 and "looks good!" in out.stdout


def test_the_old_entry_points_are_gone():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "bibcheck.py").exists() and not (root / "bibverify.py").exists()
    assert not (root / "bibcheck").exists()


def test_crossref_commands_find_the_library(tmp_path):
    from test_machinery_2026_09_25 import ZOLL90
    root = tmp_path / "lib"
    (root / "sub").mkdir(parents=True)
    (root / "cdl.bib").write_text(ZOLL90 + "\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for args, cwd in ((("crossref", "status"), root / "sub"),
                      (("--library", str(root), "crossref", "status"), elsewhere)):
        out = run(*args, cwd=cwd, env={"CDLBIB_LIBRARY": ""})
        assert out.returncode == 1 and "1 entries: pending=1" in out.stdout, out.stdout + out.stderr
    assert (root / ".bibcheck" / "verification.sqlite3").is_file()
    # outside any library, the crossref commands too fall back to the managed (downloaded) one
    managed = Path(os.environ["CDLBIB_HOME"]).resolve() / "library"
    out = run("crossref", "status", cwd=elsewhere, env={"CDLBIB_LIBRARY": ""})
    assert out.returncode == 1 and "1 entries: pending=1" in out.stdout, out.stdout + out.stderr
    assert "Traceback" not in out.stderr and (managed / ".bibcheck" / "verification.sqlite3").is_file()


def test_adapters_are_commands_found_by_name(tmp_path):
    import pytest
    from cdlbib.research import invoke_adapter, locate_adapter
    bin_dir = Path(CDLBIB).parent
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "DARTMOUTH_CHAT_API_KEY": "", "OPENAI_API_KEY": ""}
    for name in ("cdlbib-adapter-dartmouth", "cdlbib-adapter-openai"):
        assert (bin_dir / name).is_file()
        # No key: the adapter itself runs and reports the failure without a traceback.
        out = subprocess.run([str(bin_dir / name)], input="{}", capture_output=True, text=True,
                             cwd=tmp_path, env=dict(os.environ, **env))
        assert out.returncode == 2 and "adapter failed: " in out.stderr and "Traceback" not in out.stderr
    saved = os.environ["PATH"]
    os.environ["PATH"] = env["PATH"]
    try:
        assert locate_adapter("cdlbib-adapter-dartmouth") == (bin_dir / "cdlbib-adapter-dartmouth").resolve()
        with pytest.raises(FileNotFoundError):
            invoke_adapter("cdlbib-adapter-that-does-not-exist", {})
    finally:
        os.environ["PATH"] = saved


def test_one_default_library_rule_for_every_command(tmp_path):
    """CDLBIB_LIBRARY outranks a cdl.bib in the current folder, for `verify` and for
    `crossref` alike; --library outranks the variable; a file the user names outranks all."""
    from test_machinery_2026_09_25 import RAME72, ZOLL90
    a, b = (tmp_path / "A").resolve(), (tmp_path / "B").resolve()
    for folder, text in ((a, ZOLL90 + "\n\n" + RAME72 % "1" + "\n"), (b, ZOLL90 + "\n")):  # A: 2 entries, B: 1
        folder.mkdir()
        (folder / "cdl.bib").write_text(text, encoding="utf-8")
    env = {"CDLBIB_LIBRARY": str(b)}

    out = run("verify", "--no-citations", cwd=a, env=env)
    assert out.returncode == 0 and f"loading {b / 'cdl.bib'}...done" in out.stdout, out.stdout + out.stderr
    out = run("crossref", "status", cwd=a, env=env)
    assert out.returncode == 1 and "1 entries: pending=1" in out.stdout, out.stdout + out.stderr
    assert (b / ".bibcheck").is_dir() and not (a / ".bibcheck").exists()

    # --library outranks the variable
    out = run("--library", str(a), "verify", "--no-citations", cwd=b, env=env)
    assert out.returncode == 0 and f"loading {a / 'cdl.bib'}...done" in out.stdout, out.stdout + out.stderr
    out = run("--library", str(a), "crossref", "status", cwd=b, env=env)
    assert out.returncode == 1 and "2 entries: pending=2" in out.stdout, out.stdout + out.stderr

    # a file the user names outranks both, even when it is named cdl.bib
    out = run("--library", str(b), "verify", "--fname", "cdl.bib", "--no-citations", cwd=a, env=env)
    assert out.returncode == 0 and "loading cdl.bib...done" in out.stdout, out.stdout + out.stderr
    out = run("--library", str(b), "crossref", "status", "cdl.bib", "--database", str(tmp_path / "x.sqlite3"),
              "--report", str(tmp_path / "x.jsonl"), cwd=a, env=env)
    assert out.returncode == 1 and "2 entries: pending=2" in out.stdout, out.stdout + out.stderr


def test_status_and_compare_failures_keep_their_exit_codes(tmp_path):
    from test_machinery_2026_09_25 import ZOLL90
    lib = tmp_path / "lib.bib"
    lib.write_text(ZOLL90 + "\n", encoding="utf-8")
    keys = tmp_path / "keys.txt"
    keys.write_text("NotInTheLibrary99\n", encoding="utf-8")
    out = run("crossref", "status", str(lib), "--keys", str(keys), cwd=tmp_path)
    assert out.returncode == 2 and "Traceback" not in out.stderr
    assert out.stderr.strip() == "Key list is empty or contains citation keys absent from the bibliography"
    out = run("compare", str(lib), str(tmp_path / "missing.bib"), cwd=tmp_path)
    assert out.returncode == 1 and "missing.bib" in out.stderr and "Traceback" not in out.stderr


# --- optional packages installed on demand -------------------------------------------------

MANUAL = "pip install 'pypdf<7,>=6.0'"  # what the installed metadata lists for the research extra
DUMMY_PDF = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"

ADAPTER = '''import json, sys
payload = json.load(sys.stdin)
if payload["phase"] == "discover":
    print(json.dumps({"landing_url": "%s", "pdf_url": "%s"}))
else:
    print(json.dumps({"fields": {"title": {"value": "Dummy PDF file", "page": 1, "quote": "Dummy PDF file"}},
                      "uncertainties": []}))
''' % (DUMMY_PDF, DUMMY_PDF)

SEED = '''import sys
from pathlib import Path
from cdlbib.verification import Cache, load_entries
bib = Path(sys.argv[1])
cache = Cache(Path(sys.argv[2]))
for entry in load_entries(bib).values():
    cache.put(bib, entry, {"status": "needs_review"})
'''


def core_environment(tmp_path):
    """A real throwaway environment with cdlbib installed WITHOUT the research extra, a
    library with one entry awaiting review, and a research adapter. Returns (python, args)."""
    import pytest
    if not shutil.which("uv"):
        pytest.skip("uv is needed to build the scratch environment")
    root = Path(__file__).resolve().parents[1]
    env = tmp_path / "core"
    python = str(env / "bin" / "python")
    subprocess.run(["uv", "venv", "-q", str(env), "--python", sys.executable], check=True)
    subprocess.run(["uv", "pip", "install", "-q", "--python", python, str(root)], check=True)
    assert subprocess.run([python, "-c", "import pypdf"], capture_output=True).returncode != 0
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "cdl.bib").write_text("@book{Test20,\n  Title = {Dummy PDF file},\n  Year = {2020}\n}\n", encoding="utf-8")
    (tmp_path / "adapter.py").write_text(ADAPTER, encoding="utf-8")
    (tmp_path / "seed.py").write_text(SEED, encoding="utf-8")
    database = tmp_path / "cache.sqlite3"
    subprocess.run([python, str(tmp_path / "seed.py"), str(lib / "cdl.bib"), str(database)], check=True)
    args = ["research-batch", str(lib / "cdl.bib"), "--adapter", str(tmp_path / "adapter.py"),
            "--allow-host", "www.w3.org", "--database", str(database), "--limit", "1"]
    return python, args


def cdlbib_in(python, *args, cwd, path=None, **kwargs):
    env = dict(os.environ, CDLBIB_LIBRARY="")
    if path is not None:
        env["PATH"] = path
    return subprocess.run([str(Path(python).parent / "cdlbib"), *args], cwd=cwd, capture_output=True, text=True,
                          env=env, **kwargs)


def test_ask_without_a_terminal_refuses_with_the_manual_command(tmp_path):
    """research-batch needs pypdf (extra 'research'); in an environment installed without it, with
    --ask and no terminal, nothing is installed and nothing is asked."""
    python, args = core_environment(tmp_path)
    run = cdlbib_in(python, "--ask", "crossref", *args, cwd=tmp_path, stdin=subprocess.DEVNULL)
    assert run.returncode == 1, run.stdout + run.stderr
    assert MANUAL in run.stderr and "Reading PDF files" in run.stderr
    assert "Traceback" not in run.stderr and "[y/N]" not in run.stdout + run.stderr
    assert subprocess.run([python, "-c", "import pypdf"], capture_output=True).returncode != 0


def test_declining_the_prompt_at_a_terminal_installs_nothing(tmp_path):
    import pty
    python, args = core_environment(tmp_path)
    leader, follower = pty.openpty()
    os.write(leader, b"n\n")
    try:
        run = cdlbib_in(python, "--ask", "crossref", *args, cwd=tmp_path, stdin=follower)
    finally:
        os.close(follower)
        os.close(leader)
    assert run.returncode == 1 and "Install it now? [y/N]" in run.stdout + run.stderr, run.stdout + run.stderr
    assert MANUAL in run.stderr and "Traceback" not in run.stderr
    assert subprocess.run([python, "-c", "import pypdf"], capture_output=True).returncode != 0


def test_by_default_the_extra_is_installed_without_asking_and_the_command_proceeds(tmp_path):
    python, args = core_environment(tmp_path)
    run = cdlbib_in(python, "crossref", *args, cwd=tmp_path, stdin=subprocess.DEVNULL)
    assert subprocess.run([python, "-c", "import pypdf"], capture_output=True).returncode == 0, run.stdout + run.stderr
    assert "installing pypdf (needed for: Reading PDF files) ..." in run.stdout and "[y/N]" not in run.stdout + run.stderr
    assert run.returncode == 0 and "Research 1: Test20: " in run.stdout, run.stdout + run.stderr
    assert "Traceback" not in run.stderr and "needs the package" not in run.stderr


def test_no_installer_is_an_error_with_the_manual_command_and_no_second_try(tmp_path):
    """The environment has no pip and uv is not on PATH: one error, exit 1, no traceback."""
    python, args = core_environment(tmp_path)
    nothing = tmp_path / "empty"
    nothing.mkdir()
    run = cdlbib_in(python, "crossref", *args, cwd=tmp_path, stdin=subprocess.DEVNULL, path=str(nothing))
    assert run.returncode == 1 and "No installer found" in run.stderr, run.stdout + run.stderr
    assert MANUAL in run.stderr and "Traceback" not in run.stderr
    assert subprocess.run([python, "-c", "import pypdf"], capture_output=True).returncode != 0


def single_entry_args(tmp_path):
    return ["research", "Test20", "--adapter", str(tmp_path / "adapter.py"), "--allow-host", "www.w3.org",
            "--fname", str(tmp_path / "lib" / "cdl.bib"), "--database", str(tmp_path / "cache.sqlite3")]


def test_single_entry_research_installs_too(tmp_path):
    """`crossref research KEY` used to swallow the missing package as 'Research unresolved'."""
    python, _ = core_environment(tmp_path)
    args = single_entry_args(tmp_path)
    run = cdlbib_in(python, "--ask", "crossref", *args, cwd=tmp_path, stdin=subprocess.DEVNULL)
    assert run.returncode == 1 and MANUAL in run.stderr, run.stdout + run.stderr
    assert "Traceback" not in run.stderr and "Research unresolved" not in run.stderr
    assert subprocess.run([python, "-c", "import pypdf"], capture_output=True).returncode != 0
    run = cdlbib_in(python, "crossref", *args, cwd=tmp_path, stdin=subprocess.DEVNULL)
    assert subprocess.run([python, "-c", "import pypdf"], capture_output=True).returncode == 0, run.stdout + run.stderr
    assert run.returncode == 0 and "PDF evidence saved" in run.stdout, run.stdout + run.stderr


def test_end_of_input_at_the_prompt_aborts_cleanly(tmp_path):
    """EOF (Ctrl-D) at the prompt, on a real pty. A real Ctrl-C cannot be delivered to a child from
    a test without a controlling terminal, so it is not tested; click turns both into the same Abort."""
    import pty
    python, args = core_environment(tmp_path)
    leader, follower = pty.openpty()
    os.write(leader, b"\x04")
    try:
        run = cdlbib_in(python, "--ask", "crossref", *args, cwd=tmp_path, stdin=follower)
    finally:
        os.close(follower)
        os.close(leader)
    assert run.returncode == 1 and "Aborted." in run.stderr and "Traceback" not in run.stderr, run.stdout + run.stderr
    assert subprocess.run([python, "-c", "import pypdf"], capture_output=True).returncode != 0


def test_dartmouth_models_without_a_usable_key_is_one_line_not_a_traceback(tmp_path):
    """`python -m cdlbib.dartmouth_models` with a key that cannot be one (it has a space): the
    message on stderr, exit 2, nothing fetched. (A malformed key is refused before the
    keychain or the network is consulted, so the run is the same on every machine.)"""
    done = subprocess.run([sys.executable, "-m", "cdlbib.dartmouth_models"], cwd=tmp_path, capture_output=True,
                          text=True, env=dict(os.environ, DARTMOUTH_CHAT_API_KEY="not a key"))
    assert done.returncode == 2 and done.stdout == ""
    assert done.stderr == "Dartmouth key must be a single token\n"


def test_verify_help_names_no_internal_function(tmp_path):
    shown = run("verify", "--help", cwd=tmp_path)
    assert shown.returncode == 0 and "check_library" not in shown.stdout
    assert "Format check, then citation verification" in shown.stdout


def test_every_top_level_command_has_a_help_description(tmp_path):
    import re
    out = run("--help", cwd=tmp_path)
    assert out.returncode == 0
    for name in ("verify", "compare", "send", "where", "crossref"):
        line = next((l for l in out.stdout.splitlines() if re.match(rf"^│ {name}\s", l)), None)
        assert line is not None, f"{name} is not listed in --help"
        description = line.strip("│ \n").removeprefix(name).strip()
        assert description, f"{name} has no description in --help"


def test_ask_is_listed_in_help_and_yes_and_magic_are_gone(tmp_path):
    out = run("--help", cwd=tmp_path, env={"COLUMNS": "200"})
    assert out.returncode == 0
    assert "--ask" in out.stdout and "Ask before installing a missing package or creating your fork." in out.stdout
    assert "--yes" not in out.stdout and "magic" not in out.stdout
    refused = run("--yes", "verify", "--no-citations", cwd=tmp_path)
    assert refused.returncode == 2 and "No such option" in refused.stderr and "--yes" in refused.stderr
    gone = run("magic", cwd=tmp_path)
    assert gone.returncode == 2 and "No such command" in gone.stderr


def refusal(login="someone", upstream="no_such_owner/x"):
    from cdlbib.errors import PublishRefused
    return PublishRefused(f"@{login} has no fork of {upstream}.", needs_fork=True, upstream=upstream)


def test_by_default_the_fork_is_to_be_created_and_the_line_says_so(capsys):
    """The decision only: the function returns True and prints; it never runs `gh repo fork`
    (that is api.send's job, reached only with allow_fork_creation=True)."""
    from cdlbib import cli
    assert deps.ask() is False
    assert cli.fork_wanted(refusal("someone", "no_such_owner/library")) is True
    assert capsys.readouterr().out == "creating your fork someone/library ...\n"


def test_with_ask_and_no_terminal_no_fork_is_wanted_and_nothing_is_printed(capsys, monkeypatch):
    from cdlbib import cli
    monkeypatch.setattr(sys, "stdin", open(os.devnull))     # no terminal
    deps.set_ask(True)
    try:
        assert cli.fork_wanted(refusal()) is False
    finally:
        deps.set_ask(False)
    assert capsys.readouterr().out == ""
