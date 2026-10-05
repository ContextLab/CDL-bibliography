"""What a manuscript cites, as files of its own: a frozen .bib holding the cited entries
exactly as the library has them, and a .bbl compiled with the manuscript's own style.

Compiling runs LaTeX on the manuscript's files, as compiling the paper by hand does: in a
temporary copy, without shell escape, with a time limit per program, and with the search
paths set here. Nothing here prints or prompts; every failure is an ExportFailed."""
import contextlib
import html
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import library, tex
from .errors import ExportFailed

LIMIT = 120                                            # seconds one TeX program is given
ENGINES = {"pdflatex": "-draftmode", "latex": "-draftmode", "lualatex": "--draftmode", "xelatex": "-no-pdf"}
SOURCE_NOTE = "citations were read from the source; citations made by custom macros are not seen"
# What is copied into the build folder, by kind: TeX sources and styles, bibliography files,
# figures, fonts and plain data. Everything else stays behind, so no file of the paper can
# configure a program (biber.conf, texmf.cnf, latexmkrc, a .fmt, a .csf ...). A .cfg is
# copied: TeX reads it as TeX code (biblatex.cfg, hyperref.cfg), which gives the paper nothing
# its .tex does not already have, and papers ship one to set their bibliography's format.
COPIED = (".tex", ".ltx", ".sty", ".cls", ".clo", ".def", ".cfg", ".fd", ".ldf", ".bst", ".bbx", ".cbx", ".dbx", ".lbx",
          ".bib", ".tikz", ".pgf", ".pdf_tex", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps", ".mps", ".svg",
          ".tfm", ".vf", ".pfb", ".afm", ".otf", ".ttf", ".enc", ".map", ".csv", ".tsv", ".dat", ".txt")
MAX_FILES, MAX_BYTES = 5000, 1_000_000_000             # the most that is copied for one paper (with its inputs)
MAX_OUTPUT = 50_000_000                                # bytes of a control file read, or of a .bbl taken, from a build
_SKIPPED_FOLDERS = {"__pycache__", "node_modules"}     # besides every folder whose name starts with a dot
# What an earlier compile left behind is not counted among the "other files" a result mentions.
_LEFTOVERS = (".aux", ".bbl", ".bcf", ".blg", ".run.xml", ".log", ".toc", ".lof", ".lot", ".out", ".fls",
              ".fdb_latexmk", ".synctex.gz", ".nav", ".snm")
_KEPT_VARIABLES = ("PATH", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE")     # all that the programs get of the user's environment
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*\Z")                  # a style or bibliography name given to a backend
_KEY = re.compile(r"[^\s{}(),\\%#^~\"'=&$]+\Z")                        # a citation key given to a backend
JOB = "job"                                            # the backend's files are job.aux/.bcf/.bbl, whatever the paper is called
BCF = "https://sourceforge.net/projects/biblatex"


@dataclass
class Cited:
    """``keys`` in the order first cited; ``all_entries`` for \\nocite{*}; ``sources`` the
    files read; ``backend`` "bibtex", "biber" or None (no bibliography command seen);
    ``style`` the \\bibliographystyle; ``bibdata`` the bibliography resources named, without
    ".bib"; ``how`` "aux", "bcf" (a file the user named), "compiled" (a fresh LaTeX run) or
    "source" (the .tex files were parsed; ``notes`` say so)."""
    keys: list
    all_entries: bool = False
    sources: list = field(default_factory=list)
    backend: str | None = None
    style: str | None = None
    bibdata: list = field(default_factory=list)
    how: str = "source"
    main: Path | None = None
    folder: Path | None = None
    engine: str | None = None
    notes: list = field(default_factory=list)


@dataclass
class Missing:
    key: str
    renamed_to: str | None = None     # the key the library has now, when its rename ledger knows

    def __str__(self):
        return f"{self.key} (now {self.renamed_to})" if self.renamed_to else self.key


@dataclass
class Frozen:
    path: Path
    written: list                     # keys, in library order
    missing: list                     # Missing, in citation order
    parents: list = field(default_factory=list)   # entries included because a cited entry inherits from them
    cited: Cited | None = None
    notes: list = field(default_factory=list)


@dataclass
class Bbl:
    path: Path
    backend: str
    engine: str
    style: str | None
    keys: list
    cited: Cited | None = None
    notes: list = field(default_factory=list)


# --- reading the manuscript ---------------------------------------------------------------

_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%.*")
_MAGIC = re.compile(r"(?im)^\s*%\s*!\s*TeX\s+(?:TS-)?program\s*=\s*([A-Za-z]+)")
_INCLUDED = re.compile(r"\\(?:input|include|subfile)\s*\{([^{}]+)\}")
_CITE = re.compile(r"\\([A-Za-z]*[Cc]ite[A-Za-z]*)\*?")
_NOT_CITES = {"citestyle", "setcitestyle", "DeclareCiteCommand", "DeclareMultiCiteCommand", "DeclareAutoCiteCommand",
              "newcites", "citereset", "citesetup", "mancite", "citeindextrue", "citeindexfalse", "citetracker",
              "AtEveryCite", "AtEveryCitekey", "AtNextCite", "AtNextCitekey", "nocitemeta", "bibcite", "multicitedelim",
              "supercitedelim", "postcite", "precite", "citedash", "citepunct", "newcitecommand"}
_GROUP = re.compile(r"\s*\{([^{}]*)\}")
_OPTIONAL = re.compile(r"\s*(?:\[[^\]]*\]|\([^)]*\))")


def _text(path):
    return Path(path).read_bytes().decode("utf-8", errors="replace")


def _uncommented(text):
    return "\n".join(_COMMENT.sub(r"\1", line) for line in text.splitlines())


def _keys(group):
    return [key.strip() for key in group.split(",") if key.strip()]


def plain_name(name):
    """Is a bibliography resource a plain file name: no folder, no "..", no URL, no drive."""
    return bool(name) and not (set(name) & set('/\\:~*?[]{}') or name.startswith(".") or ".." in name
                               or any(ord(char) < 32 for char in name))


def _checked(names):
    """The resource names without ".bib"; ExportFailed naming every one that is not a plain file name."""
    refused = [name for name in names if not plain_name(name)]
    if refused:
        raise ExportFailed("resource_name",
                           "The paper names a bibliography that is not a plain file name: " + ", ".join(refused)
                           + ". Only a name such as cdl or cdl.bib is used (no folder, \"..\" or web address).", refused)
    return list(dict.fromkeys(name[:-4] if name.lower().endswith(".bib") else name for name in names))


def _inside(path, folder):
    path = Path(path).resolve()
    return path == folder or folder in path.parents


def _sources(main, folder):
    """[(file, its text without comments)] of the main file and what it \\input, \\include or
    \\subfile, as far as those are files inside ``folder``."""
    found, queue, seen = [], [Path(main)], set()
    while queue:
        file = queue.pop(0)
        if file.resolve() in seen or not file.is_file() or not _inside(file, folder):
            continue
        seen.add(file.resolve())
        text = _uncommented(_text(file))
        found.append((file, text))
        for name in _INCLUDED.findall(text):
            name = name.strip()
            for base in dict.fromkeys((Path(main).parent, file.parent)):
                candidates = [base / name] if name.lower().endswith(".tex") else [base / (name + ".tex"), base / name]
                queue += [candidate for candidate in candidates if candidate.is_file()]
    return found


def _cites(text):
    """(keys, is \\nocite{*} there) of every citation command in ``text``, natbib's and biblatex's."""
    keys, everything = [], False
    for match in _CITE.finditer(text):
        name, at = match.group(1), match.end()
        if name in _NOT_CITES or text[at:at + 1].isalpha() or text[at:at + 1] == "@":
            continue
        several = name.lower().endswith("cites")       # biblatex: \cites[..]{a}[..]{b}
        while True:
            while (optional := _OPTIONAL.match(text, at)):
                at = optional.end()
            group = _GROUP.match(text, at)
            if not group:
                break
            at = group.end()
            for key in _keys(group.group(1)):
                if key == "*":
                    everything = everything or name == "nocite"
                elif "#" not in key:           # \cite{#1} inside a macro definition names no entry
                    keys.append(key)
            if not several:
                break
    return keys, everything


def _from_source(main, folder):
    """The citations, bibliography resources, style and backend, as the .tex files state them."""
    keys, everything, names, style, biblatex = [], False, [], None, None
    files = _sources(main, folder)
    for _, text in files:
        found, starred = _cites(text)
        keys += found
        everything = everything or starred
        for group in re.findall(r"\\bibliography\s*\{([^{}]*)\}", text):
            names += _keys(group)
        names += [name.strip() for name in re.findall(r"\\addbibresource\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}", text)]
        styles = re.findall(r"\\bibliographystyle\s*\{([^{}]*)\}", text)
        style = styles[-1].strip() if styles else style
        for options in re.findall(r"\\(?:usepackage|RequirePackage)\s*(?:\[([^\]]*)\])?\s*\{[^{}]*\bbiblatex\b[^{}]*\}", text):
            chosen = re.search(r"backend\s*=\s*(\w+)", options or "")
            biblatex = "bibtex" if chosen and chosen.group(1).lower().startswith("bibtex") else "biber"
    backend = biblatex or ("bibtex" if style else None)
    return Cited(keys=list(dict.fromkeys(keys)), all_entries=everything, sources=[file for file, _ in files],
                 backend=backend, style=None if biblatex else style, bibdata=_checked(names), how="source",
                 main=Path(main), folder=folder)


def _from_aux(aux):
    """The same from a .aux file (and the .aux files of \\include that it names)."""
    keys, everything, names, style, files, biblatex = [], False, [], None, [], False
    queue, seen = [Path(aux)], set()
    while queue:
        file = queue.pop(0)
        if file.resolve() in seen or not file.is_file():
            continue
        seen.add(file.resolve())
        files.append(file)
        text = _text(file)
        biblatex = biblatex or "\\abx@aux@" in text
        for group in re.findall(r"\\citation\{([^{}]*)\}", text):
            for key in _keys(group):
                if key == "*":
                    everything = True
                elif key != "biblatex-control":
                    keys.append(key)
        for group in re.findall(r"\\bibdata\{([^{}]*)\}", text):
            names += _keys(group)
        styles = [style.strip() for style in re.findall(r"\\bibstyle\{([^{}]*)\}", text)]
        _checked(styles)                          # BibTeX opens <style>.bst: a plain name too
        style = styles[-1] if styles else style
        nested = [name.strip() for name in re.findall(r"\\@input\{([^{}]*)\}", text)]
        outside = [name for name in nested if os.path.isabs(name) or ".." in Path(name).parts
                   or set(name) & set(":~\\") or not name.endswith(".aux")]
        if outside:                               # BibTeX would read these .aux files too
            raise ExportFailed("resource_name", "The paper's .aux names another .aux file outside the paper's folder: "
                               + ", ".join(outside) + ".", outside)
        queue += [Path(aux).parent / name for name in nested]
    names = [name for name in _checked(names) if not name.endswith("-blx")]   # checked first, biblatex's own file then left out
    backend = "bibtex" if style else None
    return Cited(keys=list(dict.fromkeys(keys)), all_entries=everything, sources=files, backend=backend, style=style,
                 bibdata=names, how="aux", folder=Path(aux).parent), biblatex


def _from_bcf(bcf):
    """The same from biblatex's control file (.bcf), which is what biber reads."""
    text = _text(bcf)
    keys = [html.unescape(key).strip() for key in re.findall(r"<bcf:citekey\b[^>]*>([^<]*)</bcf:citekey>", text)]
    names, refused = [], []
    for attributes, name in re.findall(r"<bcf:datasource\b([^>]*)>([^<]*)</bcf:datasource>", text):
        name = html.unescape(name).strip()
        kind, glob = (re.search(rf"\b{word}\s*=\s*[\"']([^\"']*)[\"']", attributes) for word in ("type", "glob"))
        if (kind and kind.group(1) != "file") or (glob and glob.group(1).lower() not in ("false", "0")):
            refused.append(name)                  # a remote source, or a pattern that biber would expand
        names.append(name)
    if refused:
        raise ExportFailed("resource_name", "The paper names a bibliography that is not one local file: "
                           + ", ".join(refused) + ".", refused)
    return Cited(keys=list(dict.fromkeys(key for key in keys if key and key != "*")), all_entries="*" in keys,
                 sources=[Path(bcf)], backend="biber", bibdata=_checked(names), how="bcf", folder=Path(bcf).parent)


def _compiled_citations(folder, stem):
    """What a compile wrote: the .bcf when biblatex made one, else the .aux."""
    aux, bcf = folder / (stem + ".aux"), folder / (stem + ".bcf")
    found, biblatex = _from_aux(aux) if aux.is_file() else (None, False)
    if bcf.is_file():
        return _from_bcf(bcf)
    if found is None:
        raise ExportFailed("engine", f"LaTeX wrote no {aux.name}.")
    if biblatex and not found.backend:        # biblatex without a .bcf beside it: nothing says which entries
        found.notes.append(f"{aux.name} was written by biblatex and has no {bcf.name} beside it")
    return found


def main_file(paper, main=None):
    """The paper's main .tex file. ``paper`` is that file or a folder: there it is ``main``,
    else the one .tex file at the top of the folder that has a \\documentclass."""
    paper = Path(paper).expanduser()
    if paper.is_file():
        return paper.resolve()
    if not paper.is_dir():
        raise ExportFailed("no_main", f"{paper} is not a file or a folder.")
    if main:
        chosen = Path(main).expanduser()
        chosen = chosen if chosen.is_absolute() else paper / chosen
        if not chosen.is_file() or not _inside(chosen, paper.resolve()):
            raise ExportFailed("no_main", f"{main} is not a file in {paper}.")
        return chosen.resolve()
    found = [file for file in sorted(paper.glob("*.tex"))
             if file.is_file() and re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{(?!subfiles\})", _uncommented(_text(file)))]
    if not found:
        raise ExportFailed("no_main", f"No .tex file with a \\documentclass at the top of {paper}. Name the paper's main file.")
    if len(found) > 1:
        raise ExportFailed("several_main", f"{paper} holds several files with a \\documentclass: "
                           + ", ".join(file.name for file in found) + ". Name the main one (--main FILE).",
                           [file.name for file in found])
    return found[0].resolve()


def engine_for(main, engine=None):
    """The LaTeX program: ``engine`` when given (one of ENGINES; anything else is refused
    before any program runs), else what the source asks for (a `% !TEX program = ...` line;
    fontspec, unicode-math or polyglossia mean xelatex), else pdflatex.

    LuaLaTeX is never chosen from the source: Lua code in a document can read and write
    files, which -no-shell-escape does not stop. A source that asks for it (the program line,
    luacode, \\directlua) is ExportFailed("engine_choice") until ``engine`` says "lualatex"."""
    if engine:
        if engine not in ENGINES:
            raise ExportFailed("engine", f"{engine} is not one of the LaTeX programs used here: " + ", ".join(ENGINES) + ".")
        return engine
    text = _text(main)
    asked = _MAGIC.search(text)
    plain = _uncommented(text)
    lua = re.search(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{[^{}]*\bluacode\b[^{}]*\}|\\directlua\b", plain)
    if lua or (asked and asked.group(1).lower() == "lualatex"):
        raise ExportFailed("engine_choice", f"{Path(main).name} asks for lualatex, which is not run unless it is named: "
                           "Lua code in a document can read and write files. To compile it with LuaLaTeX, "
                           "pass --engine lualatex.", ["lualatex"])
    if asked and asked.group(1).lower() in ENGINES:
        return asked.group(1).lower()
    text = plain
    if re.search(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{[^{}]*\b(?:fontspec|unicode-math|polyglossia)\b[^{}]*\}", text):
        return "xelatex"
    return "pdflatex"


# --- the build folder ---------------------------------------------------------------------

class _Budget:
    """How much may still be copied; ExportFailed("too_large") before the copy that passes it."""

    def __init__(self):
        self.files, self.bytes, self.other = 0, 0, 0

    def take(self, size, path):
        self.files, self.bytes = self.files + 1, self.bytes + size
        if self.files > MAX_FILES or self.bytes > MAX_BYTES:
            raise ExportFailed("too_large", f"The paper's folder (with the inputs) holds more than is copied for a compile "
                               f"({MAX_FILES} files, {MAX_BYTES // 1_000_000} MB); reached at {path}. Give a folder "
                               "that holds only the paper.", [str(path)])


def _plan(source, target, root, plan, skipped, budget):
    """List, without copying anything, the (file, copy) pairs for the folder ``source``.

    Only regular files of the kinds in COPIED, outside hidden folders. A symbolic link to a
    regular file inside ``root`` (the folder being copied) is read through; any other link
    (out of the folder, to a folder, dangling) and anything that is not a regular file (a
    FIFO, a device, a socket) is left out and listed in ``skipped``."""
    for item in sorted(os.scandir(source), key=lambda entry: entry.name):
        here, name = Path(item.path), item.name
        if name.startswith("."):
            continue
        info = item.stat(follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            real = here.resolve()
            try:
                info = real.stat()
            except OSError:
                skipped.append((here, "the link points nowhere"))
                continue
            if not _inside(real, root) or not stat.S_ISREG(info.st_mode):
                skipped.append((here, "the link points outside the folder it is in" if not _inside(real, root)
                                else "the link is not to a file"))
                continue
            here = real
        elif stat.S_ISDIR(info.st_mode):
            if name not in _SKIPPED_FOLDERS:
                _plan(here, target / name, root, plan, skipped, budget)
            continue
        elif not stat.S_ISREG(info.st_mode):
            skipped.append((here, "it is not a regular file"))
            continue
        if not name.lower().endswith(COPIED):
            budget.other += not name.lower().endswith(_LEFTOVERS)
            continue
        budget.take(info.st_size, here)
        plan.append((here, target / name))


def _copy_planned(plan):
    for source, target in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(source, "rb") as read, open(target, "xb") as write:      # a new file: never onto, or through, anything
            if not stat.S_ISREG(os.fstat(read.fileno()).st_mode):
                raise ExportFailed("engine", f"{source} stopped being a regular file while it was copied.")
            shutil.copyfileobj(read, write)


def _environment(extra, home):
    """The whole environment of every program run here: PATH and the locale from the user's,
    an empty HOME of the build's own, the three search paths (the build folder, the supplied
    inputs, TeX's own trees), and reading and writing only below the folder a program runs in
    (openin_any=p, openout_any=p). Nothing else of the user's environment reaches a program:
    no TEXMFCNF, TEXMFHOME, BIBER_*, PERL5LIB or the like."""
    env = {name: os.environ[name] for name in _KEPT_VARIABLES if os.environ.get(name)}
    searched = os.pathsep.join([".", *(f"{folder}//" for folder in extra), ""])
    env.update(HOME=str(home), TEXINPUTS=searched, BSTINPUTS=searched, BIBINPUTS=searched,
               openout_any="p", openin_any="p", max_print_line="1000")
    return env


@dataclass
class _Build:
    folder: Path        # the copy of the paper's folder, where LaTeX runs
    main: Path          # the main file's copy
    backend: Path       # an empty folder, where BibTeX or biber runs on files written here
    env: dict
    notes: list


@contextlib.contextmanager
def _built(main, inputs=()):
    """A temporary copy of the main file's folder, plus ``inputs`` (files and folders holding
    styles, classes or other things the paper needs) on the search paths. What is copied is
    counted first, so a folder that is too large fails before anything is copied. The
    temporary folder is removed afterwards without following any link in it."""
    folder = main.parent
    with tempfile.TemporaryDirectory(prefix="cdlbib-export-") as scratch:
        scratch = Path(scratch).resolve()
        build, extra, skipped, plan, budget = scratch / "paper", [], [], [], _Budget()
        _plan(folder, build, folder, plan, skipped, budget)
        for number, given in enumerate(inputs, 1):
            given = Path(given).expanduser()
            place = scratch / "inputs" / str(number)
            if given.is_dir():
                _plan(given.resolve(), place, given.resolve(), plan, skipped, budget)
            elif given.is_file():
                real = given.resolve()
                if real.name.lower().endswith(COPIED) and given.name.lower().endswith(COPIED):
                    budget.take(real.stat().st_size, real)
                    plan.append((real, place / given.name))
                else:
                    budget.other += 1
            else:
                raise ExportFailed("missing_input", f"{given} (given as an input) is not a file or a folder.", [str(given)])
            place.mkdir(parents=True, exist_ok=True)
            extra.append(place)
        if not any(target == build / main.name for _, target in plan):
            raise ExportFailed("no_main", f"{main.name} is not a file that is compiled (a .tex file inside the paper's folder).")
        _copy_planned(plan)
        for made in (scratch / "home", scratch / "backend"):
            made.mkdir()
        notes = [f"not copied, because {why}: {path}" for path, why in skipped]
        if budget.other:
            notes.append(f"{budget.other} file{'' if budget.other == 1 else 's'} of other kinds {'was' if budget.other == 1 else 'were'}"
                         " not copied (TeX sources, styles, .bib files, figures, fonts and data files are)")
        env = _environment(extra, scratch / "home")
        env["BSTINPUTS"] = env["BIBINPUTS"] = os.pathsep.join([".", str(build), *(f"{place}//" for place in extra), ""])
        latex = dict(env, BSTINPUTS=env["TEXINPUTS"], BIBINPUTS=env["TEXINPUTS"])
        yield _Build(build, build / main.name, scratch / "backend", {"latex": latex, "backend": env}, notes)


def _program(name):
    found = shutil.which(name)
    if not found:
        raise ExportFailed("no_tex", f"{name} was not found on PATH. A .bbl needs a TeX installation that has it.", [name])
    return found


def _run(command, cwd, env, kind):
    name = Path(command[0]).name
    try:
        return subprocess.run(command, cwd=cwd, env=env, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=LIMIT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ExportFailed(kind, f"{name} did not finish within {LIMIT} seconds.") from None
    except OSError as exc:
        raise ExportFailed(kind, f"{name} could not be run: {exc}") from exc


def _tail(text, lines=15):
    return "\n".join(text.strip().splitlines()[-lines:])


def _made(path):
    """The bytes of a file a program wrote in a build, when it is a regular file (not a link,
    not a FIFO) of a size that is read; else None."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_OUTPUT:
        return None
    return Path(path).read_bytes()


def _latex(build, engine):
    """One LaTeX run of the copy, which writes the .aux (and biblatex's .bcf). Raises
    ExportFailed naming a missing class or package, or with the error and the end of the log."""
    name = build.main.name
    run = _run([_program(engine), "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", ENGINES[engine],
                "./" + name if name.startswith("-") else name], build.folder, build.env["latex"], "engine")
    if run.returncode == 0:
        return
    logged = _made(build.main.with_suffix(".log"))
    text = logged.decode("utf-8", errors="replace") if logged is not None else run.stdout
    absent = list(dict.fromkeys(re.findall(r"! (?:LaTeX|Package \S+) Error: File [`']([^']+)' not found", text)))
    if absent:
        raise ExportFailed("missing_input", f"{engine} could not find: " + ", ".join(absent)
                           + ". Supply the file, or the folder that holds it, as an input (--inputs PATH).", absent)
    errors = [line for line in text.splitlines() if line.startswith("!")]
    raise ExportFailed("engine", f"{engine} stopped with an error"
                       + (f": {errors[0][1:].strip()}" if errors else "") + "\n" + _tail(text))


# --- citations ----------------------------------------------------------------------------

def cited(paper, main=None, inputs=(), engine=None):
    """What a paper cites. ``paper`` is a .aux or .bcf (used as it is), or a .tex file or a
    folder (``main`` names the main file when the folder has several).

    For a .tex file or a folder the paper is compiled once in a temporary copy and the
    citations are read from the .aux/.bcf that run wrote, which also sees citations made by
    the paper's own macros. Without TeX, or when the compile fails, the .tex sources are
    parsed instead and ``notes`` say so."""
    paper = Path(paper).expanduser()
    suffix = paper.suffix.lower()
    if paper.is_file() and suffix in (".aux", ".bcf"):
        if suffix == ".bcf":
            found = _from_bcf(paper)
        else:
            found, biblatex = _from_aux(paper)
            if biblatex and not found.backend and paper.with_suffix(".bcf").is_file():
                found = _from_bcf(paper.with_suffix(".bcf"))
        source = paper.with_suffix(".tex")
        found.main = source.resolve() if source.is_file() else None
        return found
    file = main_file(paper, main)
    stated = _from_source(file, file.parent)          # also refuses hostile resource names before any program runs
    try:
        stated.engine = engine_for(file, engine)
    except ExportFailed as exc:
        if exc.kind != "engine_choice":
            raise
        stated.notes.append(f"{exc.detail} Not compiled; {SOURCE_NOTE}")
        return stated
    if not shutil.which(stated.engine):
        stated.notes.append(f"{stated.engine} was not found on PATH; {SOURCE_NOTE}")
        return stated
    try:
        with _built(file, inputs) as build:
            _latex(build, stated.engine)
            found = _compiled_citations(build.folder, file.stem)
            found.notes += build.notes
    except ExportFailed as exc:
        if exc.kind == "resource_name":
            raise
        stated.notes.append(f"the paper could not be compiled ({exc.detail.splitlines()[0]}); {SOURCE_NOTE}")
        return stated
    found.how, found.sources, found.main, found.folder, found.engine = "compiled", stated.sources, file, file.parent, stated.engine
    return found


# --- the library's side -------------------------------------------------------------------

def _entries(ws):
    from .verification import load_entries
    try:
        return load_entries(ws.bib)
    except (OSError, ValueError) as exc:
        raise ExportFailed("library", f"{ws.bib} could not be read: {exc}") from exc


def _renames(ws):
    """{old key: new key} of the library's rename ledger ({} when there is none to read)."""
    try:
        records = json.loads(ws.key_renames.read_text(encoding="utf-8"))
        return {str(record["old_key"]): str(record["new_key"]) for record in records}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def _renamed(key, renames):
    seen = {key}
    while key in renames and renames[key] not in seen:
        key = renames[key]
        seen.add(key)
    return key if len(seen) > 1 else None


def _file_keys(path):
    try:
        return set(library._entries(Path(path).read_bytes()))
    except OSError:
        return set()


def _library_names(found, folder, ws):
    """The resource names of the paper that stand for the library: not a file in ``folder``,
    and either the library's own name (cdl) or a name TeX resolves to the library's file."""
    names, kpsewhich = [], shutil.which("kpsewhich")
    for name in found.bibdata:
        if (folder / (name + ".bib")).exists():
            continue
        if name == ws.bib.stem or (kpsewhich and any(
                path is not None and tex._same_file(path, ws.bib) for path in tex.resolve(kpsewhich, name + ".bib"))):
            names.append(name)
    return names


def _elsewhere(found, folder, ws, local_library=True):
    """The keys of the paper's bibliography files that are not the library: files in
    ``folder``, and files TeX finds for the other resource names. ``local_library`` False
    leaves out a file in ``folder`` that has the library's name (a copy of it, whose keys may
    be older than the library's)."""
    keys, kpsewhich = set(), shutil.which("kpsewhich")
    for name in found.bibdata:
        local = folder / (name + ".bib")
        if local.is_file():
            if not tex._same_file(local, ws.bib) and (local_library or name != ws.bib.stem):
                keys |= _file_keys(local)
        elif name != ws.bib.stem and kpsewhich:
            for path in tex.resolve(kpsewhich, name + ".bib")[:1]:
                keys |= _file_keys(path) if path is not None and not tex._same_file(path, ws.bib) else set()
    return keys


def missing(ws, found, entries=None, folder=None):
    """The cited keys that neither the library nor another bibliography file of the paper has."""
    entries = _entries(ws) if entries is None else entries
    folder = folder or found.folder
    other = _elsewhere(found, folder, ws, local_library=False) if folder else set()
    renames = _renames(ws)
    return [Missing(key, _renamed(key, renames)) for key in found.keys if key not in entries and key not in other]


def _frozen_text(ws, found, entries):
    """(the frozen file's text, the keys written, the inherited parents among them).

    Every entry is the library's text for it, byte for byte, in the library's order. Text
    between entries that holds an @string or @preamble is copied as it is, first."""
    wanted = set(entries) if found.all_entries else {key for key in found.keys if key in entries}
    parents, queue = set(), list(wanted)
    while queue:
        entry = entries[queue.pop()]
        for name in ("crossref", "xdata"):
            for parent in str(entry["fields"].get(name, "")).split(","):
                parent = parent.strip()
                if parent in entries and parent not in wanted:
                    wanted.add(parent)
                    parents.add(parent)
                    queue.append(parent)
    text, at, definitions = ws.bib.read_bytes().decode("utf-8-sig"), 0, []
    spans = []
    for entry in entries.values():
        start = text.index(entry["raw"], at)
        spans.append(text[at:start])
        at = start + len(entry["raw"])
    for gap in spans + [text[at:]]:
        if re.search(r"(?im)^[^%\n]*@\s*(?:string|preamble)\b", gap):
            definitions.append(gap.strip())
    written = [key for key in entries if key in wanted]
    return "\n\n".join(definitions + [entries[key]["raw"] for key in written]) + "\n", written, [k for k in written if k in parents]


def writable(ws, out, force=False):
    """Where ``out`` is written (its folder resolved, its name as given), or
    ExportFailed("output"). An export is never written through a symbolic link, onto the
    library's cdl.bib, into a .git or .bibcheck folder or the library's verification/ folder,
    or onto a folder, with or without ``force``; onto another existing file only with ``force``.
    The checks are made on the resolved folder, so a linked folder does not get round them."""
    out = Path(out).expanduser()

    def refuse(why):
        raise ExportFailed("output", f"Not written: {out} {why}.", [str(out)])

    if out.is_symlink():
        refuse(f"is a symbolic link (to {os.readlink(out)}); an export is not written through a link")
    real = out.parent.resolve() / out.name
    if real == ws.bib.resolve() or tex._same_file(real, ws.bib):
        refuse("is the library's own file")
    for part in (".git", ".bibcheck"):
        if part in real.parts:
            refuse(f"is inside a {part} folder")
    if _inside(real, (ws.root / "verification").resolve()):
        refuse("is inside the library's verification folder")
    if real.is_dir():
        refuse("is a folder")
    if not real.parent.is_dir():
        refuse("is in a folder that does not exist")
    if os.path.lexists(out) and not force:
        refuse("already exists; --force replaces it")
    return real


def _write(path, data):
    """Write the file whole: a new temporary file in the same folder (created exclusively, so
    never through a link), then moved into place, which replaces a link rather than follows it."""
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def frozen_bib(ws, cited, out, force=False):
    """Write ``out``: the cited entries of the library (all of them for \\nocite{*}), each
    exactly as the library has it, in the library's order, with the entries they inherit from.

    Cited keys that are in no bibliography of the paper are returned in ``missing`` (with the
    key the library uses now, when its rename ledger knows the old one); the file is written
    without them."""
    entries = _entries(ws)
    target = writable(ws, out, force)
    text, written, parents = _frozen_text(ws, cited, entries)
    _write(target, text.encode("utf-8"))
    return Frozen(path=target, written=written, missing=missing(ws, cited, entries), parents=parents, cited=cited,
                  notes=list(cited.notes))


# --- the .bbl -----------------------------------------------------------------------------

def _named(keys):
    return ", ".join(str(key) for key in keys)


def _checked_keys(keys):
    """ExportFailed naming every citation key that cannot be written into a control file as it is."""
    odd = [key for key in keys if not _KEY.match(key)]
    if odd:
        raise ExportFailed("citation_key", "Cited keys with characters a citation key cannot have here "
                           "(spaces, braces, commas, backslashes, %, #, ^, ~, quotes, =, &, $): " + _named(odd) + ".", odd)


def _backend_names(names):
    odd = [name for name in names if not _NAME.match(name)]
    if odd:
        raise ExportFailed("resource_name", "A style or bibliography name the paper uses is not a plain name of letters, "
                           "digits, '.', '_', '+' and '-': " + _named(odd) + ".", odd)


def _log(build, run):
    logged = _made(build.backend / (JOB + ".blg"))
    return run.stdout + (logged.decode("utf-8", errors="replace") if logged is not None else "")


def _bibtex(build, sources, style, keys, everything):
    """Run BibTeX on a .aux written here and nowhere else: one \\citation per checked key, the
    checked style name, the checked bibliography names. BibTeX reads no control file that
    LaTeX or the paper wrote (it does not honour openin_any for the names in a .aux)."""
    cites = (["*"] if everything else []) + list(keys)
    text = "\\relax\n" + "".join(f"\\citation{{{key}}}\n" for key in cites)
    text += f"\\bibdata{{{','.join(sources)}}}\n\\bibstyle{{{style}}}\n"
    _write(build.backend / (JOB + ".aux"), text.encode("utf-8"))
    run = _run([_program("bibtex"), JOB], build.backend, build.env["backend"], "backend")
    text = _log(build, run)
    absent = list(dict.fromkeys(re.findall(r"I couldn't open (?:style|database) file (\S+)", text)))
    if absent:
        raise ExportFailed("missing_input", "BibTeX could not find: " + ", ".join(absent)
                           + ". Supply the file, or the folder that holds it, as an input (--inputs PATH).", absent)
    undefined = list(dict.fromkeys(re.findall(r"I didn't find a database entry for \"([^\"]+)\"", text)))
    if run.returncode >= 2:
        raise ExportFailed("backend", "BibTeX stopped with an error:\n" + _tail(text))
    return undefined, text


# The control file biblatex writes for biber, as an allowlist: element -> (attributes, child
# elements, may it hold text). Derived on 2026-10-05 from biber 2.22's own schema of the file
# (Biber/bcf.rng), plus the two elements biblatex 3.21 was seen to write that the schema lacks
# (nolabelwidthcounts, nolabelwidthcount), checked against the files biblatex wrote here for
# eleven documents (default, authoryear, alphabetic, apa, ieee, nature, chicago and verbose
# styles; refsections, sets, templates, each \Declare... that adds a section). The map_step
# attributes are the schema's without the seven in BCF_REGEX_STEPS. own_bcf() copies these
# names and nothing else; any other element or attribute fails the export by name (dropping
# it would change the .bbl).
MAX_BCF, MAX_BCF_ELEMENTS, MAX_BCF_VALUE = 5_000_000, 100_000, 2000
BCF_SHAPE = {
    "antecedent": (("quant",), ("field",), False),
    "bibdata": (("section",), ("datasource",), False),
    "citekey": (("intorder", "members", "nocite", "order", "type"), (), True),
    "citekeycount": (("count",), (), True),
    "consequent": (("quant",), ("field",), False),
    "constant": (("name", "type"), (), True),
    "constants": ((), ("constant",), False),
    "constraint": (("datatype", "pattern", "rangemax", "rangemin", "type"), ("antecedent", "consequent", "field",
        "fieldor", "fieldxor"), False),
    "constraints": ((), ("constraint", "entrytype"), False),
    "controlfile": (("bltxversion", "version"), ("bibdata", "datafieldset", "datalist", "datamodel", "extradatespec",
        "inheritance", "labelalphanametemplate", "labelalphatemplate", "namehashtemplate", "noinits", "nolabels",
        "nolabelwidthcounts", "nonamestrings", "nosorts", "options", "optionscope", "presort", "section", "sortexclusion",
        "sortinclusion", "sortingnamekeytemplate", "sortingtemplate", "sourcemap", "transliteration",
        "uniquenametemplate"), False),
    "datafieldset": (("name",), ("member",), False),
    "datalist": (("labelalphanametemplatename", "labelprefix", "name", "namehashtemplatename", "section",
        "sortingnamekeytemplatename", "sortingtemplatename", "type", "uniquenametemplatename"), ("filter", "filteror"),
        False),
    "datamodel": ((), ("constants", "constraints", "entryfields", "entrytypes", "fields", "multiscriptfields"), False),
    "datasource": (("datatype", "encoding", "glob", "type"), (), True),
    "defaults": (("ignore", "inherit_all", "override_target"), ("type_pair",), False),
    "entryfields": ((), ("entrytype", "field"), False),
    "entrytype": (("skip_output",), (), True),
    "entrytypes": ((), ("entrytype",), False),
    "exclusion": ((), (), True),
    "extradatespec": ((), ("scope",), False),
    "field": (("datatype", "fieldtype", "format", "label", "nullok", "order", "override_target", "skip", "skip_output",
        "source", "target"), (), True),
    "fieldor": ((), ("field",), False),
    "fields": ((), ("field",), False),
    "fieldxor": ((), ("field",), False),
    "filter": (("type",), (), True),
    "filteror": ((), ("filter",), False),
    "inclusion": ((), (), True),
    "inherit": (("ignore",), ("field", "type_pair"), False),
    "inheritance": ((), ("defaults", "inherit"), False),
    "key": ((), (), True),
    "keypart": (("order",), ("part",), False),
    "labelalphanametemplate": (("name",), ("namepart",), False),
    "labelalphatemplate": (("type",), ("labelelement",), False),
    "labelelement": (("order",), ("labelpart",), False),
    "labelpart": (("final", "ifnames", "names", "namessep", "noalphaothers", "pad_char", "pad_side",
        "substring_fixed_threshold", "substring_side", "substring_width", "substring_width_max"), (), True),
    "map": (("map_foreach", "map_overwrite", "refsection"), ("map_step", "per_datasource", "per_nottype", "per_type"),
        False),
    "map_step": (("map_append", "map_appendstrict", "map_entry_clone", "map_entry_new", "map_entry_newtype",
        "map_entry_null", "map_entrykey_allnocited", "map_entrykey_cited", "map_entrykey_citedornocited",
        "map_entrykey_nocited", "map_entrykey_starnocited", "map_entrytarget", "map_field_set", "map_field_source",
        "map_field_target", "map_field_value", "map_final", "map_notfield", "map_null", "map_origentrytype",
        "map_origfield", "map_origfieldval", "map_type_source", "map_type_target"), (), False),
    "maps": (("datatype", "level", "map_overwrite"), ("map",), False),
    "member": (("datatype", "field", "fieldtype"), (), False),
    "multiscriptfields": ((), ("field",), False),
    "namehashtemplate": (("name",), ("namepart",), False),
    "namepart": (("base", "disambiguation", "hashscope", "order", "pre", "substring_compound", "substring_side",
        "substring_width", "use"), (), True),
    "noinit": (("value",), (), False),
    "noinits": ((), ("noinit",), False),
    "nolabel": (("value",), (), False),
    "nolabelwidthcount": (("value",), (), False),
    "nolabelwidthcounts": ((), ("nolabelwidthcount",), False),
    "nolabels": ((), ("nolabel",), False),
    "nolabelwidthcount": (("value",), (), False),
    "nonamestring": (("field", "value"), (), False),
    "nonamestrings": ((), ("nonamestring",), False),
    "nosort": (("field", "value"), (), False),
    "nosorts": ((), ("nosort",), False),
    "option": (("backendin", "backendout", "datatype", "type"), ("key", "value"), True),
    "options": (("component", "type"), ("option",), False),
    "optionscope": (("type",), ("option",), False),
    "part": (("inits", "order", "type", "use"), (), True),
    "per_datasource": ((), (), True),
    "per_nottype": ((), (), True),
    "per_type": ((), (), True),
    "presort": (("type",), (), True),
    "scope": ((), ("field",), False),
    "section": (("number",), ("citekey", "citekeycount"), False),
    "sort": (("final", "locale", "order", "sort_direction", "sortcase", "sortupper"), ("sortitem",), False),
    "sortexclusion": (("type",), ("exclusion",), False),
    "sortinclusion": (("type",), ("inclusion",), False),
    "sortingnamekeytemplate": (("name", "visibility"), ("keypart",), False),
    "sortingtemplate": (("locale", "name"), ("sort",), False),
    "sortitem": (("literal", "order", "pad_char", "pad_side", "pad_width", "substring_side", "substring_width"), (),
        True),
    "sourcemap": ((), ("maps",), False),
    "translit": (("from", "langids", "target", "to"), (), False),
    "transliteration": (("entrytype",), ("translit",), False),
    "type_pair": (("inherit_all", "override_target", "source", "suppress", "target"), (), False),
    "uniquenametemplate": (("name",), ("namepart",), False),
    "value": (("order", "type"), (), True),
}
# A source-map step with one of these makes biber 2.22 compile the value as a Perl regular
# expression (Biber::Utils::imatch) and, for a replacement, evaluate it as Perl code in a Safe
# compartment (Biber::Utils::ireplace); every other step value is only substituted as text. A
# map that has one is refused whoever declared it (the paper, or the style it loads).
BCF_REGEX_STEPS = ("map_match", "map_matchi", "map_matches", "map_matchesi", "map_notmatch", "map_notmatchi", "map_replace")
# Values biber matches as regular expressions and biblatex writes by default (\DeclareNosort,
# \DeclareNolabel ...): kept, unless they hold a construct that runs code.
BCF_PATTERNS = {("nosort", "value"), ("nolabel", "value"), ("noinit", "value"), ("nonamestring", "value"),
                ("nolabelwidthcount", "value"), ("constraint", "pattern")}
# The options biblatex passes to biber (the component="biber" and per-type option lists); a
# use<name> option exists for every name field of the data model.
BCF_OPTIONS = frozenset("""alphaothers debug extradatecontext gregorianstart input_encoding julian labelalpha
    labeldateparts labeldatespec labelnamespec labeltitle labeltitlespec labeltitleyear maxalphanames maxbibnames
    maxcitenames maxitems maxsortnames minalphanames minbibnames mincitenames mincrossrefs minitems minsortnames minxrefs
    nohashothers noroman nosortothers output_encoding pluralothers singletitle skipbib skipbiblist skiplab sortalphaothers
    sortcase sortingtemplatename sortlocale sortsets sortupper uniquebaretitle uniquelist uniquename uniqueprimaryauthor
    uniquetitle uniquework""".split())
_OPTION_NAME = re.compile(r"use[a-z]{1,40}\Z")
_OPTION_VALUE = re.compile(r"[A-Za-z0-9_+.:,\- ]{0,200}\Z")


def _bcf_refused(why, names=()):
    raise ExportFailed("control_file", "The control file LaTeX wrote for biber is not used: " + why
                       + " No .bbl was compiled.", names)


def _bcf_probe(data):
    """First pass over the bytes, before any tree is built: the size and the number of elements
    are bounded, and the file has no document type, no entity of its own, no processing
    instruction, and exactly one namespace declaration (bcf = biblatex's)."""
    import xml.parsers.expat
    if len(data) > MAX_BCF:
        _bcf_refused(f"it is larger than {MAX_BCF // 1_000_000} MB.")
    seen = {"elements": 0, "namespaces": []}

    def declared(*_):
        _bcf_refused("it has a document type or entity declaration.")

    def instruction(target, _):
        _bcf_refused(f"it has a processing instruction ({target}).", [target])

    def element(name, attributes):
        seen["elements"] += 1
        if seen["elements"] > MAX_BCF_ELEMENTS:
            _bcf_refused(f"it has more than {MAX_BCF_ELEMENTS} elements.")
        for attribute in attributes:
            if attribute.startswith("xmlns"):
                seen["namespaces"].append((attribute, attributes[attribute]))
            elif ":" in attribute:
                _bcf_refused(f"the attribute {attribute} of {name} has a namespace.", [attribute])
        if not name.startswith("bcf:") or name.count(":") != 1:
            _bcf_refused(f"the element {name} is not written as bcf:<name>.", [name])

    probe = xml.parsers.expat.ParserCreate()               # not namespace-aware: names are seen as they are written
    probe.StartDoctypeDeclHandler = probe.EntityDeclHandler = probe.UnparsedEntityDeclHandler = declared
    probe.ProcessingInstructionHandler = instruction
    probe.StartElementHandler = element
    try:
        probe.Parse(data, True)
    except xml.parsers.expat.ExpatError as exc:
        _bcf_refused(f"it could not be read ({exc}).")
    if seen["namespaces"] != [("xmlns:bcf", BCF)]:
        _bcf_refused("its namespaces are not the one declaration biblatex writes (xmlns:bcf).",
                     [name for name, _ in seen["namespaces"]])


def _bcf_value(element, what, value):
    """A text or attribute value that is copied: bounded, without control characters."""
    if len(value) > MAX_BCF_VALUE or any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        _bcf_refused(f"{what} of {element} is too long or holds control characters.", [element])
    return value


def own_bcf(data, sources):
    """The control file for biber, built here from the one biblatex wrote.

    The file must have exactly the shape biblatex writes (_bcf_probe; every element bcf:<name>
    in biblatex's namespace). A new tree is then made from nothing: for each element only the
    names in BCF_SHAPE are copied, with their text; anything else is ExportFailed
    ("control_file") naming it. The data sources are not copied at all: each bibdata gets
    ``sources`` (local files, no pattern). A source map with a match or a replacement is
    refused, because biber runs those as Perl regular expressions. Option names are those in
    BCF_OPTIONS; citation keys, and the members of a set, pass the key check."""
    import xml.etree.ElementTree as ET
    _bcf_probe(data)
    ET.register_namespace("bcf", BCF)
    try:
        old = ET.fromstring(data)
    except ET.ParseError as exc:
        _bcf_refused(f"it could not be read ({exc}).")
    space = "{" + BCF + "}"

    def local(element):
        if not isinstance(element.tag, str) or not element.tag.startswith(space):
            _bcf_refused(f"the element {element.tag} is not biblatex's.", [str(element.tag)])
        return element.tag[len(space):]

    def text_of(element, name, allowed):
        text = element.text or ""
        for child in element:
            if (child.tail or "").strip():
                _bcf_refused(f"{name} holds text between its elements.", [name])
        if text.strip() and not allowed:
            _bcf_refused(f"{name} holds text.", [name])
        return _bcf_value(name, "the text", text) if allowed else None

    def checked(name, element, text):
        """The checks that depend on what an element means to biber."""
        if name == "map_step":
            regex = [attribute for attribute in element.attrib if attribute in BCF_REGEX_STEPS]
            if regex:
                _bcf_refused("the paper, or the bibliography style it loads, declares a source map with a match or a "
                             f"replacement ({', '.join(regex)}), which biber runs as a Perl regular expression.", regex)
        for attribute, value in element.attrib.items():
            if (name, attribute) in BCF_PATTERNS and ("(?{" in value or "(??{" in value):
                _bcf_refused(f"the pattern of a {name} holds a construct that runs code.", [name])
        if name == "citekey":
            _checked_keys([key for key in [text.strip()] if key != "*"]
                          + [key.strip() for key in element.get("members", "").split(",") if key.strip()])
        if name in ("section", "bibdata") and not (element.get("number") or element.get("section") or "0").isdigit():
            _bcf_refused(f"a {name} has a number that is not one.", [name])
        if name == "per_datasource" and not plain_name(text.strip()):
            _bcf_refused(f"a source map names a data source that is not a plain file name: {text.strip()}.", [text.strip()])
        if name == "option" and element.find(space + "key") is not None:
            key = "".join(element.find(space + "key").itertext()).strip()
            if key not in BCF_OPTIONS and not _OPTION_NAME.match(key):
                _bcf_refused(f"the option {key} is not one biblatex passes to biber.", [key])
            for value in element.iter(space + "value"):
                if not _OPTION_VALUE.match("".join(value.itertext()).strip()):
                    _bcf_refused(f"the value of the option {key} is not a plain word or number.", [key])

    def rebuilt(element, parent=None):
        name = local(element)
        if name not in BCF_SHAPE:
            _bcf_refused(f"it has an element this version does not know: {name}.", [name])
        attributes, children, holds_text = BCF_SHAPE[name]
        unknown = [attribute for attribute in element.attrib if attribute not in attributes]
        if unknown:
            hint = [attribute for attribute in unknown if attribute in BCF_REGEX_STEPS]
            if name == "map_step" and hint:
                checked(name, element, "")
            _bcf_refused(f"{name} has an attribute this version does not know: {', '.join(unknown)}.", unknown)
        text = text_of(element, name, holds_text)
        checked(name, element, text or "")
        fresh = ET.Element(space + name) if parent is None else ET.SubElement(parent, space + name)
        for attribute in attributes:                           # in the allowlist's order; only what is listed
            if attribute in element.attrib:
                fresh.set(attribute, _bcf_value(name, "the attribute " + attribute, element.attrib[attribute]))
        if holds_text and not len(element):
            fresh.text = text
        for child in element:
            kind = local(child)
            if kind not in children:
                _bcf_refused(f"{name} holds an element it does not hold in a file biblatex writes: {kind}.", [kind])
            if kind != "datasource":                           # never copied: written below
                rebuilt(child, fresh)
        if name == "bibdata":
            for source in sources:
                made = ET.SubElement(fresh, space + "datasource", {"type": "file", "datatype": "bibtex", "glob": "false"})
                made.text = source + ".bib"
        return fresh

    if local(old) != "controlfile":
        _bcf_refused("it is not a biblatex control file.")
    new = rebuilt(old)
    if new.find(space + "bibdata") is None:
        holder = ET.SubElement(new, space + "bibdata", {"section": "0"})
        for source in sources:
            ET.SubElement(holder, space + "datasource", {"type": "file", "datatype": "bibtex", "glob": "false"}).text = source + ".bib"
    return ET.tostring(new, encoding="utf-8", xml_declaration=True)


def _biber(build, sources, generated):
    """Run biber on the rewritten control file (own_bcf), without any configuration file, reading
    and writing in the backend folder only."""
    _write(build.backend / (JOB + ".bcf"), own_bcf(generated, sources))
    run = _run([_program("biber"), "--noconf", "--input-directory", str(build.backend),
                "--output-directory", str(build.backend), JOB], build.backend, build.env["backend"], "backend")
    text = _log(build, run)
    absent = list(dict.fromkeys(re.findall(r"ERROR - Cannot find '([^']+)'", text)))
    if absent:
        raise ExportFailed("missing_input", "biber could not find: " + ", ".join(absent)
                           + ". Supply the file, or the folder that holds it, as an input (--inputs PATH).", absent)
    undefined = list(dict.fromkeys(re.findall(r"I didn't find a database entry for '([^']+)'", text)))
    if run.returncode != 0:
        raise ExportFailed("backend", "biber stopped with an error:\n" + _tail(run.stdout))
    return undefined, text


def bbl(ws, paper, out=None, inputs=(), main=None, engine=None, force=False):
    """Compile the paper's .bbl from the library and write it to ``out`` (default: beside the
    main file, with its name).

    The paper's folder and ``inputs`` are copied (by kind of file) to a temporary folder and
    LaTeX is run there once. What that run wrote is only read here, for the keys, the style
    and the bibliography names. BibTeX or biber, whichever the paper uses, then runs in a
    second, empty folder on a control file written here, with the frozen entries under each
    bibliography name of the paper that stands for the library (a .bib file the paper's
    folder holds is copied beside them and used as it is). The style is the paper's own:
    without a \\bibliographystyle or biblatex nothing is compiled."""
    paper = Path(paper).expanduser()
    if paper.is_file() and paper.suffix.lower() in (".aux", ".bcf"):
        if not paper.with_suffix(".tex").is_file():
            raise ExportFailed("no_source", f"A .bbl is compiled from the paper's .tex file; {paper.with_suffix('.tex')} "
                               "is not there. Give the .tex file or its folder.")
        paper = paper.with_suffix(".tex")
    file = main_file(paper, main)
    out = Path(out).expanduser() if out else file.with_suffix(".bbl")
    writable(ws, out, force)                          # before any program runs
    stated = _from_source(file, file.parent)          # refuses hostile resource names before any program runs
    chosen = engine_for(file, engine)
    entries = _entries(ws)
    with _built(file, inputs) as build:
        _latex(build, chosen)
        found = _compiled_citations(build.folder, file.stem)
        found.how, found.sources, found.main, found.folder, found.engine = "compiled", stated.sources, file, file.parent, chosen
        found.notes += build.notes
        if not found.backend:
            if found.bibdata or stated.bibdata:
                raise ExportFailed("no_style", f"{file.name} names a bibliography but no \\bibliographystyle (and does not "
                                   "use biblatex), so there is no style to compile a .bbl with. No style is chosen for it.")
            raise ExportFailed("no_bibliography", f"{file.name} has no \\bibliography or \\addbibresource command.")
        _checked_keys(found.keys)
        _backend_names(found.bibdata + ([found.style] if found.style else []))
        names = _library_names(found, build.folder, ws)
        local = build.folder / (ws.bib.stem + ".bib")
        if ws.bib.stem in found.bibdata and local.is_file():
            found.notes.append(f"{local.name} in the paper's folder was used as it is")
        elif not names:
            found.notes.append(f"the paper names no bibliography that is the library ({ws.bib.stem})")
        provided = (set(entries) if names else set()) | _elsewhere(found, build.folder, ws)
        renames = _renames(ws)
        absent = [Missing(key, _renamed(key, renames)) for key in found.keys if key not in provided]
        if absent:
            raise ExportFailed("undefined_keys", "Cited, but in no bibliography of the paper: " + _named(absent) + ".",
                               [item.key for item in absent])
        text = _frozen_text(ws, found, entries)[0].encode("utf-8")
        sources, keys = list(found.bibdata), list(found.keys)
        for name in sources:                           # the backend's folder holds only files written here
            own = _made(build.folder / (name + ".bib"))
            if name in names:
                _write(build.backend / (name + ".bib"), text)
            elif own is not None:
                _write(build.backend / (name + ".bib"), own)
        if found.backend == "biber":
            generated = _made(build.folder / (file.stem + ".bcf"))
            if generated is None:
                raise ExportFailed("engine", f"LaTeX wrote no usable {file.stem}.bcf.")
            undefined, log = _biber(build, sources, generated)
        else:
            control = _made(build.folder / (file.stem + "-blx.bib")) if found.style == "biblatex" else None
            if control is not None:                    # biblatex with BibTeX: its own control entry, under a name of ours
                _write(build.backend / (JOB + "-blx.bib"), control)
                sources, keys = [JOB + "-blx"] + sources, ["biblatex-control"] + keys
            undefined, log = _bibtex(build, sources, found.style, keys, found.all_entries)
        if undefined:
            raise ExportFailed("undefined_keys", "Cited, but in no bibliography of the paper: " + _named(undefined) + ".",
                               undefined)
        made = _made(build.backend / (JOB + ".bbl"))   # the fixed name, in the folder only the backend wrote in
        if made is None:
            raise ExportFailed("backend", f"{found.backend} wrote no usable .bbl:\n" + _tail(log))
        warnings = len(re.findall(r"(?m)^Warning--|^\S*WARN - ", log))
        if warnings:
            found.notes.append(f"{found.backend} gave {warnings} warning{'' if warnings == 1 else 's'}")
        target = writable(ws, out, force)
        _write(target, made)
    return Bbl(path=target, backend=found.backend, engine=chosen, style=found.style, keys=found.keys, cited=found,
               notes=found.notes)
