"""The web interface under the conditions a review found it weak in: a decision on a proposal
version that is no longer the one shown, an edit from outside between two reads, more work
and more bytes than it should hold, uploads that arrive together, shutdown with jobs waiting,
and a library the user chose while a managed one exists.

The real server and core against libraries in tmp_path; nothing is replaced by a stand-in.
Where a test needs the one worker to be busy, it gives it a job of its own that waits for the
test (jobs.Worker runs any callable), which is how the queue is observed without racing it.
"""
import concurrent.futures
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import conftest
import web_support as web
from cdlbib import api, complete, prompts
from cdlbib.verification import load_entries
from cdlbib.web import jobs, routes, server, store

from test_web_flows import GAME62, KAHA12, TENE11, ZOLL90, _site, keys, managed, site, text  # noqa: F401
import intake_pdfs as pdfs


@pytest.fixture(autouse=True, scope="module")
def real_data_folder_untouched():
    yield
    conftest.no_real_library_touched()


Held = web.Held


# --- 1: a decision names the version it was made on ---------------------------------------------

def test_an_accept_of_the_version_that_a_recheck_is_replacing_is_refused(site):  # noqa: F811
    web.wait_idle(site.running)
    before = text(site.ws)
    proposal = site.ok("post", "/api/add/identifiers", {"queries": [pdfs.ZOLLER_DOI]})["proposals"][0]
    edited = proposal["proposed_raw"].replace("1053--1065", "1053--1066")
    held = Held(site.running)              # the recheck is slow: it waits behind this
    try:
        recheck = site.raw("POST", "/api/proposal/recheck", site.headers(post=True), json={"proposal": proposal["id"], "raw": edited})
        accept = site.raw("POST", "/api/proposal/accept", site.headers(post=True), json={"proposal": proposal["id"]})
        skip = site.raw("POST", "/api/proposal/remove-duplicate", site.headers(post=True), json={"proposal": proposal["id"]})
        assert recheck.status_code == accept.status_code == skip.status_code == 202
        assert text(site.ws) == before
    finally:
        held.done()
    new, error = site.settle(recheck)
    assert error is None and new["id"] != proposal["id"] and new["proposed_raw"] == edited
    result, error = site.settle(accept)
    assert result is None and error["kind"] == "StaleProposal" and error["current"] == new["id"]
    assert site.settle(skip)[1]["kind"] == "StaleProposal"
    assert text(site.ws) == before                                   # the text the person had not seen was not written
    # a chain of versions leads to the newest; only that one is acted on
    newer = site.ok("post", "/api/proposal/recheck", {"proposal": new["id"], "raw": proposal["proposed_raw"]})
    assert site.post("/api/proposal/accept", {"proposal": proposal["id"]})[1]["current"] == newer["id"]
    assert site.post("/api/proposal/accept", {"proposal": new["id"]})[1]["current"] == newer["id"]
    done = site.ok("post", "/api/proposal/accept", {"proposal": newer["id"]})
    assert done["written"] == ["Zoll90"] and text(site.ws).rstrip().endswith(ZOLL90)
    # accept-remaining leaves a superseded version alone and says so
    left = site.ok("post", "/api/proposal/accept-remaining", {"proposals": [proposal["id"], new["id"]]})
    assert left["accepted"] == [] and left["stale"] == [proposal["id"], new["id"]] and left["written"] == []


def test_names_are_settled_name_by_name_by_choice_not_by_text(tmp_path, monkeypatch):
    """A proposal whose author list is a question, made as tests/test_tui_add.py makes it from a
    recorded Crossref deposit, kept in the server's store as an offer of the send step is."""
    web.isolate(monkeypatch, tmp_path / "env")
    ws, item, raw = web.name_question(tmp_path / "library")
    running, client = web.start(ws)
    try:
        kept = routes.keep(running.app, item, in_library=True)
        assert kept["name_choices"] == [{"field": "author", "typed": ["A Cleeremans", "J L McCleeland"],
                                         "source": ["A Cleeremans", "J L McClelland"]}]
        body = {"proposal": kept["id"], "field": "author"}
        for bad in ({"picks": ["typed"]}, {"picks": ["typed", "theirs"]}, {"picks": ["typed", "source"], "names": ["X"]},
                    {"picks": ["typed", "source"], "field": "title"}):
            response = client.raw("POST", "/api/proposal/names", client.headers(post=True), json=dict(body, **bad))
            assert response.status_code in (200, 202, 400)
            if response.status_code != 400:
                assert client.settle(response)[1]["kind"] == "BadRequest"
        assert client.post("/api/proposal/names", dict(body, field="editor", picks=["typed", "source"]))[1]["kind"] == "BadRequest"
        settled = client.ok("post", "/api/proposal/names", dict(body, picks=["typed", "source"]))
        assert settled["id"] != kept["id"] and "McClelland" in settled["proposed_raw"] and "McCleeland" not in settled["proposed_raw"]
        assert settled["name_choices"] == [] and ws.bib.read_text(encoding="utf-8") == raw
        assert client.post("/api/proposal/names", dict(body, picks=["typed", "typed"]))[1]["kind"] == "StaleProposal"
        done = client.ok("post", "/api/proposal/accept", {"proposal": settled["id"]})
        assert done["written"] == ["CleeMcCl91"] and "McClelland" in ws.bib.read_text(encoding="utf-8")
    finally:
        running.stop()


# --- 2: an edit from outside is never hidden ----------------------------------------------------

def test_an_edit_by_another_process_is_seen_whatever_was_read_in_between(site):  # noqa: F811
    first = site.ok("get", "/api/entries")
    assert first["rows"][0][3] == "2012"
    script = ("import sys, pathlib; p = pathlib.Path(sys.argv[1]); "
              "p.write_text(p.read_text(encoding='utf-8').replace('{2012}', '{1999}'), encoding='utf-8')")
    subprocess.run([sys.executable, "-c", script, str(site.ws.bib)], check=True)
    # reads that have nothing to do with the list come first, and must not make the change look seen
    assert site.ok("get", "/api/entry", key="Game62")["key"] == "Game62"
    site.ok("get", "/api/state")
    site.ok("get", "/api/setup")
    site.ok("post", "/api/edit/preview", {"key": "Game62", "raw": GAME62})
    now = site.ok("get", "/api/revision")["revision"]
    assert now != first["revision"]
    again = site.ok("get", "/api/entries")
    assert again["revision"] == now and again["rows"][0][3] == "1999"
    assert site.ok("get", "/api/search", q="year:1999")["keys"] == ["Kaha12"]
    assert site.ok("get", "/api/revision")["revision"] == now            # and nothing moves it without a change
    assert site.ok("get", "/api/review-queue", all="1")["revision"] == now


# --- 6: bounded work and bytes ------------------------------------------------------------------

def test_the_worker_admits_a_bounded_number_joins_repeats_and_cancels_what_has_not_started():
    worker = jobs.Worker(lambda exc: {"kind": type(exc).__name__, "message": str(exc)})
    worker.start()
    gate, started = threading.Event(), threading.Event()
    try:
        first = worker.submit("hold", lambda say: (started.set(), gate.wait(60)) and "held")
        assert started.wait(30)
        waiting = [worker.submit(f"job {n}", lambda say, n=n: n) for n in range(jobs.MAX_PENDING)]
        with pytest.raises(jobs.Busy, match=f"{jobs.MAX_PENDING} requests are already waiting"):
            worker.submit("one too many", lambda say: None)
        assert worker.submit("job 3", lambda say: "again", single=True) is waiting[3]        # joined, not queued twice
        assert worker.cancel(waiting[5].id) == "cancelled" and worker.cancel(waiting[5].id) == "done"
        assert waiting[5].view()["error"]["kind"] == "Cancelled" and worker.cancel(first.id) == "running"
        assert worker.cancel("A" * 22) is None
        late = worker.submit("fits again", lambda say: "late")                                # the cancelled one made room
        gate.set()
        assert late.wait(30) and late.view()["result"] == "late"
        assert [job.view()["result"] for job in waiting if job is not waiting[5]] == [n for n in range(jobs.MAX_PENDING) if n != 5]
        assert "job 5" not in [label for label, _, _ in worker.history] and worker.overlaps == 0
    finally:
        gate.set()
        assert worker.stop() is True
    with pytest.raises(jobs.Closed):
        worker.submit("after the end", lambda say: None)


def test_finished_jobs_expire(monkeypatch):
    worker = jobs.Worker(lambda exc: {"kind": "x", "message": str(exc)})
    worker.start()
    try:
        old = worker.submit("old", lambda say: 1)
        assert old.wait(30) and worker.get(old.id) is old
        old.finished -= jobs.EXPIRY + 1                       # as if it had finished that long ago
        new = worker.submit("new", lambda say: 2)
        assert new.wait(30) and worker.get(old.id) is None and worker.get(new.id) is new
    finally:
        worker.stop()


def test_too_many_waiting_requests_are_refused_with_429_and_a_waiting_one_can_be_cancelled(site):  # noqa: F811
    web.wait_idle(site.running)
    held = Held(site.running)
    try:
        post = site.headers(post=True)
        same = [site.raw("POST", "/api/state/refresh", post, json={}).json()["job"] for _ in range(5)]
        assert len(set(same)) == 1                                           # a refresh that waits is not queued again
        answers = [site.raw("POST", "/api/check/format", post, json={}) for _ in range(jobs.MAX_PENDING + 4)]
        codes = [answer.status_code for answer in answers]
        assert codes == [202] * (jobs.MAX_PENDING - 1) + [429] * 5
        refused = answers[-1]
        assert refused.json()["error"]["kind"] == "TooManyJobs" and refused.headers["Retry-After"] == "2"
        for name, value in server.HEADERS.items():
            assert refused.headers[name] == value
        assert site.raw("GET", "/api/entries", site.headers()).status_code == 429          # reads wait in the same queue
        assert site.raw("GET", "/api/session", site.headers()).status_code == 200          # what needs no job still answers
        waiting = answers[3].json()["job"]
        assert site.raw("GET", f"/api/jobs/{waiting}/cancel", site.headers()).status_code == 405
        assert site.raw("POST", f"/api/jobs/{waiting}/cancel", site.headers(), json={}).status_code == 403     # no Origin
        cancelled = site.raw("POST", f"/api/jobs/{waiting}/cancel", post, json={}).json()["result"]
        assert cancelled == {"cancelled": True, "state": "cancelled"}
        view = site.raw("GET", f"/api/jobs/{waiting}", site.headers()).json()["result"]
        assert view["done"] and view["error"]["kind"] == "Cancelled" and not view["running"]
        running = site.raw("POST", f"/api/jobs/{held.job.id}/cancel", post, json={}).json()["result"]
        assert running == {"cancelled": False, "state": "running"}                       # a job that runs is left to finish
        assert site.raw("POST", "/api/jobs/" + "A" * 22 + "/cancel", post, json={}).status_code == 404
        assert site.raw("POST", "/api/check/format", post, json={}).status_code == 202   # the cancelled one made room
    finally:
        held.done()
    web.wait_idle(site.running)
    labels = [label for label, _, _ in site.running.app.worker.history]
    assert labels.count("POST /api/check/format") == jobs.MAX_PENDING - 1 and labels.count("POST /api/state/refresh") == 1


def test_the_store_keeps_bytes_and_counts_within_bounds_and_expires_what_is_unused():
    held = store.Store()
    try:
        limit = store.BYTES["pdf"]
        held.reserve("pdf", limit - 10)
        with pytest.raises(store.Full, match="no room for this upload"):
            held.reserve("pdf", 11)                               # promised bytes count before they arrive
        held.release("pdf", limit - 10)
        first = held.add_pdf(b"%PDF-" + b"x" * 1000)
        assert held.used("pdf") == 1005 and held.used() == 1005
        held.reserve("pdf", limit - 1005)                        # exactly what is left
        with pytest.raises(store.Full):
            held.reserve("pdf", 1)                               # the PDF in use is not dropped to make room
        held.release("pdf", limit - 1005)
        held.items[first][3] -= store.IDLE + 1                   # ... but one idle that long is
        folder = held.get("pdf", first)["folder"]
        held.items[first][3] -= store.IDLE + 1
        held.reserve("pdf", limit)
        assert not folder.exists() and held.used("pdf") == limit
        held.release("pdf", limit)
        with pytest.raises(store.Missing):
            held.get("pdf", first)
        # the total is bounded too, across kinds
        held.reserve("pdf", store.BYTES["pdf"])
        held.reserve("bundle", store.BYTES["bundle"])
        assert store.BYTES["pdf"] + store.BYTES["bundle"] + store.BYTES["export"] > store.TOTAL_BYTES
        held.release("pdf", store.BYTES["pdf"])
        held.release("bundle", store.BYTES["bundle"])
        # what nobody used for EXPIRY seconds is gone at the next use of the store
        proposal = held.put("proposal", {"n": 1})
        fresh = held.put("proposal", {"n": 2})
        held.items[proposal][3] -= store.EXPIRY + 1
        with pytest.raises(store.Missing):
            held.get("proposal", proposal)
        assert held.get("proposal", fresh) == {"n": 2}
        export = held.put("export", {"folder": held.new_folder()}, size=5)
        held.items[export][3] -= store.EXPIRY + 1
        held.put("search", [])
        assert export not in held.items and held.used("export") == 0
    finally:
        held.close()


def test_an_upload_beyond_the_quota_is_refused_before_its_body_is_read(site, monkeypatch):  # noqa: F811
    monkeypatch.setitem(store.BYTES, "pdf", 3000)
    monkeypatch.setitem(store.BYTES, "bundle", 100)
    held = site.running.app.store
    first = site.ok("upload", "/api/pdf/upload", b"%PDF-" + b"a" * 1995, "application/pdf")
    assert held.used("pdf") == 2000
    port = site.running.port
    head = (f"POST /api/pdf/upload HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\n"
            f"{web.TOKEN}: {site.token}\r\nContent-Type: application/pdf\r\nContent-Length: 1500\r\n\r\n")
    import socket
    with socket.create_connection(("127.0.0.1", port), timeout=20) as sock:      # the body is never sent: the answer still comes
        sock.sendall(head.encode())
        answer = b""
        while chunk := sock.recv(65536):
            answer += chunk
    assert answer.startswith(b"HTTP/1.1 413") and b"QuotaExceeded" in answer
    assert held.used("pdf") == 2000 and held.reserved.get("pdf", 0) == 0          # nothing stays reserved
    assert site.ok("upload", "/api/pdf/upload", b"%PDF-" + b"b" * 995, "application/pdf")["bytes"] == 1000
    assert site.upload("/api/pdf/upload", b"%PDF-", "application/pdf")[1]["kind"] == "QuotaExceeded"
    assert site.ok("get", "/api/session")                                        # and the server is as before
    assert site.raw("GET", f"/api/pdf/{first['pdf']}/file", site.headers()).status_code == 200
    kind = "application/octet-stream"
    one = site.ok("upload", "/api/export/upload", b"x" * 60, kind, name="a.tex")
    assert site.upload("/api/export/upload", b"y" * 60, kind, name="b.tex", bundle=one["bundle"])[1]["kind"] == "QuotaExceeded"
    assert held.get("bundle", one["bundle"])["files"] == ["a.tex"]
    # a refused upload gives its promise back, also when it is refused for another reason
    assert site.upload("/api/pdf/upload", b"not a pdf", "application/pdf")[1]["kind"] in ("BadRequest", "QuotaExceeded")
    assert held.reserved.get("pdf", 0) == 0 and held.reserved.get("bundle", 0) == 0


# --- 7: uploads that arrive together; shutdown --------------------------------------------------

def test_uploads_that_arrive_together_get_names_of_their_own_and_never_exceed_the_count(site):  # noqa: F811
    kind = "application/octet-stream"
    bundle = site.ok("upload", "/api/export/upload", b"0", kind, name="main.tex")["bundle"]

    def one(number):
        return site.upload("/api/export/upload", f"file {number}".encode(), kind, name="main.tex", bundle=bundle)

    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        answers = list(pool.map(one, range(1, 80)))
    taken = [result for result, error in answers if error is None]
    refused = [error for result, error in answers if error is not None]
    held = site.running.app.store.get("bundle", bundle)
    assert len(taken) == store.MAX_BUNDLE_FILES - 1 and len(refused) == 80 - store.MAX_BUNDLE_FILES
    assert all(error["kind"] == "BadRequest" and "At most" in error["message"] for error in refused)
    names = [result["name"] for result in taken]
    assert len(set(names)) == len(names) and "main.tex" not in names
    on_disk = {path.name: path.read_bytes() for path in held["folder"].iterdir()}
    assert sorted(on_disk) == sorted(held["files"]) == sorted(names + ["main.tex"]) and on_disk["main.tex"] == b"0"
    assert sorted(on_disk[name] for name in names) == sorted(f"file {n}".encode() for n in range(1, 80)
                                                            if f"file {n}".encode() in on_disk.values())
    assert site.running.app.store.used("bundle") == sum(len(data) for data in on_disk.values())


def test_stopping_cancels_what_waits_and_removes_the_folder_only_after_the_running_job(tmp_path, monkeypatch):
    web.isolate(monkeypatch, tmp_path / "env")
    running, client = web.start(web.make_library(tmp_path / "library", ZOLL90))
    web.wait_idle(running)
    folder = running.app.store.folder
    client.ok("upload", "/api/pdf/upload", b"%PDF-1.4\n", "application/pdf")
    seen = {}
    release, started = threading.Event(), threading.Event()

    def slow(say):
        started.set()
        release.wait(60)
        seen["folder at the end of the job"] = folder.exists() and any(folder.iterdir())
        return "finished"

    job = running.app.worker.submit("test: slow", slow)
    assert started.wait(30)
    waiting = [client.raw("POST", "/api/check/format", client.headers(post=True), json={}).json()["job"] for _ in range(3)]
    queued = [running.app.worker.get(found) for found in waiting]
    stopper = threading.Thread(target=running.stop)
    stopper.start()
    time.sleep(0.5)
    assert stopper.is_alive() and folder.exists()                 # stopping waits for the job that runs
    assert all(found.done and found.error["kind"] == "Cancelled" for found in queued)
    with pytest.raises(jobs.Closed):
        running.app.worker.submit("late", lambda say: None)
    release.set()
    stopper.join(30)
    assert not stopper.is_alive() and job.result == "finished"
    assert seen == {"folder at the end of the job": True} and not folder.exists()
    assert [label for label, _, _ in running.app.worker.history if label.startswith("POST")] == []


# --- 8: update, backups and undo are the managed library's only ---------------------------------

def test_a_library_the_user_chose_is_never_updated_and_the_managed_one_is_left_alone(tmp_path, monkeypatch):
    from test_update import advance
    web.isolate(monkeypatch, tmp_path / "env")
    monkeypatch.chdir(tmp_path)
    managed_ws = api.ensure_library()                               # a managed library exists, and is behind its upstream
    advance(Path(os.environ["CDLBIB_UPSTREAM"]), "A second entry", **{"cdl.bib": TENE11 + "\n\n" + ZOLL90 + "\n"})
    api.update(managed_ws, force=True)
    backups_before = [item.stamp for item in api.backups()]
    advance(Path(os.environ["CDLBIB_UPSTREAM"]), "A third entry", **{"cdl.bib": TENE11 + "\n\n" + ZOLL90 + "\n\n" + KAHA12 + "\n"})
    managed_text = managed_ws.bib.read_text(encoding="utf-8")
    assert backups_before and "Kaha12" not in managed_text

    chosen = web.make_library(tmp_path / "chosen", GAME62)
    monkeypatch.setenv("CDLBIB_LIBRARY", str(chosen.root))
    running, client = web.start(chosen)
    try:
        session = client.ok("get", "/api/session")
        assert session["managed"] is False and session["origin"] == "CDLBIB_LIBRARY"
        said = session["not_managed"]
        assert prompts.CHOSEN_BY["CDLBIB_LIBRARY"] in said and str(chosen.root) in said and "does not update it" in said
        state = client.ok("get", "/api/state")
        assert state["managed"] is False and state["not_managed"] == said and state["new_commits"] is None
        for method, path, body in (("post", "/api/update", {}), ("get", "/api/backups", None), ("post", "/api/undo", {}),
                                   ("post", "/api/undo", {"stamp": backups_before[0]}),
                                   ("post", "/api/update/decide", {"decision": "A" * 22, "choice": "discard"})):
            result, error = client.post(path, body) if method == "post" else client.get(path)
            assert result is None and error == {"kind": "NotManaged", "message": said}, path
        assert managed_ws.bib.read_text(encoding="utf-8") == managed_text       # the managed library was not updated ...
        assert [item.stamp for item in api.backups()] == backups_before         # ... nor restored, nor backed up
        assert chosen.bib.read_text(encoding="utf-8") == GAME62 + "\n\n"
    finally:
        running.stop()


def test_the_managed_library_is_updated_as_the_library_in_use(managed):  # noqa: F811
    client, upstream = managed
    source = Path(routes.__file__).read_text(encoding="utf-8")
    assert "api.update(app.ws," in source and "api.update(force" not in source and "Workspace(" not in source
    assert client.ok("get", "/api/session")["not_managed"] is None and client.ok("get", "/api/state")["not_managed"] is None


# --- 11: the whole review queue -----------------------------------------------------------------

def test_the_review_queue_is_paged_and_searched_in_full(tmp_path, monkeypatch):
    web.isolate(monkeypatch, tmp_path / "env")
    entries = [complete.render("article", f"Auth{n:03d}", dict(author=f"A Author{n}", title=f"Paper number {n} on {'memory' if n % 7 == 0 else 'vision'}",
                                                              journal="Journal of Tests", year=str(1900 + n), volume="1", pages="1--2"))
               for n in range(620)]
    ws = web.make_library(tmp_path / "library", *entries)
    running, client = web.start(ws)
    try:
        first = client.ok("get", "/api/review-queue", all="1")
        assert (first["total"], first["offset"], first["limit"], len(first["entries"])) == (620, 0, 100, 100)
        seen = []
        for offset in range(0, 700, 200):
            page = client.ok("get", "/api/review-queue", all="1", offset=offset, limit=200)
            seen += [item["key"] for item in page["entries"]]
        assert seen == [f"Auth{n:03d}" for n in range(620)]                      # every entry is reachable, in the file's order
        found = client.ok("get", "/api/review-queue", all="1", q="title:memory")
        assert found["total"] == 89 and [item["key"] for item in found["entries"]][:3] == ["Auth000", "Auth007", "Auth014"]
        last = client.ok("get", "/api/review-queue", all="1", q="key:Auth619 year:2519")
        assert [item["key"] for item in last["entries"]] == ["Auth619"]
        assert client.ok("get", "/api/review-queue", all="1", q="nothing-like-it")["total"] == 0
        for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"offset": "x"}):
            assert client.raw("GET", "/api/review-queue", client.headers(), params=dict(all="1", **bad)).status_code == 400
    finally:
        running.stop()
