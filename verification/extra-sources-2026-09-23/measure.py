"""Measure new metadata routes on the Phase-0 leftovers (2026-09-23).

Targets: the 477 'article-no-record' entries and the 460 'individual' entries
of verification/phase0-2026-09-22/groups.json.

Reads cdl.bib (working tree, re-read at the end because another agent is
applying batches) and the main verification cache READ-ONLY (mode=ro).
Writes only: results.json and groups.json next to this script, and the
response cache .bibcheck/extra-sources.sqlite3. Every bibcheck module except
extra_sources.py is loaded from the committed HEAD.

Usage (repository root):
    .venv/bin/python verification/extra-sources-2026-09-23/measure.py --pilot
    .venv/bin/python verification/extra-sources-2026-09-23/measure.py            # all 937
    .venv/bin/python verification/extra-sources-2026-09-23/measure.py --offline  # zero-request repeat
    .venv/bin/python verification/extra-sources-2026-09-23/measure.py --keys KEY ... # print rows only
"""

from __future__ import annotations

import argparse
import atexit
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
os.chdir(ROOT)  # helpers.py reads bibcheck/*.txt relative to the repository root
SEED = 20260923
S2_FALLBACK = True  # set by --s2-always
MAIN_CACHE = ROOT / ".bibcheck/verification.sqlite3"
OWN_CACHE = ROOT / ".bibcheck/extra-sources.sqlite3"
PHASE0 = ROOT / "verification/phase0-2026-09-22/groups.json"


def head_modules():
    env = dict(os.environ, DEVELOPER_DIR="/Library/Developer/CommandLineTools")
    target = Path(tempfile.mkdtemp(prefix="extra-sources-modules-"))
    atexit.register(shutil.rmtree, target, True)
    names = subprocess.run(["git", "ls-tree", "--name-only", "HEAD", "bibcheck/"], cwd=ROOT, env=env,
                           check=True, capture_output=True, text=True).stdout.split()
    for name in names:
        body = subprocess.run(["git", "show", "HEAD:" + name], cwd=ROOT, env=env, check=True,
                              capture_output=True).stdout
        (target / Path(name).name).write_bytes(body)
    shutil.copy(ROOT / "bibcheck/extra_sources.py", target / "extra_sources.py")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()
    return target, head


MODULES, HEAD = head_modules()
sys.path.insert(0, str(MODULES))
import extra_sources as xs  # noqa: E402
from verification import load_entries  # noqa: E402

NON_JOURNAL = re.compile(r"neural information processing|\bnips\b|machine learning research|"
                         r"proceedings(?! of the national academy)(?! of the royal society)|"
                         r"conference|workshop|arxiv|biorxiv|psyarxiv|medrxiv|zenodo|ssrn|osf|preprint|"
                         r"\bicml\b|\biclr\b|cognitive science society|annual meeting|abstracts?\b|"
                         r"technical report|github", re.I)
ABSTRACT = re.compile(r"(?<!dissertation )abstracts?\b|society for neuroscience", re.I)


def targets():
    groups = json.loads(PHASE0.read_text())["groups"]
    out = {}
    for g in groups:
        if g["group"] == "article-no-record" or g["decision_type"] == "individual":
            for key in g["keys"]:
                out[key] = g["group"]
    return out


def pilot_keys(target, entries, n=40):
    """20 no-record + 20 individual, stratified (era for no-record; phase-0
    group for individual), seeded."""
    rng = random.Random(SEED)
    chosen = []
    norec = sorted(k for k, g in target.items() if g == "article-no-record" and k in entries)
    def era(k):
        y = entries[k]["fields"].get("year", "")
        return "pre1960" if y < "1960" else ("1960-1999" if y < "2000" else "2000+")
    strata = defaultdict(list)
    for k in norec:
        strata[era(k)].append(k)
    quota = {"pre1960": 5, "1960-1999": 7, "2000+": 8}
    for s, keys in sorted(strata.items()):
        chosen += rng.sample(keys, min(quota[s], len(keys)))
    individual = defaultdict(list)
    for k, g in sorted(target.items()):
        if g != "article-no-record" and k in entries:
            individual[g].append(k)
    total = sum(len(v) for v in individual.values())
    picks = []
    for g, keys in sorted(individual.items(), key=lambda x: -len(x[1])):
        picks += rng.sample(keys, max(1, round(20 * len(keys) / total)))
    chosen += picks[:20]
    return chosen


def latest_review(db, key):
    row = db.execute("SELECT result FROM reviews WHERE bibliography=? AND key=? ORDER BY id DESC LIMIT 1",
                     (str((ROOT / "cdl.bib").resolve()), key)).fetchone()
    return json.loads(row[0]) if row else None


def route_status(route, row):
    """nothing / error / lead (found something) / decisive (outcome came via it)."""
    log = row["routes"].get(route)
    if log is None:
        return "not-run"
    if "skipped" in log:
        return "skipped-fallback"
    if "error" in log:
        return "not-requested-blocked" if ": not requested (" in log["error"] else "error"
    decisive = route in row.get("decisive_routes", [])
    if decisive:
        return "decisive"
    if route == "pubmed":
        found = bool(log.get("pmids"))
    elif route == "epmc-apa":
        found = bool(log.get("found"))
        if not log.get("queried"):
            return "not-applicable"
    else:
        found = bool(log.get("leads"))
    return "lead" if found else "nothing"


def process(client, entry, previous, group):
    fields = entry["fields"]
    row = {"key": entry["key"], "phase0_group": group, "fingerprint": entry["fingerprint"],
           "year": fields.get("year"), "journal": fields.get("journal", "")}
    if not previous:
        return dict(row, outcome="no-saved-review", routes={})
    if previous.get("status") != "needs_review":
        return dict(row, outcome="status-" + previous.get("status", "?"), routes={})
    gathered = xs.gather(client, entry, previous, s2_fallback_only=S2_FALLBACK)
    new, pubmed_only, provenance, errors, crossref_found, records = xs.confirm(client, entry, previous, gathered)
    if gathered.get("apa_found"):
        gathered["log"]["epmc-apa"]["found"] = gathered["apa_found"]
    verdict = xs.judge(entry, previous, new, pubmed_only)
    row.update(routes=gathered["log"], confirm_errors=errors,
               crossref_confirmed=crossref_found,
               leads=[{k: v for k, v in lead.items() if k in ("source", "doi", "pmid", "title", "year", "type")}
                      for lead in gathered["leads"]],
               pubmed_records={p: {k: r[k] for k in ("title", "journal_title", "year", "volume", "pages",
                                                     "dois", "publication_types")}
                               for p, r in list(pubmed_only.items())[:5]},
               new_candidates=sorted({c["doi"] for c in new if c.get("doi")}),
               **verdict)
    found = [xs.record_summary(fields, rec, doi) for doi, rec in records.items()]
    for pmid, raw in pubmed_only.items():
        if not xs.medline_is_notice(raw):
            found.append(xs.record_summary(fields, xs.medline_record(raw, fields.get("journal")), "pmid:" + pmid))
    row["found_records"] = found
    decisive = set()
    if verdict["outcome"] in {"verify", "proposal"}:
        if verdict.get("via") == "pubmed-only":
            decisive |= provenance.get("pmid:" + verdict["pmid"], set())
        elif verdict.get("doi") and not verdict.get("without_new_evidence"):
            doi = verdict["doi"].lower()
            decisive |= provenance.get(doi, set())
            twin = xs.apa_double_slash(doi) if doi.startswith("10.1037/") else None
            decisive |= provenance.get(twin, set()) if twin else set()
            if doi.startswith("10.1037//"):
                decisive |= provenance.get("10.1037/" + doi[len("10.1037//"):], set())
    row["decisive_routes"] = sorted(decisive)
    if verdict["outcome"] == "held" and (new or pubmed_only or gathered["leads"]):
        row["outcome"] = "held-with-new-evidence"
    elif verdict["outcome"] == "held":
        row["outcome"] = "nothing-new"
    if verdict.get("without_new_evidence"):
        row["outcome"] = verdict["outcome"] + "-without-new-evidence"
    return row


# --------------------------------------------------------------------------
# Grouping of what remains


def group_for(row, fields):
    """Coarse, one-decision groups. Order matters: the first match wins."""
    journal = fields.get("journal", "")
    year = fields.get("year", "")
    outcome = row["outcome"]
    pm = (row.get("pubmed_only") or {})
    explain = row.get("s1_explain") or {}
    issues = " ".join(row.get("resolver_issues") or [])
    if ABSTRACT.search(journal):
        return "conference-abstract-typed-article"
    if not journal.strip() or NON_JOURNAL.search(journal):
        return "non-journal-venue-typed-article"
    if pm.get("outcome") == "ambiguous" or explain.get("reason") == "ambiguous-identity" \
            or "Multiple fully matching" in issues:
        return "ambiguous-identity"
    reason = pm.get("reason") or explain.get("reason") or ""
    detail = (pm.get("detail") or explain.get("detail") or "")
    if row["phase0_group"] != "article-no-record":
        return {
            "article-more-given-names": "citation-byline-more-detailed-than-source",
            "article-author-count": "author-count-differs",
            "article-too-many-fields": "identified-record-differs-in-3plus-fields",
            "article-sources-disagree": "authoritative-sources-disagree",
            "coordinates-identity": "identified-record-value-held",
            "article-value-held": "identified-record-value-held",
            "article-would-not-verify": "identified-record-value-held",
            "article-ambiguous": "ambiguous-identity",
        }.get(row["phase0_group"], "individual-other")
    if "byline has detail" in detail or (pm.get("outcome") == "held" and "author" in (pm.get("fields") or [])
                                         and len(pm.get("fields") or []) == 1):
        return "citation-byline-more-detailed-than-source"
    plausible = [r for r in row.get("found_records", []) if r.get("identity_rule")
                 or (r["title_similarity"] >= 0.8 and r["first_author_match"])]
    if plausible:
        return "record-found-identity-rule-not-met"
    if outcome == "held-with-new-evidence" and pm.get("outcome") == "held":
        if reason == "too-many-fields":
            return "identified-record-differs-in-3plus-fields"
        return "identified-record-value-held"
    if year and year < "1960":
        return "pre-1960-no-indexed-record"
    return "no-record-in-any-source-1960-onward"


def best_record(row):
    found = [r for r in row.get("found_records", []) if r.get("identity_rule")
             or (r["title_similarity"] >= 0.8 and r["first_author_match"])]
    if not found:
        return None
    best = min(found, key=lambda r: (len(r["differs"]), -r["title_similarity"]))
    return {k: best[k] for k in ("id", "type", "title", "title_similarity", "differs")}


def subpattern(row, fields):
    """Finer label inside a group (reported, not a separate decision)."""
    if row.get("group") == "record-found-identity-rule-not-met":
        best = best_record(row) or {}
        differs = set(best.get("differs", []))
        if not fields.get("volume") and not fields.get("pages"):
            return "citation lacks volume and pages (online-first form)"
        if differs <= {"title", "journal"} and "title" in differs and best.get("title_similarity", 0) >= 0.95:
            return "title differs only in case/typography or an omitted subtitle"
        if differs & {"volume", "pages", "number"} and "year" in differs:
            return "different year and coordinates (another edition/reprint or wrong record)"
        if "author" in differs:
            return "byline differs (+ other fields)"
        return "+".join(sorted(differs)) or "other"
    if row.get("group") in {"pre-1960-no-indexed-record", "no-record-in-any-source-1960-onward"}:
        return "aggregator holds it (lead only)" if row.get("leads") else "no source at all"
    return row.get("phase0_group", "")


GROUP_TEXT = {
    "conference-abstract-typed-article": (
        "Meeting abstracts typed @article (Society for Neuroscience Abstracts and other abstract volumes).",
        "User decision 2026-09-22: flag for removal; confirm the list once."),
    "non-journal-venue-typed-article": (
        "Venues with no journal DOI or MEDLINE record, typed @article: conference proceedings (NeurIPS, "
        "CogSci), JMLR, preprints (arXiv, bioRxiv, PsyArXiv), Zenodo, or an empty journal field.",
        "Convert the entry type and route to the proceedings/preprint adapters (Phase 3); no journal record "
        "will ever exist."),
    "pre-1960-no-indexed-record": (
        "Articles before 1960 with no Crossref, PubMed, OpenAlex or Semantic Scholar record that meets the "
        "identity rule.",
        "Accept on the local PDF/scan or the user's batch sign-off (human-verified), after a 10-entry sample."),
    "no-record-in-any-source-1960-onward": (
        "Articles from 1960 on with no authoritative record found by any route (including a few where only "
        "OpenAlex/Semantic Scholar hold the work: aggregators are leads, never sources).",
        "Local PDF evidence where held; otherwise batch sign-off by journal after a 10-entry sample."),
    "aggregator-lead-only-no-authoritative-record": (
        "OpenAlex/Semantic Scholar hold a matching work but neither Crossref nor PubMed holds it.",
        "Aggregators are leads only: treat like 'no record' (PDF or sign-off)."),
    "record-found-identity-rule-not-met": (
        "A new route found a Crossref or PubMed record with a close title (similarity >= 0.8) and the same "
        "first author, but the strict identity rule fails (title more than two word edits away, missing "
        "volume and pages, author order, or year) or more than two fields differ.",
        "One review packet: confirm the found record IS the cited work (10-entry sample first); the entries "
        "then re-run through the ordinary S1 correction rules. Each row lists the record id and differing fields."),
    "citation-byline-more-detailed-than-source": (
        "The identified record's byline has less detail (initials only, no accents) than the citation.",
        "Keep the citation byline; accept by batch after a 10-entry PDF spot-check (joins phase-0 batch group)."),
    "author-count-differs": (
        "The identified record has a different number of authors.",
        "Individual PDF/publisher-page check, as one review packet."),
    "identified-record-differs-in-3plus-fields": (
        "A record meets the identity rule but three or more fields differ.",
        "Review packet: accept the source record wholesale per entry (usually a garbled citation)."),
    "identified-record-value-held": (
        "A record meets the identity rule, one or two fields differ, but the source value is unusable or a "
        "guard holds it (typography, lossy value, relation, NLM venue style).",
        "Review packet by sub-reason."),
    "authoritative-sources-disagree": (
        "Crossref and PubMed (or publisher JATS) disagree on the field that differs.",
        "Human tie-break from the PDF/publisher page; batch by field."),
    "ambiguous-identity": (
        "Two or more distinct records fit equally well.",
        "Human choice of record."),
    "individual-other": (
        "Remaining one-off cases (year conflicts, audit exclusions, external evidence).",
        "Individual review."),
}


def summarize(rows, client, elapsed, mode):
    outcomes = Counter(r["outcome"] for r in rows)
    per_route = {}
    for route in ("pubmed", "epmc-apa", "openalex", "s2"):
        per_route[route] = dict(Counter(route_status(route, r) for r in rows))
        per_route[route]["decisive_verify"] = sum(1 for r in rows if route in r.get("decisive_routes", [])
                                                   and r["outcome"] == "verify")
        per_route[route]["decisive_proposal"] = sum(1 for r in rows if route in r.get("decisive_routes", [])
                                                     and r["outcome"] == "proposal")
        per_route[route]["sole_route"] = sum(1 for r in rows if r.get("decisive_routes") == [route])
    by_group = defaultdict(Counter)
    for r in rows:
        by_group[r["phase0_group"] if r["phase0_group"] == "article-no-record" else "individual"][r["outcome"]] += 1
    via = Counter((r["outcome"], r.get("via")) for r in rows if r["outcome"] in {"verify", "proposal"})
    return {
        "mode": mode, "head": HEAD, "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "entries": len(rows), "elapsed_seconds": round(elapsed, 1),
        "outcomes": dict(outcomes), "by_target_group": {k: dict(v) for k, v in by_group.items()},
        "verify_proposal_via": {f"{a}/{b}": n for (a, b), n in via.items()},
        "per_route": per_route,
        "blocked_hosts": dict(getattr(client.session, "blocked", {})),
        "requests": {"network": sum(getattr(client.session, "by_host", {}).values()),
                     "attempts_including_refused": client.requests, "by_host": dict(client.session.by_host)
                     if hasattr(client.session, "by_host") else {},
                     "cache": dict(client.cache.hits)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--offline", action="store_true", help="refuse every network request (repeat check)")
    parser.add_argument("--keys", nargs="*")
    parser.add_argument("--s2-always", action="store_true", help="query Semantic Scholar for every entry")
    parser.add_argument("--block", nargs="*", default=[], metavar="HOST",
                        help="never request these hosts in this run (their cached responses still serve)")
    args = parser.parse_args()
    global S2_FALLBACK
    S2_FALLBACK = not (args.s2_always or args.pilot)
    target = targets()
    entries = load_entries(ROOT / "cdl.bib")
    if args.keys:
        keys = args.keys
    elif args.pilot:
        keys = pilot_keys(target, entries)
    else:
        keys = sorted(k for k in target if k in entries)
    missing = sorted(k for k in target if k not in entries)
    client = xs.make_client(OWN_CACHE, MAIN_CACHE, offline=args.offline)
    for host in args.block:
        client.session.blocked[host] = "blocked for this run (--block)"
    db = sqlite3.connect(f"file:{MAIN_CACHE}?mode=ro", uri=True, timeout=30)
    start = time.time()
    rows = {}
    for i, key in enumerate(keys, 1):
        rows[key] = process(client, entries[key], latest_review(db, key), target.get(key, "?"))
        if i % 25 == 0 or args.keys:
            print(f"{i}/{len(keys)} {key} {rows[key]['outcome']} requests={client.requests} "
                  f"{time.time() - start:.0f}s", flush=True)
    # cdl.bib may have changed during the run: re-judge changed entries on current fields.
    final = load_entries(ROOT / "cdl.bib")
    changed = [k for k in keys if k in final and final[k]["fingerprint"] != entries[k]["fingerprint"]]
    for key in changed:
        rows[key] = dict(process(client, final[key], latest_review(db, key), target.get(key, "?")),
                         rejudged_after_bib_change=True)
    gone = [k for k in keys if k not in final]
    for key in gone:
        rows[key] = dict(rows[key], outcome="key-removed-during-run")
    # Earlier documented holds (verification/**/*audit-exclusions.json) stay
    # held, exactly as in verification/phase0-2026-09-22/measure.py.
    excluded = {}
    for path in sorted(ROOT.glob("verification/**/*audit-exclusions.json")):
        data = json.loads(path.read_text())
        items = data.items() if isinstance(data, dict) else [(d.get("key"), d.get("reason") or d.get("kind"))
                                                              for d in data]
        for key, reason in items:
            excluded.setdefault(key, []).append(f"{path.relative_to(ROOT)}: {str(reason)[:160]}")
    for key, row in rows.items():
        if row["outcome"].startswith("proposal") and key in excluded:
            row["withheld_proposal"] = {k: row.pop(k) for k in ("changes", "subclasses", "rule", "via", "doi", "pmid")
                                        if k in row}
            row["outcome"] = "held-audit-excluded"
            row["audit_exclusion"] = excluded[key]
    elapsed = time.time() - start
    ordered = [rows[k] for k in keys]
    if args.keys:
        print(json.dumps(ordered, indent=1, default=sorted)[:20000])
        return
    summary = summarize(ordered, client, elapsed, "offline-repeat" if args.offline else
                        ("pilot" if args.pilot else "full"))
    summary.update(changed_during_run=changed, removed_during_run=gone, missing_at_start=missing)
    groups = defaultdict(list)
    for row in ordered:
        if row["outcome"].startswith(("verify", "proposal", "status-", "key-removed")):
            continue
        fields = final.get(row["key"], entries[row["key"]])["fields"]
        row["group"] = group_for(row, fields)
        groups[row["group"]].append(row["key"])
    mode = summary["mode"]
    out = HERE / "results.json"
    data = json.loads(out.read_text()) if out.exists() else {}
    if mode == "offline-repeat":
        full = {r["key"]: r["outcome"] for r in data.get("full", {}).get("rows", [])}
        summary["differs_from_full_run"] = sorted(r["key"] for r in ordered
                                                  if full and full.get(r["key"]) != r["outcome"])
        data[mode] = {"summary": summary}
    else:
        data[mode] = {"summary": summary, "rows": ordered}
    out.write_text(json.dumps(data, indent=1, default=sorted, ensure_ascii=False) + "\n")
    if not args.pilot and not args.offline:
        group_rows = []
        for name, keys_ in sorted(groups.items(), key=lambda x: -len(x[1])):
            text, decision = GROUP_TEXT[name]
            journals = Counter(final.get(k, entries[k])["fields"].get("journal", "") for k in keys_)
            by_key = {r["key"]: r for r in ordered}
            subpatterns = Counter(subpattern(by_key[k], final.get(k, entries[k])["fields"]) for k in keys_)
            group_rows.append({"group": name, "count": len(keys_), "description": text,
                               "suggested_batch_decision": decision, "subpatterns": dict(subpatterns.most_common()),
                               "keys": sorted(keys_), "top_journals": journals.most_common(8),
                               **({"records": {k: best_record(by_key[k]) for k in sorted(keys_)}}
                                  if name == "record-found-identity-rule-not-met" else {})})
        (HERE / "groups.json").write_text(json.dumps({"generated": summary["generated"], "head": HEAD,
                                                      "remaining": sum(len(v) for v in groups.values()),
                                                      "groups": group_rows}, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=1)[:6000])
    client.cache.close()


if __name__ == "__main__":
    main()
