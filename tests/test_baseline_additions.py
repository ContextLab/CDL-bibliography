"""The results saved since the snapshot (verification/baseline-additions.jsonl).

The snapshot (verification/baseline.jsonl.gz) is 16 MB of gzip, stored whole by git each time
it changes, so what is verified after it was written is saved in a second file beside it:
plain JSON Lines, one result a line. `crossref snapshot --additions-to SNAPSHOT` writes it,
`crossref restore SNAPSHOT` reads it with the snapshot, and a whole `crossref snapshot`
empties it.

Real files and the real commands throughout. The fixture (tests/fixtures/additions) is five
entries of cdl.bib and their saved results, frozen from the baseline of 2026-10-08; the human
approvals are the three frozen rows of tests/fixtures/revocation.
"""
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cdlbib import verification as v
from cdlbib.verification_cli import app
from cdlbib.workspace import Workspace

FIX = Path(__file__).resolve().parent / "fixtures" / "additions"
RESULTS = FIX / "results.jsonl.gz"
KEYS = ["AntoEtal24", "NguyEtal19", "Rame72", "Schr00b", "YeshEtal21"]
HUMAN = Path(__file__).resolve().parent / "fixtures" / "revocation"
HEADER = '{"additions":true,"policy":"2","schema":2}\n'


@pytest.fixture(autouse=True)
def _the_librarys_own_ledgers(monkeypatch):
    # Each library reads the ledgers in its own verification/ folder, as outside the tests.
    monkeypatch.setattr(v, "REVOCATION_LEDGER", None)


def texts(source=FIX / "entries.bib"):
    return {key: entry["raw"].strip() for key, entry in v.load_entries(str(source)).items()}


def library(folder, keys, source=FIX / "entries.bib"):
    """A library folder holding the entries ``keys`` of the fixture, and an empty verification/."""
    (folder / "verification").mkdir(parents=True, exist_ok=True)
    write(folder, keys, source)
    return Workspace(folder)


def write(folder, keys, source=FIX / "entries.bib"):
    every = texts(source)
    (folder / "cdl.bib").write_text("\n\n".join(every[key] for key in keys) + "\n", encoding="utf-8")


def run(ws, *arguments, database=None):
    """One `cdlbib crossref` command on the library, in a database of the library's own."""
    arguments = list(arguments)
    command, rest = arguments[0], arguments[1:]
    named = [str(ws.bib)] if command == "status" else ["--fname", str(ws.bib)]
    return CliRunner().invoke(app, [command, *rest, *named, "--database", str(database or ws.database)])


def statuses(ws, database=None):
    cache = v.Cache(str(database or ws.database), ledger=ws.revocations)
    try:
        return {key: result["status"] for key, result in v.current_results(str(ws.bib), cache).items()}
    finally:
        cache.close()


def lines_of(path):
    return Path(path).read_text(encoding="utf-8").splitlines()


def rows_of(path):
    return [json.loads(line) for line in lines_of(path)[1:]]


def saved(tmp_path, in_snapshot, since, results=RESULTS, source=FIX / "entries.bib"):
    """A library whose snapshot holds the results of ``in_snapshot`` and whose additions file
    holds those of ``since``, made the way they are made: the snapshot is written while the
    library holds the first entries, the others are added to cdl.bib and get their results
    (restored here from the frozen ones, in place of a network check), and
    `crossref snapshot --additions-to` writes what the snapshot lacks."""
    ws = library(tmp_path / "library", in_snapshot, source)
    work = tmp_path / "work.sqlite3"
    assert run(ws, "restore", str(results), database=work).exit_code == 0
    done = run(ws, "snapshot", str(ws.baseline), database=work)
    assert done.exit_code == 0, done.output
    write(ws.root, sorted(in_snapshot + since), source)
    assert run(ws, "restore", str(results), database=work).exit_code == 0
    done = run(ws, "snapshot", "--additions-to", str(ws.baseline), database=work)
    assert done.exit_code == 0, done.output
    return ws, done


# --- written -----------------------------------------------------------------------------------


def test_the_additions_hold_exactly_the_results_the_snapshot_lacks(tmp_path):
    ws, done = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    assert ws.additions == v.additions_beside(ws.baseline) == ws.root / "verification" / "baseline-additions.jsonl"
    assert f"2 results that {ws.baseline} lacks: Rame72, YeshEtal21" in done.output
    assert done.output.rstrip().endswith(str(ws.additions))          # the default place: beside the snapshot
    data = ws.additions.read_bytes()
    assert data.decode("utf-8").startswith(HEADER) and data.endswith(b"\n")
    assert data[:2] != b"\x1f\x8b"                                    # plain text, not gzip
    assert [row["key"] for row in rows_of(ws.additions)] == ["Rame72", "YeshEtal21"]
    # Each line is the snapshot's record of that result, byte for byte.
    with gzip.open(RESULTS, "rt", encoding="utf-8") as stream:
        frozen = {json.loads(line)["key"]: line for line in list(stream)[1:]}
    assert lines_of(ws.additions)[1:] == [frozen["Rame72"].rstrip("\n"), frozen["YeshEtal21"].rstrip("\n")]
    with gzip.open(ws.baseline, "rt", encoding="utf-8") as stream:
        assert sorted(json.loads(line)["key"] for line in list(stream)[1:]) == ["AntoEtal24", "NguyEtal19", "Schr00b"]


def test_with_nothing_to_add_the_file_holds_its_header_alone(tmp_path):
    ws, done = saved(tmp_path, KEYS, [])
    assert f"0 results that {ws.baseline} lacks" in done.output
    assert ws.additions.read_text(encoding="utf-8") == HEADER


def test_an_entry_without_a_result_has_no_line(tmp_path):
    ws, _ = saved(tmp_path, ["AntoEtal24"], ["Rame72"])
    text = ws.bib.read_text(encoding="utf-8")
    ws.bib.write_text(text.replace("Volume = {1},", "Volume = {2},"), encoding="utf-8")   # Rame72 edited: pending
    done = run(ws, "snapshot", "--additions-to", str(ws.baseline), database=tmp_path / "work.sqlite3")
    assert done.exit_code == 0 and "0 results" in done.output
    assert ws.additions.read_text(encoding="utf-8") == HEADER       # and the result of the old text is dropped


def test_one_more_result_is_one_more_line_and_no_other_line_changes(tmp_path):
    ws, _ = saved(tmp_path, ["NguyEtal19"], ["AntoEtal24", "YeshEtal21"])
    before = ws.additions.read_bytes().split(b"\n")
    work = tmp_path / "work.sqlite3"
    for added, place in (("Rame72", 2), ("Schr00b", 3)):               # each falls between two lines held
        write(ws.root, sorted(v.load_entries(str(ws.bib)).keys() | {added}))
        assert run(ws, "restore", str(RESULTS), database=work).exit_code == 0
        assert run(ws, "snapshot", "--additions-to", str(ws.baseline), database=work).exit_code == 0
        after = ws.additions.read_bytes().split(b"\n")
        assert len(after) == len(before) + 1
        assert json.loads(after[place])["key"] == added
        assert after[:place] + after[place + 1:] == before            # every other line, in its order, byte for byte
        before = after
    assert [row["key"] for row in rows_of(ws.additions)] == ["AntoEtal24", "Rame72", "Schr00b", "YeshEtal21"]
    # Written again from a database that was restored from the files themselves: the same bytes.
    kept = ws.additions.read_bytes()
    fresh = tmp_path / "fresh.sqlite3"
    assert run(ws, "restore", str(ws.baseline), database=fresh).exit_code == 0
    assert run(ws, "snapshot", "--additions-to", str(ws.baseline), database=fresh).exit_code == 0
    assert ws.additions.read_bytes() == kept


# --- restored ----------------------------------------------------------------------------------


def test_restore_of_the_snapshot_and_its_additions_gives_every_entry_its_result(tmp_path):
    ws, _ = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    fresh = tmp_path / "fresh.sqlite3"
    done = run(ws, "restore", str(ws.baseline), database=fresh)        # the file beside the snapshot is read
    assert done.exit_code == 0, done.output
    assert done.output.splitlines() == [
        "Restored 5 matching reviews",
        f"2 of them from {ws.additions} (2 results saved since the snapshot)"]
    assert statuses(ws, fresh) == dict.fromkeys(KEYS, "metadata_verified")
    assert run(ws, "status", database=fresh).exit_code == 0
    # The same through the installed command, run in the library's folder as a person runs it.
    command = Path(sys.executable).parent / "cdlbib"
    again = subprocess.run([str(command), "--library", str(ws.root), "crossref", "restore",
                            "verification/baseline.jsonl.gz", "--database", str(tmp_path / "command.sqlite3")],
                           cwd=ws.root, capture_output=True, text=True,
                           env={k: val for k, val in os.environ.items() if k != "CDLBIB_LIBRARY"})
    assert again.returncode == 0, again.stdout + again.stderr
    assert again.stdout.splitlines()[0] == "Restored 5 matching reviews"
    assert "2 of them from verification/baseline-additions.jsonl" in again.stdout


def test_another_additions_file_or_none_can_be_named(tmp_path):
    ws, _ = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    alone = tmp_path / "alone.sqlite3"
    done = run(ws, "restore", str(ws.baseline), "--no-additions", database=alone)
    assert done.exit_code == 0 and done.output == "Restored 3 matching reviews\n"
    assert statuses(ws, alone) == {"AntoEtal24": "metadata_verified", "NguyEtal19": "metadata_verified",
                                   "Schr00b": "metadata_verified", "Rame72": "pending", "YeshEtal21": "pending"}
    elsewhere = tmp_path / "elsewhere.jsonl"
    elsewhere.write_text(HEADER + lines_of(ws.additions)[1] + "\n", encoding="utf-8")   # Rame72's line alone
    named = tmp_path / "named.sqlite3"
    done = run(ws, "restore", str(ws.baseline), "--additions", str(elsewhere), database=named)
    assert done.exit_code == 0 and "Restored 4 matching reviews" in done.output
    assert statuses(ws, named)["Rame72"] == "metadata_verified" and statuses(ws, named)["YeshEtal21"] == "pending"
    done = run(ws, "restore", str(ws.baseline), "--additions", str(tmp_path / "absent.jsonl"), database=tmp_path / "x.sqlite3")
    assert done.exit_code == 2 and "is not a regular file" in done.output
    done = run(ws, "restore", str(ws.baseline), "--additions", str(elsewhere), "--no-additions", database=tmp_path / "x.sqlite3")
    assert done.exit_code == 2 and "not both" in done.output


def test_restore_without_an_additions_file_is_as_it_was(tmp_path):
    ws, _ = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    ws.additions.unlink()
    fresh = tmp_path / "fresh.sqlite3"
    done = run(ws, "restore", str(ws.baseline), database=fresh)
    assert done.exit_code == 0 and done.output == "Restored 3 matching reviews\n"
    assert sorted(key for key, status in statuses(ws, fresh).items() if status == "pending") == ["Rame72", "YeshEtal21"]
    cache = v.Cache(str(tmp_path / "function.sqlite3"), ledger=ws.revocations)
    try:
        assert v.import_snapshot(str(ws.bib), cache, str(ws.baseline)) == 3   # the function reads none unless given one
    finally:
        cache.close()


def test_a_result_saved_for_another_text_is_not_restored_and_is_named(tmp_path):
    """A line whose fingerprint is the text of no entry (the entry was edited since, or the
    fingerprint was typed) restores nothing, as such a row of a snapshot restores nothing;
    restore says which line it was. The rest is restored."""
    ws, _ = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    text = ws.bib.read_text(encoding="utf-8")
    ws.bib.write_text(text.replace("Volume = {1},", "Volume = {2},"), encoding="utf-8")   # Rame72 is another text now
    fresh = tmp_path / "fresh.sqlite3"
    done = run(ws, "restore", str(ws.baseline), database=fresh)
    assert done.exit_code == 0, done.output
    assert "Restored 4 matching reviews" in done.output
    assert f"Not restored from {ws.additions}: Rame72 (no entry has the text the result was saved for)" in done.output
    assert statuses(ws, fresh)["Rame72"] == "pending" and statuses(ws, fresh)["YeshEtal21"] == "metadata_verified"
    # The result of one entry under the fingerprint of another entry's text: it is that text's
    # result under the rule of a snapshot (the fingerprint decides, the key does not), and the
    # entry named in the line gains nothing.
    ws.bib.write_text(text, encoding="utf-8")
    rows = rows_of(ws.additions)
    other = v.load_entries(str(ws.bib))["YeshEtal21"]["fingerprint"]
    ws.additions.write_text(HEADER + v.dumps(dict(rows[0], fingerprint=other)) + "\n", encoding="utf-8")
    typed = tmp_path / "typed.sqlite3"
    assert run(ws, "restore", str(ws.baseline), database=typed).exit_code == 0
    assert statuses(ws, typed)["Rame72"] == "pending"
    # A fingerprint that is none at all is refused.
    ws.additions.write_text(HEADER + v.dumps(dict(rows[0], fingerprint="v2:typed")) + "\n", encoding="utf-8")
    done = run(ws, "restore", str(ws.baseline), database=tmp_path / "none.sqlite3")
    assert done.exit_code == 2 and "Invalid additions review record: 'Rame72'" in done.output


def tamper(what, ws, tmp_path):
    """Make the additions file one that must be refused; returns the message expected."""
    header, first, second = lines_of(ws.additions)
    row = json.loads(first)

    def put(*lines):
        ws.additions.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    if what == "a line that is not JSON":
        put(header, first[:-20], second)
        return "line 2 is not a JSON object"
    if what == "a line that is a list":
        put(header, "[" + first + "]", second)
        return "line 2 is not a JSON object"
    if what == "an empty line":
        put(header, first, "", second)
        return "line 3 is not a JSON object"
    if what == "no header":
        put(first, second)
        return "does not begin with the header of this policy"
    if what == "the header of another policy":
        put(header.replace('"policy":"2"', '"policy":"1"'), first, second)
        return "does not begin with the header of this policy"
    if what == "a row of another policy":
        put(header, v.dumps(dict(row, policy="1")), second)
        return "Invalid additions review record: 'Rame72'"
    if what == "a row without a fingerprint":
        put(header, v.dumps({k: val for k, val in row.items() if k != "fingerprint"}), second)
        return "Invalid additions review record: 'Rame72'"
    if what == "a status that is none":
        put(header, v.dumps(dict(row, status="verified")), second)
        return "Invalid additions review record: 'Rame72'"
    if what == "a pending row":
        put(header, v.dumps(dict(row, status="pending")), second)
        return "Invalid additions review record: 'Rame72'"
    if what == "the same key twice":
        put(header, first, first)
        return "Invalid additions review record: 'Rame72'"
    if what == "a machine approval without its evidence":
        put(header, v.dumps(dict(row, candidates=[])), second)
        return "Machine approval is missing its source evidence: Rame72"
    if what == "a human approval without its audit record":
        put(header, v.dumps(dict(row, status="human_verified")), second)
        return "Human approval is missing its audit record: Rame72"
    if what == "a line over the size of one result":
        put(header, v.dumps(dict(row, padding="x" * v.ADDITIONS_ROW_MAX_BYTES)), second)
        return f"line 2: {len(v.dumps(dict(row, padding='x' * v.ADDITIONS_ROW_MAX_BYTES))) + 1} bytes, over the limit of {v.ADDITIONS_ROW_MAX_BYTES}"
    if what == "a file over the size of the file":
        filler = v.dumps(dict(row, padding="x" * (v.ADDITIONS_ROW_MAX_BYTES // 2)))
        put(header, *[filler] * (v.ADDITIONS_MAX_BYTES // len(filler) + 1))
        return f"bytes, over the limit of {v.ADDITIONS_MAX_BYTES}; nothing of it was read"
    if what == "bytes that are not UTF-8":
        ws.additions.write_bytes(ws.additions.read_bytes().replace(b"Ramer", b"Ram\xe9r", 1))
        return "is not UTF-8 text"
    if what == "a link":
        real = tmp_path / "real.jsonl"
        real.write_bytes(ws.additions.read_bytes())
        ws.additions.unlink()
        ws.additions.symlink_to(real)
        return "is not a regular file (a link is not read)"
    raise AssertionError(what)


REFUSED = ["a line that is not JSON", "a line that is a list", "an empty line", "no header",
           "the header of another policy", "a row of another policy", "a row without a fingerprint",
           "a status that is none", "a pending row", "the same key twice", "a machine approval without its evidence",
           "a human approval without its audit record", "a line over the size of one result",
           "a file over the size of the file", "bytes that are not UTF-8", "a link"]


@pytest.mark.parametrize("what", REFUSED)
def test_an_additions_file_restore_must_refuse_is_refused_whole_with_the_reason(tmp_path, what):
    """Whatever restore refuses in a row of a snapshot it refuses in a line of the additions,
    by the same check, and the file's own form is checked besides. Nothing is restored then,
    from either file."""
    ws, _ = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    expected = tamper(what, ws, tmp_path)
    fresh = tmp_path / "fresh.sqlite3"
    done = run(ws, "restore", str(ws.baseline), database=fresh)
    assert done.exit_code == 2, done.output
    assert expected in done.output
    assert statuses(ws, fresh) == dict.fromkeys(KEYS, "pending")       # not the snapshot's three either
    # The snapshot alone is still good: the additions were what was refused.
    assert run(ws, "restore", str(ws.baseline), "--no-additions", database=fresh).exit_code == 0


@pytest.mark.parametrize("what", ["a row of another policy", "a status that is none", "the same key twice",
                                  "a machine approval without its evidence", "a human approval without its audit record"])
def test_the_same_row_is_refused_in_a_snapshot(tmp_path, what):
    """The control: the tampered lines above, as the rows of a snapshot, are refused by restore
    in the same words but for the file's name."""
    ws, _ = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    expected = tamper(what, ws, tmp_path).replace("additions review record", "snapshot review record")
    rows = lines_of(ws.additions)[1:]
    snapshot = tmp_path / "as-snapshot.jsonl.gz"
    with gzip.open(snapshot, "wt", encoding="utf-8") as stream:
        stream.write(v.dumps({"schema": 2, "policy": v.POLICY, "entries": len(rows)}) + "\n")
        stream.write("".join(row + "\n" for row in rows))
    done = run(ws, "restore", str(snapshot), database=tmp_path / "fresh.sqlite3")
    assert done.exit_code == 2 and expected in done.output, done.output


# --- human approvals: trusted as far as the same row of the snapshot ------------------------------


def approvals_library(tmp_path, name, in_snapshot, since):
    bib, results = HUMAN / "entries-7f3eead.bib", HUMAN / "baseline-7f3eead-3-approvals.jsonl.gz"
    ws, _ = saved(tmp_path / name, in_snapshot, since, results=results, source=bib)
    return ws


def test_a_human_approval_in_the_additions_is_what_it_is_in_the_snapshot(tmp_path):
    """The three frozen human approvals, once all in the snapshot and once two of them in the
    additions: restored, they give the same statuses and the same stored results. A revocation
    (in the library's ledger, or in a file given with --trusted-revocations, as the pull
    request check gives the base revision's) withdraws the approval in either file alike."""
    whole = approvals_library(tmp_path, "whole", ["Mink15", "NastEtal20", "Palm78"], [])
    split = approvals_library(tmp_path, "split", ["NastEtal20"], ["Mink15", "Palm78"])
    assert [row["key"] for row in rows_of(split.additions)] == ["Mink15", "Palm78"]
    assert all(row["status"] == "human_verified" and row["human_review"] for row in rows_of(split.additions))

    def restored(ws, name, *more):
        database = ws.root.parent / name
        done = run(ws, "restore", str(ws.baseline), *more, database=database)
        assert done.exit_code == 0, done.output
        cache = v.Cache(str(database), ledger=ws.revocations)
        try:
            results = v.current_results(str(ws.bib), cache)
        finally:
            cache.close()
        return {key: {k: val for k, val in result.items()} for key, result in results.items()}

    assert restored(whole, "a.sqlite3") == restored(split, "a.sqlite3")
    assert {key: result["status"] for key, result in restored(split, "b.sqlite3").items()} == dict.fromkeys(
        ["Mink15", "NastEtal20", "Palm78"], "human_verified")
    # Palm78's approval is revoked, for real, in a database that holds it; the row it wrote is
    # then given to each library both ways.
    cache = v.Cache(str(whole.root.parent / "a.sqlite3"), ledger=whole.revocations)
    try:
        written, _ = v.record_revocation(cache, str(whole.bib), "Palm78", "Recorded in error.", "@hubot",
                                         ledger=whole.revocations)
    finally:
        cache.close()
    assert len(written) == 1
    ledger = whole.revocations.read_bytes()
    whole.revocations.unlink()
    trusted = tmp_path / "base-revocations.jsonl"
    trusted.write_bytes(ledger)
    for how in ("trusted file", "the library's ledger"):
        more = ["--trusted-revocations", str(trusted)] if how == "trusted file" else []
        if how == "the library's ledger":
            whole.revocations.write_bytes(ledger)
            split.revocations.write_bytes(ledger)
        one, other = restored(whole, how + ".sqlite3", *more), restored(split, how + ".sqlite3", *more)
        assert {key: result["status"] for key, result in other.items()} == {
            "Mink15": "human_verified", "NastEtal20": "human_verified", "Palm78": "needs_review"}, how
        strip = lambda results: {key: {k: val for k, val in result.items() if k != "revoked_approval"}  # noqa: E731
                                 for key, result in results.items()}
        assert strip(one) == strip(other), how
        assert one["Palm78"]["revoked_approval"]["approval_digest"] == other["Palm78"]["revoked_approval"]["approval_digest"]


# --- folded in ---------------------------------------------------------------------------------


def test_a_whole_snapshot_empties_the_additions_beside_it(tmp_path):
    ws, _ = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    assert len(lines_of(ws.additions)) == 3
    work = tmp_path / "work.sqlite3"
    done = run(ws, "snapshot", str(ws.baseline), database=work)
    assert done.exit_code == 0, done.output
    assert f"{ws.additions}: emptied (the snapshot holds its results now)" in done.output
    assert ws.additions.read_text(encoding="utf-8") == HEADER
    with gzip.open(ws.baseline, "rt", encoding="utf-8") as stream:
        assert sorted(json.loads(line)["key"] for line in list(stream)[1:]) == KEYS
    fresh = tmp_path / "fresh.sqlite3"
    done = run(ws, "restore", str(ws.baseline), database=fresh)
    assert done.exit_code == 0 and done.output.splitlines()[0] == "Restored 5 matching reviews"
    assert statuses(ws, fresh) == dict.fromkeys(KEYS, "metadata_verified")
    # Nothing more to add, and a second whole snapshot says nothing about a file already empty.
    again = run(ws, "snapshot", "--additions-to", str(ws.baseline), database=work)
    assert again.exit_code == 0 and ws.additions.read_text(encoding="utf-8") == HEADER
    assert "emptied" not in run(ws, "snapshot", str(ws.baseline), database=work).output
    # A snapshot written elsewhere leaves the library's additions alone and makes no file.
    done = run(ws, "restore", str(RESULTS), database=work)
    elsewhere = tmp_path / "copy.jsonl.gz"
    assert run(ws, "snapshot", str(elsewhere), database=work).exit_code == 0
    assert not v.additions_beside(elsewhere).exists()


# --- protected ---------------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["the additions", "a link to the additions", "another name of the additions"])
def test_a_report_or_a_whole_snapshot_cannot_be_written_over_the_additions(tmp_path, target):
    ws, _ = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    output = {"the additions": ws.additions, "a link to the additions": tmp_path / "link.jsonl",
              "another name of the additions": tmp_path / "hard.jsonl"}[target]
    if target == "a link to the additions":
        output.symlink_to(ws.additions)
    elif target == "another name of the additions":
        os.link(ws.additions, output)
    kept = ws.additions.read_bytes()
    work = tmp_path / "work.sqlite3"
    refused = "Output path would overwrite the results saved since the snapshot"
    done = CliRunner().invoke(app, ["status", str(ws.bib), "--database", str(work), "--report", str(output)])
    assert done.exit_code == 2 and refused in done.output
    done = run(ws, "snapshot", str(output), database=work)
    assert done.exit_code == 2 and refused in done.output
    done = CliRunner().invoke(app, ["verify", str(ws.bib), "--database", str(work), "--snapshot", str(output),
                                    "--report", str(tmp_path / "report.jsonl"), "--mailto", "nobody@example.org"])
    assert done.exit_code == 2 and refused in done.output
    assert ws.additions.read_bytes() == kept


@pytest.mark.parametrize("target", ["the bibliography", "the database", "the approvals", "the revocations", "the snapshot"])
def test_the_additions_cannot_be_written_over_what_is_protected(tmp_path, target):
    ws, _ = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    work = tmp_path / "work.sqlite3"
    ws.approvals.write_text("", encoding="utf-8")
    ws.revocations.write_text("", encoding="utf-8")
    output = {"the bibliography": ws.bib, "the database": work, "the approvals": ws.approvals,
              "the revocations": ws.revocations, "the snapshot": ws.baseline}[target]
    kept = output.read_bytes()
    done = run(ws, "snapshot", "--additions-to", str(ws.baseline), str(output), database=work)
    assert done.exit_code == 2 and "Output path would overwrite" in done.output, done.output
    if target == "the database":       # opened by the command (its change counter moves), and still the database
        assert output.read_bytes()[:16] == kept[:16] == b"SQLite format 3\x00"
        assert statuses(ws, work) == dict.fromkeys(KEYS, "metadata_verified")
    else:
        assert output.read_bytes() == kept


def test_additions_are_not_made_for_a_file_that_is_no_snapshot_of_this_policy(tmp_path):
    ws, _ = saved(tmp_path, ["AntoEtal24", "NguyEtal19", "Schr00b"], ["Rame72", "YeshEtal21"])
    kept = ws.additions.read_bytes()
    work = tmp_path / "work.sqlite3"
    with gzip.open(ws.baseline, "rt", encoding="utf-8") as stream:
        header, *rows = list(stream)
    other = tmp_path / "other-policy.jsonl.gz"
    with gzip.open(other, "wt", encoding="utf-8") as stream:
        stream.write(v.dumps(dict(json.loads(header), policy="1")) + "\n" + "".join(rows))
    done = run(ws, "snapshot", "--additions-to", str(other), str(ws.additions), database=work)
    assert done.exit_code == 2 and "is not a schema-2 snapshot of the current policy" in done.output
    cut = tmp_path / "cut.jsonl.gz"
    with gzip.open(cut, "wt", encoding="utf-8") as stream:
        stream.write(header + "".join(rows[:-1]))
    done = run(ws, "snapshot", "--additions-to", str(cut), str(ws.additions), database=work)
    assert done.exit_code == 2 and "Incomplete verification snapshot" in done.output
    assert ws.additions.read_bytes() == kept


def test_the_committed_additions_file_is_one_restore_reads():
    """verification/baseline-additions.jsonl of this checkout: the header, and rows that pass
    the check restore makes of them."""
    committed = Path(__file__).resolve().parents[1] / "verification" / "baseline-additions.jsonl"
    rows = v.read_additions(committed)
    v._validated_additions(rows)
    assert [row["key"] for row in rows] == sorted(row["key"] for row in rows)
