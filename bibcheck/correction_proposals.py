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
    return format_title(re.sub(r"([&%#_])", r"\\\1", source))


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
                value = format_journal_name(venues[0])
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
                values["journal"] = format_journal_name(venues[0])
            if include_identity_fields:
                titles = primary["evidence"]["title"]["source"]
                if len(titles) == 1 and "title" not in matched:
                    values["title"] = source_title(titles[0], fields.get("title", ""))
                if "author" not in matched:
                    from helpers import reformat_author
                    people = record.get("author", [])
                    if people and all(p.get("given") and p.get("family") and not p.get("name") for p in people):
                        values["author"] = reformat_author(" and ".join(p["family"] + ", " + (p["suffix"] + ", " if p.get("suffix") else "") + p["given"] for p in people))
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
