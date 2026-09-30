"""Apply the user's surname decisions of 2026-09-30 (batch surnames0930c).

The page: https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM (collection "review0930"; source and
build scripts in verification/2026-09-30-user-review/page/). The answer documents, read with the
ArtifactData tool on 2026-09-30, are in answers/; the printed-byline evidence is in printed/;
every mismatch's decision is in decisions.json (build_decisions.py).

Steps (runner: ../apply-2026-09-30b-answers/apply.py's chain, ../apply-2026-09-25e/apply.py):

  --freeze  write surnames0930c-batch.json: the answer documents' times, and for every entry the
            decisions change, its current fingerprint and the new Author field (each changed
            name checked against the old one at its position); a key whose helpers.authors2key
            base changes is renamed (suffix rules checked in staging by check_bib).
  --apply   1. preconditions: answer documents and fingerprints are the frozen ones;
            2. staging in a copy: only the Author fields (and the one key) change, check_bib is
               clean; backup and snapshot under .bibcheck/apply-2026-09-30c-surnames/;
               key-renames.json gains the rename;
            3. the production pipeline for the batch (the edited entries and every entry not
               accepted); nothing accepted outside the batch may change;
            4. approvals: every decided entry that is still not accepted, and whose open issues
               are only surname mismatches the user decided, gets `crossref approve`
               (reviewer "Jeremy Manning"); negative controls: approving an edited entry on its
               pre-edit fingerprint is refused; the held entry is not approved;
            5. a repeat of the pipeline: zero requests, zero review writes, identical results;
            6. verification/baseline.jsonl.gz and verification/review-queue.jsonl.gz exported.

    python verification/apply-2026-09-30c-surnames/apply.py --freeze
    python verification/apply-2026-09-30c-surnames/apply.py [--apply]
"""
from collections import Counter, defaultdict
import argparse
import gzip
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("apply0925e", ROOT / "verification/apply-2026-09-25e/apply.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)  # chdir(ROOT), sys.path, patient routes
base = runner.base
WORK = ROOT / ".bibcheck" / HERE.name
base.HERE = runner.HERE = runner.runner.HERE = HERE
base.WORK = runner.WORK = runner.runner.WORK = WORK

from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_lock  # noqa: E402
import research_route  # noqa: E402,F401  (registers the research approval validator)
from helpers import authors2key, check_bib, split_names  # noqa: E402

BIB = base.BIB
BATCH = "surnames0930c"
PAGE = "https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM"
COLLECTION = "review0930"
REVIEWER = "Jeremy Manning"
FROZEN_PATH = HERE / f"{BATCH}-batch.json"
DECISIONS = json.loads((HERE / "decisions.json").read_text())
PRINTED_RULE = ("user rule 2026-09-28 (decision log): \"the printed paper is the source of truth. When the "
                "printed paper ... and the registry metadata (Crossref, PubMed, etc.) differ, the printed paper wins\"")
MISMATCH = re.compile(r"^author: surname mismatch: ")
POSITION = re.compile(r"\bauthor (\d+) is\b")
GENERIC = "No unambiguous, fully supported metadata match"


def answer(doc):
    return json.loads((HERE / "answers" / f"{doc}.json").read_text())


def changes_by_key():
    out = defaultdict(list)
    for r in DECISIONS:
        if r["decision"] == "change":
            out[r["key"]].append(r)
    return out


def year_of(entry):
    return entry["fields"]["year"]


def freeze():
    assert not FROZEN_PATH.exists(), f"{FROZEN_PATH} exists; the batch is frozen once"
    entries = load_entries(BIB)
    proposals = []
    for key, rows in sorted(changes_by_key().items()):
        entry = entries[key]
        before = entry["fields"]["author"]
        names = split_names(before)
        for r in rows:
            assert names[r["position"] - 1] == r["old_name"], (key, r["position"], names[r["position"] - 1])
            names[r["position"] - 1] = r["new_name"]
        after = " and ".join(names)
        old_base = authors2key(before, year_of(entry))
        new_base = authors2key(after, year_of(entry))
        assert key.startswith(old_base) and re.fullmatch(r"[a-z]*", key[len(old_base):]), (key, old_base)
        p = {"key": key, "fingerprint": entry["fingerprint"], "kind": "edit",
             "changes": {"author": {"before": before, "after": after}},
             "positions": [{"position": r["position"], "old": r["old_name"], "new": r["new_name"], "why": r["why"]}
                           for r in rows]}
        if new_base != old_base:
            same_base = [k for k in entries if k != key and re.fullmatch(re.escape(new_base) + r"[a-z]*", k)
                         and authors2key(entries[k]["fields"].get("author", ""), year_of(entries[k])) == new_base]
            assert not same_base, (key, new_base, same_base)  # would need suffixes; decide by hand
            p["rename"] = new_base  # no other entry shares the base, so no suffix
        proposals.append(p)
    used = sorted({d["doc"] for r in DECISIONS for d in r["docs"]})
    decided = sorted({r["key"] for r in DECISIONS if r["decision"] != "hold"})
    held = sorted({r["key"] for r in DECISIONS if r["decision"] == "hold"})
    frozen = {"batch": BATCH, "frozen_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
              "answers": {doc: answer(doc)["updatedAt"] for doc in used},
              "proposals": proposals, "decided_keys": decided, "held_keys": held}
    FROZEN_PATH.write_text(json.dumps(frozen, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"proposals": len(proposals), "renames": {p["key"]: p["rename"] for p in proposals
                                                                if p.get("rename")},
                      "decided_keys": len(decided), "held": held}))


def stage(entries, text, proposals):
    modified = text
    renames = {p["key"]: p["rename"] for p in proposals if p.get("rename")}
    for new in renames.values():
        assert new not in entries and not re.search(r"\b" + re.escape(new) + r"\b", text), new
    for p in proposals:
        entry = entries[p["key"]]
        assert entry["fingerprint"] == p["fingerprint"], f"stale proposal {p['key']}"
        assert modified.count(entry["raw"]) == 1, p["key"]
        modified = modified.replace(entry["raw"], runner.edit_raw(entry["raw"], p), 1)
    staging = WORK / f"{BATCH}-staged.bib"
    staging.write_text(modified)
    staged = load_entries(staging)
    assert list(staged) == [renames.get(k, k) for k in entries], "cite keys or order changed beyond the renames"
    by_key = {p["key"]: p for p in proposals}
    for key, entry in entries.items():
        new_key = renames.get(key, key)
        if key not in by_key:
            assert staged[new_key] == entry, key
            continue
        expected = dict(entry["fields"], author=by_key[key]["changes"]["author"]["after"], ID=new_key)
        assert staged[new_key]["fields"] == expected, key
        assert staged[new_key]["fingerprint"] != entry["fingerprint"], key
        assert authors2key(expected["author"], expected["year"]) + re.sub(r"^.*\d\d", "", new_key) == new_key, key
    errors, _ = check_bib(str(staging), verbose=False)
    assert not errors, errors
    print(f"PASS: {len(proposals)} author edits staged (renames {renames}); every other entry and key "
          "unchanged; check_bib clean", flush=True)
    return modified, renames


def edt(utc):
    from datetime import datetime, timedelta, timezone
    moment = datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=-4)))
    return moment.strftime("%Y-%m-%d %H:%M:%S EDT")


def log_renames(proposals, renames):
    if not renames:
        return
    path = ROOT / "verification/key-renames.json"
    log = json.loads(path.read_text())
    if any(r.get("commit") == BATCH for r in log):
        return
    today = subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True, check=True).stdout.strip()
    for p in proposals:
        if not p.get("rename"):
            continue
        g = answer("surname-group-longer")
        log.append({
            "old_key": p["key"], "new_key": p["rename"], "date": today, "commit": BATCH,
            "reason": (f"author {p['positions'][0]['position']} respelled '{p['positions'][0]['old']}' -> "
                       f"'{p['positions'][0]['new']}' (user decision); the key rule (helpers.authors2key) "
                       f"gives {p['rename']}"),
            "user_note": g["note"],
            "decision_source": (f"user, review page {PAGE}, collection {COLLECTION}, doc surname-group-longer, "
                                f"choice '{g['choice']}', answered {g['updatedAt']} ({edt(g['updatedAt'])})")})
    path.write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")


def approval_row(key, rows):
    """The approval text for one entry: the user's choices and the printed evidence."""
    docs, parts, printed = [], [], []
    for r in sorted(rows, key=lambda r: r["position"]):
        for d in r["docs"]:
            if d["doc"] not in {x["doc"] for x in docs}:
                docs.append(d)
        chosen = r.get("new_name") or r["entry_spelling"]
        parts.append(f"author {r['position']}: {'changed to' if r['decision'] == 'change' else 'kept'} "
                     f"'{chosen}' (entry '{r['entry_spelling']}', source '{r['source_spelling']}'): {r['why']}")
        p = r["printed"]
        if p and p.get("quote"):
            printed.append(f"printed byline ({p['url']}, p. {p['page']}): \"{p['quote']}\"")
    if docs:
        source = (f"review page {PAGE}, collection {COLLECTION}, "
                  + "; ".join(f"doc {d['doc']} ('{d['choice']}'" + (f", note {d['note']}" if d['note'] else "")
                              + f"), answered {d['answered']}" for d in docs))
    else:
        source = (f"review page {PAGE}, collection {COLLECTION} (section C/E rows settled by the printed byline, "
                  f"as the page told the user); {PRINTED_RULE}")
    note = "User surname decision 2026-09-30. " + " | ".join(parts)
    if printed:
        note += " | " + " | ".join(dict.fromkeys(printed))
    return {"key": key, "source": source, "note": note}


def approve(key, fingerprint, source, note, expect_ok=True):
    cmd = [sys.executable, "bibcheck.py", "crossref", "approve", key, "--fingerprint", fingerprint,
           "--reviewer", REVIEWER, "--source", source, "--note", note]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=dict(os.environ))
    out = (done.stdout + done.stderr).strip()
    assert (done.returncode == 0) == expect_ok, (key, done.returncode, out)
    return out


def open_issues(result, decided_positions):
    """The issues that are NOT a surname mismatch the user decided (empty: approvable)."""
    other = []
    for issue in result.get("issues", []):
        text = issue if isinstance(issue, str) else json.dumps(issue)
        if text == GENERIC:
            continue
        if MISMATCH.match(text) and set(map(int, POSITION.findall(text))) <= decided_positions:
            continue
        other.append(text)
    return other


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    if args.freeze:
        return freeze()
    frozen = json.loads(FROZEN_PATH.read_text())
    proposals = frozen["proposals"]
    for doc, updated in frozen["answers"].items():
        assert answer(doc)["updatedAt"] == updated, doc
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    report = WORK / f"{BATCH}-report.jsonl"
    try:
        backup = WORK / f"before-{BATCH}.bib"
        resuming = backup.exists()
        original = load_entries(backup if resuming else BIB)
        text = (backup if resuming else Path(BIB)).read_text()
        modified, renames = stage(original, text, proposals)
        if resuming:
            with gzip.open(WORK / f"before-{BATCH}.jsonl.gz", "rt") as f:
                before = {r["key"]: r for r in map(json.loads, f) if "key" in r}
        else:
            before = current_results(BIB, cache, original)
        print(json.dumps({"statuses": dict(Counter(r["status"] for r in before.values())),
                          "edits": [p["key"] for p in proposals], "renames": renames}), flush=True)
        if not args.apply:
            return
        with run_lock(cache):
            if resuming:
                assert Path(BIB).read_bytes() == (WORK / f"{BATCH}-staged.bib").read_bytes()
            else:
                export_snapshot(BIB, cache, WORK / f"before-{BATCH}.jsonl.gz")
                shutil.copyfile(BIB, backup)
                assert Path(BIB).read_text() == text
                Path(BIB).write_text(modified)
        log_renames(proposals, renames)
        before = {renames.get(k, k): r for k, r in before.items()}
        edited = {renames.get(p["key"], p["key"]) for p in proposals}
        keys = edited | {k for k, r in before.items() if r["status"] not in ACCEPTED}
        rows_by_key = defaultdict(list)
        for r in DECISIONS:
            rows_by_key[renames.get(r["key"], r["key"])].append(r)
        held = {renames.get(k, k) for k in frozen["held_keys"]}
        client = base.client_for(cache)
        stages, first = [], None
        for cycle in ("run", "approve", "repeat"):
            start, calls, count = time.monotonic(), client.requests, base.review_count(cache)
            if cycle == "approve":
                entries = load_entries(BIB)
                now = current_results(BIB, cache)
                messages, left = {}, {}
                for key in sorted(rows_by_key):
                    if now[key]["status"] in ACCEPTED or key in held:
                        continue
                    decided = {r["position"] for r in rows_by_key[key] if r["decision"] != "hold"}
                    other = open_issues(now[key], decided)
                    if other:
                        left[key] = other
                        continue
                    row = approval_row(key, rows_by_key[key])
                    hr = now[key].get("human_review") or {}
                    if now[key]["status"] == "human_verified" and hr == {
                            "reviewer": REVIEWER, "source": row["source"], "note": row["note"]}:
                        messages[key] = "already recorded (resumed run); not written again"
                        continue
                    messages[key] = approve(key, entries[key]["fingerprint"], row["source"], row["note"])
                # Negative controls: an approval on the pre-edit text is refused; the held entry is untouched.
                controls = {}
                for p in proposals:
                    key = renames.get(p["key"], p["key"])
                    controls[key] = approve(key, p["fingerprint"], "negative control", "negative control",
                                            expect_ok=False)
                    assert "Entry changed since review" in controls[key], controls[key]
                after = current_results(BIB, cache)
                for key in held:
                    assert after[key] == before[key], key
                row = {"cycle": cycle, "network_requests": client.requests - calls,
                       "added_review_records": base.review_count(cache) - count,
                       "approved": {k: {"status": after[k]["status"], "fingerprint": after[k]["fingerprint"],
                                        "human_review": after[k].get("human_review"), "cli": m}
                                    for k, m in messages.items()},
                       "not_approved_other_issues": left, "stale_fingerprint_controls": controls,
                       "held": {k: after[k]["status"] for k in held},
                       "library_statuses": dict(Counter(r["status"] for r in after.values()))}
                assert all(v["status"] == "human_verified" for v in row["approved"].values())
                assert row["added_review_records"] == sum(not m.startswith("already recorded")
                                                          for m in messages.values()), row["added_review_records"]
                print(json.dumps({k: v for k, v in row.items() if k not in ("approved",)}, ensure_ascii=False)[:3000],
                      flush=True)
                stages.append(row)
                first = after
                continue
            after = base.pipeline(cache, client, keys, report)
            assert set(after) == set(before), "library keys differ"
            changed_accepted = [k for k, r in before.items()
                                if r["status"] in ACCEPTED and k not in keys and after[k] != r]
            assert not changed_accepted, changed_accepted[:20]
            lost = sorted(k for k in after if before[k]["status"] in ACCEPTED and after[k]["status"] not in ACCEPTED)
            newly = sorted(k for k in after if before[k]["status"] not in ACCEPTED and after[k]["status"] in ACCEPTED)
            row = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                   "network_requests": client.requests - calls,
                   "added_review_records": base.review_count(cache) - count,
                   "batch": sorted(keys),
                   "batch_statuses_before": dict(Counter(before[k]["status"] for k in keys)),
                   "batch_statuses_after": dict(Counter(after[k]["status"] for k in keys)),
                   "previously_accepted_now_unresolved": lost, "newly_accepted": newly,
                   "library_statuses_before": dict(Counter(r["status"] for r in before.values())),
                   "library_statuses": dict(Counter(r["status"] for r in after.values()))}
            print(json.dumps({k: v for k, v in row.items() if k != "batch"}), flush=True)
            if cycle == "repeat":
                assert after == first, "repeat changed results"
                assert row["network_requests"] == row["added_review_records"] == 0, row
            stages.append(row)
            first = after
            (HERE / f"{BATCH}-results.json").write_text(json.dumps({
                "stages": stages,
                "entries": {k: {"status_before": before[k]["status"], "status": after[k]["status"],
                                "fingerprint_before": before[k]["fingerprint"], "fingerprint": after[k]["fingerprint"],
                                "accepted_source": after[k].get("accepted_source"),
                                "accepted_doi": after[k].get("accepted_doi"),
                                "human_review": after[k].get("human_review"),
                                "issues": after[k].get("issues", [])[:3]}
                            for k in sorted(keys | set(rows_by_key))}},
                indent=1, ensure_ascii=False) + "\n")
        export_snapshot(BIB, cache, ROOT / "verification/baseline.jsonl.gz")
        print(base.export_queue(first), flush=True)
        print("PASS: author edits staged and applied; production pipeline for the batch; approvals recorded; "
              "stale-fingerprint approvals refused; repeat made zero requests and zero review writes; accepted "
              "results outside the batch unchanged", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
