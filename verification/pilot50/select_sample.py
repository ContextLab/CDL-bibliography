"""Freeze a reproducible, stratified sample before source/model evaluation."""

from collections import defaultdict
import hashlib
import json
from pathlib import Path


def main():
    groups = defaultdict(list)
    report = Path(".bibcheck/local-validation-yhyn7ze1/report.jsonl")
    with report.open() as stream:
        for line in stream:
            result = json.loads(line)
            if result["status"] != "needs_review":
                continue
            candidates = [
                c
                for c in result.get("candidates", [])
                if c.get("source") == "crossref"
                and all(
                    c.get("evidence", {}).get(f, {}).get("match")
                    for f in ("title", "author")
                )
            ]
            if not candidates:
                continue
            candidate = min(candidates, key=lambda c: len(c["issues"]))
            if len(candidate["issues"]) != 1:
                continue
            groups[candidate["issues"][0]].append(
                {
                    "key": result["key"],
                    "fingerprint": result["fingerprint"],
                    "entry": result["entry"],
                    "blocker": candidate["issues"][0],
                    "candidate_doi": candidate["doi"],
                    "cached_candidate": candidate,
                }
            )
    total = sum(map(len, groups.values()))
    remaining = 50 - len(groups)
    quotas = {g: 1 + remaining * len(rows) // total for g, rows in groups.items()}
    for g in sorted(groups, key=lambda g: (-(remaining * len(groups[g]) % total), g))[
        : 50 - sum(quotas.values())
    ]:
        quotas[g] += 1
    sample = []
    for group in sorted(groups):
        rows = sorted(
            groups[group],
            key=lambda row: hashlib.sha256(
                ("pilot50-v1:" + row["key"]).encode()
            ).hexdigest(),
        )
        sample.extend(rows[: quotas[group]])
    assert len(sample) == 50
    output = Path(__file__).with_name("manifest.json")
    if output.exists():
        raise SystemExit("Sample already frozen; refusing to replace it")
    output.write_text(
        json.dumps(
            {
                "schema": 1,
                "selection": "One per blocker category plus proportional largest-remainder allocation; SHA256(pilot50-v1:key) ordering",
                "eligible_entries": total,
                "quotas": quotas,
                "entries": sample,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    for i, row in enumerate(sample, 1):
        print(
            i,
            row["key"],
            row["candidate_doi"],
            row["blocker"],
            row["entry"]["title"],
            sep=" | ",
        )


if __name__ == "__main__":
    main()
