"""Record ``type_responses.json``: the lookups of tests/test_complete_types.py.

Run once, from the repository root, with a real contact address in CROSSREF_MAILTO:

    python tests/fixtures/completion/record_type_responses.py CACHE.sqlite3

Each query below is run through ``cdlbib.complete.propose`` with the project's real client
(``extra_sources.make_client``) over the response cache at CACHE.sqlite3, and every response
the client read or fetched for it is written out as the client cached it, in the form of
``responses.json`` (see the README): the ``request`` (the client's cache key) and the
``response`` (``url``, ``retrieved_at``, ``http_status``, ``body``). The contact address is
removed from each saved URL. Nothing else is altered.
"""
import json
from pathlib import Path
import re
import sys
import tempfile

from cdlbib import complete
from cdlbib import extra_sources as xs
from cdlbib.verification import load_entries

HERE = Path(__file__).resolve().parent
FROZEN = HERE.parent / "cdl-prewave1-2026-09-26.bib"

# A DOI alone: the works are entries of the frozen library fixture unless said otherwise.
DOIS = (
    "10.1093/oxfordhb/9780190917982.013.2",   # KahaEtal24: a chapter of an edited handbook
    "10.1093/oxfordhb/9780190917982.013.38",  # Mann24: another chapter of the same book
    "10.1515/9781400882618-002",              # Klee56: a chapter; the book title carries a series number
    "10.1016/b978-0-12-108550-6.50010-0",     # BobrNorm75: a chapter the verifier accepts from Crossref
    "10.1007/978-0-387-21579-2_9",            # Scha03: a chapter whose record names a series and a book
    "10.1007/978-1-4684-1083-9_9",            # AherBeat81: a chapter whose registry publisher is not the imprint
    "10.1109/cvpr.2017.354",                  # BauEtal17: a paper in proceedings (year and acronym in the name)
    "10.1109/cvpr.2010.5539970",              # XiaoEtal10: a paper in proceedings
    "10.1145/3210240.3210322",                # NguyEtal18: a paper in proceedings; title and subtitle
    "10.18653/v1/d19-1410",                   # ReimGure19: an ACL Anthology paper (Crossref's pages differ)
    "10.32470/ccn.2018.1267-0",               # HeusMann18: a paper in proceedings with no pages
    "10.1109/icassp.1990.115702",             # Kais90: a paper in proceedings whose record has no date
    "10.1201/b16018",                         # GelmEtal13: a book (the third edition)
    "10.1017/CBO9780511802843",               # DaviHink97: a book Crossref types as a monograph
    "10.4135/9781452257044.n183",             # KahaMill13: an encyclopedia entry (reference-entry)
    "10.1136/ebm-2023-pod.3",                 # not in the library: a meeting abstract typed proceedings-article
    "10.1167/15.11.1",                        # not in the library: an article of Journal of Vision 15 (2015)
)
# A typed entry of the frozen library, as it stands there.
TYPED = ("Scha03", "KahaEtal24", "BobrNorm75")
# A typed paper in proceedings without its DOI: found by its title, first author and year.
SEARCHED = ("BauEtal17",)
# A built paper edited (``api.recheck_proposal``) to a last page the record does not have: the
# verifier then asks PubMed about the DOI.
EDITED = (("BauEtal17", "3319--3327", "3319--3328"),)


def main(cache_path):
    client = xs.make_client(cache_path)
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
    library = load_entries(FROZEN)
    for doi in DOIS:
        complete.propose(complete.Query.parse(doi), client, client.cache)
    for key in TYPED:
        complete.propose(complete.Query.from_entry(library[key]), client, client.cache)
    with tempfile.TemporaryDirectory() as folder:
        for key in SEARCHED:
            text = "\n".join(line for line in library[key]["raw"].splitlines() if not line.startswith("\tDoi = "))
            path = Path(folder) / "typed.bib"
            path.write_text(text + "\n", encoding="utf-8")
            complete.propose(complete.Query.from_entry(next(iter(load_entries(path).values()))), client, client.cache)
        from cdlbib import api
        from cdlbib.workspace import Workspace
        ws = Workspace(folder)
        ws.bib.write_text("", encoding="utf-8")
        for key, old, new in EDITED:
            built = complete.propose(complete.Query.parse(library[key]["fields"]["doi"]), client, client.cache, ws=ws)
            before = {row[0] for row in client.cache.db.execute("SELECT request FROM responses")}
            api.recheck_proposal(ws, built, built.proposed_raw.replace(old, new), database=cache_path)
            used += [row[0] for row in client.cache.db.execute("SELECT request FROM responses") if row[0] not in before]
    saved = []
    for request in used:
        body = read(request, float("inf"))
        body["url"] = re.sub(r"[?&]mailto=[^&]*", "", body["url"])
        assert client.contact not in json.dumps(body)
        saved.append({"request": json.loads(request), "response": body})
    (HERE / "type_responses.json").write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(saved)} responses saved")


if __name__ == "__main__":
    main(sys.argv[1])
