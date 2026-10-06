"""The record of an interrupted write is data about two fixed files, never a list of paths.

Each test makes a real interrupted write (a writer process killed between two replacements,
as tests/test_locking.py), then replaces or damages what it left with something the writer
would never write: a record naming a file outside the library, an absolute path, a link in
place of a prepared file or a copy, a wrong checksum. Every later write must refuse and leave
every file byte for byte as it was. Real files and processes; no mocks.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from cdlbib import api, complete, writer
from cdlbib.errors import CdlbibError
from cdlbib.verification import load_entries

from test_locking import KAHA12, killed_at, ws  # noqa: F401 - the two-entry library and the real kill


def everything(folder):
    """Every file under ``folder`` with its bytes, and every link with where it points. (Not
    the empty .bibcheck/lock: the killed writer died holding it, and the next holder removes
    it on release, as every holder does.)"""
    return {str(item.relative_to(folder)): (os.readlink(item) if item.is_symlink() else item.read_bytes())
            for item in sorted(Path(folder).rglob("*"))
            if (item.is_symlink() or item.is_file()) and item.parts[-2:] != (".bibcheck", "lock")}


def plant_path(record, ws, victim):                      # the shape of a record that names paths
    record["targets"] = [{"path": "../../victim.txt", "before": None, "after": record["targets"]["bib"]["after"],
                          "saved": None}]
    record["staged"] = ["../../victim.txt"]


def plant_relative_name(record, ws, victim):
    record["staged"]["renames"] = "../../victim.txt"


def plant_absolute_name(record, ws, victim):
    record["staged"]["bib"] = str(victim)


def plant_target(record, ws, victim):
    record["targets"]["../../victim.txt"] = record["targets"]["renames"]
    record["staged"]["../../victim.txt"] = record["staged"]["renames"]


def plant_absolute_target(record, ws, victim):
    record["targets"] = {"bib": record["targets"]["bib"], str(victim): record["targets"]["renames"]}
    record["staged"] = {"bib": record["staged"]["bib"], str(victim): record["staged"]["renames"]}


def plant_extra_key(record, ws, victim):
    record["copy"] = str(victim)


def plant_stamp(record, ws, victim):
    record["stamp"] = "../../victim.txt"


def plant_linked_temp(record, ws, victim):
    prepared = ws.key_renames.parent / record["staged"]["renames"]
    assert prepared.is_file() and not prepared.is_symlink()
    prepared.unlink()
    prepared.symlink_to(victim)


def plant_wrong_hash(record, ws, victim):                # "before" is not the checksum of the copy on disk
    record["targets"]["bib"]["before"] = "0" * 64


def plant_wrong_prepared_hash(record, ws, victim):       # the prepared file is not what the record says it made
    prepared = ws.key_renames.parent / record["staged"]["renames"]
    prepared.write_bytes(b"[]\n")


def plant_changed_copy(record, ws, victim):
    copy = ws.work / "edits" / f"{record['stamp']}-cdl.bib"
    copy.write_bytes(victim.read_bytes())


def plant_linked_copy(record, ws, victim):
    copy = ws.work / "edits" / f"{record['stamp']}-cdl.bib"
    copy.unlink()
    copy.symlink_to(victim)


def plant_linked_folder(record, ws, victim):
    real = ws.root.parent / "elsewhere"
    (ws.work / "edits").rename(real)
    (ws.work / "edits").symlink_to(real)


def plant_linked_record(record, ws, victim):
    marker = ws.work / "edits" / writer.PENDING
    kept = ws.root.parent / "record.json"
    marker.rename(kept)
    marker.symlink_to(kept)


def plant_not_json(record, ws, victim):
    record.clear()


@pytest.mark.parametrize("plant", [
    plant_path, plant_relative_name, plant_absolute_name, plant_target, plant_absolute_target, plant_extra_key,
    plant_stamp, plant_linked_temp, plant_wrong_hash, plant_wrong_prepared_hash, plant_changed_copy, plant_linked_copy,
    plant_linked_folder, plant_linked_record, plant_not_json])
def test_a_planted_or_damaged_record_changes_nothing(ws, tmp_path, plant):
    victim = tmp_path / "victim.txt"
    victim.write_text("not cdlbib's to touch\n", encoding="utf-8")
    killed_at(ws, ws.key_renames)
    marker = ws.work / "edits" / writer.PENDING
    record = json.loads(marker.read_text(encoding="utf-8"))
    assert set(record) == {"stamp", "targets", "staged"} and set(record["targets"]) == {"bib", "renames"}
    assert all(os.sep not in name for name in record["staged"].values())       # the writer records names, never paths
    assert str(ws.root) not in marker.read_text(encoding="utf-8")
    linked = plant is plant_linked_record
    plant(record, ws, victim)
    if not linked:
        (ws.work / "edits" / writer.PENDING).write_text(json.dumps(record) if record else "{ not json", encoding="utf-8")
    before = everything(tmp_path)
    opened = load_entries(ws.bib)["Kaha12"]["fingerprint"]
    for attempt in (lambda: api.recover_interrupted(ws),
                    lambda: api.save_edit(ws, "Kaha12", KAHA12.replace("2012", "2013"), opened),
                    lambda: complete.apply(ws, [])):
        with pytest.raises(CdlbibError, match="interrupted|not an ordinary folder") as refused:
            attempt()
        assert writer.PENDING in str(refused.value) or "edits" in str(refused.value)   # the record or its folder is named
        assert everything(tmp_path) == before
    assert victim.read_text(encoding="utf-8") == "not cdlbib's to touch\n"
    assert writer.interrupted(ws) is not None and api.library_state(ws).interrupted is not None
    assert everything(tmp_path) == before


def test_the_untouched_record_of_the_same_kill_is_settled(ws, tmp_path):
    """The control for the test above: without the planting, the same state recovers."""
    before = ws.bib.read_bytes()
    killed_at(ws, ws.key_renames)
    assert ws.bib.read_bytes() != before
    assert len(api.recover_interrupted(ws)) == 1 and ws.bib.read_bytes() == before


def test_only_the_writers_own_copies_are_pruned_and_never_through_a_link(ws, tmp_path):
    edits = ws.work / "edits"
    edits.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n", encoding="utf-8")
    old = "20200101T000000.000000Z"
    (edits / f"{old}-notes.txt").write_text("someone's file\n", encoding="utf-8")       # not a name the writer gives
    (edits / f"{old}-cdl.bib.orig").write_text("nor this\n", encoding="utf-8")
    (edits / f"{old}-cdl.bib").symlink_to(outside)                                      # the name, but a link
    (edits / "19990101T000000.000000Z-cdl.bib").write_text("an old copy\n", encoding="utf-8")
    for number in range(writer.KEEP_EDITS + 1):
        api.save_edit(ws, "Kaha12", KAHA12.replace("2012", str(1990 + number)), load_entries(ws.bib)["Kaha12"]["fingerprint"])
    names = sorted(item.name for item in edits.iterdir())
    assert f"{old}-notes.txt" in names and f"{old}-cdl.bib.orig" in names and f"{old}-cdl.bib" in names
    assert "19990101T000000.000000Z-cdl.bib" not in names and outside.read_text(encoding="utf-8") == "keep\n"
    assert len([name for name in names if name.endswith("-cdl.bib")]) == writer.KEEP_EDITS + 1     # 20 and the link
    real = tmp_path / "elsewhere"
    edits.rename(real)
    edits.symlink_to(real)
    kept = everything(tmp_path)
    with pytest.raises(CdlbibError, match="not an ordinary folder"):
        api.save_edit(ws, "Kaha12", KAHA12, load_entries(ws.bib)["Kaha12"]["fingerprint"])
    assert everything(tmp_path) == kept and hashlib.sha256(outside.read_bytes()).hexdigest()


# --- paths swapped for links while writes run ---------------------------------------------------

SWAPPER = """
import glob, os, sys, time
root, outside, victim, stop = sys.argv[1:5]
work, aside = os.path.join(root, '.bibcheck'), os.path.join(root, '.bibcheck.aside')
turn = 0
while not os.path.exists(stop):
    turn += 1
    try:
        if turn % 3 == 0:                      # the working folder becomes a link to a folder outside
            os.rename(work, aside)
            try:
                os.symlink(outside, work)
                time.sleep(0.002)
                os.unlink(work)
            finally:
                if not os.path.lexists(work):
                    os.rename(aside, work)
        elif turn % 3 == 1:                    # the prepared files become links to a file outside
            made = []
            for name in glob.glob(os.path.join(root, '.cdl.bib-*')):
                os.unlink(name)
                os.symlink(victim, name)
                made.append(name)
            time.sleep(0.001)
            for name in made:
                if os.path.islink(name):
                    os.unlink(name)
        else:                                  # the newest copy becomes a link to a file outside
            copies = sorted(glob.glob(os.path.join(work, 'edits', '*-cdl.bib')))
            if copies:
                name = copies[-1]
                os.rename(name, name + '.aside')
                try:
                    os.symlink(victim, name)
                    time.sleep(0.001)
                    os.unlink(name)
                finally:
                    if not os.path.lexists(name):
                        os.rename(name + '.aside', name)
    except OSError:
        pass
print('turns', turn, flush=True)
"""


def test_paths_swapped_for_links_while_writes_run_never_reach_outside_the_library(ws, tmp_path):
    """A second real process keeps swapping .bibcheck, the writer's prepared files and its
    newest copy for links to a folder and a file outside the library, while this process
    saves edits. Every save either completes or refuses with the bibliography exactly as it
    was; nothing outside is written, replaced or removed."""
    import subprocess
    import sys
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_text("not cdlbib's to touch\n", encoding="utf-8")
    stop = tmp_path / "stop"
    api.save_edit(ws, "Kaha12", KAHA12.replace("2012", "1899"), load_entries(ws.bib)["Kaha12"]["fingerprint"])
    expected, apart = ws.bib.read_bytes(), everything(outside)
    swapper = subprocess.Popen([sys.executable, "-c", SWAPPER, str(ws.root), str(outside), str(victim), str(stop)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    done = refused = 0
    try:
        # At least 150 saves, and on until three have completed: where a save takes a fraction
        # of a millisecond (Linux) nearly every one meets a swap and is refused, and 150 can
        # pass with a single one completed.
        for number in range(3000):
            if number >= 150 and done >= 3:
                break
            year = str(1000 + number)
            current = load_entries(ws.bib)["Kaha12"]
            try:
                applied = api.save_edit(ws, "Kaha12", KAHA12.replace("2012", year), current["fingerprint"])
            except CdlbibError:
                refused += 1
            else:
                assert applied.written == ["Kaha12"]
                expected = expected.replace(current["raw"].encode(), KAHA12.replace("2012", year).encode())
                done += 1
            assert not ws.bib.is_symlink() and ws.bib.read_bytes() == expected     # completed, or intact
            assert everything(outside) == apart
    finally:
        stop.write_text("stop", encoding="utf-8")
        out, err = swapper.communicate(timeout=30)
    assert swapper.returncode == 0 and int(out.split()[1]) > 50, out + err
    print("saves completed:", done, "refused:", refused, "swapper", out.strip())
    assert done >= 3 and done + refused >= 150, (done, refused)
    assert everything(outside) == apart and victim.read_text(encoding="utf-8") == "not cdlbib's to touch\n"
    final = api.save_edit(ws, "Kaha12", KAHA12.replace("2012", "2050"), load_entries(ws.bib)["Kaha12"]["fingerprint"])
    assert final.written == ["Kaha12"] and "Year = {2050}" in ws.bib.read_text(encoding="utf-8")
    assert everything(outside) == apart


def test_a_link_given_the_inode_number_of_a_removed_prepared_file_is_not_taken_for_it(tmp_path):
    """Linux file systems give the inode number of a removed file to the next thing made, so
    a link put where a prepared file stood can carry its (device, inode). The writer holds
    the prepared file open, so the number is not free to give, and what the name is now is
    not taken for the file: the move is refused and nothing becomes a link. (On a file system
    that does not reuse numbers the link differs anyway; the refusal is the same.)"""
    library = tmp_path / "library"
    library.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("not cdlbib's to touch\n", encoding="utf-8")
    (library / "cdl.bib").write_bytes(b"as it was\n")
    for attempt in range(50):
        folder = writer._Folder.at(library)
        try:
            name, identity = folder.new(".cdl.bib-", b"new text\n")
            made = os.stat(library / name)
            os.unlink(library / name)
            os.symlink(victim, library / name)
            link = os.lstat(library / name)
            assert (link.st_dev, link.st_ino) != (made.st_dev, made.st_ino), "the link was given the open file's number"
            with pytest.raises(OSError, match="replaced by something else"):
                folder.move(name, "cdl.bib", identity)
            assert folder.identity(name) != identity
        finally:
            os.unlink(library / name)
            folder.close()
        assert not (library / "cdl.bib").is_symlink() and (library / "cdl.bib").read_bytes() == b"as it was\n"
    assert victim.read_text(encoding="utf-8") == "not cdlbib's to touch\n"


def exchanged(library, target_now):
    """A real folder as it stands straight after the writer's exchange, with ``target_now``
    (a function of the library and the prepared file's name) having put something else in
    the bibliography's place since: (the folder, the name the file that was read now has,
    the prepared file's identity, the stamp of the file read, the descriptor held on it,
    the stack that closes it)."""
    import contextlib
    bib = library / "cdl.bib"
    bib.write_bytes(b"as it was read\n")
    folder, keep = writer._Folder.at(library), contextlib.ExitStack()
    name, identity = folder.new(".cdl.bib-", b"the new text\n", 0o644)
    previous, seen, read_fd = folder.read_held("cdl.bib", keep)
    assert previous == b"as it was read\n" and folder.exchange(name, "cdl.bib")
    assert folder.identity("cdl.bib") == identity and folder.stamp(name) == seen
    target_now(library, name)
    return folder, name, identity, seen, read_fd, keep


def test_a_save_another_program_makes_just_after_the_exchange_is_left_in_place(tmp_path):
    """The other program read the bibliography before the exchange and saves (by rename)
    just after it, before the writer has looked: its save is the newest and stays. The write
    is refused as changed; the file that was read is not put back over that save."""
    def saved_by_another(library, name):
        (library / "cdl.bib.editor").write_bytes(b"as it was read\n% saved by the other program\n")
        os.replace(library / "cdl.bib.editor", library / "cdl.bib")
    library = tmp_path / "library"
    library.mkdir()
    folder, name, identity, seen, read_fd, keep = exchanged(library, saved_by_another)
    with keep:
        with pytest.raises(writer._Changed):
            writer._confirm(folder, library / "cdl.bib", name, identity, seen, read_fd, b"as it was read\n")
    folder.close()
    assert (library / "cdl.bib").read_bytes() == b"as it was read\n% saved by the other program\n"


@pytest.mark.parametrize("aside", ["kept", "removed", "a link too"])
def test_a_link_found_in_the_bibliographys_place_after_the_exchange_is_not_left_there(tmp_path, aside):
    """The bibliography's name holds a link to a file outside when the writer looks (the
    prepared name was swapped for it). The file that was read is exchanged back; when it was
    removed or swapped too while it stood aside, its text is written again. Either way the
    write is refused, the bibliography is an ordinary file with what was read, and the file
    outside is untouched."""
    victim = tmp_path / "victim.txt"
    victim.write_text("not cdlbib's to touch\n", encoding="utf-8")

    def swapped(library, name):
        os.unlink(library / "cdl.bib")
        os.symlink(victim, library / "cdl.bib")
        if aside != "kept":
            os.unlink(library / name)
        if aside == "a link too":
            os.symlink(victim, library / name)
    library = tmp_path / "library"
    library.mkdir()
    folder, name, identity, seen, read_fd, keep = exchanged(library, swapped)
    with keep:
        with pytest.raises(writer._Changed):
            writer._confirm(folder, library / "cdl.bib", name, identity, seen, read_fd, b"as it was read\n")
    folder.remove(name)
    folder.close()
    bib = library / "cdl.bib"
    assert not bib.is_symlink() and bib.read_bytes() == b"as it was read\n" and oct(bib.stat().st_mode & 0o777) == "0o644"
    assert victim.read_text(encoding="utf-8") == "not cdlbib's to touch\n" and not victim.is_symlink()
    assert sorted(item.name for item in library.iterdir()) == ["cdl.bib"]
