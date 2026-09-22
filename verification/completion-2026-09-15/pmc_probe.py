"""Collect a small, cached PMC front-matter probe without changing reviews."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".bibcheck/completion-2026-09-15"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pmcids", nargs="+")
    args = parser.parse_args()
    if len(args.pmcids) > 10 or any(not re.fullmatch(r"PMC[1-9]\d*", p) for p in args.pmcids):
        parser.error("Use at most ten explicit PMC identifiers")
    for pmcid in dict.fromkeys(args.pmcids):
        receipt = WORK / ("pmc-front-" + pmcid + ".json")
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            print(json.dumps(dict(saved, cached=True)), flush=True)
            if saved["status"] == 429 or saved["status"] >= 500:
                raise RuntimeError("Cached PMC provider failure; stopped without retry")
            continue
        time.sleep(3)
        url = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"
        params = {"verb": "GetRecord", "identifier": "oai:pubmedcentral.nih.gov:" + pmcid[3:], "metadataPrefix": "pmc_fm"}
        with requests.get(url, params=params, timeout=(5, 25), allow_redirects=False, stream=True,
                          headers={"User-Agent": "bibcheck/2.0 bibliographic metadata verification",
                                   "Accept-Encoding": "gzip, deflate"}) as response:
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    raise ValueError("PMC metadata exceeds 2 MB")
                chunks.append(chunk)
            body = b"".join(chunks)
            target = WORK / ("pmc-front-" + pmcid + ".xml")
            target.write_bytes(body)
            result = {"pmcid": pmcid, "url": response.url, "status": response.status_code,
                      "retrieved_at": datetime.now(timezone.utc).isoformat(),
                      "content_type": response.headers.get("Content-Type"),
                      "retry_after": response.headers.get("Retry-After"),
                      "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                      "response_file": str(target.relative_to(ROOT)), "cached": False}
            receipt.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result), flush=True)
            if response.status_code == 429 or response.status_code >= 500:
                raise RuntimeError("PMC provider unavailable; stopped without retry")


if __name__ == "__main__":
    main()
