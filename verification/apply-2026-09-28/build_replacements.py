"""Preprint -> published replacement candidates (for user approval; NOT applied).

Candidates are cited preprints whose repository record names a published version:
- Crossref ``relation.is-preprint-of`` on the cited bioRxiv/PsyArXiv record (saved evidence in
  verification/baseline.jsonl.gz; the OSF route classes GralFinn21, LuriEtal18, NussEtal18 as
  ``replacement``; adddoi002 skipped LeeEtal19, ChieHone19, SilvEtal19 for this reason);
- the arXiv API ``arxiv:doi`` of a cited arXiv preprint (one request for all cited arXiv ids).

For each, the published version's Crossref record is fetched and a house-form draft entry
(initials, lowercase DOI, ``--`` ranges, key per the ID rule) is written with the key it would
take. Key collisions are resolved by the suffix rule and reported.

    CROSSREF_MAILTO=<contact> .venv/bin/python verification/apply-2026-09-28/build_replacements.py
"""
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import load_entries  # noqa: E402
import helpers  # noqa: E402


MAILTO = os.environ.get("CROSSREF_MAILTO", "")
UA = {"User-Agent": f"CDL-bibliography verification (mailto:{MAILTO})"}
PREPRINT = re.compile(r"rxiv|preprint|ssrn|research square", re.I)
PREFIXES = ("10.1101/", "10.48550/", "10.31234/", "10.31219/", "10.2139/", "10.21203/")


def get(url):
    time.sleep(1)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode()


def norm_title(t):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\\[a-z]+|[{}]", "", (t or "").lower()))


def cited_preprints(entries):
    out = {}
    for key, entry in entries.items():
        f = entry["fields"]
        ids = " ".join(f.get(x, "") for x in ("doi", "volume", "pages")).replace("doi.org/", "")
        if PREPRINT.search(f.get("journal", "") + " " + f.get("howpublished", "")) or \
                any(v.lower().startswith(PREFIXES) for v in ids.split()):
            out[key] = ids
    return out


def crossref_relations(entries, preprints):
    found = {}
    with gzip.open(ROOT / "verification/baseline.jsonl.gz", "rt") as f:
        next(f)
        for row in map(json.loads, f):
            key = row["key"]
            if key not in preprints:
                continue
            for c in row.get("candidates") or []:
                rec = c.get("record") or {}
                if rec.get("type") != "posted-content":
                    continue
                if norm_title((rec.get("title") or [""])[0])[:60] != norm_title(entries[key]["fields"].get("title"))[:60]:
                    continue
                for rel in (rec.get("relation") or {}).get("is-preprint-of", []):
                    found.setdefault(key, {"preprint_doi": rec["DOI"].lower(), "published_doi": rel["id"].lower(),
                                           "flag": "Crossref relation is-preprint-of on the cited preprint record "
                                                   f"{rec['DOI']}: {rel['id']}"})
    return found


def arxiv_dois(entries, preprints):
    ids = {}
    for key, text in preprints.items():
        if "arxiv" in entries[key]["fields"].get("journal", "").lower():
            m = re.search(r"(\d{4}\.\d{4,5})", text)
            if m:
                ids.setdefault(m[1], []).append(key)
    body = get("http://export.arxiv.org/api/query?id_list=" + ",".join(sorted(ids)) + f"&max_results={len(ids) + 5}")
    found = {}
    for block in body.split("<entry>")[1:]:
        ident = re.search(r"<id>http://arxiv.org/abs/([\d.]+)v(\d+)</id>", block)
        doi = re.search(r"<arxiv:doi[^>]*>([^<]+)</arxiv:doi>", block)
        ref = re.search(r"<arxiv:journal_ref[^>]*>([^<]+)</arxiv:journal_ref>", block)
        if ident and doi:
            for key in ids.get(ident[1], []):
                found[key] = {"preprint_doi": f"10.48550/arxiv.{ident[1]}", "published_doi": doi[1].lower(),
                              "flag": f"arXiv API {ident[1]}v{ident[2]}: arxiv:doi {doi[1]}; journal_ref "
                                      f"{html.unescape(ref[1]) if ref else None}"}
    return found, len(ids)


def house_author(given, family):
    """Initials without periods, one per given name; hyphenated given names keep hyphens."""
    parts = []
    for word in re.split(r"[\s.]+", given):
        if word:
            parts.append("-".join(piece[0].upper() for piece in word.split("-") if piece))
    return (" ".join(parts) + " " + family).strip()


def draft(key, rec):
    authors = " and ".join(house_author(a.get("given", ""), a.get("family", a.get("name", ""))) for a in rec.get("author", []))
    year = (rec.get("published-print") or rec.get("issued"))["date-parts"][0][0]
    pages = (rec.get("page") or rec.get("article-number") or "").replace("-", "--")
    fields = {"Author": authors, "Doi": rec["DOI"].lower(), "Journal": (rec.get("container-title") or [""])[0],
              "Number": rec.get("issue"), "Pages": pages or None, "Title": html.unescape(rec["title"][0]),
              "Volume": rec.get("volume"), "Year": str(year)}
    body = ",\n".join(f"\t{k} = {{{v}}}" for k, v in fields.items() if v)
    return f"@article{{{key},\n{body}}}", fields, year


def main():
    entries = load_entries(ROOT / "cdl.bib")
    preprints = cited_preprints(entries)
    found = crossref_relations(entries, preprints)
    arx, n_arxiv = arxiv_dois(entries, preprints)
    found.update(arx)
    rows = []
    taken = set(entries)
    for key in sorted(found):
        f = found[key]
        rec = json.loads(get(f"https://api.crossref.org/works/{f['published_doi']}?mailto={MAILTO}"))["message"]
        _, fields, year = draft("KEY", rec)
        base = helpers.authors2key(fields["Author"], year)
        same = sorted(k for k in taken if re.fullmatch(re.escape(base) + r"[a-z]*", k) and k != key)
        notes = []
        if not same:
            new_key = base
        else:
            new_key = base + "abcdefghijklmnopqrstuvwxyz"[len(same)]
            if len(same) == 1 and same[0] == base:
                notes.append(f"key collision: existing {base} (a different work) would become {base}a and the "
                             f"published version {base}b (suffix rule)")
                new_key = base + "b"
            else:
                notes.append(f"key collision with {same}: next suffix {new_key}")
        if new_key == key:
            notes.append("the published version takes the same key (same first author, author count and year)")
        text, fields, _ = draft(new_key, rec)
        cited = entries[key]["fields"]
        if len(rec.get("author", [])) != len(cited.get("author", "").split(" and ")):
            notes.append(f"author count differs: preprint {len(cited.get('author', '').split(' and '))}, "
                         f"published {len(rec.get('author', []))}")
        dup = [k for k, e in entries.items() if k != key and (e["fields"].get("doi", "").lower() == f["published_doi"]
               or norm_title(e["fields"].get("title"))[:50] == norm_title(rec["title"][0])[:50])]
        if dup:
            notes.append(f"published version may already be in cdl.bib: {dup}")
        rows.append({"key": key, "current_entry": entries[key]["raw"], "evidence": f["flag"],
                     "preprint_doi": f["preprint_doi"],
                     "published": {"doi": f["published_doi"], "venue": fields["Journal"], "year": year,
                                   "volume": fields.get("Volume"), "number": fields.get("Number"),
                                   "pages": fields.get("Pages"), "authors": fields["Author"],
                                   "crossref": f"https://api.crossref.org/works/{f['published_doi']}"},
                     "proposed_key": new_key, "proposed_entry": text, "notes": notes,
                     "action_if_approved": f"remove {key}; add {new_key}; log {key} -> {new_key} in key-renames.json"})
    out = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "FOR USER APPROVAL - not applied",
           "cited_preprints_scanned": len(preprints), "arxiv_ids_queried": n_arxiv, "candidates": rows}
    (HERE / "replacement-candidates.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for r in rows:
        print(r["key"], "->", r["proposed_key"], r["published"]["doi"], r["published"]["venue"], r["published"]["year"], r["notes"])


if __name__ == "__main__":
    main()
