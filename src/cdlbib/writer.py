"""The one transactional writer of a library's own files (cdl.bib and the key-rename ledger).
``complete.apply`` and ``desk.save_edit`` plan their text and hand it here. Nothing here
prints or prompts; the caller holds the library's write lock (library.serialized).

Whole files are prepared beside their targets, flushed, and moved into place only when every
target still holds the bytes the caller planned from. Before the first move:

- the managed library takes its command checkpoint (library.completion_checkpoint) and
  records the write as in progress (library._mark); a writer killed part-way is announced by
  every later command until `cdlbib update --undo` restores that backup;
- any other library gets a copy of cdl.bib as it was, <.bibcheck>/edits/<UTC stamp>-<name>
  (the newest KEEP_EDITS are kept), and a record of the write in progress beside it. A writer
  killed part-way is settled by the next write (``recover``): files the dead writer had
  already replaced are put back from those copies, so the library is whole again as it was.
"""
import contextlib
import datetime
import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CdlbibError

EDITS = "edits"                      # under the library's .bibcheck/
KEEP_EDITS = 20                      # pre-write copies kept for a library cdlbib does not manage
PENDING = "write-in-progress.json"


@dataclass
class Written:
    backup: object = None            # managed library: the library.Backup taken before the write
    saved_copy: Path | None = None   # any other library: the copy of cdl.bib as it was
    notes: list = field(default_factory=list)


def require_protectable(ws):
    """A bibliography inside the managed library other than its cdl.bib is refused: the
    managed backup would not hold it."""
    from . import api, library
    if api.is_managed(ws) and ws.bib.resolve() != (library.path() / 'cdl.bib').resolve():
        raise CdlbibError('The managed backup cannot protect this named bibliography; use the managed cdl.bib')


def renames_recorded(ws, renamed, reason):
    """(the key-rename ledger, its bytes now or None, its bytes with ``renamed`` {old: new}
    appended): one record per rename, dated today, with no commit yet. ValueError when the
    ledger is not a list of records."""
    ledger = ws.key_renames
    original = ledger.read_bytes() if ledger.exists() else None
    records = json.loads(original) if original is not None else []
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError('The key rename ledger must be a list of records')
    records += [dict(old_key=old, new_key=new, date=datetime.date.today().isoformat(), reason=reason, commit=None)
                for old, new in renamed.items()]
    return ledger, original, (json.dumps(records, indent=1, ensure_ascii=False) + '\n').encode('utf-8')


def _sha(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def _bytes(path):
    return path.read_bytes() if path.exists() else None


def _put(target, data):
    """Replace ``target`` with ``data`` whole (None: remove it)."""
    if data is None:
        target.unlink(missing_ok=True)
        return
    fd, name = tempfile.mkstemp(prefix='.rollback-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise


# The record of a write in progress is a file in a folder that other tools, a sync service or a
# cloned repository can put files in, so it is read as data about two fixed files and never as
# a list of paths: the files are ws.bib ("bib") and ws.key_renames ("renames"), their copies
# are <edits>/<stamp>-<file name>, and a prepared file is a name (never a path) of the exact
# form the writer makes, beside its target. Everything is checked (schema, names, ordinary
# files that are not links, sha256) before anything is restored or removed.

_STAMP = re.compile(r"\d{8}T\d{6}\.\d{6}Z")
_SHA = re.compile(r"[0-9a-f]{64}")


def _targets(ws):
    return {"bib": ws.bib, "renames": ws.key_renames}


def _edits(ws):
    """<.bibcheck>/edits; CdlbibError when something that is not a folder of its own (a link,
    a file) stands there: copies are never written or removed through a link."""
    folder = ws.work / EDITS
    if os.path.lexists(folder) and (os.path.islink(folder) or not os.path.isdir(folder)):
        raise CdlbibError(f"{folder} is not an ordinary folder, so cdlbib will not keep or remove copies there; "
                          "nothing was changed.")
    return folder


def _ordinary(path):
    """Is ``path`` an ordinary file (not a link, a folder or anything else)? None: not there."""
    try:
        found = os.lstat(path)
    except FileNotFoundError:
        return None
    return stat.S_ISREG(found.st_mode)


def _record(ws):
    """The record of the write in progress, checked: (stamp, {name: (before, after)},
    {name: the prepared file's name}). ValueError when it is not exactly what _copies writes."""
    marker = _edits(ws) / PENDING
    if _ordinary(marker) is not True:
        raise ValueError("it is not an ordinary file")
    data = json.loads(marker.read_text(encoding='utf-8'))
    known = _targets(ws)
    if not isinstance(data, dict) or set(data) != {"stamp", "targets", "staged"}:
        raise ValueError("unexpected contents")
    stamp, targets, staged = data["stamp"], data["targets"], data["staged"]
    if not isinstance(stamp, str) or not _STAMP.fullmatch(stamp):
        raise ValueError("the time stamp is not one")
    if (not isinstance(targets, dict) or not isinstance(staged, dict) or "bib" not in targets
            or not set(targets) <= set(known) or set(staged) != set(targets)):
        raise ValueError("it names files a write does not touch")
    found = {}
    for name, item in targets.items():
        if not isinstance(item, dict) or set(item) != {"before", "after"}:
            raise ValueError(f"unexpected contents for {name}")
        before, after = item["before"], item["after"]
        if not (before is None or (isinstance(before, str) and _SHA.fullmatch(before))) or not (
                isinstance(after, str) and _SHA.fullmatch(after)) or (name == "bib" and before is None):
            raise ValueError(f"the checksums of {name} are not checksums")
        prepared = staged[name]
        if not isinstance(prepared, str) or not re.fullmatch(
                r"\." + re.escape(known[name].name) + r"-[A-Za-z0-9_]{1,32}", prepared):
            raise ValueError(f"the prepared file of {name} does not have a name the writer gives")
        found[name] = (before, after)
    return stamp, found, staged


def interrupted(ws):
    """For a library cdlbib does not manage: the copy of cdl.bib taken before a write that
    did not finish ('' when the record of it cannot be read); None when there is none.
    Read-only. (The managed library's is library.interrupted.)"""
    if not os.path.lexists(ws.work / EDITS / PENDING):
        return None
    try:
        return str(_edits(ws) / f"{_record(ws)[0]}-{ws.bib.name}")
    except (OSError, ValueError, CdlbibError):
        return ""


def recover(ws):
    """Settle a write to an unmanaged library that was killed part-way, with the lock held.
    Returns the lines saying what was done ([] when there was nothing to settle). Every file
    is compared with what the dead writer recorded: all as before, or all as it meant to
    leave them, needs nothing; some replaced and some not, and the replaced ones are put back
    from the copies it took. Only ws.bib, ws.key_renames, their copies in <.bibcheck>/edits
    and the writer's prepared files beside them are ever touched: the record names no path.
    A record that is not exactly what the writer writes, a file that is a link, a file that
    is neither as before nor as planned (someone changed it since), or a copy or prepared file
    whose checksum is not the recorded one stops this with a CdlbibError before anything is
    touched. The managed library is not handled here: its lock refuses until the backup is
    restored."""
    from . import api
    marker = ws.work / EDITS / PENDING
    if api.is_managed(ws) or not os.path.lexists(marker):
        return []
    folder = _edits(ws)
    try:
        stamp, recorded, staged = _record(ws)
    except (OSError, ValueError) as exc:
        raise CdlbibError(f"An earlier write to {ws.bib} was interrupted and its record ({marker}) cannot be used "
                          f"({exc}); nothing was changed. The copies taken before each write are in {folder}.") from exc
    known = _targets(ws)
    copy = folder / f"{stamp}-{ws.bib.name}"

    def refuse(why):
        return CdlbibError(f"An earlier write to {ws.bib} was interrupted, and {why}; nothing was changed now. The "
                           f"record of that write is {marker}; the bibliography as it was before it is {copy}.")

    # Read and check everything first; nothing is changed until all of it holds.
    now, saved, prepared = {}, {}, {}
    for name, (before, after) in recorded.items():
        target = known[name]
        if _ordinary(target) is False:
            raise refuse(f"{target} is not an ordinary file")
        now[name] = _sha(_bytes(target))
        if now[name] not in (before, after):
            raise CdlbibError(f"An earlier write to {ws.bib} was interrupted, and the library was changed since; "
                              f"nothing was changed now. The bibliography as it was before that write is {copy}. "
                              f"Compare the two, then delete {marker}.")
        kept = folder / f"{stamp}-{target.name}"
        if _ordinary(kept) is not None:
            if _ordinary(kept) is False or _sha(kept.read_bytes()) != before:
                raise refuse(f"the copy {kept} is not the file that write saved")
            saved[name] = kept
        waiting = target.parent / staged[name]
        if _ordinary(waiting) is not None:
            if _ordinary(waiting) is False or _sha(waiting.read_bytes()) != after:
                raise refuse(f"the prepared file {waiting} is not the one that write made")
            prepared[name] = waiting
    replaced = [name for name, (before, after) in recorded.items() if now[name] == after and before != after]
    whole = not replaced or len(replaced) == len([1 for before, after in recorded.values() if before != after])
    if not whole:
        for name in replaced:
            if recorded[name][0] is not None and name not in saved:
                raise refuse(f"the copy of {known[name]} from before it is missing")
        for name in replaced:
            _put(known[name], saved[name].read_bytes() if name in saved else None)
    for waiting in prepared.values():
        waiting.unlink(missing_ok=True)
    for name, kept in saved.items():
        if name != "bib":
            kept.unlink(missing_ok=True)
    marker.unlink()
    if not whole:
        return [f"an earlier write to {ws.bib} was interrupted part-way; the library was put back as it was before "
                f"that write (the bibliography as it was is also in {copy})"]
    if replaced:
        return [f"an earlier write to {ws.bib} was interrupted just after it had written everything; nothing is missing"]
    return [f"an earlier write to {ws.bib} was interrupted before anything was written; the library is as it was"]


def _json(file, data):
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=file.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, file)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise


def _copies(ws, staged, writes):
    """Copy what is about to be replaced into <.bibcheck>/edits and record the write as in
    progress (logical names, checksums and the prepared files' names: no path). Returns (the
    copy of the bibliography, the copies only a recovery needs)."""
    ws.work.mkdir(parents=True, exist_ok=True)
    folder = _edits(ws)
    folder.mkdir(exist_ok=True)
    names = {path: name for name, path in _targets(ws).items()}
    if any(target not in names for target, _, _ in staged):
        raise CdlbibError("The writer replaces only the bibliography and the key-rename ledger; nothing was written")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    after = dict(writes)
    targets, prepared, copy, extra = {}, {}, None, []
    for target, temporary, previous in staged:
        if previous is not None:
            saved = folder / f"{stamp}-{target.name}"
            _put(saved, previous)
            if target == ws.bib:
                copy = saved
            else:
                extra.append(saved)
        targets[names[target]] = {"before": _sha(previous), "after": _sha(after[target])}
        prepared[names[target]] = temporary.name
    _json(folder / PENDING, {"stamp": stamp, "targets": targets, "staged": prepared})
    return copy, extra


def _prune(ws):
    """Keep the copies of the newest KEEP_EDITS writes. Only ordinary files in the edits folder
    itself whose names are exactly <stamp>-<a file the writer copies> are ever removed."""
    folder = _edits(ws)
    copied = "|".join(re.escape(path.name) for path in _targets(ws).values())
    named = {name: match[1] for name in os.listdir(folder)
             if (match := re.fullmatch(r"(\d{8}T\d{6}\.\d{6}Z)-(?:" + copied + ")", name))}
    old = sorted(set(named.values()), reverse=True)[KEEP_EDITS:]
    for name, stamp in named.items():
        if stamp in old and _ordinary(folder / name):
            with contextlib.suppress(OSError):
                os.unlink(folder / name)


def commit(ws, writes, expected, *, batch=None, operation="entry completion"):
    """Install ``writes`` ([(path, bytes)], the bibliography first) and return a Written.
    ``expected`` gives, for each path, the bytes the caller read and planned from (None: the
    file was not there); a path that holds anything else by now refuses the whole write with a
    CdlbibError ("changed while applying") and nothing is replaced. ``batch`` is the managed
    command's library.CompletionBatch, ``operation`` the name an interrupted write is
    announced by. A move that fails puts back the files already moved and raises OSError."""
    from . import api, library
    done, staged = Written(), []
    try:
        # Prepare every file before replacing either, so permission/disk failures
        # during preparation leave both originals intact.
        for target, data in writes:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.' + target.name + '-', dir=target.parent)
            staged.append((target, Path(name), expected[target]))
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if target.exists():
                os.chmod(name, target.stat().st_mode & 0o777)
        for target, _, previous in staged:
            if (target.read_bytes() if target.exists() else None) != previous:
                raise CdlbibError(f'{target} changed while applying; nothing was written')
        if ws.bib.read_bytes() != expected[ws.bib]:
            raise CdlbibError('The bibliography changed while applying; nothing was written')
        managed, extra = api.is_managed(ws), []
        if managed:
            done.backup = library.completion_checkpoint(ws, batch)
            library._mark(done.backup, operation)
        else:
            done.saved_copy, extra = _copies(ws, staged, writes)
        installed = []
        try:
            for target, temporary, previous in staged:
                os.replace(temporary, target)
                installed.append((target, previous))
        except OSError:
            for target, previous in reversed(installed):
                if previous is None:
                    target.unlink()
                else:
                    fd, name = tempfile.mkstemp(prefix='.rollback-', dir=target.parent)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(previous)
                    os.replace(name, target)
            if not managed:
                (ws.work / EDITS / PENDING).unlink(missing_ok=True)
            raise
        if managed:
            library._unmark()
            library._prune(library.backups_folder(), ws.root)
        else:
            (ws.work / EDITS / PENDING).unlink(missing_ok=True)
            for saved in extra:
                saved.unlink(missing_ok=True)
            _prune(ws)
        return done
    finally:
        for _, temporary, _ in staged:
            temporary.unlink(missing_ok=True)
