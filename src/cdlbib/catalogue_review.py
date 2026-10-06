"""Strict edition-level checks for printed books with complete author or editor bylines."""
from copy import deepcopy
import hashlib
import re
import unicodedata
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from .name_parsing import splitname
from .catalogue_discovery import M, MAX_BYTES, fetch_search, parse_search, search_query
from .verification import (author_evidence, compare_record, current_results,
                          export_snapshot, given_name_tokens, given_token_matches,
                          load_entries, normalize_book_publisher, normalize_title, normalized, outcome, run_lock,
                          split_authors, validate_output_path, write_report)

# Policy 7 re-opens unresolved books for the widened grammar (see
# verification/catalogue-phase0-2026-09-22/README.md). Records that the
# policy-6 grammar parses are still parsed by it, byte-for-byte unchanged.
CATALOGUE_POLICY = "7"
WIDENED_GRAMMAR = "7"

# LOC 008/15-17 identifies the first named publication jurisdiction. These
# exact state forms are confined to publication addresses, never paper text.
# https://www.loc.gov/marc/bibliographic/bd008a.html
# https://www.loc.gov/marc/countries/countries_regional.html
STATE_FORMS = {'mau': {'ma', 'mass', 'massachusetts'},
               'nyu': {'ny', 'n.y', 'new york'},
               'cau': {'ca', 'calif', 'california'},
               # Added with policy 7: the same exact-code rule for the other
               # jurisdictions that occur in cached records. 'enk' is England,
               # which the United Kingdom forms name unambiguously.
               'nju': {'nj', 'n.j', 'new jersey'},
               'ilu': {'il', 'ill', 'illinois'},
               'ctu': {'ct', 'conn', 'connecticut'},
               'mdu': {'md', 'maryland'},
               'pau': {'pa', 'penn', 'pennsylvania'},
               'riu': {'ri', 'r.i', 'rhode island'},
               'flu': {'fl', 'fla', 'florida'},
               'dcu': {'dc', 'd.c'},
               'enk': {'uk', 'u.k', 'england', 'united kingdom'}}


def normalized_edition(value):
    """Compare explicit edition numbers, retaining qualified/revised labels.

    The house form ``3\\textsuperscript{rd}`` (resolution-plan-2026-09-22,
    "Editions") is read as ``3rd`` (machinery fix 2026-09-25, Sips13); only a
    number followed by its own ordinal suffix is rewritten.
    """
    value = re.sub(r'^\s*([1-9]\d?)\s*\\textsuperscript\s*\{\s*(st|nd|rd|th)\s*\}',
                   r'\1\2', str(value))
    text = normalized(value).rstrip('.')
    text = re.sub(r'\s+(?:ed|edition)$', '', text)
    words = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5,
             'sixth': 6, 'seventh': 7, 'eighth': 8, 'ninth': 9, 'tenth': 10}
    if text in words:
        return str(words[text])
    match = re.fullmatch(r'([1-9]\d?)(st|nd|rd|th)?', text)
    if match:
        number = int(match[1])
        suffix = 'th' if 11 <= number % 100 <= 13 else {1:'st',2:'nd',3:'rd'}.get(number % 10, 'th')
        if match[2] in (None, suffix):
            return str(number)
    return normalized(value).rstrip('.')


def coded_address_support(local, record, xml):
    """Use a coded jurisdiction only for the first transcribed place."""
    root = ET.fromstring(xml)
    code = root.findtext(M + "controlfield[@tag='008']", '')[15:18]
    forms = STATE_FORMS.get(code)
    value = normalized(local).rstrip('.')
    if not forms or value.count(',') != 1 or not record.get('address'):
        return None
    city, state = (s.strip().rstrip('.') for s in value.rsplit(',', 1))
    if state not in forms:
        return None
    place = normalized(record['address'][0]).rstrip('.')
    if ',' in place:
        source_city, source_state = (s.strip().rstrip('.') for s in place.rsplit(',', 1))
        if source_state not in forms:
            return None  # A conflicting transcribed state cannot be overridden.
    else:
        source_city = place
    return code if city and city == source_city else None


def marc_book(xml):
    if (not isinstance(xml, str) or len(xml.encode()) > MAX_BYTES
            or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I)):
        raise ValueError("Unsupported catalogue XML")
    root = ET.fromstring(xml)
    if root.tag != M + "record":
        raise ValueError("Expected one MARC edition record")
    def fields(tag):
        return root.findall(M + f"datafield[@tag='{tag}']")
    def subs(node, code):
        return [(n.text or "").strip() for n in node.findall(M + f"subfield[@code='{code}']")]
    def one(tag, code, required=True):
        nodes = fields(tag)
        if not nodes and not required:
            return ""
        values = subs(nodes[0], code) if len(nodes) == 1 else []
        if len(values) != 1 or not values[0]:
            raise ValueError("Missing or ambiguous MARC field " + tag + code)
        return values[0]
    def control(tag):
        nodes = root.findall(M + f"controlfield[@tag='{tag}']")
        if len(nodes) != 1 or not nodes[0].text:
            raise ValueError("Missing or ambiguous MARC control " + tag)
        return nodes[0].text
    leader = root.findtext(M + "leader", "")
    date = control("008")
    if (len(leader) < 8 or leader[6:8] != "am" or len(date) != 40
            or date[6] != "s" or not re.fullmatch(r"[1-9]\d{3}", date[7:11])
            or date[11:15].strip() or date[23] != " "):
        raise ValueError("Not an unambiguous single-year printed monograph")
    if any(fields(tag) for tag in ("110", "111", "130", "710", "711", "765", "767", "775", "776", "787")):
        raise ValueError("Corporate creators or related editions require review")
    if fields("264") or len(fields("260")) != 1:
        raise ValueError("This route requires one legacy publication statement")
    titles = fields("245")
    if len(titles) != 1 or any(subs(titles[0], code) for code in ("h", "n", "p", "k", "s")):
        raise ValueError("Multipart or non-print title requires review")
    year = date[7:11]
    publication_date = one("260", "c")
    if publication_date not in {year + ".", "c" + year + ".", year, "c" + year}:
        raise ValueError("Transcribed publication year is ambiguous")
    publisher = one("260", "b").rstrip(" ,.;:")
    places = subs(fields("260")[0], "a")
    if not places or any(not v or re.search(r"[\[\]]", v) for v in places):
        raise ValueError("Missing or uncertain place of publication")
    if re.search(r"distribut|\[|\]|;", publisher, re.I):
        raise ValueError("Publisher role is uncertain")
    title = one("245", "a").rstrip(" /:")
    subtitle = subs(fields("245")[0], "b")
    if len(subtitle) > 1:
        raise ValueError("Ambiguous subtitle")
    if subtitle:
        title += ": " + subtitle[0].rstrip(" /")
    if re.search(r"[\[\]]", title):
        raise ValueError("Supplied or uncertain title requires review")
    one("100", "a")  # A single personal main entry is required for this route.
    people = []
    for creator in fields('100') + fields('700'):
        names = subs(creator, 'a')
        # 700 can name editors, owners, or related works. It is not an author
        # list on its own: only simple personal headings confirmed by 245c
        # qualify. Reject analytical entries and all work/role qualifiers.
        allowed = {'a', 'd', 'e', 'q', 'u', '0', '1', '2', '4', '6', '8'}
        if (creator.get('ind1') != '1'
                or (creator.get('tag') == '700' and creator.get('ind2') != ' ')
                or len(names) != 1 or not names[0]
                or any(n.get('code') not in allowed for n in creator)
                or any(v.rstrip(' .').lower() not in {'author', 'joint author'} for v in subs(creator, 'e'))
                or any(v != 'aut' for v in subs(creator, '4'))):
            raise ValueError("Author heading has unsupported identity or role qualifiers")
        author = splitname(names[0].rstrip(" ,."), strict_mode=True)
        people.append({"given": " ".join(author['first']), "family": " ".join(author['von'] + author['last']),
                       "suffix": " ".join(author['jr'])})
    statement = one("245", "c").rstrip(" .")
    statement = re.sub(r"^(?:by|\[by\])\s+", "", statement, flags=re.I)
    names = [statement]
    if len(people) > 1:
        # This deliberately small grammar accepts complete natural-order
        # bylines joined by commas or 'and'. Suffixes/inverted names and
        # qualified responsibilities remain unresolved rather than guessed.
        names = re.split(r",\s*(?:and\s+)?|\s+and\s+", statement)
        if len(names) != len(people) or any(not n.strip() for n in names):
            raise ValueError("Transcribed responsibility is not a complete simple byline")
    # MARC's inverted personal heading explicitly supplies the entire family
    # name. Protect that same verbatim suffix in the natural-order byline so
    # BibTeX's lowercase-particle heuristic cannot split 'De Valois'. This
    # supplies grouping only; every given name and surname still must match.
    for index, (name, person) in enumerate(zip(names, people)):
        family = person['family']
        if ' ' in family and not person['suffix']:
            pattern = r'(?<=\s)' + re.escape(family) + r'$'
            names[index] = re.sub(pattern, lambda _: '{' + family + '}', name.strip(), flags=re.I)
    statement = ' and '.join(names)
    if not author_evidence(statement, people)[0]:
        raise ValueError("Transcribed responsibility differs from the complete named author list")
    if any(re.search(r"reprint|translat|revis|facsimil", " ".join(n.itertext()), re.I) for n in fields("500")):
        raise ValueError("Edition note requires review")
    isbns = []
    for node in fields("020"):
        for value in subs(node, "a"):
            # Older ISBD punctuation separates an ISBN/qualifier from the
            # acquisition terms in 020$c with a terminal spaced colon.
            match = re.fullmatch(r"([\dXx-]+)(?:\s+\([^)]*\))?(?:\s+:)?", value)
            if not match:
                raise ValueError("Unsupported ISBN statement")
            isbns.append(match[1])
    return {"type": "book", "title": [title], "author": people, "published": {"date-parts": [[int(year)]]},
            "publisher": publisher, "ISBN": isbns, "catalogue_id": control("001"),
            "address": [v.rstrip(" ,;:") for v in places], "edition": one("250", "a", False).rstrip(" .")}


# ---------------------------------------------------------------------------
# Policy-7 widened grammar. It is consulted only for records the strict
# grammar above rejects, so every earlier approval reproduces exactly. Each
# extension is narrow; everything it does not recognise is still rejected.
# ---------------------------------------------------------------------------

AUTHOR_ROLES = {'author', 'joint author', 'aut', 'http://id.loc.gov/vocabulary/relators/aut'}
EDITOR_ROLES = {'ed', 'editor', 'edt', 'http://id.loc.gov/vocabulary/relators/edt'}
# Contributors of a foreword/introduction are named in a separate 245c clause
# and never enter the author or editor list.
SECONDARY_ROLES = {'writer of foreword', 'writer of introduction', 'author of introduction',
                   'writer of preface', 'wpr', 'aui'}
SECONDARY_CLAUSE = re.compile(
    r"(?:with\s+)?(?:an?\s+)?(?:new\s+)?(?:foreword|introduction|introd\.|preface)(?:\s+and\s+notes)?\s+by\s+"
    r"|with\s+discussions\s+by\s+|contributing\s+writers?,?\s+|contributors:\s+|visual\s+key\s+by\s+", re.I)
EDITOR_CLAUSE = re.compile(r"(?:edited\s+by|ed\.\s+by|editors?:)\s+(?P<names>.+)", re.I)
EDITOR_SUFFIX = re.compile(r"(?P<names>.+?),?\s+(?:editors|eds\.?|editor)", re.I)
ETAL = re.compile(r"et\s+al|and\s+others|\.\.\.\s*\[", re.I)
NOTE_BLOCK = re.compile(r"reprint|translat|revis|facsimil|originally\s+published", re.I)
DISTRIBUTOR = re.compile(r"(?:distributed|distributor|sole\s+distributors?)\b", re.I)


def folded(value):
    """Diacritic-insensitive form, used ONLY to relate two fields of one LC record."""
    text = unicodedata.normalize('NFD', normalized(value))
    return ''.join(c for c in text if not unicodedata.combining(c))


def split_statement(statement):
    """Split a 245c statement into ISBD clauses; never guess inside a clause."""
    statement = re.sub(r"\s*\[and\]\s*", " and ", statement)
    statement = re.sub(r"^(?:by|\[by\])\s+", "", statement.strip(), flags=re.I)
    clauses = []
    for part in re.split(r"\s+;\s+|\s*;\s+(?=\S)", statement):
        # A sentence break only separates clauses when a known role phrase follows.
        pieces = re.split(r"(?<=[.,])\s+(?=(?:with|edited|contributors|contributing|visual\s+key|"
                          r"translated|introduction|foreword)\b)", part, flags=re.I)
        for piece in pieces:
            piece = piece.strip().rstrip(' ,')
            # One terminal period ends the clause; an ISBD omission mark stays.
            if piece.endswith('.') and not piece.endswith('...'):
                piece = piece[:-1].rstrip(' ,')
            if piece:
                clauses.append(piece)
    return clauses


def statement_names(clause):
    """Natural-order names joined by commas and/or 'and'; suffixes stay attached."""
    protected = re.sub(r",\s*(Jr\.?|Sr\.?|II|III|IV)(?=,|\s+and\b|$)", r" <\1>", clause.strip())
    names = [n.strip() for n in re.split(r",\s*(?:and\s+)?|\s+and\s+|\s+&\s+", protected)]
    if not names or any(not n for n in names):
        raise ValueError("Transcribed responsibility is not a complete simple byline")
    return names


def heading_person(node, subs):
    """A personal heading's family/given split with trailing particles regrouped."""
    names = subs(node, 'a')
    if node.get('ind1') != '1' or len(names) != 1 or not names[0]:
        raise ValueError("Author heading has unsupported identity or role qualifiers")
    parts = splitname(names[0].rstrip(" ,."), strict_mode=True)
    given, family = list(parts['first']), parts['von'] + parts['last']
    while given and re.fullmatch(r"(?:van|von|der|den|de|del|della|di|du|la|le)", given[-1]):
        family.insert(0, given.pop())
    if parts['jr']:
        raise ValueError("Author heading has unsupported identity or role qualifiers")
    return {'given': " ".join(given), 'family': " ".join(family)}


def byline_person(name, heading, allow_omission=False):
    """Pair one transcribed name with its heading; the title page supplies the form.

    Surnames must agree exactly (ignoring only diacritics the LC heading lacks)
    and each shared given-name position must agree as a name or its initial,
    in either direction. The returned person keeps the transcription verbatim.
    """
    suffix = ''
    match = re.fullmatch(r"(.+?)\s+<(Jr\.?|Sr\.?|II|III|IV)>", name)
    if match:
        name, suffix = match[1], match[2]
    if allow_omission:
        name = re.sub(r"\s*\.\.\.$", "", name)
    if re.search(r"[\[\]<>()]|\.\.\.", name):
        raise ValueError("Transcribed responsibility is not a complete simple byline")
    family = heading['family']
    tail = re.search(r"(?:^|\s)(" + r"\s+".join(re.escape(w) for w in folded(family).split()) + r")$",
                     folded(name))
    if not family or not tail:
        raise ValueError("Transcribed responsibility differs from the complete named author list")
    words = name.split()
    count = len(family.split())
    given, printed_family = " ".join(words[:-count]), " ".join(words[-count:])
    stated, headed = given_name_tokens(folded(given)), given_name_tokens(folded(heading['given']))
    if not stated or not headed or any(
            not (given_token_matches(a, b) or given_token_matches(b, a)) for a, b in zip(stated, headed)):
        raise ValueError("Transcribed responsibility differs from the complete named author list")
    return {'given': given, 'family': printed_family, 'suffix': suffix}


def unheaded_person(name):
    words = name.split()
    if (len(words) < 2 or re.search(r"[\[\]<>()]|\.\.\.", name)
            or any(not w[0].isupper() for w in words)
            or not re.fullmatch(r"[^\W\d_][^\W\d_'’-]*(?:[-'’][^\W\d_]+)*", words[-1])
            or len(words[-1]) < 2):
        raise ValueError("Transcribed responsibility differs from the complete named author list")
    return {'given': " ".join(words[:-1]), 'family': words[-1], 'suffix': ''}


def imprint_groups(node, subs):
    """Ordered (places, publisher) pairs; distributor groups are not publishers."""
    groups, dates = [], []
    for sub in node:
        code, text = sub.get('code'), (sub.text or '').strip()
        if code == 'a':
            if not groups or groups[-1]['publisher'] is not None:
                groups.append({'places': [], 'supplied': [], 'publisher': None})
            place = text.rstrip(" ,;:")
            qualified = re.fullmatch(r"([^\[\]]+?)\s*\[[^\[\]]+\]\.?", place)
            if qualified:
                place = qualified[1].rstrip(" ,")
            if re.fullmatch(r"\[[^\[\]]+\]", place):
                groups[-1]['supplied'].append(place[1:-1])
            elif not place or re.search(r"[\[\]]", place):
                raise ValueError("Missing or uncertain place of publication")
            else:
                groups[-1]['places'].append(place)
        elif code == 'b':
            if not groups:
                raise ValueError("Missing or uncertain place of publication")
            text = re.split(r"\s*;\s*(?=distribut)", text, flags=re.I)[0].rstrip(" ,.;:")
            if DISTRIBUTOR.match(text):
                if groups[-1]['publisher'] is None:
                    groups.pop()
                continue
            if groups[-1]['publisher'] is not None:
                raise ValueError("Publisher role is uncertain")
            if not text or DISTRIBUTOR.search(text) or re.search(r"[\[\];]", text):
                raise ValueError("Publisher role is uncertain")
            groups[-1]['publisher'] = text
        elif code == 'c':
            dates.append(text)
        elif code not in {'3', '8'}:
            raise ValueError("Publication statement has unsupported parts")
    if not groups or any(g['publisher'] is None or not (g['places'] or g['supplied']) for g in groups):
        raise ValueError("Missing or ambiguous MARC field 260b")
    if len(dates) != 1:
        raise ValueError("Transcribed publication year is ambiguous")
    return groups, dates[0]


def marc_book_widened(xml):
    if (not isinstance(xml, str) or len(xml.encode()) > MAX_BYTES
            or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I)):
        raise ValueError("Unsupported catalogue XML")
    root = ET.fromstring(xml)
    if root.tag != M + "record":
        raise ValueError("Expected one MARC edition record")
    def fields(tag):
        return root.findall(M + f"datafield[@tag='{tag}']")
    def subs(node, code):
        return [(n.text or "").strip() for n in node.findall(M + f"subfield[@code='{code}']")]
    def control(tag):
        nodes = root.findall(M + f"controlfield[@tag='{tag}']")
        if len(nodes) != 1 or not nodes[0].text:
            raise ValueError("Missing or ambiguous MARC control " + tag)
        return nodes[0].text
    leader = root.findtext(M + "leader", "")
    date = control("008")
    year = date[7:11] if len(date) == 40 else ''
    # (a) One publication year: 008 type 's', or type 't' whose copyright
    # year equals it. Reissues ('r'), multi-part ('m') and others stay out.
    single = len(date) == 40 and (
        (date[6] == 's' and not date[11:15].strip()) or (date[6] == 't' and date[11:15] == year))
    if (len(leader) < 8 or leader[6:8] != "am" or not single
            or not re.fullmatch(r"[1-9]\d{3}", year) or date[23] != " "):
        raise ValueError("Not an unambiguous single-year printed monograph")
    if any(fields(tag) for tag in ("110", "130", "765", "767", "775", "776", "787", "880")):
        raise ValueError("Corporate creators or related editions require review")
    # (b) RDA: exactly one 264 publication statement (ind2=1). Copyright (4),
    # distribution (2) and manufacture (3) statements never name the publisher.
    publication = [n for n in fields("264") if n.get('ind2') == '1']
    if any(n.get('ind2') not in {'1', '2', '3', '4'} for n in fields("264")) \
            or len(publication) + len(fields("260")) != 1:
        raise ValueError("This route requires one publication statement")
    groups, stated = imprint_groups((publication or fields("260"))[0], subs)
    stated = stated.rstrip(" .")
    if not re.fullmatch(r"\[?(?:c|©)?" + year + r"\]?", stated) or stated.count('[') != stated.count(']'):
        raise ValueError("Transcribed publication year is ambiguous")
    titles = fields("245")
    if len(titles) != 1 or any(subs(titles[0], code) for code in ("h", "n", "p", "k", "s", "6")):
        raise ValueError("Multipart or non-print title requires review")
    main = subs(titles[0], 'a')
    if len(main) != 1 or not main[0]:
        raise ValueError("Missing or ambiguous MARC field 245a")
    title = main[0].rstrip(" /:;,=")
    subtitle = subs(titles[0], "b")
    if len(subtitle) > 1:
        raise ValueError("Ambiguous subtitle")
    if subtitle:
        title += ": " + subtitle[0].rstrip(" /,;:")
    if re.search(r"[\[\]]", title):
        raise ValueError("Supplied or uncertain title requires review")
    if any(NOTE_BLOCK.search(" ".join(n.itertext())) for n in fields("500")):
        raise ValueError("Edition note requires review")
    editions = fields("250")
    if len(editions) > 1 or (editions and (subs(editions[0], 'b') or len(subs(editions[0], 'a')) != 1)):
        raise ValueError("Edition statement requires review")
    statements = subs(titles[0], 'c')
    if len(statements) > 1:
        raise ValueError("Missing or ambiguous MARC field 245c")
    statement = statements[0].rstrip(" .") if statements else ''
    main_entry, added = fields("100"), fields("700")
    for node in main_entry + added:
        allowed = {'a', 'c', 'd', 'e', 'q', 'u', '0', '1', '2', '4', '8'}
        honorific = all(re.fullmatch(r"Sir,?|Dame,?|\([^()]+\),?", v) for v in subs(node, 'c'))
        if (any(n.get('code') not in allowed for n in node) or not honorific
                or (node.get('tag') == '700' and node.get('ind2') != ' ')):
            raise ValueError("Author heading has unsupported identity or role qualifiers")
    def roles(node):
        values = {v.rstrip(' .,').lower() for v in subs(node, 'e') + subs(node, '4')}
        if values - AUTHOR_ROLES - EDITOR_ROLES - SECONDARY_ROLES:
            raise ValueError("Author heading has unsupported identity or role qualifiers")
        return values
    if len(main_entry) > 1 or (main_entry and roles(main_entry[0]) - AUTHOR_ROLES):
        raise ValueError("Author heading has unsupported identity or role qualifiers")
    edited = not main_entry
    for node in fields("710") + fields("711") + fields("111"):
        keep = subs(node, '5') == ['DLC'] and node.get('tag') == '710'
        sponsor = (edited and not subs(node, 't')
                   and all(v.rstrip(' .,').lower() in {'sponsor', 'sponsoring body', 'issuing body'}
                           for v in subs(node, 'e')))
        if not (keep or sponsor):
            raise ValueError("Corporate creators or related editions require review")
    clauses = split_statement(statement) if statement else []
    authors, editors, secondary = [], [], []
    for index, clause in enumerate(clauses):
        editor = EDITOR_CLAUSE.fullmatch(clause) or EDITOR_SUFFIX.fullmatch(clause)
        if re.search(r"translat|\brev\.|revised|re-written", clause, re.I):
            raise ValueError("Translation or revision statement requires review")
        if SECONDARY_CLAUSE.match(clause):
            names = SECONDARY_CLAUSE.sub('', clause, count=1)
            if re.search(r"\bby\b|translat", names, re.I):
                raise ValueError("Transcribed responsibility is not a complete simple byline")
            secondary.append(names)
        elif ETAL.search(clause):
            raise ValueError("Transcribed responsibility names only part of the byline")
        elif editor and not editors:
            editors = statement_names(editor['names'])
        elif index == 0 and not edited:
            authors = statement_names(clause)
        else:
            raise ValueError("Transcribed responsibility is not a complete simple byline")
    headings = [heading_person(n, subs) for n in main_entry + added]
    people, editor_people = [], []
    if not edited:
        if not authors:
            # (e) No statement of responsibility: exactly one personal main
            # entry and no other personal heading supplies the byline.
            if statement or added or len(main_entry) != 1:
                raise ValueError("Missing or ambiguous MARC field 245c")
            head = headings[0]
            if not head['given']:
                raise ValueError("Missing or incomplete given names")
            people = [dict(head, suffix='')]
        else:
            if len(authors) > len(headings) and (secondary or editors):
                raise ValueError("Transcribed responsibility differs from the complete named author list")
            for i, name in enumerate(authors):
                if i >= len(headings):
                    # Older LC records often give an added entry to the first
                    # author only. A later printed name with no heading is
                    # accepted only in the simplest form: capitalised given
                    # names and ONE surname word, no particles or suffixes.
                    people.append(unheaded_person(name))
                    continue
                if i and roles(added[i - 1]) - AUTHOR_ROLES:
                    raise ValueError("Transcribed responsibility differs from the complete named author list")
                people.append(byline_person(name, headings[i], allow_omission=len(authors) == 1))
    elif not editors:
        raise ValueError("Missing or ambiguous MARC field 100a")
    # Added headings already paired with a transcribed author, in order.
    used = len(people) - len(main_entry) if not edited else 0
    rest = list(zip(added, headings[len(main_entry):]))[used:]
    if editors:
        if len(editors) > len(rest):
            raise ValueError("Transcribed editors differ from the named editor headings")
        for name, (node, head) in zip(editors, rest):
            if roles(node) - EDITOR_ROLES:
                raise ValueError("Transcribed editors differ from the named editor headings")
            editor_people.append(byline_person(name, head))
        rest = rest[len(editors):]
    # Every remaining personal heading must be a named secondary contributor;
    # an unexplained author/editor heading means the byline is incomplete.
    extra = folded(" ".join(secondary))
    for node, head in rest:
        if roles(node) & (AUTHOR_ROLES | EDITOR_ROLES) or not head['family'] \
                or not re.search(r"(?:^|\W)" + re.escape(folded(head['family'])) + r"(?:$|\W)", extra):
            raise ValueError("Author heading has unsupported identity or role qualifiers")
    isbns = []
    for node in fields("020"):
        for value in subs(node, "a"):
            match = re.fullmatch(r"([\dXx-]+)(?:\s+\([^)]*\))?(?:\s+:)?", value)
            if not match:
                raise ValueError("Unsupported ISBN statement")
            isbns.append(match[1])
    record = {"type": "book", "title": [title], "author": people,
              "published": {"date-parts": [[int(year)]]},
              "publisher": [g['publisher'] for g in groups], "ISBN": isbns,
              "catalogue_id": control("001"),
              "address": [p for g in groups for p in g['places']],
              "imprints": [{"publisher": g['publisher'], "address": g['places']} for g in groups],
              "edition": subs(editions[0], 'a')[0].rstrip(" .") if editions else "",
              "authority_headings": headings,
              "catalogue_grammar": WIDENED_GRAMMAR}
    if editor_people:
        record["editor"] = editor_people
    return record


def parse_edition(xml):
    """The policy-6 grammar first; the widened grammar only for its rejections.

    A policy-6 title that keeps pre-ISBD terminal punctuation (',' or ';', as
    in 'Principles of gestalt psychology,') could never match a citation, so
    that record is re-read by the widened grammar, which strips it.
    """
    try:
        record = marc_book(xml)
    except ValueError:
        return marc_book_widened(xml)
    if re.search(r"[,;]$|;:", record['title'][0]):
        return marc_book_widened(xml)
    return record


def other_edition(xml, fields):
    """True only when an unparsed record provably describes another edition.

    Its 008 date1 differs from the cited year, or its transcribed title is a
    different title. Such a record cannot be the cited edition, so it does not
    make the edition choice ambiguous. Anything else still blocks approval.
    """
    try:
        if not isinstance(xml, str) or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I):
            return False
        root = ET.fromstring(xml)
        date = root.findtext(M + "controlfield[@tag='008']", '')
        cited = str(fields.get('year', ''))
        if len(date) == 40 and re.fullmatch(r"[1-9]\d{3}", cited) and re.fullmatch(r"[1-9]\d{3}", date[7:11]):
            if date[6] in 'srte' and date[7:11] != cited:
                return True  # one stated year (or a reprint's own year) differs
            if date[6] in 'mikqcdu':
                end = date[11:15] if re.fullmatch(r"[1-9]\d{3}", date[11:15]) else '9999'
                if not date[7:11] <= cited <= end:
                    return True  # a date range that excludes the cited year
        titles = root.findall(M + "datafield[@tag='245']")
        if len(titles) != 1:
            return False
        def text(code):
            return " ".join((n.text or '') for n in titles[0].findall(M + f"subfield[@code='{code}']"))
        def key(value):
            return re.sub(r"[\W_]+", " ", folded(value)).strip()
        mine = key(fields.get('title', ''))
        whole, short = key(text('a') + ' ' + text('b')), key(text('a'))
        citedshort = key(re.split(r":", str(fields.get('title', '')))[0])
        return bool(mine and whole and mine != whole and short != citedshort)
    except (ValueError, ET.ParseError):
        return False


def compare_edition(fields, record, xml):
    """Compare every cited field with one parsed MARC edition record."""
    ordinary = {k: v for k, v in fields.items() if k not in {'address', 'edition', 'editor'}}
    evidence, issues = compare_record(ordinary, record)
    if not fields.get('author') and fields.get('editor') and record.get('editor') and not record['author']:
        # (g) An editor-only citation of an edited volume: the author check
        # has nothing to compare; the full ordered editor list replaces it.
        evidence.pop('author', None)
        issues = [i for i in issues if not i.startswith('author: ')]
    if fields.get('editor'):
        ok, detail = author_evidence(fields['editor'], record.get('editor', []))
        evidence['editor'] = {'local': fields['editor'], 'source': record.get('editor', []),
                              'match': ok, 'detail': detail}
        if not ok:
            issues.append('editor: ' + detail)
    imprints = record.get('imprints')
    places = record['address']
    if imprints and fields.get('publisher'):
        # (c) A two-publisher imprint: the cited place must belong to the
        # cited publisher's own group, never to the other publisher.
        mine = [i for i, g in enumerate(imprints)
                if normalize_book_publisher(g['publisher']) == normalize_book_publisher(fields['publisher'])]
        if mine:
            places = [p for i in mine for p in imprints[i]['address']]
    if fields.get('publisher') and 'publisher: missing evidence or mismatch' in issues:
        publishers = [g['publisher'] for g in imprints] if imprints else [record.get('publisher', '')]
        same = [p for p in publishers if p and publisher_same_firm(fields['publisher'], p)]
        if len(same) == 1:
            issues = [i for i in issues if i != 'publisher: missing evidence or mismatch']
            evidence['publisher'] = dict(evidence.get('publisher', {}), match=True, source_name_variant=same[0],
                                         detail='Catalogue gives a longer form of the same firm; house form kept')
            if imprints:
                mine = [i for i, g in enumerate(imprints) if g['publisher'] == same[0]]
                places = [p for i in mine for p in imprints[i]['address']]
    for name in ('address', 'edition'):
        local, source = fields.get(name, ''), (places if name == 'address' else record[name])
        if local or (name == 'edition' and source):
            values = source if isinstance(source, list) else [source]
            normalize = normalized_edition if name == 'edition' else lambda v: normalized(v).rstrip('.')
            match = bool(local and any(normalize(local) == normalize(s) for s in values))
            code = None
            if name == 'address' and not match and (not imprints or places[:1] == record['address'][:1]):
                code = coded_address_support(local, dict(record, address=places), xml)
            match = match or bool(code)
            evidence[name] = {'local': local, 'source': values, 'match': match}
            if code:
                evidence[name]['source_place_code'] = code
            if not match:
                issues.append(f'{name}: missing evidence or mismatch')
    return evidence, issues


def assess_catalogue(fields, response):
    candidates = []
    try:
        if fields.get("ENTRYTYPE") != "book" or fields.get("doi"):
            raise ValueError("Catalogue route requires a book without a supplied DOI")
        url = urlparse(response["url"])
        if (url.scheme != 'https' or url.hostname != 'lx2.loc.gov' or url.path != '/sru/lcdb'
                or url.username or url.password or url.port not in (None, 443)
                or hashlib.sha256(response['raw_xml'].encode()).hexdigest() != response['document_sha256']):
            raise ValueError("Invalid catalogue source provenance")
        # Discovery may omit combining accents that LC's search index fails
        # to match. The original fields and MARC transcription remain intact
        # for every identity/edition comparison below.
        queries = {search_query(fields, fold_diacritics=fold) for fold in (False, True)}
        if re.fullmatch(r'[1-9]\d{3}', str(fields.get('year', ''))):
            queries.update(search_query(fields, include_year=True, fold_diacritics=fold)
                           for fold in (False, True))
        parsed = None
        for query in sorted(queries):
            try:
                parsed = parse_search(response['raw_xml'], query)
                break
            except ValueError as exc:
                if str(exc) != 'Catalogue response does not echo the requested query':
                    raise
        if parsed is None:
            raise ValueError('Catalogue response query does not derive from this citation')
        if parsed['truncated']:
            raise ValueError("Catalogue search is truncated; edition uniqueness is unresolved")
        incomplete = False
        for xml in parsed['records']:
            evidence, record, issues = {}, {}, []
            try:
                record = parse_edition(xml)
                evidence, issues = compare_edition(fields, record, xml)
            except (ValueError, KeyError, TypeError) as exc:
                issues = ['Catalogue edition unresolved: ' + str(exc)]
                if other_edition(xml, fields):
                    # Provably another year or title: it cannot be the cited
                    # edition, so it does not make the choice ambiguous.
                    issues.append('Not a competing edition: 008 year or transcribed title differs')
                else:
                    incomplete = True
            candidates.append({'source': 'loc-catalogue', 'record_id': record.get('catalogue_id'),
                               'record': record, 'evidence': evidence, 'issues': issues,
                               'url': response['url'], 'retrieved_at': response['retrieved_at'],
                               'raw_marcxml': xml, 'raw_search_xml': response['raw_xml'],
                               'document_sha256': response['document_sha256']})
        good = [c for c in candidates if not c['issues']]
        if len(good) == 1 and not incomplete:
            return dict(outcome('metadata_verified', [], candidates), accepted_source='loc-catalogue',
                        accepted_record_id=good[0]['record_id'])
        return outcome('needs_review', ['No unique, fully matching catalogue edition'], candidates)
    except (ValueError, KeyError, TypeError, AttributeError, ET.ParseError) as exc:
        return outcome('needs_review', ['Catalogue edition unresolved: ' + str(exc)], candidates)


def reassess_saved_catalogue(fields, previous):
    """Rebuild decisions from the complete search, never saved match booleans."""
    saved = [c for c in previous.get('candidates', []) if c.get('source') == 'loc-catalogue']
    if not saved:
        return None
    responses = {}
    for c in saved:
        response = {'url': c.get('url'), 'raw_xml': c.get('raw_search_xml'),
                    'retrieved_at': c.get('retrieved_at'), 'document_sha256': c.get('document_sha256')}
        responses[tuple(response.values())] = response
    if len(responses) != 1:
        return outcome('needs_review', ['Conflicting saved catalogue searches require review'], saved)
    result = assess_catalogue(fields, next(iter(responses.values())))
    result['candidates'] = [c for c in previous.get('candidates', []) if c.get('source') != 'loc-catalogue'] + result['candidates']
    result['attempts'] = previous.get('attempts', [])
    return result


def valid_catalogue_approval(result):
    """Validate the portable source envelope and accepted MARC record identity."""
    if result.get('accepted_source') != 'loc-catalogue' or not result.get('accepted_record_id'):
        return False
    saved = [c for c in result.get('candidates', []) if c.get('source') == 'loc-catalogue'
             and c.get('record_id') == result['accepted_record_id'] and c.get('issues') == [] and c.get('evidence')]
    if len(saved) != 1:
        return False
    try:
        source = saved[0]
        # Reconstruct the originally checked local fields from their evidence.
        fields = {k: e['local'] for k, e in source['evidence'].items()}
        fields['ENTRYTYPE'] = 'book'
        checked = reassess_saved_catalogue(fields, result)
        return bool(checked and checked['status'] == 'metadata_verified'
                    and checked['accepted_record_id'] == result['accepted_record_id']
                    and next(c for c in checked['candidates'] if c.get('source') == 'loc-catalogue'
                             and c.get('record_id') == result['accepted_record_id']) == source)
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration):
        return False


# ---------------------------------------------------------------------------
# Correction proposals (read-only). One catalogue record of the SAME edition
# may supply corrections for at most two fields. Identity is pinned first:
# ordered surnames, title (or its subtitle boundary / a <=2-character typo),
# and never a changed year together with a changed publisher or edition.
# A proposal is only emitted when applying it makes the ordinary assessment
# of the unchanged search verify exactly that record. Nothing is written.
# ---------------------------------------------------------------------------

PROPOSABLE = ('title', 'author', 'editor', 'year', 'publisher', 'address', 'edition')
GENERIC_PUBLISHER_WORDS = {'press', 'publishers', 'publisher', 'publishing', 'pub', 'co', 'company',
                           'corp', 'corporation', 'inc', 'ltd', 'limited', 'associates', 'sons',
                           'and', 'the', 'of', 'books', 'book', 'verlag', 'group', 'llc'}


def _edit_distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def collapse_dotted_acronyms(value):
    """'M.I.T. Press' -> 'MIT Press' (machinery fix 2026-09-25, Chom65).

    Only runs of two or more single letters each followed by a period.
    """
    return re.sub(r"(?<![\w.])((?:[A-Za-z]\.){2,})",
                  lambda m: m.group(1).replace(".", "") + " ", value or "").replace("  ", " ")


def _publisher_tokens(value, keep_initials=False):
    words = re.findall(r"[a-z0-9]+", folded(collapse_dotted_acronyms(value)).replace('&', ' and '))
    return [w for w in words if w not in GENERIC_PUBLISHER_WORDS and (keep_initials or len(w) > 1)]


def publisher_name_form(cited, catalogue):
    """Same firm, shorter form: one token set within the other, or an acronym."""
    mine, theirs = _publisher_tokens(cited), _publisher_tokens(catalogue)
    if not mine or not theirs:
        return False
    if set(mine) <= set(theirs) or set(theirs) <= set(mine):
        return True
    if ''.join(mine) == ''.join(theirs):
        return True  # 'Harper Prism' / 'HarperPrism'
    initials = ''.join(w[0] for w in re.findall(r"[a-z]+", folded(catalogue)) if w not in {'of', 'and', 'the'})
    return len(mine) == 1 and len(mine[0]) >= 2 and initials.startswith(mine[0]) \
        and set(theirs) - set(re.findall(r"[a-z]+", folded(catalogue))) == set()


def publisher_same_firm(cited, catalogue):
    """The catalogue gives a longer (or equal) form of the cited firm's name.

    User decision 2026-09-24/25: a same-firm longer form is a match and the
    house form is kept (no edit). Every distinctive word of the cited name is
    in the catalogue name ('Addison-Wesley' / 'Addison-Wesley Pub. Co',
    'Erlbaum' / 'L. Erlbaum Associates'), the words run together
    ('Harper Prism' / 'HarperPrism'), or the cited name is the catalogue
    name's acronym ('{MIT} Press'). A catalogue name that drops a cited word
    ('Harcourt, Brace, and World' / 'Harcourt, Brace and Company') is not a
    match: that may be another firm or era. A cited initial is distinctive
    (2026-09-27): 'J H Freeman' is not the firm of 'W.H. Freeman', while
    'W H Freeman' is (the letters run together as the collapsed 'WH').
    """
    mine, theirs = _publisher_tokens(cited or ''), _publisher_tokens(catalogue or '')
    if not mine or not theirs:
        return False
    initials = _publisher_tokens(cited or '', keep_initials=True)
    if initials != mine:
        # the cited name has initials: every one must be in the catalogue name
        full = _publisher_tokens(catalogue or '', keep_initials=True)
        return set(initials) <= set(full) or ''.join(initials) == ''.join(full)
    if set(mine) <= set(theirs) or ''.join(mine) == ''.join(theirs):
        return True
    initials = ''.join(w[0] for w in re.findall(r"[a-z]+", folded(catalogue)) if w not in {'of', 'and', 'the'})
    return len(mine) == 1 and len(mine[0]) >= 2 and initials.startswith(mine[0]) \
        and set(theirs) - set(re.findall(r"[a-z]+", folded(catalogue))) == set()


def _surnames(value):
    names = []
    for name in split_authors(value or ''):
        if name.startswith('{') and name.endswith('}'):
            return None
        parts = splitname(name, strict_mode=True)
        names.append(" ".join(parts['von'] + parts['last']))
    return names


def _cited_name(local, person):
    """Rewrite one cited name from the printed byline, in the citation's style."""
    parts = splitname(local, strict_mode=True)
    initials = all(len(t) == 1 for t in given_name_tokens(" ".join(parts['first'])))
    given = person['given']
    if initials:
        given = " ".join('-'.join(p[0] for p in token.split('-')) for token in given.replace('.', '. ').split())
        given = " ".join(t.rstrip('.') for t in given.split())
    family = unicodedata.normalize('NFC', person['family'])
    given = unicodedata.normalize('NFC', given)
    # No name suffix is ever written (user decision 2026-09-24).
    return f"{given} {family}" if ' ' not in family else f"{given} {{{family}}}"


def _people_change(field, local, people):
    names = split_authors(local)
    fixed = []
    for name, person in zip(names, people):
        ok, _ = author_evidence(name, [person])
        fixed.append(name if ok else _cited_name(name, person))
    return " and ".join(fixed)


def propose_corrections(fields, result):
    """Return {'proposal': {...}} or {'group': id, 'reason': text}; never writes."""
    saved = [c for c in result.get('candidates', []) if c.get('source') == 'loc-catalogue']
    if not saved:
        return {'group': 'no-catalogue-record', 'reason': 'No cached catalogue search'}
    parsed = [c for c in saved if c.get('record')]
    blocking = [c for c in saved if not c.get('record')
                and not any(i.startswith('Not a competing edition') for i in c['issues'])]
    if not parsed:
        if not blocking:
            return {'group': 'catalogue-only-other-editions',
                    'reason': 'Every catalogue record is another year or title: ' + saved[0]['issues'][0]}
        return {'group': 'catalogue-unparsed', 'reason': blocking[0]['issues'][0]}
    options = []
    for c in parsed:
        record, issues = c['record'], c['issues']
        diff = {i.split(':', 1)[0] for i in issues}
        if not issues:
            # A record that matches the citation exactly is the cited edition
            # itself: it is a plausible option that needs no change, and no
            # other record may be proposed over it (machinery 2026-09-25,
            # Feyn65 once 'M.I.T. Press' matched '{MIT} Press').
            options.append((c, []))
            continue
        if any(':' not in i for i in issues) or diff - set(PROPOSABLE) \
                or any(i.startswith('year: conflicting') for i in issues):
            continue
        cited = _surnames(fields.get('author') or fields.get('editor'))
        role = 'author' if fields.get('author') else 'editor'
        people = record.get('author') or []
        to_editor = False
        if role == 'author' and not people and record.get('editor') and not fields.get('editor'):
            people, to_editor = record['editor'], True
        if role == 'editor':
            people = record.get('editor') or []
        if cited is None or len(cited) != len(people):
            continue
        spelling = [folded(a) != folded(p['family']) for a, p in zip(cited, people)]
        if any(spelling):
            # A surname spelling slip (<= 2 characters in ONE name) is a
            # proposal only when title, year and publisher agree exactly.
            if (sum(spelling) > 1 or diff & {'title', 'year', 'publisher'}
                    or any(_edit_distance(folded(a), folded(p['family'])) > 2
                           for a, p, bad in zip(cited, people, spelling) if bad)):
                continue
        if 'title' in diff:
            mine, theirs = normalize_title(fields['title']), normalize_title(record['title'][0])
            bare = [re.sub(r"^(?:the|a|an) ", "", t) for t in (mine, theirs)]
            if not (theirs.startswith(mine + ':') or mine.startswith(theirs + ':')
                    or (len(mine) >= 10 and _edit_distance(mine, theirs) <= 2)
                    or bare[0] == bare[1] or bare[1].startswith(bare[0] + ':')):
                continue
        if {'year', 'publisher'} <= diff or {'year', 'edition'} <= diff:
            continue
        changes = []
        if to_editor:
            changes.append({'field': 'author', 'before': fields['author'], 'after': None,
                            'rule': 'edited-volume-author-to-editor'})
            changes.append({'field': 'editor', 'before': None, 'after': fields['author'],
                            'rule': 'edited-volume-author-to-editor'})
            diff.discard('author')
            if not author_evidence(fields['author'], people)[0]:
                changes[-1]['after'] = _people_change('editor', fields['author'], people)
        if len(diff) + (1 if to_editor else 0) > 2:
            continue
        for name in sorted(diff):
            before = fields.get(name) or None
            if name == 'title':
                mine, theirs = normalize_title(fields['title']), normalize_title(record['title'][0])
                if theirs.startswith(mine + ':'):
                    # Keep the cited main title (with its brace protection)
                    # and append the catalogue's subtitle verbatim.
                    source = record['title'][0]
                    cut = next(i for i, ch in enumerate(source) if ch == ':'
                               and normalize_title(source[:i]) == mine)
                    after = fields['title'] + ': ' + source[cut + 1:].strip()
                    rule = 'title-add-catalogue-subtitle'
                elif mine.startswith(theirs + ':'):
                    after, rule = record['title'][0], 'title-subtitle-absent-from-catalogue'
                else:
                    bare = [re.sub(r"^(?:the|a|an) ", "", t) for t in (mine, theirs)]
                    after = record['title'][0]
                    rule = ('title-leading-article' if bare[0] == bare[1]
                            else 'title-article-and-subtitle' if bare[1].startswith(bare[0] + ':')
                            else 'title-spelling')
                if after.endswith('.') and not after.endswith('..'):
                    after = after[:-1]
            elif name in ('author', 'editor'):
                after = _people_change(name, fields[name], people)
                surnames = list(zip(_surnames(fields[name]), people))
                headings = record.get('authority_headings') or []
                if name == 'editor' or to_editor:
                    headings = headings[len(headings) - len(people):] if headings else []
                if any(folded(a) != folded(p['family']) for a, p in surnames):
                    rule = 'byline-surname-spelling'
                elif any(normalized(a) != normalized(p['family']) for a, p in surnames):
                    rule = 'byline-surname-diacritics'
                elif any(p.get('suffix') for p in people):
                    rule = 'byline-suffix'
                elif len(headings) >= len(people) and author_evidence(
                        fields[name], [dict(h, suffix='') for h in headings[:len(people)]])[0]:
                    # The citation agrees with LC's authority heading but the
                    # title page prints fewer given names or initials.
                    rule = 'byline-initials-not-on-title-page'
                else:
                    rule = 'byline-given-names'
            elif name == 'year':
                after, rule = str(record['published']['date-parts'][0][0]), 'year-from-catalogue-edition'
            elif name == 'publisher':
                imprints = record.get('imprints') or [{'publisher': record['publisher'], 'address': record['address']}]
                if len(imprints) != 1:
                    break
                after = imprints[0]['publisher']
                if publisher_name_form(fields['publisher'], after):
                    rule = 'publisher-name-form'
                elif _edit_distance(folded(fields['publisher']), folded(after)) <= 2:
                    return {'group': 'catalogue-transcription-typo',
                            'reason': f"Catalogue publisher {after!r} looks like a misspelling of the cited one"}
                else:
                    rule = 'publisher-different'
            elif name == 'address':
                places = c['evidence'].get('address', {}).get('source') or []
                if not places:
                    break
                city = normalized(fields['address']).split(',')[0].strip()
                same = [x for x in places if normalized(x).rstrip('.') == city]
                after = same[0] if same else places[0]
                rule = 'address-state-or-country-suffix' if same else 'address-different'
            elif name == 'edition':
                after = normalized_edition(record['edition']) if record['edition'] else None
                rule = 'edition-from-catalogue' if not before else 'edition-different'
            changes.append({'field': name, 'before': before, 'after': after, 'rule': rule})
        else:
            options.append((c, changes))
    if len(options) > 1:
        return {'group': 'several-plausible-editions', 'reason': 'More than one catalogue edition differs in at most two fields'}
    if options and not options[0][1]:
        return {'group': 'cited-edition-matches', 'reason': 'One catalogue edition matches the citation exactly'}
    if not options:
        return {'group': 'catalogue-different-edition-or-work',
                'reason': 'No parsed catalogue record agrees with the citation on the edition identity'}
    if blocking:
        return {'group': 'catalogue-unparsed-competitor', 'reason': blocking[0]['issues'][0]}
    candidate, changes = options[0]
    if any(c['rule'] == 'byline-surname-spelling' for c in changes):
        from .correction_proposals import surname_change_hold
        for c in changes:
            if c['rule'] == 'byline-surname-spelling':
                hold = surname_change_hold(fields.get('ID'), c['before'], c['after'],
                                           source=f"LC catalogue {candidate.get('record_id')}")
                if hold:
                    return {'group': 'surname-change-held', 'reason': hold}
    edited = dict(fields)
    for change in changes:
        if change['after'] is None:
            edited.pop(change['field'], None)
        else:
            edited[change['field']] = change['after']
    # Simulate the edit against the SAME saved records. The echo check of the
    # search query is not repeated: a corrected title or author changes the
    # query, and the production run re-searches after the edit is applied.
    matches, reasons = [], []
    for c in parsed:
        _, issues = compare_edition(edited, c['record'], c['raw_marcxml'])
        if not issues:
            matches.append(c['record_id'])
        elif c is candidate:
            reasons = issues
    if matches != [candidate['record_id']]:
        return {'group': 'correction-would-not-verify',
                'reason': 'Applying the catalogue values does not verify exactly this record: '
                          + '; '.join(reasons or ['another edition also matches'])}
    return {'proposal': {'record_id': candidate['record_id'], 'changes': changes,
                         'catalogue_url': candidate['url']}}


def review_book(cache, client, fields):
    """The catalogue searches and the assessment of one book, exactly as the catalogue
    review makes them: the title/author search; the same search without diacritics when
    the first finds nothing; one refinement by the cited year when several editions (or a
    truncated list) leave the choice open. Returns ``(response, result, attempts,
    queries)``. ``run_catalogue_review`` stores what this returns; the reference builder
    (``book_build``) calls it for a built book, so both judge an entry by one rule."""
    response = fetch_search(cache, client, fields)
    result = assess_catalogue(fields, response)
    attempts = [{'source': 'loc-catalogue', 'url': response['url']}]
    queries = [response['query']]
    discovery_options = {}
    if (response.get('total_records') == 0
            and search_query(fields, fold_diacritics=True) != response['query']):
        discovery_options = {'fold_diacritics': True}
        response = fetch_search(cache, client, fields, **discovery_options)
        result = assess_catalogue(fields, response)
        attempts.append({'source': 'loc-catalogue', 'url': response['url']})
        queries.append(response['query'])
    if (result['status'] != 'metadata_verified'
            and (len(result['candidates']) > 1 or response.get('truncated'))
            and re.fullmatch(r'[1-9]\d{3}', str(fields.get('year', '')))):
        refined = fetch_search(cache, client, fields, include_year=True, **discovery_options)
        narrowed = assess_catalogue(fields, refined)
        attempts.append({'source': 'loc-catalogue', 'url': refined['url']})
        queries.append(refined['query'])
        # An empty refinement is not proof that the broader
        # edition evidence was wrong. Keep those discovery leads.
        if narrowed['candidates'] and not refined.get('truncated'):
            response, result = refined, narrowed
    return response, result, attempts, queries


def run_catalogue_review(filename, cache, client, report, limit=None, snapshot=None, keys=None):
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    with run_lock(cache):
        entries = load_entries(filename)
        if keys is not None and set(keys) - entries.keys():
            raise ValueError('Catalogue keys must name existing citations')
        count = 0
        try:
            for key, entry in entries.items():
                if keys is not None and key not in keys:
                    continue
                previous = cache.get(filename, entry)
                fields = entry['fields']
                if (not previous or previous['status'] != 'needs_review' or previous.get('external_evidence')
                        or fields.get('ENTRYTYPE') != 'book' or fields.get('doi')
                        or not (fields.get('author') or fields.get('editor'))
                        or previous.get('catalogue_review', {}).get('policy') == CATALOGUE_POLICY):
                    continue
                if limit is not None and count >= limit:
                    break
                response, result, attempts, queries = review_book(cache, client, fields)
                result['candidates'] = [c for c in previous.get('candidates', []) if c.get('source') != 'loc-catalogue'] + result['candidates']
                result['attempts'] = previous.get('attempts', []) + attempts
                for name in ('auto_review', 'discovery_review', 'research_attempt'):
                    if name in previous:
                        result[name] = deepcopy(previous[name])
                result['catalogue_review'] = {'policy': CATALOGUE_POLICY, 'query': response['query'], 'queries': queries}
                cache.put(filename, entry, result)
                count += 1
        finally:
            write_report(filename, cache, report)
            if snapshot:
                export_snapshot(filename, cache, snapshot)
        return current_results(filename, cache, entries)
