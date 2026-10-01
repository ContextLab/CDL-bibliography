"""Broaden source discovery without relaxing existing metadata acceptance rules."""

from auto_review import reassess, target_dois
from verification import (
    assess_candidates,
    current_results,
    load_entries,
    normalized,
    run_lock,
    validate_output_path,
    write_report,
)


def run_discovery_review(filename, cache, client, report, limit=10, keys=None):
    validate_output_path(filename, report, cache)
    with run_lock(cache):
        entries = load_entries(filename)
        if keys is not None and (not keys or set(keys) - entries.keys()):
            raise ValueError("Discovery keys must name existing citations")
        selected = entries if keys is None else {k: entries[k] for k in keys}
        checked = 0
        try:
            for key, entry in selected.items():
                previous = cache.get(filename, entry)
                if (
                    not previous
                    or previous["status"] != "needs_review"
                    or previous.get("external_evidence")
                    or previous.get("discovery_review", {}).get("policy") == "1"
                ):
                    continue
                if checked >= limit:
                    break
                title = entry["fields"].get("title", "")
                try:
                    title = normalized(title)
                except ValueError:
                    pass  # Discovery can search markup; acceptance still rejects it.
                if not title.strip():
                    continue
                # One focused query with twenty candidates, instead of the
                # original five-item bibliographic search. No concurrent calls.
                response = client.get(
                    "https://api.crossref.org/works",
                    {
                        "query.title": title[:1500],
                        "rows": 20,
                    },
                )
                found = assess_candidates(entry["fields"], response)
                combined = dict(
                    previous, candidates=previous.get("candidates", []) + found
                )
                combined["attempts"] = previous.get("attempts", []) + [
                    {
                        "source": "crossref-expanded-title",
                        "url": response["url"],
                        "retrieved_at": response["retrieved_at"],
                        "candidates": len(found),
                    }
                ]
                result = reassess(
                    entry, combined
                )  # Recompute from documentary records.
                # New title-search candidates need their own secondary lookup.
                # Retain the DOI checkpoint for old candidates rather than
                # letting a prior entry-wide flag suppress the new evidence.
                if set(target_dois(result)) - set(target_dois(previous)):
                    checkpoint = dict(result.get("auto_review", {}))
                    checked_dois = set(checkpoint.get("epmc_checked_dois", []))
                    if checkpoint.get("epmc_checked"):
                        checked_dois.update(target_dois(previous))
                    checkpoint.update(
                        epmc_checked=False, epmc_checked_dois=sorted(checked_dois)
                    )
                    checkpoint.pop("fulltext_checked", None)
                    checkpoint.pop("publisher_year_policy", None)
                    result["auto_review"] = checkpoint
                result["discovery_review"] = {"policy": "1", "checked": True}
                cache.put(filename, entry, result)
                checked += 1
                print(
                    f"Expanded discovery {checked}: {key}: {result['status']}",
                    flush=True,
                )
        finally:
            write_report(filename, cache, report)
    return current_results(filename, cache)
