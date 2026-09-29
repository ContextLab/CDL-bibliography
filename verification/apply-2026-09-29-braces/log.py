"""Write REVIEW.md and the review packets for the human-approved entries this batch edited.

Their approvals were bound to the old text, so they lapsed to needs_review. They are NOT
re-approved here: the user reviews each one. For each entry this script writes
review-packet-<KEY>.json (``bibcheck.py crossref review-packet``) and a REVIEW.md section with
the before/after text, the lapsed approval's reviewer/source/note, and the exact
``crossref approve`` command bound to the new fingerprint.

    python verification/apply-2026-09-29-braces/log.py
"""
import json
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import Cache, current_results, load_entries  # noqa: E402


def main():
    old = json.loads((HERE / "human-approved-before.json").read_text())
    proposals = {p["key"]: p for p in json.loads((HERE / "braces0929-proposals.json").read_text())["proposals"]}
    entries = load_entries(ROOT / "cdl.bib")
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        results = current_results(ROOT / "cdl.bib", cache, entries)
    finally:
        cache.close()
    lines = ["# Human-approved entries awaiting review (braces0929, 2026-09-29)", "",
             "The braces batch changed only braces in these entries, but each human approval was bound",
             "to the old text, so it lapsed to `needs_review`. Nothing here was re-approved. To restore",
             "an approval after checking the entry, run its `crossref approve` command from the repo root.",
             "Each command reuses the old approval's reviewer and source; the note records the brace change.",
             "Review packets: `review-packet-<KEY>.json` in this folder.", ""]
    for key in sorted(old):
        entry, result, before = entries[key], results[key], old[key]
        fp = entry["fingerprint"]
        assert result["fingerprint"] == fp and result["status"] != "human_verified", (key, result["status"])
        packet = HERE / f"review-packet-{key}.json"
        subprocess.run([sys.executable, "bibcheck.py", "crossref", "review-packet", key,
                        "--output", str(packet)], cwd=ROOT, check=True, capture_output=True)
        hr = before["human_review"]
        note = (f"Re-approval after braces0929 (2026-09-29): only braces around ordinary words changed "
                f"({', '.join(proposals[key]['changes'])}). Previous approval: {hr['note']}")
        cmd = ["python", "bibcheck.py", "crossref", "approve", key, "--fingerprint", fp,
               "--reviewer", hr["reviewer"], "--source", hr["source"], "--note", note]
        lines += [f"## {key}", "", f"Status now: `{result['status']}`. "
                  f"Old fingerprint `{before['fingerprint']}`, new fingerprint `{fp}`.", ""]
        for field, change in proposals[key]["changes"].items():
            lines += [f"- {field} before: `{change['before']}`", f"- {field} after: `{change['after']}`"]
        lines += ["", "Lapsed approval:", "", f"- reviewer: {hr['reviewer']}", f"- source: {hr['source']}",
                  f"- note: {hr['note']}", "", "Entry now:", "", "```bibtex", entry["raw"], "```", "",
                  "Approve command:", "", "```sh", " ".join(shlex.quote(c) for c in cmd), "```", ""]
    (HERE / "REVIEW.md").write_text("\n".join(lines))
    print(f"REVIEW.md: {len(old)} entries")


if __name__ == "__main__":
    main()
