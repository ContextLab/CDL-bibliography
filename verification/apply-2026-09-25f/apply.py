"""Stage 2D batches (2026-09-25): sfn001 and replace001.

The runner is ../apply-2026-09-25e/apply.py, unchanged in its discipline: frozen proposals
with fingerprints (<batch>-proposals.json), a staging copy whose diff is limited to the
batch, helpers.check_bib, backup + snapshot under .bibcheck/apply-2026-09-25f/, apply, the
production pipeline for the batch keys, a repeat that must make zero requests and zero
review writes, no change to any accepted result outside the batch, then
verification/baseline.jsonl.gz and verification/review-queue.jsonl.gz.

One addition, asserted in staging: an ``edit`` proposal with an empty ``changes`` and a
``rename`` is a pure key rename (LeeEtal20 -> LeeEtal20a, the suffix rule that makes room
for LeeEtal20b). Fingerprints do not include the cite key, so for that proposal the staged
fields must equal the old fields and the fingerprint must stay the same.

    .venv/bin/python verification/apply-2026-09-25f/apply.py BATCH [--apply]
"""
import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("apply0928", ROOT / "verification/apply-2026-09-25e/apply.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)
base = runner.base
runner.HERE = runner.runner.HERE = base.HERE = HERE
runner.WORK = runner.runner.WORK = base.WORK = WORK = ROOT / ".bibcheck" / HERE.name
runner.BATCHES = ("sfn001", "replace001")

from verification import load_entries  # noqa: E402

BIB = base.BIB


def stage(batch, entries, proposals):
    text = Path(BIB).read_text()
    modified = text
    by_key = {p["key"]: p for p in proposals}
    removed = {p["key"] for p in proposals if p["kind"] == "remove"}
    renames = {p["key"]: runner.new_key_of(p) for p in proposals
               if p["kind"] != "remove" and runner.new_key_of(p) != p["key"]}
    assert len(set(renames.values())) == len(renames), "two proposals share a new key"
    for old, new in renames.items():
        # A new key may be an old key of this same batch only if that entry is itself renamed away.
        assert new not in entries or new in renames, f"new key {new} already in cdl.bib"
        if new not in entries:
            assert not re.search(r"\b" + re.escape(new) + r"\b", text), f"{new} occurs in cdl.bib"
    for p in proposals:
        entry = entries[p["key"]]
        assert entry["fingerprint"] == p["fingerprint"], f"stale proposal {p['key']}"
        raw = entry["raw"]
        assert modified.count(raw) == 1, f"raw entry not unique {p['key']}"
        if p["kind"] == "remove":
            target = raw + "\n\n" if modified.count(raw + "\n\n") == 1 else "\n\n" + raw
            assert modified.count(target) == 1, p["key"]
            modified = modified.replace(target, "", 1)
        elif p["kind"] == "replace":
            modified = modified.replace(raw, p["raw"], 1)
        else:
            modified = modified.replace(raw, runner.edit_raw(raw, p), 1)
    staging = WORK / f"{batch}-staged.bib"
    staging.write_text(modified)
    staged = load_entries(staging)
    expected_keys = [renames.get(k, k) for k in entries if k not in removed]
    assert list(staged) == expected_keys, "cite keys or order changed beyond the approved renames/removals"
    for key, entry in entries.items():
        if key in removed:
            continue
        new_key = renames.get(key, key)
        p = by_key.get(key)
        if p is None:
            assert staged[new_key] == entry, key
            continue
        if p["kind"] == "replace":
            assert staged[new_key]["raw"] == p["raw"], key
            assert staged[new_key]["fingerprint"] != entry["fingerprint"], key
            continue
        expected = dict(entry["fields"])
        for field, change in p["changes"].items():
            if change["after"] is None:
                expected.pop(field)
            else:
                expected[field] = change["after"]
        expected["ID"] = new_key
        assert staged[new_key]["fields"] == expected, (key, staged[new_key]["fields"], expected)
        if p["changes"]:
            assert staged[new_key]["fingerprint"] != entry["fingerprint"], key
        else:
            assert p.get("rename") and staged[new_key]["fingerprint"] == entry["fingerprint"], key
    from helpers import check_bib
    errors, _ = check_bib(str(staging), verbose=False)
    assert not errors, errors
    print(f"PASS: {len(proposals)} {batch} proposals staged ({len(renames)} key renames/replacements: {renames}; "
          f"removed: {sorted(removed)}); all other entries and cite keys unchanged; check_bib clean", flush=True)
    return text, modified, renames, removed


runner.stage = stage

if __name__ == "__main__":
    runner.main()
