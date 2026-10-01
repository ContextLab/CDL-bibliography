"""Two name-parsing defects found by the 2026-09-30 surname scan, fixed 2026-09-30.

1. A tilde accent outside braces (``I L Pi\\~{n}a``, PollEtal00; ``A N\\'{u}\\~{n}ez``,
   NuneEtal87): BibTeX name splitting reads ``~`` as a space, so bibtexparser's splitname
   returned the surname ``{n}a``. ``name_parsing.splitname`` braces the accent first.
2. ``\\aa`` (``E Id{\\aa}s``, MagnEtal98): ``verification.normalized`` rejected it as an
   unknown LaTeX command.

Inputs are frozen here: the author fields as cdl.bib has them on 2026-09-30, and the
Crossref author records (given/family) fetched 2026-09-30 from
https://api.crossref.org/works/<doi>. No test reads the live cdl.bib.
"""
from pathlib import Path
import sys

from bibtexparser.customization import splitname as bibtex_splitname
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from name_parsing import protect_tilde_accents, splitname  # noqa: E402
from verification import author_evidence, normalized  # noqa: E402

POLLOCK = ("M L Pollock and B A Franklin and G J Balady and B L Chaitman and J L Fleg and "
           "B Fletcher and M Limacher and I L Pi\\~{n}a and R A Stein and M Williams and T Bazzarre")
POLLOCK_CROSSREF = [  # 10.1161/01.cir.101.7.828
    ("Michael L.", "Pollock"), ("Barry A.", "Franklin"), ("Gary J.", "Balady"),
    ("Bernard L.", "Chaitman"), ("Jerome L.", "Fleg"), ("Barbara", "Fletcher"),
    ("Marian", "Limacher"), ("Ileana L.", "Piña"), ("Richard A.", "Stein"),
    ("Mark", "Williams"), ("Terry", "Bazzarre")]
NUNEZ = "A N\\'{u}\\~{n}ez and E Garc\\'{i}a-Austt and W Bu{\\~n}o"
MAGNUSSEN = "S Magnussen and E Id{\\aa}s and S H Myhre"
MAGNUSSEN_CROSSREF = [  # 10.1037/0096-1523.24.3.707
    ("Svein", "Magnussen"), ("Espen", "Idås"), ("Steinar Holst", "Myhre")]


def people(pairs):
    return [{"given": g, "family": f} for g, f in pairs]


def surname(name):
    parts = splitname(name, strict_mode=True)
    return " ".join(parts["von"] + parts["last"])


def test_the_defect_is_real_in_bibtexparser():
    # Frozen evidence of defect 1: the library's splitter cuts the surname at the tilde.
    assert bibtex_splitname("I L Pi\\~{n}a", strict_mode=True)["last"] == ["{n}a"]
    assert bibtex_splitname("A N\\'{u}\\~{n}ez", strict_mode=True)["last"] == ["{n}ez"]


def test_tilde_accent_stays_in_the_surname():
    assert splitname("I L Pi\\~{n}a")["last"] == ["Pi{\\~{n}}a"]
    assert splitname("I L Pi\\~{n}a")["first"] == ["I", "L"]
    assert normalized(surname("I L Pi\\~{n}a")) == "piña"
    assert normalized(surname("A N\\'{u}\\~{n}ez")) == "núñez"
    assert splitname("A N\\'{u}\\~{n}ez")["first"] == ["A"]
    # the unbraced-argument form
    assert normalized(surname("I L Pi\\~na")) == "piña"


def test_tilde_negative_controls():
    # A bare ~ is a tie (a space) and still separates words.
    assert splitname("J~Smith") == {"first": ["J"], "last": ["Smith"], "von": [], "jr": []}
    # An accent already inside braces is left exactly as written.
    for name in ("J Go{\\~n}i", "W Bu{\\~n}o", "C Perpi{\\~n}{\\'a}", "{\\~N}u{\\~n}ez"):
        assert protect_tilde_accents(name) == name
        assert splitname(name) == bibtex_splitname(name, strict_mode=True)
    # Names without a tilde accent are split exactly as before.
    for name in ("E Garc\\'{i}a-Austt", "M P {van den Heuvel}", "S Magnussen", "J {Hart Jr}"):
        assert splitname(name) == bibtex_splitname(name, strict_mode=True)
    # A different surname still differs after the fix.
    assert normalized(surname("I L Pi\\~{n}a")) != normalized("Pina")


def test_pollock_authors_match_crossref_after_the_fix():
    ok, reason = author_evidence(POLLOCK, people(POLLOCK_CROSSREF))
    assert ok, reason


def test_pollock_negative_control_wrong_surname():
    wrong = people(POLLOCK_CROSSREF)
    wrong[7] = {"given": "Ileana L.", "family": "Pina"}
    ok, reason = author_evidence(POLLOCK, wrong)
    assert not ok and reason == "Author surnames/order differ"


def test_nunez_now_parses_and_crossref_garbling_still_differs():
    # Crossref's record for NuneEtal87 prints "Nu´n˜ez" (spacing accents); that is a real
    # difference the checker must still report, not the parsing defect.
    crossref = people([("Angel", "Nu´n˜ez"), ("Elio", "Garci´a-Austt"), ("Washington", "Bun˜o")])
    ok, reason = author_evidence(NUNEZ, crossref)
    assert not ok and reason == "Author surnames/order differ"
    fixed = people([("Angel", "Núñez"), ("Elio", "García-Austt"), ("Washington", "Buño")])
    ok, reason = author_evidence(NUNEZ, fixed)
    assert ok, reason


def test_aa_is_a_known_accent():
    assert normalized("Id{\\aa}s") == "idås"
    assert normalized("S-{\\AA} Christianson") == "s-å christianson"
    ok, reason = author_evidence(MAGNUSSEN, people(MAGNUSSEN_CROSSREF))
    assert ok, reason


def test_aa_negative_controls():
    # Unknown commands are still rejected, including near misses of \aa.
    for value in ("Id{\\aaa}s", "Id{\\ab}s", "\\foo bar"):
        with pytest.raises(ValueError, match="Unknown LaTeX command"):
            normalized(value)
    # A different surname still differs.
    wrong = people(MAGNUSSEN_CROSSREF)
    wrong[1] = {"given": "Espen", "family": "Idas"}
    ok, reason = author_evidence(MAGNUSSEN, wrong)
    assert not ok and reason == "Author surnames/order differ"
