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
        other = []
        thread = threading.Thread(target=lambda: other.append(pytest.raises(store.Full, held.reserve, "pdf", 11)))
        thread.start()
        thread.join()
        assert other and "no room" in str(other[0].value)         # bytes promised to one request count for another
        held.release()
        assert held.used("pdf") == 0
        first = held.add_pdf(b"%PDF-" + b"x" * 1000)
        assert held.used("pdf") == 1005 and held.used() == 1005
        held.reserve("pdf", limit - 1005)                        # exactly what is left
        held.release()
        with pytest.raises(store.Full):
            held.reserve("pdf", limit - 1004)                    # one byte more: the PDF in use is not dropped to make room
        held.items[first][3] -= store.IDLE + 1                   # ... but one idle that long is
        folder = held.items[first][1]["folder"]
        held.reserve("pdf", limit)
        assert not folder.exists() and held.used("pdf") == limit
        held.release()
        with pytest.raises(store.Missing):
            held.get("pdf", first)
        assert store.BYTES["pdf"] + store.BYTES["bundle"] + store.BYTES["export"] > store.TOTAL_BYTES      # the total binds too
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


def test_admission_is_exact_at_the_boundaries_of_count_bytes_and_total(monkeypatch):
    """Count and bytes, the incoming one included, are decided under the lock before anything is
    written: the last one that fits is taken, the next is refused and leaves nothing behind."""
    monkeypatch.setitem(store.COUNTS, "pdf", 20)
    held = store.Store()
    try:
        made = [held.add_pdf(b"%PDF-" + bytes([n])) for n in range(20)]
        assert len(set(made)) == 20 and held.used("pdf") == 120
        with pytest.raises(store.Full, match="at most 20 of this kind"):
            held.add_pdf(b"%PDF-x")                                             # the 21st
        with pytest.raises(store.Full):
            held.reserve("pdf", 1, count=1)                                      # ... refused before its body is read, too
        assert len(list(held.folder.iterdir())) == 20 and held.used("pdf") == 120 and all(found in held.items for found in made)
        # bytes of one kind: exactly the limit fits, one byte more does not
        monkeypatch.setitem(store.BYTES, "bundle", 100)
        bundle, _, _ = held.add_manuscript(None, "a.tex", b"x" * 60)
        held.add_manuscript(bundle, "b.tex", b"y" * 40)
        assert held.used("bundle") == 100
        with pytest.raises(store.Full):
            held.add_manuscript(bundle, "c.tex", b"z")
        with pytest.raises(store.Full):
            held.add_manuscript(None, "d.tex", b"")                              # (nor a new bundle beside it, were the count full)
            held.add_manuscript(None, "e.tex", b"z")
        assert sorted(path.name for path in held.get("bundle", bundle)["folder"].iterdir()) == ["a.tex", "b.tex"]
        # the total, across kinds: an export that would pass it is not kept
        monkeypatch.setattr(store, "TOTAL_BYTES", held.used() + 50)
        fits = held.put("export", {"folder": held.new_folder()}, size=50)
        assert held.used() == store.TOTAL_BYTES
        with pytest.raises(store.Full):
            held.put("export", {"folder": held.new_folder()}, size=1)
        assert held.used() == store.TOTAL_BYTES and fits in held.items
        # twenty-four threads at the last free place: exactly one gets it
        held.drop("pdf", made[0])
        monkeypatch.setattr(store, "TOTAL_BYTES", 10 ** 9)
        results = []

        def one():
            try:
                results.append(held.add_pdf(b"%PDF-!"))
            except store.Full:
                results.append(None)
        threads = [threading.Thread(target=one) for _ in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len([found for found in results if found]) == 1 and sum(1 for item in held.items.values() if item[0] == "pdf") == 20
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


def test_requests_that_arrive_faster_than_the_server_takes_them_are_all_answered(tmp_path, monkeypatch):
    """Seen on a slow GitHub runner: one of 24 uploads sent together ended with "Connection
    reset by peer". Here the real server takes each connection a third of a second late, as
    its thread does on a busy computer, while 24 threads send 80 requests. Every one is
    answered. (With http.server's own queue of 5 waiting connections, Linux resets about a
    fifth of them.)"""
    web.isolate(monkeypatch, tmp_path / "env")
    running = server.start(web.make_library(tmp_path / "library", ZOLL90))
    assert running.httpd.request_queue_size >= 64
    take = running.httpd.get_request

    def late():
        time.sleep(0.3)
        return take()

    running.httpd.get_request = late
    running.serve_in_thread()
    client = web.Client(running)
    try:
        kind = "application/octet-stream"
        bundle = client.ok("upload", "/api/export/upload", b"0", kind, name="main.tex")["bundle"]

        def one(number):                    # the uploads of the test above, which is where it was seen
            try:
                return client.raw("POST", "/api/export/upload", client.headers(post=True, **{"Content-Type": kind}),
                                  data=f"file {number}".encode(), params={"name": "main.tex", "bundle": bundle}).status_code
            except Exception as exc:        # the failure this test is about is an exception of requests
                return f"{type(exc).__name__}: {exc}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            answers = list(pool.map(one, range(1, 80)))
        # Each request got the server's answer: taken (200), or refused as one file too many (400).
        assert set(answers) <= {200, 400}, [answer for answer in answers if answer not in (200, 400)][:3]
        assert answers.count(200) == store.MAX_BUNDLE_FILES - 1
    finally:
        running.stop()


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


# --- the shared decisions of the core (merged 2026-10-05) ---------------------------------------

def test_model_evidence_that_could_not_be_stored_is_kept_shown_and_retried(site, tmp_path):  # noqa: F811
    """A real failure: the verification database is made read-only, so the entry is written and
    the evidence cannot be stored; then it is made writable again and the retry stores it."""
    if not pdfs.pdflatex():
        pytest.skip("pdflatex is not installed: the test PDF cannot be typeset")
    if os.geteuid() == 0:
        pytest.skip("running as root: no file is unwritable")
    from cdlbib import intake
    from cdlbib.source_passages import materialize
    from test_intake_model import SELECTED
    web.wait_idle(site.running)
    sent = site.ok("upload", "/api/pdf/upload", pdfs.build("unknown", tmp_path / "pdf").read_bytes(), "application/pdf")
    site.ok("post", "/api/pdf/read", {"pdf": sent["pdf"]})
    read = site.running.app.store.get("pdf", sent["pdf"])["intake"]
    answer = materialize({"fields": SELECTED, "uncertainties": []}, read.pages[:intake.MODEL_PAGES])
    answer["provider_trace"] = {"provider": "test selection", "model": None}
    kept = routes.keep(site.running.app, intake.proposal_from_findings(site.ws, read, answer, "dartmouth"), pdf=sent["pdf"])
    assert site.ok("get", "/api/evidence/pending") == {"pending": []}
    locked = [path for path in site.ws.work.glob("verification.sqlite3*")]
    for path in locked:
        path.chmod(0o444)
    try:
        done = site.ok("post", "/api/proposal/accept", {"proposal": kept["id"]})
        web.wait_idle(site.running)       # the preparation that follows a write tries the evidence again, and fails too
        assert site.post("/api/proposal/accept", {"proposal": kept["id"]})[1]["kind"] == "AlreadyWritten"
        web.wait_idle(site.running)
    finally:
        for path in locked:
            path.chmod(0o644)
    assert done["written"] == ["ExamSamp19"] and done["evidence_stored"] is False and done["evidence_error"]
    assert done["outcomes"] == [{"index": 0, "key": "ExamSamp19", "status": "written", "reason": ""}]
    assert "ExamSamp19" in keys(site.ws)
    waiting = site.ok("get", "/api/evidence/pending")["pending"]
    assert waiting == [{"key": "ExamSamp19", "fingerprint": done["fingerprint"], "stale": False}]
    assert site.ok("get", "/api/proposal", proposal=kept["id"])["written"] == "ExamSamp19"       # the card is kept
    for name in ("database", "fingerprint", "evidence"):
        assert site.raw("POST", "/api/evidence/retry", site.headers(post=True), json={"key": "ExamSamp19", name: "x"}).status_code == 400
    again = site.ok("post", "/api/evidence/retry", {"key": "ExamSamp19", "proposal": kept["id"]})
    assert again == {"key": "ExamSamp19", "fingerprint": done["fingerprint"], "evidence_stored": True, "evidence_error": None}
    assert site.ok("get", "/api/evidence/pending") == {"pending": []}
    detail = site.ok("get", "/api/entry", key="ExamSamp19")
    assert detail["result"]["external_evidence"]["pdf_sha256"] == read.sha256 and "human_review" not in detail["result"]
    assert site.get("/api/proposal", proposal=kept["id"])[1]["kind"] == "NotFound"               # and now it is done with
    assert site.post("/api/evidence/retry", {"key": "ExamSamp19"})[1]["kind"] == "CdlbibError"   # nothing waits any more


def test_the_writers_own_outcomes_decide_which_cards_go(site):  # noqa: F811
    """Two proposals for one work, both acceptable when they were made: the writer writes the
    first and refuses the second, and says which by its place in the list."""
    one = site.ok("post", "/api/add/identifiers", {"queries": [pdfs.ZOLLER_DOI]})["proposals"][0]
    two = site.ok("post", "/api/add/identifiers", {"queries": [pdfs.ZOLLER_DOI]})["proposals"][0]
    assert one["acceptable"] and two["acceptable"] and one["key_proposed"] == two["key_proposed"] == "Zoll90"
    done = site.ok("post", "/api/proposal/accept-remaining", {"proposals": [one["id"], two["id"]]})
    assert [(item["index"], item["status"]) for item in done["outcomes"]] == [(0, "written"), (1, "refused")]
    assert done["accepted"] == [one["id"]] and done["written"] == ["Zoll90"]
    (left,) = done["not_written"]
    assert left["id"] == two["id"] and left["reason"] == done["outcomes"][1]["reason"] and left["reason"]
    assert text(site.ws).count("@article{Zoll90,") == 1
    assert site.get("/api/proposal", proposal=one["id"])[1]["kind"] == "NotFound"
    kept = site.ok("get", "/api/proposal", proposal=two["id"])                    # the refused one is still there
    assert kept["proposed_raw"] == ZOLL90
    single = site.ok("post", "/api/proposal/accept", {"proposal": two["id"]})     # ... and a single accept says why as well
    assert single["written"] == [] and single["outcomes"][0]["status"] == "refused" and single["outcomes"][0]["reason"]
    assert site.ok("get", "/api/proposal", proposal=two["id"])["id"] == two["id"]


def test_a_fork_is_asked_about_with_the_cores_question_and_made_only_on_a_yes(site):  # noqa: F811
    """As far as this goes without creating a fork: the send itself is replaced by a job of the
    test's own that refuses as api.send does when the user has no fork (a real
    errors.PublishRefused), run through the same routes.guarded and api.attempt as a request."""
    from cdlbib import deps
    from cdlbib.errors import PublishRefused
    web.wait_idle(site.running)
    route = next(item for item in routes.ROUTES if item.path == "/api/send")
    refusal = PublishRefused("@someone has no fork of ContextLab/CDL-bibliography.", needs_fork=True, upstream="ContextLab/CDL-bibliography")
    calls = []

    def handler(app, a, say):
        calls.append(a["allow_fork_creation"])
        if not a["allow_fork_creation"]:
            raise refusal
        return {"sent": True}

    stand_in = routes.Route(route.method, route.path, route.api, handler, route.args)

    def submit(**given):
        args = routes.arguments(stand_in, given)
        job = site.running.app.worker.submit("test: send", routes.guarded(site.running.app, stand_in, args))
        assert job.wait(30)
        return job.view()

    deps.set_ask(True)
    try:
        asked = submit()["error"]
        assert asked["kind"] == "NeedsConfirmation" and asked["needs_confirmation"] == "fork"
        assert asked["question"] == prompts.fork_question(refusal) and asked["upstream"] == "ContextLab/CDL-bibliography"
        assert calls == [False]                                             # nothing was created to ask the question
        said = submit(allow_fork_creation=True)
        assert said["result"] == {"sent": True} and calls == [False, False, True] and said["lines"] == []
    finally:
        deps.set_ask(False)
    del calls[:]
    plain = submit()                                                         # not asked to ask: said, then done
    assert plain["result"] == {"sent": True} and calls == [False, True] and plain["lines"] == [prompts.fork_line(refusal)]
    source = Path(routes.__file__).read_text(encoding="utf-8") + (Path(routes.__file__).parent / "static/js/api.js").read_text(encoding="utf-8")
    assert "Install it now" not in source and "Create one now" not in source and "creating your fork" not in source
    assert "deps.install" not in source and "api.attempt(" in source


def test_whether_completion_has_anything_to_do_is_the_cores_answer(site):  # noqa: F811
    due = site.ok("get", "/api/send/due")
    assert due == api.as_data(api.completion_due(site.ws)) and due["reachable"] is False and due["keys"] == []
    assert due["problem"].startswith("Entries could not be selected for completion")
    for name in ("reference", "database"):
        assert site.raw("GET", "/api/send/due", site.headers(), params={name: "x"}).status_code == 400


def test_a_force_field_is_refused_in_the_cores_words(site):  # noqa: F811
    forced = KAHA12.replace("\tYear = {2012}}", "\tForce = {True},\n\tYear = {2012}}")
    assert forced != KAHA12
    preview = site.ok("post", "/api/edit/preview", {"key": "Kaha12", "raw": forced})
    assert any(prompts.FORCE_REFUSED in problem for problem in preview["problems"])
    assert site.post("/api/edit/save", {"preview": preview["preview"]})[1]["kind"] == "EditRefused"
    assert text(site.ws).count("Force") == 0
    site.ws.bib.write_text(text(site.ws).replace(KAHA12, forced), encoding="utf-8")          # typed in by another program
    found = site.ok("post", "/api/check/format")
    assert found["ok"] is False and found["forced"] == [f"Kaha12: {prompts.FORCE_REFUSED}"] and "Kaha12" in found["errors"]
    assert f"Kaha12: {prompts.FORCE_REFUSED}" in found["log"]


# --- the last review (2026-10-05) ---------------------------------------------------------------

def test_a_job_that_outlives_the_wait_keeps_its_files_and_the_folder_is_named(tmp_path, monkeypatch, capfd):
    web.isolate(monkeypatch, tmp_path / "env")
    running, client = web.start(web.make_library(tmp_path / "library", ZOLL90))
    web.wait_idle(running)
    folder = running.app.store.folder
    client.ok("upload", "/api/pdf/upload", b"%PDF-1.4\n", "application/pdf")
    release, started, seen = threading.Event(), threading.Event(), {}

    def slow(say):
        started.set()
        release.wait(60)
        seen["files when the job ended"] = sorted(path.name for path in folder.rglob("*") if path.is_file())
        return "finished"

    job = running.app.worker.submit("test: slow", slow)
    assert started.wait(30)
    try:
        assert running.stop(wait=0.3) is False                       # the worker did not stop within the wait
        said = capfd.readouterr().err
        assert str(folder) in said and "test: slow" in said and "still running after 0.3 seconds" in said
        assert folder.exists() and [path.name for path in folder.rglob("*.pdf")] == ["upload.pdf"]      # nothing was deleted under it
    finally:
        release.set()
    assert job.wait(30) and seen == {"files when the job ended": ["upload.pdf"]}
    assert running.app.close(wait=30) is True and not folder.exists()    # once it has stopped, the folder goes


def test_a_candidate_found_for_a_pdf_keeps_the_pdf_with_its_proposal(site, tmp_path):  # noqa: F811
    if not pdfs.pdflatex():
        pytest.skip("pdflatex is not installed: the test PDF cannot be typeset")
    sent = site.ok("upload", "/api/pdf/upload", pdfs.build("title", tmp_path / "pdf").read_bytes(), "application/pdf")
    site.ok("post", "/api/pdf/read", {"pdf": sent["pdf"]})
    found = site.ok("post", "/api/pdf/lookup", {"pdf": sent["pdf"]})
    assert not found["matched"] and found["candidates"] and found["search"]
    assert site.running.app.store.get("search", found["search"])["pdf"] == sent["pdf"]
    chosen = site.ok("post", "/api/add/choose", {"search": found["search"], "index": 0})["proposals"][0]
    assert chosen["pdf"] == sent["pdf"]                                 # shown beside the PDF's first page, like any other from it
    if chosen["proposed_raw"]:
        again = site.ok("post", "/api/proposal/recheck", {"proposal": chosen["id"], "raw": chosen["proposed_raw"]})
        assert again["pdf"] == sent["pdf"] and again["id"] != chosen["id"]
    plain = site.ok("post", "/api/add/search", {"title": "Attention is all you need", "authors": ["Vaswani"]})
    assert site.running.app.store.get("search", plain["search"])["pdf"] is None


def test_a_save_is_bound_to_the_entry_as_it_was_opened(site):  # noqa: F811
    opened = site.ok("get", "/api/entry", key="Kaha12")
    # another program changes the entry after the editor was opened and before the first preview
    site.ws.bib.write_text(text(site.ws).replace("Oxford University Press", "Oxford Univ. Press"), encoding="utf-8")
    disk = text(site.ws)
    mine = KAHA12.replace("{2012}", "{2013}")
    preview = site.ok("post", "/api/edit/preview", {"key": "Kaha12", "raw": mine, "opened": opened["fingerprint"]})
    assert preview["changed_on_disk"] is True and preview["fingerprint"] != opened["fingerprint"]
    result, error = site.post("/api/edit/save", {"preview": preview["preview"]})
    assert error["kind"] == "EditRefused" and text(site.ws) == disk      # the other program's edit was not overwritten
    # reloaded: the entry as it is now is the baseline, and the save goes through
    now = site.ok("get", "/api/entry", key="Kaha12")
    again = site.ok("post", "/api/edit/preview", {"key": "Kaha12", "raw": now["raw"].replace("{2012}", "{2013}"), "opened": now["fingerprint"]})
    assert again["changed_on_disk"] is False
    assert site.ok("post", "/api/edit/save", {"preview": again["preview"]})["written"] == ["Kaha12"]
    assert "Oxford Univ. Press" in text(site.ws) and "{2013}" in text(site.ws)
    assert site.raw("POST", "/api/edit/preview", site.headers(post=True), json={"key": "Kaha12", "raw": mine, "opened": "../x"}).status_code == 400


def _make_due():
    """Move the managed library's last check two days back, as time would (state.json is cdlbib's own file)."""
    import datetime
    import json
    from cdlbib import library
    path = library.home() / "state.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["last_check"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).isoformat()
    data.pop("last_attempt", None)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert library.check_due()


def test_the_daily_update_check_runs_once_at_start_for_the_managed_library(tmp_path, monkeypatch):
    from cdlbib import library
    from test_update import advance
    web.isolate(monkeypatch, tmp_path / "env")
    monkeypatch.chdir(tmp_path)
    ws = api.ensure_library()
    upstream = Path(os.environ["CDLBIB_UPSTREAM"])
    advance(upstream, "A second entry", **{"cdl.bib": TENE11 + "\n\n" + ZOLL90 + "\n"})
    _make_due()
    running, client = web.start(ws)
    try:
        web.wait_idle(running)
        labels = [label for label, _, _ in running.app.worker.history]
        assert labels[:2] == ["prepare", "daily update check"] and labels.count("daily update check") == 1
        job = client.ok("get", "/api/session")["daily"]
        done, error = client.follow(job)
        assert error is None and done["action"] == "updated" and done["new_commits"] == 1 and done["message"]
        assert keys(ws) == ["TeneEtal11", "Zoll90"] and not library.check_due()
        assert client.ok("get", "/api/session")["daily"] is None            # shown once
    finally:
        running.stop()
    # a second start within the day: the check is not due, nothing is fetched, nothing changes
    advance(upstream, "A third entry", **{"cdl.bib": TENE11 + "\n\n" + ZOLL90 + "\n\n" + KAHA12 + "\n"})
    running, client = web.start(ws)
    try:
        web.wait_idle(running)
        done, error = client.follow(client.ok("get", "/api/session")["daily"])
        assert error is None and done["action"] == "not_due" and done["message"] == ""
        assert keys(ws) == ["TeneEtal11", "Zoll90"]
        assert client.ok("get", "/api/state")["new_commits"] == 0           # as last fetched: the upstream was not asked
    finally:
        running.stop()
    # due again, with unsent work: nothing is touched, and the question is the one the update asks
    ws.bib.write_text(text(ws) + "\n" + GAME62 + "\n", encoding="utf-8")
    edited = text(ws)
    _make_due()
    running, client = web.start(ws)
    try:
        web.wait_idle(running)
        done, error = client.follow(client.ok("get", "/api/session")["daily"])
        assert done is None and error["kind"] == "UpdateNeedsDecision" and text(ws) == edited
        assert error["question"].startswith("A newer version of the bibliography is available (1 new commit)")
        kept = client.ok("post", "/api/update/decide", {"decision": error["decision"], "choice": "keep"})
        assert kept["action"] == "left_alone" and text(ws) == edited
    finally:
        running.stop()


def test_no_daily_check_for_a_library_the_user_chose(site):  # noqa: F811
    web.wait_idle(site.running)
    assert site.ok("get", "/api/session")["daily"] is None
    assert "daily update check" not in [label for label, _, _ in site.running.app.worker.history]


def test_the_ci_wheel_check_reads_the_servers_own_static_table():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/autocheck.yml").read_text(encoding="utf-8")
    assert "server.STATIC" in workflow and "'proposal', 'send'" not in workflow
