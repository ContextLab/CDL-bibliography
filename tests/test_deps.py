import re
import shutil
import subprocess
import sys

import pytest

from cdlbib import deps
from cdlbib.errors import CdlbibError, MissingDependency


def test_need_returns_an_installed_module():
    assert deps.need("json", "research", "anything").dumps({}) == "{}"


def test_need_raises_with_package_extra_and_feature():
    with pytest.raises(MissingDependency) as err:
        deps.need("a_module_that_does_not_exist_xyz", "research", "Reading PDFs")
    assert (err.value.package, err.value.extra, err.value.feature) == ("a_module_that_does_not_exist_xyz", "research", "Reading PDFs")
    assert deps.manual_command("research", "pypdf") in str(err.value)


def has(python, module):
    return subprocess.run([python, "-c", f"import {module}"], capture_output=True).returncode == 0


def test_install_with_pip(tmp_path):
    subprocess.run([sys.executable, "-m", "venv", str(tmp_path / "v")], check=True)
    python = str(tmp_path / "v" / "bin" / "python")
    assert deps.installer(python)[:3] == [python, "-m", "pip"]
    assert not has(python, "iniconfig")
    deps.install("research", python=python, requirement="iniconfig")
    assert has(python, "iniconfig")


def test_install_into_an_environment_without_pip_uses_uv(tmp_path):
    if not shutil.which("uv"):
        pytest.skip("uv is not installed here")
    subprocess.run(["uv", "venv", "-q", str(tmp_path / "u"), "--python", sys.executable], check=True)
    python = str(tmp_path / "u" / "bin" / "python")
    assert not has(python, "pip")
    assert deps.installer(python)[:3] == ["uv", "pip", "install"]
    deps.install("research", python=python, requirement="iniconfig")
    assert has(python, "iniconfig")


def test_no_installer_gives_the_manual_command(tmp_path, monkeypatch):
    if not shutil.which("uv"):
        pytest.skip("uv is needed to make an environment without pip")
    subprocess.run(["uv", "venv", "-q", str(tmp_path / "u"), "--python", sys.executable], check=True)
    python = str(tmp_path / "u" / "bin" / "python")
    monkeypatch.setenv("PATH", str(tmp_path))            # uv can no longer be found
    with pytest.raises(CdlbibError, match=re.escape(deps.manual_command("research", "pypdf"))):
        deps.install("research", python=python)


def test_failed_install_is_an_error_not_a_silent_pass(tmp_path):
    subprocess.run([sys.executable, "-m", "venv", str(tmp_path / "v")], check=True)
    python = str(tmp_path / "v" / "bin" / "python")
    with pytest.raises(CdlbibError, match="install failed"):
        deps.install("research", python=python, requirement="a-package-that-does-not-exist-xyz-12345")


def test_ask_is_one_store_and_defaults_to_false():
    """Off by default: a missing package is installed without a question."""
    assert deps.ask() is False
    deps.set_ask(True)
    try:
        assert deps.ask() is True
    finally:
        deps.set_ask(False)


def test_requirements_come_from_the_installed_metadata():
    assert deps.requirements_for("research") == ["pypdf<7,>=6.0"]
    assert deps.manual_command("research", "pypdf") == "pip install 'pypdf<7,>=6.0'"


def test_an_unknown_extra_is_an_error_naming_what_to_install_by_hand():
    with pytest.raises(CdlbibError, match=r"no requirements for the extra 'nope'.*pip install 'somepkg'"):
        deps.requirements_for("nope", "somepkg")


def test_install_by_requirements_from_metadata_into_a_scratch_environment(tmp_path):
    """The by-metadata path (no requirement= hook): cdlbib is installed there, the extra is not."""
    from pathlib import Path
    if not shutil.which("uv"):
        pytest.skip("uv is needed to build the scratch environment")
    root = Path(__file__).resolve().parents[1]
    python = str(tmp_path / "e" / "bin" / "python")
    subprocess.run(["uv", "venv", "-q", str(tmp_path / "e"), "--python", sys.executable], check=True)
    subprocess.run(["uv", "pip", "install", "-q", "--python", python, str(root)], check=True)
    assert not has(python, "pypdf")
    run = subprocess.run([python, "-c", "from cdlbib import deps; deps.install('research', package='pypdf')"],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert has(python, "pypdf")
