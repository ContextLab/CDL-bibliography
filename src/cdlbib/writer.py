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
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CdlbibError

EDITS = "edits"                      # under the library's .bibcheck/
KEEP_EDITS = 20                      # pre-write copies kept for a library cdlbib does not manage
PENDING = "write-in-progress.json"
_COPY = re.compile(r"(\d{8}T\d{6}\.\d{6}Z)-.+")


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


def interrupted(ws):
    """For a library cdlbib does not manage: the copy of cdl.bib taken before a write that
    did not finish ('' when the record of it cannot be read); None when there is none.
    Read-only. (The managed library's is library.interrupted.)"""
    marker = ws.work / EDITS / PENDING
    try:
        return str(ws.work / EDITS / json.loads(marker.read_text(encoding='utf-8'))["copy"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def recover(ws):
    """Settle a write to an unmanaged library that was killed part-way, with the lock held.
    Returns the lines saying what was done ([] when there was nothing to settle). Every file
    is compared with what the dead writer recorded: all as before, or all as it meant to
    leave them, needs nothing; some replaced and some not, and the replaced ones are put back
    from the copies it took. A file that is neither (someone changed it since) stops this
    with a CdlbibError and nothing is touched. The managed library is not handled here: its
    lock refuses until the backup is restored."""
    from . import api
    folder = ws.work / EDITS
    marker = folder / PENDING
    if api.is_managed(ws) or not marker.exists():
        return []
    try:
        record = json.loads(marker.read_text(encoding='utf-8'))
        copy = folder / record["copy"]
        targets = [(Path(item["path"]), item["before"], item["after"],
                    folder / item["saved"] if item["saved"] else None) for item in record["targets"]]
        staged = [Path(name) for name in record.get("staged", [])]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CdlbibError(f"An earlier write to {ws.bib} was interrupted and its record ({marker}) cannot be read; "
                          f"nothing was changed. The copies taken before each write are in {folder}.") from exc
    now = {path: _sha(_bytes(path)) for path, *_ in targets}
    if any(now[path] not in (before, after) for path, before, after, _ in targets):
        raise CdlbibError(f"An earlier write to {ws.bib} was interrupted, and the library was changed since; nothing "
                          f"was changed now. The bibliography as it was before that write is {copy}. Compare the two, "
                          f"then delete {marker}.")
    replaced = [(path, before, saved) for path, before, after, saved in targets
                if now[path] == after and before != after]
    whole = not replaced or len(replaced) == len([1 for _, before, after, _ in targets if before != after])
    if not whole:
        for path, before, saved in replaced:
            data = None if before is None else saved.read_bytes()
            if _sha(data) != before:
                raise CdlbibError(f"An earlier write to {ws.bib} was interrupted, and the copy taken before it "
                                  f"({saved}) is not what it was; nothing was changed now.")
            _put(path, data)
    for name in staged:
        name.unlink(missing_ok=True)
    for _, _, _, saved in targets:
        if saved is not None and saved != copy:
            saved.unlink(missing_ok=True)
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


def _copies(ws, staged, expected, writes):
    """Copy what is about to be replaced into <.bibcheck>/edits and record the write as in
    progress. Returns (the copy of the bibliography, the copies only a recovery needs)."""
    folder = ws.work / EDITS
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    after = dict(writes)
    record, copy, extra = [], None, []
    for target, _, previous in staged:
        saved = None
        if previous is not None:
            saved = folder / f"{stamp}-{target.name}"
            _put(saved, previous)
            if target == ws.bib:
                copy = saved
            else:
                extra.append(saved)
        record.append({"path": str(target), "before": _sha(previous), "after": _sha(after[target]),
                       "saved": saved.name if saved else None})
    if copy is None:                     # there was no bibliography file yet: an empty copy names the state
        copy = folder / f"{stamp}-{ws.bib.name}"
        _put(copy, expected.get(ws.bib) or b'')
    _json(folder / PENDING, {"copy": copy.name, "targets": record,
                             "staged": [str(temporary) for _, temporary, _ in staged]})
    return copy, extra


def _prune(ws):
    """Keep the copies of the newest KEEP_EDITS writes."""
    folder = ws.work / EDITS
    stamps = sorted({match[1] for match in map(_COPY.fullmatch, os.listdir(folder)) if match}, reverse=True)
    for name in os.listdir(folder):
        match = _COPY.fullmatch(name)
        if match and match[1] in stamps[KEEP_EDITS:]:
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
            done.saved_copy, extra = _copies(ws, staged, expected, writes)
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
