import gzip
import json
from pathlib import Path
import sys

import pytest
import requests
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from research import allowed_url, download_pdf, invoke_adapter, validate_findings
from verification import (
    Cache,
    current_results,
    export_snapshot,
    import_snapshot,
    load_entries,
)
from verification_cli import app
import research


def test_pdf_mirror_fallback_records_failed_source(tmp_path, monkeypatch):
    calls = []

    def download(url, hosts, directory):
        calls.append(url)
        if len(calls) == 1:
            raise ValueError("Publisher link unavailable")
        return tmp_path / "paper.pdf", "sha", url

    monkeypatch.setattr(research, "download_pdf", download)
    monkeypatch.setattr(research.time, "sleep", lambda _: None)
    result = research.download_discovered_pdf(
        {
            "pdf_url": "https://source.org/a.pdf",
            "pdf_alternatives": [
                "https://source.org/a.pdf",
                "https://mirror.org/b.pdf",
            ],
        },
        ["source.org", "mirror.org"],
        tmp_path,
    )
    assert calls == ["https://source.org/a.pdf", "https://mirror.org/b.pdf"]
    assert [a["status"] for a in result[3]] == ["unavailable", "downloaded"]


def test_pdf_mirror_attempts_are_bounded(tmp_path, monkeypatch):
    calls = []

    def unavailable(url, *args):
        calls.append(url)
        raise ValueError("Unavailable")

    monkeypatch.setattr(research, "download_pdf", unavailable)
    monkeypatch.setattr(research.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="copies unavailable"):
        research.download_discovered_pdf(
            {
                "pdf_url": "https://source.org/0.pdf",
                "pdf_alternatives": [
                    f"https://source.org/{i}.pdf" for i in range(1, 10)
                ],
            },
            ["source.org"],
            tmp_path,
        )
    assert len(calls) == 3


def test_pdf_throttling_does_not_retry_same_host(tmp_path, monkeypatch):
    calls = []

    def throttle(url, *args):
        calls.append(url)
        response = requests.Response()
        response.status_code = 429
        response.url = url
        raise requests.HTTPError("Throttled", response=response)

    monkeypatch.setattr(research, "download_pdf", throttle)
    monkeypatch.setattr(research.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="copies unavailable"):
        research.download_discovered_pdf(
            {
                "pdf_url": "https://source.org/one.pdf",
                "pdf_alternatives": ["https://source.org/two.pdf"],
            },
            ["source.org"],
            tmp_path,
        )
    assert calls == ["https://source.org/one.pdf"]


def test_quote_evidence_checks_actual_page():
    pages = [{"page": 1, "text": "Actual title\nAlice Author\nPublished 2020"}]
    findings = {
        "fields": {
            "title": {"value": "Actual title", "page": 1, "quote": "Actual title"}
        }
    }
    assert validate_findings(findings, pages)
    findings["fields"]["title"]["quote"] = "Fabricated title"
    with pytest.raises(ValueError, match="absent"):
        validate_findings(findings, pages)
    findings["fields"]["title"] = {
        "value": "Actual title",
        "page": 2,
        "quote": "Actual title",
    }
    with pytest.raises(ValueError, match="absent"):
        validate_findings(findings, pages)


@pytest.mark.parametrize(
    "url",
    [
        "http://source.org/p.pdf",
        "https://evil.org/p.pdf",
        "https://user:pass@source.org/p.pdf",
        "file:///tmp/p.pdf",
        "https://source.org:444/p.pdf",
    ],
)
def test_pdf_url_allowlist(url):
    with pytest.raises(ValueError):
        allowed_url(url, {"source.org"})


def test_adapter_protocol_without_shell(tmp_path):
    script = tmp_path / "adapter with spaces"
    script.write_text(
        '#!/usr/bin/env python3\nimport json,sys\np=json.load(sys.stdin)\nprint(json.dumps({"phase":p["phase"]}))\n'
    )
    script.chmod(0o700)
    assert invoke_adapter(script, {"phase": "discover"}) == {"phase": "discover"}


def test_reject_paywall_instead_of_pdf(tmp_path):
    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield b"<html>Login required</html>"

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    with pytest.raises(ValueError, match="did not return a PDF"):
        download_pdf(
            "https://source.org/file", ["source.org"], tmp_path, session=Session()
        )


def test_snapshot_portable_and_edited_entry_not_restored(tmp_path):
    original = tmp_path / "original.bib"
    original.write_text(
        "@book{A,title={One},year={2020}}\n@book{B,title={Two},year={2021}}"
    )
    cache = Cache(tmp_path / "original.sqlite3")
    for entry in load_entries(original).values():
        cache.put(
            original,
            entry,
            {
                "status": "human_verified",
                "human_review": {
                    "reviewer": "Human",
                    "source": "Book",
                    "note": "Checked",
                },
            },
        )
    snapshot = tmp_path / "snapshot.jsonl.gz"
    export_snapshot(original, cache, snapshot)
    moved = tmp_path / "other-clone.bib"
    moved.write_text(original.read_text().replace("year={2021}", "year={2022}"))
    restored = Cache(tmp_path / "restored.sqlite3")
    assert import_snapshot(moved, restored, snapshot) == 1
    result = current_results(moved, restored)
    assert result["A"]["status"] == "human_verified"
    assert result["B"]["status"] == "pending"
    assert import_snapshot(moved, restored, snapshot) == 0


def test_bad_snapshot_is_atomic(tmp_path):
    bib = tmp_path / "a.bib"
    bib.write_text("@book{A,title={One},year={2020}}")
    cache = Cache(tmp_path / "a.sqlite3")
    entry = load_entries(bib)["A"]
    snapshot = tmp_path / "bad.jsonl.gz"
    with gzip.open(snapshot, "wt") as stream:
        stream.write(json.dumps({"schema": 1, "policy": "1", "entries": 2}) + "\n")
        stream.write(
            json.dumps(
                dict(
                    key="A",
                    fingerprint=entry["fingerprint"],
                    policy="1",
                    status="needs_review",
                )
            )
            + "\n"
        )
        stream.write(
            json.dumps(dict(key="B", fingerprint="x", policy="1", status="bogus"))
            + "\n"
        )
    with pytest.raises(ValueError):
        import_snapshot(bib, cache, snapshot)
    assert cache.db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0


def test_gate_requires_human_and_rejects_unknown_keys(tmp_path):
    bib = tmp_path / "a.bib"
    bib.write_text("@book{A,title={One},year={2020}}")
    database = tmp_path / "a.sqlite3"
    cache = Cache(database)
    cache.put(bib, load_entries(bib)["A"], {"status": "metadata_verified"})
    cache.close()
    runner = CliRunner()
    base = ["status", str(bib), "--database", str(database)]
    assert runner.invoke(app, base).exit_code == 0
    assert runner.invoke(app, base + ["--require-human"]).exit_code == 1
    keys = tmp_path / "keys.txt"
    keys.write_text("Missing\n")
    assert runner.invoke(app, base + ["--keys", str(keys)]).exit_code == 2


def test_scanned_pdf_requires_human(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from research import extract_pages

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=300, height=300)
    path = tmp_path / "scan.pdf"
    writer.write(path)
    with pytest.raises(ValueError, match="no extractable text"):
        extract_pages(path)


def test_actual_pdf_text_extraction(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    from research import extract_pages

    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 20 200 Td (Actual title) Tj ET")
    page[NameObject("/Contents")] = content
    path = tmp_path / "paper.pdf"
    writer.write(path)
    pages = extract_pages(path)
    assert "Actual title" in pages[0]["text"]


def test_reports_cannot_overwrite_bibliography_or_cache(tmp_path):
    from verification import write_report

    bib = tmp_path / "a.bib"
    original = "@book{A,title={One},year={2020}}"
    bib.write_text(original)
    cache = Cache(tmp_path / "a.sqlite3")
    alias = tmp_path / "alias.bib"
    alias.symlink_to(bib)
    for output in (bib, alias, cache.path):
        with pytest.raises(ValueError, match="overwrite"):
            write_report(bib, cache, output)
        with pytest.raises(ValueError, match="overwrite"):
            export_snapshot(bib, cache, output)
    assert bib.read_text() == original


def test_bad_output_fails_before_any_requests(tmp_path):
    from verification import run_verification

    bib = tmp_path / "a.bib"
    bib.write_text("@book{A,title={One},year={2020}}")
    cache = Cache(tmp_path / "a.sqlite3")

    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError(
                "Invalid output must be rejected before network access"
            )

    with pytest.raises(ValueError, match="overwrite"):
        run_verification(bib, cache, NoNetwork(), bib)
