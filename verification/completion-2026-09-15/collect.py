"""Paced collection for unresolved entries, with frozen discovery batches."""

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
import time
from urllib.parse import quote, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import ACCEPTED, Cache, RECORD_FIELDS, current_results, export_snapshot, load_entries
from auto_review import alias_targets, run_auto_review
from discovery_review import run_discovery_review
from fulltext_review import run_fulltext_review
from publisher_year_review import run_publisher_year_review
from reassess import export_queue

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck" / HERE.name
spec = importlib.util.spec_from_file_location("earlier", HERE.parent / "resolution-2026-09-15/run.py")
earlier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(earlier)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["secondary", "discovery", "aliases", "notices", "notice-bodies", "notice-xml", "alias-probe", "publisher-probe", "elsevier-year-probe", "wiley-head-probe"])
    parser.add_argument("--batch", default="001")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    if not args.batch.isalnum() or not 1 <= args.limit <= 6422:
        parser.error("Use an alphanumeric batch name and a limit from 1 to 6422")
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        client = earlier.client_for(cache)
        if args.stage == "wiley-head-probe":
            from publisher_metadata import PublisherMetadata
            from search_tools import get_source, SourceHTTPError
            from verification import now
            import hashlib
            import requests
            hosts = {"onlinelibrary.wiley.com", "bpspsychub.onlinelibrary.wiley.com"}
            targets = {"Cohe90": "https://bpspsychub.onlinelibrary.wiley.com/doi/abs/10.1111/j.2044-8295.1990.tb02362.x",
                       "HamaEtal08": "https://onlinelibrary.wiley.com/doi/abs/10.1002/ana.21295"}
            class CountedSession:
                def get(self, *a, **kw):
                    return client.source_request(*a, **kw)
            path = HERE / "wiley-head-probe.json"
            observed = json.loads(path.read_text()) if path.exists() else {}
            for key, url in targets.items():
                if key in observed:
                    print(key + ": saved probe reused", flush=True)
                    continue
                item = {"url": url, "retrieved_at": now()}
                try:
                    html, final = get_source(CountedSession(), url, hosts)
                    parser = PublisherMetadata(); parser.feed(html)
                    item.update(url=final, document_sha256=hashlib.sha256(html.encode()).hexdigest(), metadata=parser.source_metadata())
                    (WORK / (key + "-publisher-head.html")).write_text(html)
                except (SourceHTTPError, ValueError) as exc:
                    item["error"] = str(exc)
                except requests.RequestException:
                    raise  # A transport failure is retryable, never a saved absence.
                observed[key] = item
                path.write_text(json.dumps(observed, indent=2) + "\n")
                print(key + ": " + json.dumps(item), flush=True)
            return
        if args.stage == "elsevier-year-probe":
            from publisher_corrections import fetch_elsevier_metadata
            result = fetch_elsevier_metadata(cache, client, "10.1016/s0028-3932(98)00044-x")
            (HERE / "elsevier-year-probe.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({k: v for k, v in result.items() if k != "raw_xml"}), flush=True)
            return
        if args.stage in {"notice-bodies", "notice-xml"}:
            results = []
            for notice in json.loads((HERE / "notice-records.json").read_text()):
                for link in notice["record"].get("link", []):
                    if link.get("content-type") != ("text/xml" if args.stage == "notice-xml" else "text/plain"):
                        continue
                    url = link["URL"]
                    parsed = urlparse(url)
                    assert parsed.scheme == "https" and parsed.hostname == "api.elsevier.com"
                    response = client.source_request(url, timeout=(10, 40), allow_redirects=False)
                    filename = args.stage + "-" + str(len(results) + 1) + ".txt"
                    (WORK / filename).write_text(response.text)
                    results.append({"doi": notice["doi"], "url": url,
                                    "http_status": response.status_code,
                                    "content_type": response.headers.get("Content-Type"),
                                    "local_response": filename})
                    print(json.dumps(results[-1]), flush=True)
            (HERE / (args.stage + "-results.json")).write_text(json.dumps(results, indent=2) + "\n")
            return
        if args.stage == "publisher-probe":
            for slug in ["nn.3138", "nrn756", "nrn1105"]:
                url = "https://www.nature.com/articles/" + slug + ".ris"
                response = client.source_request(url, timeout=(10, 40), allow_redirects=False)
                for _ in range(4):
                    if response.status_code not in (301, 302, 303, 307, 308):
                        break
                    target = urljoin(response.url, response.headers.get("Location", ""))
                    parsed = urlparse(target)
                    if parsed.scheme != "https" or parsed.hostname not in {"nature.com", "www.nature.com", "idp.nature.com"}:
                        break
                    response = client.source_request(target, timeout=(10, 40), allow_redirects=False)
                (WORK / (slug + ".ris-response.txt")).write_text(response.text)
                print(json.dumps({"url": url, "status": response.status_code,
                                  "content_type": response.headers.get("Content-Type"),
                                  "citation": response.text[:3000] if response.text.lstrip().startswith("TY ") else "Not a RIS citation"}), flush=True)
            return
        if args.stage == "alias-probe":
            doi = "10.1037//0882-7974.13.4.597"
            response = client.source_request("https://api.crossref.org/works/" + quote(doi, safe=""),
                                             timeout=(10, 40), allow_redirects=False)
            try:
                body = response.json()
            except ValueError:
                body = {"non_json_body": response.text[:500]}
            record = body.get("message", {})
            observed = {"requested_doi": doi, "http_status": response.status_code,
                        "location": response.headers.get("Location"), "body_keys": list(body),
                        "record": {k: v for k, v in record.items() if k in RECORD_FIELDS or k == "alias"}}
            location = urljoin("https://api.crossref.org", observed["location"] or "")
            assert urlparse(location).hostname == "api.crossref.org"
            prime = client.get(location)
            observed["prime_record"] = prime["body"]["message"]
            (HERE / "alias-observation.json").write_text(json.dumps(observed, indent=2) + "\n")
            print(json.dumps(observed), flush=True)
            return
        if args.stage == "notices":
            records = []
            for doi in ["10.1016/j.brainres.2012.06.039", "10.1016/0013-4694(96)80250-1"]:
                response = client.crossref_doi(doi)
                record = response["body"].get("message", {})
                records.append({"doi": doi, "request_url": response["url"], "retrieved_at": response["retrieved_at"],
                                "record": {k: v for k, v in record.items() if k in RECORD_FIELDS}})
                print("Correction notice metadata collected: " + doi, flush=True)
            (HERE / "notice-records.json").write_text(json.dumps(records, indent=2) + "\n")
            return
        before = current_results("cdl.bib", cache)
        entries = load_entries("cdl.bib")
        manifest_path = HERE / f"{args.stage}-{args.batch}-manifest.json"
        if not manifest_path.exists():
            pool = [k for k, r in before.items() if r["status"] == "needs_review" and not r.get("external_evidence")
                    and (args.stage != "discovery" or not r.get("discovery_review", {}).get("checked"))]
            if args.stage == "discovery":
                # Missing identity first; still retain all entry types in scope.
                pool.sort(key=lambda k: (any(c.get("evidence", {}).get("title", {}).get("match") for c in before[k].get("candidates", [])), k))
                pool = pool[:args.limit]
            elif args.stage == "aliases":
                pool = [k for k in pool if alias_targets(before[k])][:args.limit]
            manifest_path.write_text(json.dumps({"stage": args.stage, "entries": {k: entries[k]["fingerprint"] for k in pool}}, indent=2) + "\n")
        manifest = json.loads(manifest_path.read_text())
        keys = set(manifest["entries"])
        assert all(entries[k]["fingerprint"] == fp for k, fp in manifest["entries"].items())
        stages = []
        for cycle in ("run", "repeat"):
            start, calls = time.monotonic(), client.requests
            count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
            report = WORK / f"{args.stage}-{args.batch}-report.jsonl"
            if args.stage == "discovery":
                print(f"{cycle}: expanded discovery for {len(keys)} frozen entries", flush=True)
                run_discovery_review("cdl.bib", cache, client, report, limit=len(keys), keys=keys)
            print(cycle + ": DOI-linked secondary records", flush=True)
            run_auto_review("cdl.bib", cache, report, client, keys=keys)
            print(cycle + ": publisher article front matter", flush=True)
            run_fulltext_review("cdl.bib", cache, client, report, keys=keys)
            print(cycle + ": publisher issue dates", flush=True)
            after = run_publisher_year_review("cdl.bib", cache, client, report, keys=keys)
            assert all(after[k] == r for k, r in before.items() if r["status"] in ACCEPTED)
            stage = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                     "network_requests": client.requests - calls,
                     "review_writes": cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] - count,
                     "library_statuses": dict(Counter(r["status"] for r in after.values())),
                     "batch_statuses": dict(Counter(after[k]["status"] for k in keys))}
            print(json.dumps(stage), flush=True)
            stages.append(stage)
            if cycle == "repeat":
                assert after == first
                assert stage["network_requests"] == stage["review_writes"] == 0
            first = after
            (HERE / f"{args.stage}-{args.batch}-results.json").write_text(json.dumps(stages, indent=2) + "\n")
        export_snapshot("cdl.bib", cache, ROOT / "verification/baseline.jsonl.gz")
        export_queue(entries, after)
        print("PASS: frozen batch complete; repeat zero requests and writes", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
