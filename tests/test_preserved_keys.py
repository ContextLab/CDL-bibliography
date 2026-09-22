"""A year correction must not break existing manuscript citation keys."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from helpers import check_entries


def test_preserved_key_exception_is_exact_and_only_for_key_naming():
    entry = {"ID": "ChilEtal12", "title": "Wrong", "year": "1995"}
    bd = {entry["ID"]: entry}
    assert check_entries("ID", bd, ["ChilEtal95"], verbose=False) == []
    assert check_entries("ID", bd, ["ChilEtal94"], verbose=False)
    assert check_entries("title", bd, ["Correct title"], verbose=False)
    assert check_entries("year", bd, ["1994"], verbose=False)
