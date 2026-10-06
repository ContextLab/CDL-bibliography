from unidecode import unidecode as decode
from string import ascii_lowercase
from urllib import request as get
from tqdm import tqdm

import bibtexparser as bp
import numpy as np
import pandas as pd

import re
import functools
import itertools
import os
import sys


from .resources import data_path


def read(fname):
    return pd.read_csv(data_path(fname), header=None).values.flatten().tolist()


def load_key(fname):
    key = pd.read_excel(data_path(fname), header=0, index_col="orig")
    return key.to_dict()["corrected"]


prefixes = read("prefixes.txt")
suffixes = read("suffixes.txt")
uncaps = read("uncaps.txt")
force_caps = read("caps.txt")
address_codes = read("addresses.txt")

journal_key = load_key("journal_key.xls")
publisher_key = load_key("publisher_key.xls")
address_key = load_key("address_key.xls")

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
        b = get.build_opener().open(fname).read().decode("utf-8")   # not urlopen: it keeps its first proxies
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
    """``s`` without its matching braces. The spaces directly inside the first matched pair
    are replaced by ``join``; a space inside any other matched pair is dropped (with ``join``
    a space, so is one inside a pair nested in the first).

    One pass with a stack, in time proportional to the length. It gives what the earlier
    form gave, which removed the first matched pair and called itself on the result: that
    form exhausted the call stack on a value with a thousand pairs and took time in
    proportion to the square of the length."""
    if "{" not in s or "}" not in s:
        return s
    closes, stack = {}, []
    for i, c in enumerate(s):
        if c == "{":
            stack.append(i)
        elif c == "}" and stack:
            closes[stack.pop()] = i
    if not closes:
        return s
    first = min(closes)
    first_close, closers = closes[first], set(closes.values())
    out, depth = [], 0
    for i, c in enumerate(s):
        if i in closes:
            depth += 1
        elif i in closers:
            depth -= 1
        elif c == " " and depth:
            if first < i < first_close:
                out.append(join if join != " " or depth == 1 else "")
        else:
            out.append(c)
    return "".join(out)


@functools.lru_cache(maxsize=65536)  # a pure function of its text; format_title calls it per list word
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


# Dotted abbreviations in an organization's name, read as the words they stand for when
# the organization's key part is taken (user, 2026-09-30: "'U.S.' decomposes to 'United
# States' so the first 4 letters are 'Unit'"). Only well-established forms, matched as a
# whole word exactly as printed; an undotted 'US' or an unlisted dotted form is unchanged.
ORGANIZATION_ABBREVIATIONS = {
    "U.S.": "United States",
    "U.S.A.": "United States of America",
    "U.K.": "United Kingdom",
    "U.N.": "United Nations",
}


def organization_key(name):
    """Key part of a fully braced (organization/group) author: the letters of its
    successive words, concatenated until 4 letters are reached, then truncated to 4,
    with the capitalization as printed (user rule 2026-09-28, docs/decision-log.md
    "Organization authors in keys": "use as many organization 'words' as are available,
    until 4 letters are achieved"). A dotted abbreviation in ORGANIZATION_ABBREVIATIONS
    counts as the words it stands for (user, 2026-09-30): {R Core Team} -> RCor,
    {U.S. Food and Drug Administration} -> Unit, {RNS System ...} -> RNSS, {Centers for
    Disease Control and Prevention} -> Cent. A name with fewer than 4 letters in all
    keeps what it has. None for any other name ({van der Meer} inside a personal name is
    not braced whole)."""
    name = name.strip()
    if not fully_braced(name):
        return None
    inner = name[1:-1].strip()
    while fully_braced(inner):  # the formatter's double-braced form
        inner = inner[1:-1].strip()
    words = []
    for word in remove_accents_and_hyphens(decode(inner)).split():
        words += ORGANIZATION_ABBREVIATIONS.get(remove_curlies(word), word).split()
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
        if not ("force" in list(bd[i].keys()) or same(proc(v), proc(t)))
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
    with no author (``editor`` only), the editors (stage 2B-i, 2026-09-25; the
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


# Traditional (GPO/AP-style) US state abbreviations, dotted or not, and the house's
# two-letter code for each. The house address form is "City, {ST}"; an address whose
# last comma component is one of these is written with the code (Albe00 "Cambridge,
# Mass." passed bibcheck because address_key.xls only lists "cambridge, mass" without
# the period). Two-letter codes themselves are in addresses.txt and need no entry.
US_STATE_ABBREVIATIONS = {
    "ala": "AL", "ariz": "AZ", "ark": "AR", "calif": "CA", "cal": "CA", "colo": "CO",
    "conn": "CT", "del": "DE", "d c": "DC", "fla": "FL", "ga": "GA", "ill": "IL",
    "ind": "IN", "kans": "KS", "kan": "KS", "ky": "KY", "la": "LA", "md": "MD",
    "mass": "MA", "mich": "MI", "minn": "MN", "miss": "MS", "mo": "MO", "mont": "MT",
    "nebr": "NE", "neb": "NE", "nev": "NV", "n h": "NH", "n j": "NJ", "n mex": "NM",
    "n m": "NM", "n y": "NY", "n c": "NC", "n dak": "ND", "n d": "ND", "okla": "OK",
    "oreg": "OR", "ore": "OR", "pa": "PA", "penn": "PA", "penna": "PA", "r i": "RI",
    "s c": "SC", "s dak": "SD", "s d": "SD", "tenn": "TN", "tex": "TX", "vt": "VT",
    "va": "VA", "wash": "WA", "w va": "WV", "wis": "WI", "wisc": "WI", "wyo": "WY",
}


def us_state_code(component):
    """The two-letter code for a traditional state abbreviation ("Mass.", "N.Y.",
    "Calif", "{N}.{J}."), or None. Braces, periods and spacing are ignored; two-letter
    codes already in house form ("{MA}", "MA") return None and are left to addresses.txt."""
    plain = remove_curlies(component).strip()
    if re.fullmatch(r"[A-Z]{2}", plain):
        return None
    letters = re.sub(r"\s+", " ", re.sub(r"\.", " ", plain)).strip().lower()
    return US_STATE_ABBREVIATIONS.get(letters)


# A compound acronym joined by "\&" ("AT\&T", "R\&D"): each side is one to three letters.
AMPERSAND_ACRONYM = re.compile(r"[A-Za-z]{1,3}(?:\\&[A-Za-z]{1,3})+")


def compound_acronym(core, force_caps):
    r"""The caps form of a compound acronym, or None.

    "AT\&T" and "At\&t" -> "AT\&T" (every side of a "\&" is one to three letters);
    "ieee/acm" -> "IEEE/ACM" when every "/"-separated part is a caps.txt word. The
    word-capitalizing rule turned "AT\&T" into "At\&t" (JuanRabi85, RabiEtal85), and a
    braced "{ieee/acm}" was protected as given (PimeEtal19, Ande04, TardEtal08).
    """
    plain = remove_curlies(core)
    if AMPERSAND_ACRONYM.fullmatch(plain):
        return plain.upper()
    parts = plain.split("/")
    if len(parts) < 2 or not all(re.fullmatch(r"[A-Za-z]+", q) for q in parts):
        return None
    forms = []
    for q in parts:
        listed = [f for f in force_caps if f.lower() == q.lower()]
        if not listed:
            return None
        forms.append(remove_curlies(listed[-1]))
    return "/".join(forms)


# A word in parentheses given with two or more capitals ("(COMSNETS)", "(MobiSys)") is an
# acronym as printed. The word-capitalizing rule lowercased it ("(comsnets)"), and a
# lowercased acronym later braced ("({comsnets})") was then protected as given.
PAREN_ACRONYM = re.compile(r"\((?:[A-Za-z]*[A-Z][A-Za-z]*[A-Z][A-Za-z]*)\)?[.,;:]?")


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


# LaTeX in a name is case-sensitive, and the word rules below re-case words. A name is therefore
# read ONCE, left to right, into tokens, and the rules are applied to plain tokens only; the
# opaque tokens are written out exactly as they were given, and the result is the tokens put
# together again. Nothing is looked for in a re-cased copy of the text.
#
# Opaque tokens:
#   - a control sequence with the optional "[...]" and braced arguments that follow it
#     ("\LaTeX", "\emph{Drosophila}", "\textcolor[RGB]{0,0,0}{Title}", an accent "\"{o}" or "\'e");
#   - a braced group that holds a group, a command, mathematics or a space
#     ("{\"o}", "{{Mixed} Case}", "{Lopes da Silva}");
#   - mathematics: "$...$" and "\(...\)".
# Plain: everything else, with an escaped character ("\{", "\}", "\$", "\%", "\&", "\_", "\#")
# read as that character, and a braced group of one word without a command ("{IEEE}",
# "{University}", "{Tcl/Tk}"), which the word rules own (the caps list, unbrace_ordinary).
#
# A value whose braces or mathematics do not balance is not formatted at all: the formatters
# return it unchanged, and the format check reports it (``unformattable``). So is a value of
# more than MAX_NAME_LENGTH characters. Nothing is guessed about either.
MAX_NAME_LENGTH = 5000
_ESCAPED = frozenset("{}$%&_#,;")


class Unbalanced(ValueError):
    """Braces or mathematics that do not balance: the value has no reading as tokens."""


def name_tokens(text):
    """``text`` as [(opaque, text), ...] in order (see above); the texts joined are ``text``.
    One pass: every character is looked at once, whatever the input. Raises ``Unbalanced``."""
    tokens, plain, i, size = [], [], 0, len(text)
    last_bracket = text.rfind("]")

    def group(at):
        """The index after the brace group opening at ``at`` (nested groups included)."""
        depth, k = 0, at
        while k < size:
            ch = text[k]
            if ch == "\\":
                k += 2
                continue
            depth += (ch == "{") - (ch == "}")
            k += 1
            if depth == 0:
                return k
        raise Unbalanced("a brace that is never closed")

    def opaque(end):
        nonlocal i
        if plain:
            tokens.append((False, "".join(plain)))
            plain.clear()
        tokens.append((True, text[i:end]))
        i = end

    while i < size:
        ch = text[i]
        if ch == "\\":
            following = text[i + 1:i + 2]
            if following == "(":
                close = text.find("\\)", i + 2)
                if close < 0:
                    raise Unbalanced("mathematics that is never closed")
                opaque(close + 2)
            elif following.isascii() and following.isalpha():
                j = i + 2
                while j < size and text[j].isascii() and text[j].isalpha():
                    j += 1
                while j < size:                     # its arguments: "[...]" and braced groups
                    if text[j] == "{":
                        j = group(j)
                    elif text[j] == "[" and j < last_bracket:
                        j = text.index("]", j) + 1
                    else:
                        break
                opaque(j)
            elif following == "" or following in _ESCAPED or following == "\\":
                plain.append(text[i:i + 2])       # an escaped character is that character
                i += 2
            else:                                   # an accent: the symbol and the letter it marks
                j = i + 2
                if text[j:j + 1] == "{":
                    j = group(j)
                elif j < size and text[j].isalnum():
                    j += 1
                opaque(j)
        elif ch == "$":
            close = text.find("$", i + 1)
            while close > 0 and text[close - 1] == "\\":
                close = text.find("$", close + 1)
            if close < 0:
                raise Unbalanced("mathematics that is never closed")
            opaque(close + 1)
        elif ch == "{":
            j = group(i)
            inner = text[i + 1:j - 1]
            if any(c in inner for c in "{}$ ") or "\\" in inner.replace("\\&", ""):
                opaque(j)
            else:
                plain.append(text[i:j])            # a braced word: the word rules own it
                i = j
        elif ch == "}":
            raise Unbalanced("a brace that closes nothing")
        else:
            plain.append(ch)
            i += 1
    if plain:
        tokens.append((False, "".join(plain)))
    return tokens


def unformattable(value):
    """Why ``value`` cannot be formatted (and is left unchanged by every formatter here), or
    None: it is longer than MAX_NAME_LENGTH, or its braces or mathematics do not balance."""
    if len(value) > MAX_NAME_LENGTH:
        return f"longer than {MAX_NAME_LENGTH} characters"
    try:
        name_tokens(value)
    except Unbalanced as exc:
        return str(exc)
    return None


def _token_words(tokens):
    """The words of a tokenised name: each a list of (opaque, text) parts. Words are divided
    by the spaces of plain tokens only (a space inside an opaque token divides nothing)."""
    words, current = [], []
    for is_opaque, text in tokens:
        if is_opaque:
            current.append((True, text))
            continue
        pieces = text.split(" ")
        for index, piece in enumerate(pieces):
            if index:
                words.append(current)
                current = []
            if piece:
                current.append((False, piece))
    words.append(current)
    return words


def _mixed_word(parts, inside):
    """A word that holds an opaque token: the opaque tokens as given, and the plain text
    between them in lower case with a capital where the word rules put one for any word (the
    first letter of the word and of each hyphenated part, when a letter stands there). A word
    of the uncaps list inside a name gets no capital, as any such word."""
    whole = "".join(text for _, text in parts)
    capitals = not (inside and whole.lower() in uncaps)
    out, at_start = [], True
    for is_opaque, text in parts:
        if is_opaque:
            out.append(text)
            at_start = False
            continue
        k = 0
        while k < len(text):
            ch = text[k]
            if ch == "\\":                          # an escaped character: itself
                out.append(text[k:k + 2])
                k += 2
                at_start = False
                continue
            if ch.isalpha():
                out.append(ch.upper() if at_start and capitals else ch.lower())
                at_start = False
            else:
                out.append(ch)
                at_start = ch == "-" or (at_start and ch in "([")
            k += 1
    return "".join(out)


def format_journal_name(n, key=journal_key, force_caps=force_caps, dotted_initials=False,
                        drop_countries=None, acronyms=False, ordinals=False):
    """Format a journal, booktitle, publisher or address name.

    The name is read into tokens once (``name_tokens``) and the word rules are applied to its
    plain words only; a value that cannot be read (``unformattable``) is returned unchanged.
    ``acronyms`` and ``ordinals``: the two rules of a book title (``format_booktitle``).

    ``drop_countries`` (addresses; default: on exactly when ``key`` is address_key):
    an alias target never adds a country the name does not print (see
    drop_added_country). Journal titles are exempt: the USA in "Proceedings of the
    National Academy of Sciences, USA" is part of the title, not an address.

    ``dotted_initials`` (publishers): a word made only of capital initials, with or
    without periods or braces ("W.H.", "V.", "{W}.", "W"), is written in the house
    initials style, undotted and space-separated: "W.H. Freeman" -> "W H Freeman"
    (user decision 2026-09-25 07:37 EDT, reversing stage 2B-i's dotted form). The
    word-capitalizing rule used to turn "W.H. Freeman" into "W.h. Freeman" (Marr82),
    and force_caps braced undotted initials ("{W} {H} Freeman").
    """
    if unformattable(n):
        return n
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
        # Two names whose braces used to block their alias ("The {American} Journal of
        # Psychology", Youn61; "The {Oxford} Handbook of Memory", five chapters). The
        # aliases drop the leading "The" that the printed titles carry; removing the
        # braces that protect nothing (unbrace_ordinary, 2026-09-29) must not change
        # the text, so the titles are kept as given.
        "the american journal of psychology",
        "the oxford handbook of memory",
    }
    # An alias that only cuts a hyphenated suffix ("journal of physiology-paris" ->
    # "journal of physiology") names a different journal, not a spelling variant of
    # the same one (LachEtal03); the name is formatted as given instead.
    if force_caps is address_codes and "," in n:
        # "Cambridge, Mass." -> "Cambridge, MA" (house form "City, {ST}")
        head, _, last = n.rpartition(",")
        code = us_state_code(last)
        if code is not None:
            n = f"{head}, {code}"
    alias = key.get(n.lower()) if isinstance(key.get(n.lower()), str) else None
    if drop_countries is None:
        drop_countries = key is address_key
    if alias is not None and drop_countries:
        alias = drop_added_country(n, alias)  # an alias never adds an unprinted country
    cuts_suffix = alias is not None and re.fullmatch(
        re.escape(alias.lower()) + r"-\w[\w ]*", n.lower()) is not None
    aliased = n.lower() not in preserve_identity and alias is not None and not cuts_suffix
    mixed, name_has_lower = {}, False
    if aliased:
        n = alias
        as_given = n.split(" ")
        words = n.split(" ")
    else:
        # The name is read into tokens once; a word that holds an opaque token is written by
        # _mixed_word and none of the word rules below is applied to it.
        token_words = _token_words(name_tokens(n))
        as_given = ["".join(text for _, text in parts) for parts in token_words]  # dotted initials keep their capitals
        mixed = {i: parts for i, parts in enumerate(token_words) if any(o for o, _ in parts)}
        name_has_lower = any(c.islower() for i, w in enumerate(as_given) if i not in mixed for c in w)
        if acronyms and name_has_lower:
            # Book titles: a part of a plain word given with two or more capitals is braced as given.
            as_given = [w if i in mixed or any(c in w for c in "{}\\$") else "-".join(_braced_acronym(q) for q in w.split("-"))
                        for i, w in enumerate(as_given)]
        words = [w.lower() for w in as_given]
        n = " ".join(words)
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
        if i in mixed:
            words[i] = _mixed_word(mixed[i], i > 0)
            continue
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
            compound = core and compound_acronym(core, force_caps)
            if compound:
                pre, _, suf = strip_leading_trailing_non_letters(
                    remove_curlies(given, join=" ") if given_braced else given)
                words[i] = pre + "{" + compound + "}" + suf
                continue
            if (not given_braced and PAREN_ACRONYM.fullmatch(given) and not listed):
                pre, core_given, suf = strip_leading_trailing_non_letters(given)
                words[i] = pre + "{" + core_given + "}" + suf
                continue
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
            # "(proceedings" -> "(Proceedings": capitalize the first letter after an
            # opening parenthesis or bracket, not the parenthesis ("(Eurospeech 2003)"
            # became "(eurospeech 2003)").
            if prefix and re.fullmatch(r"[(\[]+", prefix):
                words[i] = prefix + core.capitalize() + suffix

            # deal with hyphens
            if len(w.split("-")) > 1:
                # each part as it was given, so that a braced part keeps what it holds
                words[i] = "-".join(
                    format_journal_name(c, key=key, force_caps=force_caps,
                                        drop_countries=drop_countries)
                    for c in (w if aliased else as_given[i]).split("-")
                )

            if (i > 0) and (w.lower() in uncaps):
                words[i] = words[i].lower()

            # a name with a one-letter elided prefix keeps the capital given
            # after the apostrophe (held form 2026-09-27, BirdEtal09 "O'Reilly"
            # became "O'reilly"); "Scribner's", or "L'année" given in lower case, is unaffected.
            if not aliased and re.fullmatch(r"[A-Z]'[A-Z][a-z]+\W*", as_given[i]) \
                    and re.fullmatch(r"[A-Z]'[a-z]+\W*", words[i]):
                words[i] = words[i][:2] + words[i][2].upper() + words[i][3:]
    for i, w in enumerate(words):
        if i not in mixed:
            words[i] = "-".join(unbrace_ordinary(part, i > 0) for part in w.split("-"))
    if ordinals:
        # House ordinals, in the runs of words that hold no opaque token.
        out, run = [], []
        for i, w in enumerate(words + [None]):
            if w is not None and i not in mixed:
                run.append(w)
                continue
            if run:
                out.append(_meeting_ordinals(_plain_ordinals(" ".join(run))))
                run = []
            if w is not None:
                out.append(w)
        return " ".join(out)
    return " ".join(words)


# A braced word that is only ordinary title-case capitalization: a capital, then lower-case
# letters, optionally a possessive "'s" ("{University}", "{Oxford}", "{Alzheimer's}"), with
# only non-letter, non-brace, non-command characters around it ("({European}",
# "{American},"). Acronyms ("{IEEE}", "{MIT}", "{AT\&T}", single letters "{A}"), internal
# capitals ("{NeuroImage}", "{PLoS}"), deliberate lower case ("{npj}", "{e}") and anything
# holding a LaTeX command or accent ("{\"u}") do not match and keep their braces.
ORDINARY_BRACED = re.compile(r"([^A-Za-z{}\\]*)\{([A-Z][a-z]+(?:'s)?)\}([^A-Za-z{}\\]*)")


def unbrace_ordinary(word, inside):
    """Drop braces that protect nothing in a journal, booktitle, publisher or address.

    These fields are printed in title case as given (BibTeX styles do not change their
    case), so "{University}" prints exactly as "University". caps.txt braced every listed
    word, which put braces around ordinary capitalized words ("Harvard {University} Press",
    "{Oxford} {University} Press", "{American} Journal of Psychology"; user decision
    2026-09-29). A word in uncaps.txt ("{Of}", "{The}") inside a name keeps its braces,
    because without them this formatter would lower-case it. Article titles (format_title,
    sentence case) are not affected: there the braces protect proper nouns.
    """
    m = ORDINARY_BRACED.fullmatch(word)
    if m is None or (inside and m[2].lower() in uncaps):
        return word
    return m[1] + m[2] + m[3]


# --- book and proceedings titles: house ordinals and acronyms (owner decisions 2026-10-06) ---------
#
# Ordinals are written as a numeral with a superscript suffix, the form the library already
# uses: ``30\textsuperscript{th}``. An acronym keeps its capitals, protected by braces
# (``{IEEE}``, ``{ACM}``), as capitals are protected elsewhere in the library.

# A plain numeric ordinal ("30th"), not already inside braces or a command.
PLAIN_ORDINAL = re.compile(r"(?<![\w\\{])(\d+)(st|nd|rd|th)(?![\w}])", re.I)
# Words that may stand between the number of a meeting and the word that names the meeting:
# "the Fifth Annual Workshop", "the Twenty-Third Annual International Conference".
MEETING_QUALIFIERS = ("annual", "biennial", "biannual", "triennial", "international", "national", "joint",
                      "european", "asian", "pacific", "world", "regional")
MEETING_NOUNS = ("conference", "conferences", "workshop", "workshops", "symposium", "symposia", "meeting",
                 "meetings", "congress", "colloquium", "convention", "seminar", "forum")


def house_ordinal(number):
    r"""30 -> ``30\textsuperscript{th}``, 21 -> ``21\textsuperscript{st}``, 112 -> ``112\textsuperscript{th}``."""
    from .verification import numeric_ordinal
    text = numeric_ordinal(number)
    digits = str(number)
    return digits + "\\textsuperscript{" + text[len(digits):] + "}"


def _plain_ordinals(text):
    """``30th`` -> ``30\\textsuperscript{th}``. A numeral with the wrong suffix ("3th") is not an
    ordinal anyone can vouch for and is left as written; a cardinal ("30") is never touched."""
    from .verification import numeric_ordinal

    def write(match):
        number = int(match[1])
        if numeric_ordinal(number) != str(number) + match[2].lower() or match[1] != str(number):
            return match[0]
        return house_ordinal(number)
    return PLAIN_ORDINAL.sub(write, text)


def _ordinal_words():
    """A pattern for one ordinal word or compound ("Fifth", "Twenty-Third", "twenty third"), with
    the tens word in group 1 and the ordinal word in group 2, and its value."""
    from .verification import _ORDINAL_TENS, _ORDINAL_UNITS, _ORDINAL_WORDS
    words = "|".join(sorted(_ORDINAL_WORDS, key=len, reverse=True))
    pattern = re.compile(r"(?<![\w\\{-])(?:(" + "|".join(_ORDINAL_TENS) + r")[- ])?(" + words + r")(?![\w}-])", re.I)

    def value(match):
        tens, word = (match[1] or "").lower(), match[2].lower()
        if tens:
            return _ORDINAL_TENS[tens] + _ORDINAL_UNITS[word] if word in _ORDINAL_UNITS else None
        return _ORDINAL_WORDS[word]
    return pattern, value


def _numbers_a_meeting(rest):
    """Whether the text after an ordinal word shows the ordinal to be the number of a meeting:
    the next word names a meeting ("Second Workshop"), with nothing between them but words of
    MEETING_QUALIFIERS and braced acronyms ("Fourth Annual {USENIX} {Tcl/Tk} Workshop"). The
    ordinal of "Second Language Acquisition" or "Twenty-First-Century University" is part of
    the title's wording and numbers nothing."""
    if not rest.startswith(" "):
        return False
    for word in rest[:MEETING_WINDOW].split():
        core = word.strip(",;:.()").lower()
        if core in MEETING_NOUNS:
            return True
        if core in MEETING_QUALIFIERS or re.fullmatch(r"\(?\{[^{}\s]+\}(?:-\{[^{}\s]+\})*\)?[,;:.]?", word):
            continue
        return False
    return False


def _meeting_ordinals(text):
    """An ordinal word that numbers a meeting, as a house ordinal: "the Fifth Annual Workshop" ->
    ``the 5\\textsuperscript{th} Annual Workshop``. Any other ordinal word stays as written."""
    pattern, value = _ordinal_words()

    def write(match):
        number = value(match)
        if number is None or not _numbers_a_meeting(text[match.end():match.end() + MEETING_WINDOW]):
            return match[0]
        return house_ordinal(number)
    return pattern.sub(write, text)


# A part of a word given with two or more capitals ("NAACL", "MobiSys", "IEEE/CVF", "McGaugh").
_WORD_PART = re.compile(r"[A-Za-z0-9/&+.']+")   # one character class, one quantifier: read in one pass
# How far after an ordinal word the word that names the meeting is looked for.
MEETING_WINDOW = 160


def _two_capitals(part):
    """Whether ``part`` is letters, digits and ``/&+.'`` only and has two or more capitals
    ("NAACL", "MobiSys", "IEEE/CVF", "McGaugh"). The characters are checked by one pattern of
    one class and the capitals are counted, so the time is in proportion to the length."""
    return bool(_WORD_PART.fullmatch(part)) and sum("A" <= c <= "Z" for c in part) >= 2


@functools.lru_cache(maxsize=None)
def _caps_words():
    return frozenset(str(f).lower() for f in force_caps)


def _braced_acronym(part):
    """A hyphen-part of a plain word, in braces as given when it has two or more capitals:
    "NAACL" -> "{NAACL}", "(MobiSys)" -> "({MobiSys})". A caps.txt word (alone or in a "/"
    compound, which keeps its caps.txt form) and a name with an elided prefix ("O'Reilly")
    are left to the word rules."""
    pre, core, suf = strip_leading_trailing_non_letters(part)
    if (not core or not _two_capitals(core) or re.fullmatch(r"[A-Z]'[A-Z][a-z]+", core)
            or remove_non_letters(core.lower()) in _caps_words() or compound_acronym(core, force_caps)):
        return part
    return pre + "{" + core + "}" + suf


def format_booktitle(name):
    r"""The format checker's formatter for ``booktitle``: format_journal_name, and the two house
    rules for the titles of books and proceedings (owner decisions 2026-10-06).

    - A part of a word given with two or more capitals keeps them, in braces: "NAACL-HLT" ->
      "{NAACL}-{HLT}", "(MobiSys)" -> "({MobiSys})", "IEEE/CVF" -> "{IEEE/CVF}" (see
      ``_braced_acronym`` for what is left alone).
    - Ordinals are numerals with a superscript suffix: "30th" -> ``30\textsuperscript{th}``
      wherever it stands, and an ordinal word that numbers a meeting ("the Thirtieth Annual
      Conference") likewise. No ordinal is made from a cardinal, and an ordinal word that is
      part of a title's wording ("Second Language Acquisition") is not rewritten.
    """
    return format_journal_name(name, acronyms=True, ordinals=True)


@functools.lru_cache(maxsize=None)
def pending_forms():
    """{(key, field): (value, proposed)} from data/pending_house_forms.json: entries of the
    library written the way a house rule decided later now changes. The format check
    (``check_bib``) names such an entry and does not count it as an error while its value is
    exactly ``value`` and the formatter's is exactly ``proposed``. The rule holds for every
    other entry, and for a listed entry as soon as its value is anything else."""
    import json
    listed = json.loads(data_path("pending_house_forms.json").read_text(encoding="utf-8"))["entries"]
    return {(item["key"], item["field"]): (item["value"], item["proposed"]) for item in listed}


# "2d", "3d", "22d": a library catalogue's older abbreviation of 2nd, 3rd, 22nd ("2d ed.").
_CATALOGUE_ORDINAL = re.compile(r"(?<![\w\\{])(\d{1,3})d(?![\w}])")


def _catalogue_ordinal(match):
    number = int(match[1])
    written = house_ordinal(number)
    return written if match[1] == str(number) and written.endswith(("{nd}", "{rd}")) else match[0]


def format_edition(value):
    r"""The format checker's formatter for ``edition``: an ordinal, as a word or a plain
    numeral, is written as a numeral with a superscript suffix ("Second", "2nd" ->
    ``2\textsuperscript{nd}``). In this field an ordinal is the number of the edition wherever
    it stands. An ordinal followed by nothing but the word for an edition ("Second edition",
    "2nd ed.") is written as the ordinal alone, as the library's editions are and as the
    research route writes them (``research_forms.normalise_edition``). Everything else stays
    as written ("Rev. and expanded"); a cardinal is not made an ordinal."""
    if unformattable(value):
        return value
    pattern, number = _ordinal_words()

    def plain(text):
        text = pattern.sub(lambda m: m[0] if number(m) is None else house_ordinal(number(m)), text)
        return _plain_ordinals(_CATALOGUE_ORDINAL.sub(_catalogue_ordinal, text))
    # the ordinal rules on the plain tokens only; what a command or a group holds is not read
    text = "".join(part if is_opaque else plain(part) for is_opaque, part in name_tokens(value))
    alone = re.fullmatch(r"\s*(\d+\\textsuperscript\{(?:st|nd|rd|th)\})\s+(?:ed\.?|edn\.?|edition)\s*", text, re.I)
    return alone[1] if alone else text


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
    from .name_parsing import splitname
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
    from .verification import top_level_parts

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

    # an entry without a title cannot be judged (format_title read title[-1]: IndexError)
    untitled = [i for i, t in zip(ids, titles) if not str(t).strip()]
    if untitled:
        raise Exception("title: missing: " + ", ".join(untitled))

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

    # A name that cannot be read into tokens (braces or mathematics that do not balance, or a
    # value too long to be a name) is not formatted and not guessed at: it is reported, as an
    # ambiguous page range is.
    unread = []
    for i in ids:
        if "force" in bd[i]:
            continue
        for name in ("journal", "booktitle", "publisher", "address", "edition"):
            why = unformattable(str(bd[i].get(name) or ""))
            if why:
                unread.append(f"{i}: {name}: {why}")
    if unread:
        raise Exception("The following fields cannot be formatted: \n" + "\n".join(unread))

    # check journal names
    fix_dict["journal"] = check_entries(
        "journal", bd, [format_journal_name(j) for j in journals], verbose=verbose
    )

    # check book titles
    fix_dict["booktitle"] = check_entries(
        "booktitle", bd, [format_booktitle(b) for b in book_titles], verbose=verbose
    )

    # check editions
    fix_dict["edition"] = check_entries(
        "edition", bd, [format_edition(e) for e in get_vals(bd, "edition")], verbose=verbose
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

    # Entries written the way a house rule decided later now changes (pending_forms) are
    # named on every run and are not errors: nothing here, and no autofix, changes them.
    waiting = pending_forms()
    held = [(k, i) for k in fix_dict for i in fix_dict[k] if waiting.get((i[0], k)) == (i[1], i[2])]
    for k, i in held:
        fix_dict[k].remove(i)
    if held:
        print(f"{len(held)} entr{'y is' if len(held) == 1 else 'ies are'} written in a form a house rule now "
              "changes; left as written, and no error, until the owner approves the change:")
        for k, i in held:
            print(f'{i[0]}: \t{k} "{i[1]}" would be "{i[2]}"')

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
