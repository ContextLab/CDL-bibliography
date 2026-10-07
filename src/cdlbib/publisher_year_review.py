"""Corroborate Cambridge print years using the article's own HTML head.

Only the conflicting-date blocker can be resolved. All identity fields, exact
DOI, ISSN, volume and pagination must agree with both registry and publisher.
"""

from copy import deepcopy
import hashlib
import re
from urllib.parse import quote, urlparse

import requests
from .name_parsing import splitname

from .publisher_metadata import PublisherMetadata
from .search_tools import get_source, SourceHTTPError
from .verification import (
    POLICY,
    ProviderError,
    compare_record,
    load_entries,
    normalize_doi,
    now,
    run_lock,
    validate_output_path,
    write_report,
    export_snapshot,
)

FIELDS = {
    "citation_title",
    "citation_author",
    "citation_doi",
    "citation_journal_title",
    "citation_publication_date",
    "citation_online_date",
    "citation_volume",
    "citation_issue",
    "citation_firstpage",
    "citation_lastpage",
    "citation_issn",
}
BLOCKER = "year: conflicting or missing publication dates; select the cited edition explicitly"
HOSTS = {"doi.org", "dx.doi.org", "www.cambridge.org", "cambridge.org"}


def eligible(primary):
    record = primary.get("record", {})
    return (
        primary.get("source") == "crossref"
        and record.get("type") == "journal-article"
        and record.get("publisher")
        in {"Cambridge University Press (CUP)", "Cambridge University Press"}
        and primary.get("issues") == [BLOCKER]
    )


def assess_publisher_year(fields, primary, response):
    metadata = response.get("metadata", {})
    evidence, issues, mapped = {}, [], {}
    try:
        if not eligible(primary):
            raise ValueError(
                "Registry has blockers other than Cambridge publication dates"
            )
        url = urlparse(response["url"])
        if (
            url.scheme != "https"
            or url.hostname not in {"www.cambridge.org", "cambridge.org"}
            or not url.path.startswith("/core/journals/")
        ):
            raise ValueError("Not a Cambridge journal source")
        if not re.fullmatch(r"[a-f0-9]{64}", response.get("document_sha256", "")):
            raise ValueError("Missing source document hash")
        if not isinstance(metadata, dict) or any(
            not isinstance(v, list)
            or any(not isinstance(x, str) or not x.strip() for x in v)
            for v in metadata.values()
        ):
            raise ValueError("Malformed source metadata")

        def one(name):
            values = metadata.get("citation_" + name, [])
            if len(values) != 1:
                raise ValueError("Missing or ambiguous " + name)
            return values[0]

        source = primary["record"]
        doi = normalize_doi(one("doi"))
        if doi != normalize_doi(source["DOI"]):
            raise ValueError("Publisher DOI differs from registry")
        if not set(metadata.get("citation_issn", [])) & set(source.get("ISSN", [])):
            raise ValueError("Journal ISSN does not agree")
        date = one("publication_date")
        if not re.fullmatch(
            r"[1-9]\d{3}(?:/(?:0?[1-9]|1[0-2]))?(?:/(?:0?[1-9]|[12]\d|3[01]))?", date
        ):
            raise ValueError("Unsupported publication date")
        year = int(date.split("/")[0])
        dates = source.get("published-print", {}).get("date-parts", [])
        if len(dates) != 1 or not dates[0] or dates[0][0] != year:
            raise ValueError("Publisher year does not corroborate registry print year")
        people = []
        for author in metadata.get("citation_author", []):
            parts = splitname(author, strict_mode=True)
            people.append(
                {
                    "given": " ".join(parts["first"]),
                    "family": " ".join(parts["von"] + parts["last"]),
                    "suffix": " ".join(parts["jr"]),
                }
            )
        mapped = {
            "DOI": doi,
            "type": "journal-article",
            "title": [one("title")],
            "author": people,
            "container-title": [one("journal_title")],
            "published": {"date-parts": [[year]]},
            "volume": one("volume"),
            "issue": one("issue"),
            "page": one("firstpage") + "-" + one("lastpage"),
            "ISSN": metadata["citation_issn"],
        }
        secondary, secondary_issues = compare_record(fields, mapped)
        evidence = deepcopy(primary["evidence"])
        for field in ("title", "author", "journal", "year", "volume", "pages"):
            if not secondary.get(field, {}).get("match") or not evidence.get(
                field, {}
            ).get("match"):
                raise ValueError("Publisher and registry do not both support " + field)
        # A source cannot disappear a supplied optional field. Publisher/ISBN
        # were checked by Crossref; issue/DOI/ISSN must agree when supplied.
        issues = [
            s
            for s in secondary_issues
            if s.split(":", 1)[0] not in {"publisher", "isbn"}
        ]
        evidence["year"] = dict(
            secondary["year"], source_name="publisher-head", publication_date=date
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        issues = ["Publisher year unresolved: " + str(exc)]
    return {
        "source": "publisher-head",
        "doi": primary["doi"],
        "url": response.get("url"),
        "retrieved_at": response.get("retrieved_at"),
        "document_sha256": response.get("document_sha256"),
        "raw_metadata": {k: v for k, v in metadata.items() if k in FIELDS}
        if isinstance(metadata, dict)
        else {},
        "record": mapped,
        "evidence": evidence,
        "issues": issues,
        "resolved_findings": [BLOCKER] if not issues else [],
    }


def fetch_head(cache, client, doi):
    identity = "cambridge-head-v1:" + normalize_doi(doi)
    cached = cache.response(identity, 30 * 86400)
    if cached is not None and not client.refresh:
        return cached

    class CountedSession:
        def get(self, *args, **kwargs):
            return client.source_request(*args, **kwargs)

    try:
        html, url = get_source(
            CountedSession(), "https://doi.org/" + quote(doi, safe="/"), HOSTS
        )
        parser = PublisherMetadata()
        parser.feed(html)
        result = {
            "url": url,
            "retrieved_at": now(),
            "document_sha256": hashlib.sha256(html.encode()).hexdigest(),
            "metadata": {
                k: v for k, v in parser.source_metadata().items() if k in FIELDS
            },
        }
    except requests.RequestException as exc:
        raise ProviderError("Publisher retrieval failed: " + str(exc)) from exc
    except SourceHTTPError as exc:
        if exc.status == 429 or exc.status >= 500:
            raise ProviderError(
                f"Publisher HTTP {exc.status}; retry later (Retry-After: {exc.retry_after})"
            ) from exc
        result = {
            "url": "https://doi.org/" + doi,
            "retrieved_at": now(),
            "metadata": {},
            "error": str(exc),
        }
    except ValueError as exc:
        # A refusal/unsupported redirect is an explicit, resumable evidence gap.
        result = {
            "url": "https://doi.org/" + doi,
            "retrieved_at": now(),
            "metadata": {},
            "error": str(exc),
        }
    cache.save_response(identity, result)
    return result


def run_publisher_year_review(
    filename, cache, client, report, limit=None, snapshot=None, keys=None
):
    from .auto_review import select_result

    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    with run_lock(cache):
        entries = load_entries(filename)
        if keys is not None and (not keys or set(keys) - entries.keys()):
            raise ValueError("Publisher review keys must name existing citations")
        checked = 0
        try:
            for key, entry in entries.items():
                if keys is not None and key not in keys:
                    continue
                previous = cache.get(filename, entry)
                if (
                    not previous
                    or previous["status"] != "needs_review"
                    or previous.get("external_evidence")
                ):
                    continue
                if previous.get("auto_review", {}).get("publisher_year_policy") == "1":
                    continue
                targets = {
                    c["doi"]: c for c in previous.get("candidates", []) if eligible(c)
                }
                if not targets:
                    continue
                if limit is not None and checked >= limit:
                    break
                candidates = list(previous["candidates"])
                attempts = list(previous.get("attempts", []))
                for doi, primary in targets.items():
                    response = fetch_head(cache, client, doi)
                    attempts.append(
                        {
                            "source": "publisher-head",
                            "doi": doi,
                            "url": response["url"],
                            "error": response.get("error"),
                        }
                    )
                    candidates.append(
                        assess_publisher_year(entry["fields"], primary, response)
                    )
                result = select_result(entry["fields"], candidates, attempts)
                for name in ("research_attempt", "discovery_review"):
                    if name in previous:
                        result[name] = previous[name]
                result["auto_review"] = dict(
                    previous.get("auto_review", {}),
                    policy=POLICY,
                    publisher_year_policy="1",
                )
                cache.put(filename, entry, result)
                checked += 1
                print(
                    f"Publisher print-year check {checked}: {key}: {result['status']}; requests: {client.requests}",
                    flush=True,
                )
        finally:
            results = write_report(filename, cache, report)
            if snapshot:
                export_snapshot(filename, cache, snapshot)
    return results
