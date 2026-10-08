"""Run the same incremental verifier in PR, push, and manual Actions jobs.

PR snapshots come from the trusted base revision, not the proposed changes.
The results saved since the snapshot (verification/baseline-additions.jsonl) are read
with the snapshot and from the same revision as it, whatever the event: the base
revision's for a pull request and for a push that has a base (never the checkout's
copy, which is given to `crossref restore` with --additions, or --no-additions when
the base has none), and the checkout's own where the checkout's own snapshot is read
(a push without a base, a manual run).
PR caches remain scoped to their merge ref; master never restores a PR cache.
For a pull request the approvals ledger (verification/approvals.jsonl) is read from
the base revision too: the checker is given the base's copy (an empty file when the
base has none) with --trusted-approvals, so rows a pull request adds are not read,
unless a maintainer vouches for them (below).
For a push the pushed commit's own ledger is given instead: what is pushed to the
branch is already merged there, by someone who may write to it, so the rows a merge
brings in count for the entries the same merge changes. The base
revision's revocations (verification/revocations.jsonl) are given with
--trusted-revocations and honoured together with the checkout's own: a pull
request that removes a revocation line does not undo the revocation. What the
change adds to the approvals ledger is checked first (crossref check-ledger): a
removed or altered line, or an added line that is not a valid row at the time of
the run, fails the check.

A push whose previous commit is not in the history (a force-push or rewritten
history, or a new branch) has no base to compare against. Pushed content is
already merged, so its own committed baseline is checked instead: offline,
every entry must have an accepted result for its exact current text.

Rows a pull request adds to the approvals ledger (events pull_request and
pull_request_review). They have passed check-ledger: each is a valid row, now, for an
entry of the pull request's cdl.bib as it stands. They count in the pull request's own
check when someone with write access to the base repository vouches for them, which
GitHub is asked about (never the row, and never a file of the checkout):
  1. the pull request's author has write access (permission admin, maintain or write):
     then the added rows that name the author as their reviewer (human_review.github_login)
     count; or
  2. an account with write access approved the pull request, that approval is the
     account's latest review that decides anything (APPROVED, CHANGES_REQUESTED or
     DISMISSED; comments decide nothing), and it was given for the pull request's
     present head commit: then every added row counts, whoever recorded it.
The workflow supplies PR_AUTHOR, PR_NUMBER, PR_HEAD_SHA and PR_REPOSITORY from the
event and GITHUB_TOKEN; the script asks api.github.com. When any of them is missing or
GitHub cannot be asked or answers anything unexpected, nobody vouches: one line says
so and the rows do not count (the entries stay needs_review). The rows that count are
written after the base's to .bibcheck/vouched-approvals.jsonl, and the check is made in
a database of its own (.bibcheck/vouched.sqlite3, made anew): in the kept one, the
result an earlier run of the same pull request stored for the text is later than the
row and would outrank it. A pull request run ends with `crossref check-summary`: plain
lines saying which entries were verified against their sources, which a person's
review approved, which wait for a maintainer's approval, and which are not verified;
its status (0 only when the last two are empty) is the run's.

The `cdlbib crossref` commands of one run are run in this process when the
package is installed for the Python that runs this script (see `commands`):
each of them reads the whole bibliography, and parsing it takes seconds, so
they share one parse of each text the file has during the run.
"""

import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request


def git_file(revision, path):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected a full base commit SHA")
    return subprocess.run(
        ["git", "show", f"{revision}:{path}"], check=True, capture_output=True
    ).stdout


def commit_exists(revision):
    return bool(revision) and set(revision) != {"0"} and subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"], capture_output=True
    ).returncode == 0


def commands():
    """How this run runs `cdlbib crossref ...`: ``(reading, crossref)``. ``crossref(*arguments)``
    runs one command and returns its exit status; the run is made within ``reading``.

    With the package installed for this Python, a command is the function the installed
    `cdlbib` command calls (cdlbib.cli.main), called in this process, and ``reading`` is
    verification.read_once(by_content=True): the bibliography is parsed once for each text
    its file has during the run, told by the file's bytes, and not once by each command.
    Otherwise it is the command installed beside this interpreter, else the one on PATH, in
    a process of its own each time."""
    try:
        from cdlbib import verification
        from cdlbib.cli import main as cdlbib
    except ImportError:
        sibling = Path(sys.executable).parent / "cdlbib"
        program = [str(sibling) if sibling.exists() else shutil.which("cdlbib"), "crossref"]

        def crossref(*arguments):
            sys.stdout.flush()
            return subprocess.run(program + list(arguments)).returncode
        return contextlib.nullcontext(), crossref

    def crossref(*arguments):
        try:
            cdlbib(["crossref", *arguments])
        except SystemExit as stop:              # how a command ends: 0 or None, or what failed
            if stop.code is None or isinstance(stop.code, int):
                return stop.code or 0
            print(stop.code, file=sys.stderr)   # a message in place of a status, as the interpreter prints it
            return 1
        except Exception:                       # a command that broke: its traceback and status 1, as its own process gave
            traceback.print_exc()
            return 1
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
        return 0
    return verification.read_once(by_content=True), crossref


def required(status, command):
    """A step the rest depends on: a failure of it ends the run (exit status 2)."""
    if status:
        raise subprocess.CalledProcessError(status, f"cdlbib crossref {command}")


def library_check(crossref):
    """Restore the committed baseline, with the results saved since beside it when the
    checkout has them, and require every entry to be accepted (offline)."""
    required(crossref("restore", "verification/baseline.jsonl.gz"), "restore")
    return crossref("status", "cdl.bib")


# --- who vouches for the approvals a pull request adds ---------------------------------------

PULL_REQUEST_EVENTS = {"pull_request", "pull_request_review"}
WRITE_ACCESS = {"admin", "maintain", "write"}
DECIDING = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
GITHUB_API = "https://api.github.com"
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")


class Unanswered(Exception):
    """GitHub could not be asked, or its answer is not what the question has for an answer."""


def has_write_access(answer, login):
    """Whether ``answer``, GitHub's answer to
    GET /repos/{owner}/{repo}/collaborators/{login}/permission, says that ``login`` may
    write to the repository: its ``permission`` is admin, maintain or write (GitHub gives
    the maintain role as write there), and the account it is about is the one asked about.
    Unanswered for an answer of another shape."""
    if (not isinstance(answer, dict) or not isinstance(answer.get("permission"), str)
            or not isinstance(answer.get("user"), dict) or not isinstance(answer["user"].get("login"), str)):
        raise Unanswered("the answer about an account's permission is not of the expected form")
    return answer["user"]["login"].casefold() == login.casefold() and answer["permission"] in WRITE_ACCESS


def approving_accounts(reviews, head):
    """The logins whose approval of the pull request stands for the commit ``head``, from
    ``reviews``, GitHub's answer to GET /repos/{owner}/{repo}/pulls/{number}/reviews (every
    page, in the order given, which is the order of submission): for each account, its
    latest review whose state decides anything (APPROVED, CHANGES_REQUESTED, DISMISSED; a
    dismissed approval is that same review with the state DISMISSED) must be APPROVED and
    its commit_id must be ``head``. A review without an account (a deleted one) is nobody's.
    Unanswered for an answer of another shape."""
    if not isinstance(reviews, list):
        raise Unanswered("the answer about the pull request's reviews is not a list")
    latest = {}
    for review in reviews:
        if not isinstance(review, dict) or not isinstance(review.get("state"), str) or "user" not in review:
            raise Unanswered("a review in GitHub's answer is not of the expected form")
        user = review["user"]
        if user is None:
            continue
        if not isinstance(user, dict) or not isinstance(user.get("login"), str):
            raise Unanswered("a review in GitHub's answer is not of the expected form")
        if review["state"] in DECIDING:
            latest[user["login"].casefold()] = review
    return [review["user"]["login"] for review in latest.values()
            if review["state"] == "APPROVED" and isinstance(review.get("commit_id"), str)
            and bool(head) and review["commit_id"] == head]


def vouchers(author, head, reviews, permissions):
    """Who vouches for the approvals a pull request adds: ``(author, reviewers)``.
    ``author``: the pull request's author when that account has write access, else None
    (rule 1: the added rows it recorded itself count). ``reviewers``: the accounts with
    write access whose approval stands for ``head`` (rule 2: every added row counts).
    ``permissions``: GitHub's permission answer for each login asked about, by the login
    in lower case; an account without an answer vouches for nothing."""
    def writes(login):
        answer = permissions.get(login.casefold())
        return answer is not None and has_write_access(answer, login)
    return (author if author and writes(author) else None,
            [login for login in approving_accounts(reviews, head) if writes(login)])


def rows_that_count(added, author, reviewers):
    """Of ``added`` (the rows a pull request adds, as parsed lines), those someone vouches
    for (``vouchers``): all of them when a reviewer with write access approved the present
    head; else those naming the vouching author as their reviewer; else none."""
    if reviewers:
        return list(added)
    if author:
        return [row for row in added if isinstance(row.get("human_review"), dict)
                and isinstance(row["human_review"].get("github_login"), str)
                and row["human_review"]["github_login"].casefold() == author.casefold()]
    return []


def ask_github(path, token):
    """The parsed answer of GET https://api.github.com{path}, asked with ``token``.
    Unanswered when it cannot be had (said without the token or any header)."""
    request = urllib.request.Request(GITHUB_API + path, headers={
        "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "CDL-bibliography-citation-check"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise Unanswered(f"GitHub answered HTTP {exc.code} to GET {path}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Unanswered(f"GET {path} failed ({type(exc).__name__})") from None


def ask_vouchers(environ, ask=ask_github):
    """``vouchers`` for the pull request the workflow describes in ``environ`` (PR_AUTHOR,
    PR_NUMBER, PR_HEAD_SHA, PR_REPOSITORY, GITHUB_TOKEN), asking GitHub for its reviews
    and for the permission of its author and of each account whose approval stands.
    Unanswered when a fact or the token is missing or ill-formed, or GitHub is."""
    author, number, head = (environ.get(name, "").strip() for name in ("PR_AUTHOR", "PR_NUMBER", "PR_HEAD_SHA"))
    repository, token = environ.get("PR_REPOSITORY", "").strip(), environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise Unanswered("no GITHUB_TOKEN was given")
    if not (number.isdigit() and re.fullmatch(r"[0-9a-f]{40}", head) and REPOSITORY.fullmatch(repository) and author):
        raise Unanswered("the pull request's author, number, head commit or repository was not given")
    reviews, page = [], 1
    while True:
        answer = ask(f"/repos/{repository}/pulls/{int(number)}/reviews?per_page=100&page={page}", token)
        if not isinstance(answer, list):
            raise Unanswered("the answer about the pull request's reviews is not a list")
        reviews += answer
        if len(answer) < 100:
            break
        page += 1
        if page > 30:
            raise Unanswered("the pull request has more reviews than are read")
    permissions = {}
    for login in [author] + approving_accounts(reviews, head):
        # An account whose login is no user's (an app's, "name[bot]") has no permission to ask about.
        if login.casefold() not in permissions and LOGIN.fullmatch(login):
            permissions[login.casefold()] = ask(
                f"/repos/{repository}/collaborators/{urllib.parse.quote(login, safe='')}/permission", token)
    return vouchers(author, head, reviews, permissions)


def added_rows(base, head):
    """The lines ``head`` (the checkout's approvals ledger, bytes) has beyond those of
    ``base`` (the base revision's): [(line, parsed row)]. `crossref check-ledger` has
    already failed the run unless every line of the base is kept and every added line is a
    valid row."""
    held = {}
    for line in base.splitlines():
        held[line] = held.get(line, 0) + 1
    added = []
    for line in head.splitlines():
        if held.get(line):
            held[line] -= 1
        elif line.strip():
            row = json.loads(line.decode("utf-8"))
            if not isinstance(row, dict):
                raise ValueError("A line added to verification/approvals.jsonl is not a row")
            added.append((line, row))
    return added


def vouched_ledger(base, head, environ, ask=ask_github):
    """The approvals ledger a pull request's check reads, as bytes, or None for the base
    revision's alone: the base's lines, then the added lines someone vouches for. Prints
    one line saying whether the rows the pull request adds count and why."""
    added = added_rows(base, head)
    if not added:
        return None
    rows = f"{len(added)} approval{'' if len(added) == 1 else 's'} this pull request adds"
    try:
        author, reviewers = ask_vouchers(environ, ask)
    except Unanswered as exc:
        print(f"The {rows}: not counted, since who vouches for them could not be learned from GitHub ({exc}).")
        return None
    counted = rows_that_count([row for _, row in added], author, reviewers)
    if not counted:
        print(f"The {rows}: not counted. Nobody with write access vouches for them: the author "
              "has none, and no account that has it approved the present head commit.")
        return None
    chosen = [line for line, row in added if any(row is one for one in counted)]
    if reviewers:
        print(f"The {rows}: counted, on the approval of this head commit by "
              + ", ".join("@" + login for login in reviewers) + " (write access).")
    else:
        print(f"The {rows}: {len(chosen)} counted, recorded by the author @{author} (write access)"
              + ("." if len(chosen) == len(added) else "; the others were recorded by someone else."))
    return (base if not base or base.endswith(b"\n") else base + b"\n") + b"".join(line + b"\n" for line in chosen)


def main():
    reading, crossref = commands()
    with reading:
        return check(crossref)


def check(crossref):
    work = Path(".bibcheck")
    work.mkdir(exist_ok=True)
    base = os.environ.get("BASE_REVISION", "")
    event = os.environ.get("EVENT_NAME", "")
    snapshot = Path("verification/baseline.jsonl.gz")
    if event == "push" and not commit_exists(base):
        print(f"Base revision {base or '(none)'} is not in the history (force-push or new branch); "
              "checking the whole library against its committed baseline instead.")
        return library_check(crossref)
    database, additions, proposed = [], [], None
    if event in PULL_REQUEST_EVENTS | {"push"}:
        if not base or set(base) == {"0"}:
            raise ValueError("Missing base revision; use a manual full-library run")
        base_bib = work / "base.bib"
        base_bib.write_bytes(git_file(base, "cdl.bib"))
        # Use trusted baseline evidence when available. On the introducing
        # commit the baseline may not yet exist; verify selected entries fresh.
        trusted = work / "base-snapshot.jsonl.gz"
        try:
            data = git_file(base, "verification/baseline.jsonl.gz")
        except subprocess.CalledProcessError:
            snapshot = None
        else:
            trusted.write_bytes(data)
            snapshot = trusted
            # The results saved since the snapshot: the same revision's as the snapshot.
            try:
                saved_since = git_file(base, "verification/baseline-additions.jsonl")
            except subprocess.CalledProcessError:
                additions = ["--no-additions"]
            else:
                (work / "base-additions.jsonl").write_bytes(saved_since)
                additions = ["--additions", str((work / "base-additions.jsonl").resolve())]
        # Human approvals shared in the ledger count from the base revision only.
        approvals = work / "base-approvals.jsonl"
        try:
            base_approvals = git_file(base, "verification/approvals.jsonl")
        except subprocess.CalledProcessError:
            base_approvals = b""
        approvals.write_bytes(base_approvals)
        revocations = work / "base-revocations.jsonl"
        try:
            revocations.write_bytes(git_file(base, "verification/revocations.jsonl"))
        except subprocess.CalledProcessError:
            revocations.write_bytes(b"")
        trusted_ledgers = ["--trusted-revocations", str(revocations.resolve())]
        # Rows are validated when they enter: a change that removes or alters a ledger line,
        # or adds a line that is not a valid row now, under the current policy, for an entry
        # of this commit's cdl.bib under its key, fails here (nothing can be merged today to
        # start counting later: not a future date, another policy, or a text nobody has yet).
        entering = crossref("check-ledger", "--base", str(approvals.resolve()))
        if entering:
            return entering
        if event == "push":
            # Pushed content is already merged: the rows that came in with it, valid as just
            # checked, count. A pull request keeps the base's copy.
            pushed = Path("verification/approvals.jsonl")
            approvals = work / "pushed-approvals.jsonl"
            approvals.write_bytes(pushed.read_bytes() if pushed.is_file() and not pushed.is_symlink() else b"")
        else:
            # A pull request keeps the base's copy, and the rows it adds that someone with
            # write access vouches for (see the top of this file).
            own = Path("verification/approvals.jsonl")
            own_approvals = own.read_bytes() if own.is_file() and not own.is_symlink() else b""
            proposed = work / "proposed-approvals.jsonl"
            proposed.write_bytes(own_approvals)
            vouched = vouched_ledger(base_approvals, own_approvals, os.environ)
            sys.stdout.flush()
            if vouched is not None:
                approvals = work / "vouched-approvals.jsonl"
                approvals.write_bytes(vouched)
                fresh = work / "vouched.sqlite3"
                for name in (fresh.name, fresh.name + "-wal", fresh.name + "-shm", fresh.name + "-journal"):
                    (work / name).unlink(missing_ok=True)
                database = ["--database", str(fresh)]
    elif event != "workflow_dispatch":
        raise ValueError("Unsupported event")
    else:
        approvals, trusted_ledgers = None, []
    if snapshot is not None:
        required(crossref("restore", str(snapshot), *trusted_ledgers, *additions, *database), "restore")
    verify = [
        "verify",
        "cdl.bib",
        "--auto-review",
        "--snapshot",
        str(work / "checkpoint.jsonl.gz"),
    ]
    if event != "workflow_dispatch":
        verify += ["--against", str(base_bib), "--trusted-approvals", str(approvals.resolve())] + trusted_ledgers
    status = crossref(*verify, *database)
    if event in PULL_REQUEST_EVENTS and status in (0, 1):
        # What the check came to, in lines for the pull request's reader; its status is the run's.
        print("Result of the citation check of this pull request:")
        sys.stdout.flush()
        return crossref("check-summary", "cdl.bib", "--against", str(base_bib),
                        "--trusted-approvals", str(approvals.resolve()), *trusted_ledgers,
                        "--proposed-approvals", str(proposed.resolve()), *database)
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
