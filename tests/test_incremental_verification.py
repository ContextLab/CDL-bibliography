"""Behavioral tests for content caching, upgrades, and incremental gates."""

import gzip
import json
from pathlib import Path
import sys

import pytest
from typer.testing import CliRunner

from cdlbib import verification as v
from cdlbib.verification_cli import app, select_keys


BIB = "@book{Old, title={Old}, author={Alice Smith}, year={2020}, publisher={Press}}"
APPROVAL = {
    "status": "human_verified",
    "human_review": {"reviewer": "Reviewer", "source": "Book", "notes": "Checked"},
}


def setup_cache(tmp_path):
    bib = tmp_path / "test.bib"
    bib.write_text(BIB)
    cache = v.Cache(tmp_path / "cache.sqlite3")
    entry = v.load_entries(bib)["Old"]
    result = cache.put(bib, entry, APPROVAL)
    return bib, cache, entry, result


def test_key_rename_reuses_review_without_rewriting_audit(tmp_path):
    bib, cache, entry, original = setup_cache(tmp_path)
    bib.write_text(BIB.replace("{Old,", "{New,"))
    renamed = v.load_entries(bib)["New"]
    assert renamed["fingerprint"] == entry["fingerprint"]
    result = v.current_results(bib, cache)["New"]
    assert result == dict(original, key="New")
    assert cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 1
    assert (
        json.loads(cache.db.execute("SELECT result FROM reviews").fetchone()[0])["key"]
        == "Old"
    )
    # Only the key token is excluded, not occurrences of its text in fields.
    bib.write_text(BIB.replace("Old", "New"))
    assert v.current_results(bib, cache)["New"]["status"] == "pending"
    cache.close()


@pytest.mark.parametrize(
    "before,after",
    [
        ("@book", "@Book"),
        ("{Old,", "{ Old,"),
        ("title=", "title ="),
        ("{2020}", "{2021}"),
        ("author={Alice Smith}", "author={A Smith}"),
        ("publisher={Press}", "publisher={Press}, note={Note}"),
        ("title={Old}, author={Alice Smith}", "author={Alice Smith}, title={Old}"),
    ],
)
def test_every_other_raw_entry_edit_invalidates(tmp_path, before, after):
    bib, cache, _, _ = setup_cache(tmp_path)
    bib.write_text(BIB.replace(before, after))
    assert v.current_results(bib, cache)["Old"]["status"] == "pending"
    cache.close()


def test_legacy_database_migrates_exact_content_and_preserves_time(tmp_path):
    bib, cache, entry, _ = setup_cache(tmp_path)
    cache.db.execute("DELETE FROM reviews")
    cache.db.commit()
    legacy = dict(entry, fingerprint=entry["legacy_fingerprint"])
    old = cache.put(bib, legacy, APPROVAL)
    upgraded = cache.get(bib, entry)
    assert upgraded["checked_at"] == old["checked_at"]
    assert upgraded["fingerprint"] == entry["fingerprint"]
    assert upgraded["fingerprint_migration"]["fingerprint"] == old["fingerprint"]
    bib.write_text(BIB.replace("{Old,", "{New,"))
    assert v.current_results(bib, cache)["New"]["status"] == "human_verified"
    assert cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 2
    cache.close()


def test_latest_content_decision_wins_after_rename(tmp_path):
    bib, cache, old, _ = setup_cache(tmp_path)
    bib.write_text(BIB.replace("{Old,", "{New,"))
    new = v.load_entries(bib)["New"]
    cache.put(bib, new, {"status": "needs_review"})
    assert cache.get(bib, old)["status"] == "needs_review"
    cache.close()


def test_migration_cannot_overwrite_concurrent_review(tmp_path, monkeypatch):
    bib, cache, entry, _ = setup_cache(tmp_path)
    legacy = dict(entry, fingerprint=entry["legacy_fingerprint"])
    cache.put(bib, legacy, APPROVAL)
    other = v.Cache(cache.path)
    store = cache.store

    def concurrent_store(*args, **kwargs):
        other.put(bib, entry, {"status": "needs_review"})
        return store(*args, **kwargs)

    monkeypatch.setattr(cache, "store", concurrent_store)
    assert cache.get(bib, entry)["status"] == "needs_review"
    assert other.get(bib, entry)["status"] == "needs_review"
    cache.close()
    other.close()


def test_legacy_snapshot_migration_then_portable_rename(tmp_path):
    bib, cache, entry, _ = setup_cache(tmp_path)
    old_snapshot = tmp_path / "legacy.gz"
    result = dict(
        APPROVAL, key="Old", fingerprint=entry["legacy_fingerprint"], policy=v.POLICY
    )
    with gzip.open(old_snapshot, "wt") as stream:
        stream.write(json.dumps({"schema": 1, "policy": v.POLICY, "entries": 1}) + "\n")
        stream.write(json.dumps(result) + "\n")
    migrated = v.Cache(tmp_path / "migrated.sqlite3")
    assert v.import_snapshot(bib, migrated, old_snapshot) == 1
    portable = tmp_path / "portable.gz"
    v.export_snapshot(bib, migrated, portable)
    clone = tmp_path / "clone.bib"
    clone.write_text(BIB.replace("{Old,", "{New,"))
    restored = v.Cache(tmp_path / "restored.sqlite3")
    assert v.import_snapshot(clone, restored, portable) == 1
    assert v.current_results(clone, restored)["New"]["status"] == "human_verified"
    clone.write_text(clone.read_text().replace("{2020}", "{2021}"))
    assert v.import_snapshot(clone, restored, portable) == 0
    assert v.current_results(clone, restored)["New"]["status"] == "pending"
    for db in (cache, migrated, restored):
        db.close()


def test_changed_content_selection_includes_inherited_and_string_edits(tmp_path):
    base = tmp_path / "base.bib"
    base.write_text(
        '@string{pub="Press"}\n@book{Parent,title={Parent},publisher=pub}\n@inbook{Child,title={Child},crossref={Parent}}'
    )
    bib = tmp_path / "head.bib"
    bib.write_text(base.read_text().replace("title={Parent}", "title={Changed}"))
    assert select_keys(bib, against=base) == {"Parent", "Child"}
    bib.write_text(base.read_text().replace('pub="Press"', 'pub="Other"'))
    assert select_keys(bib, against=base) == {"Parent", "Child"}
    bib.write_text(base.read_text().replace("{Child,", "{Renamed,"))
    assert select_keys(bib, against=base) == set()


def test_incremental_cli_checks_new_and_edited_but_skips_legacy_backlog(
    tmp_path, monkeypatch
):
    bib, cache, _, _ = setup_cache(tmp_path)
    base = tmp_path / "base.bib"
    # The old unresolved backlog must not hide failures in added/edited entries.
    base.write_text(BIB + "\n@book{Backlog,title={Unknown}}")
    bib.write_text(
        base.read_text().replace("{Old,", "{Renamed,") + "\n@book{Added,title={New}}"
    )
    cache.put(bib, v.load_entries(bib)["Backlog"], {"status": "needs_review"})
    calls = []

    def check(entry, client):
        calls.append(entry["key"])
        return {"status": "metadata_verified"}

    monkeypatch.setattr(v, "verify_entry", check)
    command = [
        "verify",
        str(bib),
        "--against",
        str(base),
        "--database",
        str(cache.path),
    ]
    runner = CliRunner()
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    assert calls == ["Added"]
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    assert calls == ["Added"]
    bib.write_text(bib.read_text().replace("title={Old}", "title={Changed}"))
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    assert calls == ["Added", "Renamed"]
    cache.close()


def test_offline_cached_run_needs_no_contact_or_provider(tmp_path, monkeypatch):
    bib, cache, _, _ = setup_cache(tmp_path)
    monkeypatch.delenv("CROSSREF_MAILTO", raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("Cached entry was checked again")

    monkeypatch.setattr(v, "verify_entry", forbidden)
    result = CliRunner().invoke(
        app, ["verify", str(bib), "--database", str(cache.path)]
    )
    assert result.exit_code == 0, result.output
    assert "network requests: 0" in result.output
    cache.close()


def test_new_unresolved_and_provider_failure_fail_gate(tmp_path, monkeypatch):
    bib, cache, _, _ = setup_cache(tmp_path)
    base = tmp_path / "base.bib"
    base.write_text(BIB)
    bib.write_text(BIB + "\n@book{New,title={Uncertain}}")
    command = [
        "verify",
        str(bib),
        "--against",
        str(base),
        "--database",
        str(cache.path),
    ]
    monkeypatch.setattr(v, "verify_entry", lambda *args: {"status": "needs_review"})
    assert CliRunner().invoke(app, command).exit_code == 1

    def failure(*args):
        raise v.ProviderError("Unavailable")

    monkeypatch.setattr(v, "verify_entry", failure)
    assert CliRunner().invoke(app, command + ["--retry-unresolved"]).exit_code == 2
    assert v.current_results(bib, cache)["New"]["status"] == "provider_error"
    cache.close()


def test_edit_during_run_cannot_pass(tmp_path, monkeypatch):
    bib, cache, _, _ = setup_cache(tmp_path)
    base = tmp_path / "base.bib"
    base.write_text(BIB)
    bib.write_text(BIB + "\n@book{New,title={New}}")

    def edit(*args):
        bib.write_text(bib.read_text().replace("title={Old}", "title={Changed}"))
        return {"status": "metadata_verified"}

    monkeypatch.setattr(v, "verify_entry", edit)
    result = CliRunner().invoke(
        app, ["verify", str(bib), "--against", str(base), "--database", str(cache.path)]
    )
    assert result.exit_code == 1, result.output
    assert "pending=1" in result.output
    cache.close()


@pytest.mark.parametrize("source", ["europepmc", "pmc-jats"])
def test_secondary_source_approvals_survive_snapshot_restore(tmp_path, source):
    bib, cache, entry, _ = setup_cache(tmp_path)
    candidate = {
        "source": source,
        "doi": "10.1234/example",
        "issues": [],
        "evidence": {"title": {"match": True}},
        "raw_record": {"id": "123"},
        "raw_xml": "<article/>",
        "medline_record": {"id": "123"},
    }
    cache.put(
        bib,
        entry,
        {
            "status": "metadata_verified",
            "accepted_source": source,
            "accepted_doi": candidate["doi"],
            "candidates": [candidate],
        },
    )
    snapshot = tmp_path / "snapshot.gz"
    v.export_snapshot(bib, cache, snapshot)
    restored = v.Cache(tmp_path / "restored.sqlite3")
    assert v.import_snapshot(bib, restored, snapshot) == 1
    assert restored.get(bib, entry)["accepted_source"] == source
    cache.close()
    restored.close()


def test_auto_review_never_recompares_current_approved_entry(tmp_path, monkeypatch):
    from cdlbib import auto_review

    bib, cache, entry, _ = setup_cache(tmp_path)
    cache.put(bib, entry, {"status": "metadata_verified"})

    def forbidden(*args, **kwargs):
        pytest.fail("Current approval was reassessed")

    monkeypatch.setattr(auto_review, "reassess", forbidden)
    auto_review.run_auto_review(bib, cache, tmp_path / "report.jsonl")
    cache.close()


def test_keys_restrict_all_automatic_layers(tmp_path, monkeypatch):
    from cdlbib import auto_review
    from cdlbib import fulltext_review

    bib, cache, entry, _ = setup_cache(tmp_path)
    cache.put(bib, entry, {"status": "needs_review"})

    def forbidden(*args, **kwargs):
        pytest.fail("Unselected entry was reassessed")

    monkeypatch.setattr(auto_review, "reassess", forbidden)
    auto_review.run_auto_review(bib, cache, tmp_path / "report.jsonl", keys=set())
    fulltext_review.run_fulltext_review(
        bib, cache, None, tmp_path / "report.jsonl", keys=set()
    )
    cache.close()


def test_resolver_upgrade_revisits_unresolved_once_without_network(
    tmp_path, monkeypatch
):
    from cdlbib import auto_review

    bib, cache, entry, _ = setup_cache(tmp_path)
    cache.put(
        bib,
        entry,
        {
            "status": "needs_review",
            "candidates": [],
            "attempts": [],
            "auto_review": {"policy": v.POLICY, "epmc_checked": True},
        },
    )
    calls = []
    original = auto_review.reassess

    def tracked(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(auto_review, "reassess", tracked)
    auto_review.run_auto_review(bib, cache, tmp_path / "report.jsonl")
    first = cache.get(bib, entry)
    auto_review.run_auto_review(bib, cache, tmp_path / "report.jsonl")
    assert len(calls) == 1
    assert cache.get(bib, entry) == first
    assert first["auto_review"]["epmc_checked"] is True
    monkeypatch.setattr(
        auto_review, "RESOLVER_VERSION", auto_review.RESOLVER_VERSION + 1
    )
    auto_review.run_auto_review(bib, cache, tmp_path / "report.jsonl")
    assert len(calls) == 2
    cache.close()


@pytest.mark.parametrize("command", ["verify", "status"])
def test_report_cannot_overwrite_comparison_base(tmp_path, command):
    bib, cache, _, _ = setup_cache(tmp_path)
    base = tmp_path / "base.bib"
    base.write_text(BIB)
    result = CliRunner().invoke(
        app,
        [
            command,
            str(bib),
            "--database",
            str(cache.path),
            "--against",
            str(base),
            "--report",
            str(base),
        ],
    )
    assert result.exit_code == 2, result.output
    assert base.read_text() == BIB
    cache.close()


def test_a_normalized_text_is_remembered_and_a_refused_one_refused_again():
    assert v.normalized("The {\\'E}cole  Normale") == v.normalized("The {\\'E}cole  Normale") == "the école normale"
    assert v.normalized(1990) == "1990"
    for _ in range(2):
        with pytest.raises(ValueError, match="Math or semantic markup"):
            v.normalized("$x$")
        with pytest.raises(ValueError, match="Unknown LaTeX command"):
            v.normalized("\\foo{x}")


def test_read_once_parses_a_copy_with_the_same_bytes_once_and_a_changed_file_again(tmp_path):
    bib, base = tmp_path / "test.bib", tmp_path / "base.bib"
    bib.write_text(BIB)
    base.write_text(BIB)
    plain = v.load_entries(bib)
    files = (str(bib.resolve()), str(base.resolve()))
    with v.read_once() as store:
        first, copy = v.load_entries(bib), v.load_entries(base)
        assert first == copy == plain
        parses = [found for name, found in store.items() if name[0] in files]
        assert len(parses) == 2 and parses[0] is parses[1]            # one parse serves both files
        first["Old"]["fields"]["title"] = "spoiled by the caller"      # each caller has a copy of its own
        assert v.load_entries(bib) == plain
        base.write_text(BIB.replace("{2020}", "{920}"))                # the base changes: parsed again
        changed = v.load_entries(base)
        assert changed["Old"]["fields"]["year"] == "920" and changed["Old"]["fingerprint"] != plain["Old"]["fingerprint"]
        assert v.load_entries(bib) == plain                            # and the other file's parse stays
        bib.write_text(BIB.replace("{2020}", "{920}"))                 # now the two have the same bytes again
        assert v.load_entries(bib) == changed
        assert len([name for name in store if name[0] in files]) == 2 and len(store) == 3   # the first text's parse was let go
    assert v.load_entries(base) == changed


def test_read_once_by_content_sees_an_edit_that_keeps_the_size_and_the_modification_time(tmp_path):
    import os
    bib, base = tmp_path / "test.bib", tmp_path / "base.bib"
    bib.write_text(BIB)
    base.write_text(BIB)
    plain = v.load_entries(bib)
    files = (str(bib.resolve()), str(base.resolve()))

    def edit_unseen(text):
        """Another text of the same size, with the file's times put back as they were."""
        before = bib.stat()
        bib.write_text(text)
        os.utime(bib, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = bib.stat()
        assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)

    with v.read_once(by_content=True) as store:
        assert v.load_entries(bib) == v.load_entries(base) == plain
        parses = [found for name, found in store.items() if name[0] in files]
        assert len(parses) == 2 and parses[0] is parses[1]            # one parse serves both files
        edit_unseen(BIB.replace("{2020}", "{1920}"))
        changed = v.load_entries(bib)
        assert changed["Old"]["fields"]["year"] == "1920" and changed["Old"]["fingerprint"] != plain["Old"]["fingerprint"]
        assert v.load_entries(base) == plain
        with v.read_once():                                            # a block inside reads the same way
            edit_unseen(BIB.replace("{2020}", "{1820}"))
            assert v.load_entries(bib)["Old"]["fields"]["year"] == "1820"
        edit_unseen(BIB)
        assert v.load_entries(bib) == plain
        assert len([name for name in store if name[0] in files]) == 2 and len(store) == 3
    # Control: by the file's time and size (the plain block), that same edit is not seen.
    with v.read_once():
        assert v.load_entries(bib) == plain
        edit_unseen(BIB.replace("{2020}", "{1920}"))
        assert v.load_entries(bib) == plain
    assert v.load_entries(bib) == changed


def _written(path):
    """What tells one writing of a file from the next: each is a new file moved into place."""
    found = path.stat()
    return found.st_ino, found.st_mtime_ns, found.st_size


def test_unchanged_outputs_are_kept_only_while_nothing_they_are_made_from_changes(tmp_path):
    import os
    bib, cache, entry, original = setup_cache(tmp_path)
    report, snapshot = tmp_path / "out" / "report.jsonl", tmp_path / "out" / "snapshot.jsonl.gz"

    def read():
        rows = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()]
        with gzip.open(snapshot, "rt", encoding="utf-8") as stream:
            saved = [json.loads(line) for line in stream][1:]
        assert [(r["key"], r["status"]) for r in rows] == [(r["key"], r["status"]) for r in saved]
        return {r["key"]: r["status"] for r in rows}

    def both():
        results = v.write_report(bib, cache, report)
        assert v.export_snapshot(bib, cache, snapshot) == results == v.current_results(bib, cache)
        assert {key: r["status"] for key, r in results.items()} == read()   # what is handed back is what the files say
        return results, _written(report), _written(snapshot)

    # Outside the block every call writes both files anew.
    _, first_report, first_snapshot = both()
    _, again_report, again_snapshot = both()
    assert again_report != first_report and again_snapshot != first_snapshot

    with v.unchanged_outputs_kept():
        results, kept_report, kept_snapshot = both()
        assert results == {"Old": original}
        results["Old"] = "spoiled by the caller"                           # each caller has a mapping of its own
        for _ in range(2):                                                 # nothing changed: nothing is written
            results, same_report, same_snapshot = both()
            assert results == {"Old": original} and (same_report, same_snapshot) == (kept_report, kept_snapshot)

        # A result stored through this connection.
        stored = cache.put(bib, entry, {"status": "needs_review", "issues": ["Checked again"]})
        results, new_report, new_snapshot = both()
        assert results == {"Old": stored} and read() == {"Old": "needs_review"}
        assert new_report != kept_report and new_snapshot != kept_snapshot
        assert both()[1:] == (new_report, new_snapshot)

        # A result stored through another connection (another process using the database).
        other = v.Cache(cache.path)
        approved = other.put(bib, entry, APPROVAL)
        other.close()
        results, newer_report, newer_snapshot = both()
        assert results == {"Old": approved} and read() == {"Old": "human_verified"}
        assert newer_report != new_report and newer_snapshot != new_snapshot
        assert both()[1:] == (newer_report, newer_snapshot)

        # The bibliography edited: the entry is another text, with no result. (Told by the
        # file's bytes: this edit keeps its size, and its times are put back.)
        times = bib.stat()
        bib.write_text(BIB.replace("{2020}", "{1920}"))
        os.utime(bib, ns=(times.st_atime_ns, times.st_mtime_ns))
        assert (bib.stat().st_mtime_ns, bib.stat().st_size) == (times.st_mtime_ns, times.st_size)
        results, edited_report, edited_snapshot = both()
        assert results["Old"]["status"] == "pending" and read() == {"Old": "pending"}
        assert edited_report != newer_report and edited_snapshot != newer_snapshot
        assert both()[1:] == (edited_report, edited_snapshot)

        # A row for that text added to the approvals ledger this cache reads.
        edited = v.load_entries(bib)["Old"]
        review = {"reviewer": "@octocat", "source": "https://example.org/book", "note": "Compared every field.",
                  "github_login": "octocat", "github_id": 583231}
        row = {"key": "Old", "fingerprint": edited["fingerprint"], "human_review": review,
               "approval_digest": v.approval_digest(review), "approved_at": v.now(), "policy": v.POLICY}
        assert v.valid_shared_approval(row)
        ledger = v.approval_ledger()
        assert ledger is not None and ledger.parent == tmp_path and not ledger.exists()
        ledger.write_text(v.dumps(row) + "\n", encoding="utf-8")
        results, ledger_report, ledger_snapshot = both()
        assert results["Old"]["status"] == "human_verified" and read() == {"Old": "human_verified"}
        assert ledger_report != edited_report and ledger_snapshot != edited_snapshot
        assert both()[1:] == (ledger_report, ledger_snapshot)

        # Its revocation added to the revocation ledger.
        revocation = {"key": "Old", "fingerprint": row["fingerprint"], "approval": review,
                      "approval_digest": row["approval_digest"], "approval_checked_at": row["approved_at"],
                      "revoked_at": v.now(), "revoked_by": "@hubot", "reason": "Recorded in error."}
        assert v.valid_revocation(revocation)
        Path(v.REVOCATION_LEDGER).write_text(v.dumps(revocation) + "\n", encoding="utf-8")
        results, revoked_report, revoked_snapshot = both()
        assert results["Old"]["status"] == "pending" and read() == {"Old": "pending"}
        assert revoked_report != ledger_report and revoked_snapshot != ledger_snapshot
        assert both()[1:] == (revoked_report, revoked_snapshot)

        # A file that is gone, or was replaced by other hands, is written again.
        report.unlink()
        snapshot.write_bytes(b"not a snapshot")
        results, back_report, back_snapshot = both()
        assert results["Old"]["status"] == "pending" and back_report != revoked_report and back_snapshot != revoked_snapshot

        # Indexing the history writes its checkpoints and changes no result: nothing is written.
        cache.index_notices()
        assert both()[1:] == (back_report, back_snapshot)

        # Results of entries the caller read itself are the results of those entries.
        earlier = v.load_entries(bib)
        bib.write_text(BIB)
        assert v.current_results(bib, cache, earlier)["Old"]["status"] == "pending"
        assert v.current_results(bib, cache)["Old"] == approved
        assert v.current_results(bib, cache, earlier)["Old"]["status"] == "pending"

    # After the block every call writes again.
    _, after_report, _ = both()
    assert both()[1] != after_report
    cache.close()
