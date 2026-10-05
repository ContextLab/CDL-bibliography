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
