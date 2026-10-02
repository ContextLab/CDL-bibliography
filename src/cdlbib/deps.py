"""Install an optional extra on demand. Core code never prompts and never installs: it
raises MissingDependency. A front end asks the user, then calls install() once."""
import importlib
import shutil
import subprocess
import sys

from .errors import CdlbibError, MissingDependency

_assume_yes = False  # the front end's --yes; the only place it is kept


def set_assume_yes(value):
    """Record the front end's --yes (install without asking)."""
    global _assume_yes
    _assume_yes = bool(value)


def assume_yes():
    return _assume_yes


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


def install(extra, python=sys.executable, requirement=None):
    """Install cdlbib[extra] (or `requirement`, for tests) into python's environment.
    Version ranges come only from pyproject.toml, through the extra."""
    target = requirement or f"cdlbib[{extra}]"
    command = installer(python)
    if not command:
        raise CdlbibError(f"No installer found for this environment. Install by hand: pip install 'cdlbib[{extra}]'")
    run = subprocess.run([*command, target], capture_output=True, text=True)
    if run.returncode != 0:
        raise CdlbibError(f"install failed ({' '.join(command)} {target}):\n{run.stderr.strip()[-2000:]}")
    importlib.invalidate_caches()
