"""The two Textual themes, built from cdlbib.theme's role colours and nothing else."""
import os

from textual.theme import Theme

from .. import theme

NAMES = {"dark": "cdlbib-dark", "light": "cdlbib-light"}


def build(mode):
    roles = theme.MODES[mode]
    return Theme(
        name=NAMES[mode], dark=mode == "dark",
        primary=roles["primary"], secondary=roles["border"], accent=roles["accent"],
        foreground=roles["text"], background=roles["background"], surface=roles["surface"], panel=roles["panel"],
        success=roles["success"], warning=roles["warning"], error=roles["error"],
        variables={
            "cdl-muted": roles["muted"], "cdl-border": roles["border"], "cdl-on-primary": roles["on_primary"],
            "text-muted": roles["muted"], "foreground-muted": roles["muted"], "text-disabled": roles["muted"],
            "foreground-disabled": roles["muted"],
            "border": roles["accent"], "border-blurred": roles["border"],
            "block-cursor-foreground": roles["on_primary"], "block-cursor-background": roles["primary"],
            "block-cursor-blurred-foreground": roles["text"], "block-cursor-blurred-background": roles["panel"],
            "block-hover-background": roles["panel"],
            "input-cursor-background": roles["text"], "input-cursor-foreground": roles["background"],
            "input-selection-background": roles["primary"], "input-selection-foreground": roles["on_primary"],
            "footer-foreground": roles["text"], "footer-background": roles["panel"],
            "footer-key-foreground": roles["accent"], "footer-key-background": roles["panel"],
            "footer-description-foreground": roles["text"], "footer-description-background": roles["panel"],
            "footer-item-background": roles["panel"],
            "scrollbar": roles["border"], "scrollbar-hover": roles["accent"], "scrollbar-active": roles["accent"],
            "scrollbar-background": roles["surface"], "scrollbar-background-hover": roles["surface"],
            "scrollbar-background-active": roles["surface"], "scrollbar-corner-color": roles["surface"],
            "button-foreground": roles["text"], "button-color-foreground": roles["on_primary"],
            "link-color": roles["accent"], "link-color-hover": roles["accent"],
            "link-background": roles["background"], "link-background-hover": roles["panel"],
            "screen-selection-background": roles["primary"], "screen-selection-foreground": roles["on_primary"],
        })


def terminal_mode(environ=None):
    """"light" or "dark" as the terminal says, else "dark". Textual does not ask the terminal
    for its background; the one thing a terminal may tell is COLORFGBG ("foreground;background"
    palette numbers, set by some terminals): background 7 or 15 is a light one."""
    value = (os.environ if environ is None else environ).get("COLORFGBG", "")
    last = value.rsplit(";", 1)[-1].strip()
    return "light" if last in ("7", "15") else "dark"


def other(name):
    return NAMES["light"] if name == NAMES["dark"] else NAMES["dark"]


def mode_of(name):
    return "light" if name == NAMES["light"] else "dark"
