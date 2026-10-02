"""Send a change: the user's fork, a branch, a pull request. One route for everyone."""
import json
import re
import subprocess

from .errors import PublishRefused

ALLOWED = ("cdl.bib", "verification/")
WORK = ".bibcheck/"                      # the local working folder: never sent, never a stray file
PROTECTED_UPSTREAM = "ContextLab/CDL-bibliography"


def _run(args, cwd=None, check=True):
    try:
        run = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:               # git or gh is not installed
        raise PublishRefused(f"`{args[0]}` could not be run ({type(exc).__name__}: {exc})") from exc
    if check and run.returncode != 0:
        raise PublishRefused(f"`{' '.join(args[:3])} …` failed:\n{(run.stderr or run.stdout).strip()[-2000:]}")
    return run


def upstream_of(ws):
    """'OWNER/NAME' of the GitHub repository the checkout was cloned from (its origin)."""
    url = _run(["git", "remote", "get-url", "origin"], cwd=ws.root).stdout.strip()
    match = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url)
    if not match:
        raise PublishRefused(f"The checkout's origin is not a GitHub repository: {url}")
    return f"{match.group(1)}/{match.group(2)}"


def find_fork(upstream, login):
    """The fork of ``upstream`` owned by ``login`` ('login/NAME'), or None. Read-only."""
    name = upstream.split("/", 1)[1]
    run = _run(["gh", "api", f"repos/{login}/{name}"], check=False)
    if run.returncode == 0:
        data = json.loads(run.stdout)
        if data.get("fork") and (data.get("parent") or {}).get("full_name", "").lower() == upstream.lower():
            return data["full_name"]
    # A fork may have been renamed: ask the upstream for forks owned by this login.
    run = _run(["gh", "api", f"repos/{upstream}/forks", "--paginate", "--jq",
                f'.[] | select(.owner.login == "{login}") | .full_name'], check=False)
    names = run.stdout.split() if run.returncode == 0 else []
    return names[0] if names else None


def create_fork(upstream):
    """Fork ``upstream`` into the logged-in user's account. Called only after the user agreed."""
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
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ws.root).stdout.strip()


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
    return [p for p in _changed(ws) if not _allowed(p) and not p.startswith(WORK)]


def pending(ws):
    """The changed paths a send would commit."""
    return [p for p in _changed(ws) if _allowed(p)]


def commit_to_branch(ws, branch, message):
    """Commit the changes to cdl.bib and verification/ on ``branch`` (made from the current
    commit when new) and leave the checkout on it. Returns the commit."""
    mine = pending(ws)
    if not mine:
        raise PublishRefused("There are no changes to cdl.bib or verification/ to send.")
    if current_branch(ws) != branch:
        exists = _run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=ws.root, check=False).returncode == 0
        _run(["git", "switch", branch] if exists else ["git", "switch", "-c", branch], cwd=ws.root)
    _run(["git", "add", "-A", "--", *mine], cwd=ws.root)
    _run(["git", "commit", "-m", message, "--", *mine], cwd=ws.root)
    return _run(["git", "rev-parse", "HEAD"], cwd=ws.root).stdout.strip()


def push(ws, remote_url, branch):
    _run(["git", "push", remote_url, f"refs/heads/{branch}:refs/heads/{branch}"], cwd=ws.root)


def open_or_update_pr(upstream, base, head, title, body, retitle=True):
    """The URL of the open pull request from ``head`` ('branch' or 'owner:branch') into
    ``upstream``'s ``base``: the existing one with its body replaced (and its title, unless
    ``retitle`` is False), or a new one."""
    found = _run(["gh", "pr", "list", "--repo", upstream, "--head", head.split(":")[-1], "--base", base,
                  "--state", "open", "--json", "url,headRepositoryOwner"]).stdout
    owner = head.split(":")[0] if ":" in head else upstream.split("/")[0]
    urls = [p["url"] for p in json.loads(found or "[]")
            if (p.get("headRepositoryOwner") or {}).get("login", "").lower() == owner.lower()]
    if urls:
        _run(["gh", "pr", "edit", urls[0], "--body", body, *(["--title", title] if retitle else [])])
        return urls[0]
    out = _run(["gh", "pr", "create", "--repo", upstream, "--base", base, "--head", head,
                "--title", title, "--body", body]).stdout.strip()
    return out.splitlines()[-1]


def assert_safe_test_target(upstream, base):
    if upstream.lower() == PROTECTED_UPSTREAM.lower() or base == "master":
        raise PublishRefused(f"Tests may not target {upstream} or a master branch (got {upstream}@{base}).")
