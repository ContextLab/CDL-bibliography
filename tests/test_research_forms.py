"""Tests for bibcheck/research_forms.py (the research post-check's house normalisers that
research_route uses to re-check saved approvals).

Copied unchanged from tests/test_research_postcheck.py, which tests the whole post-check
(verification/research-2026-09-25/postcheck.py) and lives with it in the archive repository
ContextLab/CDL-bibliography-stacks. Values are frozen in each test; no file or network is read.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import research_forms as pc  # noqa: E402


def test_house_names_unchanged_list():
    assert pc.normalise_names("{Food and Drug Administration}")[0] == "{Food and Drug Administration}"
    assert pc.split_names("A B Smith and {Food and Drug Administration}") == ["A B Smith", "{Food and Drug Administration}"]


def test_formatter_never_lowercases_inner_capitals():
    assert pc.guarded("O'Reilly", "O'reilly") is None
    assert pc.guarded("Erlbaum", "Erlbaum") == "Erlbaum"


def test_ordinals():
    assert pc.normalise_ordinals("Proceedings of the 53rd Annual Meeting")[0] == \
        "Proceedings of the 53\\textsuperscript{rd} Annual Meeting"
    assert pc.normalise_ordinals("22\\textsuperscript{th} meeting")[0] == "22\\textsuperscript{nd} meeting"
    assert pc.normalise_ordinals("11th and 112th")[0] == "11\\textsuperscript{th} and 112\\textsuperscript{th}"
    assert pc.normalise_ordinals("\\url{https://x.org/1st}")[0] == "\\url{https://x.org/1st}"
    assert pc.normalise_edition("Second")[0] == "2\\textsuperscript{nd}"
    assert pc.normalise_edition("2nd ed.")[0] == "2\\textsuperscript{nd}"
    assert pc.normalise_edition("Rev. and expanded")[0] == "Rev. and expanded"


def test_issue_ranges_and_pages():
    assert pc.normalise_number("3-4")[0] == "3--4"
    assert pc.normalise_number("5–6")[0] == "5--6"
    assert pc.normalise_number("6407")[0] == "6407"
    assert pc.normalise_pages("347-76")[0] == "347--376"
    assert pc.normalise_pages("31--39")[0] == "31--39"


def test_proceedings_booktitle_year():
    assert pc.normalise_booktitle("Proceedings of the 2022 Conference of the North {American} Chapter")[0] == \
        "Proceedings of the Conference of the North {American} Chapter"
    assert pc.normalise_booktitle("Advances in Neural Information Processing Systems 13 (2000)")[0] == \
        "Advances in Neural Information Processing Systems 13"
    assert pc.normalise_booktitle("Handbook of Data Visualization")[0] == "Handbook of Data Visualization"
    assert pc.normalise_booktitle("Memory in 2000: A Retrospective")[0] == "Memory in 2000: A Retrospective"

