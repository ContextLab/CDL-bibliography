"""Source-addressed extraction: model selects lines, Python copies quotations.

Passage selection proves where text came from, not its bibliographic meaning.
Only conservative literal grounding is reported; no citation approval is issued.
"""

import hashlib
import json
import re

from .verification import normalized, normalize_pages, split_authors

FIELDS = [
    "title",
    "author",
    "year",
    "journal",
    "booktitle",
    "volume",
    "number",
    "pages",
    "publisher",
    "doi",
    "isbn",
    "issn",
    "edition",
    "ENTRYTYPE",
]


def numbered_passages(pages):
    passages, seen = [], set()
    for page in pages:
        number, text = page["page"], page["text"]
        if (
            type(number) is not int
            or number < 1
            or number in seen
            or not isinstance(text, str)
        ):
            raise ValueError(
                "Source pages require unique positive page numbers and text"
            )
        seen.add(number)
        offset = 0
        for line, raw in enumerate(text.splitlines(keepends=True), 1):
            end = offset + len(raw)
            if raw.strip():
                passages.append(
                    {
                        "id": f"p{number}l{line}",
                        "page": number,
                        "start": offset,
                        "end": end,
                        "text": raw,
                    }
                )
            offset = end
    if not passages or len(passages) > 2500:
        raise ValueError("Source has no passages or exceeds 2500 lines")
    return passages


def extraction_schema():
    from .openai_research_adapter import object_schema

    return object_schema(
        {
            "fields": {
                "type": "array",
                "items": object_schema(
                    {
                        "field": {"type": "string", "enum": FIELDS},
                        "value": {"type": "string"},
                        "passage_ids": {"type": "array", "items": {"type": "string"}},
                    }
                ),
            },
            "uncertainties": {"type": "array", "items": {"type": "string"}},
        }
    )


# Passage role risk. Literal grounding proves a value was copied from the
# selected offsets; it cannot prove the value plays the bibliographic role being
# claimed. A receipt date, a copyright line, a preprint stamp, an affiliation and
# a reference-list entry are all literally present on the page and all report
# `literal_text_present`. These patterns mark a selection whose printed role
# makes the proposed field suspect.
#
# A match NEVER approves and NEVER blocks. It records an explicit uncertainty and
# a machine-readable flag that any future acceptance rule must consult. A false
# positive withholds acceptance, which is safe; a false negative admits a wrong
# value, which is not. These patterns therefore deliberately over-flag.

REFERENCE_HEADING = re.compile(
    r"^[^\S\n]*(references|bibliography|works cited|literature cited)"
    r"[^\S\n]*$",
    re.IGNORECASE | re.MULTILINE,
)

DATE_ROLE_PATTERNS = [
    (
        "receipt_or_revision_date",
        re.compile(
            r"\b(received|accepted|revised|resubmitted|submitted|in press|"
            r"published online|first published|available online)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "copyright_line",
        re.compile(r"\u00a9|\(c\)\s*\d{4}|\bcopyright\b", re.IGNORECASE),
    ),
    (
        "preprint_version_stamp",
        re.compile(
            r"\b(arxiv|biorxiv|medrxiv|psyarxiv|preprint)\b|v\d+\s*\[",
            re.IGNORECASE,
        ),
    ),
]

# A venue value sitting on an author-affiliation line is usually the authors'
# institution, not the publisher. University presses are real publishers, so the
# marker is affiliation apparatus rather than the word "University".
AFFILIATION_PATTERN = re.compile(
    r"\b(department|faculty|laboratory|institute of|school of|"
    r"corresponding author|e-?mail)\b|@",
    re.IGNORECASE,
)

# Front matter numbers affiliations ("1 Dartmouth College, Hanover NH") and
# ties each to a superscript on the byline. A venue value taken from such a line
# is the authors' institution, not the venue.
AFFILIATION_MARKER = re.compile(r"^[\s*\u2020\u2021]*\d{1,2}[\s.)]+[^\W\d_]")

# An institution named as a venue is suspect unless it names an imprint.
INSTITUTION_VALUE = re.compile(
    r"\b(universit|college|institute|akademi|academy)", re.IGNORECASE
)
IMPRINT_VALUE = re.compile(
    r"\b(press|publish|books|editions|verlag|\u00e9ditions)", re.IGNORECASE
)

VENUE_FIELDS = {"publisher", "journal", "booktitle"}

AUTHOR_CONTINUES = re.compile(r"\s*(,|;|&|\band\b)\s*[^\W\d_]", re.IGNORECASE)


def _author_list_may_be_truncated(value, text):
    """True when the source continues with another name after the last claimed one."""
    try:
        names = [normalized(v) for v in split_authors(value) if v.strip()]
        flat = normalized(text)
    except (ValueError, TypeError):
        return False
    if not names:
        return False
    position = flat.rfind(names[-1])
    if position < 0:
        return False
    return bool(AUTHOR_CONTINUES.match(flat[position + len(names[-1]) :]))


def role_risks(field, value, runs, in_reference_list):
    """Printed roles that make a literally grounded value suspect.

    Returns flag names only. Never an approval, never a rejection.
    """
    risks = []
    if in_reference_list:
        risks.append("reference_list")
    text = " ".join(runs)
    if field == "year":
        risks.extend(n for n, p in DATE_ROLE_PATTERNS if p.search(text))
    if field in VENUE_FIELDS and (
        AFFILIATION_PATTERN.search(text)
        or any(AFFILIATION_MARKER.match(run) for run in runs)
    ):
        risks.append("affiliation_line")
    if (
        field in VENUE_FIELDS
        and INSTITUTION_VALUE.search(value)
        and not IMPRINT_VALUE.search(value)
    ):
        risks.append("institution_named_as_venue")
    if field == "author" and _author_list_may_be_truncated(value, text):
        risks.append("possible_omitted_author")
    return risks


def literal_grounding(field, value, quotes):
    """Substring support only, never an assertion of role/identity/completeness."""
    try:
        transform = normalize_pages if field == "pages" else normalized
        texts = [transform(q) for q in quotes]
        if field == "ENTRYTYPE":
            return (
                False  # A BibTeX category is an interpretation, not printed metadata.
            )
        if field == "author":
            # Require each proposed full name verbatim on a selected source line.
            # Do not discard accents, affiliations, suffixes or expand initials.
            values = [normalized(v) for v in split_authors(value)]
        else:
            values = [transform(value)]
        # Footnote digits can directly follow an author's surname. This reports
        # literal letters only, never identity or completeness of the author list.
        boundary = r"[^\W\d_]" if field == "author" else r"\w"
        return bool(values) and all(
            v
            and any(
                re.search(
                    r"(?<!" + boundary + ")" + re.escape(v) + r"(?!" + boundary + ")", t
                )
                for t in texts
            )
            for v in values
        )
    except (ValueError, TypeError):
        return False


def materialize(finding, pages):
    passages = numbered_passages(pages)
    indexed = {p["id"]: p for p in passages}
    page_text = {p["page"]: p["text"] for p in pages}
    # Offset of a reference-list heading on each page, if any. Text at or after
    # it describes other works, so it cannot supply this work's own metadata.
    reference_start = {}
    for number, text in page_text.items():
        heading = REFERENCE_HEADING.search(text)
        if heading:
            reference_start[number] = heading.end()
    fields = finding.get("fields")
    if not isinstance(finding.get("uncertainties"), list) or any(
        not isinstance(v, str) for v in finding["uncertainties"]
    ):
        raise ValueError("Extraction requires an uncertainties array")
    if not isinstance(fields, list) or not fields:
        raise ValueError("No source selections returned")
    authors = [f for f in fields if isinstance(f, dict) and f.get("field") == "author"]
    if len(authors) > 1:
        combined_ids, names, last_position = [], [], (-1, -1, -1)
        for author in authors:
            ids = author.get("passage_ids")
            value = author.get("value")
            if (
                set(author) != {"field", "value", "passage_ids"}
                or not isinstance(ids, list)
                or not ids
                or any(not isinstance(i, str) or i not in indexed for i in ids)
                or not isinstance(value, str)
                or not value.strip()
                or value in names
                or " and " in value
            ):
                raise ValueError(
                    "Repeated authors require distinct, source-ordered individual names"
                )
            selected = sorted(
                (indexed[i] for i in ids), key=lambda p: (p["page"], p["start"])
            )
            text = normalized("".join(p["text"] for p in selected))
            value_position = text.find(normalized(value))
            position = (selected[0]["page"], selected[0]["start"], value_position)
            if value_position < 0 or position <= last_position:
                raise ValueError("Repeated authors overlap or differ from source order")
            last_position = position
            names.append(value)
            combined_ids.extend(i for i in ids if i not in combined_ids)
        fields = [f for f in fields if f not in authors] + [
            {
                "field": "author",
                "value": " and ".join(names),
                "passage_ids": combined_ids,
            }
        ]
    result, unsupported, risky = {}, [], {}
    for field in fields:
        if not isinstance(field, dict) or set(field) != {
            "field",
            "value",
            "passage_ids",
        }:
            raise ValueError("Extraction requires field, value and passage_ids only")
        name, value, ids = field["field"], field["value"], field["passage_ids"]
        if not isinstance(name, str) or name not in FIELDS or name in result:
            raise ValueError("Unknown or duplicate extracted field")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Empty field value")
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 80
            or any(not isinstance(i, str) or i not in indexed for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError(
                "Passage selection contains unknown, duplicate or excessive IDs"
            )
        selected = sorted(
            (indexed[i] for i in ids), key=lambda p: (p["page"], p["start"])
        )
        # Preserve distinct spans, including across pages; never invent an ellipsis
        # between passages. Each span is an exact slice of the original page text.
        spans = [
            {
                "id": p["id"],
                "page": p["page"],
                "start": p["start"],
                "end": p["end"],
                "quote": page_text[p["page"]][p["start"] : p["end"]],
            }
            for p in selected
        ]
        runs = []
        last = None
        for span in spans:
            if (
                last
                and span["page"] == last["page"]
                and not page_text[span["page"]][last["end"] : span["start"]].strip()
            ):
                runs[-1] += (
                    page_text[span["page"]][last["end"] : span["start"]] + span["quote"]
                )
            else:
                runs.append(span["quote"])
            last = span
        grounded = literal_grounding(name, value, runs)
        if not grounded:
            unsupported.append(name)
        in_reference_list = any(
            span["start"] >= reference_start.get(span["page"], float("inf"))
            for span in spans
        )
        risks = role_risks(name, value, runs, in_reference_list)
        if risks:
            risky[name] = risks
        result[name] = {
            "value": value,
            "page": spans[0]["page"],
            "quote": spans[0]["quote"],
            "passages": spans,
            "grounding": "literal_text_present"
            if grounded
            else "interpretation_required",
            "role_risk": risks,
        }
    return {
        "fields": result,
        "uncertainties": list(finding.get("uncertainties", []))
        + [
            f"{name}: proposed value is not literally supported by selected passages"
            for name in unsupported
        ]
        + [
            f"{name}: selected passage role is {', '.join(flags)}; literal support "
            "does not establish that this text states the work's own "
            f"{name}"
            for name, flags in risky.items()
        ],
        "extraction_policy": "source-passages-1",
        "source_text_sha256": hashlib.sha256(
            json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "unsupported_fields": unsupported,
        "role_risk_fields": risky,
    }
