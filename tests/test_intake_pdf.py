"""PDF intake: ``read_pdf``, ``render_first_page`` and ``propose_from_pdf``.

The PDFs are typeset here by real pdflatex from tests/intake_pdfs.py (encrypted with
pypdf's writer, turned into a scan by Ghostscript); nothing is a stand-in. The lookups a
PDF leads to are the real responses of tests/fixtures/intake/pdf_lookups.json.gz, fetched
once on 2026-10-05 by tests/fixtures/intake/record.py and replayed through the real client.
"""
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import zlib

import pytest

from cdlbib import api, deps, intake
from cdlbib.errors import CdlbibError
from cdlbib.verification import ACCEPTED

from conftest import ZOLL90
import intake_pdfs as pdfs
from intake_support import library, offline_client

pytestmark = pytest.mark.skipif(not pdfs.pdflatex(), reason="pdflatex is not installed: the test PDFs cannot be typeset")


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """Every PDF of intake_pdfs.SOURCES, typeset once for this module."""
    folder = tmp_path_factory.mktemp("pdfs")
    return {name: pdfs.build(name, folder) for name in pdfs.SOURCES}


@pytest.fixture
def client(tmp_path):
    client = offline_client(tmp_path / "cache", "pdf_lookups.json.gz")
    yield client
    client.cache.close()


# --- reading ------------------------------------------------------------------------------------

def test_doi_on_page_one(made):
    read = intake.read_pdf(made["doi"])
    assert read.problem is None and not read.ocr
    assert read.sha256 == hashlib.sha256(made["doi"].read_bytes()).hexdigest()
    assert [p["page"] for p in read.pages] == [1, 2] and read.first_page_text == read.pages[0]["text"]
    assert read.identifiers == [intake.Identifier(
        "doi", pdfs.ZOLLER_DOI, 1, "J. Res. Sci. Teach. 27(10), 1053–1065 (1990) DOI: " + pdfs.ZOLLER_DOI)]
    kind, value, page, quote = read.identifiers[0]  # also a plain tuple
    assert (kind, page) == ("doi", 1) and quote in " ".join(read.first_page_text.split())
    # the largest text on page 1, across its two lines; pdflatex sets the apostrophe curly
    assert read.title_guess == pdfs.ZOLLER_TITLE.replace("'", "’")
    assert read.title_source == "largest text on page 1"
    # the DOI in the reference list on page 2 is another work's
    assert "10.9999/not.this.one" in read.pages[1]["text"]
    assert api.read_pdf(made["doi"]) == read


def test_arxiv_stamp(made):
    read = intake.read_pdf(made["arxiv"])
    assert [(i.kind, i.value, i.page) for i in read.identifiers] == [("arxiv", pdfs.ARXIV_ID + "v7", 1)]
    assert "arXiv:1706.03762v7 [cs.CL] 2 Aug 2023" in read.identifiers[0].quote
    assert read.title_guess == pdfs.ARXIV_TITLE  # not the stamp, which is set larger and turned


def test_title_only_and_metadata(made):
    read = intake.read_pdf(made["title"])
    assert read.identifiers == [] and read.title_guess == pdfs.MURDOCK_TITLE
    assert read.metadata["author"] == "Bennet B. Murdock" and read.metadata["producer"].startswith("pdfTeX")


def test_identifier_in_metadata_and_title_from_metadata(tmp_path, made):
    import pypdf
    writer = pypdf.PdfWriter(clone_from=str(made["unknown"]))
    writer.add_metadata({"/Title": "A title kept in the metadata only", "/Subject": "doi:10.1234/meta.5678; PMID: 12345678",
                         "/Keywords": "https://arxiv.org/abs/2208.02957v1"})
    path = tmp_path / "meta.pdf"
    with open(path, "wb") as handle:
        writer.write(handle)
    read = intake.read_pdf(path)
    assert {(i.kind, i.value, i.page) for i in read.identifiers} == {
        ("doi", "10.1234/meta.5678", None), ("pmid", "12345678", None), ("arxiv", "2208.02957v1", None)}
    assert next(i for i in read.identifiers if i.kind == "doi").quote == "metadata subject: doi:10.1234/meta.5678; PMID: 12345678"
    assert read.title_guess == pdfs.UNKNOWN_TITLE  # the page's own title comes before the metadata's
    assert intake._title_from_runs([("x", 10.0)]) is None


def test_encrypted_is_a_problem_not_an_exception(tmp_path, made):
    locked = pdfs.encrypted(made["doi"], tmp_path / "locked.pdf")
    read = intake.read_pdf(locked)
    assert (read.problem, read.pages, read.identifiers, read.title_guess) == ("encrypted", [], [], None)
    assert "password" in read.detail and read.sha256
    # encrypted against copying only (an empty user password): it opens, so it is read
    open_copy = intake.read_pdf(pdfs.encrypted(made["doi"], tmp_path / "owner.pdf", user_password=""))
    assert open_copy.problem is None and open_copy.identifiers[0].value == pdfs.ZOLLER_DOI


def test_not_a_pdf_damaged_missing(tmp_path):
    text = tmp_path / "notes.pdf"
    text.write_text("These are notes, not a PDF.", encoding="utf-8")
    assert intake.read_pdf(text).problem == "not_pdf"
    damaged = tmp_path / "damaged.pdf"
    damaged.write_bytes(b"%PDF-1.4\n" + b"not really a pdf body " * 50)
    read = intake.read_pdf(damaged)
    assert read.problem == "unreadable" and read.pages == [] and "could not be parsed" in read.detail
    with pytest.raises(CdlbibError, match="could not be opened"):
        intake.read_pdf(tmp_path / "absent.pdf")
    with pytest.raises(CdlbibError, match="%PDF-"):
        intake.render_first_page(text)


def test_page_cap_time_limit_and_size_cap(tmp_path, made, monkeypatch):
    import pypdf
    writer = pypdf.PdfWriter()
    for _ in range(4):
        writer.append(str(made["doi"]))
    long = tmp_path / "long.pdf"
    with open(long, "wb") as handle:
        writer.write(handle)
    assert len(pypdf.PdfReader(str(long)).pages) == 8
    assert [p["page"] for p in intake.read_pdf(long).pages] == [1, 2, 3, 4, 5]
    monkeypatch.setattr(intake, "READ_TIMEOUT", 0.001)
    slow = intake.read_pdf(long)
    assert slow.problem == "timeout" and slow.pages == []
    monkeypatch.setattr(intake, "READ_TIMEOUT", 60)
    monkeypatch.setattr(intake, "MAX_PDF_BYTES", 1000)
    big = intake.read_pdf(long)
    assert big.problem == "too_large" and big.sha256 is None
    with pytest.raises(CdlbibError, match="larger than"):
        intake.render_first_page(long)


def test_scan_without_and_with_ocr(tmp_path, made):
    if not shutil.which("gs"):
        pytest.skip("Ghostscript (gs) is not installed: no image-only PDF can be made")
    scan = pdfs.image_only(made["title"], tmp_path / "scan.pdf")
    plain = intake.read_pdf(scan, ocr=False)
    assert plain.problem == "no_text" and plain.identifiers == [] and plain.title_guess is None
    assert [p["text"].strip() for p in plain.pages] == ["", ""]
    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        pytest.skip("pdftoppm and tesseract are not both installed: local_ocr cannot run")
    read = intake.read_pdf(scan)
    assert read.problem is None and read.ocr and "OCR" in read.detail
    assert pdfs.MURDOCK_TITLE in read.first_page_text and intake.title_on_pages(read.pages, pdfs.MURDOCK_TITLE)


# --- the first page as an image -----------------------------------------------------------------

def _pixels(png):
    """Width, height, channels and the raw rows of a PNG written without row filters."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, depth, kind = struct.unpack(">IIBB", png[16:26])
    position, data = 8, b""
    while position < len(png):
        (length,), name = struct.unpack(">I", png[position:position + 4]), png[position + 4:position + 8]
        body = png[position + 8:position + 8 + length]
        assert struct.unpack(">I", png[position + 8 + length:position + 12 + length])[0] == zlib.crc32(name + body)
        if name == b"IDAT":
            data += body
        position += 12 + length
    assert depth == 8
    return width, height, {0: 1, 2: 3, 6: 4}[kind], zlib.decompress(data)


def test_render_first_page(tmp_path, made):
    pytest.importorskip("pypdfium2", reason="pypdfium2 (the 'pdf' extra) is not installed")
    png = intake.render_first_page(made["doi"], 300)
    width, height, channels, rows = _pixels(png)
    assert width == 300 and 380 <= height <= 400  # US letter, 8.5 x 11
    assert len(rows) == height * (1 + width * channels)
    values = set(rows[1:1 + width * channels]) | set(rows[len(rows) // 5:len(rows) // 5 + 5000])
    assert 255 in values and min(values) < 128  # white paper with dark type on it
    assert api.render_first_page(made["doi"], 300) == png
    for width in (0, 15, 4001):
        with pytest.raises(CdlbibError, match="between 16 and 4000"):
            intake.render_first_page(made["doi"], width)
    with pytest.raises(CdlbibError, match="could not be drawn"):
        intake.render_first_page(pdfs.encrypted(made["doi"], tmp_path / "locked.pdf"), 300)


def test_pdf_extra_is_registered_like_research():
    assert deps.requirements_for("pdf") == ["pypdfium2>=4"]
    assert deps.manual_command("pdf", "pypdfium2") == "pip install 'pypdfium2>=4'"


# --- the title on the page ----------------------------------------------------------------------

def test_title_on_pages():
    page = [{"page": 1, "text": "Running head\nThe eﬀect of inter-\nresponse times on Glöckner’s\nrecall model\nA. Author\n"}]
    assert intake.title_on_pages(page, "The effect of inter-response times on {G}l{\\\"o}ckner's recall model")
    assert intake.title_on_pages(page, "THE EFFECT OF INTER-RESPONSE TIMES ON GLÖCKNER'S RECALL MODEL")
    assert not intake.title_on_pages(page, "The effect of response times on recall")
    assert not intake.title_on_pages(page, "Recall")  # too short to mean anything
    assert not intake.title_on_pages([], "The effect of inter-response times")
    embedded = [{"page": 2, "text": "Title: Backward learning in paired associates (1956)\n"}]
    assert intake.title_on_pages(embedded, "Backward learning in paired associates")


# --- from a PDF to a source record --------------------------------------------------------------

def test_doi_gives_the_checked_entry(tmp_path, made, client):
    ws = library(tmp_path / "lib")
    result = intake.propose_from_pdf(ws, intake.read_pdf(made["doi"]), client=client)
    assert client.requests == 0 and result.matched
    assert result.found_by.kind == "doi" and result.tried == [f"doi {pdfs.ZOLLER_DOI}: record found"]
    proposal = result.proposal
    assert proposal.proposed_raw == ZOLL90  # the frozen library's entry, byte for byte
    assert proposal.status in ACCEPTED and not proposal.needs_decision and not proposal.manual
    assert proposal.issues == [] and proposal.key_proposed == "Zoll90"
    assert proposal.notes[0] == f"Found by the doi read from the PDF (page 1): {pdfs.ZOLLER_DOI}"
    assert ws.bib.read_text(encoding="utf-8") == ""  # nothing is written


def test_arxiv_stamp_gives_the_arxiv_entry(tmp_path, made, client):
    result = intake.propose_from_pdf(library(tmp_path / "lib"), intake.read_pdf(made["arxiv"]), client=client)
    assert client.requests == 0 and result.found_by.kind == "arxiv"
    raw = result.proposal.proposed_raw
    assert "\tJournal = {{arXiv}}" in raw and "\tVolume = {1706.03762v7}" in raw
    assert "\tTitle = {Attention is all you need}" in raw and raw.startswith("@article{VaswEtal23,")
    assert not result.proposal.needs_decision and not result.proposal.manual


def test_title_and_metadata_author_find_the_one_record(tmp_path, made, client):
    result = intake.propose_from_pdf(library(tmp_path / "lib"), intake.read_pdf(made["titled"]), client=client)
    assert client.requests == 0 and result.found_by.kind == "title"
    assert result.proposal.proposed_raw == ZOLL90 and not result.proposal.needs_decision
    assert "first author Uri Zoller" in result.tried[0]


def test_title_that_matches_no_record_exactly_gives_leads_only(tmp_path, made, client):
    result = intake.propose_from_pdf(library(tmp_path / "lib"), intake.read_pdf(made["title"]), client=client)
    assert client.requests == 0 and not result.matched and result.found_by is None
    assert [c["doi"] for c in result.candidates] == ["10.1037/h0044314"]  # '"Backward" learning ...': not taken
    assert len(result.tried) == 2 and "none is taken without a choice" in result.tried[0]
    assert "1 similar record(s)" in result.message and "language model" in result.message
    assert result.prefill == {"title": pdfs.MURDOCK_TITLE}


def test_another_works_identifier_is_never_taken_silently(tmp_path, made, client):
    read = intake.read_pdf(made["mismatch"])
    assert read.identifiers[0].value == pdfs.ZOLLER_DOI and read.title_guess == pdfs.OTHER_TITLE
    result = intake.propose_from_pdf(library(tmp_path / "lib"), read, client=client)
    assert client.requests == 0 and result.matched
    proposal = result.proposal
    assert proposal.needs_decision and proposal.proposed_raw == ZOLL90
    assert len(proposal.issues) == 1 and "is not on the first 2 page(s) of the PDF" in proposal.issues[0]
    assert "may be a different work" in proposal.issues[0]
    assert result.prefill == {"title": pdfs.OTHER_TITLE, "doi": pdfs.ZOLLER_DOI}


def test_nothing_found_carries_what_was_read(tmp_path, made, client):
    read = intake.read_pdf(made["unknown"])
    result = intake.propose_from_pdf(library(tmp_path / "lib"), read, client=client)
    assert client.requests == 0
    assert (result.proposal, result.found_by, result.candidates) == (None, None, [])
    assert result.message.startswith("No source record was found for this PDF.")
    assert result.intake is read and result.prefill == {"title": pdfs.UNKNOWN_TITLE}
    assert result.tried == [f"title {pdfs.UNKNOWN_TITLE}: No record in Crossref or PubMed matches the title; "
                            "the entry is left as typed"]


def test_duplicate_in_the_library_is_flagged(tmp_path, made, client):
    result = intake.propose_from_pdf(library(tmp_path / "lib", ZOLL90), intake.read_pdf(made["doi"]), client=client)
    assert result.proposal.duplicate_of == "Zoll90" and result.proposal.needs_decision
    assert "already in the library" in result.proposal.issues[-1]


def test_a_pdf_that_gave_nothing_is_not_looked_up(tmp_path, made, client):
    locked = intake.read_pdf(pdfs.encrypted(made["doi"], tmp_path / "locked.pdf"))
    result = intake.propose_from_pdf(library(tmp_path / "lib"), locked, client=client)
    assert not result.matched and result.tried == [] and result.prefill == {}
    assert result.message.startswith("No DOI, arXiv id, PMID or title could be read")


def test_a_source_that_does_not_answer_is_said(tmp_path, made):
    empty = offline_client(tmp_path / "empty")  # no saved response: every lookup is refused
    try:
        result = intake.propose_from_pdf(library(tmp_path / "lib"), intake.read_pdf(made["doi"]), client=empty)
    finally:
        empty.cache.close()
    assert not result.matched and "offline" in result.tried[0] and result.tried[0].startswith("doi ")


# --- limits are applied before or while the work they bound -------------------------------------

def _bomb(path, megabytes):
    """A one-page PDF of a few kilobytes whose content stream inflates to ``megabytes`` MB."""
    import pypdf
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 700 Td (A) Tj ET\n" + b" " * (megabytes * 1_000_000))
    page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


def test_a_stream_that_inflates_beyond_the_cap_is_not_inflated(tmp_path, monkeypatch):
    import time
    bomb = _bomb(tmp_path / "bomb.pdf", 60)
    assert bomb.stat().st_size < 200_000  # 60 MB of content in a small file
    started = time.monotonic()
    read = intake.read_pdf(bomb)
    assert read.problem == "unreadable" and read.pages == [] and "LimitReachedError" in read.detail
    assert time.monotonic() - started < 30
    # the cap is what stopped it: with the cap above the stream's size the same file is read
    monkeypatch.setattr(intake, "MAX_STREAM_BYTES", 75_000_000)
    assert [p["text"].strip() for p in intake.read_pdf(bomb).pages] == ["A"]


def test_text_extraction_stops_at_the_caps(made, monkeypatch):
    whole = intake.read_pdf(made["doi"])
    assert whole.detail is None and len(whole.pages) == 2 and len(whole.pages[0]["text"]) > 1000
    monkeypatch.setattr(intake, "MAX_PAGE_CHARS", 200)
    cut = intake.read_pdf(made["doi"])
    assert cut.problem is None and "was cut" in cut.detail
    assert [p["page"] for p in cut.pages] == [1]  # reading stopped there: page 2 was never extracted
    assert 0 < len(cut.pages[0]["text"]) <= 200 and whole.pages[0]["text"].startswith(cut.pages[0]["text"][:150])
    monkeypatch.setattr(intake, "MAX_PAGE_CHARS", 100_000)
    monkeypatch.setattr(intake, "MAX_TOTAL_CHARS", len(whole.pages[0]["text"]) + 50)
    capped = intake.read_pdf(made["doi"])
    assert sum(len(p["text"]) for p in capped.pages) <= intake.MAX_TOTAL_CHARS and "was cut" in capped.detail
    assert capped.pages[0]["text"] == whole.pages[0]["text"] and len(capped.pages[1]["text"]) <= 50
    # the child's own answer: extraction stopped inside page 1 (the visitor raised), page 2 was not begun
    code, out, _, over = intake._child(["read", made["doi"], 5, 200, 300_000, 20_000_000], 60, 4_000_000)
    job = json.loads(out)
    assert (code, over) == (0, False) and [p["page"] for p in job["pages"]] == [1] and "was cut" in job["detail"]


def test_a_child_that_writes_too_much_or_too_long_is_killed(made, monkeypatch):
    import time
    arguments = ["read", made["doi"], 5, 100_000, 300_000, 20_000_000]
    code, out, err, over = intake._child(arguments, 60, 4_000_000)
    assert (code, over) == (0, False) and out.startswith(b"{")
    started = time.monotonic()
    code, out, err, over = intake._child(arguments, 60, 100)
    assert over and len(out) <= 100 + 65536 and code != 0  # stopped at the limit and killed, not read to the end
    assert time.monotonic() - started < 30
    with pytest.raises(subprocess.TimeoutExpired):
        intake._child(arguments, 0.01, 4_000_000)
    code, out, err, over = intake._child(["nonsense"], 60, 1000)
    assert code == 2 and out == b"" and "usage:" in err
    monkeypatch.setattr(intake, "MAX_OUTPUT_BYTES", 100)
    read = intake.read_pdf(made["doi"])
    assert read.problem == "unreadable" and "more than 100 bytes" in read.detail and read.pages == []


def test_the_limits_a_child_sets_on_itself():
    """What the platform accepts, by experiment: the CPU limit everywhere; the memory limits
    on Linux. macOS refuses them (setrlimit raises), so there the caps above are the bound."""
    code, out, err, over = intake._child(["limits"], 60, 1000)
    limits = json.loads(out)
    assert code == 0 and "RLIMIT_CPU" in limits
    if sys.platform.startswith("linux"):
        assert "RLIMIT_AS" in limits
    else:
        assert set(limits) <= {"RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_DATA"}


def test_a_preview_is_sized_before_it_is_drawn(tmp_path, made, monkeypatch):
    pytest.importorskip("pypdfium2", reason="pypdfium2 (the 'pdf' extra) is not installed")
    import pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(72, 14400)  # one inch wide, 200 inches high
    tall = tmp_path / "tall.pdf"
    with open(tall, "wb") as handle:
        writer.write(handle)
    with pytest.raises(CdlbibError, match="it would be 800000 pixels high, more than the 16000000 pixels"):
        intake.render_first_page(tall, 4000)
    assert intake.render_first_page(tall, 16)[:8] == b"\x89PNG\r\n\x1a\n"  # 16 x 3200: within the limit
    monkeypatch.setattr(intake, "MAX_PIXELS", 10_000)
    with pytest.raises(CdlbibError, match="more than the 10000 pixels"):
        intake.render_first_page(made["doi"], 300)
    monkeypatch.setattr(intake, "MAX_PIXELS", 16_000_000)
    monkeypatch.setattr(intake, "MAX_IMAGE_BYTES", 1000)
    with pytest.raises(CdlbibError, match="larger than 1000 bytes; drawing was stopped"):
        intake.render_first_page(made["doi"], 800)
