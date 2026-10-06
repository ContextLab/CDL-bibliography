"""What the writer does when something else acts at the worst instant of a write.

Each test makes the other program's move at an exact point of a real write, from an audit hook
of the interpreter: the writer announces each replacement (``os.rename``), every flagged rename
of the C library is announced with its names and folder descriptor just before the call, and every
file it opens is an ``open`` event. The other program's move is a real file operation (a save
in place, a save by rename, a link, a removal, running out of descriptors); nothing of the
writer is replaced or patched. Real files and processes; no mocks.
"""
import errno
import os
import stat
import sys

import pytest

from cdlbib import api, library, verification, writer
from cdlbib.errors import CdlbibError, WriteConflict
from cdlbib.verification import load_entries

from test_locking import HEAD, KAHA12, RENAMED, ZOLL90, child, finish, killed_at, line, ws  # noqa: F401

STEPS = []          # [(does this event start it?, what the other program does then)], each done once, in order


def _audit(event, args):
    if STEPS and event in ("os.rename", "open") and STEPS[0][0](event, args):
        STEPS.pop(0)[1](event, args)


sys.addaudithook(_audit)             # for the life of the process; it does nothing while STEPS is empty


@pytest.fixture(autouse=True)
def no_steps_left():
    STEPS.clear()
    yield
    left = len(STEPS)
    STEPS.clear()
    assert not left, f"{left} of the other program's moves were never reached"


def announced(target):
    return lambda event, args: event == "os.rename" and str(args[1]) == str(target)


def rename_call(event, args):        # just before the next flagged rename (an exchange, or taking a free name)
    return event == "os.rename" and args[2] != -1


def next_open(event, args):          # just before the next file is opened
    return event == "open"


def nothing(event, args):
    pass


def strays(ws):
    return sorted(path.name for folder in (ws.root, ws.root / "verification") if folder.is_dir()
                  for path in folder.iterdir() if path.name.startswith(".") and path.name != ".bibcheck")


def edit(ws, year="1999"):
    return api.save_edit(ws, "Kaha12", KAHA12.replace("2012", year), load_entries(ws.bib)["Kaha12"]["fingerprint"])


# --- 1: a save in place that times and sizes do not show ------------------------------------------

def test_a_save_in_place_between_the_reading_and_the_exchange_is_kept(ws):
    """Another program writes the bibliography in place (the same file, the same size, and it
    sets the file's time back, as a tool that preserves times does) after the writer has read
    it and just before the exchange. The file that comes out of the exchange is the one that
    was read, by device, inode, time and size; what it HOLDS is the other program's save. It
    is put back and the write is refused: nothing of the other program's is discarded."""
    before = ws.bib.read_bytes()
    theirs = before.replace(b"{27}", b"{28}")
    assert theirs != before and len(theirs) == len(before)

    def save_in_place(event, args):
        found = os.stat(ws.bib)
        with open(ws.bib, "r+b") as stream:
            stream.write(theirs)
        os.utime(ws.bib, ns=(found.st_atime_ns, found.st_mtime_ns))
        assert (os.stat(ws.bib).st_ino, os.stat(ws.bib).st_mtime_ns) == (found.st_ino, found.st_mtime_ns)
    STEPS[:] = [(announced(ws.bib), nothing), (rename_call, save_in_place)]
    with pytest.raises(CdlbibError, match="changed while applying; nothing was written"):
        edit(ws)
    assert ws.bib.read_bytes() == theirs and strays(ws) == [] and writer.interrupted(ws) is None


def test_a_file_written_while_it_is_read_is_not_taken_for_either_state(tmp_path):
    """The reading itself: the file's times and size are taken before the read and after it.
    A second thread appends to a large file for as long as it is being read (a real write
    during a real read); that reading is refused, and once the writing has stopped the file
    is read as it is."""
    import contextlib
    import threading
    path = tmp_path / "cdl.bib"
    path.write_bytes(b"x" * (48 << 20))
    stop, appended = threading.Event(), []

    def append():
        with open(path, "ab", buffering=0) as stream:
            while not stop.is_set():
                appended.append(stream.write(b"y"))
    thread = threading.Thread(target=append)
    folder = writer._Folder.at(tmp_path)
    try:
        thread.start()
        while not appended:
            pass
        with contextlib.ExitStack() as keep:
            with pytest.raises(writer._Changed):
                folder.read_held("cdl.bib", keep)
        fd = os.open(path, os.O_RDONLY)
        try:
            assert writer._read_fd(fd)[1] is False
        finally:
            os.close(fd)
        stop.set()
        thread.join()
        with contextlib.ExitStack() as keep:
            data, _, _ = folder.read_held("cdl.bib", keep)
        assert data == b"x" * (48 << 20) + b"y" * len(appended)
    finally:
        stop.set()
        thread.join()
        folder.close()


# --- 2: taking back, and settling a killed write ----------------------------------------------------

def two_files(ws):
    """A write of both files (as a key rename makes): (writes, expected)."""
    before = ws.bib.read_bytes()
    after = before.replace(ZOLL90.encode(), RENAMED.encode())
    ledger = b'[\n {"old_key": "Zoll90", "new_key": "Zoller1990"}\n]\n'
    return [(ws.bib, after), (ws.key_renames, ledger)], {ws.bib: before, ws.key_renames: None}


def ledger_appears(ws):
    def appear(event, args):         # the second file is not as the caller planned: the write is taken back
        ws.key_renames.parent.mkdir(exist_ok=True)
        ws.key_renames.write_bytes(b"[]\n")
    return appear


def test_a_save_made_while_a_write_is_taken_back_is_kept(ws):
    """The bibliography is replaced, the ledger turns out changed, and the bibliography is
    being taken back: another program saves it (by rename) after the writer has seen that it
    still holds the new text and just before the old text is put in its place. That save
    stays, the conflict is said, and the record of the write is kept."""
    writes, expected = two_files(ws)
    theirs = writes[0][1] + b"% saved by the other program\n"

    def save_by_rename(event, args):
        (ws.root / "cdl.bib.editor").write_bytes(theirs)
        os.replace(ws.root / "cdl.bib.editor", ws.bib)
    STEPS[:] = [(announced(ws.key_renames), ledger_appears(ws)), (rename_call, save_by_rename)]
    with library.transaction(ws):
        with pytest.raises(WriteConflict, match="was changed by something else in the meantime") as conflict:
            writer.commit(ws, writes, expected)
    assert conflict.value.files == [str(ws.bib)]
    assert ws.bib.read_bytes() == theirs and ws.key_renames.read_bytes() == b"[]\n"
    assert writer.interrupted(ws) and open(writer.interrupted(ws), "rb").read() == expected[ws.bib]
    assert strays(ws) == []


@pytest.mark.parametrize("permissions", [0o644, 0o640, 0o664])
def test_a_write_taken_back_leaves_the_permission_bits_as_they_were(ws, permissions):
    os.chmod(ws.bib, permissions)
    writes, expected = two_files(ws)
    STEPS[:] = [(announced(ws.key_renames), ledger_appears(ws))]
    with library.transaction(ws):
        with pytest.raises(CdlbibError, match="changed while applying; nothing was written"):
            writer.commit(ws, writes, expected)
    assert ws.bib.read_bytes() == expected[ws.bib] and stat.S_IMODE(os.stat(ws.bib).st_mode) == permissions
    assert writer.interrupted(ws) is None and strays(ws) == []


def test_a_killed_write_is_put_back_with_the_permission_bits_it_had(ws):
    os.chmod(ws.bib, 0o640)
    before = ws.bib.read_bytes()
    killed_at(ws, ws.key_renames)
    assert ws.bib.read_bytes() != before and stat.S_IMODE(os.stat(ws.bib).st_mode) == 0o640
    with library.transaction(ws):
        pass
    assert ws.bib.read_bytes() == before and stat.S_IMODE(os.stat(ws.bib).st_mode) == 0o640
    assert writer.interrupted(ws) is None and strays(ws) == []


def test_a_save_made_while_a_killed_write_is_put_back_is_kept(ws):
    """The next command settles a write that was killed after the bibliography was replaced:
    another program saves the bibliography after the settling has read it and just before
    the copy is put in its place. That save stays, and the settling refuses, naming the record."""
    before = ws.bib.read_bytes()
    killed_at(ws, ws.key_renames)
    half = ws.bib.read_bytes()
    theirs = half + b"% saved by the other program\n"

    def save_by_rename(event, args):
        (ws.root / "cdl.bib.editor").write_bytes(theirs)
        os.replace(ws.root / "cdl.bib.editor", ws.bib)
    STEPS[:] = [(rename_call, save_by_rename)]
    with pytest.raises(CdlbibError, match="was changed by something else while the library was being put back"):
        with library.transaction(ws):
            pass
    assert ws.bib.read_bytes() == theirs
    assert writer.interrupted(ws) and open(writer.interrupted(ws), "rb").read() == before


# --- 3: no descriptors left just after the exchange ---------------------------------------------------

EXHAUSTED = HEAD + """
import errno, resource
from cdlbib import writer
resource.setrlimit(resource.RLIMIT_NOFILE, (64, resource.getrlimit(resource.RLIMIT_NOFILE)[1]))
before = ws.bib.read_bytes()
opened = api.entry(ws, 'Zoll90').fingerprint
state = {{'announced': False, 'exchanged': False, 'held': [], 'refused': 0}}
def audit(event, args):
    if event == 'os.rename' and str(args[1]) == str(ws.bib):
        state['announced'] = True
    elif event == 'os.rename' and args[2] != -1 and state['announced'] and not state['exchanged']:
        state['exchanged'] = True                     # the exchange is the next thing done
    elif event == 'open' and state['exchanged'] and not state['held']:
        try:                                          # the first file opened after it: every descriptor is taken
            while True:
                state['held'].append(os.dup(0))
        except OSError as exc:
            assert exc.errno == errno.EMFILE, exc
sys.addaudithook(audit)
try:
    api.save_edit(ws, 'Zoll90', {raw!r}, opened)
    said = 'DONE'
except BaseException as exc:
    said = type(exc).__name__ + ' ' + ' '.join(str(exc).split())
for fd in state['held']:
    os.close(fd)
state['held'] = [-1]
print(said)
print('taken', len(state['held']) and state['exchanged'])
print('bibliography', 'new' if ws.bib.read_bytes() != before else 'as it was', '| ledger', ws.key_renames.exists(),
      '| record', bool(writer.interrupted(ws)))
with library.transaction(ws):
    print('settled')
print('bibliography', 'new' if ws.bib.read_bytes() != before else 'as it was', '| ledger', ws.key_renames.exists(),
      '| record', bool(writer.interrupted(ws)),
      '| strays', sorted(p.name for p in ws.root.iterdir() if p.name.startswith('.') and p.name != '.bibcheck'))
"""


def test_with_no_descriptors_left_after_the_exchange_the_write_is_not_called_unwritten(ws):
    """A real descriptor limit (RLIMIT_NOFILE) is reached in a child process at the first file
    opened after the bibliography was exchanged: the writer can open nothing to look at what it
    did, or to take it back. It must not say that nothing was written (the bibliography is the
    new one and the ledger the old), and must keep the record of the write, from which the
    next command puts the library back whole."""
    process = child(EXHAUSTED.format(root=str(ws.root), raw=RENAMED), ws.root)
    try:
        said = line(process)
        assert said.startswith("WriteConflict The write could not be finished"), said + process.stderr.read()
        assert "it may hold the new text" in said and "nothing was written" not in said
        assert "Too many open files" in said and str(ws.work / "edits" / writer.PENDING) in said
        assert line(process) == "taken True"
        assert line(process) == "bibliography new | ledger False | record True"
        assert line(process).startswith("settled")
        assert line(process) == "bibliography as it was | ledger False | record False | strays []"
        assert process.wait(timeout=30) == 0, process.stderr.read()
    finally:
        finish(process)


# --- 4: a folder where a file is to be put -----------------------------------------------------------

def test_a_folder_in_the_place_of_a_file_is_left_where_it_is(tmp_path):
    """The exchange of two names also exchanges a file with a folder. A folder found in the
    place a file is put to is exchanged back at once; it is never left under another name,
    and nothing in it is removed."""
    library_folder = tmp_path / "library"
    (library_folder / "cdl.bib").mkdir(parents=True)
    (library_folder / "cdl.bib" / "inside.txt").write_text("a file of the user's\n", encoding="utf-8")
    folder = writer._Folder.at(library_folder)
    try:
        with pytest.raises(OSError):
            folder.put("cdl.bib", b"new text\n")
        assert sorted(item.name for item in library_folder.iterdir()) == ["cdl.bib"]
        assert (library_folder / "cdl.bib" / "inside.txt").read_text(encoding="utf-8") == "a file of the user's\n"
        made, identity = folder.new(".made-", b"new text\n")
        assert folder.move(made, "cdl.bib", identity) is False
        folder.clear(made)
        assert sorted(item.name for item in library_folder.iterdir()) == ["cdl.bib"] and (library_folder / "cdl.bib").is_dir()
        assert writer._restore(folder, library_folder / "free", None, None, b"x") is True      # nothing there, none wanted
        with pytest.raises(OSError):
            writer._restore(folder, library_folder / "cdl.bib", b"old\n", 0o644, b"new text\n")
        assert (library_folder / "cdl.bib" / "inside.txt").is_file()
    finally:
        folder.close()


# --- 5: a folder that cannot be flushed to the disk ---------------------------------------------------

def test_a_failed_flush_of_a_folder_is_an_error_and_an_unsupported_one_is_not(tmp_path):
    """Flushing a real folder works. A real failure of fsync (here EBADF: the descriptor was
    closed) is raised, not passed over; EINVAL, which is what fsync answers for something that
    cannot be flushed (here a pipe), is the one kind that is passed over."""
    folder = writer._Folder.at(tmp_path)
    folder.flush()
    os.close(folder.fd)
    with pytest.raises(OSError) as failed:
        folder.flush()
    assert failed.value.errno == errno.EBADF
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(OSError) as unsupported:
            os.fsync(read_end)
        assert unsupported.value.errno in writer._NO_FOLDER_FSYNC
        writer._Folder(tmp_path, read_end).flush()               # passed over
    finally:
        os.close(read_end)
        os.close(write_end)
    assert errno.EIO not in writer._NO_FOLDER_FSYNC and errno.ENOSPC not in writer._NO_FOLDER_FSYNC


# --- 15: the ledger is read by name from the held folders ---------------------------------------------

def test_the_key_rename_ledger_is_not_read_through_a_link(ws, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text('[{"old_key": "Planted", "new_key": "Outside"}]\n', encoding="utf-8")
    ws.key_renames.parent.mkdir()
    os.symlink(outside, ws.key_renames)
    with pytest.raises(CdlbibError, match="is a link, or not an ordinary file"):
        writer.renames_recorded(ws, {"Zoll90": "Zoller1990"}, "a test")
    os.unlink(ws.key_renames)
    ws.key_renames.write_text("[]\n", encoding="utf-8")
    ledger, original, data = writer.renames_recorded(ws, {"Zoll90": "Zoller1990"}, "a test")
    assert (ledger, original) == (ws.key_renames, b"[]\n") and b"Zoller1990" in data and b"Planted" not in data
    os.unlink(ws.key_renames)
    os.rmdir(ws.key_renames.parent)
    os.symlink(tmp_path, ws.key_renames.parent)                  # the ledger's folder is a link
    (tmp_path / ws.key_renames.name).write_text('[{"old_key": "Planted"}]\n', encoding="utf-8")
    with pytest.raises(CdlbibError, match="is a link, or not an ordinary file"):
        writer.renames_recorded(ws, {"Zoll90": "Zoller1990"}, "a test")


# --- a save, a link or a removal in the instant after the exchange --------------------------------------

def test_a_save_another_program_makes_just_after_the_exchange_is_left_in_place(ws):
    """The other program read the bibliography before the exchange and saves (by rename)
    just after it, before the writer has looked: its save is the newest and stays. The write
    is refused as changed; the file that was read is not put back over that save."""
    theirs = ws.bib.read_bytes() + b"% saved by the other program\n"

    def save_by_rename(event, args):
        (ws.root / "cdl.bib.editor").write_bytes(theirs)
        os.replace(ws.root / "cdl.bib.editor", ws.bib)
    STEPS[:] = [(announced(ws.bib), nothing), (rename_call, nothing), (next_open, save_by_rename)]
    with pytest.raises(CdlbibError, match="changed while applying; nothing was written"):
        edit(ws)
    assert ws.bib.read_bytes() == theirs and strays(ws) == [] and writer.interrupted(ws) is None


@pytest.mark.parametrize("aside", ["kept", "removed", "a link too"])
def test_a_link_found_in_the_bibliographys_place_after_the_exchange_is_not_left_there(ws, tmp_path, aside):
    """The prepared file is swapped for a link to a file outside just before the exchange, so
    the bibliography's name holds that link when the writer looks. The file that was read is
    exchanged back; when it was removed or swapped too while it stood aside, its text is
    written again, with its permission bits. Either way the write is refused, the
    bibliography is an ordinary file with what was read, and the file outside is untouched."""
    victim = tmp_path / "victim.txt"
    victim.write_text("not cdlbib's to touch\n", encoding="utf-8")
    os.chmod(victim, 0o666)
    os.chmod(ws.bib, 0o640)
    before, prepared = ws.bib.read_bytes(), []

    def remember(event, args):
        prepared.append(str(args[0]))

    def swap_for_a_link(event, args):
        os.unlink(prepared[0])
        os.symlink(victim, prepared[0])

    def take_the_file_away(event, args):                 # it stands under the prepared name now
        if aside != "kept":
            os.unlink(prepared[0])
        if aside == "a link too":
            os.symlink(victim, prepared[0])
    STEPS[:] = [(announced(ws.bib), remember), (rename_call, swap_for_a_link), (next_open, take_the_file_away)]
    with pytest.raises(CdlbibError):
        edit(ws)
    assert not ws.bib.is_symlink() and ws.bib.read_bytes() == before
    assert stat.S_IMODE(os.stat(ws.bib).st_mode) == 0o640
    assert victim.read_text(encoding="utf-8") == "not cdlbib's to touch\n" and not victim.is_symlink()
    assert stat.S_IMODE(os.stat(victim).st_mode) == 0o666
    assert strays(ws) == [] and writer.interrupted(ws) is None
    assert edit(ws, "2001").written == ["Kaha12"]                 # and the next save goes through
