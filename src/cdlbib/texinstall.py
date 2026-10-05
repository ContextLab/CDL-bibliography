"""The TeX programs a .bbl needs beyond LaTeX itself (biber, bibtex): which version is
installed, and how a missing one gets installed on this computer.

plan() only looks (PATH, the folders of the TeX installation, the package manager beside it);
install() runs the one command plan() names. That command is the TeX installation's own
package manager, run as the current user: `tlmgr install` in a TeX Live folder this user can
write to, `brew install` beside a Homebrew TeX Live. Nothing here runs sudo; where the
installation needs an administrator (MacTeX, a distribution's packages) or has no package
manager that can be run (MiKTeX is not driven from here), the plan carries the command for
a person to run instead."""
import functools
import os
import re
import shutil
import subprocess
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


@dataclass
class Plan:
    """How ``program`` gets installed here. ``distribution``: "texlive" (a TeX Live folder with
    its tlmgr), "homebrew", "miktex", "system" (a distribution's packages), "unknown", or
    "none" (no TeX found). ``command`` is the argument list install() runs, and is empty when
    nothing can be run from here; ``manual`` is then the sentence naming the command for a
    person, and ``why`` the reason it is not run."""
    program: str
    distribution: str
    command: list = field(default_factory=list)
    manual: str = ""
    why: str = ""

    @property
    def shown(self):
        """The command as a person would type it."""
        return " ".join(Path(self.command[0]).name if n == 0 else part for n, part in enumerate(self.command))


def _out(command):
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=QUICK, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _restricted(config):
    """Does this tlmgr configuration (TEXMFSYSCONFIG/tlmgr/config) list the allowed actions
    without "install" (Homebrew's TeX Live does; tlmgr then refuses the action)."""
    try:
        lines = Path(config).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in lines:
        name, _, value = line.partition("=")
        if name.strip() == "allowed-actions":
            return "install" not in [action.strip() for action in value.split(",")]
    return False


def plan(program):
    """The Plan for ``program``, from what is on PATH now. Reads only."""
    anchor = shutil.which("kpsewhich") or shutil.which("pdflatex")
    if not anchor:
        return Plan(program, "none", manual=NO_TEX, why="no TeX installation was found on PATH")
    real = Path(anchor).resolve()
    name = TEXLIVE.get(program)

    if shutil.which("miktex") or shutil.which("initexmf") or "miktex" in str(real).lower():
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
        brew = shutil.which("brew")
        if not brew or Path(brew).parent.parent != cellar.parent:
            return Plan(program, "homebrew", manual=said, why=f"the brew of {cellar.parent} was not found on PATH")
        if not os.access(cellar, os.W_OK):
            return Plan(program, "homebrew", manual=said, why=f"{cellar} is not writable by this user")
        return Plan(program, "homebrew", command=[brew, "install", "biber"], manual=said)

    if real.parent in (Path("/usr/bin"), Path("/bin")):         # a distribution's own packages: they need root
        for manager, packages in SYSTEM.items():
            if shutil.which(manager) and program in packages:
                return Plan(program, "system", manual="Run: " + SYSTEM_COMMAND[manager].format(packages[program]),
                            why="the system's packages need an administrator, and sudo is never run from here")

    tlmgr = real.parent / "tlmgr"
    root = _out([anchor, "-var-value", "TEXMFROOT"]).strip()
    if name and root and tlmgr.exists() and (Path(root) / "tlpkg" / "texlive.tlpdb").is_file():
        said = f"tlmgr install {name}"
        config = _out([anchor, "-var-value", "TEXMFSYSCONFIG"]).strip()
        if config and _restricted(Path(config) / "tlmgr" / "config"):
            return Plan(program, "texlive", why="this TeX Live's tlmgr is set up not to install packages",
                        manual=f"Install {program} with the package manager this TeX Live came from.")
        locked = [str(place) for place in (Path(root) / "tlpkg", Path(root) / "tlpkg" / "texlive.tlpdb", real.parent)
                  if not os.access(place, os.W_OK)]
        if locked:
            return Plan(program, "texlive", manual=f"Run: sudo {said}",
                        why=f"{locked[0]} is not writable by this user, and sudo is never run from here")
        return Plan(program, "texlive", command=[str(tlmgr), "install", name], manual=f"Run: {said}")
    return Plan(program, "unknown", why="the TeX installation has no package manager that is known here",
                manual=f"Install {program} with the package manager this TeX installation came from"
                       + (f" (in TeX Live: tlmgr install {name})." if name else "."))


def how(program):
    """One sentence for a person: what installs ``program`` here, and why it is not done for them."""
    found = plan(program)
    if found.command:
        return f"Run: {found.shown} (cdlbib export --bbl does this when the program is needed)"
    return found.manual + (f" ({found.why})" if found.why and found.distribution != "none" else "")


def install(program):
    """Run the plan's command and return the program's path. CdlbibError when there is no
    command to run, when it fails, or when the program is still not on PATH afterwards."""
    found = plan(program)
    if not found.command:
        raise CdlbibError(f"{program} cannot be installed from here: {found.why}. {found.manual}")
    try:
        run = subprocess.run(found.command, capture_output=True, text=True, timeout=LONG, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise CdlbibError(f"install failed ({found.shown}): it did not finish within {LONG} seconds.") from None
    except OSError as exc:
        raise CdlbibError(f"install failed ({found.shown}): {exc}") from exc
    said = (run.stdout.strip() + "\n" + run.stderr.strip()).strip()[-2000:]
    if run.returncode != 0:
        raise CdlbibError(f"install failed ({found.shown}):\n{said}")
    path = shutil.which(program)
    if not path:
        raise CdlbibError(f"{found.shown} finished, but {program} is still not on PATH:\n{said}")
    version.cache_clear()
    return path


@functools.lru_cache(maxsize=None)
def _version(path, stamp):
    text = _out([path, "--version"])
    found = re.search(r"(?:version:?\s*|\s)(\d+\.\d+[\w.]*)", text.splitlines()[0]) if text.strip() else None
    return found.group(1) if found else ""


def version(program):
    """The version ``program --version`` reports ("2.22"), or "" when it is not installed or
    does not say. Asked once per file as it is now (its path, size and time)."""
    path = shutil.which(program)
    if not path:
        return ""
    try:
        info = os.stat(path)
    except OSError:
        return ""
    return _version(path, (info.st_size, info.st_mtime_ns))


version.cache_clear = _version.cache_clear


def biblatex_version():
    """The version of the biblatex.sty TeX finds ("3.21"), or ""."""
    kpsewhich = shutil.which("kpsewhich")
    path = _out([kpsewhich, "biblatex.sty"]).strip() if kpsewhich else ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")[:20000] if path else ""
    except OSError:
        return ""
    found = re.search(r"\\def\\abx@version\{([^}]+)\}", text)
    return found.group(1) if found else ""


def versions_line():
    """What is installed, for a setup report: "biber 2.22, biblatex 3.21", or what there is of it."""
    parts = [f"{name} {value}" for name, value in (("biber", version("biber")), ("biblatex", biblatex_version())) if value]
    return ", ".join(parts)
