"""api.revision under reads and writes, api.check_keys' scope and cost, and the search bounds
api.find_candidates passes on.

Real files, a real SQLite cache holding the verifier's own results, a second real process that
approves, the 6,481-entry frozen library for the cost, and the saved search responses with the
network refused. No mocks.
"""
import shutil
import subprocess
import sys
import time

import pytest

import conftest
from cdlbib import api, intake
from cdlbib.errors import IdentityUnavailable
from cdlbib.verification import Cache, load_entries, record_approval, verify_entry
from cdlbib.workspace import Workspace

from intake_support import CONTACT, library as search_library, offline_client
from test_complete_cli import refused_network
from test_complete_identify import client, library_entry  # noqa: F401
from test_desk import GAME62, KAHA12, TEXT, ZOLL90

REVIEW = dict(reviewer="@fixture", source="the journal's page", note="every field checked", github_login="fixture",
              github_id=1)


@pytest.fixture
def offline(monkeypatch):
    for name, value in refused_network().items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def ws(tmp_path, client):
    """Four entries and Game62, with stored results of several kinds: the verifier's own for
    Game62 (candidates and all), an approval, and a result stored under the old (pre-v2)
    fingerprint, which the first read brings up to date."""
    root = tmp_path / "lib"
    root.mkdir()
    ws = Workspace(root)
    ws.bib.write_text(TEXT + "\n" + GAME62 + "\n", encoding="utf-8")
    found = load_entries(ws.bib)
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        cache.put(ws.bib, found["Game62"], verify_entry(found["Game62"], client))
        record_approval(cache, ws.bib, "Kaha12", found["Kaha12"]["fingerprint"], REVIEW)
        legacy = dict(found["Zoll90"], fingerprint=found["Zoll90"]["legacy_fingerprint"])
        cache.put(ws.bib, legacy, {"status": "human_verified", "issues": [], "human_review": REVIEW})
    finally:
        cache.close()
    return ws


def looks(ws, reference):
    """Every way of looking at the library that writes nothing to it."""
    summaries = api.entries(ws)
    api.search(ws, "memory")
    api.search(summaries, "status:pending")
    for key in ("Zoll90", "Kaha12", "Game62", "GlocBets08"):
        api.entry(ws, key)
    api.preview_edit(ws, "Kaha12", KAHA12.replace("2012", "2013"))
    api.preview_edit(ws, None, ZOLL90.replace("{Zoll90,", "{Another90,"))
    api.review_queue(ws, all_entries=True)
    api.review_queue(ws, reference=str(reference))
    api.library_state(ws)
    api.library_state(ws, refresh=True)
    return {item.key: item.status for item in summaries}


def test_revision_stays_put_under_reads_and_moves_with_every_real_change(ws, tmp_path, offline):
    reference = tmp_path / "reference.bib"
    reference.write_text(KAHA12 + "\n", encoding="utf-8")
    lines = []
    prepared = api.prepare(ws, progress=lines.append)      # the cache's one-time bookkeeping happens here
    assert "reading the stored verification results ..." in lines
    start = api.revision(ws)
    assert prepared.revision == start and start[1] is not None and start[2:] == (None, None)
    statuses = looks(ws, reference)
    assert statuses == {"Zoll90": "human_verified", "Kaha12": "human_verified", "GlocBets08": "pending",
                        "TeneEtal11": "pending", "Game62": "metadata_verified"}
    assert api.revision(ws) == start                        # however much the database file itself was touched
    looks(ws, reference)
    api.prepare(ws)
    assert api.revision(ws) == start

    opened = api.entry(ws, "GlocBets08")
    api.save_edit(ws, "GlocBets08", opened.raw.replace("1055--1075", "1055--1076"), opened.fingerprint)
    saved = api.revision(ws)
    assert saved[0] != start[0] and saved[1:] == start[1:]
    looks(ws, reference)
    assert api.revision(ws) == saved

    renamed = api.entry(ws, "TeneEtal11")
    api.save_edit(ws, "TeneEtal11", renamed.raw.replace("{TeneEtal11,", "{Tenenbaum2011,"), renamed.fingerprint)
    after_rename = api.revision(ws)
    assert after_rename[2] is not None and saved[2] is None and after_rename[0] != saved[0]

    check = api.check_keys(ws, ["Kaha12"], mailto=CONTACT)   # already approved: the gate stores nothing new
    assert check.ok and api.revision(ws) == after_rename
    with pytest.raises(Exception):                           # an unverified key, the network refused: a result IS stored
        api.check_keys(ws, ["GlocBets08"], mailto=CONTACT)
    checked = api.revision(ws)
    assert api.entry(ws, "GlocBets08").status == "provider_error"
    assert checked[1] != after_rename[1] and checked[0] == after_rename[0]
    assert api.revision(ws) == checked


def test_revision_moves_when_another_process_approves_and_on_approve_and_revoke(ws, tmp_path):
    api.prepare(ws)
    start = api.revision(ws)
    fingerprint = load_entries(ws.bib)["GlocBets08"]["fingerprint"]
    code = f"""
from cdlbib.verification import Cache, record_approval
from cdlbib.workspace import Workspace
ws = Workspace({str(ws.root)!r})
cache = Cache(ws.database, ledger=ws.revocations)
record_approval(cache, ws.bib, "GlocBets08", {fingerprint!r}, {REVIEW!r})
cache.close()
"""
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    elsewhere = api.revision(ws)
    assert elsewhere != start and elsewhere[0] == start[0] and elsewhere[1][0] > start[1][0]
    assert api.entry(ws, "GlocBets08").status == "human_verified" and api.revision(ws) == elsewhere

    from cdlbib import identity
    try:
        identity.current()
    except IdentityUnavailable as exc:
        pytest.skip(f"no GitHub login for a real approval: {exc}")
    opened = api.entry(ws, "TeneEtal11")
    api.approve(ws, "TeneEtal11", opened.fingerprint, "the journal's page", "all fields checked")
    approved = api.revision(ws)
    assert approved != elsewhere and approved[1][0] > elsewhere[1][0]
    api.revoke(ws, "TeneEtal11", "wrong issue", expected_fingerprint=opened.fingerprint)
    revoked = api.revision(ws)
    assert revoked != approved and revoked[1][1] == approved[1][1] + 1
    api.entry(ws, "TeneEtal11"); api.entries(ws)
    assert api.revision(ws) == revoked


def test_asking_for_the_revision_changes_no_file(ws):
    from test_desk import tree
    before = tree(ws.root)
    stamps = {name: (path.stat().st_mtime_ns, path.stat().st_size) for name, path in
              ((item.name, item) for item in ws.work.iterdir())}
    for _ in range(3):
        api.revision(ws)
    assert tree(ws.root) == before
    assert stamps == {item.name: (item.stat().st_mtime_ns, item.stat().st_size) for item in ws.work.iterdir()}
    empty = Workspace(ws.root.parent / "none")
    empty.root.mkdir()
    empty.bib.write_text(KAHA12 + "\n", encoding="utf-8")
    assert api.revision(empty)[1:] == (None, None, None) and not empty.work.exists()


# --- checking chosen keys costs the chosen keys ----------------------------------------------------

def test_check_keys_judges_only_the_chosen_entries_and_says_so(tmp_path, offline):
    ws = Workspace(tmp_path)
    using = ZOLL90.replace("{Journal of Research in Science Teaching}", "jrst").replace("1053--1065", "1053-1065")
    elsewhere = KAHA12.replace("New York, {NY}", "New York, NY").replace("Year = {2012}", "Abstract = {x},\n\tYear = {2012}")
    ws.bib.write_text('@string{jrst = "Journal of Research in Science Teaching"}\n\n' + using + "\n\n" + elsewhere
                      + "\n\n" + GAME62 + "\n", encoding="utf-8")
    found = load_entries(ws.bib)
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        for key in found:
            record_approval(cache, ws.bib, key, found[key]["fingerprint"], REVIEW)
    finally:
        cache.close()
    lines = []
    clean = api.check_keys(ws, ["Game62"], progress=lines.append, mailto=CONTACT)
    assert clean.ok and clean.scope == "keys" and clean.format.ok and clean.format.errors == []
    assert lines[0] == "format: Game62: looks good"             # a line per entry, then the gate's
    assert any(text.startswith("citations: 1 of 1 chosen entries verified") for text in lines)
    lines = []
    chosen = api.check_keys(ws, ["Zoll90", "Kaha12"], progress=lines.append, mailto=CONTACT)
    assert not chosen.ok and chosen.citations.ok and chosen.scope == "keys"
    assert chosen.format.errors == ["Zoll90", "Kaha12"] and chosen.format.failure == ""
    assert chosen.format.corrections == {"Zoll90": {"pages": "1053--1065"},        # the entry that uses the @string
                                         "Kaha12": {"address": "New York, {NY}", "abstract": None}}
    assert lines[0] == "format: Zoll90: the format checker would write pages as 1053--1065"
    assert lines[1].startswith("format: Kaha12: ")
    whole = api.check_library(ws, citations=False)               # the whole-library path, as it was
    assert whole.scope == "library" and not whole.ok and "non-essential fields: Kaha12" in whole.format.failure


def test_check_keys_on_the_whole_frozen_library_does_not_cost_a_library_pass(tmp_path, offline):
    """6,481 entries. The whole-library format check takes about 11 s here (it is timed,
    below); checking one approved entry must take a fraction of that once the library is read."""
    ws = Workspace(tmp_path)
    shutil.copy(conftest.FROZEN_LIBRARY, ws.bib)
    key = api.entries(ws)[100].key
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        record_approval(cache, ws.bib, key, api.entry(ws, key).fingerprint, REVIEW)
    finally:
        cache.close()
    started = time.monotonic()
    check = api.check_keys(ws, [key], mailto=CONTACT)
    chosen = time.monotonic() - started
    assert check.scope == "keys" and set(check.citations.checked) == {key}
    assert check.format.errors == [item for item in [key] if api.entry(ws, key).format]
    started = time.monotonic()
    whole = api.check_format(ws)
    library = time.monotonic() - started
    print(f"check_keys of one entry: {chosen:.1f} s; whole-library format check: {library:.1f} s")
    assert len(whole.errors) > 100 and check.format.errors != whole.errors
    # the gate still reads the library and writes its report (a few seconds); what is gone is the format pass
    assert chosen < 0.8 * library + 5, (chosen, library)


def test_send_checked_still_checks_the_format_of_the_whole_library(tmp_path, monkeypatch, offline):
    from cdlbib.errors import GateFailed
    from test_publish import GIT_ENV, git
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    remote = tmp_path / "fork.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "master", str(remote))
    work = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", str(remote), str(work))
    git(work, "checkout", "-q", "-B", "master")
    (work / "cdl.bib").write_text(KAHA12.replace("New York, {NY}", "New York, NY") + "\n", encoding="utf-8")
    git(work, "add", "-A"); git(work, "commit", "-q", "-m", "start"); git(work, "push", "-q", "origin", "HEAD:master")
    ws = Workspace(work)
    ws.bib.write_text(ws.bib.read_text(encoding="utf-8") + "\n" + ZOLL90 + "\n", encoding="utf-8")   # the new entry is clean
    reports = []
    with pytest.raises(GateFailed, match="not sent: fix the format errors") as failed:
        api.send_checked(ws, report=reports.append)
    assert failed.value.check.scope == "library" and failed.value.check.format.errors == ["Kaha12"]
    assert reports[0].scope == "library"


# --- the bounds of a search pass through ----------------------------------------------------------

def test_find_candidates_passes_limit_and_per_source_on(tmp_path, offline):
    saved = offline_client(tmp_path / "cache", "searches.json.gz")
    database = saved.cache.path
    saved.cache.close()
    ws = search_library(tmp_path / "lib")
    asked = dict(authors=["Manning", "Kahana"], database=str(database), mailto=CONTACT)
    # the searches were recorded with five records per source: the same parameters replay them
    direct_client = offline_client(tmp_path / "cache2", "searches.json.gz")
    try:
        direct = intake.find_candidates(ws, client=direct_client, per_source=5, authors=["Manning", "Kahana"])
        two = intake.find_candidates(ws, client=direct_client, per_source=5, limit=2, authors=["Manning", "Kahana"])
    finally:
        direct_client.cache.close()
    replayed = api.find_candidates(ws, per_source=5, **asked)
    assert replayed == direct and replayed.errors == [] and len(replayed) > 2
    assert api.find_candidates(ws, per_source=5, limit=2, **asked) == two and len(two) == 2
    huge = api.find_candidates(ws, per_source=5, limit=10**9, **asked)                 # bounded by intake's maximum
    assert huge == direct and len(huge) <= intake.MAX_CANDIDATES
    default = api.find_candidates(ws, **asked)       # ten per source were never recorded: each source says so
    assert default == [] and len(default.errors) == 3
    import inspect
    parameters = inspect.signature(api.find_candidates).parameters
    assert parameters["limit"].default is None and parameters["per_source"].default is None
