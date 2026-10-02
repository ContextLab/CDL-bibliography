"""Run the same incremental verifier in PR, push, and manual Actions jobs.

PR snapshots come from the trusted base revision, not the proposed changes.
PR caches remain scoped to their merge ref; master never restores a PR cache.

A push whose previous commit is not in the history (a force-push or rewritten
history, or a new branch) has no base to compare against. Pushed content is
already merged, so its own committed baseline is checked instead: offline,
every entry must have an accepted result for its exact current text.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


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


def library_check(command):
    """Restore the committed baseline and require every entry to be accepted (offline)."""
    subprocess.run(command + ["restore", "verification/baseline.jsonl.gz"], check=True)
    return subprocess.run(command + ["status", "cdl.bib"]).returncode


def main():
    work = Path(".bibcheck")
    work.mkdir(exist_ok=True)
    base = os.environ.get("BASE_REVISION", "")
    event = os.environ.get("EVENT_NAME", "")
    # The command installed beside this interpreter, else the one on PATH.
    sibling = Path(sys.executable).parent / "cdlbib"
    command = [str(sibling) if sibling.exists() else shutil.which("cdlbib"), "crossref"]
    snapshot = Path("verification/baseline.jsonl.gz")
    if event == "push" and not commit_exists(base):
        print(f"Base revision {base or '(none)'} is not in the history (force-push or new branch); "
              "checking the whole library against its committed baseline instead.")
        return library_check(command)
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
    elif event != "workflow_dispatch":
        raise ValueError("Unsupported event")
    if snapshot is not None:
        subprocess.run(command + ["restore", str(snapshot)], check=True)
    verify = command + [
        "verify",
        "cdl.bib",
        "--auto-review",
        "--snapshot",
        str(work / "checkpoint.jsonl.gz"),
    ]
    if event != "workflow_dispatch":
        verify += ["--against", str(base_bib)]
    return subprocess.run(verify).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
