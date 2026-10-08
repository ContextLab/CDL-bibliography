"""Run the same incremental verifier in PR, push, and manual Actions jobs.

PR snapshots come from the trusted base revision, not the proposed changes.
PR caches remain scoped to their merge ref; master never restores a PR cache.
For a pull request the approvals ledger (verification/approvals.jsonl) is read from
the base revision too: the checker is given the base's copy (an empty file when the
base has none) with --trusted-approvals, so rows a pull request adds are not read.
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

The `cdlbib crossref` commands of one run are run in this process when the
package is installed for the Python that runs this script (see `commands`):
each of them reads the whole bibliography, and parsing it takes seconds, so
they share one parse of each text the file has during the run.
"""

import contextlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback


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
    """Restore the committed baseline and require every entry to be accepted (offline)."""
    required(crossref("restore", "verification/baseline.jsonl.gz"), "restore")
    return crossref("status", "cdl.bib")


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
    if event in {"pull_request", "push"}:
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
        # Human approvals shared in the ledger count from the base revision only.
        approvals = work / "base-approvals.jsonl"
        try:
            approvals.write_bytes(git_file(base, "verification/approvals.jsonl"))
        except subprocess.CalledProcessError:
            approvals.write_bytes(b"")
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
    elif event != "workflow_dispatch":
        raise ValueError("Unsupported event")
    else:
        approvals, trusted_ledgers = None, []
    if snapshot is not None:
        required(crossref("restore", str(snapshot), *trusted_ledgers), "restore")
    verify = [
        "verify",
        "cdl.bib",
        "--auto-review",
        "--snapshot",
        str(work / "checkpoint.jsonl.gz"),
    ]
    if event != "workflow_dispatch":
        verify += ["--against", str(base_bib), "--trusted-approvals", str(approvals.resolve())] + trusted_ledgers
    return crossref(*verify)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
