"""Build braces0929-proposals.json: braces that protect nothing, removed (2026-09-29).

User decision 2026-09-29: "Correct the braces". format_journal_name braced every caps.txt
word, so journal, booktitle and publisher names carried braces around ordinary title-case
words ("Harvard {University} Press", "{Oxford} {University} Press", "{American} Journal of
Psychology"). helpers.unbrace_ordinary now drops them; this script runs the formatter over
every entry and freezes each changed value with the entry's fingerprint. Each proposal is
asserted to change braces only (the text without braces is identical) and to be stable
under a second formatter pass. Address values are formatted too (they only carry state
codes, which keep their braces).

    python verification/apply-2026-09-29-braces/build.py
"""
from collections import Counter
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import helpers  # noqa: E402
from verification import load_entries  # noqa: E402

BATCH = "braces0929"
SOURCE = ("formatter: helpers.unbrace_ordinary drops braces around ordinary title-case words in "
          "journal/booktitle/publisher names (user decision 2026-09-29); text unchanged")
FIELD_FORMAT = {
    "journal": lambda v: helpers.format_journal_name(v),
    "booktitle": lambda v: helpers.format_journal_name(v),
    "publisher": lambda v: helpers.format_journal_name(v, key=helpers.publisher_key, dotted_initials=True),
    "address": lambda v: helpers.format_journal_name(v, key=helpers.address_key, force_caps=helpers.address_codes),
}


def strip(s):
    return s.replace("{", "").replace("}", "")


def main():
    entries = load_entries(ROOT / "cdl.bib")
    proposals, per_field, braces = [], Counter(), Counter()
    for key, entry in entries.items():
        changes = {}
        for field, fmt in FIELD_FORMAT.items():
            before = entry["fields"].get(field)
            if before is None:
                continue
            after = fmt(before)
            if after == before:
                continue
            assert strip(after) == strip(before), (key, field, before, after)
            assert fmt(after) == after, (key, field, after)
            changes[field] = {"before": before, "after": after}
            per_field[field] += 1
            braces[field] += (before.count("{") - after.count("{"))
        if changes:
            proposals.append({"key": key, "kind": "edit", "fingerprint": entry["fingerprint"],
                              "changes": changes, "source": SOURCE})
    bib_sha = hashlib.sha256((ROOT / "cdl.bib").read_bytes()).hexdigest()
    out = {"batch": BATCH, "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
           "input": [{"file": "cdl.bib", "sha256": bib_sha}],
           "count": len(proposals), "counts": {"edit": len(proposals), "remove": 0}, "renames": {},
           "values_changed_per_field": dict(per_field), "brace_pairs_removed_per_field": dict(braces),
           "proposals": proposals}
    (HERE / f"{BATCH}-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    (HERE / "batch-keys.txt").write_text("".join(p["key"] + "\n" for p in proposals))
    print(f"{len(proposals)} proposals written; values per field {dict(per_field)}; "
          f"brace pairs removed {dict(braces)}")


if __name__ == "__main__":
    main()
