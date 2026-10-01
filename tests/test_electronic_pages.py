"""Published electronic-page suffixes survive legacy formatting."""

from pathlib import Path
import sys

import pytest

from cdlbib.helpers import valid_pages


@pytest.mark.parametrize("pages", ["439-452.e5", "439--452.e5"])
def test_electronic_suffix_is_preserved(pages):
    assert valid_pages(pages) == (True, [pages, "439--452.e5"])


@pytest.mark.parametrize("pages", ["452--439.e5", "439--439.e5", "439--452.e0", "439--452.e", "439--452.e5x"])
def test_bad_electronic_ranges_are_rejected(pages):
    assert not valid_pages(pages)[0]
