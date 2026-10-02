"""Send a change: the user's fork, a branch, a pull request. One route for everyone."""
import json
import os
import re
import subprocess

from .errors import PublishRefused

ALLOWED = ("cdl.bib", "verification/")
WORK = ".bibcheck/"                      # the tool's local working folder: never sent, never reported
PROTECTED_UPSTREAM = "ContextLab/CDL-bibliography"
NO_CHANGES = "There are no changes to cdl.bib or verification/ to send."
# The forms git uses for a GitHub repository, github.com only: https:// and http:// (with an
# optional user@), git@github.com:O/N, ssh://git@github.com[:port]/O/N, git://github.com/O/N.
GITHUB_URL = re.compile(r"^(?:https?://(?:[^@/\s]+@)?github\.com/|ssh://git@github\.com(?::\d+)?/|git@github\.com:"
                        r"|git://github\.com/)([^/\s:]+)/([^/\s]+?)(?:\.git)?/?$")
# The two push failures that are recognised; any other wording gets no hint.
NO_SIGN_IN = re.compile(r"terminal prompts disabled|Authentication failed", re.IGNORECASE)
NO_PERMISSION = re.compile(r"Permission to \S+ denied", re.IGNORECASE)


def _run(args, cwd=None, check=True):
    try:                                 # git never stops to ask for a password: the api does not prompt
        run = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except OSError as exc:               # git or gh is not installed
        raise PublishRefused(f"`{args[0]}` could not be run ({type(exc).__name__}: {exc})") from exc
    if check and run.returncode != 0:
        raise PublishRefused(f"`{' '.join(args[:3])} …` failed:\n{(run.stderr or run.stdout).strip()[-2000:]}")
    return run


def _github(path, jq=None):
    """A GitHub API GET through gh: the parsed answer (the jq output's lines, with ``jq``),
    or None when GitHub says 404. Any other failure is 'GitHub could not be reached': a
    failed call is never read as 'there is no such repository'."""
    run = _run(["gh", "api", path, *(["--paginate", "--jq", jq] if jq else [])], check=False)
    if run.returncode == 0:
        return run.stdout.split() if jq else json.loads(run.stdout)
    if "HTTP 404" in run.stderr:
        return None
    raise PublishRefused(f"GitHub could not be reached (gh api {path}):\n{(run.stderr or run.stdout).strip()[-2000:]}")


def upstream_of(ws):
    """'OWNER/NAME' of the GitHub repository the checkout's origin points to. It is the
    upstream unless it is itself a fork (see resolve)."""
    url = _run(["git", "remote", "get-url", "origin"], cwd=ws.root).stdout.strip()
    match = GITHUB_URL.match(url)
    if not match:
        raise PublishRefused(f"The checkout's origin is not a GitHub repository: {url}")
    return f"{match.group(1)}/{match.group(2)}"


def is_fork(repository):
    data = _github(f"repos/{repository}")
    if data is None:
        raise PublishRefused(f"GitHub has no repository {repository} (or it is not visible to you).")
    return bool(data.get("fork"))


def is_own_fork(repository, login):
    """Does GitHub say ``repository`` is a fork owned by ``login``?"""
    data = _github(f"repos/{repository}")
    return bool(data and data.get("fork") and data["owner"]["login"].lower() == login.lower())


def resolve(ws, login):
    """(upstream, fork) for a checkout: where pull requests go, and the user's fork of it
    ('login/NAME') or None. A checkout cloned from a fork sends to the fork's parent; when
    that fork is the user's own, it is the fork (nothing is looked up or created)."""
    origin = upstream_of(ws)
    data = _github(f"repos/{origin}")
    if data is None:
        raise PublishRefused(f"GitHub has no repository {origin} (or it is not visible to you).")
    if not data.get("fork"):
        return data["full_name"], find_fork(data["full_name"], login)
    upstream = data["parent"]["full_name"]
    if data["owner"]["login"].lower() == login.lower():
        return upstream, data["full_name"]
    return upstream, find_fork(upstream, login)


def find_fork(upstream, login):
    """The fork of ``upstream`` owned by ``login`` ('login/NAME'), or None. Read-only."""
    name = upstream.split("/", 1)[1]
    data = _github(f"repos/{login}/{name}")
    if data and data.get("fork") and (data.get("parent") or {}).get("full_name", "").lower() == upstream.lower():
        return data["full_name"]
    # A fork may have been renamed: ask the upstream for forks owned by this login.
    names = _github(f"repos/{upstream}/forks", jq=f'.[] | select(.owner.login == "{login}") | .full_name')
    if names is None:
        raise PublishRefused(f"GitHub has no repository {upstream} (or it is not visible to you).")
    return names[0] if names else None


def create_fork(upstream):
    """Fork ``upstream`` into the logged-in user's account. Called only after the user agreed."""
    if is_fork(upstream):
        raise PublishRefused(f"{upstream} is itself a fork; a fork of a fork is never created.")
    _run(["gh", "repo", "fork", upstream, "--clone=false"])
    login = _run(["gh", "api", "user", "--jq", ".login"]).stdout.strip()
    fork = find_fork(upstream, login)
    if not fork:
        raise PublishRefused(f"gh reported success, but no fork of {upstream} is visible for @{login} yet; try again shortly")
    return fork


def branch_prefix(login):
    return f"cdlbib/{login}/"


def branch_name(login, summary, today):
    slug = re.sub(r"[^a-z0-9]+", "-", (summary or "").lower()).strip("-")[:50].strip("-") or "update"
    return f"{branch_prefix(login)}{today.isoformat()}-{slug}"


def current_branch(ws):
    """The branch the checkout is on; 'HEAD' when it is on none (detached)."""
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ws.root).stdout.strip()


def require_branch(ws, main=None):
    """The branch the checkout is on. A checkout on no branch is refused: there would be
    no branch to come back to. ``main`` is the branch to suggest, when the caller knows it."""
    here = current_branch(ws)
    if here == "HEAD":
        raise PublishRefused("The checkout is not on a branch (detached HEAD). Nothing was changed. Switch to a "
                             "branch first (your edits are carried along), then run `cdlbib send` again"
                             + (f":\n  git switch {main}" if main else "."))
    return here


def _head(ws, ref="HEAD"):
    return _run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=ws.root, check=False).stdout.strip()


def _changed(ws):
    """Every path git reports as changed or untracked, relative to the checkout; a rename
    or copy contributes both of its paths."""
    out = _run(["git", "status", "--porcelain", "--untracked-files=all", "-z"], cwd=ws.root).stdout
    paths, second = set(), False
    for part in (p for p in out.split("\0") if p):
        if second:                       # the other path of a rename record carries no status
            paths.add(part)
            second = False
            continue
        second = part[0] in "RC" or part[1] in "RC"
        paths.add(part[3:])
    return sorted(paths)


def _allowed(path):
    return path == ALLOWED[0] or path.startswith(ALLOWED[1])


def unrelated_changes(ws):
    """Changed or untracked paths a send leaves alone (for reporting; never a refusal)."""
    return [p for p in _changed(ws) if not _allowed(p) and not p.startswith(WORK)]


def pending(ws):
    """The changed paths a send would commit."""
    return [p for p in _changed(ws) if _allowed(p)]


def require_identity(ws):
    """git must know the author before anything is written: a commit that fails for want
    of a name would leave a half-made branch."""
    for who in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        if _run(["git", "var", who], cwd=ws.root, check=False).returncode != 0:
            raise PublishRefused(
                "git does not know your name and email, so it cannot commit. Nothing was changed. "
                "Set them, then run `cdlbib send` again:\n"
                '  git config --global user.name "Your Name"\n'
                '  git config --global user.email "you@example.org"')


def commit_to_branch(ws, branch, message):
    """Commit the changes to cdl.bib and verification/ on ``branch`` (made from the current
    commit when new) and leave the checkout on it. Returns the commit. Every other changed,
    staged or untracked file is left as it is: only our paths are staged and the commit names
    them. If the commit cannot be made, the checkout is put back on the branch it was on."""
    mine = pending(ws)
    if not mine:
        raise PublishRefused(NO_CHANGES)
    previous = require_branch(ws)
    exists = bool(_head(ws, f"refs/heads/{branch}"))
    listed = _run(["git", "diff", "--cached", "--name-only", "-z", "--", *mine], cwd=ws.root).stdout
    ours = [p for p in mine if p not in set(listed.split("\0"))]     # what this call stages, and may unstage
    tip = None                           # the branch's commit once the checkout is on it
    if previous != branch:               # the first write; git makes it whole or not at all
        try:
            _run(["git", "switch", branch] if exists else ["git", "switch", "-c", branch], cwd=ws.root)
        except PublishRefused as exc:
            raise PublishRefused(
                f"git could not switch to branch {branch}"
                + (", which already exists and differs in files you have changed" if exists else "")
                + ". Nothing was changed. Commit or set aside the files git names below, or send with a different "
                f"--summary (the branch is named after it).\n{exc}") from exc
    try:
        tip = _head(ws)
        _run(["git", "add", "-A", "--", *mine], cwd=ws.root)
        _run(["git", "commit", "-m", message, "--", *mine], cwd=ws.root)
    except PublishRefused as exc:
        raise PublishRefused(f"{_put_back(ws, previous, branch, tip, ours, made=not exists)}\n{exc}") from exc
    return _head(ws)


def _put_back(ws, previous, branch, tip, ours, made):
    """After a failed commit: back to the branch the user was on, the index as it was,
    without a branch made for nothing. Only moves that lose nothing (no reset, no stash, no
    clean, no force). Returns the sentences that say what happened and where the checkout is."""
    if tip is not None and _head(ws) != tip:     # git reported a failure, yet the branch has a new commit
        return (f"The commit step reported a failure, but a commit was made on branch {current_branch(ws)}; "
                "nothing was sent. Run `cdlbib send` again to resume from there."
                + go_back(previous, current_branch(ws)))
    failed = "The commit could not be made, so nothing was committed and nothing was sent."
    if tip is not None and ours:         # the add may have run: take our paths out of the index again
        _run(["git", "restore", "--staged", "--", *ours], cwd=ws.root, check=False)
    if current_branch(ws) != previous:
        _run(["git", "switch", previous], cwd=ws.root, check=False)
    if current_branch(ws) != previous:
        return (f"{failed} The checkout could not be put back: it is on branch {current_branch(ws)}, with your "
                f"changes in place; go back with: git switch {previous}")
    if made and previous != branch and tip is not None and _head(ws, f"refs/heads/{branch}") == tip:
        _run(["git", "branch", "-d", branch], cwd=ws.root, check=False)
    return f"{failed} The checkout is back on branch {previous}, with your changes in place."


def push(ws, remote_url, branch):
    _run(["git", "push", remote_url, f"refs/heads/{branch}:refs/heads/{branch}"], cwd=ws.root)


def deliver(ws, branch, message, remote_url, target=None):
    """Commit what is pending on ``branch``, then push the branch to ``remote_url``. With
    nothing pending, a checkout already on ``branch`` only pushes (a send that is being
    resumed). Returns the committed paths. A failed push says where things stand."""
    previous, files = require_branch(ws), pending(ws)
    if files:
        commit_to_branch(ws, branch, message)
    elif previous != branch:
        raise PublishRefused(NO_CHANGES)
    try:
        push(ws, remote_url, branch)
    except PublishRefused as exc:
        raise PublishRefused(
            f"The change is committed on branch {branch}, but the push to {target or remote_url} failed: nothing was "
            f"sent and no pull request was opened.{push_hint(str(exc), target or remote_url)} Run `cdlbib send` "
            f"again to resume from there.{go_back(previous, branch)}\n{exc}") from exc
    return files


def push_hint(error, target):
    """What to do about a failed push, for the two failures git words recognisably; else ''."""
    if NO_PERMISSION.search(error):
        return (f" The GitHub account git is signed in with lacks permission to push to {target}; check which "
                "account is logged in with `gh auth status`.")
    if NO_SIGN_IN.search(error):
        return " git could not sign in to GitHub: run `gh auth setup-git` (it makes git use gh's login)."
    return ""


def go_back(previous, branch):
    return f" To go back instead: git switch {previous}" if previous != branch else ""


def _pull_requests(upstream, head, base=None):
    """The pull requests into ``upstream`` from ``head`` ('branch' or 'owner:branch'), any state."""
    found = _run(["gh", "pr", "list", "--repo", upstream, "--head", head.split(":")[-1], "--state", "all",
                  *(["--base", base] if base else []), "--json", "url,state,headRepositoryOwner"]).stdout
    owner = head.split(":")[0] if ":" in head else upstream.split("/")[0]
    return [p for p in json.loads(found or "[]")
            if (p.get("headRepositoryOwner") or {}).get("login", "").lower() == owner.lower()]


def earlier_pr(upstream, head):
    """(url, 'merged' | 'closed') of a finished pull request from ``head`` when no open one
    exists; None when one is open or there has never been one."""
    found = _pull_requests(upstream, head)
    if not found or any(p["state"] == "OPEN" for p in found):
        return None
    done = next((p for p in found if p["state"] == "MERGED"), found[0])   # gh lists the newest first
    return done["url"], done["state"].lower()


def open_or_update_pr(upstream, base, head, title, body, retitle=True):
    """The URL of the open pull request from ``head`` ('branch' or 'owner:branch') into
    ``upstream``'s ``base``: the existing one with its body replaced (and its title, unless
    ``retitle`` is False), or a new one."""
    urls = [p["url"] for p in _pull_requests(upstream, head, base) if p["state"] == "OPEN"]
    if urls:
        _run(["gh", "pr", "edit", urls[0], "--body", body, *(["--title", title] if retitle else [])])
        return urls[0]
    out = _run(["gh", "pr", "create", "--repo", upstream, "--base", base, "--head", head,
                "--title", title, "--body", body]).stdout.strip()
    return out.splitlines()[-1]


def assert_safe_test_target(upstream, base):
    if upstream.lower() == PROTECTED_UPSTREAM.lower() or base == "master":
        raise PublishRefused(f"Tests may not target {upstream} or a master branch (got {upstream}@{base}).")
