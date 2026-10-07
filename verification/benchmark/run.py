"""Reevaluate frozen source records; never use saved match flags or an LLM vote."""

import json
from pathlib import Path
import sys

from cdlbib.auto_review import reassess


def run():
    data = json.loads((Path(__file__).parent / "cases.json").read_text())
    results = []
    for case in data["cases"]:
        result = reassess({"fields": case["fields"]}, case["previous"])
        results.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "expected": case["expected"],
                "actual": result["status"],
                "passed": result["status"] == case["expected"],
            }
        )
    report = {
        "works": data["works"],
        "cases": len(results),
        "passed": sum(r["passed"] for r in results),
        "false_acceptances": sum(
            r["actual"] == "metadata_verified" and r["expected"] != "metadata_verified"
            for r in results
        ),
        "missed_matches": sum(
            r["expected"] == "metadata_verified" and r["actual"] != "metadata_verified"
            for r in results
        ),
        "results": results,
    }
    return report


if __name__ == "__main__":
    report = run()
    (Path(__file__).parent / "results.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "results"}))
    for result in report["results"]:
        if not result["passed"]:
            print(result)
    sys.exit(0 if report["passed"] == report["cases"] else 1)
