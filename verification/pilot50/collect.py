"""Collect paced, cached primary-source evidence for the frozen 50-entry audit.

No bibliography edits, model calls, or citation approvals. Publisher failures
are recorded; challenges are not bypassed. Existing registry evidence is kept
distinct from publisher HTML and article front matter.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from publisher_metadata import PublisherMetadata
from search_tools import get_source
from verification import normalize_doi

HOSTS = {
    "doi.org",
    "dx.doi.org",
    "www.nature.com",
    "nature.com",
    "link.springer.com",
    "link.springerlink.com",
    "www.sciencedirect.com",
    "sciencedirect.com",
    "linkinghub.elsevier.com",
    "api.elsevier.com",
    "journals.sagepub.com",
    "onlinelibrary.wiley.com",
    "www.pnas.org",
    "pnas.org",
    "www.jneurosci.org",
    "jneurosci.org",
    "academic.oup.com",
    "dl.acm.org",
    "ieeexplore.ieee.org",
    "journals.plos.org",
    "www.frontiersin.org",
    "frontiersin.org",
    "www.jle.com",
    "jle.com",
    "www.cambridge.org",
    "cambridge.org",
    "direct.mit.edu",
    "thejns.org",
    "www.thejns.org",
    "learnmem.cshlp.org",
    "www.cell.com",
    "cell.com",
    "www.tandfonline.com",
    "pubmed.ncbi.nlm.nih.gov",
    "pmc.ncbi.nlm.nih.gov",
    "europepmc.org",
    "www.ebi.ac.uk",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / ".bibcheck/local-validation-yhyn7ze1/report.jsonl",
        help="Original report used to freeze this pilot, or another explicit source report",
    )
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name("manifest.json").read_text())
    chosen = {r["key"]: r for r in manifest["entries"]}
    directory = ROOT / ".bibcheck/pilot50/sources"
    directory.mkdir(parents=True, exist_ok=True)
    with args.report.open() as f:
        for line in f:
            result = json.loads(line)
            if result["key"] not in chosen:
                continue
            row = chosen[result["key"]]
            supplemental = [
                c
                for c in result.get("candidates", [])
                if c.get("doi")
                and normalize_doi(c["doi"]) == normalize_doi(row["candidate_doi"])
                and c.get("source") in ("europepmc", "pmc-jats")
            ]
            prior = directory / (row["key"] + "-prior.json")
            if not prior.exists():
                prior.write_text(json.dumps(supplemental, ensure_ascii=False, indent=2))
    session = requests.Session()
    outcomes = []
    for i, row in enumerate(manifest["entries"], 1):
        path = directory / (row["key"] + "-publisher.json")
        if path.exists():
            result = json.loads(path.read_text())
            print(f"{i}/50 {row['key']}: cached {result['status']}", flush=True)
        else:
            url = "https://doi.org/" + quote(row["candidate_doi"], safe="/")
            try:
                html, final = get_source(session, url, HOSTS)
                parser = PublisherMetadata()
                parser.feed(html)
                body = directory / (row["key"] + ".html")
                body.write_text(html, encoding="utf-8")
                result = {
                    "status": "retrieved",
                    "url": final,
                    "sha256": hashlib.sha256(html.encode()).hexdigest(),
                    "metadata": parser.source_metadata(),
                }
            except (requests.RequestException, ValueError) as exc:
                result = {"status": "unavailable", "url": url, "error": str(exc)}
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(
                f"{i}/50 {row['key']}: {result['status']}; {result.get('url')}; {result.get('error', '')}",
                flush=True,
            )
        outcomes.append({"key": row["key"], **result})
    (directory.parent / "collection.json").write_text(
        json.dumps(outcomes, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
