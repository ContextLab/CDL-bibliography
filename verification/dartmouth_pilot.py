"""Run one live citation research attempt, preserving safe diagnostics locally.

Usage: python verification/dartmouth_pilot.py --key VaswEtal17
The bibliography and verification database are read only. Findings are saved under
the ignored .bibcheck/debug directory for inspection before a production batch.
"""

import argparse
import json
from pathlib import Path
import sys
import tempfile

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
import dartmouth_research_adapter as adapter
from research import download_discovered_pdf, extract_pages, validate_findings
from search_tools import WebSearch
from verification import load_entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", default="VaswEtal17")
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--pages", type=int, choices=range(1, 6), default=5)
    parser.add_argument(
        "--landing-url",
        help="Known publisher landing page; discovery still fetches its metadata",
    )
    parser.add_argument(
        "--source-url",
        help="An already retrieved PDF URL for an isolated extraction test",
    )
    parser.add_argument(
        "--backend", choices=["duckduckgo", "europepmc"], default="duckduckgo"
    )
    args = parser.parse_args()
    entry = load_entries("cdl.bib")[args.key]
    root = Path(".bibcheck/debug")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    directory = Path(tempfile.mkdtemp(prefix="dartmouth-", dir=root))
    secret, model = adapter.configuration(adapter.os.environ)

    def save(name, value):
        # API diagnostics contain response content only, never request headers.
        # Redact the credential as a final guard before any disk write.
        def redact(item):
            if isinstance(item, str):
                return item.replace(secret, "[REDACTED]")
            if isinstance(item, dict):
                return {redact(k): redact(v) for k, v in item.items()}
            if isinstance(item, list):
                return [redact(v) for v in item]
            return item

        path = directory / name
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2).replace(
                secret, "[REDACTED]"
            )
            + "\n"
        )
        path.chmod(0o600)

    class Session(requests.Session):
        calls = 0

        def post(self, url, **kwargs):
            self.calls += 1
            print(f"Dartmouth request {self.calls}", flush=True)
            response = super().post(url, **kwargs)
            try:
                body = response.json()
            except ValueError:
                body = {"invalid_json": True}
            save(
                f"response-{self.calls}.json",
                {
                    "http_status": response.status_code,
                    "error": body.get("error", body.get("detail")),
                    "choices": [
                        {
                            "finish_reason": c.get("finish_reason"),
                            "message": {"content": c.get("message", {}).get("content")},
                        }
                        for c in body.get("choices", [])
                    ],
                    "usage": body.get("usage"),
                    "id": body.get("id"),
                },
            )
            print(
                f"Dartmouth response {self.calls}: HTTP {response.status_code}",
                flush=True,
            )
            return response

    session = Session()
    print("Diagnostics: " + str(directory), flush=True)
    try:
        adapter.check_model(session)
        print("Model available: " + model, flush=True)
        hosts = [
            "arxiv.org",
            "papers.nips.cc",
            "papers.neurips.cc",
            "proceedings.neurips.cc",
            "aclanthology.org",
            "europepmc.org",
            "pmc.ncbi.nlm.nih.gov",
            "www.ncbi.nlm.nih.gov",
        ] + args.allow_host
        if args.source_url:
            finding = {
                "pdf_url": args.source_url,
                "landing_url": args.source_url,
                "uncertainties": [
                    "Explicitly supplied PDF; discovery not exercised in this run"
                ],
                "provider_trace": {"discovery": "explicit-pilot-source"},
            }
        else:
            search = WebSearch(args.backend)
            try:
                finding = adapter.run(
                    {
                        "phase": "discover",
                        "entry": entry["fields"],
                        "previous_evidence": {"candidates": [{"url": args.landing_url}]}
                        if args.landing_url
                        else {},
                        "allowed_pdf_hosts": hosts,
                    },
                    session=session,
                    searcher=search,
                )
            finally:
                search.close()
        save("discovery.json", finding)
        print("Retrieved PDF candidate: " + finding["pdf_url"], flush=True)
        pdf, sha, final_url, downloads = download_discovered_pdf(
            finding, hosts, directory
        )
        pages = extract_pages(pdf)[: args.pages]
        save("pages.json", pages)
        extracted = adapter.run(
            {"phase": "extract", "entry": entry["fields"], "pages": pages},
            session=session,
        )
        validate_findings(extracted, pages)
        result = {
            "key": args.key,
            "fingerprint": entry["fingerprint"],
            "model": model,
            "pdf_sha256": sha,
            "download_attempts": downloads,
            "pdf_url": final_url,
            "discovery": finding,
            "extraction": extracted,
            "quote_check": "passed",
            "status": "needs_review",
        }
        save("result.json", result)
        print(
            "Live evidence collected; exact PDF quotations passed. Fields: "
            + ", ".join(extracted["fields"]),
            flush=True,
        )
    except Exception as exc:
        message = str(exc).replace(secret, "[REDACTED]")
        save("failure.json", {"type": type(exc).__name__, "reason": message})
        print(
            "Pilot unresolved: " + type(exc).__name__ + ": " + message[:500], flush=True
        )
        return 2
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
