"""The palette: Dartmouth's greens, and readable contrast in both modes."""
import re

import pytest

from cdlbib import theme


def test_the_recorded_dartmouth_colours_are_the_palette_anchors():
    assert (theme.GREEN, theme.FOREST, theme.RICH_FOREST) == ("#00693e", "#12312b", "#0D1E1C")
    assert theme.DARK["background"] == theme.RICH_FOREST and theme.DARK["surface"] == theme.FOREST
    assert theme.LIGHT["text"] == theme.RICH_FOREST
    assert theme.DARK["primary"] == theme.LIGHT["primary"] == theme.GREEN


def test_contrast_matches_the_wcag_reference_values():
    assert theme.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert theme.contrast("#ffffff", "#ffffff") == pytest.approx(1.0)
    assert theme.contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)   # the classic near miss


@pytest.mark.parametrize("mode", sorted(theme.MODES))
def test_every_drawn_pairing_is_readable(mode):
    colours = theme.MODES[mode]
    failures = [(fore, back, round(theme.contrast(colours[fore], colours[back]), 2), need)
                for fore, back, need in theme.pairs(mode)
                if theme.contrast(colours[fore], colours[back]) < need]
    assert failures == []


@pytest.mark.parametrize("mode", sorted(theme.MODES))
def test_no_plain_black_or_white_and_both_modes_define_the_same_roles(mode):
    colours = theme.MODES[mode]
    assert set(colours) == set(theme.DARK)
    assert all(re.fullmatch(r"#[0-9a-fA-F]{6}", colour) for colour in colours.values())
    assert not {c.lower() for c in colours.values()} & {"#000000", "#ffffff"}
    for colour in (colours[role] for role in theme.BACKGROUNDS):     # green-tinted: green is the largest channel
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        assert g > r and g >= b


def test_the_stylesheet_carries_both_modes():
    sheet = theme.stylesheet()
    assert f"--cdl-background: {theme.LIGHT['background']};" in sheet
    assert f"--cdl-background: {theme.DARK['background']};" in sheet
    assert "--cdl-on-primary:" in sheet and "prefers-color-scheme: dark" in sheet
