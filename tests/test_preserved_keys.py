"""Every key follows the key rule; there are no per-entry exceptions (user, 2026-10-01:
"I want *every* entry in cdl.bib to follow the same rules. There shouldn't be overrides.").

ChilEtal12 is a 1995 paper whose key had been kept after its year was corrected; it was
renamed ChilEtal95 (verification/key-renames.json). The old key must now be flagged.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
from cdlbib import helpers  # noqa: E402
from cdlbib.helpers import authors2key, check_entries  # noqa: E402


def test_key_follows_corrected_year_with_no_exception():
    target = authors2key("A Childers and B Other and C Third", "1995")
    assert target == "ChilEtal95"
    old = {"ID": "ChilEtal12", "author": "A Childers and B Other and C Third", "year": "1995"}
    assert check_entries("ID", {old["ID"]: old}, [target], verbose=False) == [
        ("ChilEtal12", "ChilEtal12", "ChilEtal95")]
    new = dict(old, ID="ChilEtal95")
    assert check_entries("ID", {new["ID"]: new}, [target], verbose=False) == []


def test_key_check_runs_on_other_fields_too():
    entry = {"ID": "ChilEtal95", "title": "Wrong", "year": "1995"}
    bd = {entry["ID"]: entry}
    assert check_entries("title", bd, ["Correct title"], verbose=False)
    assert check_entries("year", bd, ["1994"], verbose=False)


def test_no_key_override_table():
    assert not (ROOT / "bibcheck" / "key_overrides.json").exists()
    assert not (ROOT / "src" / "cdlbib" / "data" / "key_overrides.json").exists()
    assert not hasattr(helpers, "key_overrides")


def test_renamed_keys_flagged_under_their_old_names(tmp_path):
    """Two of the 29 renames (2026-10-01), checked through check_bib on a small file:
    the old key fails the key check and the rule's key passes."""
    entries = {
        "BorgEtal06": ("SchaEtal06", "J {Schaich Borg} and C Hynes and J {Van Horn} and S Grafton and W Sinnott-Armstrong", "2006"),
        "Thie03": ("ThieSton03", "A Thiele and G Stoner", "2003"),
    }
    def write(use_old):
        text = ""
        for old, (new, author, year) in entries.items():
            text += (f"@article{{{old if use_old else new},\n\tAuthor = {{{author}}},\n"
                     f"\tJournal = {{Test Journal}},\n\tTitle = {{A test title}},\n"
                     f"\tYear = {{{year}}}}}\n\n")
        path = tmp_path / ("old.bib" if use_old else "new.bib")
        path.write_text(text)
        return str(path)
    errors, _ = helpers.check_bib(write(True), verbose=False)
    assert {k: v["ID"] for k, v in errors.items()} == {k: v[0] for k, v in entries.items()}
    errors, _ = helpers.check_bib(write(False), verbose=False)
    assert errors == {}
