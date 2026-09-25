"""Tests for names.py on real cdl.bib names (no mocks).

    .venv/bin/python -m pytest verification/apply-2026-09-27/test_names.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "bibcheck"))
import pytest  # noqa: E402
from names import split_names, strip_suffix, to_initials  # noqa: E402
import helpers  # noqa: E402


@pytest.mark.parametrize("before,after", [
    ("Roediger, III, H L", "H L Roediger"),
    ("Murdock, Jr, B B", "B B Murdock"),
    ("Engel, Jr, Jerome", "Jerome Engel"),
    ("Buño, Jr, W", "W Buño"),
    ("William H Saufley Jr", "William H Saufley"),
    ("H L Roediger III", "H L Roediger"),
    ("J Jr Engel", "J Engel"),
    ("A Jr Stanc\\^ak", "A Stanc\\^ak"),
    ("W H Jr Warren", "W H Warren"),
    ("M I Posner", "M I Posner"),
])
def test_strip_suffix(before, after):
    assert strip_suffix(before) == after
    assert helpers.reformat_author(after) == after


def test_strip_suffix_rejects_other_comma_forms():
    with pytest.raises(ValueError):
        strip_suffix("Smith, John")


@pytest.mark.parametrize("before,after", [
    ("Jill M Goldstein", "J M Goldstein"),
    ("Liam M O’Brien", "L M O’Brien"),
    ("Ethan S Bromberg-Martin", "E S Bromberg-Martin"),
    ("Guido {van Rossum}", "G {van Rossum}"),
    ("Mohamad N M Saad", "M N M Saad"),
    ("J{\\'o}zsef Janszky", "J Janszky"),
    ("Cédric Anen", "C Anen"),
    ("Jean-Pierre Changeux", "J-P Changeux"),
    ("Ludwig van Beethoven", "L van Beethoven"),
    ("Y-C Chen", "Y-C Chen"),
    ("M E Smith", "M E Smith"),
    ("{Centers for Disease Control and Prevention}", "{Centers for Disease Control and Prevention}"),
    # 2026-09-27 refinements, real cdl.bib names:
    ("Alexander\u00a0G Huth", "A G Huth"),            # HuthEtal12: no-break space
    ("Jean\u2010Philippe Lachaux", "J-P Lachaux"),     # MainEtal07: U+2010 hyphen
    ("Yen-lu Chow", "Y-L Chow"),                        # BambEtal90: lowercase second part
    ("Hans-{J}ochen Heinze", "H-J Heinze"),             # FernEtal98: braced capital
    ("Tom O M Carter", "T O M Carter"),
])
def test_to_initials(before, after):
    new, why = to_initials(before)
    assert why is None and new == after
    assert helpers.reformat_author(new) == new
    assert helpers.last_name(new) == helpers.last_name(before)


@pytest.mark.parametrize("name,reason", [
    ("C Mejia Arenas", "compound"),
    ("Ranxiao Frances Wang", "compound"),
    ("Anna Stigsdotter Neely", "compound"),
    ("B A L Di Leone", "compound"),
    ("{\\'E}mile Durkheim", "accents"),
    ("Shui-I Shih", "mixes"),
    ("a {van Nieuw Amerongen}", "lowercase"),
    ("Kim Y", "initial"),
    ("{\\L}ukasz Langa", "accents"),
    ("Miller E K", "initial"),
    ("J Kevin O'Regan", "compound"),
])
def test_to_initials_holds(name, reason):
    new, why = to_initials(name)
    assert new is None and reason in why


def test_split_names_keeps_braced_and():
    assert split_names("{Centers for Disease Control and Prevention} and J Smith") == [
        "{Centers for Disease Control and Prevention}", "J Smith"]
    assert split_names("A B and C D and E F") == ["A B", "C D", "E F"]
