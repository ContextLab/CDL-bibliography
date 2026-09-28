from unidecode import unidecode as decode
from string import ascii_lowercase
from urllib import request as get
from tqdm import tqdm

import bibtexparser as bp
import numpy as np
import pandas as pd

import re
import itertools
import os
import sys
import json
from pathlib import Path


def read(fname):
    if not os.path.exists(fname):
        fname = os.path.join("bibcheck", fname)
    return pd.read_csv(fname, header=None).values.flatten().tolist()


def load_key(fname):
    if not os.path.exists(fname):
        fname = os.path.join("bibcheck", fname)
    key = pd.read_excel(fname, header=0, index_col="orig")
    return key.to_dict()["corrected"]


prefixes = read("prefixes.txt")
suffixes = read("suffixes.txt")
uncaps = read("uncaps.txt")
force_caps = read("caps.txt")
address_codes = read("addresses.txt")

def load_key_overrides(key, fname):
    """Apply source-backed corrections to an alias table loaded by load_key.

    journal_key.xls mapped some names onto a different journal ('psychonomic
    science' -> 'psychological science', 'j comp neurol' -> 'journal of
    computational neuroscience') or onto a misspelled target ('physiological
    review'). The legacy .xls is not rewritten (no faithful .xls writer is
    installed, and a binary diff cannot be reviewed); each correction lives in a
    JSON file with its evidence. 'remove' drops the alias so the name is
    formatted as given; 'retarget' replaces the target. Each row names the
    spreadsheet's old target, and a mismatch raises instead of silently
    overriding a row someone has since edited.
    """
    path = Path(__file__).parent / fname
    for row in json.loads(path.read_text())["overrides"]:
        source = row["source"]
        if key.get(source) != row["old_target"]:
            raise ValueError(
                f"{fname}: {source!r} maps to {key.get(source)!r} in the spreadsheet, "
                f"not the recorded old target {row['old_target']!r}")
        if row["action"] == "remove":
            del key[source]
        elif row["action"] == "retarget":
            key[source] = row["new_target"]
        else:
            raise ValueError(f"{fname}: unknown action {row['action']!r} for {source!r}")
    return key


journal_key = load_key_overrides(load_key("journal_key.xls"), "journal_key_overrides.json")
publisher_key = load_key("publisher_key.xls")
address_key = load_key("address_key.xls")

# Preserve published citation keys after source-backed metadata corrections.
# Each exception is tied to the exact newly computed name, and affects only
# key naming checks; it never disables metadata or formatting checks.
key_overrides = json.loads((Path(__file__).parent / "key_overrides.json").read_text())

LATEST_BIBFILE = (
    "https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/cdl.bib"
)


def printv(s, verbose=True, **kwargs):
    if verbose:
        print(s, **kwargs)


def load_bibliography(fname, verbose=True):
    if fname == "github":
        fname = LATEST_BIBFILE

    printv(f"loading {fname}...", verbose=verbose, end="")

    parser = bp.bparser.BibTexParser(
        ignore_nonstandard_types=True, common_strings=True, homogenize_fields=True
    )
    if os.path.exists(fname):
        with open(fname, "r") as b:
            bibdata = bp.load(b, parser=parser)
    else:
        b = get.urlopen(fname).read().decode("utf-8")
        bibdata = parser.parse(b)
    printv("done", verbose=verbose)
    return bibdata.get_entry_dict()


def remove_accents_and_hyphens(s):
    replace = {"{\\l}": "l", "{\\o}": "o", "{\\i}": "i", "{\\t}": "t"}
    for key, val in replace.items():
        s = s.replace(key, val)

    accents = r"""\{?\\[`'^"~=.uvHtcdbkr]?\s?\{?\\?(\w*)\}?"""
    accented_chars = [x for x in re.finditer(accents, s)]

    s_list = [c for c in s]
    hyphen = "-"
    for a in accented_chars:
        next_len = a.end() - a.start()
        s_list[a.start()] = a.group(1)
        s_list[(a.start() + 1) : a.end()] = hyphen * (next_len - 1)

    return "".join([c for c in s_list if c != hyphen])


def match(names, template):
    # check if list of strings names contains a match to the potentially multi-word
    # template.  return the position of the start of the left-most match
    template = template.split(" ")
    for i, x in enumerate(names[: len(names) - len(template) + 1]):
        found_match = False
        for j, t in enumerate(template):
            if names[i + j].lower() != t:
                found_match = False
                break
            else:
                found_match = True
        if found_match:
            return i
    return -1


def remove_curlies(s, join=""):  # only removes *matching* curly braces
    for i, c in enumerate(s):
        if c == "{":
            j = i

            curly_count = 1
            while j < len(s) - 1:
                j += 1
                if s[j] == "{":
                    curly_count += 1

                if s[j] == "}":
                    curly_count -= 1

                if curly_count == 0:
                    break

            if curly_count == 0:
                return remove_curlies(
                    s[:i] + join.join(s[(i + 1) : j].split(" ")) + s[(j + 1) :]
                )
    return s


def remove_non_letters(s):
    remove_chars = [
        ",",
        ".",
        "!",
        "?",
        "'",
        '"',
        "{",
        "}",
        "-",
        "\\",
        ":",
        "(",
        ")",
        "[",
        "]",
        "+",
        "/",
        "*",
    ]
    for c in remove_chars:
        s = s.replace(c, "")
    return s


def char_match(x, y, ignore_case=True):
    if ignore_case:
        x = x.lower()
        y = y.lower()
    return remove_non_letters(x.strip()) == remove_non_letters(y.strip())


def rearrange(name, preserve_non_letters=False):
    original_name = name

    # remove suffixes and convert to list
    if preserve_non_letters:
        name = [x.strip() for x in name.split(",")]
    else:
        name = [remove_non_letters(x.strip()) for x in name.split(",")]
    sxs = [n for n in name if n.lower() in suffixes]
    name = [n for n in name if n.lower() not in suffixes]

    if len(name) == 2:  # last, first (+ middle)
        if preserve_non_letters and len(name[0].split(" ")) > 1:
            if not (
                (len(name[0]) >= 2) and (name[0][0] == "{") and (name[0][-1] == "}")
            ):
                name[0] = "{" + name[0] + "}"
        x = " ".join([name[1], name[0]])
    elif len(name) == 1:  # first (+ middle) + last
        x = name[0]
    elif len(name) == 0:
        raise Exception(f"no non-suffix names: {original_name}")
    elif len(name) > 2:
        raise Exception(f"too many commas: {original_name}")
    return x


def last_name(names):
    # remove suffixes and non-letters
    names = [
        remove_non_letters(n)
        for n in rearrange(names).split(" ")
        if not (n.lower() in suffixes)
    ]

    # start at the end and move backward
    x = []
    found_prefix = False
    for n in reversed(names):
        if (n.lower() in prefixes) and (n != n.upper()):
            found_prefix = True
        elif found_prefix or len(x) > 0:
            break
        x.append(n)
    if found_prefix:
        return "".join(reversed(x))
    else:
        return x[0]


def split_names(names):
    """Split a BibTeX name list at " and " outside braces (2026-09-27): a braced
    group or organization such as ``{U.S. Food and Drug Administration}`` is one
    name, not two. A list with unbalanced braces is split as before."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(names):
        c = names[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return names.split(" and ")
        elif depth == 0 and names.startswith(" and ", i):
            parts.append(names[start:i])
            i += 5
            start = i
            continue
        i += 1
    if depth != 0:
        return names.split(" and ")
    parts.append(names[start:])
    return parts


def organization_key(name):
    """Key part of a fully braced (organization/group) author: the letters of its
    successive words, concatenated until 4 letters are reached, then truncated to 4,
    with the capitalization as printed (user rule 2026-09-28, resolution-plan README
    "Organization authors in keys": "use as many organization 'words' as are available,
    until 4 letters are achieved"): {R Core Team} -> RCor, {U.S. Food and Drug
    Administration} -> USFo, {RNS System ...} -> RNSS, {Centers for Disease Control and
    Prevention} -> Cent. A name with fewer than 4 letters in all keeps what it has.
    None for any other name ({van der Meer} inside a personal name is not braced whole)."""
    name = name.strip()
    if not fully_braced(name):
        return None
    inner = name[1:-1].strip()
    while fully_braced(inner):  # the formatter's double-braced form
        inner = inner[1:-1].strip()
    words = remove_accents_and_hyphens(decode(inner)).split()
    if not words:
        return None
    letters = ""
    for word in words:
        letters += "".join(c for c in remove_curlies(word) if c.isascii() and c.isalpha())
        if len(letters) >= 4:
            break
    return letters[:4] or None


def last_names_from_str(x):
    # pass in a single string (and-separated) or list of authors and get back a list of last names
    if type(x) == str:
        return [last_name(n) for n in split_names(x)]
    elif type(x) == list:
        return [last_name(n) for n in x]
    else:
        return [""]


def authors2key(authors, year):
    def key(author):
        # an organization (a fully braced name) is one author keyed by the letters of its
        # successive words, up to 4
        org = organization_key(author)
        if org:
            return org

        # convert accented unicode characters to closest ascii equivalent
        author = decode(author)

        # re-arrange author name to FIRST [MIDDLE] LAST [SUFFIX]
        author = remove_accents_and_hyphens(author)
        # author = reformat_author(author)
        author = remove_curlies(author)
        author = reformat_author(author)

        # get first 4 letters of last name
        return last_name(author)[:4]

    yr_str = str(year)[-2:]

    authors = split_names(authors)
    if len(authors) == 0:
        raise Exception("Author information missing, no key generated")
    elif len(authors) == 1:
        return key(authors[0]) + yr_str
    elif len(authors) == 2:
        return key(authors[0]) + key(authors[1]) + yr_str
    elif len(authors) >= 3:
        return key(authors[0]) + "Etal" + yr_str
    else:
        raise Exception("Something went wrong...")


def get_vals(bd, field, proc=lambda x: x):
    def safe_get(item, field):
        if field in item.keys():
            return item[field]
        else:
            return ""

    return [proc(safe_get(i, field)) for k, i in bd.items()]


def same_id(a, b, ignore_special=False):
    if ignore_special and (("\\" in a) or ("\\" in b)):
        return True

    if len(a) > len(b):
        return same_id(b, a)
    elif a == b:
        return True
    else:
        return a == b[: len(a)]


def check_entries(
    field,
    bd,
    targets,
    same=lambda x, y: x == y,
    proc=lambda x: x,
    valproc=lambda x: x,
    verbose=True,
):
    vals = get_vals(bd, field, proc=valproc)
    ids = get_vals(bd, "ID")

    printv(f"running check: {field}...", verbose=verbose)
    tofix = [
        (i, v, t)
        for i, v, t in tqdm(zip(ids, vals, targets))
        if not ("force" in list(bd[i].keys()) or same(proc(v), proc(t))
                or (field == "ID" and key_overrides.get(i) == t))
    ]

    if len(tofix) == 0:
        printv(f"no {field}s to fix!", verbose=verbose)
    else:
        printv(f"{len(tofix)} errors detected:", verbose=verbose)
        for i in tofix:
            printv(f'{i[0]}: \t{field} "{i[1]}" should be "{i[2]}"', verbose=verbose)
    printv("\n", verbose=verbose)
    return tofix


def duplicate_inds(x):
    # for the list x, return a new list containing 0 or more
    # lists of the indices of matching (non-unique) elements
    y = []
    unique_vals, counts = np.unique(x, return_counts=True)
    for v in [v for i, v in enumerate(unique_vals) if counts[i] > 1]:
        y.append([i for i, j in enumerate(x) if j == v])
    return y


def find_duplicates(ids, authors, titles, verbose=True):
    printv("Checking for duplicated keys and entries...", verbose=verbose)

    # check for multiple entries with the same key
    # note: the current version of bibtexparser overwrites parsed entries
    # with whatever comes latest in the .bib file, so currently this check
    # doesn't actually do anything...
    unique_ids, counts = np.unique(ids, return_counts=True)
    duplicate_keys = unique_ids[np.where(counts > 1)[0]]

    if len(duplicate_keys) > 0:
        printv("Multiple entries for the following key(s):", verbose=verbose)
        printv("\n".join(duplicate_keys), verbose=verbose)
    else:
        printv("No keys with multiple entries were found.", verbose=verbose)

    # check for duplicated information.
    # a duplicate is found when two (or more) entries share BOTH a set of author last names AND a title
    duplicates = []
    duplicate_title_inds = duplicate_inds(titles)

    last_names = [" and ".join(last_names_from_str(a)) for a in authors]
    duplicate_authors = duplicate_inds(last_names)

    for i in duplicate_title_inds:
        duplicate_author_inds = list(
            np.array(i)[np.array(duplicate_inds([last_names[j] for j in i]), dtype=int)]
        )
        for a in duplicate_author_inds:
            duplicates.append(a)

    if len(duplicate_keys) > 0:
        for d in duplicates:
            printv(
                f"These key combinations appear to have the same author/title combinations [ind, key]: {[[i, ids[i]] for i in d]}",
                verbose=verbose,
            )
    else:
        printv("No entries with duplicated authors/titles were found.", verbose=verbose)

    return duplicate_keys, duplicates


def get_key_suffixes(n):
    """
    return a list of suffixes to append to keys with the same base:
    a, b, c, ..., z, aa, ab, ..., az, ba, ..., bz, aaa, aab, ...
    """
    # source: https://stackoverflow.com/questions/29351492/how-to-make-a-continuous-alphabetic-list-python-from-a-z-then-from-aa-ab-ac-e/29351603
    if n <= 1:
        return ""

    def generate_id():
        i = 1
        while True:
            for s in itertools.product(ascii_lowercase, repeat=i):
                yield "".join(s)
            i += 1

    gen = generate_id()

    def helper():
        for s in gen:
            return s

    return [helper() for i in range(n)]


# Check bibtex keys. Duplicates should be assigned a suffix of 'a', 'b', etc.
# If keys match aside from suffix then still allow the bibtex file to "pass"
# as long as all "matching" keys are unique and all have suffixes and the
# suffixes span a, b, c, ..., etc. without gaps
def key_names(bd):
    """The names a cite key is built from: the authors, or for an edited volume
    with no author (``editor`` only), the editors (stage 2B-i, 2026-09-26; the
    rule used to demand a year-only key such as ``94``)."""
    return [a if a.strip() else e
            for a, e in zip(get_vals(bd, "author"), get_vals(bd, "editor"))]


def check_key_suffixes(bd):
    ids = get_vals(bd, "ID")
    authors = key_names(bd)
    years = get_vals(bd, "year")

    target_ids = [authors2key(a, y) for a, y in zip(authors, years)]

    checked = []
    bad_keys = []

    # for duplicate base keys, ensure correct suffixes
    same_base = duplicate_inds(target_ids)
    for inds in same_base:
        next_base = target_ids[inds[0]]
        target_keys = [next_base + x for x in get_key_suffixes(len(inds))]
        actual_keys = list(np.array(ids)[inds])

        correct_keys = [a for a in actual_keys if a in target_keys]
        missing_keys = [t for t in target_keys if t not in actual_keys]
        i = 0
        for a in actual_keys:
            checked.append(a)
            if a not in target_keys:
                bad_keys.append([a, missing_keys[i]])
                i += 1

    # for non-duplicate base keys, ensure *no* suffixes
    for i, t in zip(ids, target_ids):
        if i not in checked:
            if not (i == t):
                bad_keys.append([i, t])

    # now generate a list of actual ids and target ids, where the targets are
    # in the same order of the actual ids
    targets = []
    for i in ids:
        correction = [b[1] for b in bad_keys if b[0] == i]
        if len(correction) == 0:
            targets.append(i)
        elif len(correction) == 1:
            targets.append(correction[0])
        else:
            raise Exception(f"same key was corrected multiple times: {i}")

    return targets


# 1. numbers separated by n-dash with no spaces; right number larger than left number
# 2. zero or more lowercase letter(s) + sequence of digits
# 3. two combinations of letter(s) + sequence of digits:
#   - same letters at the beginning
#   - right number larger than left number
# 4. two uppercase letters, hypthen, digit, letter, ., two digits (e.g., PS-2B.16)
# 5. empty string
# 6. doi
def valid_page(p):  # single page, no hyphens
    if len(p) == 0:  # empty string
        return True, "empty", None

    if re.fullmatch(r"[0-9]+", p):  # integer
        return True, "int", int(p)

    # Source-backed alphanumeric article number with dot-separated parts
    # (machinery fix 2026-09-25, KothEtal25: Crossref article-number
    # "IMAG.a.136"). It must start with a letter, contain a digit, and have
    # no hyphen, so it can never be read as a range.
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)+", p) and re.search(r"\d", p):
        return True, "article-number", None

    # Society for Neuroscience eLocator (held form 2026-09-27, HeniEtal19:
    # "ENEURO.0306-19.2019"): JOURNAL.NNNN-YY.YYYY. Its hyphen is part of the
    # identifier, so it is matched whole here, before any range splitting.
    if re.fullmatch(r"[A-Z]+\.\d{4}-\d{2}\.\d{4}", p):
        return True, "elocator", None

    # Science-family article number (held form 2026-09-27, ViveEtal10: Sci
    # Transl Med "24ra22" = issue 24, research article 22): issue digits, a
    # two-letter lowercase article type, then the article digits.
    if re.fullmatch(r"[1-9]\d*[a-z]{2}[1-9]\d*", p):
        return True, "article-number", None

    # page number with a capital-letter suffix (held form 2026-09-27,
    # BrinCrag72: proceedings abstracts printed as "28P--29P", PubMed
    # "PG  - 28P-29P"). A range needs the same suffix on both ends.
    x = re.fullmatch(r"(?P<digits>[1-9]\d*)(?P<suffix>[A-Z])", p)
    if x is not None:
        return True, "suffixed", [x.group("suffix"), int(x.group("digits"))]

    # prefix of one or more letters, followed by a sequence of digits
    r1 = re.compile(r"""(?P<prefix>[a-zA-Z]+)(?P<digits>\d+)""")
    x = r1.fullmatch(p)
    if not (x is None):
        return True, "prefixed", [x.group("prefix"), int(x.group("digits"))]

    # two uppercase letters, hyphen, digit, letter, ., two digits
    r2 = re.compile(r"""(?P<prefix>[A-Z]{2}-[\dA-Z]{2}).(?P<digits>\d+)""")
    x = r2.fullmatch(p)
    if not (x is None):
        return True, "conference", [x.group("prefix"), int(x.group("digits"))]

    # doi address
    r3 = re.compile(r"""doi\.org/(?P<doi>[A-Za-z\d\-\./]+)""")
    x = r3.fullmatch(p)
    if not (x is None):
        return True, "doi", None

    # arXiv section
    r4 = re.compile(r"""((?P<subject>[a-z]{2,})/)?(?P<article>[\d\.]+(v[\d]+)?)""")
    x = r4.fullmatch(p)
    if not (x is None):
        return True, "arxiv", None

    # roman numeral
    def mixed_case(s):
        return not ((s == s.lower()) or (s == s.upper()))

    def roman2int(s):
        # source: https://www.w3resource.com/python-exercises/class-exercises/python-class-exercise-2.php
        vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        x = 0
        for i in range(len(s)):
            if i > 0 and vals[s[i]] > vals[s[i - 1]]:
                x += vals[s[i]] - 2 * vals[s[i - 1]]
            else:
                x += vals[s[i]]
        return x

    # source: https://www.geeksforgeeks.org/validating-roman-numerals-using-regular-expression/
    r5 = re.compile(r"""^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$""")
    x = r5.fullmatch(p.upper())
    if not ((x is None) or mixed_case(p)):
        return True, "roman", roman2int(p.upper())

    return False, "invalid", None


def valid_pages(p):
    # Check for invalid dash characters (en-dash, em-dash, minus sign, etc.)
    invalid_dashes = {
        "\u2013": "en-dash (–)",
        "\u2014": "em-dash (—)",
        "\u2212": "minus sign (−)",
        "\u2010": "hyphen (‐)",
        "\u2011": "non-breaking hyphen (‑)",
    }

    for dash_char, dash_name in invalid_dashes.items():
        if dash_char in p:
            # Return False with error message
            suggested_fix = p.replace(dash_char, "-")
            return False, [p, suggested_fix]

    # Cell Press citations may include an electronic-page suffix on the last
    # printed page (e.g. 439--452.e5). Preserve that published locator exactly.
    electronic_range = re.fullmatch(r"([1-9]\d*)-{1,2}([1-9]\d*)(\.e[1-9]\d*)", p)
    if electronic_range:
        first, last, electronic = electronic_range.groups()
        return int(first) < int(last), [p, first + "--" + last + electronic]

    # An article printed in two or more parts (held form 2026-09-27,
    # MullSchu94: "81--190, 257--339"; user default: cite every part). Each
    # part must be valid on its own and the parts must run forward.
    if "," in p:
        parts = [x.strip() for x in p.split(",")]
        checked = [valid_pages(x) for x in parts]
        target = ", ".join(c[1][1] for c in checked)
        if not all(len(x) > 0 and c[0] for x, c in zip(parts, checked)):
            return False, [p, target]
        bounds = [[valid_page(y)[1:] for y in c[1][1].split("--")] for c in checked]
        ordered = all(
            b1[-1][0] == "int" and b2[0][0] == "int" and b1[-1][1] < b2[0][1]
            for b1, b2 in zip(bounds, bounds[1:]))
        return ordered, [p, target]

    valid, kind, val = valid_page(p)
    if valid:  # "single" page
        return True, [p, p]
    else:  # page range
        # split by hyphen
        ps = [x.strip() for x in p.split("-") if len(x.strip()) > 0]
        if len(ps) == 2:
            if ps[0] == ps[1]:
                return False, [p, ps[0]]

            valid1, kind1, val1 = valid_page(ps[0])
            valid2, kind2, val2 = valid_page(ps[1])

            # front matter through body text (held form 2026-09-27, Perr14
            # "i--97", Unde45, Ward37, Webb17, Calk96): a lowercase roman
            # first page and an arabic last page. The two numberings cannot be
            # compared, so the order is fixed by the forms: roman first.
            if (valid1 and valid2 and kind1 == "roman" and kind2 == "int"
                    and ps[0] == ps[0].lower() and val2 > 0):
                return True, [p, "--".join(ps)]

            if (not (valid1 and valid2)) or (not (kind1 == kind2)):
                if (kind1 == "prefixed") and (kind2 == "int"):
                    return False, [
                        p,
                        "--".join([val1[0] + str(val1[1]), val1[0] + str(val2)]),
                    ]
                return False, [p, p]

            if kind1 in ["int", "roman"]:
                if val1 < val2:
                    return True, [p, "--".join(ps)]
                elif kind1 == "int":
                    # attempt to autocorrect
                    p1 = str(val1)
                    p2 = str(val2)
                    if len(p2) < len(p1):
                        return False, [p, "--".join([p1, p1[: -len(p2)] + p2])]
                    return False, [p, "--".join(ps)]
            elif kind1 in ["prefixed", "conference", "suffixed"]:
                if (val1[0] == val2[0]) and (val1[1] < val2[1]):
                    return True, [p, "--".join(ps)]
                else:
                    return False, [p, "--".join(ps)]
            # dois and arxiv sections can't be specified as ranges
        return False, [p, "--".join(ps)]


def generate_correct_pages(bd):
    ids = get_vals(bd, "ID")
    pages = get_vals(bd, "pages")

    target_pages = [valid_pages(p)[1][1] for p in pages]

    unfixable = [
        (i, valid_pages(p)) for i, p in zip(ids, target_pages) if not valid_pages(p)[0]
    ]
    return target_pages, unfixable


DOTTED_INITIALS = re.compile(r"(?:\{[A-Z]\}\.|[A-Z]\.)+|\{[A-Z]\}|[A-Z]")

# Country forms an alias target may end in, each with the spellings that count as the
# name already printing that country. address_key.xls maps bare cities onto a city plus
# country ('london' -> 'london, uk', 'paris' -> 'paris, fr', 'heidleberg' ->
# 'heidelberg, germany'); user decision 2026-09-26: a country the source does not print
# is dropped, so the formatter must never add one. Rows that restate a country the name
# already prints ('london, england' -> 'london, uk', 'prague, czech republic' ->
# 'prague, cz') are the house country form and still apply. US state codes are not
# countries and are untouched ('boston' -> 'boston, ma').
ALIAS_COUNTRIES = {
    "uk": ["uk", "u. k.", "u.k.", "united kingdom", "england", "great britain",
           "britain", "scotland", "wales"],
    "fr": ["fr", "france"],
    "germany": ["germany", "deutschland"],
    "ru": ["ru", "russia"],
    "ch": ["ch", "switzerland"],
    "it": ["it", "italy"],
    "au": ["au", "australia"],
    "cz": ["cz", "czech republic", "czechia"],
    "usa": ["usa", "u.s.a.", "u. s. a.", "us", "u.s.", "united states", "america"],
    "canada": ["canada"],
    "sweden": ["sweden"],
}


def drop_added_country(name, target):
    """Return an alias target without a country that ``name`` does not print.

    If the target's last comma component is a country and no spelling of that country
    appears as a word in ``name``, the component is removed; the rest of the alias
    (a spelling fix such as 'heidleberg' -> 'heidelberg') still applies. Returns None
    when nothing of the alias is left beyond ``name`` itself.
    """
    parts = [p.strip() for p in target.split(",")]
    country = remove_curlies(parts[-1]).strip().lower()
    if len(parts) < 2 or country not in ALIAS_COUNTRIES:
        return target
    printed = remove_curlies(name).lower()
    if any(re.search(r"(?<![a-z])" + re.escape(form) + r"(?![a-z])", printed)
           for form in ALIAS_COUNTRIES[country]):
        return target
    kept = ", ".join(parts[:-1])
    return None if kept.lower() == name.lower() else kept


def format_journal_name(n, key=journal_key, force_caps=force_caps, dotted_initials=False,
                        drop_countries=None):
    """Format a journal, booktitle, publisher or address name.

    ``drop_countries`` (addresses; default: on exactly when ``key`` is address_key):
    an alias target never adds a country the name does not print (see
    drop_added_country). Journal titles are exempt: the USA in "Proceedings of the
    National Academy of Sciences, USA" is part of the title, not an address.

    ``dotted_initials`` (publishers): a word made only of capital initials, with or
    without periods or braces ("W.H.", "V.", "{W}.", "W"), is written in the house
    initials style, undotted and space-separated: "W.H. Freeman" -> "W H Freeman"
    (user decision 2026-09-26, reversing stage 2B-i's dotted form). The
    word-capitalizing rule used to turn "W.H. Freeman" into "W.h. Freeman" (Marr82),
    and force_caps braced undotted initials ("{W} {H} Freeman").
    """
    # The legacy spreadsheet contains aliases that erase a historical title,
    # monograph designation, or journal section. Formatting cannot establish
    # that publication identity; retain those words for source verification.
    preserve_identity = {
        "journal of experimental psychology monograph",
        "journal of experimental psychology monograph supplement",
        "journal of experimental psychology; journal of experimental psychology",
        "the quarterly journal of experimental psychology section a",
        "the quarterly journal of experimental psychology: section a",
        # The prefixed NLM title applied in 1989-2005. Do not impose it on
        # articles whose sources use the unprefixed journal title.
        "brain research reviews",
    }
    # An alias that only cuts a hyphenated suffix ("journal of physiology-paris" ->
    # "journal of physiology") names a different journal, not a spelling variant of
    # the same one (LachEtal03); the name is formatted as given instead.
    alias = key.get(n.lower()) if isinstance(key.get(n.lower()), str) else None
    if drop_countries is None:
        drop_countries = key is address_key
    if alias is not None and drop_countries:
        alias = drop_added_country(n, alias)  # an alias never adds an unprinted country
    cuts_suffix = alias is not None and re.fullmatch(
        re.escape(alias.lower()) + r"-\w[\w ]*", n.lower()) is not None
    aliased = n.lower() not in preserve_identity and alias is not None and not cuts_suffix
    if aliased:
        n = alias
        as_given = n.split(" ")
    else:
        as_given = n.split(" ")  # before lowercasing: dotted initials keep their capitals
        n = n.lower()

    words = n.split(" ")
    # next line isn't working...
    # words = ['-'.join([format_journal_name(x) for x in w.split('-')]) if len(w.split('-')) > 1 else w for w in words] #deal with hyphens

    # Addresses: the words before the first comma name the city, and a city
    # word given in mixed case is not a state code (held form 2026-09-27,
    # BartEtal04c "La Jolla, {CA}" was read as "{LA} Jolla"). An all-capital
    # word there ("Washington DC") is still matched against the codes.
    city_words = -1
    if force_caps is address_codes and not aliased and "," in n:
        city_words = len(n.split(",")[0].split(" "))

    for i, w in enumerate(words):
        if dotted_initials and DOTTED_INITIALS.fullmatch(as_given[i]):
            words[i] = " ".join(re.findall(r"[A-Z]", as_given[i]))
            continue
        # Check if word is fully braced (starts and ends with braces around the whole word)
        is_fully_braced = before_letters(w, "{") and after_letters(w, "}")

        if not aliased:
            given = as_given[i]
            # A braced word is protected exactly as given (held forms
            # 2026-09-27: RangEtal14 "{PMLR}" became "{pmlr}", HeniEtal19
            # "{eNeuro}" became "{eneuro}"); a word in caps.txt keeps its
            # caps.txt form below.
            given_braced = before_letters(given, "{") and after_letters(given, "}")
            core = strip_leading_trailing_non_letters(
                remove_curlies(given, join=" ") if given_braced else given)[1]
            listed = core and any(f.lower() == remove_non_letters(core.lower())
                                  for f in force_caps)
            if given_braced and core and not listed:
                words[i] = given
                continue
            # the article "a", given in lower case inside a name, stays an
            # article (held form 2026-09-27, Fish22 "Containing Papers of a
            # Mathematical or Physical Character" became "of {A} Mathematical");
            # a capital "A" ("Series A") is still the caps.txt letter, and so
            # is "a" opening a subtitle ("{EEG}: a Guide" -> "{EEG}: {A} Guide").
            if (0 < i < len(words) - 1 and given == "a"
                    and as_given[i - 1][-1:].isalnum()):
                words[i] = "a"
                continue
        city_word = (not aliased and i < city_words and not is_fully_braced
                     and as_given[i] != as_given[i].upper())

        if is_fully_braced:
            # Remove outer braces for processing, we'll check caps on the content
            unbraced = remove_curlies(w, join=" ")
            prefix, core, suffix = strip_leading_trailing_non_letters(unbraced)
        else:
            # Not fully braced, process normally
            prefix, core, suffix = strip_leading_trailing_non_letters(w)

        # Skip if no core (word is only punctuation)
        if not core:
            words[i] = w
            continue

        correct_caps = [
            f for f in force_caps if f.lower() == remove_non_letters(core.lower())
        ] if not city_word else []

        if len(correct_caps) >= 1:
            c = correct_caps[-1]
            if not (c[0] == "{" and c[-1] == "}"):
                c = insert_non_letters("{" + c + "}", remove_curlies(core, join=" "))
            # Add back prefix and suffix (but not the outer braces we removed, since c already has them)
            words[i] = prefix + c + suffix
        else:
            words[i] = w.capitalize()

            # deal with hyphens
            if len(w.split("-")) > 1:
                words[i] = "-".join(
                    format_journal_name(c, key=key, force_caps=force_caps,
                                        drop_countries=drop_countries)
                    for c in w.split("-")
                )

            if (i > 0) and (w.lower() in uncaps):
                words[i] = words[i].lower()

            # a name with a one-letter elided prefix keeps the capital given
            # after the apostrophe (held form 2026-09-27, BirdEtal09 "O'Reilly"
            # became "O'reilly"); "Scribner's", or "L'année" given in lower case, is unaffected.
            if not aliased and re.fullmatch(r"[A-Z]'[A-Z][a-z]+\W*", as_given[i]) \
                    and re.fullmatch(r"[A-Z]'[a-z]+\W*", words[i]):
                words[i] = words[i][:2] + words[i][2].upper() + words[i][3:]
    return " ".join(words)


# rearrange author name (first middle last suffix)
# get rid of (any number of) clumped initials:
# AA --> A A
# A.A. --> A A
# A.A --> A A
# AA. --> A A
# ...
# AAA --> A A A
# One letter of a name: a LaTeX accent group or a single character.
LETTER_UNIT = re.compile(r"\{\\[^A-Za-z\s]\{?[A-Za-z]\}?\}|\\[^A-Za-z\s]\{?[A-Za-z]\}?"
                         r"|\{\\[A-Za-z]+\s*\{?[A-Za-z]\}?\}|\\[A-Za-z]+\{[A-Za-z]\}|.")


def fully_braced(s):
    """True when the brace opening ``s`` is the one closing it: ``{RNS Group}``,
    not ``{\\.I} Polat`` or ``{A} and {B}``."""
    if len(s) < 2 or s[0] != "{" or s[-1] != "}":
        return False
    depth = 0
    for i, c in enumerate(s):
        depth += (c == "{") - (c == "}")
        if depth == 0:
            return i == len(s) - 1
    return False


def reformat_author(author, fragment=False):
    if len(split_names(author)) > 1:
        return " and ".join([reformat_author(a) for a in split_names(author)])

    # A name braced whole is a corporate or group author and is kept exactly
    # as given (held form 2026-09-27, KingEtal11 "{RNS System in Epilepsy
    # Study Group}"): splitting its capitals as clumped initials turned it
    # into "{ R N S System ...}". An unbraced group name is still read as a
    # personal name.
    if not fragment and fully_braced(author.strip()):
        return author.strip()

    # BibTeX's explicit ``family, suffix, given`` form must retain the suffix.
    # rearrange() deliberately removes suffixes for citation-key construction;
    # using it here used to silently discard Jr/Sr/III from author bylines.
    from bibtexparser.customization import splitname
    try:
        parts = splitname(author, strict_mode=True)
        if parts["jr"] and parts["last"] and parts["first"]:
            family = " ".join(parts["von"] + parts["last"])
            suffix = " ".join(parts["jr"]).replace(".", "")
            given = reformat_author(" ".join(parts["first"]))
            return family + ", " + suffix + ", " + given
    except (ValueError, KeyError):
        pass

    # A hyphenated-initials fragment ('X' of 'J-X') is not a whole name and is
    # not rearranged. A whole name that cannot be parsed is an error; it used
    # to be swallowed by a bare except.
    if not fragment:
        try:
            author = rearrange(author, preserve_non_letters=True)
        except Exception as exc:  # rearrange raises bare Exception for malformed names
            raise ValueError(f"cannot parse name {author!r}: {exc}") from exc

    unclumped = []
    names = author.split(" ")

    for n in names:
        # remove periods
        n = n.replace(".", "")
        if (remove_non_letters(n.lower()) not in suffixes) and (n == n.upper()):
            if n.find("-") >= 0:
                n = "-".join([reformat_author(c, fragment=True) for c in n.split("-")])
            else:
                # Split clumped initials ("MA") into letters, keeping a LaTeX accent
                # group ({\'A}, \'A, {\'{A}}) whole as one letter.
                unclumped.extend(LETTER_UNIT.findall(n))
                continue
        unclumped.append(n)

    return " ".join(unclumped)


def get_fields(bd):
    # get all fields
    fields = {}
    for k in bd.keys():
        next_entry = bd[k]
        for field, vals in next_entry.items():
            if not (field in fields.keys()):
                fields[field] = [vals]
            else:
                fields[field].append(vals)

    for k in fields.keys():
        fields[k] = list(np.unique(fields[k]))

    return fields


def polish_database(bd, errors, autofix=False, verbose=True, return_removed=False):
    keep_fields = read("keep_fields.txt")

    removed = {}
    printv("searching for extra fields...", verbose=verbose)
    x = {}
    for b in tqdm(bd.keys()):
        # printv(f'checking item {b} for extraneous fields...', verbose=verbose)
        next_item = {}
        if "force" in list(bd[b].keys()):
            printv(
                f"\tforce flag found: skipping pruning of entry [{b}]", verbose=verbose
            )
            x[b] = bd[b]
            continue
        for k in bd[b].keys():
            if k in keep_fields:
                next_item[k] = bd[b][k]
            else:
                if b in removed.keys():
                    removed[b].append(k)
                else:
                    removed[b] = [k]
                printv(f"\textraneous field detected: {b}[{k}]", verbose=verbose)
        x[b] = next_item

    if autofix:
        printv("\nautocorrecting...", verbose=verbose)
        for i in tqdm(errors.keys()):
            if i not in bd.keys():
                raise Exception(f"key {i} not found, aborting")
            elif "force" in list(bd[i].keys()):
                printv(
                    f"\tforce flag found: skipping corrections of entry [{b}]",
                    verbose=verbose,
                )
                continue

            for k in errors[i].keys():
                if k in keep_fields:
                    printv(
                        f'autocorrecting {i}[{k}] to "{errors[i][k]}"', verbose=verbose
                    )
                    x[i][k] = errors[i][k]

    # convert x to bibtexparser's entries_list format
    entries_list = []
    for k, e in x.items():
        entries_list.append(e)

    if return_removed:
        return entries_list, removed
    else:
        return entries_list


def write_bib(fname, biblist, order, indent="\t"):
    def entry2str(e):
        s = "@" + e["ENTRYTYPE"] + "{" + e["ID"] + ","
        at_least_one = False
        for k in order:
            if (k not in ["ENTRYTYPE", "ID"]) and (k in e.keys()):
                s += "\n" + indent + k.capitalize() + " = {" + e[k] + "},"
                at_least_one = True
        if at_least_one:
            s = s[:-1]  # remove last comma

        return s + "}" + "\n"

    bibtex_str = "\n".join([entry2str(b) for b in biblist])
    print(bibtex_str, file=open(fname, "w+"))


def before_letters(s, c):  # true if c occurs before the first letter in s
    for i in s:
        if i.lower() in ascii_lowercase:
            return False
        elif i == c:
            return True
    return False


def after_letters(s, c):  # true if c occurs after the last letter in s
    return before_letters(s[::-1], c)


def strip_leading_trailing_non_letters(s):
    """Strip leading and trailing non-alphabetic characters from a string.
    Returns (prefix, core, suffix) where core contains only letters and internal punctuation."""
    if len(s) == 0:
        return "", "", ""

    # Find first letter
    first_letter = -1
    for i, c in enumerate(s):
        if c.lower() in ascii_lowercase:
            first_letter = i
            break

    if first_letter == -1:  # No letters found
        return s, "", ""

    # Find last letter
    last_letter = -1
    for i in range(len(s) - 1, -1, -1):
        if s[i].lower() in ascii_lowercase:
            last_letter = i
            break

    prefix = s[:first_letter]
    core = s[first_letter : last_letter + 1]
    suffix = s[last_letter + 1 :]

    return prefix, core, suffix


def insert_non_letters(x, y):
    z = ""
    i = 0  # position in x
    j = 0  # position in y
    while (i < len(x)) and (j < len(y)):
        if x[i].lower() == y[j].lower():
            z += x[i]
            i += 1
            j += 1
        elif (
            x[i].lower() not in ascii_lowercase
        ):  # from the first case, we also know x[i] != y[j]
            z += x[i]
            i += 1
        elif (x[i].lower() in ascii_lowercase) and (
            y[j].lower() not in ascii_lowercase
        ):
            z += y[j]
            j += 1
        else:  # x[i] and y[j] are both in ascii_lowercase but x[i] != x[j] -- throw an error
            raise Exception(f'"{y}" is not a compatable template for "{x}"')

    # insert trailing punctuation from y
    if (j < len(y)) and (remove_non_letters(y[j:]) == ""):
        z += y[j:]

    # insert trailing punctuation from x
    if (i < len(x)) and (remove_non_letters(x[i:]) == ""):
        z += x[i:]

    return z


SECTION_DESIGNATION = re.compile(r"\d+[A-Za-z]?(?:\([A-Za-z0-9]{1,4}\))+[.,;:]?")


def format_title(title):
    def ends_in_punctuation(s):
        return (len(s) > 0) and (s[-1] in [".", "!", "?"])

    # remove curly braces that enclose the entire title
    # - check for "curlied" first and last words that don't extend for the entire title
    # - more complex situations are not handled (err on the side of *not* correcting the title)
    if (
        before_letters(title, "{")
        and after_letters(title, "}")
        and title.count("{") == 1
        and title.count("}") == 1
    ):
        title = title[1:-1]

    # remove '.' at the end
    if title[-1] == ".":
        title = title[:-1]

    # if any words appear in force_caps, enclose them in curly braces if not already done
    reformatted_title = []

    prev_w = ""
    curly_count = 0

    for w in title.split(" "):
        # if w contains '{', keep adding words unmodified until a '}' is found
        curly_count += w.count("{")

        if curly_count > 0:
            reformatted_title.append(w)
            prev_w = w

            curly_count -= w.count("}")
            continue

        if curly_count < 0:
            raise Exception(f"mismatched curly braces: {title}")

        # leave "a" and specified caps unchanged
        if w.lower() == "a" or (before_letters(w, "{") and after_letters(w, "}")):
            reformatted_title.append(w)
        # a statutory section with lettered subsections, kept as printed (held form
        # 2026-09-27, FoodAdmi20b "section 513(f)(2)" became "513({F})(2)")
        elif SECTION_DESIGNATION.fullmatch(w):
            reformatted_title.append(w)
        # if w contains curly braces, just append it unchanged
        elif (w.count("{") > 0) or (w.count("}") > 0):
            reformatted_title.append(w)
        else:
            # Strip leading/trailing non-letters before checking caps
            prefix, core, suffix = strip_leading_trailing_non_letters(w)
            # Only check core if it has letters
            if core:
                caps_match = [
                    f
                    for f in force_caps
                    if f.lower() == remove_non_letters(core.lower())
                ]
                if len(caps_match) > 0:
                    # Apply braces only to the core, then add back prefix and suffix
                    core_with_braces = insert_non_letters(
                        "{" + caps_match[-1] + "}", remove_curlies(core, join=" ")
                    )
                    w = prefix + core_with_braces + suffix
                elif not ends_in_punctuation(prev_w):
                    w = w.lower()
            reformatted_title.append(w)
        prev_w = w

    # capitalize the first word if it's not in force_caps
    if (
        not (
            (reformatted_title[0].count("{") > 0)
            or (reformatted_title[0].count("}") > 0)
        )
    ) and (
        remove_non_letters(reformatted_title[0].lower())
        not in [f.lower() for f in force_caps]
    ):
        reformatted_title[0] = reformatted_title[0].capitalize()

    return " ".join([r for r in reformatted_title if len(r) > 0])


def duplicate_fields(text):
    """{citation key: [field names given more than once]} in raw BibTeX text.

    bibtexparser keeps only one value of a repeated field, so a merge that
    produces two ``Doi`` lines (PR #88: OwenMann24, HeusEtal21) would pass
    silently. Scans entry bodies with the strict verification scanner's
    brace/quote rules.
    """
    from verification import top_level_parts

    found, pos = {}, 0
    while True:
        match = re.compile(r"@([A-Za-z]+)\s*([({])").search(text, pos)
        if not match:
            return found
        kind, opener = match.groups()
        closer = "}" if opener == "{" else ")"
        depth, quoted, i = 0, False, match.end()
        while i < len(text):
            c = text[i]
            if c == "\\":
                i += 2
                continue
            if c == '"' and depth == 0:
                quoted = not quoted
            elif not quoted:
                if c == closer and depth == 0:
                    break
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
            i += 1
        body, pos = text[match.end():i], i + 1
        if kind.lower() in {"comment", "string", "preamble"}:
            continue
        parts = top_level_parts(body)
        key = parts.pop(0).strip()
        names = [m[1].lower() for m in (re.match(r"\s*([\w-]+)\s*=", p) for p in parts) if m]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            found[key] = repeated


def check_bib(bibfile, autofix=False, outfile=None, verbose=True):
    if bibfile != "github" and os.path.exists(bibfile):
        with open(bibfile, "r", encoding="utf-8") as handle:
            repeated = duplicate_fields(handle.read())
        if repeated:
            raise Exception("duplicate fields found: " + "; ".join(
                f"{key}: {', '.join(names)}" for key, names in sorted(repeated.items())))
    bd = load_bibliography(bibfile)

    ids = get_vals(bd, "ID")
    authors = get_vals(bd, "author")
    years = get_vals(bd, "year")
    titles = get_vals(bd, "title")
    pages = get_vals(bd, "pages")
    journals = get_vals(bd, "journal")
    book_titles = get_vals(bd, "booktitle")
    publishers = get_vals(bd, "publisher")
    editors = get_vals(bd, "editor")
    addresses = get_vals(bd, "address")

    # check for duplicate keys
    duplicate_keys, redundant_keys = find_duplicates(
        ids, authors, titles, verbose=verbose
    )
    assert len(duplicate_keys) == 0, "duplicate keys found: " + ", ".join(
        duplicate_keys
    )
    assert len(redundant_keys) == 0, "redundant keys found: " + ", ".join(
        [str([ids[i] for i in d]) for d in redundant_keys]
    )
    printv("\n", verbose=verbose)

    # check for bibitem key bases
    fix_dict = {}
    fix_dict["ID"] = check_entries(
        "ID",
        bd,
        [authors2key(a, y) for a, y in zip(key_names(bd), years)],
        same=same_id,
        verbose=verbose,
    )

    # check for bibitem key suffixes
    target_keys = check_key_suffixes(bd)
    fix_dict["ID"].extend(check_entries("ID", bd, target_keys, verbose=verbose))

    # check page numbers: ambiguous pages
    target_pages, unfixable = generate_correct_pages(bd)
    if len(unfixable) > 0:
        msg = f"The following page numbers are ambiguous or incorrect: \n"
        msg += "\n".join([f"{i}: {p}" for i, p in unfixable])
        raise Exception(msg)
    else:
        printv("No ambiguous page numbers were found.", verbose=verbose)
    printv("\n", verbose=verbose)

    # check page numbers: correctable formatting
    fix_dict["pages"] = check_entries("pages", bd, target_pages, verbose=verbose)

    # check journal names
    fix_dict["journal"] = check_entries(
        "journal", bd, [format_journal_name(j) for j in journals], verbose=verbose
    )

    # check book titles
    fix_dict["booktitle"] = check_entries(
        "booktitle", bd, [format_journal_name(b) for b in book_titles], verbose=verbose
    )

    # check article titles
    fix_dict["title"] = check_entries(
        "title", bd, [format_title(t) for t in titles], verbose=verbose
    )

    # check publishers
    fix_dict["publisher"] = check_entries(
        "publisher",
        bd,
        [format_journal_name(p, key=publisher_key, dotted_initials=True) for p in publishers],
        verbose=verbose,
    )

    # check author names
    fix_dict["author"] = check_entries(
        "author", bd, [reformat_author(a) for a in authors], verbose=verbose
    )

    # check editor names
    fix_dict["editor"] = check_entries(
        "editor", bd, [reformat_author(e) for e in editors], verbose=verbose
    )

    # check addresses
    fix_dict["address"] = check_entries(
        "address",
        bd,
        [
            format_journal_name(a, key=address_key, force_caps=address_codes)
            for a in addresses
        ],
        verbose=verbose,
    )

    # reorganize fix_dict by key
    fields = fix_dict.keys()
    errors = {}
    for k in fields:
        for i in fix_dict[k]:
            if i[0] not in errors.keys():
                errors[i[0]] = {}
            errors[i[0]][k] = i[2]

    # remove extra fields, correct entries if autofix = True
    polished_bd, removed = polish_database(
        bd, errors, autofix=autofix, verbose=verbose, return_removed=True
    )
    if not autofix:
        assert len(removed) == 0, (
            "the following entries have non-essential fields: " + ", ".join(removed)
        )

    if outfile is not None:
        keep_fields = read("keep_fields.txt")
        keep_fields.sort()
        write_bib(outfile, polished_bd, keep_fields)

    return errors, polished_bd


def compare_bibs(a, b, verbose=True, return_summary=False, outfile=None):
    if type(a) == str:
        a = load_bibliography(a)

    if type(b) == str:
        b = load_bibliography(b)

    def keys_compare(a, b):
        x = set(a.keys())
        y = set(b.keys())

        return (
            list(x - y),
            list(y - x),
            list(set.intersection(x, y)),
        )  # a only, b only, both

    summary = ""

    a_only, b_only, both = keys_compare(a, b)
    if len(a_only) > 0:
        summary += "removed the following entries: " + ", ".join(a_only)
        if len(b_only) > 0:
            summary += "\n\n"
    if len(b_only) > 0:
        summary += "added the following entries: " + ", ".join(b_only)

    added = {}
    deleted = {}
    modified = {}
    for i in tqdm(both):
        old_keys, new_keys, both_keys = keys_compare(a[i], b[i])
        if len(old_keys) > 0:
            deleted[i] = old_keys
        if len(new_keys) > 0:
            added[i] = new_keys

        next_modified = []
        for j in both_keys:
            if not (a[i][j] == b[i][j]):
                next_modified.append(j)
        if len(next_modified) > 0:
            modified[i] = next_modified

    if (len(a_only) > 0) or (len(b_only) > 0):
        summary += "\n\n"

    changed = list(
        set.union(
            set.union(set(added.keys()), set(deleted.keys())), set(modified.keys())
        )
    )
    if len(changed) > 0:
        summary += "modified the following entries: " + ", ".join(changed)

    modified = len(summary) > 0
    if outfile:
        printv(f"writing summary of changes to file: {outfile}", verbose=verbose)
        print(summary, file=open(outfile, "w+"))

    if modified:
        printv(summary, verbose=verbose)
    else:
        printv("bibliographies are functionally identical", verbose=verbose)

    if return_summary:
        return not modified, summary
    else:
        return not modified
