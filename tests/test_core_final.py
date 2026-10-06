"""The last core round: a rollback that never writes over someone else's change; model
evidence journaled before the entry is written (killed at each gap); a PDF read from the
bytes that were hashed; an export that never replaces a file it did not see; .lua copied only
when lualatex is named; `add --author` and `add --pdf`; one serializer.

Real processes (writers paused, edited around and killed), real files, PDFs typeset by
pdflatex, recorded lookups with the network refused. No mocks.
"""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import conftest
import intake_pdfs as pdfs
from cdlbib import api, export, intake, writer
from cdlbib.errors import CdlbibError, CompletionRefused, WriteConflict
from cdlbib.verification import load_entries
from cdlbib.workspace import Workspace

from intake_support import CONTACT, library as search_library, offline_client
from test_complete_cli import refused_network, terminal
from test_locking import KAHA12, RENAMED, TEXT, child, finish, line, ws  # noqa: F401

ZOLL90 = conftest.ZOLL90
needs_pdflatex = pytest.mark.skipif(not pdfs.pdflatex(), reason="pdflatex is not installed: the test PDFs cannot be typeset")


@pytest.fixture
def offline(monkeypatch):
    for name, value in refused_network().items():
        monkeypatch.setenv(name, value)


# --- 1. taking a write back ---------------------------------------------------------------------

PAUSED = """
import sys, os, signal
from cdlbib import api
from cdlbib.errors import CdlbibError
from cdlbib.workspace import Workspace
ws = Workspace({root!r})
opened = api.entry(ws, 'Zoll90').fingerprint
signal.signal(signal.SIGUSR1, lambda *received: None)
def audit(event, args):
    if event == 'os.rename' and str(args[1]) == {ledger!r}:
        print('paused', flush=True)          # the bibliography is replaced; the ledger is next
        signal.pause()
sys.addaudithook(audit)
try:
    api.save_edit(ws, 'Zoll90', {raw!r}, opened)
    print('SAVED', flush=True)
except CdlbibError as exc:
    print(type(exc).__name__, getattr(exc, 'files', None), '|', exc, flush=True)
"""


def paused_rename(ws):
    process = child(PAUSED.format(root=str(ws.root), ledger=str(ws.key_renames), raw=RENAMED), ws.root)
    assert line(process) == "paused"
    return process


def resumed(process):
    os.kill(process.pid, signal.SIGUSR1)
    out, err = process.communicate(timeout=30)
    assert process.returncode == 0, err
    return out.strip()


def test_a_rollback_leaves_a_file_someone_else_changed_and_says_so(ws):
    """The writer (a real process) has replaced cdl.bib and is about to write the ledger. This
    process then saves cdl.bib itself and makes the ledger something the writer did not
    expect, so the writer has to take its write back: it must not put the old cdl.bib over
    this process's save."""
    before = ws.bib.read_bytes()
    process = paused_rename(ws)
    try:
        half = ws.bib.read_bytes()
        assert half == before.replace(ZOLL90.encode(), RENAMED.encode())
        mine = half + b"% saved by someone else while the write was under way\n"
        ws.bib.write_bytes(mine)
        ws.key_renames.parent.mkdir(exist_ok=True)
        ws.key_renames.write_text("[]\n", encoding="utf-8")            # not what the writer planned from
        said = resumed(process)
    finally:
        finish(process)
    assert said.startswith(f"WriteConflict [{str(ws.bib)!r}] | The write could not be finished and was being taken back")
    assert "was changed by something else in the meantime; it was left as it is now" in said
    assert ws.bib.read_bytes() == mine and ws.key_renames.read_text(encoding="utf-8") == "[]\n"
    copy = writer.interrupted(ws)                                     # the record of the write stays
    assert copy and Path(copy).read_bytes() == before and copy in said
    with pytest.raises(CdlbibError, match="was interrupted, and the library was changed since"):
        api.save_edit(ws, "Kaha12", KAHA12.replace("2012", "2013"), load_entries(ws.bib)["Kaha12"]["fingerprint"])
    assert ws.bib.read_bytes() == mine
    assert issubclass(WriteConflict, CdlbibError) and WriteConflict("x", files=[ws.bib]).files == [str(ws.bib)]


def test_a_rollback_puts_back_what_nobody_else_touched(ws):
    """The control: only the ledger is in the way. The bibliography is put back as it was."""
    before = ws.bib.read_bytes()
    process = paused_rename(ws)
    try:
        ws.key_renames.parent.mkdir(exist_ok=True)
        ws.key_renames.write_text("[]\n", encoding="utf-8")
        said = resumed(process)
    finally:
        finish(process)
    assert said.startswith("CdlbibError None |") and "changed while applying; nothing was written" in said
    assert ws.bib.read_bytes() == before and writer.interrupted(ws) is None
    assert api.save_edit(ws, "Kaha12", KAHA12.replace("2012", "2013"),
                         load_entries(ws.bib)["Kaha12"]["fingerprint"]).written == ["Kaha12"]


# --- 2. evidence is on disk before the entry is --------------------------------------------------

DRAFT = """
import os, signal, sys
from pathlib import Path
from cdlbib import api, intake
from cdlbib.workspace import Workspace
ws = Workspace({root!r})
draft = api.draft_manual(ws, {{"title": "A typed paper on recall", "author": "Example, Ada", "year": "2001", "journal": "Memory"}})
draft.evidence = {{"pdf_sha256": "ab" * 32, "reviewer": "model: test selection", "fields": {{"year": {{"page": 1, "quote": "Published 2001"}}}}}}
pdf = intake.PdfIntake(path=Path("paper.pdf"), sha256="ab" * 32)
def audit(event, args):
    if {condition}:
        print('gap', flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
sys.addaudithook(audit)
api.accept_draft(ws, draft, pdf)
print('finished', flush=True)
"""
EVIDENCE = {"pdf_sha256": "ab" * 32, "reviewer": "model: test selection",
            "fields": {"year": {"page": 1, "quote": "Published 2001"}}}
GAPS = {
    "before the entry is written": "event == 'os.rename' and str(args[1]) == str(ws.bib)",
    "after the entry, before the evidence is stored": "event == 'sqlite3.connect' and str(args[0]).endswith('verification.sqlite3')",
    "after the evidence is stored, before the record is dropped": "event == 'os.remove' and str(args[0]) == 'Exam01.json'",
}


@pytest.mark.parametrize("gap", list(GAPS))
def test_a_draft_accepted_by_a_process_killed_at_any_point_keeps_or_drops_its_evidence_rightly(ws, gap):
    before = ws.bib.read_bytes()
    process = child(DRAFT.format(root=str(ws.root), condition=GAPS[gap]), ws.root)
    try:
        assert line(process) == "gap"
        process.wait(timeout=30)
    finally:
        finish(process)
    assert process.returncode == -signal.SIGKILL
    record = ws.work / "pending-evidence" / "Exam01.json"
    assert record.is_file()                                           # at every gap the evidence is on disk
    kept = json.loads(record.read_text(encoding="utf-8"))
    assert kept["key"] == "Exam01" and kept["evidence"] == EVIDENCE
    lines = []
    if gap == "before the entry is written":
        assert ws.bib.read_bytes() == before
        api.prepare(ws, progress=lines.append)
        assert "model evidence for Exam01: dropped: the entry it was read for was not written" in lines
        assert "Exam01" not in load_entries(ws.bib) and ws.bib.read_bytes() == before
    else:
        written = load_entries(ws.bib)["Exam01"]
        assert kept["fingerprint"] == written["fingerprint"]          # worked out before the entry was written
        stored_already = gap.startswith("after the evidence is stored")
        assert ("external_evidence" in api.entry(ws, "Exam01").result) is stored_already
        assert api.pending_evidence(ws) == [api.PendingEvidence("Exam01", written["fingerprint"], False)]
        api.prepare(ws, progress=lines.append)
        assert "model evidence for Exam01: stored" in lines
        assert api.entry(ws, "Exam01").result["external_evidence"] == EVIDENCE
        assert api.entry(ws, "Exam01").status == "needs_review"
    assert not record.exists() and api.pending_evidence(ws) == []


def test_when_the_evidence_cannot_be_kept_the_entry_is_not_written(ws):
    draft = api.draft_manual(ws, {"title": "A typed paper on recall", "author": "Example, Ada", "year": "2001",
                                  "journal": "Memory"})
    draft.evidence = dict(EVIDENCE)
    pdf = intake.PdfIntake(path=Path("paper.pdf"), sha256="ab" * 32)
    ws.work.mkdir()
    (ws.work / "pending-evidence").write_text("a file where the folder would be\n", encoding="utf-8")
    before = ws.bib.read_bytes()
    with pytest.raises(CompletionRefused, match="could not be kept on disk .* was not written either"):
        api.accept_draft(ws, draft, pdf)
    assert ws.bib.read_bytes() == before and "Exam01" not in load_entries(ws.bib)
    (ws.work / "pending-evidence").unlink()
    done = api.accept_draft(ws, draft, pdf)
    assert done.written and done.evidence_stored is True and api.pending_evidence(ws) == []


# --- 3. a PDF is read from the bytes that were hashed ------------------------------------------------

@pytest.fixture(scope="module")
def two_pdfs(tmp_path_factory):
    folder = tmp_path_factory.mktemp("pdfs")
    return pdfs.build("doi", folder), pdfs.build("unknown", folder)


@needs_pdflatex
def test_a_pdf_replaced_while_it_is_read_never_gives_text_of_one_file_under_the_hash_of_another(two_pdfs, tmp_path,
                                                                                               monkeypatch):
    """A second real process keeps replacing the path with one PDF, then the other. Every
    reading's SHA-256 is one of the two files', and the title read is that file's title."""
    import tempfile
    # The copies read_pdf makes go to a temporary folder of this test's own: the shared one may hold the
    # copy another process is reading at this moment (seen on 2026-10-06), which is no finding about this code.
    own = tmp_path / "tmp"
    own.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(own))
    first, second = two_pdfs
    known = {hashlib.sha256(first.read_bytes()).hexdigest(): pdfs.ZOLLER_TITLE.replace("'", "’"),
             hashlib.sha256(second.read_bytes()).hexdigest(): pdfs.UNKNOWN_TITLE}
    target, stop = tmp_path / "paper.pdf", tmp_path / "stop"
    target.write_bytes(first.read_bytes())
    swapper = subprocess.Popen([sys.executable, "-c", """
import os, shutil, sys, time
target, first, second, stop = sys.argv[1:5]
turn = 0
while not os.path.exists(stop):
    turn += 1
    shutil.copyfile(second if turn % 2 else first, target + '.next')
    os.replace(target + '.next', target)
    time.sleep(0.003)
print(turn)
""", str(target), str(first), str(second), str(stop)], stdout=subprocess.PIPE, text=True)
    seen = set()
    try:
        for _ in range(12):
            read = intake.read_pdf(target, ocr=False)
            assert read.problem is None and read.sha256 in known, read.detail
            assert read.title_guess == known[read.sha256]             # the text is of the bytes that were hashed
            seen.add(read.sha256)
    finally:
        stop.write_text("stop", encoding="utf-8")
        turns = int(swapper.communicate(timeout=30)[0])
    assert turns > 20 and seen
    assert Path(tempfile.gettempdir()) == own
    assert not list(own.glob("cdlbib-pdf-copy-*/paper.pdf"))      # the copies are removed
    assert not list(own.glob("cdlbib-pdf-copy-*"))                # and so are their folders


@needs_pdflatex
def test_a_preview_is_refused_for_a_file_that_changed_since_it_was_read(two_pdfs, tmp_path):
    first, second = two_pdfs
    target = tmp_path / "paper.pdf"
    target.write_bytes(first.read_bytes())
    read = api.read_pdf(target)
    assert read.sha256 == hashlib.sha256(first.read_bytes()).hexdigest()
    try:
        image = api.render_first_page(target, width=200)
    except CdlbibError as exc:
        if "pypdfium2" not in str(exc):
            raise
        pytest.skip(f"no page preview here: {exc}")
    assert image.startswith(b"\x89PNG")
    target.write_bytes(second.read_bytes())                           # the same path, other bytes
    with pytest.raises(CdlbibError, match="has changed since it was read"):
        api.render_first_page(target, width=200)
    again = api.read_pdf(target)                                      # reading it again makes it the file in hand
    assert again.sha256 == hashlib.sha256(second.read_bytes()).hexdigest() and again.title_guess == pdfs.UNKNOWN_TITLE
    assert api.render_first_page(target, width=200).startswith(b"\x89PNG")
    # evidence of the first reading is not accepted with the second
    proposal = intake.ModelProposal(manual=True, evidence={"pdf_sha256": read.sha256, "fields": {}, "reviewer": "x"})
    with pytest.raises(CdlbibError, match="different PDF"):
        intake.evidence_for(proposal, again)


# --- 4. an export never replaces a file it did not see -------------------------------------------------

def test_without_force_a_file_that_appears_is_never_written_over(tmp_path):
    target = tmp_path / "out.bib"
    export._write(target, b"first\n", replace=False)
    assert target.read_bytes() == b"first\n"
    with pytest.raises(export.ExportFailed, match="already exists; --force replaces it") as failed:
        export._write(target, b"second\n", replace=False)             # as if it appeared after the check
    assert failed.value.kind == "output" and target.read_bytes() == b"first\n"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["out.bib"]      # no temporary file is left
    link = tmp_path / "link.bib"
    link.symlink_to(tmp_path / "elsewhere.bib")                       # a dangling link is a name that is taken
    with pytest.raises(export.ExportFailed):
        export._write(link, b"x", replace=False)
    assert not (tmp_path / "elsewhere.bib").exists()
    export._write(target, b"third\n")                                 # with force: replaced
    assert target.read_bytes() == b"third\n"


def test_frozen_bib_uses_the_no_replace_write_unless_forced(tmp_path):
    lib = Workspace(tmp_path / "lib")
    lib.root.mkdir()
    lib.bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text("\\documentclass{article}\\begin{document}\\cite{Zoll90}\\bibliography{cdl}\\end{document}\n",
                                    encoding="utf-8")
    out = paper / "refs.bib"
    made = api.export_bib(lib, paper / "main.tex", out=out)
    assert made.written == ["Zoll90"] and ZOLL90 in out.read_text(encoding="utf-8")
    out.write_text("mine\n", encoding="utf-8")
    with pytest.raises(export.ExportFailed, match="already exists"):
        api.export_bib(lib, paper / "main.tex", out=out)
    assert out.read_text(encoding="utf-8") == "mine\n"
    api.export_bib(lib, paper / "main.tex", out=out, force=True)
    assert ZOLL90 in out.read_text(encoding="utf-8")


# --- 5. .lua files -------------------------------------------------------------------------------------

def test_lua_files_are_copied_only_when_lualatex_is_named(tmp_path):
    paper, styles = tmp_path / "paper", tmp_path / "styles"
    (paper / "sub").mkdir(parents=True)
    styles.mkdir()
    main = paper / "main.tex"
    main.write_text("\\documentclass{article}\\begin{document}x\\end{document}\n", encoding="utf-8")
    (paper / "helpers.lua").write_text("return 1\n", encoding="utf-8")
    (paper / "sub" / "more.lua").write_text("return 2\n", encoding="utf-8")
    (paper / "notes.sh").write_text("echo no\n", encoding="utf-8")
    (styles / "style.lua").write_text("return 3\n", encoding="utf-8")

    def copied(**options):
        with export._built(main, inputs=[styles], **options) as build:
            return sorted(str(item.relative_to(build.folder.parent)) for item in build.folder.parent.rglob("*") if item.is_file())

    assert copied() == ["paper/main.tex"]
    assert copied(lua=True) == ["inputs/1/style.lua", "paper/helpers.lua", "paper/main.tex", "paper/sub/more.lua"]
    import inspect
    assert inspect.getsource(export.cited).count('lua=engine == "lualatex"') == 1
    assert inspect.getsource(export.bbl).count('lua=engine == "lualatex"') == 1


# --- 6. add --author, add --pdf --------------------------------------------------------------------------

def test_add_by_author_alone_offers_the_leads_through_the_candidate_choice(tmp_path):
    saved = offline_client(tmp_path / "cache", "searches.json.gz")
    database = saved.cache.path
    try:
        expected = intake.find_candidates(search_library(tmp_path / "expected"), client=saved, per_source=5,
                                          authors=["Manning", "Kahana"])
    finally:
        saved.cache.close()
    lib = search_library(tmp_path / "lib")
    argv = ["--library", str(lib.root), "add", "--author", "Manning", "--author", "Kahana", "--per-source", "5",
            "--database", str(database), "--mailto", CONTACT]
    status, out = terminal(tmp_path, "from cdlbib.cli import main; main()", "0\n", argv=argv)
    assert status == 0, out
    assert len(expected) > 2 and f"{len(expected)} records by Manning, Kahana; choose one" in out
    for number, lead in enumerate(expected, 1):
        assert f"[{number}] {lead['authors']} {lead['year']}: {lead['title']}" in out, lead
    assert "[0] none of these" in out and lib.bib.read_text(encoding="utf-8") == ""
    # without a terminal: listed as a proposal with nothing to write, and nothing is changed
    run = subprocess.run([sys.executable, "-c", "from cdlbib.cli import main; main()", *argv], cwd=tmp_path, input="",
                         capture_output=True, text=True, env=dict(os.environ, **refused_network()))
    assert run.returncode == 0 and "nothing was changed" in run.stdout and "choose one" in run.stdout, run.stdout + run.stderr


def test_add_by_an_author_nobody_has_says_so(tmp_path):
    saved = offline_client(tmp_path / "cache", "searches.json.gz")
    database = saved.cache.path
    saved.cache.close()
    lib = search_library(tmp_path / "lib")
    run = subprocess.run([sys.executable, "-c", "from cdlbib.cli import main; main()", "--library", str(lib.root), "add",
                          "--author", "Zzyzxqvson", "--database", str(database), "--mailto", CONTACT], cwd=tmp_path,
                         input="", capture_output=True, text=True, env=dict(os.environ, **refused_network()))
    assert run.returncode == 1 and "No record by Zzyzxqvson was found." in run.stdout, run.stdout + run.stderr
    assert "Traceback" not in run.stderr and lib.bib.read_text(encoding="utf-8") == ""


@needs_pdflatex
def test_add_pdf_says_what_was_read_and_goes_on_to_accept(two_pdfs, tmp_path):
    with_doi, unknown = two_pdfs
    saved = offline_client(tmp_path / "cache", "pdf_lookups.json.gz")
    database = saved.cache.path
    saved.cache.close()
    lib = search_library(tmp_path / "lib")
    argv = ["--library", str(lib.root), "add", "--database", str(database), "--mailto", CONTACT, "--pdf"]
    status, out = terminal(tmp_path, "from cdlbib.cli import main; main()", "a\n", argv=[*argv, str(with_doi)])
    assert status == 0, out
    digest = hashlib.sha256(with_doi.read_bytes()).hexdigest()
    assert f"PDF: {with_doi} (SHA-256 {digest})" in out
    assert f'  doi {pdfs.ZOLLER_DOI} (page 1: "J. Res. Sci. Teach. 27(10), 1053' in out
    assert "  title read: Students" in out and "(largest text on page 1)" in out
    assert "Your choice [a/e/s/A/q]" in out and "Added: Zoll90" in out
    assert lib.bib.read_text(encoding="utf-8").strip() == ZOLL90
    # a PDF no source knows: said, with where model reading and manual entry are offered
    status, out = terminal(tmp_path, "from cdlbib.cli import main; main()", "", argv=[*argv, str(unknown)])
    assert status == 1, out
    assert f"  title read: {pdfs.UNKNOWN_TITLE}" in out and "No source record was found for this PDF." in out
    assert "are offered by `cdlbib tui` and `cdlbib web`." in out and "Your choice" not in out
    assert lib.bib.read_text(encoding="utf-8").strip() == ZOLL90
    # and --pdf stands alone
    status, out = terminal(tmp_path, "from cdlbib.cli import main; main()", "", argv=[*argv, str(with_doi), "10.1/x"])
    import re
    shown = " ".join(re.sub(r"\x1b\[[0-9;]*m|[│╭╮╰╯─]", " ", out).split())
    assert status != 0 and "pdf is given by itself: one PDF, and no other query" in shown, shown   # (rich styles the dashes apart)


# --- 7. one serializer ---------------------------------------------------------------------------------

def test_intake_to_data_is_api_as_data(tmp_path):
    held = intake.PdfIntake(path=Path("x.pdf"), identifiers=[intake.Identifier("doi", "10.1/x", 1, "doi:10.1/x")])
    result = intake.PdfResult(intake=held, message="nothing")
    for value in (held, result, intake.Accepted(applied=None, key="K"), intake.Candidates(), {"a": (1, Path("p"))}):
        assert intake.to_data(value) == api.as_data(value) == api.intake_data(value)
        json.dumps(api.as_data(value))
    assert api.as_data(held)["identifiers"] == [{"kind": "doi", "value": "10.1/x", "page": 1, "quote": "doi:10.1/x"}]
    assert api.as_data(result)["matched"] is False and api.as_data(intake.Accepted(applied=None, key="K"))["written"] is True
    assert api.as_data(intake.Candidates()) == {"items": [], "errors": []}
    import inspect
    assert "as_data" in inspect.getsource(intake.to_data) and len(inspect.getsource(intake.to_data).splitlines()) < 8
    assert not hasattr(intake, "_route_ready") and not hasattr(intake, "_regular_file")
    from cdlbib import cli
    assert not hasattr(cli, "install_wanted") and not hasattr(cli, "_tex_state")
