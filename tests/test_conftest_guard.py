"""The suite's guard on the real data folder (tests/conftest.py): what it records of a folder
that exists, and that every kind of change shows. Run on a managed library of the test's own
(a real clone of the local upstream), never on the real folder."""
import os

import conftest
from cdlbib import library
from cdlbib.workspace import Workspace

from test_library import managed  # noqa: F401


def test_the_guard_sees_every_change_to_a_data_folder(managed):
    home, _ = managed
    ws = Workspace(library.download())
    library.write_state(library.State(None, library.upstream()))
    before = conftest.data_folder_state(home)
    assert conftest.data_folder_changes(before, conftest.data_folder_state(home)) == []
    assert before["library/cdl.bib"][0] == "file" and len(before["library/cdl.bib"][3]) == 64
    assert len(before["state.json"][3]) == 64 and "library/.git/HEAD" in before
    assert not any(name.startswith(("library/.git/objects", "library/.git/index")) for name in before)

    def changes():
        return conftest.data_folder_changes(before, conftest.data_folder_state(home))

    stamp = os.stat(ws.bib)
    ws.bib.write_bytes(ws.bib.read_bytes().replace(b"1990", b"1991"))       # same size, and the old time put back
    os.utime(ws.bib, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert changes() == ["library/cdl.bib: changed"]
    ws.bib.write_bytes(ws.bib.read_bytes().replace(b"1991", b"1990"))
    os.utime(ws.bib, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert changes() == []
    (ws.root / ".bibcheck").mkdir()
    (ws.root / ".bibcheck" / "lock").write_text("", encoding="utf-8")
    assert changes() == ["library/.bibcheck: added", "library/.bibcheck/lock: added"]
    (ws.root / ".bibcheck" / "lock").unlink()
    (ws.root / ".bibcheck").rmdir()
    library.backup(ws)
    assert any(name.startswith("backups/") and name.endswith(": added") for name in changes())
    assert "library/cdl.bib: changed" not in changes()
    (home / "state.json").unlink()
    assert "state.json: removed" in changes()


def test_the_real_data_folder_is_as_the_run_found_it():
    assert conftest.real_data_folder_problem() is None
    conftest.no_real_library_touched()
    assert (conftest._REAL_DATA_FOLDER_STATE is None) == (not conftest._REAL_DATA_FOLDER_EXISTED)
