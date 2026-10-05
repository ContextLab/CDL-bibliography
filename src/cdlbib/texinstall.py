"""The TeX programs a .bbl needs beyond LaTeX itself (biber, bibtex): which version is
installed, and how a missing one gets installed on this computer.

plan() only looks (PATH, the folders of the TeX installation, the package manager beside it);
install() runs the one command plan() names. That command is the TeX installation's own
package manager, run as the current user: `tlmgr install` in a TeX Live folder this user can
write to, `brew install` beside a Homebrew TeX Live (always asked about first: Plan.confirm). Nothing here runs sudo; where the
installation needs an administrator (MacTeX, a distribution's packages) or has no package
manager that can be run (MiKTeX is not driven from here), the plan carries the command for
a person to run instead.

What is run, and how:
- The package manager is never looked up on PATH. It is the tlmgr in the folder that holds
  the kpsewhich in use (links followed), or the brew of the Homebrew prefix whose Cellar
  holds that kpsewhich. A TeX found through a folder of PATH that is not an absolute path
  (".", an empty component) gives no command at all.
- Every program runs in an empty folder of its own, with standard input closed, and with
  environment() as its whole environment: its PATH is the program's own folder and the
  system's folders, not the user's PATH.
- One time limit covers a program's exit and the end of its output; the program and all it
  started are ended when the limit passes, and on every other way out of the call.
- Of what a program prints, at most MAX_OUTPUT bytes are kept; of a file, at most MAX_FILE
  bytes are read, and only from a regular file.
- Text from a program or a file that is shown to a person passes shown(): printable
  characters only, of a bounded length. A version is digits and dots, or it is not reported."""
import functools
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CdlbibError

EXTRA = "tex"                    # the MissingDependency.extra of a TeX program (errors.MissingProgram)
# program -> the TeX Live package that holds it (`tlmgr install NAME`).
TEXLIVE = {"biber": "biber", "bibtex": "bibtex"}
# program -> the package of a system's own package manager; a program not listed has no command named.
SYSTEM = {"apt-get": {"biber": "biber", "bibtex": "texlive-binaries"},
          "dnf": {"biber": "biber", "bibtex": "texlive-bibtex"},
          "pacman": {"biber": "biber"}}
SYSTEM_COMMAND = {"apt-get": "sudo apt-get install {}", "dnf": "sudo dnf install {}", "pacman": "sudo pacman -S {}"}
NO_TEX = "Install TeX Live (https://tug.org/texlive/) or, on macOS, MacTeX (https://tug.org/mactex/)."
ALLOWLIST_BIBER = "2.22"         # the biber whose schema export.BCF_SHAPE was derived from
QUICK, LONG = 30, 1800           # seconds: a version or a variable; an installation
MAX_OUTPUT = 64_000              # bytes kept of what one program prints
MAX_FILE = 200_000               # bytes read of one file
MAX_SHOWN = 2000                 # characters of a program's output shown to a person
MAX_PATH = 1024                  # characters of a path a program names
_VERSION = re.compile(r"(?<![\w.])(\d{1,4}(?:\.\d{1,4}){1,3})(?![.\d])")
# All a program run here gets of the user's environment: where programs are, where the user's
# files are (a package manager keeps its cache there), the locale, and the proxy for a download.
KEPT = ("HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "http_proxy", "https_proxy", "ftp_proxy", "no_proxy",
        "HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "NO_PROXY")
# Where a program run here finds an interpreter or a helper, after its own folder: the system's
# folders only. The user's PATH is not passed on.
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
# What `brew install` is told every time: no update of Homebrew itself, no cleanup of other
# formulae, no upgrade or reinstallation of the formulae that depend on this one, no hints.
BREW_QUIET = ("HOMEBREW_NO_AUTO_UPDATE", "HOMEBREW_NO_INSTALL_CLEANUP", "HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK",
              "HOMEBREW_NO_ENV_HINTS")
BREW_KEPT = ("HOMEBREW_NO_ANALYTICS", "HOMEBREW_NO_INSTALL_UPGRADE")      # the user's own, passed on as "1" when set


@dataclass
class Plan:
    """How ``program`` gets installed here. ``distribution``: "texlive" (a TeX Live folder with
    its tlmgr), "homebrew", "miktex", "system" (a distribution's packages), "unknown", or
    "none" (no TeX found). ``command`` is the argument list install() runs (its first item an
    absolute path), and is empty when nothing can be run from here; ``manual`` is then the
    sentence naming the command for a person, and ``why`` the reason it is not run.
    ``confirm``: the command is run only after a person said yes, with or without --ask."""
    program: str
    distribution: str
    command: list = field(default_factory=list)
    manual: str = ""
    why: str = ""
    confirm: bool = False        # the command changes software outside the TeX installation (brew): always asked first

    @property
    def shown(self):
        """The command as a person would type it."""
        return " ".join(Path(part).name if n == 0 else part for n, part in enumerate(self.command))


def shown(text, limit=MAX_SHOWN, lines=True):
    """``text`` as it may be shown to a person: printable characters only (a line break is
    kept when ``lines``; an escape sequence loses its escape character and so does nothing
    to a terminal), and the last ``limit`` characters at most."""
    kept = "".join(char if char.isprintable() or (lines and char == "\n") else " " if char in "\t\r\n" else ""
                   for char in str(text))
    return kept.strip()[-limit:]


def environment(command=()):
    """The whole environment of ``command``, a program run here: KEPT from the user's, and a
    PATH made here, not taken from the user's: the folder of the program (as it was named,
    and the one it really lies in when that is a link) and SYSTEM_PATH. An interpreter or a
    helper the program looks up by name (`#!/usr/bin/env perl`, curl, git) is therefore the
    one of its own installation or of the system, never one in a folder the user's PATH
    happens to hold. No TEXMFCNF, PERL5LIB, BIBER_* or the like reaches it.

    brew is also told not to update Homebrew, not to clean up and not to upgrade what depends
    on the formula (BREW_QUIET), and the user's own opt-outs of that kind (BREW_KEPT) stay."""
    env = {name: os.environ[name] for name in KEPT if os.environ.get(name)}
    folders = []
    if command:
        named = Path(command[0])
        folders = [str(named.parent), str(named.resolve().parent)]
        if named.name == "brew":
            env.update({name: "1" for name in BREW_KEPT if os.environ.get(name)})
            env.update({name: "1" for name in BREW_QUIET})
    env["PATH"] = os.pathsep.join(dict.fromkeys(folders + list(SYSTEM_PATH)))
    return env


def _run(command, timeout=QUICK, keep="head", limit=MAX_OUTPUT):
    """(exit status, what the program printed) of ``command``, an argument list whose first
    item is an absolute path; (None, why) when it could not be run or did not finish in
    ``timeout`` seconds. Of the output (stdout and stderr together) only the first, or with
    ``keep`` "tail" the last, ``limit`` bytes are held; the rest is read and dropped.

    ``timeout`` is one limit for all of it: the program's exit and the end of its output (a
    child it left behind that still holds the output open counts as not finished). However
    this returns or is left (the limit, an interruption, an error), every program of the
    group that was started is ended first."""
    if not os.path.isabs(command[0]):
        return None, f"{command[0]} is not an absolute path"
    held = bytearray()

    def read(descriptor):
        while True:
            try:
                chunk = os.read(descriptor, 8192)
            except OSError:
                return
            if not chunk:
                return
            if keep == "tail":
                held.extend(chunk)
                del held[:-limit]
            elif len(held) < limit:
                held.extend(chunk[:limit - len(held)])

    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix="cdlbib-tex-") as empty:
        try:
            process = subprocess.Popen(command, cwd=empty, env=environment(command), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, bufsize=0)
        except OSError as exc:
            return None, shown(exc, lines=False)
        reader = threading.Thread(target=read, args=(process.stdout.fileno(),), name="cdlbib-tex-output", daemon=True)
        status = None
        try:
            reader.start()
            try:
                status = process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                status = None
            if status is not None:
                reader.join(max(0.0, deadline - time.monotonic()))
                if reader.is_alive():                          # the output is still held open by something it started
                    status = None
        finally:
            _stop(process)                                     # on every way out: nothing that was started stays
            reader.join(5)
            if not reader.is_alive():                          # a reader still reading is left to end; closing would wait for it
                process.stdout.close()
    text = bytes(held).decode("utf-8", errors="replace")
    return (status, text) if status is not None else (None, f"it did not finish within {timeout} seconds")


def _stop(process):
    """End the program and whatever it started (its process group), finished or not."""
    import signal
    try:
        os.killpg(process.pid, signal.SIGKILL)                # the group is the program's own (start_new_session)
    except (OSError, AttributeError):
        pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _out(command):
    status, text = _run(command)
    return text if status == 0 else ""


def _path(text):
    """The one absolute path a program printed, or None (nothing, several lines, too long,
    not absolute, or with a character that is not printable)."""
    value = text.strip()
    if not value or len(value) > MAX_PATH or not value.isprintable() or not os.path.isabs(value):
        return None
    return Path(value)


def read(path, limit=MAX_FILE):
    """The first ``limit`` bytes of a regular file as text; "" for anything else."""
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            return ""
        with open(path, "rb") as file:
            return file.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _restricted(config):
    """Does this tlmgr configuration (TEXMFSYSCONFIG/tlmgr/config) list the allowed actions
    without "install" (Homebrew's TeX Live does; tlmgr then refuses the action)."""
    for line in read(config).splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "allowed-actions":
            return "install" not in [action.strip() for action in value.split(",")]
    return False


def which(program):
    """shutil.which, when what it finds is an absolute path; None for a program found through
    a folder of PATH that is relative to wherever the command was started."""
    found = shutil.which(program)
    return found if found and os.path.isabs(found) else None


def plan(program):
    """The Plan for ``program``, from what is on PATH now. Reads only."""
    anchor = which("kpsewhich") or which("pdflatex")
    if not anchor:
        relative = shutil.which("kpsewhich") or shutil.which("pdflatex")
        return Plan(program, "none", manual=NO_TEX, why="TeX is found only through a folder of PATH that is not an "
                    "absolute path, and nothing is run from such a folder" if relative else "no TeX installation was found on PATH")
    real = Path(anchor).resolve()
    name = TEXLIVE.get(program)

    if which("miktex") or which("initexmf") or "miktex" in str(real).lower():
        package = f"{program}-windows-x64" if os.name == "nt" and program == "biber" else None
        return Plan(program, "miktex", why="MiKTeX's package manager is not run from here",
                    manual=(f"Run: miktex packages install {package}" if package else
                            f"Install the MiKTeX package that holds {program} with MiKTeX Console."))

    if "Cellar" in real.parts:                                 # Homebrew: <prefix>/Cellar/texlive/<version>/bin/kpsewhich
        cellar = Path(*real.parts[:real.parts.index("Cellar") + 1])
        wanted = ["brew", "install", "biber"] if program == "biber" else ["brew", "reinstall", "texlive"]
        said = "Run: " + " ".join(wanted)
        if program != "biber":
            return Plan(program, "homebrew", manual=said + f" (Homebrew's texlive holds {program})",
                        why=f"Homebrew's texlive is installed without its {program}")
        brew = cellar.parent / "bin" / "brew"                  # the brew of this prefix, whatever PATH says
        if not (brew.is_file() and os.access(brew, os.X_OK)):
            return Plan(program, "homebrew", manual=said, why=f"{shown(brew, MAX_PATH)} is not there")
        if not os.access(cellar, os.W_OK):
            return Plan(program, "homebrew", manual=said, why=f"{shown(cellar, MAX_PATH)} is not writable by this user")
        return Plan(program, "homebrew", command=[str(brew), "install", "biber"], manual=said, confirm=True)

    if real.parent in (Path("/usr/bin"), Path("/bin")):         # a distribution's own packages: they need root
        for manager, packages in SYSTEM.items():
            if (which(manager) or os.path.exists(f"/usr/bin/{manager}")) and program in packages:
                return Plan(program, "system", manual="Run: " + SYSTEM_COMMAND[manager].format(packages[program]),
                            why="the system's packages need an administrator, and sudo is never run from here")

    tlmgr = real.parent / "tlmgr"                               # beside the kpsewhich in use, whatever PATH says
    root = _path(_out([str(real), "-var-value", "TEXMFROOT"]))
    if name and root and tlmgr.is_file() and os.access(tlmgr, os.X_OK) and (root / "tlpkg" / "texlive.tlpdb").is_file():
        said = f"tlmgr install {name}"
        config = _path(_out([str(real), "-var-value", "TEXMFSYSCONFIG"]))
        if config and _restricted(config / "tlmgr" / "config"):
            return Plan(program, "texlive", why="this TeX Live's tlmgr is set up not to install packages",
                        manual=f"Install {program} with the package manager this TeX Live came from.")
        locked = [place for place in (root / "tlpkg", root / "tlpkg" / "texlive.tlpdb", real.parent)
                  if not os.access(place, os.W_OK)]
        if locked:
            return Plan(program, "texlive", manual=f"Run: sudo {said}",
                        why=f"{shown(locked[0], MAX_PATH)} is not writable by this user, and sudo is never run from here")
        return Plan(program, "texlive", command=[str(tlmgr), "install", name], manual=f"Run: {said}")
    return Plan(program, "unknown", why="the TeX installation has no package manager that is known here",
                manual=f"Install {program} with the package manager this TeX installation came from"
                       + (f" (in TeX Live: tlmgr install {name})." if name else "."))


def how(program):
    """One sentence for a person: what installs ``program`` here, and why it is not done for them."""
    found = plan(program)
    if found.command:
        return (f"Run: {found.shown} (cdlbib export --bbl " + ("asks, then does this," if found.confirm else "does this")
                + " when the program is needed)")
    return found.manual + (f" ({found.why})" if found.why and found.distribution != "none" else "")


def install(program):
    """Run the plan's command and return the program's path. CdlbibError when there is no
    command to run, when it fails, or when the program is still not on PATH afterwards."""
    found = plan(program)
    if not found.command:
        raise CdlbibError(f"{program} cannot be installed from here: {found.why}. {found.manual}")
    status, text = _run(found.command, timeout=LONG, keep="tail")
    if status is None:
        raise CdlbibError(f"install failed ({found.shown}): {shown(text)}")
    if status != 0:
        raise CdlbibError(f"install failed ({found.shown}):\n{shown(text)}")
    path = which(program)
    if not path:
        raise CdlbibError(f"{found.shown} finished, but {program} is still not on PATH:\n{shown(text)}")
    _version.cache_clear()
    return path


@functools.lru_cache(maxsize=None)
def _version(path, stamp):
    lines = _out([path, "--version"]).splitlines()
    found = _VERSION.search(lines[0][:200]) if lines else None
    return found.group(1) if found else ""


def version(program):
    """The version ``program --version`` reports, as digits and dots ("2.22"; of "0.99d" the
    "0.99"), or "" when the program is not installed or reports none. Asked once per file as
    it is now (its path, size and time)."""
    path = which(program)
    if not path:
        return ""
    try:
        info = os.stat(path)
    except OSError:
        return ""
    return _version(path, (info.st_size, info.st_mtime_ns))


version.cache_clear = _version.cache_clear


def biblatex_version():
    """The version of the biblatex.sty TeX finds, as digits and dots ("3.21"), or ""."""
    kpsewhich = which("kpsewhich")
    path = _path(_out([kpsewhich, "biblatex.sty"])) if kpsewhich else None
    found = re.search(r"\\def\\abx@version\{(\d{1,4}(?:\.\d{1,4}){1,3})[a-z]?\}", read(path)) if path else None
    return found.group(1) if found else ""


def versions_line():
    """What is installed, for a setup report: "biber 2.22, biblatex 3.21", or what there is of it."""
    parts = [f"{name} {value}" for name, value in (("biber", version("biber")), ("biblatex", biblatex_version())) if value]
    return ", ".join(parts)
