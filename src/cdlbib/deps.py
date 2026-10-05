"""Install an optional extra on demand. Core code never prompts and never installs: it
raises MissingDependency. A front end tells the user (or asks, with --ask), then calls install() once."""
import importlib
import importlib.metadata
import re
import shutil
import subprocess
import sys

from .errors import CdlbibError, MissingDependency

_ask = False  # the front end's --ask; the only place it is kept


def set_ask(value):
    """Record the front end's --ask (ask before installing; the default is to install)."""
    global _ask
    _ask = bool(value)


def ask():
    return _ask


def need(module, extra, feature):
    """The imported optional module, or MissingDependency naming the extra that provides it."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise MissingDependency(module, extra, feature) from exc


def installer(python=sys.executable):
    """The command prefix that installs into python's environment (pip, else uv); [] if neither."""
    if subprocess.run([python, "-m", "pip", "--version"], capture_output=True).returncode == 0:
        return [python, "-m", "pip", "install"]
    if shutil.which("uv"):
        return ["uv", "pip", "install", "--python", python]
    return []


def requirements_for(extra, package=None):
    """The requirement strings the installed cdlbib's metadata lists for `extra`, marker
    removed (e.g. ['pypdf<7,>=6.0']). The metadata is generated from pyproject.toml, so
    version ranges have one source and the install never asks an index for cdlbib itself."""
    hand = f" Install by hand: pip install '{package}'" if package else ""
    try:
        listed = importlib.metadata.requires("cdlbib")
    except importlib.metadata.PackageNotFoundError:
        raise CdlbibError("cdlbib is not installed as a package, so its optional requirements are unknown." + hand)
    found = []
    clause = re.compile(r"""\s*(?:and\s+)?extra\s*==\s*(["'])(.+?)\1\s*(?:and\s+)?""")
    for line in listed or []:
        requirement, _, marker = line.partition(";")
        names = [m.group(2) for m in clause.finditer(marker)]
        if extra in [n.replace("_", "-").lower() for n in names] + names:
            rest = clause.sub(" ", marker).strip()
            found.append(requirement.strip() + (f"; {rest}" if rest else ""))
    if not found:
        raise CdlbibError(f"cdlbib lists no requirements for the extra '{extra}'." + hand)
    return found


def manual_command(extra, package=None):
    """The one text that tells a person what to install by hand."""
    try:
        wanted = requirements_for(extra)
    except CdlbibError:
        wanted = [package] if package else [f"cdlbib[{extra}]"]
    return "pip install " + " ".join(f"'{w}'" for w in wanted)


def install(extra, python=sys.executable, requirement=None, package=None):
    """Install what cdlbib's metadata lists for `extra` (or `requirement`, for tests) into
    python's environment. A TeX program (``extra`` "tex": errors.MissingProgram) is installed
    by the TeX installation's own package manager instead (texinstall.install)."""
    if extra == "tex" and not requirement:
        from . import texinstall
        texinstall.install(package)
        return
    targets = [requirement] if requirement else requirements_for(extra, package)
    command = installer(python)
    if not command:
        raise CdlbibError(f"No installer found for this environment. Install by hand: {manual_command(extra, package)}")
    run = subprocess.run([*command, *targets], capture_output=True, text=True)
    if run.returncode != 0:
        raise CdlbibError(f"install failed ({' '.join([*command, *targets])}):\n{run.stderr.strip()[-2000:]}")
    importlib.invalidate_caches()
