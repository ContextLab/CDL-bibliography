"""Who is acting: the GitHub login of the gh CLI. The only source of a reviewer's name."""
from dataclasses import dataclass
import json
import re
import shutil
import subprocess
import time

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


# What gh prints when GitHub could not be asked at all, or answered that it is busy: nothing
# about who is logged in. Seen on 2026-10-06: one `gh api user` among several hundred in a
# test run failed, although the user was logged in the second before and after.
_NOT_AN_ANSWER = re.compile(
    r"error connecting|could not resolve|dial tcp|connection (?:refused|reset)|timeout|timed out|\bEOF\b|"
    r"TLS handshake|rate limit|HTTP (?:429|5\d\d)", re.IGNORECASE)
PAUSES = (2, 5)        # seconds before the second and the third request


def _ask(timeout):
    try:
        return subprocess.run(["gh", "api", "user"], capture_output=True, text=True, timeout=timeout, env=git_env())
    except (OSError, subprocess.SubprocessError) as exc:
        raise IdentityUnavailable(f"Could not ask gh who is logged in ({type(exc).__name__}). {HOW}") from exc


def current(timeout=60):
    """The logged-in GitHub user. ``timeout``: the seconds gh is given to answer.

    When gh says that GitHub could not be reached, or that it is busy, the request is made
    again (three in all); if none is answered the refusal says so, and does not say that
    nobody is logged in."""
    if not shutil.which("gh"):
        raise IdentityUnavailable(f"The GitHub CLI (gh) was not found. {HOW}")
    run = _ask(timeout)
    for pause in PAUSES:
        if run.returncode == 0 or not _NOT_AN_ANSWER.search(run.stderr or ""):
            break
        time.sleep(pause)
        run = _ask(timeout)
    if run.returncode != 0:
        if _NOT_AN_ANSWER.search(run.stderr or ""):
            raise IdentityUnavailable(
                f"GitHub did not answer who is logged in ({len(PAUSES) + 1} requests through gh failed: connection "
                "or rate limit). Nothing was recorded; try again in a few minutes.")
        raise IdentityUnavailable(f"No GitHub user is logged in. {HOW}")
    try:
        data = json.loads(run.stdout)
        return Identity(login=str(data["login"]), id=int(data["id"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise IdentityUnavailable(f"gh returned no user. {HOW}") from exc
