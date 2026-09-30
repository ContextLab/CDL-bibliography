"""House name forms for the stage 2B-ii batches (2026-09-25) (resolution-plan-2026-09-22, user decisions).

- No name suffixes: ``strip_suffix`` removes Jr/Sr/II/III/IV (either BibTeX's
  ``Family, Jr, Given`` form or a bare suffix token) and returns ``Given Family``.
- Initials everywhere: ``to_initials`` converts full given names to initials (one per
  given name; a hyphenated given name keeps hyphenated initials, ``Yu-Chen`` -> ``Y-C``),
  keeping the surname, lowercase particles and braced groups exactly as written. It
  returns ``(new_name, None)`` or ``(None, hold_reason)`` when the surname may be
  compound/unbraced or the given/family split is ambiguous.
"""
import re
import unicodedata

SUFFIXES = ("Jr", "Sr", "II", "III", "IV")
SUFFIX_TOKEN = re.compile(r"^(?:Jr|Sr|II|III|IV)\.?$")
PARTICLES = {"de", "da", "di", "von", "zu", "van", "du", "des", "del", "della", "la", "le", "der", "af",
             "dos", "das", "do", "dei", "ten", "ter", "den", "op", "vom", "y", "e", "al", "el", "st"}


def tokens(name):
    """Split on spaces outside braces; a braced group with spaces stays one token."""
    out, depth, current = [], 0, ""
    for ch in name:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                raise ValueError(f"unbalanced braces: {name!r}")
        if ch == " " and depth == 0:
            if current:
                out.append(current)
            current = ""
        else:
            current += ch
    if depth:
        raise ValueError(f"unbalanced braces: {name!r}")
    if current:
        out.append(current)
    return out


def split_names(value):
    """Split an author/editor field on ' and ' outside braces."""
    toks = tokens(value)
    names, current = [], []
    for t in toks:
        if t == "and":
            names.append(" ".join(current))
            current = []
        else:
            current.append(t)
    names.append(" ".join(current))
    if any(not n for n in names):
        raise ValueError(f"empty name in {value!r}")
    return names


def strip_suffix(name):
    """'Roediger, III, H L' -> 'H L Roediger'; 'William H Saufley Jr' -> 'William H Saufley';
    'J Jr Engel' -> 'J Engel'. A name without a suffix is returned unchanged."""
    parts = [p.strip() for p in name.split(",")]
    if len(parts) == 3 and SUFFIX_TOKEN.match(parts[1]):
        return parts[2] + " " + parts[0]
    if len(parts) != 1:
        raise ValueError(f"unexpected comma form: {name!r}")
    kept = [t for t in tokens(name) if not SUFFIX_TOKEN.match(t)]
    return " ".join(kept)


def plain_letters(token):
    """Letters of a token with LaTeX accents, braces and combining marks removed."""
    text = re.sub(r"\\[a-zA-Z]+\s*|\\.", "", token)
    text = text.replace("{", "").replace("}", "")
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def is_initial(token):
    """One capital letter (optionally LaTeX-accented), or hyphenated initials (Y-C)."""
    pieces = token.split("-")
    return all(re.fullmatch(r"[A-Z]", plain_letters(p)) and not re.search(r"[a-z]", re.sub(r"\\[a-zA-Z]+", "", p))
               for p in pieces)


def initial_of(word):
    """Initial of one given-name piece; None when it cannot be taken safely.

    The first character must be a plain capital letter (``J{\\'o}zsef`` -> ``J``,
    ``C\u00e9dric`` -> ``C``); a word that starts with an accent command or a brace
    (``{\\'E}mile``), or that holds anything but letters and LaTeX accents, is not
    converted automatically."""
    if not word:
        return None
    braced = re.match(r"\{([A-Z])\}", word)
    if braced:  # 'Hans-{J}ochen': a braced capital, kept from BibTeX case-folding
        word = braced[1] + word[braced.end():]
    first = word[0]
    if first.islower():
        first = first.upper()  # 'Yen-lu' -> 'Y-L': each part of a hyphenated given name
    if not first.isalpha() or not first.isupper():
        return None
    rest = plain_letters(word[1:])
    if not rest or not all(c.isalpha() for c in rest):
        return None
    return first


def to_initials(name):
    """Return (new, None), (name, None) when nothing changes, or (None, reason)."""
    if "," in name:
        return None, "comma form"
    # A no-break space (HuthEtal12 'Alexander\u00a0G') separates names like a space.
    toks = tokens(name.replace("\u00a0", " "))
    if len(toks) == 1:
        return name, None  # single token (corporate or braced) - nothing to do
    # surname: last token plus any lowercase particles directly before it
    i = len(toks) - 1
    while i - 1 >= 1 and toks[i - 1] in PARTICLES:
        i -= 1
    given, surname = toks[:i], toks[i:]
    if is_initial(surname[-1]):
        return None, f"surname '{surname[-1]}' looks like an initial (given/family order unclear)"
    full = [t for t in given if not is_initial(t)]
    if not full:
        return name, None
    if any(t.startswith("{") and t.endswith("}") and " " in t for t in given):
        return None, "braced multi-word group among the given names"
    if len(given) >= 2 and not is_initial(given[-1]):
        return None, (f"'{given[-1]}' directly before the surname '{' '.join(surname)}' may be part of a "
                      "compound (unbraced) surname")
    new = []
    for t in given:
        if is_initial(t):
            new.append(t)
            continue
        if t.lower() in PARTICLES or t[0].islower():
            return None, f"lowercase/particle token '{t}' among the given names"
        pieces = t.replace("\u2010", "-").split("-")  # U+2010 hyphen (MainEtal07 'Jean\u2010Philippe')
        if len(pieces) > 1 and any(len(p) == 1 for p in pieces):
            return None, f"given name '{t}' mixes initials and words"
        inits = [initial_of(p) for p in pieces]
        if None in inits:
            return None, f"given name '{t}' has accents, braces or non-letters (initial not taken automatically)"
        new.append("-".join(inits))
    return " ".join(new + surname), None
