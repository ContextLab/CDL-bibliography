"""Who is acting: the GitHub login of the gh CLI. The only source of a reviewer's name."""
from dataclasses import dataclass
import json
import shutil
import subprocess

from .errors import IdentityUnavailable
from .gitenv import git_env

HOW = "Install the GitHub CLI (https://cli.github.com) and run: gh auth login"


@dataclass(frozen=True)
class Identity:
    login: str
    id: int

    @property
    def handle(self):
        return "@" + self.login


def current(timeout=60):
    """The logged-in GitHub user. ``timeout``: the seconds gh is given to answer."""
    if not shutil.which("gh"):
        raise IdentityUnavailable(f"The GitHub CLI (gh) was not found. {HOW}")
    try:
        run = subprocess.run(["gh", "api", "user"], capture_output=True, text=True, timeout=timeout, env=git_env())
    except (OSError, subprocess.SubprocessError) as exc:
        raise IdentityUnavailable(f"Could not ask gh who is logged in ({type(exc).__name__}). {HOW}") from exc
    if run.returncode != 0:
        raise IdentityUnavailable(f"No GitHub user is logged in. {HOW}")
    try:
        data = json.loads(run.stdout)
        return Identity(login=str(data["login"]), id=int(data["id"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise IdentityUnavailable(f"gh returned no user. {HOW}") from exc
