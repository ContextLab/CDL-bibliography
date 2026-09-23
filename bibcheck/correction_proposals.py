"""Source-backed correction proposals; never edit or approve by themselves.

Pagination repairs require a unique journal identity and agreement between the
publisher's Crossref deposit and a DOI-linked PubMed record. All other supplied
fields must already match. The caller must retain provenance and recheck the
edited raw-entry fingerprint through normal verification.
"""

from copy import deepcopy
import re

from auto_review import authors_with_pubmed_suffixes, compatible_authors, epmc_record, expanded_pages, reassess, safe_compare
from verification import normalize_doi, normalize_journal, normalized, top_level_parts

PAGE_FINDINGS = {
    "pages: missing evidence or mismatch",
    "pages: source supplies a field absent from the citation",
    "pages: source supplies an article number absent from the citation",
    "number: source supplies a field absent from the citation",
}


def pagination_proposal(entry, previous):
    fields = entry["fields"]
    if (fields.get("ENTRYTYPE") != "article"
            or previous.get("status") != "needs_review"
            or previous.get("external_evidence")):
        return None
    choices = {}
    for primary in previous.get("candidates", []):
        if (primary.get("source") != "crossref" or not primary.get("issues")
                or set(primary["issues"]) - PAGE_FINDINGS):
            continue
        try:
            record = primary["record"]
            doi = normalize_doi(record["DOI"])
            if fields.get("doi") and normalize_doi(fields["doi"]) != doi:
                continue
            pages = expanded_pages(record.get("page") or record.get("article-number", ""))
            if not re.fullmatch(r"[a-z]{0,3}\d+(?:-[a-z]{0,3}\d+(?:\.e\d+)?)?", pages):
                continue
            proposed = dict(fields, pages=pages.replace("-", "--"))
            if proposed == fields:
                continue
            primary_evidence, primary_issues = safe_compare(proposed, record)
            if primary_issues:
                continue
            secondaries = [c for c in previous.get("candidates", [])
                           if c.get("source") == "europepmc" and c.get("doi") == primary.get("doi")]
            identifiers = {c.get("raw_record", {}).get("id") for c in secondaries}
            if len(identifiers) != 1:
                continue
            for secondary in secondaries:
                raw = secondary["raw_record"]
                mapped = epmc_record(raw, record)
                if not set(mapped.get("ISSN", [])) & set(record.get("ISSN", [])):
                    continue
                if expanded_pages(mapped.get("page", "")) != pages:
                    continue
                secondary_evidence, secondary_issues = safe_compare(proposed, mapped)
                # Optional publisher/ISBN fields are already checked against
                # Crossref. All supplied issue/DOI/ISSN fields still must agree.
                if any(s.split(":", 1)[0] not in {"publisher", "isbn"} for s in secondary_issues):
                    continue
                if not all(primary_evidence.get(k, {}).get("match")
                           and secondary_evidence.get(k, {}).get("match")
                           for k in ("title", "author", "year", "journal", "volume", "pages")):
                    continue
                result = reassess(dict(entry, fields=proposed), previous)
                if result["status"] != "metadata_verified" or result.get("accepted_doi") != doi:
                    continue
                choices[(doi, pages)] = {
                    "kind": "corroborated_pagination",
                    "key": fields["ID"],
                    "fingerprint": entry["fingerprint"],
                    "changes": {"pages": {"before": fields.get("pages"), "after": proposed["pages"]}},
                    "doi": doi,
                    "pubmed_id": raw["id"],
                    "primary": deepcopy(primary),
                    "secondary": deepcopy(secondary),
                }
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return next(iter(choices.values())) if len(choices) == 1 else None


def replace_pagination(text, entries, proposals):
    """Prepare exact raw-field edits, rejecting stale or ambiguous proposals."""
    seen = set()
    for proposal in proposals:
        key = proposal["key"]
        if key in seen:
            raise ValueError(f"Duplicate proposal: {key}")
        seen.add(key)
        entry = entries[key]
        if entry["fingerprint"] != proposal["fingerprint"]:
            raise ValueError(f"Stale proposal: {key}")
        if set(proposal["changes"]) != {"pages"}:
            raise ValueError(f"Unexpected fields: {key}")
        change = proposal["changes"]["pages"]
        if entry["fields"].get("pages") != change["before"]:
            raise ValueError(f"Old value differs: {key}")
        if not re.fullmatch(r"[a-z]{0,3}\d+(?:--[a-z]{0,3}\d+(?:\.e\d+)?)?", change["after"]):
            raise ValueError(f"Unsafe page value: {key}")
        raw = entry["raw"]
        if text.count(raw) != 1:
            raise ValueError(f"Raw entry is not unique: {key}")
        pattern = re.compile(r"(?im)^(\s*pages\s*=\s*)\{([^{}]*)\}")
        matches = list(pattern.finditer(raw))
        if change["before"] is None:
            if matches or not raw.endswith("}"):
                raise ValueError(f"Cannot insert pages: {key}")
            changed = raw[:-1] + ",\n\tPages = {" + change["after"] + "}}"
        else:
            if len(matches) != 1 or matches[0][2] != change["before"]:
                raise ValueError(f"Pages are not a simple unique field: {key}")
            changed = pattern.sub(lambda m: m[1] + "{" + change["after"] + "}", raw)
        text = text.replace(raw, changed, 1)
    return text


def source_title(source, local):
    """Keep protected names and source acronyms while using repository title style."""
    local_normal = normalized(local)  # Mathematical/unknown markup needs review.
    source_normal = normalized(source)
    if ((len(source.split()) > 2 and source.isupper())
            or (re.match(r"^\s*\d+[.)]\s+", source) and not re.match(r"^\s*\d+[.)]\s+", local))):
        raise ValueError("Possible numbered heading or all-capital source typography")
    words = local_normal.split()
    # Registry text can inherit lost spaces from publisher HTML ("inMind").
    if any(a + b in source_normal.split() and a + b not in words for a, b in zip(words, words[1:])):
        raise ValueError("Possible joined words in source title")
    if re.search(r"[<>{}\\$*†‡]", source):
        raise ValueError("Source title has markup or a possible footnote marker")
    protected = {w.lower(): w for w in re.findall(r"(?<!\w)[A-Za-z][A-Za-z0-9-]*", source)
                 if sum(c.isupper() for c in w) >= 2}
    protected.update({w.lower(): w for w in re.findall(r"\{([^{}\\]+)\}", local)})
    if protected:
        pattern = r"(?<!\w)(?:" + "|".join(re.escape(w) for w in sorted(protected, key=len, reverse=True)) + r")(?!\w)"
        source = re.sub(pattern, lambda m: "{" + protected[m[0].lower()] + "}", source, flags=re.I)
    from helpers import format_title
    # House style: lowercase after a colon. format_title preserves a capital
    # article "A" there because "A" is in caps.txt; never a braced {A}.
    titled = format_title(re.sub(r"([&%#_])", r"\\\1", source))
    titled = re.sub(r"(?<=\w)\u2019(?=\w)", "'", titled)  # typographic apostrophe
    return re.sub(r"(:\s+)A(?=\s)", r"\1a", titled)


JEP_HISTORY = {
    "title": "Journal of Experimental Psychology",
    "issn": "0022-1015",
    "years": [1916, 1974],
    "volumes": [1, 103],
    "successor": "Journal of Experimental Psychology: General",
    "successor_start_year": 1975,
    "sources": ["https://www.ncbi.nlm.nih.gov/nlmcatalog/7502586",
                "https://www.apa.org/pubs/databases/psycarticles/title-history.pdf"],
    "documentary_audit_date": "2026-09-16",
}


def journal_history_proposal(entry, previous):
    """Correct the documented predecessor title, never alias it to its successor."""
    fields = entry["fields"]
    if (fields.get("ENTRYTYPE") != "article" or previous.get("status") != "needs_review"
            or previous.get("external_evidence")
            or fields.get("journal") != JEP_HISTORY["successor"]):
        return None
    choices = {}
    for primary in previous.get("candidates", []):
        try:
            record = primary["record"]
            if (primary.get("source") != "crossref"
                    or record.get("type") != "journal-article"
                    or primary.get("issues") != ["journal: missing evidence or mismatch"]
                    or record.get("container-title") != [JEP_HISTORY["title"]]
                    or JEP_HISTORY["issn"] not in record.get("ISSN", [])
                    or not re.fullmatch(r"[1-9]\d{3}", fields.get("year", ""))
                    or not re.fullmatch(r"[1-9]\d*", fields.get("volume", ""))
                    or not 1916 <= int(fields["year"]) <= 1974
                    or not 1 <= int(fields["volume"]) <= 103):
                continue
            proposed = dict(entry, fields=dict(fields, journal=JEP_HISTORY["title"]))
            doi = normalize_doi(record["DOI"])
            # A known secondary contradiction must not disappear just because
            # the registry becomes a complete match after the venue repair.
            conflict = False
            for secondary in previous.get("candidates", []):
                if secondary.get("source") == "europepmc" and normalize_doi(secondary.get("doi", "")) == doi:
                    mapped = epmc_record(secondary["raw_record"], record)
                    if safe_compare(proposed["fields"], mapped)[1]:
                        conflict = True
            if conflict:
                continue
            checked = reassess(proposed, previous)
            if checked["status"] != "metadata_verified" or checked.get("accepted_doi") != doi:
                continue
            choices[doi] = {"kind": "documented_journal_history", "key": entry["key"],
                            "fingerprint": entry["fingerprint"], "doi": doi,
                            "changes": {"journal": {"before": fields["journal"], "after": JEP_HISTORY["title"]}},
                            "primary": deepcopy(primary), "journal_history": deepcopy(JEP_HISTORY)}
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return next(iter(choices.values())) if len(choices) == 1 else None


def _venue_key(value):
    """Loose venue key for cross-source corroboration only (never acceptance)."""
    import html
    text = _fold(re.sub(r"\s*&\s*", " and ", html.unescape(value or "")))
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text)
    words = re.sub(r"[^\w]+", " ", text).split()
    return " ".join(words[1:] if words[:1] == ["the"] else words)


def journal_text(venue):
    """Registry venue as repository text: entities decoded, '&' written 'and'."""
    import html
    return re.sub(r"\s*&\s*", " and ", html.unescape(venue))


def source_authors(record):
    """Format a complete source byline without inventing or deduplicating people."""
    people = record.get("author", [])
    if not people or any(not p.get("given") or not p.get("family") or p.get("name") for p in people):
        raise ValueError("Incomplete or corporate source byline")
    if any(re.search(r"[<>{}\\$\n\r]", p.get(f, "")) for p in people for f in ("given", "family", "suffix")):
        raise ValueError("Unsupported source author markup")
    names = [p["family"] + ", " + (p["suffix"] + ", " if p.get("suffix") else "") + p["given"] for p in people]
    if len({normalized(n) for n in names}) != len(names):
        raise ValueError("Duplicate people in source byline")
    from helpers import reformat_author
    return reformat_author(" and ".join(names))


def suffix_proposal(entry, previous):
    """Add a documented suffix while preserving every existing given name."""
    from bibtexparser.customization import splitname
    from helpers import reformat_author
    from verification import split_authors
    fields = entry["fields"]
    if (fields.get("ENTRYTYPE") != "article" or previous.get("status") != "needs_review"
            or previous.get("external_evidence")):
        return None
    choices = {}
    for primary in previous.get("candidates", []):
        if (primary.get("source") != "crossref"
                or primary.get("issues") not in ([], ["author: Author suffix differs"])):
            continue
        for secondary in previous.get("candidates", []):
            if secondary.get("source") != "europepmc" or secondary.get("doi") != primary.get("doi"):
                continue
            try:
                mapped = epmc_record(secondary["raw_record"], primary["record"])
                people = authors_with_pubmed_suffixes(primary["record"], mapped)
                if (people is None and compatible_authors(primary["record"], mapped)
                        and any(p.get("suffix") for p in mapped.get("author", []))):
                    people = deepcopy(primary["record"]["author"])
                secondary_evidence = safe_compare(fields, mapped)[0]
                if not all(secondary_evidence.get(f, {}).get("match")
                           for f in ("title", "journal", "year", "volume", "pages")):
                    continue
                names = split_authors(fields["author"])
                if not people or len(names) != len(people):
                    continue
                changed = []
                for name, person in zip(names, people):
                    parts = splitname(name, strict_mode=True)
                    if person.get("suffix") and not parts["jr"]:
                        name = reformat_author(" ".join(parts["von"] + parts["last"]) + ", "
                                               + person["suffix"] + ", " + " ".join(parts["first"]))
                    changed.append(name)
                author = " and ".join(changed)
                if author == fields["author"]:
                    continue
                result = reassess(dict(entry, fields=dict(fields, author=author)), previous)
                doi = normalize_doi(primary["doi"])
                if result["status"] != "metadata_verified" or result.get("accepted_doi") != doi:
                    continue
                choices[(doi, author)] = {"kind": "corroborated_pubmed_suffix", "key": entry["key"],
                    "fingerprint": entry["fingerprint"], "changes": {"author": {"before": fields["author"], "after": author}},
                    "doi": doi, "pubmed_id": secondary["raw_record"]["id"],
                    "primary": deepcopy(primary), "secondary": deepcopy(secondary)}
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    return next(iter(choices.values())) if len(choices) == 1 else None


def issue_year_proposal(entry, previous):
    """Select the cited issue year only when print date and PubMed agree.

    A different online-first year is retained in the source evidence. The
    proposed citation must pass the existing issue-year adjudication policy.
    """
    fields = entry["fields"]
    if (fields.get("ENTRYTYPE") != "article" or previous.get("status") != "needs_review"
            or previous.get("external_evidence")):
        return None
    choices = {}
    for primary in previous.get("candidates", []):
        if (primary.get("source") != "crossref" or not primary.get("issues")
                or any(not i.startswith("year:") for i in primary["issues"])):
            continue
        try:
            record = primary["record"]
            dates = record.get("published-print", {}).get("date-parts", [])
            if len(dates) != 1 or not dates[0] or not re.fullmatch(r"[1-9]\d{3}", str(dates[0][0])):
                continue
            year = str(dates[0][0])
            if year == fields.get("year"):
                continue
            proposed = dict(fields, year=year)
            evidence, issues = safe_compare(proposed, record)
            if any(not i.startswith("year: conflicting") for i in issues):
                continue
            doi = normalize_doi(primary["doi"])
            secondaries = [c for c in previous.get("candidates", [])
                           if c.get("source") == "europepmc" and c.get("doi") == primary["doi"]]
            if len({c.get("raw_record", {}).get("id") for c in secondaries}) != 1:
                continue
            for secondary in secondaries:
                raw = secondary["raw_record"]
                mapped = epmc_record(raw, record)
                secondary_evidence, secondary_issues = safe_compare(proposed, mapped)
                if (any(i.split(":", 1)[0] not in {"publisher", "isbn"} for i in secondary_issues)
                        or not set(mapped.get("ISSN", [])) & set(record.get("ISSN", []))
                        or not all(evidence.get(f, {}).get("match") and secondary_evidence.get(f, {}).get("match")
                                   for f in ("title", "author", "journal", "year", "volume", "pages"))):
                    continue
                checked = reassess(dict(entry, fields=proposed), previous)
                if checked["status"] != "metadata_verified" or checked.get("accepted_doi") != doi:
                    continue
                choices[(doi, year)] = {"kind": "corroborated_issue_year", "key": entry["key"],
                    "fingerprint": entry["fingerprint"], "doi": doi,
                    "changes": {"year": {"before": fields.get("year"), "after": year}},
                    "primary": deepcopy(primary), "secondary": deepcopy(secondary), "pubmed_id": raw["id"]}
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            continue
    return next(iter(choices.values())) if len(choices) == 1 else None


def field_proposal(entry, previous, field):
    """Repair one field only when all other coordinates agree."""
    if field not in {"title", "volume", "number", "year", "doi", "author", "journal"}:
        raise ValueError("Unsupported correction field")
    fields = entry["fields"]
    if (fields.get("ENTRYTYPE") != "article" or previous.get("status") != "needs_review"
            or previous.get("external_evidence")):
        return None
    if field == "doi" and fields.get("doi"):
        return None  # Never replace a supplied identity with another work.
    choices = {}
    allowed = {f"{field}: missing evidence or mismatch", f"{field}: source supplies a field absent from the citation",
               "number: source supplies a field absent from the citation"}
    if field == "doi":
        allowed = {"Source has related versions/works; review publication identity",
                   "number: source supplies a field absent from the citation"}
    elif field == "author":
        allowed = {"author: " + detail for detail in (
            "Missing authors or different author counts", "Author surnames/order differ",
            "Author suffix differs", "Missing or incomplete given names", "Author given names differ")}
        allowed.add("number: source supplies a field absent from the citation")
    for primary in previous.get("candidates", []):
        if (primary.get("source") != "crossref" or (not primary.get("issues") and field != "doi")
                or set(primary.get("issues", [])) - allowed):
            continue
        try:
            record = primary["record"]
            doi = normalize_doi(record["DOI"])
            if fields.get("doi") and normalize_doi(fields["doi"]) != doi:
                continue
            if field == "doi":
                value = doi
            elif field == "journal":
                venues = record.get("container-title", [])
                if len(venues) != 1 or re.search(r"[<>{}\\$\n\r]", venues[0]):
                    continue
                from helpers import format_journal_name
                value = format_journal_name(journal_text(venues[0]))
                # Historical formatter aliases sometimes erase sections or
                # replace historical titles. Do not propagate those changes.
                if normalize_journal(value) != normalize_journal(venues[0]):
                    continue
            elif field == "author":
                # A complete replacement byline must itself match both sources;
                # no inferred initials, author omissions, or reordering to fit.
                # Shared upstream errors can occur in both feeds. Identical
                # people repeated in a byline require source adjudication.
                value = source_authors(record)
                # Never discard given-name detail or people the citation has
                # (audit rule: e.g. full names must not become initials).
                if byline_loses_detail(fields.get("author", ""), record.get("author", [])):
                    continue
            elif field == "title":
                # Derive the full title/subtitle with the same production parser.
                values = safe_compare(fields, record)[0]["title"]["source"]
                if len(values) != 1:
                    continue
                value = source_title(values[0], fields.get("title", ""))
            elif field == "year":
                values = safe_compare(fields, record)[0]["year"]["source"]
                if len(set(values)) != 1:
                    continue
                value = values[0]
            else:
                if field == "volume" and fields.get(field) and not fields[field].isdigit():
                    # A combined volume(issue) must be split without losing the
                    # issue; that is a separate multi-field correction.
                    continue
                value = str(record.get("issue" if field == "number" else field, ""))
                if not re.fullmatch(r"[1-9]\d*", value):
                    continue
            if fields.get(field) == value:
                continue
            if field in {"title", "journal", "author"} and loses_characters(fields.get(field), value):
                continue  # never drop the citation's accents or insert U+FFFD
            proposed = dict(fields, **{field: value})
            primary_evidence, primary_issues = safe_compare(proposed, record)
            if primary_issues:
                continue
            secondaries = [c for c in previous.get("candidates", [])
                           if c.get("source") == "europepmc" and c.get("doi") == primary.get("doi")]
            if len({c.get("raw_record", {}).get("id") for c in secondaries}) != 1:
                continue
            for secondary in secondaries:
                raw = secondary["raw_record"]
                # Journal repairs need PubMed's own title, not the Crossref
                # title normally added through the shared ISSN mapping.
                mapped = epmc_record(raw, {"DOI": doi} if field == "journal" else record)
                if not set(mapped.get("ISSN", [])) & set(record.get("ISSN", [])):
                    continue
                secondary_evidence, secondary_issues = safe_compare(proposed, mapped)
                if any(s.split(":", 1)[0] not in {"publisher", "isbn"} for s in secondary_issues):
                    continue
                required = {"title", "author", "year", "journal", "volume", "pages", field}
                if not all(primary_evidence.get(k, {}).get("match") and secondary_evidence.get(k, {}).get("match") for k in required):
                    continue
                result = reassess(dict(entry, fields=proposed), previous)
                if result["status"] != "metadata_verified" or result.get("accepted_doi") != doi:
                    continue
                choices[(doi, value)] = {"kind": "corroborated_" + field, "key": fields["ID"],
                    "fingerprint": entry["fingerprint"], "changes": {field: {"before": fields.get(field), "after": value}},
                    "doi": doi, "pubmed_id": raw["id"], "primary": deepcopy(primary), "secondary": deepcopy(secondary)}
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return next(iter(choices.values())) if len(choices) == 1 else None


def replace_field(text, entry, proposal):
    """Prepare a single raw-field replacement without reserializing the entry."""
    if entry["fingerprint"] != proposal["fingerprint"] or entry["key"] != proposal["key"]:
        raise ValueError("Stale proposal")
    if len(proposal["changes"]) != 1:
        raise ValueError("Expected one field")
    field, change = next(iter(proposal["changes"].items()))
    if field not in {"title", "volume", "number", "year", "doi", "author", "journal", "publisher", "edition"}:
        raise ValueError("Unsupported field")
    if field == "doi":
        normalize_doi(change["after"])
    if entry["fields"].get(field) != change["before"]:
        raise ValueError("Old value differs")
    # Validate delimiters before inserting into a braced value.
    if any(c in change["after"] for c in "\n\r"):
        raise ValueError("Unsupported value")
    depth = 0
    for token in re.findall(r"\\.|[{}]", change["after"]):
        if token == "{": depth += 1
        elif token == "}": depth -= 1
        if depth < 0:
            raise ValueError("Unbalanced field value")
    if depth:
        raise ValueError("Unbalanced field value")
    raw = entry["raw"]
    prefix = re.match(r"@[A-Za-z]+\s*\{", raw)
    if not prefix or not raw.endswith("}") or text.count(raw) != 1:
        raise ValueError("Raw entry is not unique or has unsupported delimiters")
    parts = top_level_parts(raw[prefix.end():-1])
    matching = [i for i, part in enumerate(parts[1:], 1) if re.match(r"\s*" + field + r"\s*=", part, re.I)]
    if change["before"] is None:
        if matching:
            raise ValueError("Field unexpectedly exists")
        parts.append("\n\t" + field.capitalize() + " = {" + change["after"] + "}")
    else:
        if len(matching) != 1:
            raise ValueError("Field is not unique")
        i = matching[0]
        before = re.match(r"(\s*" + field + r"\s*=\s*)", parts[i], re.I)[1]
        parts[i] = before + "{" + change["after"] + "}"
    changed = raw[:prefix.end()] + ",".join(parts) + "}"
    return text.replace(raw, changed, 1)


def coordinate_proposal(entry, previous):
    """Repair multiple numeric coordinates while title, byline and year agree."""
    if (entry["fields"].get("ENTRYTYPE") != "article" or previous.get("status") != "needs_review"
            or previous.get("external_evidence")):
        return None
    choices = {}
    for primary in previous.get("candidates", []):
        if primary.get("source") != "crossref":
            continue
        issues = primary.get("issues", [])
        if not issues or any(i.split(":", 1)[0] not in {"volume", "number", "pages"} for i in issues):
            continue
        if not all(primary.get("evidence", {}).get(f, {}).get("match") for f in ("title", "author", "year", "journal")):
            continue
        try:
            source = primary["record"]
            values = {"volume": str(source.get("volume", "")), "number": str(source.get("issue", "")),
                      "pages": expanded_pages(source.get("page") or source.get("article-number", "")).replace("-", "--")}
            if not all(re.fullmatch(r"[1-9]\d*", values[f]) for f in ("volume", "number")):
                continue
            if not re.fullmatch(r"[a-z]{0,3}\d+(?:--[a-z]{0,3}\d+(?:\.e\d+)?)?", values["pages"]):
                continue
            old = entry["fields"]
            volume = old.get("volume", "")
            if volume and not volume.isdigit():
                combined = re.fullmatch(r"(\d+)\s*\((\d+)\)", volume)
                if not combined or combined.groups() != (values["volume"], values["number"]):
                    continue  # Never discard a different embedded issue label.
            changes = {f: {"before": old.get(f), "after": value} for f, value in values.items()
                       if not primary.get("evidence", {}).get(f, {}).get("match") and old.get(f) != value}
            if len(changes) < 2:
                continue
            # Leave one coordinate unresolved and reuse the full paired-source
            # proposal checks, including all edited coordinates and DOI identity.
            last = "pages" if "pages" in changes else "number"
            interim = dict(entry, fields=dict(old, **{f: c["after"] for f, c in changes.items() if f != last}))
            reviewed = reassess(interim, previous)
            proposal = (pagination_proposal(interim, reviewed) if last == "pages"
                        else field_proposal(interim, reviewed, last))
            if not proposal or proposal["changes"][last]["after"] != changes[last]["after"]:
                continue
            proposal.update(kind="corroborated_coordinates", changes=changes, primary=deepcopy(primary))
            choices[(proposal["doi"], tuple((f, c["after"]) for f, c in sorted(changes.items())))] = proposal
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return next(iter(choices.values())) if len(choices) == 1 else None


def replace_coordinates(text, entry, proposal):
    """Prepare a multi-coordinate edit; the runner validates the full parsed file."""
    if not 2 <= len(proposal["changes"]) <= 3 or set(proposal["changes"]) - {"volume", "number", "pages"}:
        raise ValueError("Expected two or three numeric coordinates")
    if text.count(entry["raw"]) != 1:
        raise ValueError("Raw entry is not unique")
    working = deepcopy(entry)
    for field, change in proposal["changes"].items():
        single = dict(proposal, changes={field: change})
        if field == "pages":
            changed = replace_pagination(working["raw"], {entry["key"]: working}, [single])
        else:
            changed = replace_field(working["raw"], working, single)
        working["raw"] = changed
        working["fields"][field] = change["after"]
    return text.replace(entry["raw"], working["raw"], 1)


def publication_proposal(entry, previous, *, include_identity_fields=False):
    """Corroborate multiple publication fields for an unchanged title/byline.

    Each changed field independently passes its existing single-field policy
    against the complete proposed citation. This includes PubMed's own venue
    title and the unique registry year checks; no weaker multi-field shortcut.
    """
    if (entry["fields"].get("ENTRYTYPE") != "article" or previous.get("status") != "needs_review"
            or previous.get("external_evidence")):
        return None
    allowed = {"journal", "year", "volume", "number", "pages"}
    if include_identity_fields:
        allowed |= {"title", "author"}
    choices = {}
    for primary in previous.get("candidates", []):
        if (primary.get("source") != "crossref" or not primary.get("issues")
                or any(i.split(":", 1)[0] not in allowed for i in primary["issues"])):
            continue
        matched = {f for f in ("title", "author", "year", "journal", "volume", "pages")
                   if primary.get("evidence", {}).get(f, {}).get("match")}
        if include_identity_fields:
            if len(matched) < 3 or not matched & {"title", "author"}:
                continue
        elif not {"title", "author"} <= matched:
            continue
        try:
            fields, record = entry["fields"], primary["record"]
            from helpers import format_journal_name
            values = {"volume": str(record.get("volume", "")), "number": str(record.get("issue", "")),
                      "pages": expanded_pages(record.get("page") or record.get("article-number", "")).replace("-", "--")}
            years = primary["evidence"]["year"]["source"]
            if len(set(years)) == 1:
                values["year"] = years[0]
            venues = record.get("container-title", [])
            if len(venues) == 1:
                values["journal"] = format_journal_name(journal_text(venues[0]))
            if include_identity_fields:
                titles = primary["evidence"]["title"]["source"]
                if len(titles) == 1 and "title" not in matched:
                    values["title"] = source_title(titles[0], fields.get("title", ""))
                if "author" not in matched:
                    from helpers import reformat_author
                    people = record.get("author", [])
                    if (people and all(p.get("given") and p.get("family") and not p.get("name") for p in people)
                            and not byline_loses_detail(fields.get("author", ""), people)):
                        values["author"] =reformat_author(" and ".join(p["family"] + ", " + (p["suffix"] + ", " if p.get("suffix") else "") + p["given"] for p in people))
            changes = {f: {"before": fields.get(f), "after": value} for f, value in values.items()
                       if not primary.get("evidence", {}).get(f, {}).get("match") and fields.get(f) != value}
            if (not 2 <= len(changes) <= 4
                    or not set(changes) & ({"title", "author"} if include_identity_fields else {"year", "journal"})):
                continue
            proofs = {}
            for field, change in changes.items():
                interim = dict(entry, fields=dict(fields, **{f: c["after"] for f, c in changes.items() if f != field}))
                reviewed = reassess(interim, previous)
                proof = (pagination_proposal(interim, reviewed) if field == "pages"
                         else field_proposal(interim, reviewed, field))
                if not proof or proof["changes"][field] != change or proof["doi"] != normalize_doi(record["DOI"]):
                    break
                proofs[field] = proof
            if len(proofs) != len(changes):
                continue
            proof = next(iter(proofs.values()))
            proposal = {"kind": "corroborated_combined" if include_identity_fields else "corroborated_publication", "key": entry["key"], "fingerprint": entry["fingerprint"],
                        "changes": changes, "doi": proof["doi"], "pubmed_id": proof["pubmed_id"],
                        "primary": deepcopy(primary), "secondary": proof["secondary"]}
            choices[(proof["doi"], tuple((f, c["after"]) for f, c in sorted(changes.items())))] = proposal
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return next(iter(choices.values())) if len(choices) == 1 else None


def replace_publication(text, entry, proposal):
    allowed = {"year", "journal", "volume", "number", "pages"}
    if proposal.get("kind") == "corroborated_combined":
        allowed |= {"title", "author"}
    if (not 2 <= len(proposal["changes"]) <= 4
            or set(proposal["changes"]) - allowed):
        raise ValueError("Expected two to four publication fields")
    if text.count(entry["raw"]) != 1:
        raise ValueError("Raw entry is not unique")
    working = deepcopy(entry)
    for field, change in proposal["changes"].items():
        single = dict(proposal, changes={field: change})
        if field == "pages":
            changed = replace_pagination(working["raw"], {entry["key"]: working}, [single])
        else:
            changed = replace_field(working["raw"], working, single)
        working["raw"] = changed
        working["fields"][field] = change["after"]
    return text.replace(entry["raw"], working["raw"], 1)


# ---------------------------------------------------------------------------
# Resolver 28 / Phase 0 (verification/phase0-2026-09-22/README.md).
# User policy 2026-09-22: one authoritative source suffices. If Crossref or
# PubMed holds the record for the cited work, a citation may be corrected from
# it without a second agreeing source. Identity is never loosened: it comes
# from the work's own DOI, or from agreement on nearly every other field.
# ---------------------------------------------------------------------------

SINGLE_SOURCE_FIELDS = ("title", "author", "year", "journal", "volume", "number", "pages")
MAX_SINGLE_SOURCE_FIELDS = 2


def _fold(value):
    import unicodedata
    text = unicodedata.normalize("NFKD", normalized(value))
    return "".join(c for c in text if not unicodedata.combining(c))


def _marks(value):
    """Number of diacritics in a (LaTeX or Unicode) value; -1 if unparsable."""
    import unicodedata
    try:
        return sum(1 for c in unicodedata.normalize("NFD", normalized(value or "")) if unicodedata.combining(c))
    except ValueError:
        return -1


def _braced_words(text):
    """Lower-case words carrying case-protecting braces (not {\\'a} accents)."""
    words = set()
    for token in re.findall(r"\S*\{(?!\\)[^{}]*\}\S*", text or ""):
        for word in re.findall(r"[^\W\d_]+", re.sub(r"[{}]", "", token)):
            words.add(word.lower())
    return words


def _plain_words(text):
    return {w.lower() for w in re.findall(r"[^\W\d_]+", re.sub(r"\\[A-Za-z]+|[{}\\]", "", text or ""))}


def loses_characters(before, after):
    """The replacement drops diacritics, case-protecting braces on a word it
    keeps (e.g. {B}owers -> bowers), or contains a replacement character."""
    if "\ufffd" in (after or "") or _marks(after) < _marks(before):
        return True
    kept = (_braced_words(before) & _plain_words(after)) - _braced_words(after)
    return bool(kept)


def _title_words(value):
    return re.sub(r"[^\w]+", " ", _fold(value)).split()


def _word_distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def title_small_difference(local, source):
    """At most two word-level edits, or the citation omits the source subtitle."""
    try:
        a, b = _title_words(local), _title_words(source)
    except ValueError:
        return False
    if not a or not b:
        return False
    if _word_distance(a, b) <= 2:
        return True
    main = _title_words(re.split(r":\s", normalized(source), maxsplit=1)[0])
    return ":" in normalized(source) and main == a and len(a) >= 3


def _first_family(value):
    from bibtexparser.customization import splitname
    from verification import split_authors
    name = split_authors(value)[0]
    if name.startswith("{"):
        return _fold(name)
    parts = splitname(name, strict_mode=True)
    return _fold(" ".join(parts["von"] + parts["last"]))


def _record_years(record):
    years = set()
    for date in ("published", "published-print", "published-online", "issued"):
        for parts in record.get(date, {}).get("date-parts", []) or []:
            if parts and re.fullmatch(r"[1-9]\d{3}", str(parts[0])):
                years.add(str(parts[0]))
    return years


def _first_page(value):
    return normalized(str(value or "")).replace("--", "-").split("-")[0]


def single_source_identity(fields, record):
    """Return the identity rule a source record satisfies, or None.

    I0: the citation supplies this DOI. I1: title within two word edits (or the
    citation omits the source subtitle), first-author surname, year, venue, and
    volume or first page all agree. I2: exact title, first-author surname, year,
    volume and first page agree (venue may differ and is then corrected).
    """
    try:
        if fields.get("doi"):
            return "I0" if normalize_doi(fields["doi"]) == normalize_doi(record.get("DOI", "")) else None
        titles = record.get("title") or []
        if len(titles) != 1 or not fields.get("title") or not fields.get("author") or not record.get("author"):
            return None
        subtitles = [s for s in record.get("subtitle", []) or [] if s.strip()]
        title = titles[0] + (": " + subtitles[0] if len(subtitles) == 1 and not normalized(titles[0]).endswith(normalized(subtitles[0])) else "")
        person = record["author"][0]
        family = _fold(person.get("family") or person.get("name") or "")
        if not family or family != _first_family(fields["author"]):
            return None
        if str(fields.get("year", "")) not in _record_years(record):
            return None
        from auto_review import expanded_pages
        same_volume = bool(fields.get("volume") and record.get("volume")
                           and normalized(fields["volume"]) == normalized(str(record["volume"])))
        page = record.get("page") or record.get("article-number")
        same_page = bool(fields.get("pages") and page
                         and _first_page(expanded_pages(fields["pages"])) == _first_page(expanded_pages(str(page))))
        venues = record.get("container-title") or []
        same_venue = bool(fields.get("journal") and any(
            normalize_journal(fields["journal"]) == normalize_journal(v) for v in venues))
        if same_venue and (same_volume or same_page) and title_small_difference(fields["title"], title):
            return "I1"
        if same_volume and same_page and normalize_title_safe(fields["title"]) == normalize_title_safe(title):
            return "I2"
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        return None
    return None


def normalize_title_safe(value):
    from verification import normalize_title
    try:
        return normalize_title(value)
    except ValueError:
        return None


def byline_adds_information(local, people):
    """A source byline may replace the citation's only if nothing is lost.

    Same number of people (or the citation ends in 'others' and the source
    extends it); every citation given-name token is an initial/equal of the
    source token in order; surnames equal up to accents or a two-letter typo
    fix; any citation suffix is kept by the source.
    """
    from bibtexparser.customization import splitname
    from verification import given_name_tokens, given_token_matches, normalize_author_suffix, split_authors
    names = split_authors(local)
    if names and normalized(names[-1]) == "others":
        names = names[:-1]
        if len(names) >= len(people):
            return False
    elif len(names) != len(people):
        return False
    for name, person in zip(names, people):
        if name.startswith("{") or person.get("name"):
            return False
        parts = splitname(name, strict_mode=True)
        family = " ".join(parts["von"] + parts["last"])
        if _fold(family) != _fold(person.get("family", "")):
            if (_word_distance(list(_fold(family)), list(_fold(person.get("family", "")))) > 2
                    or surname_form_only(family, person.get("family", ""))
                    or _only_deletions(_fold(family), _fold(person.get("family", "")))):
                return False
        if parts["jr"] and normalize_author_suffix(" ".join(parts["jr"])) != normalize_author_suffix(person.get("suffix", "")):
            return False
        if _marks(name) > _marks(person.get("family", "") + " " + person.get("given", "")):
            return False  # the source lacks the citation's accents
        old = given_name_tokens(" ".join(parts["first"]))
        new = given_name_tokens(person.get("given", ""))
        if not old or len(old) > len(new) or any(not given_token_matches(a, b) for a, b in zip(old, new)):
            return False
    return True


def _only_deletions(longer, shorter):
    """True when ``shorter`` is ``longer`` with letters removed: registries drop
    characters they cannot encode (e.g. Turkish dotless i), so a source that
    only deletes letters is not trusted to correct a surname on its own."""
    if len(shorter) >= len(longer):
        return False
    it = iter(longer)
    return all(c in it for c in shorter)


def surname_form_only(local, source):
    """Surnames that differ only by spacing, hyphens, braces or case."""
    def squash(value):
        return re.sub(r"[\s{}\-]+", "", _fold(value))
    try:
        return normalized(local) != normalized(source) and _fold(local) != _fold(source) and squash(local) == squash(source)
    except ValueError:
        return False


def byline_loses_detail(local, people):
    """True when a replacement byline would drop people or given-name detail.

    Only people whose surnames agree (up to accents) are compared, so a
    garbled or placeholder byline can still be replaced by a complete one.
    A citation with more people than the source always loses detail.
    """
    from bibtexparser.customization import splitname
    from verification import given_name_tokens, split_authors
    try:
        names = [n for n in split_authors(local) if normalized(n) != "others"]
        if len(names) > len(people):
            return True
        if len(names) != len(people):
            return False
        for name, person in zip(names, people):
            if name.startswith("{"):
                continue
            parts = splitname(name, strict_mode=True)
            family = " ".join(parts["von"] + parts["last"])
            if surname_form_only(family, person.get("family", "")):
                return True  # e.g. "den Nijs" -> "denNijs": a source spacing defect
            if _fold(family) != _fold(person.get("family", "")):
                continue
            if _marks(name) > _marks(person.get("family", "") + " " + person.get("given", "")):
                return True  # the source lacks the citation's accents
            old = given_name_tokens(" ".join(parts["first"]))
            new = given_name_tokens(person.get("given", ""))
            if len(old) > len(new) or any(len(a) > 1 and len(b) == 1 for a, b in zip(old, new)):
                return True
        return False
    except (ValueError, TypeError, KeyError, AttributeError):
        return True


def _issue_fields(issues):
    fields, blockers = set(), set()
    for issue in issues:
        head = issue.split(":", 1)[0]
        if issue.endswith("no deterministic verifier for this field"):
            blockers.add("extra-field:" + head)
        elif issue.startswith("publication type/version"):
            blockers.add("type")
        elif issue.startswith("Source flags an update"):
            blockers.add("update")
        elif issue.startswith("Source has related versions"):
            blockers.add("relation")
        elif issue.startswith("Unsupported source metadata"):
            blockers.add("unsupported-source")
        elif head in SINGLE_SOURCE_FIELDS or head in {"doi", "publisher", "isbn", "issn"}:
            fields.add(head)
        else:
            blockers.add("other:" + head)
    return fields, blockers


def _pubmed_for(previous, doi):
    raws = {}
    for c in previous.get("candidates", []):
        if c.get("source") == "europepmc" and c.get("raw_record"):
            try:
                if normalize_doi(c.get("doi", "")) == doi:
                    raws[str(c["raw_record"].get("id"))] = c["raw_record"]
            except ValueError:
                continue
    return raws


def single_source_proposal(entry, previous, explain=None):
    """Correct up to two fields from the one source holding the cited record.

    Returns a proposal or None; ``explain`` (a dict) receives the hold reason.
    Publisher is ignored on @article (user policy: drop the field); a proposal
    for an entry that still has one is marked ``requires_publisher_drop``.
    Every value is copied from the source record; the other source, when it
    holds the same field, must agree or the entry is held. The edited entry
    must then verify through the ordinary resolver on the same DOI.
    """
    from auto_review import unique_crossref_primaries
    from verification import apa_twin_key
    explain = explain if explain is not None else {}
    fields = entry["fields"]
    if fields.get("ENTRYTYPE") != "article":
        explain["reason"] = "not-article"
        return None
    if previous.get("status") != "needs_review" or previous.get("external_evidence"):
        explain["reason"] = "not-eligible"
        return None
    evaluated = {k: v for k, v in fields.items() if k != "publisher"}
    identified = {}
    for candidate in previous.get("candidates", []):
        if candidate.get("source") != "crossref":
            continue
        try:
            doi = normalize_doi(candidate["doi"])
        except (ValueError, KeyError, TypeError):
            continue
        if doi in identified:
            continue
        primaries = unique_crossref_primaries(previous["candidates"], doi)
        rule = single_source_identity(evaluated, primaries[0]["record"]) if len(primaries) == 1 else None
        pubmed = _pubmed_for(previous, doi)
        mapped = None
        if len(pubmed) == 1:
            try:
                mapped = epmc_record(next(iter(pubmed.values())), primaries[0]["record"])
                rule = rule or single_source_identity(evaluated, dict(mapped, DOI=doi))
            except (ValueError, KeyError, TypeError, AttributeError):
                mapped = None
        if rule:
            if len(primaries) != 1:
                identified[doi] = ("ambiguous-duplicate-records", None, None)
            else:
                identified[doi] = (rule, primaries[0], mapped)
    works = {}
    for doi, value in identified.items():
        works.setdefault(apa_twin_key(doi), []).append((doi, value))
    if not works:
        explain["reason"] = "no-identified-record"
        return None
    if len(works) > 1:
        explain["reason"] = "ambiguous-identity"
        explain["dois"] = sorted(identified)
        return None
    choices = next(iter(works.values()))
    choices = [c for c in choices if c[1][0] != "ambiguous-duplicate-records"]
    if not choices:
        explain["reason"] = "ambiguous-identity"
        return None
    # APA twins: prefer the single-slash form, as the resolver does.
    choices.sort(key=lambda c: "//" in c[0])
    doi, (rule, primary, mapped) = choices[0]
    record = primary["record"]
    explain.update(doi=doi, identity=rule)
    issues = safe_compare(evaluated, record)[1]
    from verification import YEAR_CONFLICT, print_year_selects_cited
    if YEAR_CONFLICT in issues:
        # Resolver 28 print-year route: judged again on the final proposal.
        probe = dict(evaluated, volume=str(record.get("volume") or ""),
                     pages=str(record.get("page") or record.get("article-number") or ""))
        if print_year_selects_cited(probe, record):
            issues = [i for i in issues if i != YEAR_CONFLICT]
    changed, blockers = _issue_fields(issues)
    changed.discard("publisher")
    blockers = {b for b in blockers if b != "extra-field:publisher"}
    if blockers:
        explain["reason"] = "not-correctable"
        explain["blockers"] = sorted(blockers)
        explain["fields"] = sorted(changed)
        return None
    if "doi" in changed or "issn" in changed or "isbn" in changed:
        explain["reason"] = "identifier-conflict"
        return None
    # An omitted optional issue is only advisory once volume and pages agree.
    if changed == {"number"} and not fields.get("number"):
        explain["reason"] = "advisory-only"
        return None
    if not changed:
        explain["reason"] = "no-field-differs"
        return None
    if len(changed) > MAX_SINGLE_SOURCE_FIELDS:
        explain["reason"] = "too-many-fields"
        explain["fields"] = sorted(changed)
        return None
    values, sources = {}, {}
    try:
        from helpers import format_journal_name
        for field in sorted(changed):
            value, origin = None, "crossref"
            if field == "title":
                titles = safe_compare(evaluated, record)[0]["title"]["source"]
                if len(titles) != 1:
                    raise ValueError("title: several source titles")
                old_words, new_words = _title_words(fields.get("title", "")), _title_words(titles[0])
                if len(new_words) < len(old_words) and old_words[:len(new_words)] == new_words:
                    raise ValueError("title: citation title has words the source lacks")
                value = source_title(titles[0], fields.get("title", ""))
                if mapped and normalize_title_safe(mapped["title"][0]) != normalize_title_safe(titles[0]):
                    raise ValueError("title: sources disagree")
            elif field == "author":
                people = record.get("author") or []
                if not people and mapped:
                    people, origin = mapped["author"], "pubmed"
                if not byline_adds_information(fields.get("author", ""), people):
                    raise ValueError("author: citation byline has detail the source lacks")
                value = source_authors({"author": people})
                if mapped and origin == "crossref" and not compatible_authors({"author": people}, mapped):
                    raise ValueError("author: sources disagree")
            elif field == "year":
                prints = [str(p[0]) for p in record.get("published-print", {}).get("date-parts", []) if p]
                years = sorted(_record_years(record))
                value = prints[0] if len(prints) == 1 else (years[0] if len(years) == 1 else None)
                if not value:
                    raise ValueError("year: no single print or publication year")
                if mapped and str(mapped["published"]["date-parts"][0][0]) != value:
                    raise ValueError("year: sources disagree")
            elif field == "journal":
                venues = record.get("container-title") or []
                if len(venues) != 1 or re.search(r"[<>{}\\$\n\r]", venues[0]):
                    raise ValueError("journal: no single registry venue")
                value = format_journal_name(journal_text(venues[0]))
                if normalize_journal(value) != normalize_journal(venues[0]):
                    raise ValueError("journal: formatter changes the venue")
            elif field in {"volume", "number"}:
                key = "issue" if field == "number" else "volume"
                value = str(record.get(key) or "")
                if not value and mapped:
                    value, origin = str(mapped.get(key) or ""), "pubmed"
                if not re.fullmatch(r"[1-9]\d*", value):
                    raise ValueError(field + ": no plain numeric source value")
                if mapped and mapped.get(key) and origin == "crossref" and str(mapped[key]) != value:
                    raise ValueError(field + ": sources disagree")
            elif field == "pages":
                raw = record.get("page") or record.get("article-number") or ""
                if not raw and mapped:
                    raw, origin = mapped.get("page") or "", "pubmed"
                pages = expanded_pages(raw)
                if not re.fullmatch(r"[a-z]{0,3}\d+(?:-[a-z]{0,3}\d+(?:\.e\d+)?)?", pages):
                    raise ValueError("pages: unsupported source locator")
                if mapped and mapped.get("page") and origin == "crossref" and expanded_pages(mapped["page"]) != pages:
                    raise ValueError("pages: sources disagree")
                value = pages.replace("-", "--")
            values[field], sources[field] = value, origin
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        explain["reason"] = "value-held"
        explain["detail"] = str(exc)
        explain["fields"] = sorted(changed)
        return None
    values = {f: v for f, v in values.items() if fields.get(f) != v}
    if not values:
        explain["reason"] = "no-change-possible"
        explain["fields"] = sorted(changed)
        return None
    lossy = sorted(f for f, v in values.items() if loses_characters(fields.get(f), v))
    if lossy:
        explain["reason"] = "value-held"
        explain["detail"] = "; ".join(f"{f}: source value drops accents or has a replacement character" for f in lossy)
        explain["fields"] = sorted(changed)
        return None
    subclasses = {f: change_subclass(f, fields.get(f), v, year=fields.get("year"),
                                     corroborated=mapped is not None and sources[f] == "crossref")
                  for f, v in values.items()}
    held = sorted(f for f, sub in subclasses.items() if sub in HELD_SUBCLASSES)
    if subclasses.get("journal") in {"journal-other-venue", "journal-section"}:
        # Crossref carries a journal's CURRENT title (e.g. Psychiatric Services
        # for 1983 Hospital and Community Psychiatry). A different venue name is
        # proposed only when the DOI-linked PubMed record, which keeps the title
        # at publication, names the same venue.
        raws = list(_pubmed_for(previous, doi).values())
        titles = [r.get("journalInfo", {}).get("journal", {}).get("title", "") for r in raws]
        if len(raws) != 1 or _venue_key(titles[0]) != _venue_key(values["journal"]):
            held.append("journal")
            subclasses["journal"] = "journal-replacement-unconfirmed"
    if held:
        explain["reason"] = "value-held"
        explain["detail"] = "; ".join(f"{f}: {subclasses[f]}" for f in held)
        explain["fields"] = sorted(changed)
        return None
    proposed = dict(evaluated, **values)
    remaining = safe_compare(proposed, record)[1]
    if remaining == [YEAR_CONFLICT] and print_year_selects_cited(proposed, record):
        remaining = []
    if remaining and not (mapped and not [
            i for i in safe_compare(proposed, mapped)[1] if i.split(":", 1)[0] not in {"publisher", "isbn"}]):
        explain["reason"] = "would-not-match-source"
        explain["fields"] = sorted(changed)
        return None
    checked = reassess(dict(entry, fields=proposed), previous)
    accepted = checked.get("accepted_doi")
    if checked["status"] != "metadata_verified" or not accepted or apa_twin_key(accepted) != apa_twin_key(doi):
        explain["reason"] = "would-not-verify"
        explain["fields"] = sorted(changed)
        explain["issues"] = checked.get("issues", [])
        return None
    origin = sorted(set(sources.values()))
    both = mapped is not None
    return {"kind": "single_source_" + "+".join(sorted(values)), "rule": "S1-" + rule,
            "key": entry["key"], "fingerprint": entry["fingerprint"], "doi": accepted,
            "source": "+".join(origin) + ("; pubmed holds the record and does not contradict" if both and origin == ["crossref"] else ""),
            "changes": {f: {"before": fields.get(f), "after": v} for f, v in sorted(values.items())},
            "subclasses": subclasses,
            "requires_publisher_drop": bool(fields.get("publisher")),
            "primary": deepcopy(primary)}


# Changes never proposed from one source: they carry no information gain or a
# known registry defect (typography-only titles; a cited venue name that the
# registry merely extends with a section/subtitle, often the current title of a
# renamed journal rather than its title at publication).
HELD_SUBCLASSES = {"title-typography-only", "journal-extension"}
RISKY_SUBCLASSES = {"author-surname-spelling", "title-crossref-only", "pages-different-start",
                    "journal-section", "journal-other-venue", "volume", "year-print-year"}


def change_subclass(field, before, after, year=None, corroborated=False):
    """Coarse kind of a single-field change, for holds and spot-check classes."""
    before = before or ""
    try:
        if field == "title":
            if _title_words(before) == _title_words(after):
                return "title-typography-only"
            return "title-crossref+pubmed" if corroborated else "title-crossref-only"
        if field == "author":
            from bibtexparser.customization import splitname
            from verification import split_authors
            old = [n for n in split_authors(before) if normalized(n) != "others"]
            new = split_authors(after)
            if len(old) != len(new) or normalized(before).endswith(" others"):
                return "author-byline-completion"
            families = [(_fold(" ".join(splitname(a, strict_mode=True)["von"] + splitname(a, strict_mode=True)["last"])),
                         _fold(" ".join(splitname(b, strict_mode=True)["von"] + splitname(b, strict_mode=True)["last"])))
                        for a, b in zip(old, new) if not a.startswith("{")]
            if any(a != b for a, b in families):
                return "author-surname-spelling"
            return "author-given-names-accents-suffix"
        if field == "journal":
            a, b = _fold(before), _fold(after)
            a, b = re.sub(r"^the\s+", "", a), re.sub(r"^the\s+", "", b)
            if (normalized(before) == normalized(JEP_HISTORY["successor"])
                    and normalized(after) == normalized(JEP_HISTORY["title"])
                    and re.fullmatch(r"[1-9]\d{3}", str(year or "")) and int(year) <= JEP_HISTORY["years"][1]):
                return "journal-jep-history"
            if _word_distance(list(a), list(b)) <= 3:
                return "journal-typo"
            wa, wb = _title_words(before), _title_words(after)
            if wa and wb and (wa == wb[:len(wa)] or wb == wa[:len(wb)]
                              or " ".join(wa) in " ".join(wb) or " ".join(wb) in " ".join(wa)):
                return "journal-extension"
            main_a, main_b = re.split(r"[:/]", a)[0].strip(), re.split(r"[:/]", b)[0].strip()
            if main_a == main_b:
                return "journal-section"
            return "journal-other-venue"
        if field == "pages":
            from auto_review import expanded_pages
            first = lambda v: expanded_pages(v).split("-")[0] if v else ""
            return "pages-complete-range" if first(before) and first(before) == first(after) else (
                "pages-added" if not before else "pages-different-start")
        if field == "year":
            return "year-print-year"
        return field
    except (ValueError, TypeError, KeyError, IndexError):
        return field + "-unclassified"


def drop_publisher_proposal(entry):
    """User policy 2026-09-22: @article entries do not carry ``publisher``."""
    fields = entry["fields"]
    if fields.get("ENTRYTYPE") != "article" or not fields.get("publisher"):
        return None
    return {"kind": "drop_publisher", "rule": "P1", "key": entry["key"], "fingerprint": entry["fingerprint"],
            "changes": {"publisher": {"before": fields["publisher"], "after": None}}}


def add_doi_proposal(entry, result):
    """Add the DOI of a fully verified match to an entry that lacks one."""
    fields = entry["fields"]
    doi = result.get("accepted_doi")
    if fields.get("doi") or result.get("status") != "metadata_verified" or not doi:
        return None
    return {"kind": "add_doi", "rule": "D1", "key": entry["key"], "fingerprint": entry["fingerprint"],
            "changes": {"doi": {"before": None, "after": normalize_doi(doi)}},
            "accepted_source": result.get("accepted_source")}
