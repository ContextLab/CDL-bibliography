"""A predecessor title is corrected using dated evidence, never made an alias."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from correction_proposals import JEP_HISTORY, journal_history_proposal
from verification import assess_candidates, normalize_journal
from test_verification import entry, record, response


def example(entry, record):
    local = deepcopy(entry[1])
    local["fields"].update(journal=JEP_HISTORY["successor"], year="1960", volume="59")
    record.update({"container-title": [JEP_HISTORY["title"]], "ISSN": [JEP_HISTORY["issn"]],
                   "published": {"date-parts": [[1960]]}, "volume": "59"})
    prior = {"status": "needs_review", "candidates": assess_candidates(local["fields"], response(record))}
    return local, prior


def test_history_proposal_changes_only_the_incorrect_successor_title(entry, record):
    local, prior = example(entry, record)
    before = deepcopy((local, prior))
    proposed = journal_history_proposal(local, prior)
    assert proposed and proposed["changes"] == {"journal": {"before": JEP_HISTORY["successor"], "after": JEP_HISTORY["title"]}}
    assert proposed["journal_history"]["sources"]
    assert (local, prior) == before
    assert normalize_journal(JEP_HISTORY["title"]) != normalize_journal(JEP_HISTORY["successor"])


@pytest.mark.parametrize("title", [
    "Journal of Experimental Psychology", "Journal of Experimental Psychology: General",
    "Journal of Experimental Psychology Monograph", "Journal of Experimental Psychology Monograph Supplement",
    "The Quarterly Journal of Experimental Psychology Section A",
    "The Quarterly Journal of Experimental Psychology: Section A",
    "Journal of Physiology-Paris",
])
def test_formatter_preserves_publication_identity(title):
    from helpers import format_journal_name
    assert normalize_journal(format_journal_name(title)) == normalize_journal(title)
    assert format_journal_name(format_journal_name(title)) == format_journal_name(title)


def test_alias_cutting_a_hyphenated_suffix_is_not_applied():
    """journal_key maps 'journal of physiology-paris' to 'journal of physiology', a
    different journal (LachEtal03, wave-4 review). Other aliases still apply."""
    from helpers import format_journal_name
    assert format_journal_name("Journal of Physiology-Paris") == "Journal of Physiology-Paris"
    assert format_journal_name("Journal of Physiology") == "Journal of Physiology"
    # negative control: a hyphen alias that re-punctuates the same journal still applies
    assert format_journal_name("Journal of Experimental Psychology-General") == \
        "Journal of Experimental Psychology: General"


@pytest.mark.parametrize("bad", ["future", "too_old", "future_volume", "wrong_issn", "pages", "title", "hold", "notice", "ambiguous"])
def test_history_cannot_hide_other_identity_problems(entry, record, bad):
    local, prior = example(entry, record)
    if bad == "future": local["fields"]["year"] = "1975"
    elif bad == "too_old": local["fields"]["year"] = "1915"
    elif bad == "future_volume": local["fields"]["volume"] = "104"
    elif bad == "wrong_issn": prior["candidates"][0]["record"]["ISSN"] = ["0096-3445"]
    elif bad in {"pages", "title"}: local["fields"][bad] = "wrong"
    elif bad == "hold": prior["external_evidence"] = [{"issue": "Unresolved edition"}]
    elif bad == "notice": prior["candidates"][0]["record"]["updated-by"] = [{"DOI": "10.1234/notice"}]
    else:
        local["fields"].pop("doi")
        rival = deepcopy(prior["candidates"][0])
        rival["doi"] = rival["record"]["DOI"] = "10.1234/rival"
        prior["candidates"].append(rival)
    assert journal_history_proposal(local, prior) is None
