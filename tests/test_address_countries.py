"""The address formatter never adds a country the source does not print.

User decision 2026-09-26 (verification/resolution-plan-2026-09-22/README.md): a country
is dropped from an entry's address when the source does not print it. address_key.xls
mapped bare cities onto city + country ('london' -> 'london, uk', 'paris' -> 'paris, fr'),
so check_bib rejected Galt83/Yate66 'London' and BancEtal65 'Paris' (wave-1 held rows,
verification/apply-2026-09-26-wave1/). Entries are frozen here from cdl.bib at 03b8abd;
the live bibliography is never read.
"""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import helpers  # noqa: E402

GALT83 = """@book{Galt83,
\tAddress = {%s},
\tAuthor = {F Galton},
\tPublisher = {Macmillan},
\tTitle = {Inquiries into human faculty and its development},
\tYear = {1883}}
"""
YATE66 = """@book{Yate66,
\tAddress = {%s},
\tAuthor = {F A Yates},
\tPublisher = {Routledge and Kegan Paul},
\tTitle = {The art of memory},
\tYear = {1966}}
"""
BANCETAL65 = """@book{BancEtal65,
\tAddress = {%s},
\tAuthor = {J Bancaud and J Talairach and A Bonis},
\tPublisher = {Masson},
\tTitle = {La st\\'{e}r\\'{e}o-\\'{e}lectroenc\\'{e}phalographie dans l'\\'{e}pilepsie},
\tYear = {1965}}
"""
CHRI92 = """@book{Chri92,
\tAddress = {%s},
\tAuthor = {Sven-{\\AA}ke Christianson},
\tEditor = {S-{\\AA} Christianson},
\tPublisher = {Erlbaum},
\tTitle = {The handbook of emotion and memory: research and theory},
\tYear = {1992}}
"""


def fmt(address):
    return helpers.format_journal_name(address, key=helpers.address_key,
                                       force_caps=helpers.address_codes)


def check(tmp_path, raw):
    path = tmp_path / "a.bib"
    path.write_text(raw, encoding="utf-8")
    return helpers.check_bib(str(path), verbose=False)[0]


@pytest.mark.parametrize("address", [
    "London", "Paris", "Oxford", "Heidelberg", "Leipzig", "Stuttgart", "Lausanne", "Trieste",
    "New Jersey",
])
def test_bare_city_gains_no_country(address):
    # Each of these had an address_key row adding a country ('paris' -> 'paris, fr').
    assert fmt(address) == address


def test_alias_spelling_fix_still_applies_without_the_country():
    assert fmt("Heidleberg") == "Heidelberg"  # was 'Heidelberg, Germany'
    assert fmt("NJ") == "New Jersey"  # was 'New Jersey, USA'


@pytest.mark.parametrize("address, house", [
    ("London, {UK}", "London, {UK}"),
    ("Paris, {FR}", "Paris, {FR}"),
    ("Hove, {UK}", "Hove, {UK}"),
    # an existing, printed country still takes the house form
    ("London, England", "London, {UK}"),
    ("Oxford, U. K.", "Oxford, {UK}"),
    ("Berlin, Germany", "Berlin"),
])
def test_printed_country_keeps_house_form(address, house):
    assert fmt(address) == house


@pytest.mark.parametrize("address, house", [
    ("Hillsdale, {NJ}", "Hillsdale, {NJ}"),
    ("Cambridge, {MA}", "Cambridge, {MA}"),
    ("Boston", "Boston, {MA}"),  # US state codes are a separate house convention
    ("Hillsdale, N. J.", "Hillsdale, {NJ}"),
])
def test_us_state_codes_unchanged(address, house):
    assert fmt(address) == house


def test_journal_titles_are_not_addresses():
    # "USA" is part of the PNAS title; the country guard applies to addresses only.
    assert helpers.format_journal_name("PNAS") == "Proceedings of the National Academy of Sciences, {USA}"


@pytest.mark.parametrize("template, key, address", [
    (GALT83, "Galt83", "London"),
    (YATE66, "Yate66", "London"),
    (BANCETAL65, "BancEtal65", "Paris"),
])
def test_wave1_held_rows_pass_check_bib(tmp_path, monkeypatch, template, key, address):
    monkeypatch.chdir(ROOT)
    assert check(tmp_path, template % address) == {}


@pytest.mark.parametrize("template, address", [
    (GALT83, "London, {UK}"), (YATE66, "London, {UK}"), (BANCETAL65, "Paris, {FR}"),
    (CHRI92, "Hillsdale, {NJ}"),
])
def test_existing_country_and_state_forms_pass_check_bib(tmp_path, monkeypatch, template, address):
    monkeypatch.chdir(ROOT)
    assert check(tmp_path, template % address) == {}


def test_nonhouse_address_is_still_rejected(tmp_path, monkeypatch):
    # Negative control: check_bib still enforces the address house form.
    monkeypatch.chdir(ROOT)
    assert check(tmp_path, GALT83 % "London, England") == {"Galt83": {"address": "London, {UK}"}}
