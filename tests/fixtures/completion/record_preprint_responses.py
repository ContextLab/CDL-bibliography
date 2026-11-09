"""Record ``preprint_responses.json``: the lookups of tests/test_complete_preprints.py.

Run once, from the repository root, with the project's contact address:

    python tests/fixtures/completion/record_preprint_responses.py CACHE.sqlite3 CONTACT

Each query below is run through ``cdlbib.complete.propose`` with the project's real client
(``extra_sources.make_client``) over the response cache at CACHE.sqlite3 (an empty file for a
fresh recording), and every response the client read or fetched for it is written out as the
client cached it, in the form of ``responses.json`` (see the README): the ``request`` (the
client's cache key: a list for an API request, a string for a document a route fetched, such
as ``biorxiv-details-v1:<DOI>`` or ``osf-source-v1:<URL>``) and the ``response`` (``url``,
``retrieved_at``, ``http_status`` and ``body``, or for a document ``url``, ``body``,
``document_sha256`` and ``retrieved_at``). The contact address is removed from each saved
URL, and an e-mail address inside a body is replaced by ``[address removed]`` (a plain address,
or one a version page writes as ``name{at}host`` in its ``citation_author_email`` tags); the
SHA-256 of a document whose body was so changed is computed again, over the saved body.
Nothing else is altered.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

from cdlbib import complete
from cdlbib import extra_sources as xs
from cdlbib.verification import load_entries

HERE = Path(__file__).resolve().parent
ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+(?:@|\{at\})[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

# A DOI alone, as `cdlbib add` is given it.
DOIS = (
    "10.64898/2026.03.19.712982",   # bioRxiv, 2026 DOI prefix, one version (the 1kD project)
    "10.1101/2021.05.10.443308",    # bioRxiv, two versions (XieEtal21 of cdl.bib)
    "10.1101/2025.06.01.25328748",  # medRxiv, one version; history and registry agree
    "10.1101/2025.05.29.25327068",  # medRxiv; the history's title is not the registry's
    "10.31234/osf.io/mhxtd_v1",     # PsyArXiv, a versioned DOI (FitzEtal26a of cdl.bib)
    "10.31234/osf.io/erzfp",        # PsyArXiv, an unversioned DOI (MannEtal23a of cdl.bib)
    "10.31235/osf.io/kv2qc",        # SocArXiv (an OSF server)
    "10.21203/rs.3.rs-4840802/v1",  # Research Square
    "10.2139/ssrn.5238498",         # SSRN
    "10.1101/2020.01.27.922062",    # bioRxiv; its history names the published article (ChenEtal21)
)
# Entries typed by hand, completed as `cdlbib verify` offers to complete them.
TYPED = (
    "@article{RaviEtal26,\n"
    "\tAuthor = {H Raviv and L Hasenfratz and K Gousios and M Faryna and R Beaty and D Johnson and B Chen and "
    "A Altenhof and B Ryan and C A Greenberg and Z Hong and G Assayag and A Tsyhanov and V Malakhov and "
    "T Rosenwein and O Raviv and C Lew-Williams and U Hasson},\n"
    "\tDoi = {10.64898/2026.03.19.712982},\n"
    "\tJournal = {{bioRxiv}},\n"
    "\tTitle = {The {First 1,000 Days (1kD) Project}: collecting and analyzing an ultra-dense naturalistic "
    "dataset of human baby development},\n"
    "\tVolume = {10.64898/2026.03.19.712982},\n"
    "\tYear = {2026}}",
)


def main(cache_path, contact):
    client = xs.make_client(cache_path, contact=contact)
    used = []
    read, save = client.cache.response, client.cache.save_response

    def response(request, ttl):
        found = read(request, ttl)
        if found is not None and request not in used:
            used.append(request)
        return found

    def save_response(request, body):
        if request not in used:
            used.append(request)
        save(request, body)

    client.cache.response, client.cache.save_response = response, save_response
    for doi in DOIS:
        built = complete.propose(complete.Query.parse(doi), client, client.cache)
        print(doi, built.status, built.key_proposed)
    with tempfile.TemporaryDirectory() as folder:
        for text in TYPED:
            path = Path(folder) / "typed.bib"
            path.write_text(text + "\n", encoding="utf-8")
            built = complete.propose(complete.Query.from_entry(next(iter(load_entries(path).values()))),
                                     client, client.cache)
            print("typed", built.status, built.key_typed)
    saved = []
    for request in used:
        body = read(request, float("inf"))
        body["url"] = re.sub(r"[?&]mailto=[^&]*", "", body["url"])
        text = body["body"] if isinstance(body.get("body"), str) else json.dumps(body.get("body"))
        cleaned = ADDRESS.sub("[address removed]", text)
        if cleaned != text:
            if isinstance(body.get("body"), str):
                body["body"] = cleaned
                if "document_sha256" in body:
                    body["document_sha256"] = hashlib.sha256(cleaned.encode()).hexdigest()
            else:
                body["body"] = json.loads(cleaned)
        assert contact not in json.dumps(body) and not ADDRESS.search(json.dumps(body))
        try:
            key = json.loads(request)
        except ValueError:
            key = request  # a document's cache key
        saved.append({"request": key, "response": body})
    (HERE / "preprint_responses.json").write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n",
                                                  encoding="utf-8")
    print(f"{len(saved)} responses saved")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
