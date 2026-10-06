"""install.sh, run for real: the script itself, real uv, real Pythons, real installations.

Nothing is substituted. Each test runs the script with a home folder, a temporary folder and
caches of its own, and with a PATH that is one folder of links to this computer's programs:
"uv is not installed" is a PATH that really has no uv, "the default Python is too old" is a
PATH whose python3 is a real older interpreter (when this computer has one; otherwise a PATH
with no Python at all). The package is installed from a copy of this checkout, in a folder
whose name has a space; its dependencies come from PyPI, so the tests that install need
the network and are skipped by name without it.

The tests that download uv itself (uv's installer from astral.sh, and one old uv from
GitHub's releases) run only when asked for:

    CDLBIB_TEST_INSTALL_UV_DOWNLOAD=1 pytest tests/test_install_script.py

No test writes into the real home folder: every test compares the real ~/.local/bin, uv's
real tool folder and the shell profiles before and after."""
import os
import platform
import pty
import pwd
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
REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
SYSTEM = "/usr/bin:/bin:/usr/sbin:/sbin"
# What a shell script, uv's installer, pip and a Python build may call. Linked one by one,
# so that the PATH of a test holds no Python, no uv and no git unless the test adds it.
SYSTEM_TOOLS = ("sh awk base64 basename cat chmod cp cut date dirname env expr false find getconf grep gzip head "
                "id install ld ldd ln ls mkdir mktemp mv od readlink rm rmdir sed sleep sort sw_vers tail tar tee "
                "touch tr true uname uniq wc which xargs xcode-select").split()
COMMANDS = ("cdlbib", "cdlbib-adapter-dartmouth", "cdlbib-adapter-openai")
DOWNLOAD_UV = os.environ.get("CDLBIB_TEST_INSTALL_UV_DOWNLOAD") == "1"
download_uv = pytest.mark.skipif(not DOWNLOAD_UV, reason="downloads uv; set CDLBIB_TEST_INSTALL_UV_DOWNLOAD=1 to run")
SHELLS = sorted({os.path.realpath(found) for found in ("/bin/sh", shutil.which("dash", path=SYSTEM)) if found})


def version_of(program):
    try:
        out = subprocess.run([program, "-B", "-c", "import sys; print(*sys.version_info[:2])"],
                             capture_output=True, text=True, timeout=30)
        major, minor = out.stdout.split()
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def real_executable(program):
    """The interpreter itself (on macOS /usr/bin/python3 only starts the developer tools' one)."""
    out = subprocess.run([program, "-B", "-c", "import sys; print(getattr(sys, '_base_executable', '') or sys.executable)"],
                         capture_output=True, text=True, timeout=30)
    return out.stdout.strip() or program


def old_python():
    """A real Python older than 3.11 on this computer, or None."""
    for name in ("/usr/bin/python3", "python3.10", "python3.9", "python3.8"):
        found = shutil.which(name)
        if found and (version_of(found) or (9, 9)) < (3, 11):
            return real_executable(found)
    return None


OLD_PYTHON = old_python()
NEW_PYTHON = real_executable(sys.executable)   # the tests themselves need Python 3.11 or later
UV = shutil.which("uv")
need_uv = pytest.mark.skipif(not UV, reason="uv is not installed")


def listing(folder):
    """{name: (size, modification time)} of what is directly in a folder ({} when absent)."""
    try:
        return {entry.name: (entry.lstat().st_size, entry.lstat().st_mtime_ns) for entry in Path(folder).iterdir()}
    except OSError:
        return {}


def real_home_state():
    folders = (".local/bin", ".local/share/uv/tools", ".local/share/uv/python", ".local/share/cdlbib",
               ".cargo/bin", ".config/uv", ".config/fish/conf.d", "Library/Application Support/cdlbib")
    profiles = (".zshrc", ".zshenv", ".zprofile", ".profile", ".bashrc", ".bash_profile", ".bash_login")
    state = {name: listing(REAL_HOME / name) for name in folders}
    for name in profiles:
        path = REAL_HOME / name
        state[name] = (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None
    return state


@pytest.fixture(autouse=True)
def nothing_of_the_users_touched():
    before = real_home_state()
    yield
    after = real_home_state()
    changed = [name for name in before if before[name] != after[name]]
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
        env = {"HOME": str(self.home), "PATH": str(self.programs), "TMPDIR": str(self.tmp), "SHELL": "/bin/zsh",
               "LANG": "en_US.UTF-8", "UV_CACHE_DIR": str(self.caches / "uv"),
               "UV_PYTHON_CACHE_DIR": str(self.caches / "uv-python"), "PIP_CACHE_DIR": str(self.caches / "pip")}
        env.update(more)
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
                       (("--extras", "tui; rm -rf x"), "--extras takes names separated by commas"),
                       (("--ref", "a b"), "--ref takes a branch, tag or commit name"),
                       (("--repo", "http://example.org/x"), "--repo takes the https address"),
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
    assert "no Python 3.11 or later was found on PATH." in out.stderr
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
               line.endswith("/uv-install.sh' https://astral.sh/uv/install.sh") for line in lines), out.stdout
    assert any(line.startswith(f"+ '{box.programs}/env' 'UV_UNMANAGED_INSTALL={own_uv}' '{box.programs}/sh' ")
               for line in lines), out.stdout
    assert (f"+ '{own_uv}/uv' --no-config tool install --python '>=3.11' --with pip --force "
            f"--reinstall-package cdlbib '{box.checkout}[tui]'") in lines, out.stdout
    assert lines[-1] == "Nothing was installed. Run the script without --ask, or in a terminal, to install."
    assert box.files() == set() and box.leftovers() == []


@need_uv
def test_ask_without_a_terminal_and_uv_present_prints_the_one_command(box):
    out = box.with_uv().run("--ask")
    assert out.returncode == 1, out.stdout + out.stderr
    assert (f"+ '{box.programs}/uv' --no-config tool install --python '>=3.11' --with pip --force "
            f"--reinstall-package cdlbib '{box.checkout}'") in out.stdout.splitlines()
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
    assert "No Python 3.11 or later was found: uv downloads one into its own folder" in out
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
def test_running_again_changes_nothing_but_the_package_and_downloads_no_second_python(box, online):
    box.with_uv().with_old_python()
    ok(box.run())
    files, pythons = box.files(), listing(box.pythons)
    for _ in range(2):
        again = ok(box.run())
        assert "Installed: cdlbib 2.0.0" in again and box.installed() == "cdlbib 2.0.0"
        assert "No Python 3.11 or later was found" not in again
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
    out = ok(box.run(shell=shell))
    own_uv = box.data / "uv" / "uv"
    assert (f"uv was not found: downloading uv with its installer (https://astral.sh/uv/install.sh, saved to a "
            f"temporary file and run with sh) into {box.data / 'uv'}; no shell profile is changed.") in out
    assert "No Python 3.11 or later was found: uv downloads one into its own folder" in out
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"
    assert own_uv.is_file() and not (box.bin / "uv").exists() and not (box.home / ".cargo").exists()
    assert not (box.home / ".config").exists(), "uv's installer wrote a receipt or a profile"
    assert not [name for name in os.listdir(box.home) if not name.startswith(".local") and name != ".cache"]
    assert box.leftovers() == []
    files, uv_before, pythons = box.files(), own_uv.stat().st_mtime_ns, listing(box.pythons)

    again = ok(box.run(shell=shell))
    assert "downloading uv" not in again and "astral.sh" not in again and "No Python 3.11" not in again
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
    assert subprocess.run([str(program), "--version"], capture_output=True, text=True).stdout.startswith("uv 0.4.0")
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
    assert f"{box.programs}/uv is older than uv 0.5.0 and is left as it is: downloading uv with its installer" in out
    assert "Installed: cdlbib 2.0.0" in out and box.installed() == "cdlbib 2.0.0"
    assert os.path.getsize(program) == size
    assert subprocess.run([program, "--version"], capture_output=True, text=True).stdout.startswith("uv 0.4.0")
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
    assert f"+ '{box.programs}/uv' --no-config tool install" in out.stdout
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
        assert f"+ '{box.programs}/uv' --no-config tool install" in out.stdout
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
        assert (f"+ '{box.programs}/uv' --no-config tool install --python '>=3.11' --with pip --force "
                "--reinstall-package cdlbib 'cdlbib @ git+https://github.com/ContextLab/CDL-bibliography'"
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
    assert "downloading uv with its installer" in out.stdout and "Installed: cdlbib " in out.stdout
    assert box.installed().startswith("cdlbib ") and box.installed() != "cdlbib 6.6.6"
    nothing_ran(folder)
