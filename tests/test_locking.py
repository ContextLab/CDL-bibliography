"""The write lock of every library, and what a killed writer leaves.

Real processes: two writers started together on one library; a writer that waits while this
process holds the lock; writers killed with SIGKILL between two file replacements (stopped
there by an audit hook in the child's own interpreter, as tests/test_write_boundaries.py
does: no hook in the product). Real files and the real managed library (local bare
upstream). No mocks.
"""
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

import conftest
from cdlbib import api, complete, desk, library, writer
from cdlbib.errors import CdlbibError, IdentityUnavailable
from cdlbib.verification import load_entries
from cdlbib.workspace import Workspace

from test_library import managed  # noqa: F401
from test_publish import GIT_ENV

ZOLL90 = conftest.ZOLL90
KAHA12 = ("@book{Kaha12,\n\tAddress = {New York, {NY}},\n\tAuthor = {M J Kahana},\n\tPublisher = {Oxford University "
          "Press},\n\tTitle = {Foundations of human memory},\n\tYear = {2012}}")
TEXT = "% two entries\n" + ZOLL90 + "\n\n" + KAHA12 + "\n"
RENAMED = ZOLL90.replace("{Zoll90,", "{Zoller1990,")


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "shared library"
    root.mkdir()
    (root / "cdl.bib").write_text(TEXT, encoding="utf-8")
    return Workspace(root)


def child(code, cwd):
    return subprocess.Popen([sys.executable, "-u", "-c", code], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=dict(os.environ, **GIT_ENV))


def line(process, seconds=30):
    assert select.select([process.stdout], [], [], seconds)[0], "the child did not get there: " + (
        process.stderr.read() if process.poll() is not None else "still running")
    return process.stdout.readline().strip()


def finish(*processes):
    for process in processes:
        if process.poll() is None:
            process.kill()
            process.wait()


HEAD = """
import sys, os, signal, time
from pathlib import Path
from cdlbib import api, complete, library
from cdlbib.errors import CdlbibError, EditRefused
from cdlbib.workspace import Workspace
ws = Workspace({root!r})
"""


# --- where the lock is -------------------------------------------------------------------------

def test_every_library_has_a_lock_and_the_holder_reenters(ws, tmp_path, managed):
    assert not ws.work.exists()
    with library.transaction(ws):
        assert (ws.work / "lock").is_file()
        with library.transaction(ws):                            # the holder is not locked out
            applied = api.save_edit(ws, "Kaha12", KAHA12.replace("2012", "2013"),
                                    load_entries(ws.bib)["Kaha12"]["fingerprint"])
        assert applied.written == ["Kaha12"]
        assert (ws.work / "lock").is_file()
    assert not (ws.work / "lock").exists() and (ws.work / "edits").is_dir()      # the lock leaves nothing behind
    named = Workspace.for_bib(tmp_path / "papers" / "refs.bib")
    named.bib.parent.mkdir()
    named.bib.write_text(KAHA12 + "\n", encoding="utf-8")
    with library.transaction(named):
        assert (tmp_path / "papers" / ".bibcheck" / "lock").is_file()
    assert not (tmp_path / "papers" / ".bibcheck").exists()      # not even the folder, when the lock made it
    home, _ = managed
    mine = Workspace(library.download())
    with library.transaction(mine):
        assert (home / "lock").is_file() and not (mine.work / "lock").exists()      # the managed lock, as before
        with library.transaction(ws):                            # two libraries, two locks
            pass


def test_a_folder_that_is_not_there_or_cannot_be_written_is_not_locked(tmp_path):
    absent = Workspace(tmp_path / "no such folder")
    with library.transaction(absent):
        pass
    assert not (tmp_path / "no such folder").exists()
    with pytest.raises(CdlbibError):
        complete.apply(absent, [])
    assert not (tmp_path / "no such folder").exists()
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    (sealed / "cdl.bib").write_text(KAHA12 + "\n", encoding="utf-8")
    sealed.chmod(0o555)
    try:
        with library.transaction(Workspace(sealed)):
            assert api.entries(Workspace(sealed))[0].key == "Kaha12"
        assert not (sealed / ".bibcheck").exists()
    finally:
        sealed.chmod(0o755)


# --- two writers -------------------------------------------------------------------------------

WRITER = HEAD + """
name, count = {name!r}, {count}
while not Path({go!r}).exists():
    time.sleep(0.005)
done = 0
for number in range(count):
    raw = complete.render('misc', f'{{name}}{{number:02d}}', dict(author=f'{{name}} Writer', title=f'Note {{number}} of {{name}}',
                                                                howpublished='Lab notebook', year='2020'))
    done += api.save_edit(ws, None, raw).written == [f'{{name}}{{number:02d}}']
    while True:                                                 # and both keep rewriting one shared entry
        current = api.entry(ws, 'Kaha12')
        try:
            api.save_edit(ws, 'Kaha12', current.raw.replace('Title = {{', 'Title = {{' + name[0]), current.fingerprint)
            break
        except EditRefused:                                     # the other writer got there first: open it again
            pass
print('DONE', done, flush=True)
"""


def test_two_processes_writing_at_once_lose_nothing(ws, tmp_path):
    count, go = 12, tmp_path / "go"
    writers = [child(WRITER.format(root=str(ws.root), name=name, count=count, go=str(go)), ws.root)
               for name in ("Alpha", "Bravo")]
    try:
        time.sleep(1.0)                                          # both are up and waiting for the signal
        assert all(process.poll() is None for process in writers)
        go.write_text("go", encoding="utf-8")
        results = [process.communicate(timeout=180) for process in writers]
    finally:
        finish(*writers)
    for process, (out, err) in zip(writers, results):
        assert process.returncode == 0, err
        assert out.strip() == f"DONE {count}", out + err         # no save was refused or lost
    found = load_entries(ws.bib)
    expected = {f"{name}{number:02d}" for name in ("Alpha", "Bravo") for number in range(count)}
    assert set(found) == expected | {"Zoll90", "Kaha12"} and found["Zoll90"]["raw"] == ZOLL90
    title = found["Kaha12"]["fields"]["title"]                   # every one of the 24 shared edits is in it
    assert title.endswith("Foundations of human memory") and len(title) == len("Foundations of human memory") + 2 * count
    assert sorted(title[:2 * count]) == ["A"] * count + ["B"] * count
    assert ws.bib.read_text(encoding="utf-8").startswith("% two entries\n" + ZOLL90 + "\n\n")
    edits = ws.work / "edits"
    assert len(list(edits.glob("*-cdl.bib"))) == writer.KEEP_EDITS and not (edits / writer.PENDING).exists()
    assert not list(ws.root.glob(".cdl.bib-*")) and writer.interrupted(ws) is None


WAITING = HEAD + """
opened = api.entry(ws, {key!r}).fingerprint
print('ready', flush=True)
try:
    if {mode!r} == 'edit':
        result = api.save_edit(ws, {key!r}, {raw!r}, opened).written
    elif {mode!r} == 'approve':
        result = api.approve(ws, {key!r}, opened, 'a source', 'a note')['status']
    else:
        fields = dict(author='A Smith', title='A new paper', journal='Nature', year='2020')
        item = complete.Proposal(key_proposed='Smit20', entry_type='article', proposed_raw=complete.render('article', 'Smit20', fields),
                                 changes=[complete.FieldChange(k, None, v, 'fixture', 'filled') for k, v in fields.items()])
        result = complete.apply(ws, [item]).written
    print('RESULT', result, flush=True)
except CdlbibError as exc:
    print('REFUSED', type(exc).__name__, exc, flush=True)
"""


def held_then(ws, mode, key, raw, meanwhile):
    """Start a writer while this process holds the library's lock; it must wait. ``meanwhile``
    runs under the lock; then the lock is released and the writer's one line is returned."""
    with library.transaction(ws):
        process = child(WAITING.format(root=str(ws.root), mode=mode, key=key, raw=raw), ws.root)
        try:
            assert line(process) == "ready"
            time.sleep(0.6)
            assert process.poll() is None, process.stderr.read()         # waiting for the lock, not finished
            assert not select.select([process.stdout], [], [], 0)[0]
            before = ws.bib.read_bytes()
            meanwhile()
            held = ws.bib.read_bytes()
        except BaseException:
            finish(process)
            raise
    out, err = process.communicate(timeout=60)
    assert process.returncode == 0, err
    return out.strip(), before, held


@pytest.mark.parametrize("mode", ["edit", "apply"])
def test_a_writer_waits_for_the_lock_and_then_builds_on_what_was_written(ws, mode):
    mine = ZOLL90.replace("{27}", "{28}")

    def meanwhile():
        api.save_edit(ws, "Zoll90", mine, load_entries(ws.bib)["Zoll90"]["fingerprint"])

    out, before, held = held_then(ws, mode, "Kaha12", KAHA12.replace("2012", "2013"), meanwhile)
    assert held == before.replace(ZOLL90.encode(), mine.encode())
    text = ws.bib.read_text(encoding="utf-8")
    assert mine in text                                          # the edit made under the lock was not lost
    if mode == "edit":
        assert out == "RESULT ['Kaha12']" and text == TEXT.replace(ZOLL90, mine).replace("2012", "2013")
    else:
        assert out == "RESULT ['Smit20']" and set(load_entries(ws.bib)) == {"Zoll90", "Kaha12", "Smit20"}


def test_the_fingerprint_is_compared_once_the_lock_is_held(ws):
    """The waiting writer opened Zoll90 before this process changed it: its save is refused."""
    def meanwhile():
        api.save_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}"), load_entries(ws.bib)["Zoll90"]["fingerprint"])

    out, _, held = held_then(ws, "edit", "Zoll90", ZOLL90.replace("{10}", "{11}"), meanwhile)
    assert out.startswith("REFUSED EditRefused Zoll90 was changed since it was opened; nothing was written")
    assert ws.bib.read_bytes() == held


def test_an_approval_waits_for_the_lock_and_is_refused_for_content_that_changed(ws):
    from cdlbib import identity
    try:
        identity.current()
    except IdentityUnavailable as exc:
        pytest.skip(f"no GitHub login for a real approval: {exc}")

    def meanwhile():
        api.save_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}"), load_entries(ws.bib)["Zoll90"]["fingerprint"])

    out, _, _ = held_then(ws, "approve", "Zoll90", "", meanwhile)
    assert out == "REFUSED ApprovalRefused Entry changed since review; approval rejected"
    assert api.entry(ws, "Zoll90").status == "pending"


# --- a writer that is killed -------------------------------------------------------------------

KILLED = HEAD + """
opened = api.entry(ws, 'Zoll90').fingerprint
def audit(event, args):
    if event == 'os.rename' and str(args[1]) == {target!r}:
        print('paused', flush=True)
        signal.pause()
sys.addaudithook(audit)
api.save_edit(ws, 'Zoll90', {raw!r}, opened)
"""


def killed_at(ws, target):
    """A real rename of Zoll90, killed just before the file ``target`` is replaced."""
    process = child(KILLED.format(root=str(ws.root), target=str(target), raw=RENAMED), ws.root)
    try:
        assert line(process) == "paused"
        process.kill()
        process.wait(timeout=10)
    finally:
        finish(process)


def strays(ws):
    return sorted(path.name for folder in (ws.root, ws.root / "verification") if folder.is_dir()
                  for path in folder.iterdir() if path.name.startswith("."))


def test_a_writer_killed_between_the_bibliography_and_the_ledger_is_put_back(ws):
    before = ws.bib.read_bytes()
    killed_at(ws, ws.key_renames)
    half = ws.bib.read_bytes()
    assert half == before.replace(ZOLL90.encode(), RENAMED.encode()) and not ws.key_renames.exists()   # part-way
    copy = writer.interrupted(ws)
    assert copy and Path(copy).read_bytes() == before and Path(copy).parent == ws.work / "edits"
    assert [item.key for item in api.entries(ws)] == ["Zoller1990", "Kaha12"]       # reading entries does not settle it
    assert ws.bib.read_bytes() == half and writer.interrupted(ws) == copy
    said = api.recover_interrupted(ws)                            # the lock the dead writer held is free
    assert len(said) == 1 and "interrupted part-way; the library was put back as it was" in said[0] and copy in said[0]
    assert ws.bib.read_bytes() == before and not ws.key_renames.exists()
    assert writer.interrupted(ws) is None and api.library_state(ws).interrupted is None
    assert strays(ws) == [".bibcheck"] and Path(copy).read_bytes() == before
    assert api.recover_interrupted(ws) == []
    applied = api.save_edit(ws, "Zoll90", RENAMED, load_entries(ws.bib)["Zoll90"]["fingerprint"])      # and it can be redone
    assert applied.renamed == {"Zoll90": "Zoller1990"} and applied.notes == [] and ws.key_renames.is_file()


def test_the_next_save_settles_a_killed_writer_by_itself(ws):
    before = ws.bib.read_bytes()
    killed_at(ws, ws.key_renames)
    edited = KAHA12.replace("2012", "2013")
    applied = api.save_edit(ws, "Kaha12", edited, load_entries(ws.bib)["Kaha12"]["fingerprint"])
    assert applied.written == ["Kaha12"] and len(applied.notes) == 1 and "put back as it was" in applied.notes[0]
    assert ws.bib.read_bytes() == before.replace(KAHA12.encode(), edited.encode())  # the half-made rename is gone
    assert not ws.key_renames.exists() and writer.interrupted(ws) is None and strays(ws) == [".bibcheck"]
    assert applied.saved_copy.read_bytes() == before


def test_a_writer_killed_before_it_replaced_anything_leaves_the_library_as_it_was(ws):
    before = ws.bib.read_bytes()
    killed_at(ws, ws.bib)
    assert ws.bib.read_bytes() == before and writer.interrupted(ws) and len(strays(ws)) > 1     # its prepared files
    said = api.recover_interrupted(ws)
    assert len(said) == 1 and "interrupted before anything was written" in said[0]
    assert ws.bib.read_bytes() == before and not ws.key_renames.exists() and strays(ws) == [".bibcheck"]
    assert writer.interrupted(ws) is None


def test_a_library_changed_after_the_kill_is_not_touched(ws):
    killed_at(ws, ws.key_renames)
    ws.bib.write_text(ws.bib.read_text(encoding="utf-8") + "% my own note\n", encoding="utf-8")
    mine, copy = ws.bib.read_bytes(), writer.interrupted(ws)
    for attempt in (lambda: api.recover_interrupted(ws),
                    lambda: api.save_edit(ws, "Kaha12", KAHA12.replace("2012", "2013"),
                                          load_entries(ws.bib)["Kaha12"]["fingerprint"]),
                    lambda: complete.apply(ws, [])):
        with pytest.raises(CdlbibError, match="was interrupted, and the library was changed since") as refused:
            attempt()
        assert copy in str(refused.value)
        assert ws.bib.read_bytes() == mine and writer.interrupted(ws) == copy


def test_an_edit_of_the_managed_library_killed_part_way_is_announced_and_undone(managed):
    ws = Workspace(library.download())
    before = ws.bib.read_bytes()
    killed_at(ws, ws.key_renames)
    assert ws.bib.read_bytes() != before and not ws.key_renames.exists()
    stamp = library.interrupted()
    assert stamp and api.library_state(ws).interrupted == stamp
    for attempt in (lambda: api.save_edit(ws, "Zoller1990", ZOLL90, load_entries(ws.bib)["Zoller1990"]["fingerprint"]),
                    lambda: api.recover_interrupted(ws)):
        with pytest.raises(CdlbibError, match="an earlier entry edit of the bibliography .* was interrupted") as refused:
            attempt()
        assert stamp in str(refused.value)
    restored, _ = library.undo(ws)
    assert restored.stamp == stamp and ws.bib.read_bytes() == before
    assert not ws.key_renames.exists() and library.interrupted() is None
    assert api.save_edit(ws, "Zoll90", RENAMED, load_entries(ws.bib)["Zoll90"]["fingerprint"]).written == ["Zoller1990"]
    assert desk.parsed(ws) == load_entries(ws.bib)


def test_asking_for_the_state_settles_a_killed_writer_and_says_so(ws):
    before = ws.bib.read_bytes()
    killed_at(ws, ws.key_renames)
    copy = writer.interrupted(ws)
    state = api.library_state(ws)
    assert state.interrupted is None and ws.bib.read_bytes() == before and not ws.key_renames.exists()
    assert any("interrupted part-way; the library was put back as it was" in note and copy in note for note in state.notes)
    assert api.recover_interrupted(ws) == [] and not any("interrupted" in note for note in api.library_state(ws).notes)


def test_a_killed_writer_is_settled_before_a_check_an_approval_or_a_revocation(ws):
    """Nothing is checked, approved or revoked on a half-made change: taking the lock puts
    the library back first. (Zoll90 is the key before the interrupted rename.)"""
    from cdlbib import identity
    from cdlbib.errors import ApprovalRefused, GateFailed
    before = ws.bib.read_bytes()
    killed_at(ws, ws.key_renames)
    half = load_entries(ws.bib)
    assert "Zoller1990" in half and "Zoll90" not in half
    lines = []
    with pytest.raises(GateFailed, match="citation keys absent from the bibliography"):
        api.check_keys(ws, ["Zoller1990"], progress=lines.append, mailto="valid@example.org")   # the key of the half state
    assert ws.bib.read_bytes() == before and writer.interrupted(ws) is None
    assert len(lines) == 1 and "put back as it was" in lines[0]
    try:
        identity.current()
    except IdentityUnavailable as exc:
        pytest.skip(f"no GitHub login for a real approval: {exc}")
    for act in (lambda: api.approve(ws, "Zoller1990", half["Zoller1990"]["fingerprint"], "a source", "a note"),
                lambda: api.revoke(ws, "Zoller1990", "a reason", expected_fingerprint=half["Zoller1990"]["fingerprint"])):
        killed_at(ws, ws.key_renames)
        with pytest.raises(ApprovalRefused):
            act()
        assert ws.bib.read_bytes() == before and writer.interrupted(ws) is None
    assert api.entry(ws, "Zoll90").status == "pending"


def test_a_killed_writer_is_never_sent_half_done(tmp_path, monkeypatch):
    """A real checkout: the rename is killed between the bibliography and the ledger. The
    send that follows works on the library put back whole (the gate sees the old key and the
    format failure planted in it refuses the send); the half-made state is never committed."""
    from cdlbib import publish
    from cdlbib.errors import GateFailed
    from test_publish import git
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    remote = tmp_path / "fork.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "master", str(remote))
    work = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", str(remote), str(work))
    git(work, "checkout", "-q", "-B", "master")
    (work / "verification").mkdir()
    (work / "verification" / ".gitkeep").write_text("", encoding="utf-8")
    (work / "cdl.bib").write_text("% start\n", encoding="utf-8")
    git(work, "add", "-A"); git(work, "commit", "-q", "-m", "start"); git(work, "push", "-q", "origin", "HEAD:master")
    mine = Workspace(work)
    mine.bib.write_text(ZOLL90.replace("1053--1065", "1053-1065") + "\n", encoding="utf-8")     # unsent, and not yet sendable
    before = mine.bib.read_bytes()
    process = child(KILLED.format(root=str(work), target=str(mine.key_renames),
                                  raw=RENAMED.replace("1053--1065", "1053-1065")), work)
    try:
        assert line(process) == "paused"
        process.kill(); process.wait(timeout=10)
    finally:
        finish(process)
    assert b"Zoller1990" in mine.bib.read_bytes() and not mine.key_renames.exists()
    lines, reports = [], []
    with pytest.raises(GateFailed, match="not sent") as refused:
        api.send_checked(mine, progress=lines.append, report=reports.append)
    assert mine.bib.read_bytes() == before and writer.interrupted(mine) is None        # settled before the gate
    assert len(lines) == 1 and "put back as it was" in lines[0] and str(mine.bib) in lines[0], lines   # this library's, once
    assert refused.value.check.format.errors == ["Zoll90"] and reports[0].format.errors == ["Zoll90"]
    assert publish.current_branch(mine) == "master" and git(work, "log", "--oneline").count("\n") == 0
    assert git(remote, "for-each-ref", "--format=%(refname)", "refs/heads/cdlbib/") == ""
    # and a record that cannot be trusted refuses the send outright, naming the record
    process = child(KILLED.format(root=str(work), target=str(mine.key_renames),
                                  raw=RENAMED.replace("1053--1065", "1053-1065")), work)
    try:
        assert line(process) == "paused"
        process.kill(); process.wait(timeout=10)
    finally:
        finish(process)
    mine.bib.write_text(mine.bib.read_text(encoding="utf-8") + "% changed since\n", encoding="utf-8")
    changed = mine.bib.read_bytes()
    with pytest.raises(CdlbibError, match="was interrupted, and the library was changed since") as refused:
        api.send_checked(mine)
    assert writer.PENDING in str(refused.value) and mine.bib.read_bytes() == changed
    assert publish.current_branch(mine) == "master" and git(work, "log", "--oneline").count("\n") == 0


HAMMER = """
import os, random, sys, time
bib, stop, log = sys.argv[1:4]
number = 0
while not os.path.exists(stop):
    number += 1
    with open(bib, 'rb') as stream:              # an editor that knows nothing of the lock:
        data = stream.read()                     # read, add a line, save by rename
    with open(bib + '.editor', 'wb') as stream:
        stream.write(data + b'%% saved by the other program %d\\n' % number)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(bib + '.editor', bib)
    with open(log, 'a') as stream:
        stream.write('%d\\n' % number)
    time.sleep(random.random() * 0.05)
"""


def test_a_program_that_ignores_the_lock_never_has_a_save_written_over(ws, tmp_path):
    """A second real process saves cdl.bib over and over (read, append a numbered line, rename
    into place) while this one saves edits through the writer. Each of this process's saves
    either completes or is refused; and whichever it is, no save of the other program is
    discarded: every line it ever saved is in the file, in order, at the end."""
    stop, log = tmp_path / "stop", tmp_path / "saved.txt"
    hammer = subprocess.Popen([sys.executable, "-c", HAMMER, str(ws.bib), str(stop), str(log)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    done = refused = 0
    try:
        while not log.exists():
            time.sleep(0.01)
        for number in range(150):
            try:
                current = api.entry(ws, "Kaha12")
                applied = api.save_edit(ws, "Kaha12", KAHA12.replace("2012", str(1500 + number)), current.fingerprint)
                done += applied.written == ["Kaha12"]
            except CdlbibError as exc:
                assert "changed" in str(exc) or "could not be read" in str(exc), exc
                refused += 1
    finally:
        stop.write_text("stop", encoding="utf-8")
        out, err = hammer.communicate(timeout=30)
    assert hammer.returncode == 0, err
    saved = [int(text) for text in log.read_text().split()]
    kept = [int(text.rsplit(" ", 1)[1]) for text in ws.bib.read_text(encoding="utf-8").splitlines()
            if text.startswith("% saved by the other program ")]
    print("writer saves completed:", done, "refused:", refused, "other program's saves:", len(saved))
    assert done + refused == 150 and done >= 1 and refused >= 1 and len(saved) > 30
    assert kept == saved == list(range(1, len(saved) + 1))            # not one of its saves was written over
    assert set(load_entries(ws.bib)) == {"Zoll90", "Kaha12"} and not list(ws.root.glob(".cdl.bib-*"))
    assert writer.interrupted(ws) is None
