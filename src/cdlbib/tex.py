"""The TeX side of a library: one link in the user's TeX tree, so that a manuscript anywhere on
the computer finds cdl.bib (`\\bibliography{cdl}`, `\\addbibresource{cdl.bib}`).

The link is <TEXMFHOME>/bibtex/bib/cdl.bib -> the library's cdl.bib. It names the path, so it
follows the library through every update. A link is cdlbib's own only while tex-link.json in
cdlbib's data folder records exactly that link path and target; anything else at the path is
never removed. Nothing here prints, prompts or edits a shell file."""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import library
from .errors import TexLinkRefused
from .workspace import BIB_NAME

RECORD = "tex-link.json"
SAVED = BIB_NAME + ".cdlbib-saved-"      # a file moved aside by replace=True: SAVED + UTC stamp
TIMEOUT = 30                             # seconds one kpsewhich or mktexlsr call is given
STATES = ("linked", "absent", "other_library", "foreign", "no_tex", "shadowed")


@dataclass
class TexStatus:
    """``state``: "linked" (the link is cdlbib's, names this library, and kpsewhich resolves
    cdl.bib to it), "absent", "other_library" (cdlbib's link, to another library), "foreign"
    (a file or link cdlbib did not make), "shadowed" (linked, but kpsewhich finds another file
    or none; ``notes`` say why), "no_tex" (no kpsewhich, so nothing can be resolved).

    ``present`` is what is at the link path whatever TeX says: "absent", "linked",
    "other_library" or "foreign". ``target`` is what a link there names. ``other_trees`` are
    the further folders TEXMFHOME lists (only the first is used). ``changes`` are the things
    link() did, as lines; status() leaves it empty."""
    kpsewhich: str | None
    texmf_home: Path
    link: Path
    target: Path | None
    state: str
    resolves_to: Path | None
    bibinputs_line: str
    notes: list = field(default_factory=list)
    present: str = "absent"
    other_trees: list = field(default_factory=list)
    changes: list = field(default_factory=list)


@dataclass
class Unlinked:
    link: Path
    removed: bool
    reason: str = ""      # why nothing was removed
    notes: list = field(default_factory=list)


def _run(command, cwd=None):
    """(exit status, stdout) of a TeX tool; (None, "") when it could not be run or did not answer."""
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return done.returncode, done.stdout


def trees():
    """(the kpsewhich found on PATH or None, the folders of TEXMFHOME in order).

    With TeX: `kpsewhich -expand-braces '$TEXMFHOME'`, which lists every folder in order
    whether or not it exists yet (`-expand-path` leaves out the ones that do not, so it is
    only the second try). Without TeX, or when it names none: the TEXMFHOME variable, else
    ~/Library/texmf on macOS and ~/texmf elsewhere."""
    kpsewhich = shutil.which("kpsewhich")
    found = []
    if kpsewhich:
        for option in ("-expand-braces", "-expand-path"):
            status, out = _run([kpsewhich, option, "$TEXMFHOME"])
            found = [part.lstrip("!") for part in out.strip().split(os.pathsep) if part.strip("!")] if status == 0 else []
            if found:
                break
    if not found:
        named = [part for part in os.environ.get("TEXMFHOME", "").split(os.pathsep) if part and "{" not in part]
        user = Path(os.environ["HOME"]) if os.environ.get("HOME") else Path.home()
        found = named or [str(user / "Library" / "texmf" if sys.platform == "darwin" else user / "texmf")]
    return kpsewhich, [Path(part).expanduser() for part in found]


def link_path(tree):
    return Path(tree) / "bibtex" / "bib" / BIB_NAME


def _record():
    """The recorded link as {"link", "target"}; None when there is no readable record."""
    try:
        data = json.loads((library.home() / RECORD).read_text(encoding="utf-8"))
        return {"link": str(data["link"]), "target": str(data["target"])}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _write_record(link, target):
    folder = library.home()
    folder.mkdir(parents=True, exist_ok=True)
    library._write_json(folder / RECORD, {
        "link": str(link), "target": str(target),
        "linked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})


def _ours(link):
    """Is the thing at ``link`` the link cdlbib recorded: a symbolic link at exactly the
    recorded path, naming exactly the recorded target."""
    record = _record()
    return bool(record and link.is_symlink() and record["link"] == str(link) and os.readlink(link) == record["target"])


def _present(link, bib):
    """("absent" | "linked" | "other_library" | "foreign", what a link there names or None)."""
    if not os.path.lexists(link):
        return "absent", None
    target = Path(os.readlink(link)) if link.is_symlink() else None
    if not _ours(link):
        return "foreign", target
    return ("linked" if str(target) == str(bib) else "other_library"), target


def _same_place(one, other):
    one, other = Path(one), Path(other)
    return one.name == other.name and one.parent.resolve() == other.parent.resolve()


def _same_file(one, other):
    try:
        return os.path.samefile(one, other)
    except OSError:
        return False


def resolve(kpsewhich, name=BIB_NAME):
    """What `kpsewhich NAME` and `kpsewhich -format=bib NAME` give from an empty folder (so
    that a file in the current folder is not the answer): two paths, each None when not found."""
    found = []
    with tempfile.TemporaryDirectory(prefix="cdlbib-kpsewhich-") as empty:
        for command in ([kpsewhich, name], [kpsewhich, "-format=bib", name]):
            status, out = _run(command, cwd=empty)
            line = out.strip().splitlines()[0] if status == 0 and out.strip() else ""
            found.append(Path(line) if line else None)
    return found


def _search_folders(value):
    return [part.lstrip("!").rstrip("/") for part in value.split(os.pathsep) if part.strip("!/")]


def _why_shadowed(link, winners):
    """The lines saying why kpsewhich does not give the link."""
    searched = os.environ.get("BIBINPUTS", "")
    notes = []
    for winner in dict.fromkeys(winners):
        if winner is None:
            if searched and "" not in searched.split(os.pathsep):
                notes.append(f"kpsewhich does not find {BIB_NAME}: BIBINPUTS is set to {searched!r} with no empty "
                             "component, so the TeX trees are not searched for .bib files")
            else:
                notes.append(f"kpsewhich does not find {BIB_NAME}, although {link} is there")
        elif any(_same_place(winner, Path(folder) / BIB_NAME) or Path(folder).resolve() in winner.resolve().parents
                 for folder in _search_folders(searched)):
            notes.append(f"kpsewhich finds {winner} first, because BIBINPUTS is set to {searched!r}")
        else:
            notes.append(f"kpsewhich finds {winner} first; it is in a folder TeX searches before {link.parent}")
    return notes


def bibinputs_line(ws):
    """The shell line that makes TeX search the library's folder for .bib files (the way that
    needs no link). It is only ever shown: cdlbib writes it into no file."""
    quoted = str(ws.bib.parent)
    for char in ("\\", '"', "$", "`"):
        quoted = quoted.replace(char, "\\" + char)
    return f'export BIBINPUTS="{quoted}:${{BIBINPUTS}}"'


def status(ws):
    """Where the link is or would be, what is there, and what TeX resolves cdl.bib to now.
    Reads only; runs kpsewhich when it is installed."""
    kpsewhich, found = trees()
    link = link_path(found[0])
    present, target = _present(link, ws.bib)
    result = TexStatus(kpsewhich=kpsewhich, texmf_home=found[0], link=link, target=target, state=present,
                       resolves_to=None, bibinputs_line=bibinputs_line(ws), present=present, other_trees=found[1:])
    if found[1:]:
        result.notes.append("TEXMFHOME lists more than one folder; the first is used. The others: "
                            + ", ".join(str(tree) for tree in found[1:]))
    if present == "other_library" and not target.exists():
        result.notes.append(f"the library the link names is no longer there: {target}")
    if not kpsewhich:
        result.state = "no_tex"
        result.notes.append("TeX was not found (no kpsewhich on PATH), so what TeX would resolve cannot be shown")
        return result
    winners = resolve(kpsewhich)
    result.resolves_to = winners[0] or winners[1]
    if present != "linked":
        return result
    wrong = [winner for winner in winners
             if winner is None or not (_same_place(winner, link) or _same_file(winner, ws.bib))]
    if wrong:
        result.state = "shadowed"
        result.notes += _why_shadowed(link, wrong)
    elif not _same_place(winners[0], link):
        result.notes.append(f"kpsewhich finds {winners[0]}, which is this library's file")
    return result


def _refresh(tree, changes, notes):
    """`mktexlsr TREE`, only when the tree has a file-name database (ls-R) to bring up to date."""
    if not (tree / "ls-R").is_file():
        return
    mktexlsr = shutil.which("mktexlsr")
    if mktexlsr and _run([mktexlsr, str(tree)])[0] == 0:
        changes.append(f"refreshed the file-name database of {tree} (mktexlsr)")
    else:
        notes.append(f"{tree} has a file-name database (ls-R) that could not be refreshed; run: mktexlsr {tree}")


def _saved_name(link):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name, number = link.with_name(SAVED + stamp), 1
    while os.path.lexists(name):
        number += 1
        name = link.with_name(f"{SAVED}{stamp}-{number}")
    return name


def link(ws, replace=False):
    """Make <TEXMFHOME>/bibtex/bib/cdl.bib a link to this library's cdl.bib and return the
    status afterwards (``changes`` lists what was done; nothing, when it was linked already).

    cdlbib's own link to another library is pointed at this one. A file or link cdlbib did
    not make is left where it is and TexLinkRefused is raised, unless ``replace``: then it is
    moved aside, beside itself, as cdl.bib.cdlbib-saved-<UTC time>, never deleted. Without TeX
    the link is made in the default tree, where a TeX installed later looks."""
    before = status(ws)
    path, changes = before.link, []
    if before.present == "foreign":
        if not replace:
            raise TexLinkRefused(
                f"{path} exists and was not made by cdlbib"
                + (f" (a link to {before.target})" if before.target else "")
                + "; it was left as it is. With replace, it is moved aside to "
                + f"{SAVED}<time> in the same folder and the link is made.", status=before)
        saved = _saved_name(path)
        os.rename(path, saved)
        changes.append(f"moved the existing {path} aside to {saved}")
    if before.present != "linked":
        earlier = _record()
        if earlier and earlier["link"] != str(path) and _ours(Path(earlier["link"])):
            os.unlink(earlier["link"])     # cdlbib's link in the tree TEXMFHOME named before
            changes.append(f"removed the earlier link {earlier['link']} (the TeX tree is now {before.texmf_home})")
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_record(path, ws.bib)       # first: a crash leaves a record of no link, never an unrecorded link
        if before.present == "other_library":
            temporary = path.with_name(f".{BIB_NAME}.cdlbib-{os.getpid()}")
            os.symlink(str(ws.bib), temporary)
            os.replace(temporary, path)
            changes.append(f"pointed {path} at {ws.bib} (it named {before.target})")
        else:
            try:
                os.symlink(str(ws.bib), path)
            except FileExistsError:
                raise TexLinkRefused(f"{path} appeared while the link was being made; it was left as it is.",
                                     status=before) from None
            changes.append(f"linked {path} -> {ws.bib}")
    notes = []
    if changes:
        _refresh(before.texmf_home, changes, notes)
    after = status(ws)
    after.changes, after.notes = changes, after.notes + notes
    return after


def unlink():
    """Remove cdlbib's link, and only that: a file or link at the path that the record does
    not describe is left where it is."""
    record, (_, found) = _record(), trees()
    path = Path(record["link"]) if record else link_path(found[0])
    if not os.path.lexists(path):
        if record:
            (library.home() / RECORD).unlink(missing_ok=True)
        return Unlinked(path, False, "there is no link")
    if not _ours(path):
        return Unlinked(path, False, "the file there was not made by cdlbib, and was left as it is")
    os.unlink(path)
    (library.home() / RECORD).unlink(missing_ok=True)
    result = Unlinked(path, True)
    changes = []
    _refresh(path.parents[2], changes, result.notes)
    result.notes = changes + result.notes
    return result
