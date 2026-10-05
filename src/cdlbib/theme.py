"""The one palette of the interactive front ends. The TUI themes and the web style sheet
are derived from it; nothing else names a colour."""

GREEN = "#00693e"          # Dartmouth Green
FOREST = "#12312b"         # Forest Green
RICH_FOREST = "#0D1E1C"    # Rich Forest Green: the near-black

# role -> colour. "on_primary" is text drawn on a "primary" fill.
DARK = {
    "background": RICH_FOREST, "surface": FOREST, "panel": "#1A4239",
    "text": "#EAF4EF", "muted": "#A9C7BA",
    "primary": GREEN, "on_primary": "#F4FAF7", "accent": "#5FD3A0",
    "success": "#7BD88F", "warning": "#E8C468", "error": "#FF8A80", "border": "#4FA084",
}
LIGHT = {
    "background": "#F4FAF7", "surface": "#E6F2EC", "panel": "#D3E8DE",
    "text": RICH_FOREST, "muted": "#3F5F55",
    "primary": GREEN, "on_primary": "#F4FAF7", "accent": "#004D2E",
    "success": "#00603A", "warning": "#6B4700", "error": "#9C1C16", "border": "#4E8A72",
}
MODES = {"dark": DARK, "light": LIGHT}

BACKGROUNDS = ("background", "surface", "panel")
TEXTS = ("text", "muted", "accent", "success", "warning", "error")   # each is used as text on every background
TEXT_CONTRAST, MARK_CONTRAST = 4.5, 3.0                              # WCAG 2.1 AA: text; borders and marks


def _luminance(colour):
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """The WCAG 2.1 contrast ratio of two #rrggbb colours (1 to 21)."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def pairs(mode):
    """[(foreground role, background role, required ratio)]: every pairing the front ends draw."""
    found = [(text, back, TEXT_CONTRAST) for text in TEXTS for back in BACKGROUNDS]
    found.append(("on_primary", "primary", TEXT_CONTRAST))
    found += [("border", back, MARK_CONTRAST) for back in BACKGROUNDS]
    return found


def css_variables(mode):
    """The palette of ``mode`` as CSS custom properties (``--cdl-<role>``)."""
    return "".join(f"  --cdl-{role.replace('_', '-')}: {colour};\n" for role, colour in MODES[mode].items())


def stylesheet():
    """The web interface's theme sheet: light by default, dark when the system asks for it,
    and either one when the page sets ``data-theme``."""
    return (f":root {{\n{css_variables('light')}}}\n"
            f"@media (prefers-color-scheme: dark) {{\n:root:not([data-theme=\"light\"]) {{\n{css_variables('dark')}}}\n}}\n"
            f":root[data-theme=\"dark\"] {{\n{css_variables('dark')}}}\n")
