"""The cdlbib console command, run as a real subprocess from outside and inside a library."""
import os
import subprocess
import sys
from pathlib import Path
import shutil

CDLBIB = shutil.which("cdlbib") or str(Path(sys.executable).parent / "cdlbib")


def run(*args, cwd, env=None):
    return subprocess.run([CDLBIB, *args], cwd=cwd, capture_output=True, text=True,
                          env=dict(os.environ, **(env or {})))


def test_help_and_version_work_outside_a_library(tmp_path):
    assert run("--help", cwd=tmp_path).returncode == 0
    out = run("--version", cwd=tmp_path)
    assert out.returncode == 0 and out.stdout.strip() == "cdlbib 2.0.0"


def test_library_command_outside_a_library_explains(tmp_path):
    out = run("verify", "--no-citations", cwd=tmp_path, env={"CDLBIB_LIBRARY": ""})
    assert out.returncode == 2 and "No library found" in out.stderr and "Traceback" not in out.stderr


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
    out = run("crossref", "status", cwd=elsewhere, env={"CDLBIB_LIBRARY": ""})
    assert out.returncode == 2 and "No library found" in out.stderr and "Traceback" not in out.stderr


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
