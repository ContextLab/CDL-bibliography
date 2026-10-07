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


def kept(ws):
    """{path under .bibcheck/kept: its bytes, or where a link points, or "a folder"}: what
    writes kept in their private folders."""
    found = {}
    for item in sorted((ws.work / "kept").rglob("*")) if (ws.work / "kept").is_dir() else ():
        name = str(item.relative_to(ws.work / "kept"))
        if item.is_symlink():
            found[name] = "link to " + os.readlink(item)
        elif item.is_file():
            found[name] = item.read_bytes()
        elif len(item.relative_to(ws.work / "kept").parts) > 1:
            found[name] = "a folder"
    return found


def copies(ws):
    return {item.name: item.read_bytes() for item in sorted((ws.work / "edits").glob("*-*"))} if (ws.work / "edits").is_dir() else {}


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
        os.unlink(library_folder / made)
        folder._let_go(made)
        assert sorted(item.name for item in library_folder.iterdir()) == ["cdl.bib"] and (library_folder / "cdl.bib").is_dir()
        # the library-file step: the folder goes back under its name, the file made is kept aside
        import contextlib
        stack = contextlib.ExitStack()
        aside = writer._Aside(lambda: folder.sub(".bibcheck", create=True), stack)
        made, identity = folder.new(".made-", b"new text\n")
        with pytest.raises(writer._Changed):
            folder.install(made, "cdl.bib", b"what was expected\n", aside)
        assert (library_folder / "cdl.bib" / "inside.txt").read_text(encoding="utf-8") == "a file of the user's\n"
        assert [(label, foreign) for label, foreign, _ in aside.items] == [("cdl.bib.not-installed", False)]
        assert (aside.path / "cdl.bib.not-installed").read_bytes() == b"new text\n"
        assert writer._restore(folder, library_folder / "free", None, None, b"x", aside) is True      # nothing there, none wanted
        with pytest.raises(OSError):
            writer._restore(folder, library_folder / "cdl.bib", b"old\n", 0o644, b"new text\n", aside)
        assert (library_folder / "cdl.bib" / "inside.txt").is_file()
        assert sorted(item.name for item in library_folder.iterdir()) == [".bibcheck", "cdl.bib"]
        stack.close()
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
    with pytest.raises(WriteConflict) as refused:
        edit(ws)
    assert not ws.bib.is_symlink() and ws.bib.read_bytes() == before
    assert stat.S_IMODE(os.stat(ws.bib).st_mode) == 0o640
    assert victim.read_text(encoding="utf-8") == "not cdlbib's to touch\n" and not victim.is_symlink()
    assert stat.S_IMODE(os.stat(victim).st_mode) == 0o666
    # the link that stood in the bibliography's place is not removed: it is kept, and named
    links = {name: what for name, what in kept(ws).items() if what == f"link to {victim}"}
    assert links and all(str(ws.work / "kept" / name) in str(refused.value) for name in links), (kept(ws), str(refused.value))
    assert "Nothing was written" in str(refused.value) or "written again" in str(refused.value)
    assert strays(ws) == [] and writer.interrupted(ws)            # the record stays while something unexpected is kept
    assert edit(ws, "2001").written == ["Kaha12"]                 # the next save settles it and goes through
    assert writer.interrupted(ws) is None and set(links) <= set(kept(ws))


# --- nothing that stood under a library name is removed -----------------------------------------------

def test_a_program_that_holds_the_bibliography_open_loses_nothing_it_writes_after_a_save(ws):
    """Another program opens the bibliography for writing and keeps it open. cdlbib saves an
    edit: the file the other program has open is no longer the bibliography. What that
    program writes then, at any time, goes into a file that is kept: the copy of that save
    in .bibcheck/edits, the same file it has open. It is never a removed file."""
    before = ws.bib.read_bytes()
    theirs = os.open(ws.bib, os.O_WRONLY | os.O_APPEND)
    try:
        assert edit(ws).written == ["Kaha12"]
        os.write(theirs, b"% written by the program that had it open\n")
        held = os.fstat(theirs)
        assert held.st_nlink == 1                                  # the file it holds still has a name
        (copy,) = [item for item in (ws.work / "edits").iterdir() if item.name.endswith("-cdl.bib")]
        assert (os.stat(copy).st_dev, os.stat(copy).st_ino) == (held.st_dev, held.st_ino)
        assert copy.read_bytes() == before + b"% written by the program that had it open\n"
        assert stat.S_IMODE(os.stat(copy).st_mode) == 0o600
    finally:
        os.close(theirs)
    assert b"Year = {1999}" in ws.bib.read_bytes() and kept(ws) == {} and strays(ws) == []


def test_a_save_in_place_after_the_content_was_checked_is_in_the_copy(ws):
    """The schedule: the other program has the bibliography open; cdlbib exchanges it away
    and reads it (it holds what was expected); THEN the other program writes its save through
    its descriptor, before cdlbib does anything more with that file. The save is in the copy
    kept for this write. (It used to be removed with the file.)"""
    before = ws.bib.read_bytes()
    theirs = os.open(ws.bib, os.O_WRONLY | os.O_APPEND)

    def save_through_the_descriptor(event, args):          # just before the file that came out is moved aside
        os.write(theirs, b"% saved after the check\n")
    try:
        STEPS[:] = [(announced(ws.bib), nothing), (rename_call, nothing), (rename_call, save_through_the_descriptor)]
        assert edit(ws).written == ["Kaha12"]
        assert os.fstat(theirs).st_nlink == 1
    finally:
        os.close(theirs)
    assert list(copies(ws).values()) == [before + b"% saved after the check\n"]
    assert b"Year = {1999}" in ws.bib.read_bytes() and kept(ws) == {}


def test_a_save_written_into_the_new_file_while_it_stood_as_the_bibliography_is_kept(ws):
    """The schedule: cdlbib reads A; another program saves B by rename; the exchange puts
    cdlbib's file T in the bibliography's place and B comes out, so T is to be exchanged back;
    just before that, a program overwrites the bibliography it sees (T) in place with its save
    C. B is the bibliography again, the write is refused, and T, holding C, is kept in the
    write's folder and named. (T used to be removed as cdlbib's own file.)"""
    a = ws.bib.read_bytes()
    b = a + b"% B, saved by rename\n"
    c = b"% C, saved in place over the text that stood there\n"

    def save_b_by_rename(event, args):
        (ws.root / "cdl.bib.editor").write_bytes(b)
        os.replace(ws.root / "cdl.bib.editor", ws.bib)

    def save_c_in_place(event, args):
        with open(ws.bib, "r+b") as stream:
            assert b"Year = {1999}" in stream.read()               # it is cdlbib's new text that stands there
            stream.seek(0)
            stream.truncate()
            stream.write(c)
    STEPS[:] = [(announced(ws.bib), nothing), (rename_call, save_b_by_rename), (rename_call, save_c_in_place)]
    with pytest.raises(CdlbibError, match="changed while applying; nothing was written") as refused:
        edit(ws)
    assert ws.bib.read_bytes() == b
    (name,) = [name for name, what in kept(ws).items() if what == c]
    assert name.endswith("cdl.bib.not-installed") and str(ws.work / "kept" / name) in str(refused.value)
    assert strays(ws) == [] and writer.interrupted(ws) is None
    assert edit(ws, "2001").written == ["Kaha12"] and (ws.work / "kept" / name).read_bytes() == c


def test_a_folder_that_could_not_be_exchanged_back_is_kept_and_the_record_stays(ws):
    """The schedule: after the last reading, the bibliography is replaced by a folder. The
    exchange puts cdlbib's file in its place and the folder comes out; the exchange back
    fails (a real failure of the rename: the library's folder is made read-only for that one
    call). The old text can then be written again, and is; but the folder that stood there
    is neither removed nor left under a prepared name without a word: it is kept in the
    write's folder, the error names it, and the record of the write stays."""
    if os.geteuid() == 0:
        pytest.skip("root renames in a read-only folder")
    before = ws.bib.read_bytes()

    def a_folder_in_its_place(event, args):
        os.unlink(ws.bib)
        os.mkdir(ws.bib)
        (ws.bib / "inside.txt").write_text("a file of the user's\n", encoding="utf-8")

    def read_only(event, args):
        os.chmod(ws.root, 0o555)

    def writable_again(event, args):
        os.chmod(ws.root, 0o755)
    STEPS[:] = [(announced(ws.bib), nothing), (rename_call, a_folder_in_its_place), (rename_call, read_only),
                (rename_call, writable_again)]
    try:
        with pytest.raises(WriteConflict) as refused:
            edit(ws)
    finally:
        os.chmod(ws.root, 0o755)
    folders = [name for name, what in kept(ws).items() if what == "a folder"]
    assert len(folders) == 1 and (ws.work / "kept" / folders[0] / "inside.txt").read_text(encoding="utf-8") == "a file of the user's\n"
    assert str(ws.work / "kept" / folders[0]) in str(refused.value)
    assert writer.interrupted(ws) and str(ws.work / "edits" / writer.PENDING) in str(refused.value)
    assert ws.bib.is_file() and ws.bib.read_bytes() == before and strays(ws) == []
    # The next command settles the write, and says where that folder is before the record goes
    # (it finds the write's private folder from the record's stamp).
    lines = api.recover_interrupted(ws)
    assert len(lines) == 1 and str(ws.work / "kept" / folders[0]) in lines[0], lines
    assert "was not what was expected" in lines[0] and writer.interrupted(ws) is None
    assert (ws.work / "kept" / folders[0] / "inside.txt").is_file()


def test_a_bibliography_removed_while_a_write_is_taken_back_is_written_again_and_that_is_said(ws):
    writes, expected = two_files(ws)

    def removed(event, args):
        ledger_appears(ws)(event, args)
        os.unlink(ws.bib)
    STEPS[:] = [(announced(ws.key_renames), removed)]
    with library.transaction(ws):
        with pytest.raises(CdlbibError, match="was removed by something else while it was being written") as refused:
            writer.commit(ws, writes, expected)
    assert "changed while applying" in str(refused.value)
    assert ws.bib.read_bytes() == expected[ws.bib] and strays(ws) == []
    assert list(kept(ws).values()) == [expected[ws.bib]]       # the file the write had replaced: kept, not removed


def test_an_error_that_is_not_of_the_system_takes_the_same_way_back(ws):
    """An audit hook of the program that raises (as an interruption does) between the two
    files of a write: the bibliography, already replaced, is taken back, the record of the
    write is removed, and the error is the hook's own."""
    writes, expected = two_files(ws)

    def raises(event, args):
        raise RuntimeError("raised by an audit hook")
    STEPS[:] = [(announced(ws.key_renames), raises)]
    with library.transaction(ws):
        with pytest.raises(RuntimeError, match="raised by an audit hook"):
            writer.commit(ws, writes, expected)
    assert ws.bib.read_bytes() == expected[ws.bib] and not ws.key_renames.exists()
    assert writer.interrupted(ws) is None and strays(ws) == []


def test_reading_stops_at_the_size_the_file_had(tmp_path):
    path = tmp_path / "grows"
    path.write_bytes(b"x" * 1000)
    fd = os.open(path, os.O_RDONLY)
    try:
        with open(path, "ab") as stream:                           # it has grown tenfold before it is read
            stream.write(b"y" * 9000)
        assert writer._read_fd(fd)[:2] == (b"x" * 1000 + b"y" * 9000, True)     # as it is now: stable
    finally:
        os.close(fd)
    # a file with no end: one byte past the size it reports is read, and no more
    fd = os.open("/dev/zero", os.O_RDONLY)
    try:
        data, stable, _ = writer._read_fd(fd)
    finally:
        os.close(fd)
    assert (len(data), stable) == (1, False)


# --- descriptors ----------------------------------------------------------------------------------------

LEAKS = HEAD + """
import errno, resource
from cdlbib import writer
resource.setrlimit(resource.RLIMIT_NOFILE, (64, resource.getrlimit(resource.RLIMIT_NOFILE)[1]))
def descriptors():
    return len(os.listdir('/dev/fd'))
state = {{'armed': False, 'exchanged': False, 'held': []}}
def audit(event, args):
    if not state['armed']:
        return
    if event == 'os.rename' and args[2] == -1 and str(args[1]) == str(ws.bib):
        state['exchanged'] = None
    elif event == 'os.rename' and args[2] != -1 and state['exchanged'] is None:
        state['exchanged'] = True
    elif event == 'open' and state['exchanged'] is True and not state['held']:
        try:
            while True:
                state['held'].append(os.dup(0))
        except OSError as exc:
            assert exc.errno == errno.EMFILE, exc
sys.addaudithook(audit)
baseline, counts, said = None, [], set()
for turn in range({turns}):
    opened = api.entry(ws, 'Zoll90').fingerprint
    state.update(armed=True, exchanged=False, held=[])
    try:
        api.save_edit(ws, 'Zoll90', {raw!r}, opened)
        said.add('DONE')
    except CdlbibError as exc:
        said.add(type(exc).__name__)
    state['armed'] = False
    for fd in state['held']:
        os.close(fd)
    with library.transaction(ws):            # settles the write
        pass
    if baseline is None:
        baseline = descriptors()
    counts.append(descriptors())
import json
print(json.dumps([sorted(said), baseline, sorted(set(counts))]))
"""


def test_descriptors_are_all_closed_again_after_failures_under_a_low_limit(ws):
    """Twenty writes in one process, each brought to a real EMFILE (RLIMIT_NOFILE 64) at the
    first file opened after the exchange, each settled afterwards: the number of descriptors
    the process has open is the same after every one of them."""
    process = child(LEAKS.format(root=str(ws.root), raw=RENAMED, turns=20), ws.root)
    try:
        said = line(process, 120)
        assert process.wait(timeout=60) == 0, process.stderr.read()
    finally:
        finish(process)
    import json
    outcomes, baseline, counts = json.loads(said)
    assert outcomes == ["WriteConflict"] and counts == [baseline], said


# --- what a later command must not lose or pass over ---------------------------------------------------

AT_THE_END = HEAD + """
opened = api.entry(ws, 'Zoll90').fingerprint
def audit(event, args):
    if event == 'os.remove' and str(args[0]) == 'write-in-progress.json':
        print('paused', flush=True)
        signal.pause()
sys.addaudithook(audit)
api.save_edit(ws, 'Zoll90', {raw!r}, opened)
"""


def test_a_ledger_copy_that_is_the_file_a_program_has_open_survives_the_settling_of_a_killed_write(ws):
    """Another program has the key-rename ledger open. A write of both files replaces them
    (the ledger that program has open becomes the write's copy of it) and is killed just
    before its record is removed. The next command settles the write. What the other
    program then writes through its descriptor is still in a file with a name: the settling
    did not remove the copies."""
    ws.key_renames.parent.mkdir()
    ws.key_renames.write_bytes(b"[]\n")
    theirs = os.open(ws.key_renames, os.O_WRONLY | os.O_APPEND)
    try:
        process = child(AT_THE_END.format(root=str(ws.root), raw=RENAMED), ws.root)
        try:
            assert line(process) == "paused"
            process.kill()
            process.wait(timeout=10)
        finally:
            finish(process)
        held = os.fstat(theirs)
        (copy,) = [item for item in (ws.work / "edits").iterdir() if item.name.endswith("-" + ws.key_renames.name)]
        assert (os.stat(copy).st_dev, os.stat(copy).st_ino) == (held.st_dev, held.st_ino) and writer.interrupted(ws)
        lines = api.recover_interrupted(ws)
        assert len(lines) == 1 and "nothing is missing" in lines[0] and writer.interrupted(ws) is None
        os.write(theirs, b"% written by the program that had it open\n")
        assert os.fstat(theirs).st_nlink == 1 and copy.read_bytes() == b"[]\n% written by the program that had it open\n"
    finally:
        os.close(theirs)
    assert b"Zoller1990" in ws.bib.read_bytes() and b"Zoller1990" in ws.key_renames.read_bytes()


def test_the_record_stays_when_something_unexpected_was_kept_whatever_was_raised(ws, tmp_path):
    """The prepared file is swapped for a link just before the exchange, so a link has to be
    kept aside; and while that is being dealt with, an audit hook of the program raises an
    error that is not the system's. The bibliography is as it was, the link is kept, the
    error is the hook's own, and the record of the write is NOT removed: something
    unexpected was kept, and the next command is to say so."""
    victim = tmp_path / "victim.txt"
    victim.write_text("not cdlbib's to touch\n", encoding="utf-8")
    before, prepared = ws.bib.read_bytes(), []

    def remember(event, args):
        prepared.append(str(args[0]))

    def swap_for_a_link(event, args):
        os.unlink(prepared[0])
        os.symlink(victim, prepared[0])

    def raises(event, args):
        raise RuntimeError("raised by an audit hook")
    STEPS[:] = [(announced(ws.bib), remember), (rename_call, swap_for_a_link), (rename_call, nothing), (rename_call, raises)]
    with pytest.raises(RuntimeError, match="raised by an audit hook"):
        edit(ws)
    assert ws.bib.read_bytes() == before and not ws.bib.is_symlink() and strays(ws) == []
    links = [name for name, what in kept(ws).items() if what == f"link to {victim}"]
    assert len(links) == 1 and writer.interrupted(ws)
    lines = api.recover_interrupted(ws)
    assert len(lines) == 1 and str(ws.work / "kept" / links[0]) in lines[0] and writer.interrupted(ws) is None
    assert victim.read_text(encoding="utf-8") == "not cdlbib's to touch\n"


def test_what_a_successful_save_had_to_keep_aside_is_said_to_the_caller(ws):
    """A save completes, but the file it replaced cannot become its copy (a folder was put in
    the copy's place): it stays in the write's private folder, and the result of the save
    says so, with the path."""
    def a_folder_in_the_copys_place(event, args):
        (copy,) = [item for item in (ws.work / "edits").iterdir() if item.name.endswith("-cdl.bib")]
        os.unlink(copy)
        os.mkdir(copy)
        (copy / "inside.txt").write_text("x\n", encoding="utf-8")
    STEPS[:] = [(announced(ws.bib), nothing), (rename_call, nothing), (rename_call, nothing),
                (rename_call, a_folder_in_the_copys_place)]
    applied = edit(ws)
    assert applied.written == ["Kaha12"] and b"Year = {1999}" in ws.bib.read_bytes()
    assert kept(ws) and any(str(ws.work / "kept") in note for note in applied.notes), applied.notes
