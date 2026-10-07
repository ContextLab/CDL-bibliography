"""install.sh, run for real: the script itself, real uv, real Pythons, real installations.

Nothing is substituted. Each test runs the script with a home folder, a temporary folder and
caches of its own, and with a PATH that is one folder of links to this computer's programs:
"uv is not installed" is a PATH that really has no uv, "the default Python is too old" is a
PATH whose python3 is a real older interpreter (when this computer has one; otherwise a PATH
with no Python at all). The package is installed from a copy of this checkout, in a folder
whose name has a space; its dependencies come from PyPI, so the tests that install need
the network and are skipped by name without it.

The tests that download uv itself (uv's installer from astral.sh, and one old uv program
from GitHub's releases) run only when asked for:

    CDLBIB_TEST_INSTALL_UV_DOWNLOAD=1 pytest tests/test_install_script.py

No test runs an old uv installer (those ignore UV_UNMANAGED_INSTALL, install into
~/.cargo/bin and edit shell profiles): the one test that names such an installer checks that
install.sh downloads it and refuses to run it.

No test writes outside pytest's temporary folder. Every program a test starts gets an
environment that is written out in full here, never a copy of the tester's: HOME and every
variable that tells uv, its installer, cargo, pipx or a shell where to write (XDG_*, UV_*,
CARGO_HOME, RUSTUP_HOME, PIPX_*, ZDOTDIR) name folders of the test. For every test the
tester's own environment has those variables pointing at a folder that must stay empty, and
the home folder the test run started with (and the account's, when HOME was replaced) is
compared before and after each test and before and after the module: shell profiles,
~/.config/fish, ~/.config/uv, ~/.cargo/bin, ~/.local/bin and uv's tool folder.

Run on macOS only so far. On Linux the script has been run by nothing but the step in
.github/workflows/autocheck.yml; these tests have not been run there."""
import hashlib
import os
import platform
import pty
import pwd
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "install.sh"
# The home folders that no test may change: the account's, and the one this run started
# with (they differ when the suite is run with HOME replaced).
REAL_HOMES = sorted({Path(pwd.getpwuid(os.getuid()).pw_dir), Path(os.environ.get("HOME") or "/nonexistent")})
# For the few programs that are only asked for their version: no folder of anyone's to write to.
BARE = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"}
# What tells uv, its installer, cargo, rustup, pipx and zsh where to write, with the place
# under a test's home folder that each one names in the environment the tests make.
WRITE_PLACES = {"XDG_DATA_HOME": ".local/share", "XDG_BIN_HOME": ".local/bin", "XDG_CACHE_HOME": ".cache",
                "XDG_CONFIG_HOME": ".config", "XDG_STATE_HOME": ".local/state",
                "UV_TOOL_DIR": ".local/share/uv/tools", "UV_TOOL_BIN_DIR": ".local/bin",
                "UV_PYTHON_INSTALL_DIR": ".local/share/uv/python", "UV_PYTHON_BIN_DIR": ".local/bin",
                "UV_INSTALL_DIR": ".local/uv-install-dir", "CARGO_HOME": ".cargo", "RUSTUP_HOME": ".rustup",
                "PIPX_HOME": ".local/pipx", "PIPX_BIN_DIR": ".local/bin", "PIPX_MAN_DIR": ".local/share/man",
                "ZDOTDIR": "."}
# In the tester's own environment the same variables, and the caches, name a folder that
# every test checks is still empty.
LEAK_NAMES = (*WRITE_PLACES, "UV_CACHE_DIR", "UV_PYTHON_CACHE_DIR", "PIP_CACHE_DIR", "CARGO_DIST_FORCE_INSTALL_DIR",
              "UV_UNMANAGED_INSTALL")
SYSTEM = "/usr/bin:/bin:/usr/sbin:/sbin"
# What a shell script, uv's installer, pip and a Python build may call. Linked one by one,
# so that the PATH of a test holds no Python, no uv and no git unless the test adds it.
SYSTEM_TOOLS = ("sh awk base64 basename cat chmod cp cut date dirname env expr false find getconf grep gzip head "
                "id install ld ldd ln ls mkdir mktemp mv od ps readlink rm rmdir sed sha256sum shasum sleep sort sw_vers tail "
                "tar tee "
                "touch tr true uname uniq wc which xargs xcode-select").split()
COMMANDS = ("cdlbib", "cdlbib-adapter-dartmouth", "cdlbib-adapter-openai")
DOWNLOAD_UV = os.environ.get("CDLBIB_TEST_INSTALL_UV_DOWNLOAD") == "1"
download_uv = pytest.mark.skipif(not DOWNLOAD_UV, reason="downloads uv; set CDLBIB_TEST_INSTALL_UV_DOWNLOAD=1 to run")
# The one version of uv that install.sh downloads, and the SHA-256 of its installer, as
# written in the script.
UV_VERSION = re.search(r"^UV_VERSION=(\S+)$", SCRIPT.read_text(encoding="utf-8"), re.M).group(1)
UV_INSTALLER_SHA256 = re.search(r"^UV_INSTALLER_SHA256=([0-9a-f]{64})$", SCRIPT.read_text(encoding="utf-8"), re.M).group(1)
UV_INSTALLER = f"https://astral.sh/uv/{UV_VERSION}/install.sh"
SHELLS = sorted({os.path.realpath(found) for found in ("/bin/sh", shutil.which("dash", path=SYSTEM)) if found})


def version_of(program):
    try:
        out = subprocess.run([program, "-B", "-c", "import sys; print(*sys.version_info[:2])"],
                             capture_output=True, text=True, timeout=30, env=BARE)
        major, minor = out.stdout.split()
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def real_executable(program):
    """The interpreter itself (on macOS /usr/bin/python3 only starts the developer tools' one)."""
    out = subprocess.run([program, "-B", "-c", "import sys; print(getattr(sys, '_base_executable', '') or sys.executable)"],
                         capture_output=True, text=True, timeout=30, env=BARE)
    return out.stdout.strip() or program


def old_python():
    """A real Python older than 3.11 on this computer, or None."""
    for name in ("/usr/bin/python3", "python3.10", "python3.9", "python3.8"):
        found = shutil.which(name)
        if found and (version_of(found) or (9, 9)) < (3, 11):
            return real_executable(found)
    return None


def python_between(low, high):
    """A real released Python whose version is from low to high on this computer, or None:
    the one running the tests when it fits, else one found by name."""
    for name in (sys.executable, *(f"python3.{minor}" for minor in range(high[1], low[1] - 1, -1))):
        found = name if os.path.isabs(name) else shutil.which(name)
        if found and low <= (version_of(found) or (0, 0)) <= high:
            return real_executable(found)
    return None


OLD_PYTHON = old_python()
NEW_PYTHON = python_between((3, 11), (3, 13))      # what install.sh installs with
NEWER_PYTHON = python_between((3, 14), (3, 19))    # newer than the package is tested on
UV = shutil.which("uv")
need_uv = pytest.mark.skipif(not UV, reason="uv is not installed")


def listing(folder):
    """{name: (size, modification time)} of what is directly in a folder ({} when absent)."""
    try:
        return {entry.name: (entry.lstat().st_size, entry.lstat().st_mtime_ns) for entry in Path(folder).iterdir()}
    except OSError:
        return {}


def tree(folder):
    """{relative name: (size, modification time)} of everything under a folder ({} when absent)."""
    found = {}
    for base, folders, files in os.walk(folder):
        for name in folders + files:
            path = Path(base) / name
            try:
                found[str(path.relative_to(folder))] = (path.lstat().st_size, path.lstat().st_mtime_ns)
            except OSError:
                found[str(path.relative_to(folder))] = None
    return found


def real_home_state():
    """What no test may change, in each of REAL_HOMES. Nothing is read but names, sizes and times."""
    folders = (".local/bin", ".local/share/uv/tools", ".local/share/uv/python", ".local/share/cdlbib",
               ".cargo/bin", "Library/Application Support/cdlbib")
    trees = (".config/fish", ".config/uv")
    files = (".zshrc", ".zshenv", ".zprofile", ".zlogin", ".profile", ".bashrc", ".bash_profile", ".bash_login",
             ".cargo/env", ".cargo/env.fish", ".local/bin/env", ".local/bin/env.fish")
    state = {}
    for home in REAL_HOMES:
        for name in folders:
            state[f"{home}/{name}"] = listing(home / name)
        for name in trees:
            state[f"{home}/{name}/**"] = tree(home / name)
        for name in files:
            path = home / name
            try:
                state[f"{home}/{name}"] = (path.lstat().st_size, path.lstat().st_mtime_ns)
            except OSError:
                state[f"{home}/{name}"] = None
    return state


def real_home_changes(before):
    after = real_home_state()
    return [name for name in before if before[name] != after[name]]


@pytest.fixture(scope="module", autouse=True)
def real_home_is_the_same_after_the_module():
    before = real_home_state()
    yield
    changed = real_home_changes(before)
    assert not changed, ("while tests/test_install_script.py ran, these changed in the real home folder "
                         f"(by a test, or by something else at the same time): {changed}")


@pytest.fixture(autouse=True)
def nothing_of_the_users_touched(tmp_path_factory, monkeypatch):
    """The tester's environment names a folder of this test for everything that uv, its
    installer, cargo, pipx or zsh would write; that folder stays empty, and the real home
    folder stays as it was."""
    leak = tmp_path_factory.mktemp("must-stay-empty")
    for name in LEAK_NAMES:
        monkeypatch.setenv(name, str(leak / name.lower()))
    before = real_home_state()
    yield
    assert sorted(os.listdir(leak)) == [], "a program was started with the tester's environment and wrote there"
    changed = real_home_changes(before)
    assert not changed, f"the run changed the real home folder: {changed}"


@pytest.fixture(scope="session")
def caches(tmp_path_factory):
    """Download caches of this test run, shared by its tests so that each package is fetched once."""
    return tmp_path_factory.mktemp("install-caches")


@pytest.fixture
def online():
    try:
        socket.create_connection(("pypi.org", 443), timeout=10).close()
    except OSError:
        pytest.skip("needs the network (pypi.org) to download the package's dependencies")


class Box:
    """One imaginary computer: a home folder, a temporary folder, a folder of programs and a
    copy of the checkout, all under one folder whose name has a space."""

    def __init__(self, root, caches):
        self.root = root / "one user"
        self.home = self.root / "home folder"
        self.tmp = self.root / "tmp"
        self.programs = self.root / "programs"
        self.checkout = self.root / "the checkout"
        self.caches = caches
        for folder in (self.home, self.tmp, self.programs, self.checkout / "docs"):
            folder.mkdir(parents=True)
        for name in SYSTEM_TOOLS:
            self.link(name)
        shutil.copy2(SCRIPT, self.checkout / "install.sh")
        shutil.copy2(ROOT / "pyproject.toml", self.checkout / "pyproject.toml")
        shutil.copy2(ROOT / "LICENSE", self.checkout / "LICENSE")
        shutil.copy2(ROOT / "docs" / "pypi.md", self.checkout / "docs" / "pypi.md")
        shutil.copytree(ROOT / "src", self.checkout / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        self.bin = self.home / ".local" / "bin"
        self.data = self.home / ".local" / "share" / "cdlbib"
        self.tool = self.home / ".local" / "share" / "uv" / "tools" / "cdlbib"
        self.pythons = self.home / ".local" / "share" / "uv" / "python"

    def link(self, name, target=None):
        target = target or shutil.which(name, path=SYSTEM) or shutil.which(name)
        if target and not (self.programs / name).exists():
            os.symlink(target, self.programs / name)
        return target

    def with_uv(self, program=None):
        self.link("uv", program or UV)
        return self

    def with_python(self, program=NEW_PYTHON, name="python3"):
        if not program:
            pytest.skip("this computer has no Python 3.11, 3.12 or 3.13")
        self.link(name, program)
        return self

    def with_old_python(self):
        """The default python3 is a real interpreter older than 3.11, when this computer has
        one; otherwise there is no Python on PATH at all."""
        if OLD_PYTHON:
            self.link("python3", OLD_PYTHON)
            assert version_of(str(self.programs / "python3")) < (3, 11)
        return self

    def env(self, **more):
        """The whole environment of a program a test starts. Nothing is taken from the tester's."""
        env = {"HOME": str(self.home), "PATH": str(self.programs), "TMPDIR": str(self.tmp), "SHELL": "/bin/zsh",
               "LANG": "en_US.UTF-8", "UV_CACHE_DIR": str(self.caches / "uv"),
               "UV_PYTHON_CACHE_DIR": str(self.caches / "uv-python"), "PIP_CACHE_DIR": str(self.caches / "pip"),
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
        env.update({name: str(self.home / place) for name, place in WRITE_PLACES.items()})
        env.update(more)
        assert not set(env) - set(more) - {"HOME", "PATH", "TMPDIR", "SHELL", "LANG", "UV_CACHE_DIR", "PIP_CACHE_DIR",
                                           "UV_PYTHON_CACHE_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
                                           "GIT_TERMINAL_PROMPT", *WRITE_PLACES}
        for name, value in env.items():
            if name in WRITE_PLACES or name in ("HOME", "TMPDIR", "UV_CACHE_DIR", "PIP_CACHE_DIR", "UV_PYTHON_CACHE_DIR"):
                assert Path(value).is_relative_to(self.root.parent) or Path(value).is_relative_to(self.caches), (name, value)
        return env

    def command(self, *args, shell="/bin/sh", script=None):
        return [shell, str(script or self.checkout / "install.sh"), *args]

    def run(self, *args, shell="/bin/sh", env=None, stdin=subprocess.DEVNULL, script=None, **kwargs):
        """The script, without a terminal: no input, and a session of its own (no /dev/tty)."""
        return subprocess.run(self.command(*args, shell=shell, script=script), env=env or self.env(),
                              cwd=self.root, stdin=stdin, capture_output=True, text=True, timeout=1800,
                              start_new_session=True, **kwargs)

    def installed(self, command="cdlbib"):
        """What the installed command says its version is, run from outside any library."""
        out = subprocess.run([str(self.bin / command), "--version"], env=self.env(), cwd=self.tmp,
                             capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stdout + out.stderr
        return out.stdout.strip()

    def files(self):
        """Every file and link under the home folder (not Python's compiled files)."""
        return {str(path.relative_to(self.home)) for path in self.home.rglob("*")
                if (path.is_file() or path.is_symlink()) and "__pycache__" not in path.parts}

    def set_version(self, version):
        project = self.checkout / "pyproject.toml"
        text = project.read_text(encoding="utf-8")
        assert 'version = "2.0.0"' in text
        project.write_text(text.replace('version = "2.0.0"', f'version = "{version}"'), encoding="utf-8")

    def leftovers(self):
        return sorted(path.name for path in self.tmp.iterdir())


@pytest.fixture
def box(tmp_path, caches):
    return Box(tmp_path, caches)


def ok(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


# --- what needs no network -----------------------------------------------------------------

def test_help_names_every_option(box):
    out = ok(box.run("--help"))
    for option in ("--extras", "--ref", "--repo", "--pypi", "--ask", "--no-uv", "--uninstall", "--help"):
        assert option in out
    assert box.files() == set()


def test_unknown_option_and_bad_values_stop_before_anything_is_done(box):
    for args, said in ((("--bogus",), "unknown option: --bogus"),
                       (("--extras", "tui; rm -rf x"), "--extras takes research, pdf and tui"),
                       (("--extras", "tui,evil"), "--extras takes research, pdf and tui"),
                       (("--extras", "tui]"), "--extras takes research, pdf and tui"),
                       (("--extras", "tui] @ https://example.org/x#"), "--extras takes research, pdf and tui"),
                       (("--extras", "TUI"), "--extras takes research, pdf and tui"),
                       (("--extras", "tui,"), "--extras takes research, pdf and tui"),
                       (("--extras", ",tui"), "--extras takes research, pdf and tui"),
                       (("--extras", "tui,,pdf"), "--extras takes research, pdf and tui"),
                       (("--extras", "--with"), "--extras takes research, pdf and tui"),
                       (("--extras=*",), "--extras takes research, pdf and tui"),
                       (("--ref", "a b"), "--ref takes a branch, tag or commit name"),
                       (("--ref", "-x"), "--ref takes a branch, tag or commit name"),
                       (("--ref", "--upload-pack=x"), "--ref takes a branch, tag or commit name"),
                       (("--ref", "a..b"), "--ref takes a branch, tag or commit name"),
                       (("--ref", "main#egg=other"), "--ref takes a branch, tag or commit name"),
                       (("--ref", "main ; python_version<'3'"), "--ref takes a branch, tag or commit name"),
                       (("--ref", "x@y"), "--ref takes a branch, tag or commit name"),
                       (("--ref", "x[y]"), "--ref takes a branch, tag or commit name"),
                       (("--ref", "a\nb"), "--ref takes a branch, tag or commit name"),
                       (("--ref=*",), "--ref takes a branch, tag or commit name"),
                       (("--repo", "http://example.org/x"), "--repo takes the https address"),
                       (("--repo", "https://example.org/x y"), "--repo takes the https address"),
                       (("--repo", "https://example.org/x#egg=y"), "--repo takes the https address"),
                       (("--repo", "https://user@example.org/x"), "--repo takes the https address"),
                       (("--repo", "https://example.org/../x"), "--repo takes the https address"),
                       (("--repo", "https://-example.org/x"), "--repo takes the https address"),
                       (("--repo", "-https://example.org/x"), "--repo takes the https address"),
                       (("--repo", "file:///etc"), "--repo takes the https address"),
                       (("--pypi", "--ref", "master"), "--pypi cannot be used together"),
                       (("--extras",), "--extras needs a value")):
        out = box.with_uv().run(*args)
        assert out.returncode == 1 and said in out.stderr, out.stdout + out.stderr
    assert box.files() == set()


@pytest.mark.parametrize("shell", SHELLS)
def test_no_uv_option_with_a_python_that_is_too_old_installs_nothing_and_says_what_to_install(box, shell):
    out = box.with_old_python().run("--no-uv", shell=shell)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "uv was not found, --no-uv was given, and" in out.stderr
    assert "no Python 3.11, 3.12 or 3.13 was found on PATH." in out.stderr
    assert "Nothing was installed." in out.stderr and "https://docs.astral.sh/uv/getting-started/installation/" in out.stderr
    assert box.files() == set() and box.leftovers() == []


def test_ask_without_a_terminal_installs_nothing_and_prints_the_commands(box):
    """No uv, no Python: the commands are the download of uv's installer, its run, and the install."""
    if not box.link("curl"):
        pytest.skip("curl is not installed")
    out = box.with_old_python().run("--ask", "--extras", "tui")
    assert out.returncode == 1, out.stdout + out.stderr
    own_uv = box.data / "uv"
    lines = out.stdout.splitlines()
    assert "--ask was given and there is no terminal to ask on: nothing is installed." in lines
    assert any(line.startswith(f"+ '{box.programs}/curl' --proto '=https' --tlsv1.2 -fsSL -o '") and
               line.endswith(f"/uv-install.sh' {UV_INSTALLER}") for line in lines), out.stdout
    assert any(line.startswith(f"+ '{box.programs}/env' 'UV_UNMANAGED_INSTALL={own_uv}' 'UV_NO_MODIFY_PATH=1' "
                               f"'INSTALLER_NO_MODIFY_PATH=1' '{box.programs}/sh' ") for line in lines), out.stdout
    assert any(line.startswith(f"+ '{own_uv}/uv' --no-config build --wheel --python '>=3.11,<3.14' --out-dir '")
               and line.endswith(f"/dist' -- '{box.checkout}'") for line in lines), out.stdout
    assert (f"+ cd '{box.data}/dist' && '{own_uv}/uv' --no-config tool install --python '>=3.11,<3.14' --with pip "
            "--force --reinstall-package cdlbib -- './cdlbib-VERSION-py3-none-any.whl[tui]'") in lines, out.stdout
    assert lines[-1] == "Nothing was installed. Run the script without --ask, or in a terminal, to install."
    assert box.files() == set() and box.leftovers() == []


@need_uv
def test_ask_without_a_terminal_and_uv_present_prints_the_one_command(box):
    out = box.with_uv().run("--ask")
    assert out.returncode == 1, out.stdout + out.stderr
    assert (f"+ cd '{box.data}/dist' && '{box.programs}/uv' --no-config tool install --python '>=3.11,<3.14' "
            "--with pip --force --reinstall-package cdlbib -- ./cdlbib-VERSION-py3-none-any.whl"
            ) in out.stdout.splitlines()
    assert "astral.sh" not in out.stdout and box.files() == set()


def answer_on_a_terminal(box, reply, *args):
    """Run the script with --ask on a real pseudo-terminal and type one reply."""
    master, slave = pty.openpty()
    process = subprocess.Popen(box.command("--ask", *args), env=box.env(), cwd=box.root, stdin=slave, stdout=slave,
                               stderr=slave, start_new_session=True)
    os.close(slave)
    seen, sent = b"", False
    deadline = time.time() + 1800
    while time.time() < deadline:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        seen += chunk
        if not sent and b"[y/N]" in seen:
            os.write(master, reply.encode() + b"\n")
            sent = True
    code = process.wait(timeout=60)
    os.close(master)
    return code, seen.decode(errors="replace")


@need_uv
def test_ask_on_a_terminal_answered_no_installs_nothing(box):
    code, seen = answer_on_a_terminal(box.with_uv(), "n")
    assert code == 1 and "Install cdlbib with uv? [y/N]" in seen and "stopped: nothing was installed." in seen, seen
    assert box.files() == set()


def test_uninstall_with_nothing_installed_is_no_error(box):
    out = ok(box.with_uv().run("--uninstall"))
    assert "Nothing to remove" in out and box.files() == set()


def test_git_source_without_git_says_so(box):
    """The script read from a pipe has no checkout beside it, so its source is the GitHub
    repository; this PATH has no git."""
    with open(SCRIPT, "rb") as script:
        out = subprocess.run(["/bin/sh", "-s"], stdin=script, env=box.env(), cwd=box.root,
                             capture_output=True, text=True, timeout=300, start_new_session=True)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "git is needed to install from https://github.com/ContextLab/CDL-bibliography and was not found." in out.stderr
    assert box.files() == set()


def test_no_uv_and_neither_curl_nor_wget_says_so(box):
    out = box.with_old_python().run()
    assert out.returncode == 1, out.stdout + out.stderr
    assert "uv has to be downloaded, and neither curl nor wget is installed." in out.stderr
    assert box.files() == set() and box.leftovers() == []


# --- installing with a uv that is already there (needs PyPI) --------------------------------

@need_uv
@pytest.mark.parametrize("shell", SHELLS)
def test_uv_present_and_the_default_python_too_old(box, online, shell):
    """The case that prompted the script: `pip install` said "requires a different Python".
    uv downloads a Python into its own folder; the python3 on PATH stays what it was."""
    box.with_uv().with_old_python()
    before = version_of(str(box.programs / "python3")) if OLD_PYTHON else None
    out = ok(box.run(shell=shell))
    assert "No Python 3.11, 3.12 or 3.13 was found: uv downloads one into its own folder" in out
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"
    assert f"Command:   {box.bin}/cdlbib (installed with uv)" in out
    assert [path.name for path in box.pythons.iterdir() if path.name.startswith("cpython-")], "uv downloaded no Python"
    assert (version_of(str(box.programs / "python3")) if OLD_PYTHON else None) == before
    for command in COMMANDS:
        assert (box.bin / command).exists()
    # The bin folder is not on this PATH: the line to add is printed, and no profile is written.
    assert f"{box.bin} is not on your PATH." in out
    assert 'Add this line to ~/.zshrc, then open a new terminal:\n  export PATH="$HOME/.local/bin:$PATH"' in out
    assert not [name for name in os.listdir(box.home) if name.startswith(".z") or name.startswith(".bash") or name == ".profile"]
    assert box.leftovers() == []


@need_uv
def test_colour_forced_in_the_environment_does_not_reach_the_paths_the_script_reads(box, online):
    """Found on 2026-10-06 by installing for real from a session with FORCE_COLOR=3: uv then
    prints its folders with colour codes, the script took them as part of the path, and
    reported a failed install that had succeeded."""
    box.with_uv().with_python()
    result = box.run(env=dict(box.env(), FORCE_COLOR="3", CLICOLOR_FORCE="1"))
    out = ok(result)
    assert "\x1b" not in result.stdout and "\x1b" not in result.stderr
    assert "Installed: cdlbib 2.0.0" in out and f"Command:   {box.bin}/cdlbib (installed with uv)" in out
    assert box.installed() == "cdlbib 2.0.0"


@need_uv
def test_running_again_changes_nothing_but_the_package_and_downloads_no_second_python(box, online):
    box.with_uv().with_old_python()
    ok(box.run())
    files, pythons = box.files(), listing(box.pythons)
    for _ in range(2):
        again = ok(box.run())
        assert "Installed: cdlbib 2.0.0" in again and box.installed() == "cdlbib 2.0.0"
        assert "No Python 3.11, 3.12 or 3.13 was found" not in again
        assert box.files() == files
        assert listing(box.pythons) == pythons
    assert box.leftovers() == []


@need_uv
def test_running_again_installs_the_changed_checkout(box, online):
    box.with_uv().with_python()
    ok(box.run())
    assert box.installed() == "cdlbib 2.0.0"
    box.set_version("2.0.1")
    assert "Installed: cdlbib 2.0.1" in ok(box.run()) and box.installed() == "cdlbib 2.0.1"


@need_uv
def test_path_hint_is_not_printed_when_the_folder_is_on_path_and_names_the_shell_otherwise(box, online):
    box.with_uv().with_python()
    on_path = ok(box.run(env=box.env(PATH=f"{box.programs}:{box.bin}")))
    assert "is not on your PATH" not in on_path
    fish = ok(box.run(env=box.env(SHELL="/usr/local/bin/fish")))
    assert 'Run this once in fish, then open a new terminal:\n  fish_add_path "$HOME/.local/bin"' in fish
    bash = ok(box.run(env=box.env(SHELL="/bin/bash")))
    profile = "~/.bash_profile" if sys.platform == "darwin" else "~/.bashrc"
    assert f'Add this line to {profile}, then open a new terminal:\n  export PATH="$HOME/.local/bin:$PATH"' in bash


@need_uv
def test_extras_option_installs_the_extra(box, online):
    box.with_uv().with_python()
    ok(box.run("--extras", "tui"))
    python = box.tool / "bin" / "python"
    assert subprocess.run([str(python), "-c", "import textual"], env=box.env(), capture_output=True).returncode == 0


@need_uv
def test_an_extra_is_installed_later_from_inside_the_uv_environment_without_uv_on_path(box, online):
    """The package installs an optional extra the first time it is needed (cdlbib.deps). The
    script puts pip into uv's environment for that: it works with no uv on PATH."""
    ok(box.with_uv().with_python().run())
    python = str(box.tool / "bin" / "python")
    (box.programs / "uv").unlink()
    missing = subprocess.run([python, "-c", "import textual"], env=box.env(), capture_output=True, text=True)
    assert missing.returncode != 0 and "No module named 'textual'" in missing.stderr
    code = ("from cdlbib import deps\nassert deps.installer()[1:] == ['-m', 'pip', 'install'], deps.installer()\n"
            "deps.install('tui')\nimport textual\nprint('textual', textual.__version__)")
    later = subprocess.run([python, "-c", code], env=box.env(), cwd=box.tmp, capture_output=True, text=True, timeout=900)
    assert later.returncode == 0 and later.stdout.startswith("textual "), later.stdout + later.stderr


@need_uv
def test_uninstall_removes_the_installation_and_a_second_uninstall_is_a_no_op(box, online):
    box.with_uv().with_python()
    box.bin.mkdir(parents=True)
    (box.bin / "something-else").write_text("#!/bin/sh\n")
    (box.data / "library").mkdir(parents=True)      # where cdlbib keeps its library on Linux
    (box.data / "library" / "cdl.bib").write_text("% the user's\n")
    ok(box.run())
    assert box.installed() == "cdlbib 2.0.0" and box.tool.is_dir()
    out = ok(box.run("--uninstall"))
    assert "Removed cdlbib." in out
    assert not box.tool.exists() and not [command for command in COMMANDS if (box.bin / command).exists()]
    assert not (box.data / "install-state").exists()
    assert (box.bin / "something-else").exists() and (box.data / "library" / "cdl.bib").exists()
    files = box.files()
    second = ok(box.run("--uninstall"))
    assert "Nothing to remove" in second and box.files() == files


@need_uv
@pytest.mark.parametrize("damage", ["a command link", "the environment", "the environment's Python", "the receipt",
                                    "the state file", "everything of uv's tool"])
def test_running_again_repairs_a_damaged_installation(box, online, damage):
    box.with_uv().with_python()
    ok(box.run())
    files = box.files()
    if damage == "a command link":
        (box.bin / "cdlbib").unlink()
    elif damage == "the environment":
        shutil.rmtree(box.tool / "lib")
    elif damage == "the environment's Python":
        for path in (box.tool / "bin").iterdir():
            if path.name.startswith("python"):
                path.unlink()
    elif damage == "the receipt":
        (box.tool / "uv-receipt.toml").unlink()
    elif damage == "the state file":
        (box.data / "install-state").unlink()
    else:
        shutil.rmtree(box.tool)
    out = ok(box.run())
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"
    assert box.files() == files and box.leftovers() == []


@need_uv
def test_a_run_that_is_killed_while_uv_installs_is_recovered_by_the_next_run(box, online):
    """The script's whole process group gets SIGTERM as soon as it has printed the uv command
    (uv has just started). The next run ends with a working command, and --uninstall after an
    unfinished run removes what there is."""
    box.with_uv().with_python()
    process = subprocess.Popen(box.command(), env=box.env(), cwd=box.root, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    for line in process.stdout:
        if line.startswith("+ ") and " tool install " in line:
            os.killpg(process.pid, signal.SIGTERM)
            break
    process.stdout.read()
    assert process.wait(timeout=120) != 0
    assert box.leftovers() == []
    assert (box.data / "install-state").read_text().startswith("method=uv\n")
    ok(box.run("--uninstall"))
    assert not box.tool.exists() and not (box.data / "install-state").exists()
    out = ok(box.run())
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"


# --- --no-uv: a virtual environment made with a Python 3.11+ on PATH (needs PyPI) --------------

@pytest.mark.parametrize("shell", SHELLS)
def test_no_uv_option_makes_a_virtual_environment_with_the_newest_python(box, online, shell):
    """python3 is too old (or absent); the Python 3.11+ is found under another name by asking
    each candidate for its version."""
    minor = sys.version_info[1]
    box.with_old_python().with_python(name=f"python3.{minor}")
    out = ok(box.run("--no-uv", shell=shell))
    assert "Installed: cdlbib 2.0.0" in out and f"Command:   {box.bin}/cdlbib (installed with venv)" in out
    assert box.installed() == "cdlbib 2.0.0"
    venv = box.data / "venv"
    assert version_of(str(venv / "bin" / "python")) == (3, minor)
    for command in COMMANDS:
        assert os.readlink(box.bin / command) == str(venv / "bin" / command)
    assert "astral.sh" not in out and not (box.data / "uv").exists() and not box.tool.exists()
    assert box.leftovers() == []
    # Again: the same files, and the changed checkout is installed.
    files = box.files()
    ok(box.run("--no-uv", shell=shell))
    assert box.files() == files
    box.set_version("2.0.1")
    assert "Installed: cdlbib 2.0.1" in ok(box.run("--no-uv", shell=shell)) and box.installed() == "cdlbib 2.0.1"


def test_no_uv_environment_is_repaired_and_uninstalled(box, online):
    box.with_python()
    box.bin.mkdir(parents=True)
    (box.bin / "something-else").write_text("#!/bin/sh\n")
    ok(box.run("--no-uv"))
    venv = box.data / "venv"
    files = box.files()
    for damage in ("a link", "the Python", "pip", "the state file"):
        if damage == "a link":
            (box.bin / "cdlbib-adapter-openai").unlink()
        elif damage == "the Python":
            for path in (venv / "bin").iterdir():
                if path.name.startswith("python"):
                    path.unlink()
        elif damage == "pip":
            for path in (venv / "lib").glob("python*/site-packages/pip"):
                shutil.rmtree(path)
        else:
            (box.data / "install-state").unlink()
        out = ok(box.run("--no-uv"))
        assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0", damage
        assert box.files() == files, damage
    out = ok(box.run("--uninstall"))
    assert "Removed cdlbib." in out and not venv.exists() and not box.data.exists()
    assert sorted(os.listdir(box.bin)) == ["something-else"]
    assert "Nothing to remove" in ok(box.run("--uninstall"))


def test_no_uv_will_not_replace_a_file_that_is_not_its_link(box, online):
    box.with_python()
    box.bin.mkdir(parents=True)
    (box.bin / "cdlbib").write_text("#!/bin/sh\necho mine\n")
    out = box.run("--no-uv")
    assert out.returncode == 1 and "exists and is not a link; it was left alone" in out.stderr
    assert (box.bin / "cdlbib").read_text() == "#!/bin/sh\necho mine\n"


@need_uv
def test_changing_route_leaves_one_installation(box, online):
    """First a virtual environment (--no-uv, no uv on PATH), then uv appears: the environment
    and its links are replaced by uv's tool, and back again."""
    box.with_python()
    ok(box.run("--no-uv"))
    venv = box.data / "venv"
    assert venv.is_dir()
    out = ok(box.with_uv().run())
    assert "Replacing the earlier installation (made with venv)." in out and "installed with uv" in out
    assert not venv.exists() and box.tool.is_dir() and box.installed() == "cdlbib 2.0.0"
    (box.programs / "uv").unlink()
    out = ok(box.run("--no-uv"))
    assert "Replacing the earlier installation (made with uv)." in out and "installed with venv" in out
    assert venv.is_dir() and box.installed() == "cdlbib 2.0.0"


@need_uv
def test_ask_on_a_terminal_answered_yes_installs(box, online):
    code, seen = answer_on_a_terminal(box.with_uv().with_python(), "y")
    assert code == 0 and "Install cdlbib with uv? [y/N]" in seen and "Installed: cdlbib 2.0.0" in seen, seen
    assert box.installed() == "cdlbib 2.0.0"


# --- downloading uv (only when asked for) --------------------------------------------------

@download_uv
@pytest.mark.parametrize("shell", SHELLS)
def test_no_uv_and_no_usable_python_downloads_uv_once(box, online, shell):
    """Nothing but curl and an old (or no) Python: uv's installer is downloaded and run, uv
    downloads a Python, and cdlbib works. A second run downloads neither again; a uv that an
    interrupted download left unusable is downloaded again; --uninstall removes the uv."""
    box.link("curl")
    box.with_old_python()
    first = box.run(shell=shell)
    out = ok(first)
    own_uv = box.data / "uv" / "uv"
    assert (f"uv was not found: downloading uv {UV_VERSION} with its installer ({UV_INSTALLER}, saved to a "
            f"temporary file, checked against the SHA-256 in this script and run with sh) into {box.data / 'uv'}; "
            "no shell profile is changed.") in out
    assert "The installer checks the archive of uv against the SHA-256 it carries" in out
    assert "skipping sha256 checksum verification" not in first.stdout + first.stderr
    assert "no checksums to verify" not in first.stdout + first.stderr
    assert subprocess.run([str(own_uv), "--version"], capture_output=True, text=True,
                          env=BARE).stdout.startswith(f"uv {UV_VERSION}")
    assert "No Python 3.11, 3.12 or 3.13 was found: uv downloads one into its own folder" in out
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"
    assert (f"+ '{box.programs}/env' 'UV_UNMANAGED_INSTALL={box.data / 'uv'}' 'UV_NO_MODIFY_PATH=1' "
            f"'INSTALLER_NO_MODIFY_PATH=1' '{box.programs}/sh' ") in out
    # UV_INSTALL_DIR and CARGO_HOME are set in this environment (to folders of the test): uv
    # went to neither, and no profile of the home folder (ZDOTDIR is the home folder) was made.
    assert own_uv.is_file() and not (box.bin / "uv").exists() and not (box.home / ".cargo").exists()
    assert not (box.home / ".local" / "uv-install-dir").exists()
    assert not [name for name in os.listdir(box.home) if name.startswith((".z", ".bash", ".profile"))]
    assert not (box.home / ".config").exists(), "uv's installer wrote a receipt or a profile"
    assert not [name for name in os.listdir(box.home) if not name.startswith(".local") and name != ".cache"]
    assert box.leftovers() == []
    files, uv_before, pythons = box.files(), own_uv.stat().st_mtime_ns, listing(box.pythons)

    again = ok(box.run(shell=shell))
    assert "downloading uv" not in again and "astral.sh" not in again and "No Python 3.11," not in again
    assert own_uv.stat().st_mtime_ns == uv_before and listing(box.pythons) == pythons and box.files() == files

    own_uv.write_bytes(b"")          # what a download that was cut off can leave
    repaired = ok(box.run(shell=shell))
    assert "downloading uv" in repaired and box.installed() == "cdlbib 2.0.0" and box.leftovers() == []
    assert listing(box.pythons) == pythons and box.files() == files

    removed = ok(box.run("--uninstall", shell=shell))
    assert "Removed cdlbib." in removed and not box.data.exists() and not box.tool.exists()
    assert not [command for command in COMMANDS if (box.bin / command).exists()]
    assert "Nothing to remove" in ok(box.run("--uninstall", shell=shell))


@download_uv
def test_a_run_killed_during_the_download_of_uv_leaves_no_temporary_file_and_is_recovered(box, online):
    box.link("curl")
    process = subprocess.Popen(box.command(), env=box.env(), cwd=box.root, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    for line in process.stdout:
        if line.startswith("+ ") and "UV_UNMANAGED_INSTALL=" in line:
            assert [name for name in box.leftovers() if name.startswith("cdlbib-install.")]
            os.killpg(process.pid, signal.SIGTERM)
            break
    process.stdout.read()
    assert process.wait(timeout=120) != 0
    assert not [name for name in box.leftovers() if name.startswith("cdlbib-install.")]
    out = ok(box.run())
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"


def old_uv(folder):
    """A real uv 0.4.0 (older than the script's minimum), from uv's GitHub releases."""
    machine = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64", "AMD64": "x86_64"}[platform.machine()]
    target = f"{machine}-apple-darwin" if sys.platform == "darwin" else f"{machine}-unknown-linux-gnu"
    archive = folder / "uv.tar.gz"
    urllib.request.urlretrieve(f"https://github.com/astral-sh/uv/releases/download/0.4.0/uv-{target}.tar.gz", archive)
    with tarfile.open(archive) as tar:
        tar.extractall(folder, filter="data")
    program = folder / f"uv-{target}" / "uv"
    assert subprocess.run([str(program), "--version"], capture_output=True, text=True,
                          env=BARE).stdout.startswith("uv 0.4.0")
    return str(program)


@download_uv
def test_an_older_uv_on_path_is_left_as_it_is(box, online, tmp_path):
    """uv 0.4.0 is on PATH. By default a current uv is downloaded into the script's folder and
    used; with --no-uv a virtual environment is made instead. The old uv is not changed."""
    program = old_uv(tmp_path)
    size = os.path.getsize(program)
    box.with_uv(program).with_python()
    box.link("curl")
    venv_route = ok(box.run("--no-uv"))
    assert "installed with venv" in venv_route and "astral.sh" not in venv_route
    out = ok(box.run())
    assert f"{box.programs}/uv is older than uv 0.5.0 and is left as it is: downloading uv {UV_VERSION} with its installer" in out
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"
    assert os.path.getsize(program) == size
    assert subprocess.run([program, "--version"], capture_output=True, text=True,
                          env=BARE).stdout.startswith("uv 0.4.0")
    again = ok(box.run())
    assert "downloading uv" not in again and f"uv={box.data}/uv/uv" in (box.data / "install-state").read_text()


@download_uv
def test_git_source_from_a_repository_and_branch(box, online):
    """The script read from a pipe, as with `curl ... | sh`: the source is a git repository.
    CDLBIB_TEST_INSTALL_REPO and CDLBIB_TEST_INSTALL_REF name one that holds the package."""
    repo, ref = os.environ.get("CDLBIB_TEST_INSTALL_REPO"), os.environ.get("CDLBIB_TEST_INSTALL_REF")
    if not repo or not ref:
        pytest.skip("set CDLBIB_TEST_INSTALL_REPO and CDLBIB_TEST_INSTALL_REF to a repository and branch with the package")
    box.with_uv().with_python()
    box.link("git")
    env = box.env()
    if sys.platform == "darwin":
        env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    with open(SCRIPT, "rb") as script:
        out = subprocess.run(["/bin/sh", "-s", "--", "--repo", repo, "--ref", ref], stdin=script, env=env,
                             cwd=box.root, capture_output=True, text=True, timeout=1800, start_new_session=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert f"Installing cdlbib from {repo} ({ref})." in out.stdout and "Installed: cdlbib " in out.stdout
    assert box.installed().startswith("cdlbib ")


# --- a hostile current folder ----------------------------------------------------------------

DECOYS = ("uv", "python3", "python3.13", "python", "git", "curl", "wget", "sh", "env", "sed", "grep", "mkdir", "rm",
          "mktemp", "cat", "uname", "pip", "pip3")
PLANTED = [".python-version", "decoy.py", "ensurepip.py", "importlib.py", "pip.conf", "pip.py", "pyproject.toml",
           "setup.cfg", "sitecustomize.py", "usercustomize.py", "uv.toml", "venv.py"]


def hostile_folder(folder):
    """A folder that tries to steer the installation when the script is started in it: programs
    with the names the script uses (each one, if run, writes its name into RAN and fails), a
    pyproject.toml of another "cdlbib", and the files that uv, pip and Python read from a
    current folder."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in DECOYS:
        decoy = folder / name
        decoy.write_text(f'#!/bin/sh\necho "{name} $*" >> "{folder}/RAN"\nexit 97\n')
        decoy.chmod(0o755)
    (folder / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools>=77"]\nbuild-backend = "setuptools.build_meta"\n\n'
        '[project]\nname = "cdlbib"\nversion = "6.6.6"\n\n[project.scripts]\ncdlbib = "decoy:main"\n\n'
        '[tool.uv]\nindex-url = "https://127.0.0.1:9/simple"\n')
    (folder / "decoy.py").write_text(f'def main():\n    open(r"{folder}/RAN", "a").write("decoy package\\n")\n')
    (folder / "uv.toml").write_text('index-url = "https://127.0.0.1:9/simple"\npython-preference = "only-system"\n')
    (folder / ".python-version").write_text("3.9\n")
    (folder / "pip.conf").write_text("[global]\nindex-url = https://127.0.0.1:9/simple\n")
    (folder / "setup.cfg").write_text("[metadata]\nname = cdlbib\nversion = 6.6.6\n")
    for name in ("sitecustomize.py", "usercustomize.py", "pip.py", "venv.py", "ensurepip.py", "importlib.py"):
        (folder / name).write_text(f'open(r"{folder}/RAN", "a").write("{name}\\n")\n')
    return folder


def hostile_paths(box, folder):
    """The PATH values that would find the folder's programs: ".", an empty entry (which a
    shell reads as the current folder), a relative name, and the folder's own full path."""
    return {"dot first": f".:{box.programs}", "empty entry first": f":{box.programs}",
            "empty entry last": f"{box.programs}:", "its full path first": f"{folder}:{box.programs}",
            "a relative folder first": f"../{folder.name}:{box.programs}"}


def nothing_ran(folder):
    ran = folder / "RAN"
    assert not ran.exists(), "from the current folder ran: " + ran.read_text()
    assert sorted(path.name for path in folder.iterdir() if path.name not in DECOYS + ("install.sh",)) == PLANTED, \
        "the run wrote into the current folder"


@need_uv
@pytest.mark.parametrize("path", ["dot first", "empty entry first", "empty entry last", "its full path first",
                                  "a relative folder first"])
def test_script_file_started_in_a_hostile_folder_installs_the_checkout_with_the_real_programs(box, online, path):
    """`sh "/the checkout/install.sh"` from a folder of decoys: the source is the folder the
    script file is in, never the current one, and no program of the current folder runs."""
    folder = hostile_folder(box.root / "hostile folder")
    box.with_uv().with_python()
    env = box.env(PATH=hostile_paths(box, folder)[path])
    out = subprocess.run(box.command(), env=env, cwd=folder, stdin=subprocess.DEVNULL, capture_output=True,
                         text=True, timeout=1800, start_new_session=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert f"Installing cdlbib from the checkout {box.checkout}." in out.stdout
    assert f"+ '{box.programs}/uv' --no-config build --wheel" in out.stdout
    assert f"+ cd '{box.data}/dist' && '{box.programs}/uv' --no-config tool install" in out.stdout
    assert "Installed: cdlbib 2.0.0" in out.stdout and box.installed() == "cdlbib 2.0.0"
    nothing_ran(folder)


def test_script_file_named_by_a_relative_path_uses_its_own_folder_not_the_current_one(box, online):
    """`sh "../the checkout/install.sh" --no-uv` from the hostile folder: a virtual environment
    made by the real Python, with pip run outside the folder (its sitecustomize.py, pip.py,
    pip.conf and setup.cfg are not read)."""
    folder = hostile_folder(box.root / "hostile folder")
    box.with_python()
    out = subprocess.run(["/bin/sh", "../the checkout/install.sh", "--no-uv"], env=box.env(PATH=f".:{box.programs}"),
                         cwd=folder, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1800,
                         start_new_session=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert f"Installing cdlbib from the checkout {box.checkout}." in out.stdout
    assert "installed with venv" in out.stdout and box.installed() == "cdlbib 2.0.0"
    nothing_ran(folder)


@need_uv
def test_decoys_inside_the_checkout_itself_are_not_run(box, online):
    """`sh install.sh` inside the checkout, with "." on PATH and programs named uv and python3
    lying in the checkout: the checkout is the source, and its folder is not searched."""
    for name in DECOYS:
        decoy = box.checkout / name
        decoy.write_text(f'#!/bin/sh\necho "{name} $*" >> "{box.checkout}/RAN"\nexit 97\n')
        decoy.chmod(0o755)
    box.with_uv().with_python()
    for path in (f".:{box.programs}", f"{box.checkout}:{box.programs}"):
        out = subprocess.run(["/bin/sh", "install.sh"], env=box.env(PATH=path), cwd=box.checkout,
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1800,
                             start_new_session=True)
        assert out.returncode == 0, out.stdout + out.stderr
        assert f"+ '{box.programs}/uv' --no-config build --wheel" in out.stdout
        assert box.installed() == "cdlbib 2.0.0"
        assert not (box.checkout / "RAN").exists(), (box.checkout / "RAN").read_text()


def piped(box, folder, *args, path=None, **env):
    """`sh < install.sh` (as `curl ... | sh` runs it), started in a folder."""
    with open(SCRIPT, "rb") as script:
        return subprocess.run(["/bin/sh", "-s", "--", *args], stdin=script, cwd=folder,
                              env=box.env(PATH=path or f".:{box.programs}", **env),
                              capture_output=True, text=True, timeout=1800, start_new_session=True)


@need_uv
def test_piped_script_in_a_hostile_folder_never_takes_the_folder_as_its_source(box):
    """The folder has a pyproject.toml named cdlbib and even a file called install.sh. Read
    from a pipe, the script's source is the repository; with --ask and no terminal it prints
    the one command, which names the repository and the real uv."""
    folder = hostile_folder(box.root / "hostile folder")
    shutil.copy2(SCRIPT, folder / "install.sh")
    box.with_uv().with_python()
    box.link("git")
    more = {"DEVELOPER_DIR": "/Library/Developer/CommandLineTools"} if sys.platform == "darwin" else {}
    for path in hostile_paths(box, folder).values():
        out = piped(box, folder, "--ask", path=path, **more)
        assert out.returncode == 1, out.stdout + out.stderr
        assert "Installing cdlbib from https://github.com/ContextLab/CDL-bibliography." in out.stdout
        assert (f"+ '{box.programs}/uv' --no-config tool install --python '>=3.11,<3.14' --with pip --force "
                "--reinstall-package cdlbib -- 'cdlbib @ git+https://github.com/ContextLab/CDL-bibliography'"
                ) in out.stdout.splitlines()
        assert str(folder) not in out.stdout + out.stderr
    nothing_ran(folder)
    assert box.files() == set()


def test_piped_script_in_a_hostile_folder_does_not_use_its_git_or_its_curl(box):
    """No real git on PATH, and a program called git in the current folder: git is reported
    missing. With --pypi (no git needed) and no real curl: curl is reported missing."""
    folder = hostile_folder(box.root / "hostile folder")
    for path in hostile_paths(box, folder).values():
        out = piped(box, folder, path=path)
        assert out.returncode == 1 and "git is needed to install from" in out.stderr, out.stdout + out.stderr
        out = piped(box, folder, "--pypi", path=path)
        assert out.returncode == 1 and "neither curl nor wget is installed" in out.stderr, out.stdout + out.stderr
    nothing_ran(folder)
    assert box.files() == set() and box.leftovers() == []


@need_uv
def test_configuration_files_above_the_temporary_folder_and_in_the_users_folder_do_not_steer_uv(box, online):
    """uv reads uv.toml from the folder it runs in, the folders above it, and the user's
    configuration folder. The script runs uv with --no-config in a fresh folder: an index
    address that cannot be reached, written in those places, changes nothing."""
    bad = 'index-url = "https://127.0.0.1:9/simple"\n'
    (box.tmp / "uv.toml").write_text(bad)
    (box.home / ".config" / "uv").mkdir(parents=True)
    (box.home / ".config" / "uv" / "uv.toml").write_text(bad)
    out = ok(box.with_uv().with_python().run("--extras", "pdf"))
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"
    assert box.leftovers() == ["uv.toml"]


def test_the_temporary_folder_is_private_and_not_predictable(box):
    """Seen while the script waits at the --ask question, before anything is downloaded."""
    if not box.link("curl"):
        pytest.skip("curl is not installed")
    names = []
    for _ in range(2):
        master, slave = pty.openpty()
        process = subprocess.Popen(box.command("--ask"), env=box.env(), cwd=box.root, stdin=slave, stdout=slave,
                                   stderr=slave, start_new_session=True)
        os.close(slave)
        seen = b""
        while b"[y/N]" not in seen:
            seen += os.read(master, 4096)
        (made,) = [path for path in box.tmp.iterdir() if path.name.startswith("cdlbib-install.")]
        assert made.is_dir() and not made.is_symlink() and made.stat().st_mode & 0o777 == 0o700
        assert made.stat().st_uid == os.getuid()
        names.append(made.name)
        os.write(master, b"n\n")
        assert process.wait(timeout=60) == 1
        os.close(master)
        assert box.leftovers() == []
    assert names[0] != names[1] and "XXXXXX" not in names[0] + names[1]


@download_uv
def test_piped_script_in_a_hostile_folder_installs_from_the_repository(box, online):
    """The whole of `curl ... | sh` from a hostile folder, for real: nothing but curl and git
    on PATH (and the decoys in the current folder), so uv is downloaded, and the package comes
    from the repository named by CDLBIB_TEST_INSTALL_REPO and CDLBIB_TEST_INSTALL_REF."""
    repo, ref = os.environ.get("CDLBIB_TEST_INSTALL_REPO"), os.environ.get("CDLBIB_TEST_INSTALL_REF")
    if not repo or not ref:
        pytest.skip("set CDLBIB_TEST_INSTALL_REPO and CDLBIB_TEST_INSTALL_REF to a repository and branch with the package")
    folder = hostile_folder(box.root / "hostile folder")
    box.link("curl")
    box.link("git")
    more = {"DEVELOPER_DIR": "/Library/Developer/CommandLineTools"} if sys.platform == "darwin" else {}
    out = piped(box, folder, "--repo", repo, "--ref", ref, **more)
    assert out.returncode == 0, out.stdout + out.stderr
    assert f"downloading uv {UV_VERSION} with its installer" in out.stdout and "Installed: cdlbib " in out.stdout
    assert box.installed().startswith("cdlbib ") and box.installed() != "cdlbib 6.6.6"
    nothing_ran(folder)


# --- paths, extras and names that could be read as something else ------------------------------

def awkward_checkout(box, plain=False):
    """The checkout moved to a path with a space, #, @, ;, [x] and a folder that starts with a
    dash (or, with plain, to a path of letters only, under a link so that it is short)."""
    if plain:
        folder = box.root.parent / "plain" / "checkout"
    else:
        folder = box.root / "-dash folder" / "a #b @ c;d [x]" / "check out"
    folder.parent.mkdir(parents=True)
    shutil.move(box.checkout, folder)
    box.checkout = folder
    return folder


def recorded(box):
    """Everything uv and the installer wrote down about where the tool came from: uv's
    receipt and every file of cdlbib's *.dist-info in the tool's environment, as one text."""
    texts = [(box.tool / "uv-receipt.toml").read_text(encoding="utf-8")]
    for info in (box.tool / "lib").glob("python*/site-packages/cdlbib-*.dist-info"):
        for path in info.iterdir():
            if path.is_file():
                texts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(texts)


def temporary_folder_of(out):
    """The temporary folder a run of the script used, read from the command it printed."""
    (line,) = [line for line in out.splitlines() if " build --wheel " in line]
    found = re.search(r"--out-dir '?(.+/cdlbib-install\.[A-Za-z0-9]+)/dist'? -- ", line)
    return Path(found.group(1))


@need_uv
@pytest.mark.parametrize("where", ["a path with a space", "a path that could be read as a requirement"])
def test_uv_records_the_wheel_in_the_users_folder_and_nothing_in_a_temporary_folder(box, online, where):
    """A checkout is installed as a wheel that the script builds and keeps in
    ~/.local/share/cdlbib/dist (mode 700). uv records that file and nothing under TMPDIR, so
    a package that someone later puts where the temporary folder was is never installed:
    `uv tool upgrade cdlbib` leaves the tool as it is."""
    folder = box.checkout if where == "a path with a space" else awkward_checkout(box)
    box.with_uv().with_python()
    out = ok(box.run("--extras", "tui"))
    assert f"Installing cdlbib from the checkout {folder}." in out
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"
    dist = box.data / "dist"
    assert sorted(os.listdir(dist)) == ["cdlbib-2.0.0-py3-none-any.whl"] and dist.stat().st_mode & 0o777 == 0o700
    used = temporary_folder_of(out)
    assert used.parent == box.tmp and not used.exists() and box.leftovers() == []
    text = recorded(box)
    assert f'path = "{dist}/cdlbib-2.0.0-py3-none-any.whl"' in text and 'extras = ["tui"]' in text
    for forbidden in (str(box.tmp), "cdlbib-install.", str(folder), "/src"):
        assert forbidden not in text.replace("/site-packages", ""), forbidden
    python = str(box.tool / "bin" / "python")
    assert subprocess.run([python, "-I", "-c", "import textual"], env=box.env(), cwd=box.tmp).returncode == 0

    # Someone recreates the temporary folder with a package of the same name in every place
    # an earlier design could have recorded.
    for decoy in (used / "src", used / "dist", used):
        hostile_folder(decoy)
    shutil.copytree(used / "src", used / "dist" / "cdlbib-2.0.0-py3-none-any.whl")
    upgrade = subprocess.run([str(box.programs / "uv"), "--no-config", "tool", "upgrade", "cdlbib"], env=box.env(),
                             cwd=box.tmp, capture_output=True, text=True, timeout=900)
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr
    assert box.installed() == "cdlbib 2.0.0" and recorded(box) == text
    assert not list(used.rglob("RAN"))
    shutil.rmtree(used)

    # Again, and with a new version: one wheel, the same record, the same files.
    files = box.files()
    ok(box.run("--extras", "tui"))
    assert box.files() == files and recorded(box).count(str(box.tmp)) == 0
    box.set_version("2.0.1")
    assert "Installed: cdlbib 2.0.1" in ok(box.run("--extras", "tui")) and box.leftovers() == []
    assert sorted(os.listdir(dist)) == ["cdlbib-2.0.1-py3-none-any.whl"] and str(box.tmp) not in recorded(box)
    ok(box.run("--uninstall"))
    assert not box.tool.exists() and not box.data.exists()


@need_uv
def test_data_folder_that_uv_cannot_install_from_is_refused_before_anything_is_done(box):
    data = box.root / "data #1 [x]"
    out = box.with_uv().with_python().run(env=box.env(XDG_DATA_HOME=str(data)))
    assert out.returncode == 1 and f"uv cannot install from {data}/cdlbib/dist" in out.stderr, out.stdout + out.stderr
    assert "Nothing was installed." in out.stderr and not data.exists() and box.files() == set()


def test_checkout_whose_path_could_be_read_as_a_requirement_is_installed_with_pip(box, online):
    """--no-uv: pip gets a file:// address in which every such character is written as %XX."""
    folder = awkward_checkout(box)
    box.with_python()
    out = ok(box.run("--no-uv", "--extras", "tui,pdf"))
    assert f"Installing cdlbib from the checkout {folder}." in out
    encoded = "/-dash%20folder/a%20%23b%20%40%20c%3bd%20%5bx%5d/check%20out"
    (line,) = [line for line in out.splitlines() if " -m pip install " in line]
    assert line.endswith(f"{encoded}'") and " -- 'cdlbib[tui,pdf] @ file:///" in line, line
    assert "#" not in line.split(" -- ")[1] and ";" not in line.split(" -- ")[1]
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"
    python = str(box.data / "venv" / "bin" / "python")
    assert subprocess.run([python, "-c", "import textual, pypdfium2"], env=box.env(), cwd=box.tmp).returncode == 0
    box.set_version("2.0.1")
    assert "Installed: cdlbib 2.0.1" in ok(box.run("--no-uv", "--extras", "tui,pdf"))


# --- the Python the environment is made with ---------------------------------------------------

@need_uv
def test_uv_does_not_use_a_python_newer_than_the_package_is_tested_on(box, online):
    """The only Python on PATH is 3.14 or later (a real one): uv is asked for >=3.11,<3.14,
    so it downloads a 3.13 and the environment is made with that."""
    if not NEWER_PYTHON:
        pytest.skip("this computer has no Python 3.14 or later")
    box.with_uv().with_python(NEWER_PYTHON)
    assert version_of(str(box.programs / "python3")) >= (3, 14)
    out = ok(box.run())
    assert "No Python 3.11, 3.12 or 3.13 was found: uv downloads one into its own folder" in out
    assert "--python '>=3.11,<3.14'" in out and box.installed() == "cdlbib 2.0.0"
    assert (3, 11) <= version_of(str(box.tool / "bin" / "python")) <= (3, 13)
    assert 'python = ">=3.11' in (box.tool / "uv-receipt.toml").read_text() and "<3.14" in (box.tool / "uv-receipt.toml").read_text()


def test_no_uv_option_does_not_use_a_python_newer_than_the_package_is_tested_on(box):
    if not NEWER_PYTHON:
        pytest.skip("this computer has no Python 3.14 or later")
    out = box.with_python(NEWER_PYTHON).run("--no-uv")
    assert out.returncode == 1 and "no Python 3.11, 3.12 or 3.13 was found on PATH." in out.stderr, out.stdout + out.stderr
    assert box.files() == set()


@need_uv
def test_uv_with_an_old_default_python_makes_the_environment_with_3_11_to_3_13(box, online):
    ok(box.with_uv().with_old_python().run())
    assert (3, 11) <= version_of(str(box.tool / "bin" / "python")) <= (3, 13)


# --- the installer of uv -------------------------------------------------------------------------

@download_uv
def test_installer_of_a_uv_older_than_the_minimum_is_downloaded_but_never_run(box, online):
    """CDLBIB_UV_INSTALLER names the installer of uv 0.4.0, which ignores UV_UNMANAGED_INSTALL,
    installs into ~/.cargo/bin and edits shell profiles. It is not the installer whose SHA-256
    is written in install.sh, so it is refused: nothing at all is written into the home folder
    of the test."""
    if not box.link("curl"):
        pytest.skip("curl is not installed")
    out = box.run(env=box.env(CDLBIB_UV_INSTALLER="https://astral.sh/uv/0.4.0/install.sh"))
    assert out.returncode == 1, out.stdout + out.stderr
    assert (f"the file from https://astral.sh/uv/0.4.0/install.sh is not the installer of uv {UV_VERSION} that "
            "this script") in out.stderr
    assert f"and {UV_INSTALLER_SHA256} is expected." in out.stderr
    assert "It was not run. Nothing was installed." in out.stderr
    assert "UV_UNMANAGED_INSTALL=" not in out.stdout
    assert box.files() == set() and box.leftovers() == []
    assert not (box.home / ".cargo").exists() and not (box.home / ".zshrc").exists()


def test_installer_address_must_be_one_of_uvs_own(box):
    for address in ("https://example.org/uv/0.9.0/install.sh", "http://astral.sh/uv/0.9.0/install.sh",
                    "https://astral.sh/uv/0.9.0/../../x/install.sh", "https://astral.sh/uv/0.9.0/install.sh?x",
                    "https://astral.sh/uv/install.sh;x", "https://astral.sh.example.org/uv/0.9.0/install.sh"):
        out = box.run(env=box.env(CDLBIB_UV_INSTALLER=address))
        assert out.returncode == 1 and "CDLBIB_UV_INSTALLER takes an address of the form" in out.stderr, address
    assert box.files() == set()


# --- PATH entries that cannot be decided are left out --------------------------------------------

def test_path_entries_that_reach_the_current_folder_by_a_link_or_dots_are_not_searched(box):
    """The hostile folder is on PATH as a link to it, through "..", through a link to a link,
    and with a trailing slash; a broken link and a file are on PATH too. None is searched:
    git and curl are reported missing although programs of those names lie in the folder."""
    folder = hostile_folder(box.root / "hostile folder")
    links = box.root / "links"
    links.mkdir()
    os.symlink(folder, links / "to-folder")
    os.symlink(links / "to-folder", links / "to-link")
    os.symlink(links / "nowhere", links / "broken")
    (links / "a-file").write_text("")
    entries = [f"{links}/to-folder", f"{links}/to-link", f"{folder}/../{folder.name}", f"{folder}/", f"{folder}/.",
               f"{links}/broken", f"{links}/a-file", f"{folder}//", ".", "", "..//" + folder.name]
    for entry in entries:
        for path in (f"{entry}:{box.programs}", f"{box.programs}:{entry}"):
            out = piped(box, folder, path=path)
            assert out.returncode == 1 and "git is needed to install from" in out.stderr, (entry, out.stdout + out.stderr)
            out = piped(box, folder, "--pypi", path=path)
            assert out.returncode == 1 and "neither curl nor wget is installed" in out.stderr, (entry, out.stderr)
    nothing_ran(folder)
    assert box.files() == set()


def test_a_path_with_nothing_usable_stops_the_script(box):
    folder = hostile_folder(box.root / "hostile folder")
    for path in (".", ":", f"{folder}", f".:{folder}:relative/bin:{box.root}/missing"):
        out = piped(box, folder, "--help", path=path)
        assert out.returncode == 1 and "no folder of PATH can be used" in out.stderr, (path, out.stdout + out.stderr)
        out = piped(box, folder, path=path)
        assert out.returncode == 1 and "no folder of PATH can be used" in out.stderr, (path, out.stdout + out.stderr)
    nothing_ran(folder)


@need_uv
def test_programs_run_by_the_script_get_a_path_without_the_current_folder(box, online):
    """uv builds the package by running Python and the build backend; with "." first on PATH
    and decoys named python3, sh and git in the current folder, none of them is run, by the
    script or by what it starts. The script file is named by a path through a link."""
    folder = hostile_folder(box.root / "hostile folder")
    os.symlink(box.checkout, folder / "link to checkout")
    box.with_uv().with_python()
    out = subprocess.run(["/bin/sh", "link to checkout/install.sh", "--extras", "research"],
                         env=box.env(PATH=f".:{folder}:{box.programs}:./"), cwd=folder, stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=1800, start_new_session=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert f"Installing cdlbib from the checkout {box.checkout}." in out.stdout
    assert box.installed() == "cdlbib 2.0.0"
    assert not (folder / "RAN").exists(), (folder / "RAN").read_text()


# --- a run that fails leaves a working installation as it was ------------------------------------

def refused_address():
    """An index address on this computer that nothing listens on: connections are refused."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/simple"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def break_the_source(box, how):
    """Make the source something that cannot be installed; the arguments and the environment
    of the run that will fail."""
    if how == "the index cannot be reached":
        address = refused_address()
        return ("--pypi",), box.env(UV_DEFAULT_INDEX=address, UV_INDEX_URL=address, PIP_INDEX_URL=address,
                                    UV_HTTP_TIMEOUT="5", PIP_RETRIES="0", PIP_DEFAULT_TIMEOUT="5")
    box.set_version("2.0.1")
    project = box.checkout / "pyproject.toml"
    text = project.read_text(encoding="utf-8")
    if how == "the build of the checkout fails":
        project.write_text(text + "\n[[[ this line is not TOML\n", encoding="utf-8")
    else:
        assert how == "a dependency of the checkout does not exist"
        assert "\ndependencies = [\n" in text
        project.write_text(text.replace("\ndependencies = [\n", "\ndependencies = [\n"
                                        '    "cdlbib-no-such-distribution-for-the-install-tests==99",\n', 1),
                           encoding="utf-8")
    return (), box.env()


FAILURES = ["the index cannot be reached", "the build of the checkout fails",
            "a dependency of the checkout does not exist"]


@need_uv
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("how", FAILURES)
def test_a_source_that_cannot_be_installed_leaves_the_working_uv_installation_as_it_was(box, online, how, shell):
    """codex round 3, item 12. Before the fix a failed `uv tool install` was answered by
    uninstalling the tool and removing its environment, and the wheel of the installed
    version was replaced before the new one was known to install."""
    box.with_uv().with_python()
    ok(box.run(shell=shell))
    wheel = box.data / "dist" / "cdlbib-2.0.0-py3-none-any.whl"
    def files():       # uv keeps a lock file of its own beside its tools once it has asked an index
        return {name for name in box.files() if not name.startswith(".local/share/uv/credentials/")}
    before, state, wheel_digest = files(), (box.data / "install-state").read_text(), digest(wheel)
    environment = tree(box.tool / "lib")
    args, env = break_the_source(box, how)
    out = box.run(*args, shell=shell, env=env)
    assert out.returncode == 1, out.stdout + out.stderr
    assert (f"The installation that was there is unchanged: {box.bin}/cdlbib runs as before."
            in out.stderr), out.stdout + out.stderr
    assert "Trying again after removing" not in out.stdout + out.stderr
    assert box.installed() == "cdlbib 2.0.0"
    for command in COMMANDS:
        assert (box.bin / command).exists()
    assert sorted(os.listdir(box.data / "dist")) == ["cdlbib-2.0.0-py3-none-any.whl"] and digest(wheel) == wheel_digest
    assert tree(box.tool / "lib") == environment, "the environment of the installed version was changed"
    assert files() == before and (box.data / "install-state").read_text() == state
    assert box.leftovers() == []
    # And a second failing run, which before the fix left no command at all.
    again = box.run(*args, shell=shell, env=env)
    assert again.returncode == 1 and box.installed() == "cdlbib 2.0.0", again.stdout + again.stderr


@pytest.mark.parametrize("how", FAILURES)
def test_a_source_that_cannot_be_installed_leaves_the_working_virtual_environment_as_it_was(box, online, how):
    """--no-uv. With an index that cannot be reached, `pip install --upgrade cdlbib` finds the
    installed version sufficient and ends with success; the script fetches the package from
    the index first, so that it does not report an installation that did not happen."""
    box.with_python()
    ok(box.run("--no-uv"))
    files, state = box.files(), (box.data / "install-state").read_text()
    args, env = break_the_source(box, how)
    out = box.run("--no-uv", *args, env=env)
    assert out.returncode == 1, out.stdout + out.stderr
    if how == "the index cannot be reached":
        assert ("the index could not be reached or has no cdlbib, so nothing was installed or updated."
                in out.stderr), out.stderr
        assert "Installed:" not in out.stdout
    assert (f"The installation that was there is unchanged: {box.bin}/cdlbib runs as before."
            in out.stderr), out.stdout + out.stderr
    assert box.installed() == "cdlbib 2.0.0"
    assert box.files() == files and (box.data / "install-state").read_text() == state and box.leftovers() == []


@need_uv
def test_a_first_installation_that_fails_installs_nothing_and_the_next_run_installs(box, online):
    """Nothing is there to keep: the run stops with an error, and a run with the source put
    right installs."""
    box.with_uv().with_python()
    project = box.checkout / "pyproject.toml"
    good = project.read_text(encoding="utf-8")
    break_the_source(box, "a dependency of the checkout does not exist")
    out = box.run()
    assert out.returncode == 1 and "No working cdlbib was installed" in out.stderr, out.stdout + out.stderr
    assert not (box.bin / "cdlbib").exists() and box.leftovers() == []
    project.write_text(good, encoding="utf-8")
    assert "Installed: cdlbib 2.0.0" in ok(box.run()) and box.installed() == "cdlbib 2.0.0"
    assert sorted(os.listdir(box.data / "dist")) == ["cdlbib-2.0.0-py3-none-any.whl"]


@need_uv
def test_a_broken_installation_is_repaired_and_a_working_one_is_kept_until_the_new_version_runs(box, online):
    """The command does not run (its environment's packages are gone): that installation is
    removed and installed again. The upgrade after it is made beside the installed version
    first, and only the new wheel is left at the end."""
    box.with_uv().with_python()
    ok(box.run())
    shutil.rmtree(box.tool / "lib")
    broken = subprocess.run([str(box.bin / "cdlbib"), "--version"], env=box.env(), cwd=box.tmp, capture_output=True)
    assert broken.returncode != 0
    out = ok(box.run())
    assert f"The cdlbib tool in {box.tool.parent} does not run: it is removed and installed again." in out
    assert "it is kept until the new version" not in out
    assert box.installed() == "cdlbib 2.0.0"
    box.set_version("2.0.1")
    out = ok(box.run())
    assert "The installed cdlbib runs: it is kept until the new version has been installed beside it and has run." in out
    assert "Installed: cdlbib 2.0.1" in out and box.installed() == "cdlbib 2.0.1"
    assert sorted(os.listdir(box.data / "dist")) == ["cdlbib-2.0.1-py3-none-any.whl"] and box.leftovers() == []


# --- --uninstall removes the installation that was recorded, and only that -------------------------

def recorded_state(box):
    return dict(line.split("=", 1) for line in (box.data / "install-state").read_text().splitlines())


@need_uv
@pytest.mark.parametrize("shell", SHELLS)
def test_uninstall_removes_the_recorded_tool_and_not_the_one_of_another_tool_directory(box, online, shell):
    """codex round 3, item 13. The script installs into one tool directory of uv; a second,
    unrelated cdlbib is installed with uv itself into another one. --uninstall, run with
    UV_TOOL_DIR and UV_TOOL_BIN_DIR naming the other one, removes the script's and leaves the
    other. Before the fix it removed the other and left its own."""
    box.with_uv().with_python()
    ok(box.run(shell=shell))
    assert recorded_state(box) == {"method": "uv", "bin": str(box.bin), "uv": str(box.programs / "uv"),
                                   "tool_dir": str(box.tool.parent), "tool_bin": str(box.bin)}
    other = box.root / "another"
    elsewhere = box.env(UV_TOOL_DIR=str(other / "tools"), UV_TOOL_BIN_DIR=str(other / "bin"))
    made = subprocess.run([str(box.programs / "uv"), "--no-config", "tool", "install", "--python", ">=3.11,<3.14",
                           "--", "./cdlbib-2.0.0-py3-none-any.whl"], env=elsewhere, cwd=box.data / "dist",
                          capture_output=True, text=True, timeout=900)
    assert made.returncode == 0, made.stdout + made.stderr
    assert (other / "tools" / "cdlbib" / "uv-receipt.toml").is_file() and (other / "bin" / "cdlbib").exists()

    out = ok(box.run("--uninstall", shell=shell, env=elsewhere))
    assert "Removed cdlbib." in out
    assert not box.tool.exists() and not [command for command in COMMANDS if (box.bin / command).exists()]
    assert not box.data.exists()
    assert (other / "tools" / "cdlbib" / "uv-receipt.toml").is_file()
    still = subprocess.run([str(other / "bin" / "cdlbib"), "--version"], env=box.env(), cwd=box.tmp,
                           capture_output=True, text=True, timeout=120)
    assert still.returncode == 0 and still.stdout.strip() == "cdlbib 2.0.0", still.stdout + still.stderr
    assert "Nothing to remove" in ok(box.run("--uninstall", shell=shell, env=elsewhere))
    assert (other / "bin" / "cdlbib").exists()


@need_uv
def test_installing_again_with_another_tool_directory_stops_and_changes_nothing(box, online):
    box.with_uv().with_python()
    ok(box.run())
    files, state = box.files(), (box.data / "install-state").read_text()
    other = box.root / "another"
    out = box.run(env=box.env(UV_TOOL_DIR=str(other / "tools"), UV_TOOL_BIN_DIR=str(other / "bin")))
    assert out.returncode == 1, out.stdout + out.stderr
    assert f"this script installed cdlbib into uv's tool directory {box.tool.parent}" in out.stderr
    assert "Nothing was changed." in out.stderr and "To move it on purpose, run this" in out.stderr
    assert "--uninstall" in out.stderr and "then run it again with the new settings." in out.stderr
    assert not other.exists() and box.files() == files and (box.data / "install-state").read_text() == state
    assert box.installed() == "cdlbib 2.0.0"


@need_uv
@pytest.mark.parametrize("shell", SHELLS)
def test_uninstall_that_cannot_be_done_keeps_the_record_and_everything_else(box, online, shell):
    """No uv at all, then a uv that fails (the tool directory cannot be written): each time the
    script ends with an error, says what to do, and the tool, the wheel and the record are as
    they were. With uv working again the same command removes everything; once more is a no-op."""
    if os.getuid() == 0:
        pytest.skip("a folder cannot be closed to root")
    box.with_uv().with_python()
    ok(box.run(shell=shell))
    files, state = box.files(), (box.data / "install-state").read_text()

    (box.programs / "uv").unlink()
    out = box.run("--uninstall", shell=shell)
    assert out.returncode == 1, out.stdout + out.stderr
    assert f"cdlbib is installed as a uv tool in {box.tool}" in out.stderr and "was not found" in out.stderr
    assert f"To remove it by hand: delete the folder {box.tool} and the links to it in" in out.stderr
    assert f"nothing else was removed, and the record {box.data}/install-state is kept." in out.stderr
    assert box.files() == files and (box.data / "install-state").read_text() == state
    assert box.installed() == "cdlbib 2.0.0"

    box.with_uv()
    folders = [box.tool.parent, box.tool, *(path for path in box.tool.rglob("*") if path.is_dir() and not path.is_symlink())]
    modes = {folder: folder.stat().st_mode & 0o7777 for folder in folders}
    for folder in folders:      # nothing in uv's tool can be deleted
        folder.chmod(0o500)
    try:
        out = box.run("--uninstall", shell=shell)
    finally:
        for folder, mode in modes.items():
            folder.chmod(mode)
    assert out.returncode == 1, out.stdout + out.stderr
    assert f"uv did not uninstall cdlbib from {box.tool.parent}" in out.stderr
    assert f"nothing else was removed, and the record {box.data}/install-state is kept." in out.stderr
    assert (box.data / "install-state").read_text() == state and box.tool.is_dir()
    assert box.files() == files and box.installed() == "cdlbib 2.0.0"

    out = ok(box.run("--uninstall", shell=shell))
    assert "Removed cdlbib." in out and not box.tool.exists() and not box.data.exists()
    assert not [command for command in COMMANDS if (box.bin / command).exists()]
    files = box.files()
    second = ok(box.run("--uninstall", shell=shell))
    assert "Nothing to remove" in second and box.files() == files


@need_uv
def test_a_record_of_the_earlier_form_is_uninstalled_through_the_command_link(box, online):
    """A state file written before the tool directory was recorded (method, bin and uv only):
    the tool directory is read from where the command link leads. Without that link there is
    no telling which tool directory it was: nothing is removed and the record is kept."""
    box.with_uv().with_python()
    ok(box.run())
    state = box.data / "install-state"
    earlier = f"method=uv\nbin={box.bin}\nuv={box.programs / 'uv'}\n"
    state.write_text(earlier)
    link = box.bin / "cdlbib"
    target = os.readlink(link)
    link.unlink()
    out = box.run("--uninstall")
    assert out.returncode == 1 and "does not say which tool directory of uv holds cdlbib" in out.stderr, out.stderr
    assert state.read_text() == earlier and box.tool.is_dir()
    os.symlink(target, link)
    assert "Removed cdlbib." in ok(box.run("--uninstall"))
    assert not box.tool.exists() and not box.data.exists() and not link.exists()


# --- what is downloaded is checked before it is run --------------------------------------------------

DIGEST_TOOLS = ("sha256sum", "shasum", "openssl")


def only_digest_tool(box, tool):
    """The PATH of the box has this one program to compute a SHA-256 with (or none)."""
    for name in DIGEST_TOOLS:
        if (box.programs / name).is_symlink():
            (box.programs / name).unlink()
    if tool != "none" and not box.link(tool):
        pytest.skip(f"this computer has no {tool}")


def planted_installer(box):
    """A file that would pass for an installer of uv by its version line and its mention of
    UV_UNMANAGED_INSTALL (all that was looked at before the fix); run, it writes RAN."""
    planted = box.root / "planted" / "install.sh"
    planted.parent.mkdir()
    planted.write_text(f'#!/bin/sh\nAPP_VERSION="{UV_VERSION}"\n# UV_UNMANAGED_INSTALL\n'
                       f'echo ran > "{planted.parent}/RAN"\nmkdir -p "$UV_UNMANAGED_INSTALL"\n'
                       f'printf \'#!/bin/sh\\necho "uv {UV_VERSION}"\\n\' > "$UV_UNMANAGED_INSTALL/uv"\n'
                       'chmod 755 "$UV_UNMANAGED_INSTALL/uv"\nexit 1\n')
    return planted


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("tool", DIGEST_TOOLS)
def test_an_installer_of_uv_with_another_digest_is_refused_and_never_run(box, tool, shell):
    """codex round 3, item 14, without the network: the file the installer is read from is not
    the one whose SHA-256 is written in install.sh. It is not run, with each of the programs
    the digest can be computed with, and the message names the digest found, the one expected
    and how to install uv by hand. Naming another digest or version in the environment
    changes nothing."""
    if not box.link("curl"):
        pytest.skip("curl is not installed")
    only_digest_tool(box, tool)
    planted = planted_installer(box)
    for more in ({}, {"UV_INSTALLER_SHA256": digest(planted), "UV_VERSION": "9.9.9", "UV_INSTALLER": str(planted),
                      "CDLBIB_UV_INSTALLER_SHA256": digest(planted)}):
        out = box.with_old_python().run(shell=shell, env=box.env(CDLBIB_UV_INSTALLER=str(planted), **more))
        assert out.returncode == 1, out.stdout + out.stderr
        assert f"is not the installer of uv {UV_VERSION} that this script" in out.stderr, out.stderr
        assert f"its SHA-256 is {digest(planted)}" in out.stderr and f"and {UV_INSTALLER_SHA256} is expected." in out.stderr
        assert "It was not run. Nothing was installed. Install uv by hand" in out.stderr
        assert "https://docs.astral.sh/uv/getting-started/installation/" in out.stderr
        assert "UV_UNMANAGED_INSTALL=" not in out.stdout
        assert not (planted.parent / "RAN").exists(), "the planted installer was run"
        assert box.files() == set() and box.leftovers() == []


def test_without_a_program_to_compute_a_digest_nothing_is_downloaded(box):
    if not box.link("curl"):
        pytest.skip("curl is not installed")
    only_digest_tool(box, "none")
    planted = planted_installer(box)
    out = box.with_old_python().run(env=box.env(CDLBIB_UV_INSTALLER=str(planted)))
    assert out.returncode == 1, out.stdout + out.stderr
    assert "what is downloaded cannot be checked: none of" in out.stderr and "sha256sum, shasum and openssl" in out.stderr
    assert "+ " not in out.stdout and not (planted.parent / "RAN").exists()
    assert box.files() == set() and box.leftovers() == []


def test_help_says_what_is_checked_when_uv_is_downloaded(box):
    out = ok(box.run("--help"))
    assert f"downloads uv {UV_VERSION} with its installer" in out
    assert f"(https://astral.sh/uv/{UV_VERSION}/install.sh)" in out
    for said in ("What is checked when uv is downloaded:", "its SHA-256 must be the one written in this script",
                 "the installer carries the SHA-256 of the archive for each platform",
                 "Not checked: signatures"):
        assert said in out, said
    assert "UV_VERSION_HERE" not in out


def fetched(address):
    """The bytes at an address (uv's site answers 403 to urllib's default User-Agent)."""
    request = urllib.request.Request(address, headers={"User-Agent": "cdlbib-install-tests"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        return reply.read()


@download_uv
def test_the_digest_in_the_script_is_the_digest_of_the_installer_on_uvs_site(online):
    """The live file. It also still does what install.sh relies on: it carries a SHA-256 for
    each archive, compares the archive with it (skipping that without a sha256sum command),
    and honours UV_UNMANAGED_INSTALL."""
    body = fetched(UV_INSTALLER)
    assert hashlib.sha256(body).hexdigest() == UV_INSTALLER_SHA256
    text = body.decode("utf-8")
    assert f'APP_VERSION="{UV_VERSION}"' in text and "UV_UNMANAGED_INSTALL" in text
    assert 'verify_checksum "$_file" "$_checksum_style" "$_checksum_value"' in text
    assert len(re.findall(r'_checksum_style="sha256"\n\s+_checksum_value="[0-9a-f]{64}"', text)) >= 10
    assert "if ! check_cmd sha256sum; then" in text


@download_uv
def test_the_genuine_installer_with_one_line_added_is_refused(box, online):
    if not box.link("curl"):
        pytest.skip("curl is not installed")
    changed = box.root / "changed" / "install.sh"
    changed.parent.mkdir()
    changed.write_bytes(fetched(UV_INSTALLER) + f'\necho ran > "{changed.parent}/RAN"\n'.encode())
    out = box.with_old_python().run(env=box.env(CDLBIB_UV_INSTALLER=str(changed)))
    assert out.returncode == 1 and "It was not run. Nothing was installed." in out.stderr, out.stdout + out.stderr
    assert not (changed.parent / "RAN").exists() and box.files() == set() and box.leftovers() == []


@download_uv
@pytest.mark.parametrize("tool", DIGEST_TOOLS)
def test_an_archive_of_uv_with_another_digest_is_refused_by_the_installer(box, online, tool, tmp_path):
    """The genuine installer, told (by its own setting INSTALLER_DOWNLOAD_URL) to fetch the
    archive of uv from a folder that holds another file under that name: it compares the
    archive with the SHA-256 it carries and stops before unpacking, whichever program the
    script made its sha256sum from. No uv is left and nothing of the archive runs."""
    if not box.link("curl"):
        pytest.skip("curl is not installed")
    only_digest_tool(box, tool)
    machine = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64", "AMD64": "x86_64"}[platform.machine()]
    targets = ([f"{machine}-apple-darwin"] if sys.platform == "darwin" else
               [f"{machine}-unknown-linux-gnu", f"{machine}-unknown-linux-musl"])
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    for target in targets:
        inside = tmp_path / f"uv-{target}"
        inside.mkdir()
        for name in ("uv", "uvx"):
            (inside / name).write_text(f'#!/bin/sh\necho ran >> "{tmp_path}/RAN"\necho "uv {UV_VERSION}"\n')
            (inside / name).chmod(0o755)
        with tarfile.open(mirror / f"uv-{target}.tar.gz", "w:gz") as tar:
            tar.add(inside, arcname=f"uv-{target}")
    out = box.with_old_python().run(env=box.env(INSTALLER_DOWNLOAD_URL=f"file://{mirror}"))
    said = out.stdout + out.stderr
    assert out.returncode == 1, said
    assert "checksum mismatch" in said and "the installer of uv failed" in out.stderr, said
    assert "skipping sha256 checksum verification" not in said
    assert not (tmp_path / "RAN").exists(), "a program from the archive was run"
    assert not (box.data / "uv" / "uv").exists() and not (box.bin / "cdlbib").exists()
    assert box.leftovers() == []


# --- a failure in the last phase, after the new version has been tried beside the old one ------------

def own_files(box):
    """box.files() without the lock file uv keeps beside its tools once it has asked an index."""
    return {name for name in box.files() if not name.startswith(".local/share/uv/credentials/")}


def nothing_set_aside(box):
    assert not (box.data / "kept").exists() and not (box.data / "kept.done").exists()
    assert not (box.data / "venv.kept").exists()
    assert not (box.tool.parent / "cdlbib-kept-by-install-sh").exists()
    assert not [path.name for path in box.bin.iterdir() if path.name.endswith(".new")]
    assert not os.path.lexists(box.data / "install-lock"), "the run ended and its lock is still there"
    assert not os.path.lexists(box.data / "install-lock.takeover")


def uv_that_fails_the_live_installation(box, damage):
    """The uv of the box becomes a program that runs the real uv for everything except the
    installation into the live tool directory (the one with --reinstall-package; the trial
    beside it has none): that one fails, at once or after the real uv has replaced the
    environment and the program has then deleted its packages and its command."""
    real = os.path.realpath(box.programs / "uv")
    (box.programs / "uv").unlink()
    after = (f'"{real}" "$@"\nrm -rf "$UV_TOOL_DIR/cdlbib/lib"\nrm -f "$UV_TOOL_BIN_DIR/cdlbib"\n'
             if damage == "after replacing and breaking the environment" else "")
    (box.programs / "uv").write_text(
        '#!/bin/sh\ncase " $* " in\n  *" tool install "*" --reinstall-package "*)\n'
        f'{after}    echo "this uv fails the installation into the live tool directory" >&2\n    exit 1 ;;\nesac\n'
        f'exec "{real}" "$@"\n')
    (box.programs / "uv").chmod(0o755)
    return real


def real_uv_again(box, real):
    (box.programs / "uv").unlink()
    os.symlink(real, box.programs / "uv")


@need_uv
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("damage", ["at once", "after replacing and breaking the environment"])
@pytest.mark.parametrize("change", ["a new version", "the same version with other content"])
def test_a_live_installation_that_fails_after_the_trial_puts_the_old_one_back(box, online, change, damage, shell):
    """codex round 4, item 12. The trial beside the installed version succeeds; the
    installation into the live tool directory then fails. The environment, the wheel (also
    one of the same name), the command links and the state file are what they were."""
    box.with_uv().with_python()
    ok(box.run(shell=shell))
    wheel = box.data / "dist" / "cdlbib-2.0.0-py3-none-any.whl"
    state = box.data / "install-state"
    before = (own_files(box), state.read_bytes(), digest(wheel), tree(box.tool), listing(box.bin),
              {name: os.readlink(box.bin / name) for name in COMMANDS})
    if change == "a new version":
        box.set_version("2.0.1")
    else:
        (box.checkout / "src" / "cdlbib" / "added_for_the_test.py").write_text("VALUE = 1\n")
    real = uv_that_fails_the_live_installation(box, damage)
    out = box.run(shell=shell)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "it is kept until the new version has been installed beside it and has run" in out.stdout
    assert "this uv fails the installation into the live tool directory" in out.stderr
    assert (f"The installation that was there is unchanged: {box.bin}/cdlbib runs as before."
            in out.stderr), out.stdout + out.stderr
    assert box.installed() == "cdlbib 2.0.0"
    after = (own_files(box), state.read_bytes(), digest(wheel), tree(box.tool), listing(box.bin),
             {name: os.readlink(box.bin / name) for name in COMMANDS})
    for name, was, now in zip(("files", "state", "wheel", "environment", "bin", "links"), before, after):
        assert was == now, name
    assert sorted(os.listdir(box.data / "dist")) == ["cdlbib-2.0.0-py3-none-any.whl"]
    nothing_set_aside(box)
    assert box.leftovers() == []
    python = str(box.tool / "bin" / "python")
    assert subprocess.run([python, "-I", "-c", "import cdlbib.added_for_the_test"], env=box.env(),
                          capture_output=True).returncode != 0

    real_uv_again(box, real)
    out = ok(box.run(shell=shell))
    if change == "a new version":
        assert "Installed: cdlbib 2.0.1" in out and box.installed() == "cdlbib 2.0.1"
        assert sorted(os.listdir(box.data / "dist")) == ["cdlbib-2.0.1-py3-none-any.whl"]
    else:
        assert subprocess.run([python, "-I", "-c", "import cdlbib.added_for_the_test"], env=box.env(),
                              capture_output=True).returncode == 0
        assert digest(wheel) != before[2]
    nothing_set_aside(box)


@need_uv
@pytest.mark.parametrize("damage", ["at once", "after replacing and breaking the environment"])
def test_a_change_from_the_virtual_environment_to_uv_that_fails_leaves_the_virtual_environment(box, online, damage):
    box.with_python()
    ok(box.run("--no-uv"))
    venv, state = box.data / "venv", box.data / "install-state"
    before = (own_files(box), state.read_bytes(), {name: os.readlink(box.bin / name) for name in COMMANDS})
    box.with_uv()
    real = uv_that_fails_the_live_installation(box, damage)
    out = box.run()
    assert out.returncode == 1, out.stdout + out.stderr
    assert (f"The installation that was there is unchanged: {box.bin}/cdlbib runs as before."
            in out.stderr), out.stdout + out.stderr
    assert box.installed() == "cdlbib 2.0.0" and not box.tool.exists()
    assert (own_files(box) - {name for name in own_files(box) if name.startswith(".local/share/uv/")
                              or name.startswith(".local/share/cdlbib/dist/")},
            state.read_bytes(), {name: os.readlink(box.bin / name) for name in COMMANDS}) == before
    assert all(os.readlink(box.bin / name) == str(venv / "bin" / name) for name in COMMANDS)
    assert not list((box.data / "dist").glob("*.whl")), "a wheel was left for an installation that is not there"
    nothing_set_aside(box)
    real_uv_again(box, real)
    out = ok(box.run())
    assert "Replacing the earlier installation (made with venv)." in out and "installed with uv" in out
    assert not venv.exists() and box.installed() == "cdlbib 2.0.0"
    assert recorded_state(box)["method"] == "uv" and "venv_bin" not in recorded_state(box)


@need_uv
def test_a_change_from_uv_to_the_virtual_environment_that_fails_among_the_links_leaves_uvs_commands(box, online):
    """The new links are made one by one. Here the program that puts them in place (mv) fails
    at the second link, when the first already leads to the virtual environment: all the
    links lead to uv's environment again, and the new virtual environment is gone."""
    box.with_uv().with_python()
    ok(box.run())
    state = box.data / "install-state"
    before = (own_files(box), state.read_bytes(), tree(box.tool), {name: os.readlink(box.bin / name) for name in COMMANDS})
    (box.programs / "uv").unlink()
    real = os.path.realpath(box.programs / "mv")
    count = box.root / "moves into bin"
    (box.programs / "mv").unlink()
    (box.programs / "mv").write_text(
        '#!/bin/sh\nfor last in "$@"; do :; done\n'
        f'case $last in\n  "{box.bin}"/*)\n    echo x >> "{count}"\n'
        f'    if [ "$(wc -l < "{count}")" -ge 2 ]; then echo "this mv fails at the second link" >&2; exit 1; fi ;;\nesac\n'
        f'exec "{real}" "$@"\n')
    (box.programs / "mv").chmod(0o755)
    out = box.run("--no-uv")
    assert out.returncode == 1, out.stdout + out.stderr
    assert "this mv fails at the second link" in out.stderr and count.read_text() == "x\nx\n"
    assert (f"The installation that was there is unchanged: {box.bin}/cdlbib runs as before."
            in out.stderr), out.stdout + out.stderr
    assert box.installed() == "cdlbib 2.0.0" and not (box.data / "venv").exists()
    assert (own_files(box), state.read_bytes(), tree(box.tool),
            {name: os.readlink(box.bin / name) for name in COMMANDS}) == before
    nothing_set_aside(box)

    (box.programs / "mv").unlink()
    os.symlink(real, box.programs / "mv")
    out = ok(box.run("--no-uv"))
    assert "Replacing the earlier installation (made with uv)." in out and "installed with venv" in out
    assert box.installed() == "cdlbib 2.0.0" and not box.tool.exists() and not (box.data / "dist").exists()
    assert all(os.readlink(box.bin / name) == str(box.data / "venv" / "bin" / name) for name in COMMANDS)
    assert recorded_state(box) == {"method": "venv", "bin": str(box.bin), "venv_bin": str(box.bin)}


def test_a_new_version_that_does_not_run_leaves_the_virtual_environment_as_it_was(box, online):
    """--no-uv, where pip changes the environment in place: the new version installs, and its
    command fails. The copy of the environment that was set aside is put back."""
    box.with_python()
    ok(box.run("--no-uv"))
    state = box.data / "install-state"
    before = (box.files(), state.read_bytes())
    box.set_version("2.0.1")
    module = box.checkout / "src" / "cdlbib" / "__init__.py"
    good = module.read_text(encoding="utf-8")
    module.write_text(good + "\nraise SystemExit(3)\n", encoding="utf-8")
    out = box.run("--no-uv")
    assert out.returncode == 1, out.stdout + out.stderr
    assert "was installed but 'cdlbib --version' failed." in out.stderr
    assert (f"The installation that was there is unchanged: {box.bin}/cdlbib runs as before."
            in out.stderr), out.stdout + out.stderr
    assert box.installed() == "cdlbib 2.0.0" and (box.files(), state.read_bytes()) == before
    nothing_set_aside(box)
    module.write_text(good, encoding="utf-8")
    assert "Installed: cdlbib 2.0.1" in ok(box.run("--no-uv")) and box.installed() == "cdlbib 2.0.1"
    nothing_set_aside(box)


@need_uv
def test_a_new_version_that_does_not_run_is_never_put_in_the_place_of_uvs_tool(box, online):
    """With uv the same new version fails beside the installed one, which is not touched."""
    box.with_uv().with_python()
    ok(box.run())
    environment, state = tree(box.tool), (box.data / "install-state").read_bytes()
    box.set_version("2.0.1")
    module = box.checkout / "src" / "cdlbib" / "__init__.py"
    module.write_text(module.read_text(encoding="utf-8") + "\nraise SystemExit(3)\n", encoding="utf-8")
    out = box.run()
    assert out.returncode == 1 and "runs as before" in out.stderr, out.stdout + out.stderr
    assert "--reinstall-package" not in out.stdout
    assert box.installed() == "cdlbib 2.0.0" and tree(box.tool) == environment
    assert (box.data / "install-state").read_bytes() == state
    assert sorted(os.listdir(box.data / "dist")) == ["cdlbib-2.0.0-py3-none-any.whl"]
    nothing_set_aside(box)


@need_uv
def test_a_run_killed_without_warning_during_the_live_installation_is_undone_by_the_next_run(box, online):
    """SIGKILL (which no script can catch) to the whole process group as soon as the live
    `uv tool install` is printed: the old environment is still set aside. The next run puts
    it back before anything else; here that run's own source cannot be built, so what is
    left is the old installation, complete."""
    box.with_uv().with_python()
    ok(box.run())
    wheel = box.data / "dist" / "cdlbib-2.0.0-py3-none-any.whl"
    state = box.data / "install-state"
    before = (own_files(box), state.read_bytes(), digest(wheel), tree(box.tool))
    box.set_version("2.0.1")
    process = subprocess.Popen(box.command(), env=box.env(), cwd=box.root, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    for line in process.stdout:
        if line.startswith("+ ") and " --reinstall-package " in line:
            os.killpg(process.pid, signal.SIGKILL)
            break
    process.stdout.read()
    assert process.wait(timeout=120) == -signal.SIGKILL
    assert (box.data / "kept" / "where").is_file()
    assert (box.tool.parent / "cdlbib-kept-by-install-sh").is_dir()
    assert holder(box) == process.pid, "the killed run could not give its lock back"
    for path in box.tmp.iterdir():          # the killed run could not remove its temporary folder
        shutil.rmtree(path)

    project = box.checkout / "pyproject.toml"
    project.write_text(project.read_text(encoding="utf-8") + "\n[[[ this line is not TOML\n", encoding="utf-8")
    out = box.run()
    assert out.returncode == 1, out.stdout + out.stderr
    assert ("An earlier run was stopped while it replaced the installation: the installation that was there "
            "is put back.") in out.stdout
    assert (f"A run of this script that is no longer running (process {process.pid}) left its lock: "
            "this run takes it over.") in out.stdout
    assert out.stdout.index("this run takes it over.") < out.stdout.index("An earlier run was stopped")
    assert box.installed() == "cdlbib 2.0.0"
    assert (own_files(box), state.read_bytes(), digest(wheel), tree(box.tool)) == before
    nothing_set_aside(box)


# --- two names of one tool directory ----------------------------------------------------------------

@need_uv
def test_another_name_of_the_same_tool_directory_is_the_same_installation(box, online):
    """codex round 4, N6. UV_TOOL_DIR and UV_TOOL_BIN_DIR name the folders of the installation
    through links: it is the same installation, it is upgraded, and the state file records
    the folders by their physical paths."""
    box.with_uv().with_python()
    ok(box.run())
    alias = box.root / "other names"
    alias.mkdir()
    os.symlink(box.tool.parent, alias / "tools")
    os.symlink(box.bin, alias / "bin")
    elsewhere = box.env(UV_TOOL_DIR=str(alias / "tools"), UV_TOOL_BIN_DIR=str(alias / "bin"))
    box.set_version("2.0.1")
    out = ok(box.run(env=elsewhere))
    assert "Installed: cdlbib 2.0.1" in out and box.installed() == "cdlbib 2.0.1"
    assert recorded_state(box)["tool_dir"] == str(box.tool.parent) and recorded_state(box)["tool_bin"] == str(box.bin)
    assert "Installed: cdlbib 2.0.1" in ok(box.run())
    (alias / "tools").unlink()
    (alias / "bin").unlink()
    assert "Removed cdlbib." in ok(box.run("--uninstall", env=elsewhere))
    assert not box.tool.exists() and not box.data.exists()


# --- one run at a time (codex round 5, item R5-2) -----------------------------------------------------
# The lock is the link install-lock in the script's data folder; its text names the run that
# holds it: PID:START:HOST. Every run here is the real script in a real process.

HOST = re.sub(r"[^A-Za-z0-9.-]", "-", os.uname().nodename)
# How this computer says when a process started (the script reads /proc where there is one, else ps).
START_KIND = "proc" if os.path.exists(f"/proc/{os.getpid()}/stat") else "ps"
ANOTHER_START = "proc-1" if START_KIND == "proc" else "ps-Thu-Jan-1-00-00-00-1970"


def lock_text(box, name="install-lock"):
    """The text of the lock, or None when there is no lock."""
    path = box.data / name
    return os.readlink(path) if os.path.islink(path) else None


def holder(box):
    """The process number in the lock (None without a lock); the rest of the text is checked."""
    text = lock_text(box)
    if text is None:
        return None
    match = re.fullmatch(rf"(\d+):{START_KIND}-[A-Za-z0-9-]+:{re.escape(HOST)}", text)
    assert match, text
    return int(match.group(1))


def no_lock(box):
    return not os.path.lexists(box.data / "install-lock") and not os.path.lexists(box.data / "install-lock.takeover")


def gone_process():
    """The number of a real process that has ended."""
    process = subprocess.Popen(["/bin/sh", "-c", "exit 0"], env=BARE)
    process.wait(timeout=30)
    return process.pid


def refused(out, box, pid=None, name="install-lock"):
    assert out.returncode == 1, out.stdout + out.stderr
    if pid is not None:
        assert (f"install.sh: another run of this script is installing or removing cdlbib (process {pid} on "
                in out.stderr), out.stderr
    assert "Nothing was changed." in out.stderr, out.stderr
    assert f"The lock is {box.data / name}\n" in out.stderr, out.stderr
    assert (f"  rm -f '{box.data}/install-lock' '{box.data}/install-lock.takeover'\n" in out.stderr), out.stderr
    assert "Installing cdlbib" not in out.stdout and "Removed" not in out.stdout and "Nothing to remove" not in out.stdout


class Asked:
    """The script started with --ask on a real pseudo-terminal. It takes the lock, then asks
    its question and waits: a run that holds the lock for as long as the test wants, with no
    network. What it prints goes to a file."""

    def __init__(self, box, name, *args, shell="/bin/sh"):
        self.master, slave = pty.openpty()
        self.log = box.root / f"{name}.log"
        with open(self.log, "wb") as log:
            self.process = subprocess.Popen(box.command("--ask", *args, shell=shell), env=box.env(), cwd=box.root,
                                            stdin=slave, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        os.close(slave)
        self.pid = self.process.pid

    def text(self):
        return self.log.read_text(encoding="utf-8", errors="replace")

    def asking(self):
        return "[y/N]" in self.text()

    def wait_until_asked(self):
        deadline = time.time() + 120
        while time.time() < deadline and not self.asking() and self.process.poll() is None:
            time.sleep(0.05)
        assert self.asking() and self.process.poll() is None, self.text()
        return self

    def end(self, how):
        if how == "answered no":
            os.write(self.master, b"n\n")
        else:
            os.killpg(self.pid, getattr(signal, how))
        code = self.process.wait(timeout=120)
        os.close(self.master)
        return code

    def stop(self):
        if self.process.poll() is None:
            os.killpg(self.pid, signal.SIGKILL)
            self.process.wait(timeout=60)
            os.close(self.master)


@need_uv
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("ending", ["answered no", "SIGINT", "SIGTERM", "SIGHUP"])
def test_a_run_started_while_another_holds_the_lock_changes_nothing_and_the_lock_goes_when_the_first_ends(box, ending, shell):
    """A live lock is refused, by an installation and by --uninstall, with a message that names
    the lock and says how to remove it; the run that holds it gives it back when it stops
    with an error and when it gets SIGINT, SIGTERM or SIGHUP."""
    box.with_uv()
    first = Asked(box, "first", shell=shell)
    try:
        first.wait_until_asked()
        assert holder(box) == first.pid
        text = lock_text(box)
        for args in ((), ("--uninstall",), ("--no-uv",)):
            started = time.time()
            refused(box.run(*args, shell=shell), box, first.pid)
            assert time.time() - started < 60, "the second run waited"
            assert lock_text(box) == text and first.process.poll() is None
        code = first.end(ending)
    finally:
        first.stop()
    assert code == {"answered no": 1, "SIGINT": 130, "SIGTERM": 143, "SIGHUP": 143}[ending], first.text()
    assert no_lock(box) and box.files() == set() and box.leftovers() == []
    assert "Nothing to remove" in ok(box.run("--uninstall", shell=shell))
    assert no_lock(box) and not box.data.exists()
    assert list(box.home.iterdir()) == [], "a folder that was made for the lock is left"


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("left_by", ["a process that is gone", "a process whose number another process has now"])
def test_a_lock_whose_process_is_gone_is_taken_over(box, left_by, shell):
    """A lock that a killed run left: no process has its number, or a process that started at
    another time has it (this test's own process, here)."""
    pid = gone_process() if left_by == "a process that is gone" else os.getpid()
    box.data.mkdir(parents=True)
    os.symlink(f"{pid}:{ANOTHER_START}:{HOST}", box.data / "install-lock")
    out = ok(box.with_uv().run("--uninstall", shell=shell))
    assert f"A run of this script that is no longer running (process {pid}) left its lock: this run takes it over." in out
    assert "Nothing to remove" in out
    assert no_lock(box) and not box.data.exists() and box.files() == set()


UNDECIDED = {
    "a process that runs, and no start in the lock": lambda: f"{os.getpid()}:unknown:{HOST}",
    "a process that runs, its start read another way": lambda: (
        f"{os.getpid()}:{'ps-Thu-Jan-1-00-00-00-1970' if START_KIND == 'proc' else 'proc-1'}:{HOST}"),
    "another computer": lambda: f"{gone_process()}:{ANOTHER_START}:another-computer.example",
    "a text that is not a lock's": lambda: "something else",
    "a process number that is not a number": lambda: f"12x:{ANOTHER_START}:{HOST}",
}


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("what", [*UNDECIDED, "a folder"])
def test_a_lock_that_cannot_be_shown_to_be_left_behind_is_not_taken_over(box, what, shell):
    """Only a lock whose process is shown to be gone is taken over. Everything else stops the
    script, at once, with the lock left as it is."""
    box.data.mkdir(parents=True)
    lock = box.data / "install-lock"
    if what == "a folder":
        (lock / "inside").mkdir(parents=True)
    else:
        os.symlink(UNDECIDED[what](), lock)
    text = lock_text(box)
    for args in (("--uninstall",), ()):
        refused(box.with_uv().run(*args, shell=shell), box)
        assert lock_text(box) == text and (text is not None or (lock / "inside").is_dir())
        assert sorted(path.name for path in box.data.iterdir()) == ["install-lock"]
        assert sorted(path.name for path in lock.iterdir()) == ["inside"] if text is None else True
    assert box.leftovers() == []


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("taker", ["gone", "running"])
def test_a_takeover_that_another_run_began_is_not_repeated(box, taker, shell):
    """The lock's process is gone and another run holds install-lock.takeover (or was killed
    holding it): this run takes nothing over, removes nothing, and names that link."""
    box.data.mkdir(parents=True)
    os.symlink(f"{gone_process()}:{ANOTHER_START}:{HOST}", box.data / "install-lock")
    other = gone_process() if taker == "gone" else os.getpid()
    os.symlink(f"{other}:{'unknown' if taker == 'running' else ANOTHER_START}:{HOST}", box.data / "install-lock.takeover")
    texts = (lock_text(box), lock_text(box, "install-lock.takeover"))
    refused(box.with_uv().run("--uninstall", shell=shell), box, other, name="install-lock.takeover")
    assert (lock_text(box), lock_text(box, "install-lock.takeover")) == texts


@need_uv
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("start", ["no lock", "a lock whose process is gone"])
def test_of_many_runs_started_together_one_gets_the_lock(box, start, shell):
    """Eight runs at once, over nothing or over a lock that a killed run left: exactly one
    reaches its question, with the lock in its name; the seven others changed nothing."""
    box.with_uv()
    if start != "no lock":
        box.data.mkdir(parents=True)
        os.symlink(f"{gone_process()}:{ANOTHER_START}:{HOST}", box.data / "install-lock")
    runs = [Asked(box, f"run {number}", shell=shell) for number in range(8)]
    try:
        deadline = time.time() + 180
        while time.time() < deadline:
            going = [run for run in runs if run.process.poll() is None]
            if len(going) <= 1 and all(run.asking() for run in going):
                break
            time.sleep(0.05)
        assert len(going) == 1, [run.text() for run in runs]
        winner = going[0]
        time.sleep(1)
        assert winner.process.poll() is None and winner.asking()
        assert holder(box) == winner.pid and lock_text(box, "install-lock.takeover") is None
        for run in runs:
            if run is not winner:
                assert run.process.returncode == 1, run.text()
                assert "Nothing was changed." in run.text() and f"The lock is {box.data}/install-lock" in run.text()
                assert "[y/N]" not in run.text()
                os.close(run.master)
        # The run that removes the old lock is one run; the lock it then makes can go to
        # another that asked in that moment, so the one that says so need not be the winner.
        took_over = [run for run in runs if "this run takes it over." in run.text()]
        assert len(took_over) <= (start != "no lock") and all(run is winner for run in took_over)
        assert winner.end("answered no") == 1
    finally:
        for run in runs:
            run.stop()
    assert no_lock(box) and box.files() == set()


def uv_that_waits_in_the_live_installation(box, then):
    """The uv of the box becomes a program that runs the real uv for everything except the
    installation into the live tool directory: there it makes the file `reached`, waits for the
    file `go`, and then fails after the real uv has replaced the environment and the program
    has deleted its packages and its command ("fails"), or runs the real uv ("succeeds")."""
    real = os.path.realpath(box.programs / "uv")
    reached, go = box.root / "reached", box.root / "go"
    (box.programs / "uv").unlink()
    after = (f'    "{real}" "$@"\n    rm -rf "$UV_TOOL_DIR/cdlbib/lib"\n    rm -f "$UV_TOOL_BIN_DIR/cdlbib"\n'
             '    echo "this uv fails the installation into the live tool directory" >&2\n    exit 1 ;;\n'
             if then == "fails" else '    ;;\n')
    (box.programs / "uv").write_text(
        '#!/bin/sh\ncase " $* " in\n  *" tool install "*" --reinstall-package "*)\n'
        f'    : > "{reached}"\n    while [ ! -e "{go}" ]; do sleep 1; done\n{after}esac\n'
        f'exec "{real}" "$@"\n')
    (box.programs / "uv").chmod(0o755)
    return real, reached, go


@need_uv
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("then", ["fails", "succeeds"])
def test_a_run_started_while_another_replaces_the_installation_touches_nothing_of_it(box, online, then, shell):
    """codex round 5, R5-2. The first run has set the working installation aside and its uv is
    at work in the live tool directory (held there by the test). A second installation and an
    --uninstall started now are refused; what the first run set aside is as it was. When the
    first run's installation then fails, the installation that was there is put back and
    works; when it succeeds, the new version is installed."""
    box.with_uv().with_python()
    ok(box.run(shell=shell))
    wheel = box.data / "dist" / "cdlbib-2.0.0-py3-none-any.whl"
    state = box.data / "install-state"
    before = (own_files(box), state.read_bytes(), digest(wheel), tree(box.tool))
    box.set_version("2.0.1")
    real, reached, go = uv_that_waits_in_the_live_installation(box, then)
    log = box.root / "first.log"
    with open(log, "wb") as output:
        first = subprocess.Popen(box.command(shell=shell), env=box.env(), cwd=box.root, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        deadline = time.time() + 1800
        while time.time() < deadline and not reached.exists() and first.poll() is None:
            time.sleep(0.1)
        assert reached.exists() and first.poll() is None, log.read_text(errors="replace")
        kept_tool = box.tool.parent / "cdlbib-kept-by-install-sh"
        assert holder(box) == first.pid
        assert (box.data / "kept" / "where").is_file() and kept_tool.is_dir()
        aside = (tree(kept_tool), tree(box.data / "kept"), state.read_bytes(), lock_text(box))
        assert aside[0] == before[3], "what is set aside is the environment that was installed"
        for args in ((), ("--uninstall",), ("--no-uv",), ()):
            refused(box.run(*args, shell=shell), box, first.pid)
            assert (tree(kept_tool), tree(box.data / "kept"), state.read_bytes(), lock_text(box)) == aside
            assert first.poll() is None
        go.write_text("")
        code = first.wait(timeout=1800)
    finally:
        if first.poll() is None:
            os.killpg(first.pid, signal.SIGKILL)
            first.wait(timeout=60)
    output = log.read_text(errors="replace")
    if then == "fails":
        assert code == 1, output
        assert f"The installation that was there is unchanged: {box.bin}/cdlbib runs as before." in output
        assert box.installed() == "cdlbib 2.0.0"
        assert (own_files(box), state.read_bytes(), digest(wheel), tree(box.tool)) == before
    else:
        assert code == 0, output
        assert "Installed: cdlbib 2.0.1" in output and box.installed() == "cdlbib 2.0.1"
    nothing_set_aside(box)
    assert box.leftovers() == []
    real_uv_again(box, real)
    out = ok(box.run(shell=shell))
    assert "Installed: cdlbib 2.0.1" in out and box.installed() == "cdlbib 2.0.1"
    assert sorted(os.listdir(box.data / "dist")) == ["cdlbib-2.0.1-py3-none-any.whl"]
    nothing_set_aside(box)
    assert "Removed cdlbib." in ok(box.run("--uninstall", shell=shell))
    assert not box.tool.exists() and not box.data.exists()


@need_uv
def test_what_another_run_set_aside_is_never_deleted_to_make_room(box, online):
    """Something stands where this run would set the installation aside, and no record says
    it is an unfinished replacement: it is not deleted. The run stops, the installation is
    unchanged, and the message names what is in the way."""
    box.with_uv().with_python()
    ok(box.run())
    state = box.data / "install-state"
    before = (state.read_bytes(), tree(box.tool))
    in_the_way = box.tool.parent / "cdlbib-kept-by-install-sh"
    (in_the_way / "bin").mkdir(parents=True)
    (in_the_way / "bin" / "the only copy").write_text("of an installation another run set aside\n")
    box.set_version("2.0.1")
    out = box.run()
    assert out.returncode == 1, out.stdout + out.stderr
    assert f"install.sh: {in_the_way} is there, and this run did not put it there." in out.stderr, out.stderr
    assert f"The installation that was there is unchanged: {box.bin}/cdlbib runs as before." in out.stderr
    assert (in_the_way / "bin" / "the only copy").read_text() == "of an installation another run set aside\n"
    assert box.installed() == "cdlbib 2.0.0" and (state.read_bytes(), tree(box.tool)) == before
    assert no_lock(box) and not (box.data / "kept").exists()
    assert sorted(os.listdir(box.data / "dist")) == ["cdlbib-2.0.0-py3-none-any.whl"]
    shutil.rmtree(in_the_way)
    assert "Installed: cdlbib 2.0.1" in ok(box.run())
    nothing_set_aside(box)
