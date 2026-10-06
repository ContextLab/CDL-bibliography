"""Record ``rule_responses.json``: the lookups of tests/test_complete_rules.py.

Run once, from the repository root, with a real contact address in CROSSREF_MAILTO:

    python tests/fixtures/completion/record_rule_responses.py CACHE.sqlite3

CACHE.sqlite3 is a new, empty response cache. It is first filled with the responses already
saved beside this file (``responses.json``, ``type_responses.json``), so that only what those
do not hold is requested. Each query below is then run through ``cdlbib.complete.propose``
with the project's real client (``extra_sources.make_client``), and every response the client
fetched for it is written out as the client cached it, in the form of ``responses.json`` (see
the README): the ``request`` (the client's cache key: a list for an API request, a string for
a document such as the ACL Anthology's BibTeX) and the ``response``. The contact address is
removed from each saved URL, and a response that holds an e-mail address is refused. Nothing
else is altered.
"""
import json
from pathlib import Path
import re
import sys
import tempfile

from cdlbib import complete
from cdlbib import extra_sources as xs
from cdlbib.verification import dumps, load_entries

HERE = Path(__file__).resolve().parent
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# A DOI alone.
DOIS = (
    "10.1515/9783110858778-003",           # a chapter whose own record names the book's one editor
    "10.1093/med/9780197549469.003.0016",  # a chapter whose record names four editors (one with a particle)
    "10.18653/v1/d19-1410",                # ReimGure19: the Anthology's record is read for the pages
    "10.18653/v1/d19-6607",                # ClanEtal19: an ordinal word in the proceedings' name; an Anthology paper
    "10.1117/12.2309486",                  # not in the library: a paper in proceedings whose record names editors
)
# That paper typed as built, with the volume's editors as its record names them.
PAPER_EDITORS = "J Zhou and P Radeva and D Nikolaev and A Verikas"
# The first chapter typed with editors: the record's own, another book's, and one too many.
CHAPTER = ("@incollection{Mins79,\n\tAuthor = {M Minsky},\n\tBooktitle = {Frame Conceptions and Text Understanding},\n"
           "\tDoi = {10.1515/9783110858778-003},\n\tEditor = {EDITORS},\n\tPages = {1--25},\n"
           "\tPublisher = {De Gruyter},\n\tTitle = {A framework for representing knowledge},\n\tYear = {1979}}")
EDITORS = ("D Metzing", "P H Winston", "D Metzing and P H Winston")


def main(cache_path):
    client = xs.make_client(cache_path)
    for name in ("responses.json", "type_responses.json"):
        for item in json.loads((HERE / name).read_text(encoding="utf-8")):
            request = item["request"]
            if isinstance(request, list):
                url, params, xml = request
                request = dumps([url, {k: client.contact if v == "CONTACT" else v for k, v in params.items()}, xml])
            client.cache.save_response(request, item["response"])
    before = {row[0] for row in client.cache.db.execute("SELECT request FROM responses")}
    # What an earlier run of this script saved is not requested again, and is written out again.
    target = HERE / "rule_responses.json"
    for item in json.loads(target.read_text(encoding="utf-8")) if target.exists() else []:
        request = item["request"]
        client.cache.save_response(request if isinstance(request, str) else dumps(request), item["response"])
    built = {}
    for doi in DOIS:
        proposal = built[doi] = complete.propose(complete.Query.parse(doi), client, client.cache)
        print(doi, "->", proposal.status, proposal.issues, file=sys.stderr)
    with tempfile.TemporaryDirectory() as folder:
        paper = built["10.1117/12.2309486"].proposed_raw
        typed = [CHAPTER.replace("EDITORS", editors) for editors in EDITORS]
        typed.append(paper.replace("\tPages = ", "\tEditor = {" + PAPER_EDITORS + "},\n\tPages = "))
        for text in typed:
            path = Path(folder) / "typed.bib"
            path.write_text(text + "\n", encoding="utf-8")
            entry = next(iter(load_entries(path).values()))
            proposal = complete.propose(complete.Query.from_entry(entry), client, client.cache)
            print(entry["fields"].get("editor"), "->", proposal.status, proposal.issues, file=sys.stderr)
    saved = []
    for (request,) in client.cache.db.execute("SELECT request FROM responses ORDER BY fetched"):
        if request in before:
            continue
        body = client.cache.response(request, float("inf"))
        body["url"] = re.sub(r"[?&]mailto=[^&]*", "", body["url"])
        text = json.dumps(body)
        assert client.contact not in text and not ADDRESS.search(text), request
        saved.append({"request": json.loads(request) if request.startswith("[") else request, "response": body})
    (HERE / "rule_responses.json").write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(saved)} responses saved", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
