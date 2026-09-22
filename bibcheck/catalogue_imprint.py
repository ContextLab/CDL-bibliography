"""Resolve a historical chapter imprint through an explicitly bound book edition.

No general publisher alias is created. Edition bindings require documentary
review; the publisher value itself is parsed from a pinned LOC MARC record.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from verification import compare_record, normalize_doi, normalize_title

EDITIONS = json.loads((Path(__file__).parent / "book_editions.json").read_text())
M = "{http://www.loc.gov/MARC21/slim}"


def edition_for(primary):
    doi = primary.get("doi", "")
    return next((e for e in EDITIONS if re.fullmatch(re.escape(e["book_doi"]) + r"_[1-9]\d*", doi)), None)


def catalogue_publisher(xml, edition):
    if (not isinstance(xml, str) or len(xml) > 100_000
            or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I)
            or hashlib.sha256(xml.encode()).hexdigest() != edition["document_sha256"]):
        raise ValueError("Catalogue document is not the reviewed edition record")
    root = ET.fromstring(xml)
    if root.tag != M + "record":
        raise ValueError("Expected one MARC record")
    def controls(tag):
        return [n.text or "" for n in root.findall(M + "controlfield") if n.get("tag") == tag]
    def fields(tag):
        return [n for n in root.findall(M + "datafield") if n.get("tag") == tag]
    def values(node, code):
        return [(n.text or "").strip() for n in node.findall(M + "subfield") if n.get("code") == code]
    def one(tag, code):
        nodes = fields(tag)
        if len(nodes) != 1 or len(values(nodes[0], code)) != 1:
            raise ValueError("Missing or ambiguous catalogue field " + tag + code)
        return values(nodes[0], code)[0]
    if controls("001") != [edition["record_id"]] or one("010", "a") != edition["lccn"]:
        raise ValueError("Catalogue identity differs")
    leader = root.findtext(M + "leader", "")
    dates = controls("008")
    if (len(leader) < 8 or leader[6:8] != "am" or len(dates) != 1
            or len(dates[0]) < 15 or dates[0][6] != "s"
            or dates[0][7:11] != str(edition["year"])):
        raise ValueError("Catalogue is not a single dated printed monograph")
    title = one("245", "a").rstrip(" /:")
    if fields("250") or values(fields("245")[0], "b"):
        raise ValueError("Additional edition or subtitle needs its own binding")
    if normalize_title(title) != normalize_title(edition["booktitle"]):
        raise ValueError("Catalogue book title differs")
    if one("260", "c") not in {str(edition["year"]) + ".", "c" + str(edition["year"]) + "."} or fields("264"):
        raise ValueError("Imprint date or publication statement is ambiguous")
    publisher = one("260", "b").rstrip(" ,;")
    # This MARC phrase expressly identifies the publishing body. It is not a
    # distributor statement, and no generic splitting on the word 'by' occurs.
    cooperation = re.fullmatch(r"Published in cooperation with ([^;]+) by ([^;]+)", publisher)
    if cooperation:
        publisher = cooperation[2]
    if not publisher or re.search(r"distribut|;|\[|\]", publisher, re.I):
        raise ValueError("Publisher/distributor roles remain ambiguous")
    return publisher


def assess_catalogue_imprint(fields, primary, response=None):
    evidence, issues, record = {}, [], {}
    edition = edition_for(primary)
    response = deepcopy(edition) if response is None and edition else response or {}
    try:
        if not edition or response.get("document_sha256") != edition["document_sha256"] or response.get("catalogue_url") != edition["catalogue_url"]:
            raise ValueError("No reviewed binding for this exact book edition")
        source = primary["record"]
        if (fields.get("ENTRYTYPE") != "incollection" or source.get("type") != "book-chapter"
                or normalize_doi(source["DOI"]) != primary["doi"]
                or set(source.get("ISBN", [])) != set(edition["registry_isbns"])
                or source.get("publisher") != edition["registry_publisher"]
                or source.get("container-title") != [edition["booktitle"]]
                or fields.get("year") != str(edition["year"])):
            raise ValueError("Chapter registry does not identify the reviewed edition")
        _, old_issues = compare_record(fields, source)
        if old_issues != ["publisher: missing evidence or mismatch"]:
            raise ValueError("Registry has blockers other than the historical imprint")
        publisher = catalogue_publisher(response["raw_marcxml"], edition)
        record = dict(deepcopy(source), publisher=publisher)
        evidence, issues = compare_record(fields, record)
        if not issues:
            evidence["publisher"].update(source_name="LOC MARC publication statement", registry_publisher=source["publisher"])
    except (ValueError, KeyError, TypeError, AttributeError, ET.ParseError) as exc:
        issues = ["Catalogue imprint unresolved: " + str(exc)]
    return {"source": "catalogue-imprint", "doi": primary.get("doi"),
            "url": response.get("catalogue_url"), "catalogue_url": response.get("catalogue_url"),
            "retrieved_at": response.get("retrieved_at"), "document_sha256": response.get("document_sha256"),
            "raw_marcxml": response.get("raw_marcxml"),
            "edition_binding": edition["book_doi"] if edition else None,
            "record": record, "evidence": evidence, "issues": issues}
