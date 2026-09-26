"""journal_key.xls aliases must not rename a journal into a different one.

The spreadsheet mapped names onto different journals ('psychonomic science' ->
'psychological science', 'j comp neurol' -> 'journal of computational
neuroscience') and onto misspelled targets ('physiological review',
'international journal of phychophysiology'). bibcheck/journal_key_overrides.json
corrects those rows; the audit is verification/journal-alias-audit-2026-09-26.json.
These tests run the real formatter over the real spreadsheet and override file.
"""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import helpers  # noqa: E402
from helpers import format_journal_name, journal_key, load_key, load_key_overrides  # noqa: E402

OVERRIDES = json.loads((ROOT / "bibcheck" / "journal_key_overrides.json").read_text())["overrides"]


@pytest.mark.parametrize("name, expected", [
    # different journal: the alias used to rename these into another journal
    ("Psychonomic Science", "Psychonomic Science"),                    # was Psychological Science
    ("Psychometric Monographs", "Psychometric Monographs"),            # was Psychometrika
    ("J Comp Neurol", "The Journal of Comparative Neurology"),         # was J Computational Neuroscience
    ("J Comp Physiol", "Journal of Comparative Physiology"),           # was J Computational Physiology
    ("J Comp Physiol A", "Journal of Comparative Physiology {A}"),
    ("J Exp Psychol", "Journal of Experimental Psychology"),           # was JEP: General (1975-)
    ("Journal of the Royal Statistical Society. Series C (Applied Statistics)",
     "Journal of the Royal Statistical Society Series {C}: Applied Statistics"),  # was JOSA
    ("Journal of the Optical Society of America [A]", "Journal of the Optical Society of America {A}"),
    ("Journals of Gerontology", "The Journals of Gerontology"),        # was Journal of Gerontology
    ("Journal of Neural Transmission Supplement", "Journal of Neural Transmission Supplement"),
    ("Proceedings of the Royal Society of London A", "Proceedings of the Royal Society of London Series {A}"),
    ("Learning, Memory", "Learning, Memory"),                          # was Learning and Memory
    ("Learning and Memory: Memory Systems", "Learning and Memory: Memory Systems"),
    ("Proceedings of the NAACL-HLT",
     "Proceedings of the Conference of the North {American} Chapter of the Association for "
     "Computational Linguistics: Human Language Technologies"),
])
def test_alias_no_longer_renames_into_a_different_journal(name, expected):
    assert format_journal_name(name) == expected


@pytest.mark.parametrize("name, expected", [
    ("Physiological Reviews", "Physiological Reviews"),                # was Physiological Review
    ("Int J Psychophysiol", "International Journal of Psychophysiology"),
    ("J Clin Exp Neuropsychol", "Journal of Clinical and Experimental Neuropsychology"),
    ("Psychol Forsch", "Psychologische Forschung"),
    ("Journal of Experimental Psychlogy: Human Perception and Performance",
     "Journal of Experimental Psychology: Human Perception and Performance"),
    ("{Artificial Intelligence and Statistics}", "Artificial Intelligence and Statistics"),
    ("Reliability Engineering \\& Systems Safety", "Reliability Engineering and System Safety"),
    ("Alzheimer Disease \\& Associated Disorders", "Alzheimer Disease and Associated Disorders"),
])
def test_misspelled_alias_targets_are_corrected(name, expected):
    assert format_journal_name(name) == expected


@pytest.mark.parametrize("name, expected", [
    # negative controls: genuine abbreviations and variants still expand
    ("Psychol Sci", "Psychological Science"),
    ("Psychol Rev", "Psychological Review"),
    ("J Neurosci", "The Journal of Neuroscience"),
    ("J Cogn Neurosci", "Journal of Cognitive Neuroscience"),
    ("Trends Cogn Sci", "Trends in Cognitive Sciences"),
    ("Nat Rev Neurosci", "Nature Reviews Neuroscience"),
    ("Learning \\& Memory", "Learning and Memory"),
    ("Perception \\& Psychophysics", "Perception and Psychophysics"),
    ("Journal of Physiology (London)", "Journal of Physiology"),
    ("PNAS", "Proceedings of the National Academy of Sciences, {USA}"),
])
def test_genuine_aliases_still_apply(name, expected):
    assert format_journal_name(name) == expected


def test_every_override_corrects_a_row_the_spreadsheet_still_has():
    raw = load_key("journal_key.xls")
    for row in OVERRIDES:
        assert raw.get(row["source"]) == row["old_target"], row["source"]
        if row["action"] == "remove":
            assert row["source"] not in journal_key
        else:
            assert journal_key[row["source"]] == row["new_target"]
            assert row["new_target"] != row["old_target"] or row["class"] == "misspelled_target"


def test_only_overridden_rows_differ_from_the_spreadsheet():
    raw = load_key("journal_key.xls")

    def target(key, source):
        value = key.get(source)
        return value if isinstance(value, str) else None  # NaN (no alias) == absent

    changed = {s for s in set(raw) | set(journal_key) if target(raw, s) != target(journal_key, s)}
    assert changed == {row["source"] for row in OVERRIDES}


@pytest.mark.parametrize("misspelling", [
    "phychophysiology", "neuropyschology", "intellience", "coysne", "experiment psychology",
    "psychologie forschung", "floweree", "youman's",
])
def test_no_active_target_carries_a_known_misspelling(misspelling):
    assert not [t for t in journal_key.values() if isinstance(t, str) and misspelling in t]
    assert "physiological review" not in journal_key.values()


def test_loader_refuses_an_override_whose_old_target_no_longer_matches(tmp_path):
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"overrides": [{
        "source": "psychol sci", "old_target": "psychonomic science",
        "action": "remove", "new_target": None}]}))
    key = load_key("journal_key.xls")
    with pytest.raises(ValueError, match="psychol sci"):
        load_key_overrides(key, stale)
    assert key["psychol sci"] == "psychological science"


def test_overrides_apply_to_journal_names_only():
    assert helpers.publisher_key == load_key("publisher_key.xls")
    assert helpers.address_key == load_key("address_key.xls")


def test_audit_records_every_override():
    audit = json.loads((ROOT / "verification" / "journal-alias-audit-2026-09-26.json").read_text())
    recorded = {r["source"] for r in audit["wrong_rows"]}
    assert {r["source"] for r in OVERRIDES} <= recorded
