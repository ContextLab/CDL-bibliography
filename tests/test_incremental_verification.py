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
