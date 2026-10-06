"""Book entries built from Library of Congress catalogue records.

The catalogue check (``catalogue_review``) verifies a ``@book`` against one MARC edition
record of the Library of Congress SRU catalogue. This module builds the entry from that
same record: the request is ``catalogue_discovery.fetch_query`` (the check's client, pacing
and response cache), the record is read by ``catalogue_review.parse_edition`` (the check's
grammar), and every built field is kept only when ``catalogue_review.compare_edition`` (the
check's comparison) accepts it for the record. A record the grammar does not read gives no
entry: the check could not verify one.

A book is asked for by its ISBN, by its LCCN, or by its title and first author. Editions are
distinct works: a search that finds several records is answered with the records, as
candidates to choose from, never with one of them.

Nothing here prints, prompts, writes a file or records an approval.
"""
import re
import xml.etree.ElementTree as ET

from . import correction_proposals as cp
from .catalogue_discovery import M, fetch_query, fetch_search, identifier_query, search_query
from .verification import ProviderError, normalize_title

SOURCE = "loc-catalogue"   # the verifier's own name for the source (``accepted_source``)
SOURCE_NAME = "Library of Congress catalogue"
# The fields of a built book, in the layout's order. No DOI and no ISBN: the catalogue check
# is for a book without a supplied DOI, and an ISBN is not a house field.
BUILT = ("address", "author", "edition", "editor", "publisher", "title", "year")
# MARC 008/15-17 codes whose jurisdiction is a state the house address names by its
# two-letter code: the codes ``catalogue_review.STATE_FORMS`` lets the check compare, less
# England (the format checker never adds a country the source does not print).
STATE_CODES = {"mau": "MA", "nyu": "NY", "cau": "CA", "nju": "NJ", "ilu": "IL", "ctu": "CT",
               "mdu": "MD", "pau": "PA", "riu": "RI", "flu": "FL", "dcu": "DC"}

_ISBN = re.compile(r"(?i)^(isbn(?:-1[03])?\s*:?\s*)?([\dx][\dx\- ]{8,20})$")
_LCCN = re.compile(r"(?i)^lccn\s*:?\s*([a-z]{0,3}\s*\d[\d\- ]{5,12})$")


def _isbn_valid(digits):
    if re.fullmatch(r"\d{9}[\dX]", digits):
        return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(digits)) % 11 == 0
    if re.fullmatch(r"\d{13}", digits):
        return sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(digits)) % 10 == 0
    return False


def isbn_text(text):
    """``text`` as an ISBN's digits ("9780195333244", "0195333241"), or None when it is not
    one. With the word ISBN before it, any 10 or 13 characters of the right kind are an ISBN
    (a wrong check digit is reported by the lookup, not read as a title); without the word,
    only a number with a correct check digit that is an ISBN-13 or is written with hyphens."""
    found = _ISBN.match(" ".join(str(text or "").split()))
    if not found:
        return None
    digits = re.sub(r"[\- ]", "", found[2]).upper()
    if not re.fullmatch(r"\d{9}[\dX]|\d{13}", digits):
        return None
    if found[1]:
        return digits
    marked = len(digits) == 13 and digits[:3] in ("978", "979") or "-" in found[2]
    return digits if marked and _isbn_valid(digits) else None


def lccn_text(text):
    """``text`` ("LCCN 2012007685", "lccn: 92-17326") as a normalised Library of Congress
    control number (the Library's rule: no spaces, and the serial after a hyphen padded to
    six digits), or None. The word LCCN is required: a bare number names nothing."""
    found = _LCCN.match(" ".join(str(text or "").split()))
    if not found:
        return None
    return normalized_lccn(found[1])


def normalized_lccn(value):
    value = re.sub(r"\s+", "", str(value or "")).lower().split("/")[0]
    if "-" in value:
        left, _, right = value.partition("-")
        if not right.isdigit() or len(right) > 6:
            return None
        value = left + right.zfill(6)
    return value if re.fullmatch(r"[a-z]{0,3}(?:\d{8}|\d{10})", value) else None


def _other_isbn(digits):
    """The same ISBN in its other length (978-prefixed 13 <-> 10), or None."""
    if len(digits) == 13 and digits.startswith("978"):
        body = digits[3:12]
        check = (11 - sum((10 - i) * int(c) for i, c in enumerate(body)) % 11) % 11
        return body + ("X" if check == 10 else str(check))
    if len(digits) == 10:
        body = "978" + digits[:9]
        return body + str((10 - sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(body)) % 10) % 10)
    return None


# --- the record's own identifiers ---------------------------------------------------------------------

class WrongRecord(ValueError):
    """The catalogue answered a standard-number query with records of which none carries
    that number: an answer that echoes the query proves nothing about the record in it."""


def same_isbn(one, two):
    """Whether two ISBNs (digits, as ``isbn_text`` gives them) name the same edition: equal,
    or the ten- and thirteen-digit forms of one number. Both must have a correct check digit."""
    one, two = str(one or "").upper(), str(two or "").upper()
    return bool(_isbn_valid(one) and _isbn_valid(two) and (one == two or _other_isbn(one) == two))


def record_isbns(xml):
    """The ISBNs the record itself states (MARC 020 $a; cancelled ones in $z are not its own)."""
    _, subs = _marc(xml)
    found = []
    for value in subs("020", "a"):
        digits = re.sub(r"[\- ]", "", (re.match(r"[\dXx\- ]+", value) or [""])[0]).upper()
        if _isbn_valid(digits) and digits not in found:
            found.append(digits)
    return found


def matched_identifier(xml, isbn=None, lccn=None):
    """Where the record itself carries the number asked for: ``{"field": "020", "value":
    its own ISBN}`` (the same number, in either length) or ``{"field": "010", "value": its
    normalised LCCN}``; None when it does not."""
    if isbn:
        stated = record_isbns(xml)      # the number as asked when the record states it so, else its other length
        own = isbn if isbn in stated else next((value for value in stated if same_isbn(value, isbn)), None)
        return {"field": "020", "value": own, "asked": isbn} if own else None
    if lccn:
        _, subs = _marc(xml)
        own = [normalized_lccn(value) for value in subs("010", "a")]
        return {"field": "010", "value": lccn, "asked": lccn} if normalized_lccn(lccn) in own else None
    return None


def _own_records(found, how, **asked):
    """The records of an answer that carry the number asked for; ``WrongRecord`` when the
    answer has records and none does."""
    kept = [xml for xml in found["records"] if matched_identifier(xml, **asked)]
    if found["records"] and not kept:
        raise WrongRecord(f"The catalogue's answer for {how} holds {len(found['records'])} "
                          f"record{'s' if len(found['records']) != 1 else ''}, none of which carries that number "
                          "itself; it is not used")
    return kept


# --- one record, for a person to choose ------------------------------------------------------------

def _marc(xml):
    root = ET.fromstring(xml)

    def subs(tag, code):
        return [" ".join((n.text or "").split()) for field in root.findall(M + f"datafield[@tag='{tag}']")
                for n in field.findall(M + f"subfield[@code='{code}']") if (n.text or "").strip()]
    return root, subs


def record_title(xml):
    """The record's transcribed title (245 $a and $b), without its ISBD punctuation."""
    _, subs = _marc(xml)
    main = " ".join(subs("245", "a")).rstrip(" /:;,=")
    rest = " ".join(subs("245", "b")).rstrip(" /,;:")
    title = main + (": " + rest if rest else "")
    return title[:-1] if title.endswith(".") and not title.endswith("..") else title


def summary(xml):
    """One catalogue record as a candidate: the shape of ``complete._summary`` (``authors``,
    ``year``, ``journal``, ``doi``, ``title``, ``type``, ``source``) with the record's
    ``lccn`` (the identifier it is looked up by), ``edition`` and ``publisher``. ``journal``
    holds the publisher and the edition, so that two editions read differently wherever a
    candidate is listed. Nothing is judged here; the record is read as it is transcribed."""
    root, subs = _marc(xml)
    date = root.findtext(M + "controlfield[@tag='008']", "")
    year = date[7:11] if re.fullmatch(r"[1-9]\d{3}", date[7:11]) else ""
    heads = [h.rstrip(" ,.") for h in subs("100", "a") + subs("700", "a")]
    stated = " ".join(subs("245", "c")).rstrip(" .")
    publisher = "; ".join(p.rstrip(" ,.;:") for p in subs("260", "b") + subs("264", "b"))
    edition = " ".join(subs("250", "a")).rstrip(" ./")
    lccn = normalized_lccn((subs("010", "a") or [""])[0])
    out = {"authors": "; ".join(heads) or stated, "year": year,
           "journal": ", ".join(p for p in (publisher, edition) if p), "doi": None,
           "title": record_title(xml), "type": "book", "source": SOURCE, "lccn": lccn,
           "edition": edition, "publisher": publisher,
           "record_id": root.findtext(M + "controlfield[@tag='001']", "")}
    out["_authors"] = " and ".join(heads) or None
    return out


def _shown(lead):
    return {k: v for k, v in lead.items() if not k.startswith("_")}


# --- the house form of one record ------------------------------------------------------------------

def _edition_house(text):
    """A numbered edition statement ("2nd ed", "Third edition") in the house form
    ``2\\textsuperscript{nd}``; None for any other statement (revised, enlarged, ...)."""
    from .catalogue_review import normalized_edition
    number = normalized_edition(text)
    if not re.fullmatch(r"[1-9]\d?", number):
        return None
    n = int(number)
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}\\textsuperscript{{{suffix}}}"


def _braced_title(title, skip=()):
    """The transcribed title with each capitalised word after the first in braces (not the
    words at the positions in ``skip``). The
    catalogue transcribes a title in sentence case, so such a word is a proper noun or an
    acronym, which the house title protects; the title formatter lowers every other one."""
    words = title.split(" ")
    out = []
    for index, word in enumerate(words):
        found = re.fullmatch(r"([^\w]*)(\w[\w'’.\-&]*?)([^\w]*)", word)
        # The first word is capitalised by position; a capital further inside it ("R&D", "fMRI")
        # is the word's own, and the word is protected like any other.
        capital = found and any(c.isupper() for c in (found[2][1:] if not index else found[2]))
        if index not in skip and capital and not re.search(r"[{}\\$]", word):
            word = found[1] + "{" + found[2] + "}" + found[3]
        out.append(word)
    return " ".join(out)


# Characters TeX reads as commands in plain text. A catalogue (or registry) string is plain
# text: before it is given house braces or commands it goes through ``plain_source``.
_UNREADABLE = re.compile(r"[~^]")
_SPECIAL = re.compile(r"[%&#_~^$\\{}]")


def plain_source(name, text):
    """A plain source string as TeX text: ``% & # _`` escaped (``intake.escape_plain``, the
    package's one escaper, used for PDF and model text too). ``ValueError`` for a string with
    a backslash, a brace or a dollar sign (not plain text) and for one with ``~`` or ``^``:
    their TeX forms are commands the verifier does not read, so the field could not be
    checked. Braces that are already in ``text`` must be the caller's own (the house
    protection of a word), added before this is called."""
    from .intake import escape_plain
    bare = re.sub(r"[{}]", "", text)
    if re.search(r"[\\$<>]", bare) or _UNREADABLE.search(bare):
        raise ValueError(f"{name}: the source text has a character with no plain TeX form the check reads "
                         "(a backslash, a dollar sign, ~ or ^)")
    return escape_plain(name, text)


def _after_article(title):
    """The second word of a title that begins with an article, when the record capitalises
    it; else None. In a record entered under its title (no author heading) the cataloguing
    rule itself capitalises that word, so its capital does not show a proper noun."""
    words = title.split(" ")
    if len(words) > 1 and words[0] in ("The", "A", "An") and words[1][:1].isupper():
        return words[1]
    return None


def _title_case(title):
    """Whether the record capitalises its title word by word (some older records do): then
    a capital says nothing about a proper noun."""
    words = [w for w in re.findall(r"[^\W\d_]{4,}", title)][1:]
    return len(words) >= 3 and all(w[0].isupper() for w in words)


def _place(record, xml, publisher):
    """The place written as the address, and every place the record gives the publisher.
    The first place the record transcribes for the publisher; when the record's 008 code
    names a state the house address carries (``STATE_CODES``) and the place is the record's
    first, the city with that state's code."""
    imprints = record.get("imprints") or [{"publisher": publisher, "address": record["address"]}]
    places = next((g["address"] for g in imprints if g["publisher"] == publisher), record["address"])
    if not places:
        return None, []
    place = places[0]
    code = ET.fromstring(xml).findtext(M + "controlfield[@tag='008']", "")[15:18]
    if code in STATE_CODES and record["address"][:1] == [place]:
        return place.split(",")[0].strip() + ", " + STATE_CODES[code], places
    return place, places


def build_book(xml, key_typed=None):
    """The proposal for one catalogue record (its MARC XML): a ``@book`` in house format
    whose every field the catalogue check accepts for this record.

    The record is read by the check's grammar (``catalogue_review.parse_edition``); a record
    it does not read raises ``ValueError`` with the grammar's reason. Each field is written
    by the format checker's own formatter. A field whose written form the check's comparison
    (``catalogue_review.compare_edition``) does not accept for the record is left out and
    listed in ``unfilled`` with the record's value, as is a part the house format has no
    form for (several publishers, an edition statement that is not a number).
    """
    from . import complete
    from .catalogue_review import compare_edition, parse_edition
    from .complete import FieldChange, Proposal, Unfilled, _Hold, _publisher_format, _written
    from .helpers import authors2key, format_title, reformat_author

    record = parse_edition(xml)
    lead = summary(xml)
    proposal = Proposal(key_typed=key_typed, entry_type="book", record_source=SOURCE)
    fields, stated = {}, {}

    def hold(name, reason, value=""):
        proposal.unfilled.append(Unfilled(name, reason, {SOURCE: value} if value else {}))

    def write(name, value, formatter, raw):
        try:
            written, doubts = _written(name, value, formatter)
        except _Hold as held:
            return hold(name, held.reason, raw)
        fields[name], stated[name] = written, raw
        if doubts:
            proposal.issues.extend(doubts)
            proposal.needs_decision = True
            proposal.changes.append(FieldChange(name, None, written, SOURCE, "question"))
        else:
            proposal.changes.append(FieldChange(name, None, written, SOURCE, "filled"))

    def plain(name, text, raw):
        """``text`` escaped for TeX, or None after listing the field as unfilled."""
        try:
            return plain_source(name, text)
        except ValueError as exc:
            hold(name, str(exc), raw)
            return None

    title = record["title"][0]
    if re.search(r"[<>{}\\$]", title) or _UNREADABLE.search(title):
        hold("title", "title: no plain catalogue title", title)
    elif _title_case(title):
        write("title", format_title(plain_source("title", title)), format_title, title)
        proposal.issues.append("title: the catalogue record capitalises every word of the title, so no proper "
                               "noun could be told from it; brace the proper nouns")
        proposal.needs_decision = True
    else:
        doubtful = _after_article(title) if not record.get("author") else None
        write("title", format_title(plain_source("title", _braced_title(title, skip=(1,) if doubtful else ()))),
              format_title, title)
        if doubtful:
            proposal.issues.append(f"title: the record capitalises {doubtful!r} after the opening article, as the "
                                   "cataloguing rule does for a book entered under its title; it is written in "
                                   "lower case, so brace it if it is a name")
            proposal.needs_decision = True
    for name in ("author", "editor"):
        people = record.get(name) or []
        if not people:
            continue
        said = complete._people_text(people)
        if any(_SPECIAL.search(str(p.get(part) or "")) for p in people for part in ("given", "family")):
            # A name is written as initials and a surname, never escaped: one with a character
            # TeX reads as a command is not written at all.
            hold(name, f"{name}: a name in the record has a character that is not plain text in TeX", said)
            continue
        try:
            value = cp.source_authors({"author": [{"given": p["given"], "family": p["family"]} for p in people]})
        except ValueError as exc:
            hold(name, f"{name}: {exc}", said)
            continue
        write(name, value, reformat_author, said)
    year = str(record["published"]["date-parts"][0][0])
    fields["year"], stated["year"] = year, year
    proposal.changes.append(FieldChange("year", None, year, SOURCE, "filled"))

    publishers = record["publisher"] if isinstance(record["publisher"], list) else [record["publisher"]]
    publisher = publishers[0]
    if len(publishers) > 1:
        # The check accepts either publisher with a place of its own; which one a citation
        # names is the person's choice (the library cites such books both ways).
        said = "; ".join(f"{g['publisher']} ({', '.join(g['address'])})" for g in record.get("imprints") or []) \
            or "; ".join(publishers)
        proposal.issues.append(f"publisher: the record names {len(publishers)} publishers, each with its place "
                               f"({said}); the first is written, and the citation may name the other")
        proposal.needs_decision = True
    escaped = plain("publisher", publisher, publisher)
    if escaped is not None:
        write("publisher", _publisher_format(escaped), _publisher_format, publisher)
    place, places = _place(record, xml, publisher)
    escaped = plain("address", place, "; ".join(places)) if place else None
    if escaped is not None:
        from .helpers import address_codes, address_key, format_journal_name

        def address_format(value):
            return format_journal_name(value, key=address_key, force_caps=address_codes)
        write("address", address_format(escaped), address_format, "; ".join(places))
        if len(places) > 1 and "address" in fields:
            proposal.notes.append(f"address: the record gives the publisher {len(places)} places ("
                                  + "; ".join(places) + "); the first is written")
    if len(publishers) > 1:   # the choice between the publishers is the person's: both fields are questions
        proposal.changes = [FieldChange(c.field, c.typed, c.proposed, c.source, "question")
                            if c.field in ("publisher", "address") else c for c in proposal.changes]
    if record.get("edition"):
        edition = _edition_house(record["edition"])
        if edition is None:
            hold("edition", "edition: the record's edition statement is not a numbered edition, and the "
                 "house format writes only a number; the catalogue check cannot verify the entry "
                 "without the edition", record["edition"])
        else:
            fields["edition"], stated["edition"] = edition, record["edition"]
            proposal.changes.append(FieldChange("edition", None, edition, SOURCE, "filled"))

    # Only what the check accepts stays: the comparison is the check's own, on the same record.
    _, issues = compare_edition(dict(fields, ENTRYTYPE="book"), record, xml)
    for issue in issues:
        name = issue.split(":", 1)[0]
        if name in ("publisher", "address") and name in fields:
            value = fields.pop(name)
            proposal.changes = [c for c in proposal.changes if c.field != name]
            hold(name, f"{name}: the catalogue check does not accept the house form {value!r} for the record's "
                 "value, so it is not written", stated[name])
    order = complete._field_order()
    proposal.changes.sort(key=lambda c: order.index(c.field))
    names = fields.get("author") or fields.get("editor")
    if names:
        proposal.key_proposed = authors2key(names, year)
    else:
        hold("ID", "a key needs the authors (or, for an edited volume, the editors) and the year")
    proposal.proposed_raw = complete.render("book", key_typed or proposal.key_proposed or complete.NO_KEY, fields)
    complete._set_complete(proposal, fields)
    proposal.notes.insert(0, f"Built from the {SOURCE_NAME} record "
                          + (f"LCCN {lead['lccn']}" if lead["lccn"] else lead["record_id"])
                          + (f" (ISBN {', '.join(record['ISBN'])})" if record.get("ISBN") else "") + ".")
    return proposal


# --- finding the record ----------------------------------------------------------------------------

def _same_title(asked, xml):
    """Whether a record carries the asked title: its whole title, or its title before the
    subtitle (a book is often asked for without its subtitle)."""
    try:
        mine = normalize_title(asked)
        whole = record_title(xml)
        return mine in {normalize_title(whole), normalize_title(whole.split(":")[0])}
    except ValueError:
        return False


def find_records(query, client, cache):
    """The catalogue records ``query`` names, as ``(records, how, truncated)``: ``records``
    the MARC XML of each, ``how`` the words for what was asked ("the ISBN 978...").

    An ISBN that finds nothing is asked for once more in its other length (a record of
    before 2007 carries the ten-digit form only). A title and first author are searched as
    the catalogue check searches them (``catalogue_discovery.search_query``; without
    diacritics when the first search finds nothing), so the check later reads the same
    saved response. Every answer is read under one deadline and a size limit
    (``container_titles.within``)."""
    import time
    from .container_titles import RESOLVE_SECONDS, within
    with within(client, time.monotonic() + RESOLVE_SECONDS):
        return _find_records(query, client, cache)


def _find_records(query, client, cache):
    if query.isbn:
        if not _isbn_valid(query.isbn):
            raise ValueError(f"{query.isbn} is not an ISBN: its check digit is wrong")
        found = fetch_query(cache, client, identifier_query("isbn", query.isbn))
        other = _other_isbn(query.isbn)
        if not found["records"] and other:
            found = fetch_query(cache, client, identifier_query("isbn", other))
        how = f"the ISBN {query.isbn}"
        # The answer is believed only for the records that carry the number themselves.
        return _own_records(found, how, isbn=query.isbn), how, found["truncated"]
    if query.lccn:
        found = fetch_query(cache, client, identifier_query("lccn", query.lccn))
        how = f"the LCCN {query.lccn}"
        return _own_records(found, how, lccn=query.lccn), how, found["truncated"]
    fields = {"title": query.title or "", "author": query.author or ""}
    found = fetch_search(cache, client, fields)
    if not found["records"] and search_query(fields, fold_diacritics=True) != found["query"]:
        found = fetch_search(cache, client, fields, fold_diacritics=True)
    return found["records"], "the title and the first author", found["truncated"]


def propose_book(query, client, cache):
    """The proposal for a book asked for by ISBN, LCCN, or title and first author
    (``complete.Query`` with ``isbn``, ``lccn`` or ``book``). Always a ``Proposal``:

    - one record, read by the check's grammar: the built entry, not yet checked
      (``complete.checked`` runs the verifier, the catalogue check included);
    - several records: no entry; ``candidates`` lists them (each with its ``lccn``) and
      ``issues`` says that one has to be chosen. A title search is narrowed to the records
      that carry the title and, when a year was given, that year; only a single such record
      is built;
    - no record, a record the grammar does not read, or the catalogue not answering
      (``status`` "provider_error"): no entry, and ``issues`` says why.
    """
    from .complete import LOOKUP_FAILED, Proposal

    def nothing(reasons, candidates=(), status=None):
        return Proposal(key_typed=query.key, typed_raw=query.raw, entry_type="book", record_source=SOURCE,
                        status=status, issues=[r for r in reasons if r] + list(query.notes),
                        candidates=[_shown(c) for c in candidates], needs_decision=True)

    if not (query.isbn or query.lccn) and not (query.title and query.author):
        return nothing(["A book is looked up in the catalogue by its ISBN, its LCCN, or its title together with "
                        "its first author (or first editor); give one of these"])
    try:
        records, how, truncated = find_records(query, client, cache)
    except ProviderError as exc:
        return nothing([f"The lookup failed: the {SOURCE_NAME} did not answer ({exc}); nothing is proposed"],
                       status=LOOKUP_FAILED)
    except WrongRecord as exc:
        return nothing([f"{exc}; nothing is proposed"])
    except ValueError as exc:
        return nothing([f"{exc}; nothing was looked up"])
    more = (" The catalogue lists more records than the ten it returned; give the ISBN or the LCCN."
            if truncated else "")
    if not records:
        return nothing([f"No {SOURCE_NAME} record has {how}; nothing was searched for in its place" + more])
    leads = [summary(xml) for xml in records]
    chosen, note = None, None
    if query.isbn or query.lccn:
        if len(records) == 1:
            chosen = 0
        else:
            return nothing([f"{len(records)} catalogue records have {how}: editions are distinct works, and one "
                            "has to be chosen." + more], leads)
    else:
        titled = [i for i, xml in enumerate(records) if _same_title(query.title, xml)]
        year = str(query.year or "").strip()
        dated = [i for i in titled if leads[i]["year"] == year] if year else titled
        asked = "the title, the first author and the year" if year else how
        if len(dated) == 1 and not truncated:
            chosen = dated[0]
            others = len(titled) - 1
            note = (f"One catalogue record matches {asked}"
                    + (f" ({others} other record{'s' if others != 1 else ''} with this title, of other years, "
                       "not taken)" if others else "") + ".")
        elif dated:
            return nothing([f"{len(dated)} catalogue records match {asked}: editions are distinct works, and one "
                            "has to be chosen." + more], [leads[i] for i in dated])
        elif titled:
            return nothing([f"No catalogue record with this title is of {year}; {len(titled)} of other years "
                            "found, and none is taken without a choice." + more], [leads[i] for i in titled])
        else:
            return nothing([f"No catalogue record has exactly this title; {len(records)} similar "
                            f"record{'s' if len(records) != 1 else ''} found, and none is taken without a choice."
                            + more], leads)
    lead = leads[chosen]
    try:
        proposal = build_book(records[chosen], key_typed=query.key)
    except (ValueError, KeyError, TypeError, ET.ParseError) as exc:
        named = f"LCCN {lead['lccn']}" if lead["lccn"] else f"record {lead['record_id']}"
        return nothing([f"The catalogue record {named} (\"{lead['title']}\", {lead['year']}) is not one the "
                        f"catalogue check reads, so no entry it could verify can be built from it ({exc}). "
                        "Enter the book by hand; it then needs a human check."])
    proposal.typed_raw = query.raw
    proposal.notes += [n for n in query.notes if n not in proposal.notes]
    if note:
        proposal.notes.insert(1, note)
    proposal.choices.append(built_from(records[chosen], isbn=query.isbn, lccn=query.lccn))
    return proposal


def built_from(xml, isbn=None, lccn=None):
    """The record an entry was built from, kept on its proposal (``choices``): its catalogue
    id and LCCN, and, when a number was asked for, the record's own field that carries it
    (``matched``). ``catalogue_check`` holds the verifier's answer to this record."""
    lead = summary(xml)
    return {"field": "record", "by": SOURCE, "record_id": lead["record_id"], "lccn": lead["lccn"],
            "isbns": record_isbns(xml), "matched": matched_identifier(xml, isbn=isbn, lccn=lccn)}


def catalogue_check(entry, result, client, cache=None, record_id=None):
    """The verifier's result for a book the first check left unresolved, after the catalogue
    check: ``catalogue_review.review_book`` for the entry, under the conditions
    ``run_catalogue_review`` applies (a ``@book`` with authors or editors and no DOI, not yet
    accepted, with no external evidence). Any other entry's result is returned as it is."""
    from .catalogue_review import CATALOGUE_POLICY, review_book
    from .verification import ACCEPTED
    fields = entry["fields"]
    if (result.get("status") in ACCEPTED or result.get("status") != "needs_review"
            or result.get("external_evidence") or str(fields.get("ENTRYTYPE") or "").lower() != "book"
            or fields.get("doi") or not (fields.get("author") or fields.get("editor"))):
        return result
    response, assessed, attempts, queries = review_book(cache if cache is not None else client.cache, client, fields)
    assessed["candidates"] = [c for c in result.get("candidates", []) if c.get("source") != SOURCE] + assessed["candidates"]
    assessed["attempts"] = list(result.get("attempts", [])) + attempts
    assessed["catalogue_review"] = {"policy": CATALOGUE_POLICY, "query": response["query"], "queries": queries}
    if record_id and assessed.get("status") in ACCEPTED and assessed.get("accepted_record_id") != record_id:
        # The entry was built from one record (the one that carries the number asked for); a
        # check that verifies it against another record has not verified that book.
        from .verification import outcome
        held = outcome("needs_review", [
            f"The catalogue check matched the entry to record {assessed.get('accepted_record_id')}, not to the "
            f"record it was built from ({record_id}); it is not taken as verified"], assessed["candidates"])
        held["attempts"], held["catalogue_review"] = assessed["attempts"], assessed["catalogue_review"]
        return held
    return assessed


def leads(client, title, authors, year, rows):
    """Catalogue records for a title and an author, as leads of ``intake.find_candidates``
    (``(lead, BibTeX authors)`` pairs). The catalogue is asked only when both are given: its
    search (the check's own) needs a title and a surname."""
    if not title or not authors:
        return
    import time
    from .container_titles import RESOLVE_SECONDS, within
    fields = {"title": title, "author": authors[0]}
    with within(client, time.monotonic() + RESOLVE_SECONDS):
        found = fetch_search(client.cache, client, fields)
        if not found["records"] and search_query(fields, fold_diacritics=True) != found["query"]:
            found = fetch_search(client.cache, client, fields, fold_diacritics=True)
    for xml in found["records"][:rows]:
        lead = summary(xml)
        names = lead.pop("_authors")
        if lead["lccn"]:   # a record without a control number cannot be asked for again
            yield lead, names


# --- a typed @book -----------------------------------------------------------------------------------

def _typed_record(typed, client, cache, query=None):
    """The catalogue records a typed ``@book`` may be, as ``(records, chosen index or None,
    how it was found, note)``. Its ``isbn`` or ``lccn`` field names the record; otherwise the
    title and the first author (or editor) are searched and the records that carry the title
    are narrowed by the typed year and the typed edition. One record is chosen only when it
    is the only one left; a typed year or edition that no record has narrows nothing when a
    single record carries the title (the difference is then shown as a question)."""
    from .catalogue_review import normalized_edition
    from .complete import Query
    isbn = isbn_text("ISBN " + str(typed.get("isbn") or "").split(",")[0].strip()) if typed.get("isbn") else None
    lccn = lccn_text("LCCN " + str(typed.get("lccn") or "")) if typed.get("lccn") else None
    if query is not None and (query.isbn or query.lccn):      # the record the person chose among the candidates
        isbn, lccn = query.isbn, query.lccn
    if isbn or lccn:
        records, how, truncated = find_records(Query(isbn=isbn, lccn=None if isbn else lccn, book=True), client, cache)
        return records, (0 if len(records) == 1 else None), how, truncated, range(len(records))
    names = typed.get("author") or typed.get("editor") or ""
    if not typed.get("title") or not names:
        raise ValueError("A typed book is looked up by its ISBN or LCCN, or by its title together with its authors "
                         "or editors; the entry has neither")
    records, how, truncated = find_records(Query(title=typed["title"], author=names, book=True), client, cache)
    titled = [i for i, xml in enumerate(records) if _same_title(typed["title"], xml)]
    left = titled
    if len(left) > 1 and typed.get("year"):
        left = [i for i in left if summary(records[i])["year"] == str(typed["year"]).strip()]
    if len(left) > 1 and typed.get("edition"):
        left = [i for i in left if summary(records[i])["edition"]
                and normalized_edition(summary(records[i])["edition"]) == normalized_edition(typed["edition"])]
    chosen = left[0] if len(left) == 1 and not truncated else None
    return records, chosen, how, truncated, (left or titled)


def propose_typed_book(query, client, cache):
    """The completion of a typed ``@book`` from its Library of Congress record: a
    ``Proposal`` in which every field is ``kept`` (typed, and the catalogue check accepts it
    for the record, or the record says nothing of it), ``changed`` (typed, right, and written
    in house format), ``filled`` (not typed; the record's value), a ``question`` (typed, and
    the check does not accept it for the record: the typed value stays in the text and the
    record's is shown beside it) or ``dropped`` (not a house field). Nothing typed is
    overwritten. Several editions are candidates and nothing is proposed. A typed DOI makes
    the entry one the catalogue check does not judge (it is for a book without a supplied
    DOI) and Crossref's record of a book states no edition and no place, so such an entry is
    left as typed, and that is said."""
    from . import complete
    from .catalogue_review import compare_edition, parse_edition
    from .complete import FieldChange, LOOKUP_FAILED, Proposal, Unfilled
    typed = {(k if k in ("ENTRYTYPE", "ID") else k.lower()): v for k, v in (query.fields or {}).items()
             if v is not None and str(v) != ""}

    def nothing(reasons, candidates=(), status=None):
        return Proposal(key_typed=query.key, typed_raw=query.raw, entry_type="book", record_source=SOURCE,
                        status=status, issues=[r for r in reasons if r], doi=typed.get("doi"),
                        candidates=[_shown(c) for c in candidates], needs_decision=True)

    if typed.get("doi"):
        return nothing(["A book with a DOI is not completed: the catalogue check is for a book without a supplied "
                        "DOI, and Crossref's record of a book states no edition and no place of publication. The "
                        "entry is left as typed; `cdlbib verify` checks it against Crossref"])
    try:
        records, chosen, how, truncated, shown = _typed_record(typed, client, cache, query)
    except WrongRecord as exc:
        return nothing([f"{exc}; the entry is left as typed"])
    except ProviderError as exc:
        return nothing([f"The lookup failed: the {SOURCE_NAME} did not answer ({exc}); the entry is left as typed"],
                       status=LOOKUP_FAILED)
    except ValueError as exc:
        return nothing([f"{exc}; the entry is left as typed"])
    more = " The catalogue lists more records than the ten it returned; add the ISBN or the LCCN." if truncated else ""
    if not records:
        return nothing([f"No {SOURCE_NAME} record has {how}; the entry is left as typed" + more])
    if chosen is None:
        leads_ = [summary(records[i]) for i in shown] or [summary(xml) for xml in records]
        return nothing([f"{len(leads_)} catalogue record{'s' if len(leads_) != 1 else ''} may be this book ({how}): "
                        "editions are distinct works, and one has to be chosen; the entry is left as typed." + more],
                       leads_)
    xml = records[chosen]
    lead = summary(xml)
    try:
        built = build_book(xml, key_typed=query.key)
        record = parse_edition(xml)
    except (ValueError, KeyError, TypeError, ET.ParseError) as exc:
        named = f"LCCN {lead['lccn']}" if lead["lccn"] else f"record {lead['record_id']}"
        return nothing([f"The catalogue record {named} (\"{lead['title']}\", {lead['year']}) is not one the "
                        f"catalogue check reads ({exc}); the entry is left as typed and needs a human check"])
    source = {c.field: c for c in built.changes}
    keep = set(complete._field_order())
    house = {k: v for k, v in typed.items() if k in keep and k not in ("ENTRYTYPE", "ID")}
    evidence, _ = compare_edition(dict(house, ENTRYTYPE="book"), record, xml)
    proposal = Proposal(key_typed=query.key, typed_raw=query.raw, entry_type="book", record_source=SOURCE,
                        notes=list(built.notes), issues=list(built.issues), needs_decision=built.needs_decision)
    fields, dropped = {}, []
    for name in sorted(set(house) | set(source)):
        had, change = house.get(name), source.get(name)
        if had is None:                                   # not typed: the record's value
            fields[name] = change.proposed
            proposal.changes.append(FieldChange(name, None, change.proposed, SOURCE, change.kind))
            continue
        formed = complete._house_form(name, had)
        accepted = had == (change.proposed if change else None) or bool(evidence.get(name, {}).get("match"))
        if change is None or accepted:                    # the record is silent, or the check accepts what was typed
            fields[name] = formed
            proposal.changes.append(FieldChange(name, had, formed, "typed" if formed == had else "house format",
                                                "kept" if formed == had else "changed"))
        else:                                             # the check does not accept it: asked, never overwritten
            fields[name] = had
            proposal.changes.append(FieldChange(name, had, change.proposed, SOURCE, "question"))
            proposal.issues.append(f"{name}: the typed value {had!r} is not what the catalogue record has "
                                   f"({change.proposed!r}); the typed value is kept until this is decided")
            proposal.needs_decision = True
    for name in sorted(k for k in typed if k not in keep and k not in ("ENTRYTYPE", "ID")):
        dropped.append(FieldChange(name, typed[name], None, "not a house field", "dropped"))
    # what the record states and the entry does not have, as the builder listed it
    proposal.unfilled = [Unfilled(u.field, u.reason, u.source_values) for u in built.unfilled if u.field not in fields]
    order = complete._field_order()
    proposal.changes.sort(key=lambda c: order.index(c.field))
    proposal.changes += dropped
    names = fields.get("author") or fields.get("editor")
    if names and fields.get("year"):
        from .helpers import authors2key
        proposal.key_proposed = authors2key(names, fields["year"])
    proposal.proposed_raw = complete.render("book", query.key or proposal.key_proposed or complete.NO_KEY, fields)
    complete._set_complete(proposal, fields)
    asked_isbn = isbn_text("ISBN " + str(typed.get("isbn") or "").split(",")[0].strip()) if typed.get("isbn") else None
    asked_lccn = lccn_text("LCCN " + str(typed.get("lccn") or "")) if typed.get("lccn") else None
    proposal.choices.append(built_from(xml, isbn=query.isbn or asked_isbn,
                                       lccn=None if (query.isbn or asked_isbn) else (query.lccn or asked_lccn)))
    return proposal
