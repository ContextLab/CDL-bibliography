"""What the core returned, laid out as text. Nothing here decides anything: every status,
issue and message is shown as the core gave it."""
import json
from datetime import datetime, timezone

from rich.text import Text

from .widgets import Writer, mark


def _value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _people(source):
    """A source's author list as names (a Crossref person is {"given", "family"})."""
    names = []
    for item in source:
        if isinstance(item, dict) and ("family" in item or "given" in item or "name" in item):
            names.append(" ".join(part for part in (item.get("given"), item.get("family") or item.get("name")) if part))
        else:
            names.append(_value(item))
    return "; ".join(names)


def status_text(status, colour):
    glyph, role = mark(status)
    return Text(f"{glyph} {status}", colour(role))


# --- one entry ---------------------------------------------------------------------------------

def issues(detail, colour):
    out = Writer(colour)
    out.part("Status: ").text.append_text(status_text(detail.status, colour))
    out.line()
    out.head("Issues")
    for line in detail.issues or ["(none)"]:
        out.line(f"  {line}", "warning" if detail.issues else "muted")
    out.head("Advisories")
    for line in detail.advisories or ["(none)"]:
        out.line(f"  {line}", None if detail.advisories else "muted")
    out.head("House format")
    if detail.format is None:
        out.line("  (not computed here; open the entry in the Library view)", "muted")
    for finding in detail.format or ([] if detail.format is None else [None]):
        if finding is None:
            out.line("  (no findings)", "muted")
            continue
        out.line(f"  {finding.field or 'entry'}: {finding.message}", "warning")
        if finding.field is not None:
            out.line(f"      now:       {finding.current}")
            out.line(f"      formatter: {finding.corrected if finding.corrected is not None else '(removes the field)'}")
    return out.text


def when(moment):
    """A moment as the interface writes it: "2026-10-05 04:29 UTC". ``moment`` is a datetime or
    the ISO text of one; text that is not a date is given back as it is."""
    if isinstance(moment, str):
        try:
            moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
        except ValueError:
            return moment
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def _candidate(out, title, candidate):
    out.head(title)
    for name in ("source", "doi", "url"):
        if candidate.get(name):
            out.line(f"  {name}: {candidate[name]}")
    if candidate.get("retrieved_at"):
        out.line(f"  retrieved: {when(candidate['retrieved_at'])}")
    evidence = candidate.get("evidence") or {}
    if evidence:
        out.line("  each field: = the library and the source agree, ≠ they differ", "muted")
    for name, found in evidence.items():
        if not isinstance(found, dict):
            out.line(f"  {name}: {_value(found)}")
            continue
        match = found.get("match")
        role = "success" if match is True else "error" if match is False else "muted"
        source = found.get("source")
        shown = _people(source) if isinstance(source, list) else _value(source)
        out.line(f"  {'=' if match is True else '≠' if match is False else '·'} {name}", role, bold=True)
        out.line(f"      library: {_value(found.get('local'))}")
        out.line(f"      source:  {shown}")
        if found.get("detail"):
            out.line(f"      {found['detail']}", "muted")
    for line in candidate.get("issues") or []:
        out.line(f"  issue: {line}", "warning")
    for line in candidate.get("advisories") or []:
        out.line(f"  advisory: {line}")


def _record(out, record, indent="  "):
    for name, value in record.items():
        if isinstance(value, dict) and value and all(isinstance(item, dict) for item in value.values()):
            out.line(f"{indent}{name}:")
            for field, found in value.items():
                page = f" (p. {found['page']})" if found.get("page") is not None else ""
                out.line(f"{indent}  {field}: {found.get('value', '')}{page}")
                if found.get("quote"):
                    out.line(f"{indent}      “{found['quote']}”", "muted")
                for other, more in found.items():
                    if other not in ("value", "page", "quote"):
                        out.line(f"{indent}      {other}: {_value(more)}", "muted")
        elif isinstance(value, dict):
            out.line(f"{indent}{name}:")
            _record(out, value, indent + "  ")
        elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            out.line(f"{indent}{name}:")
            for item in value:
                out.line(f"{indent}  - {item}")
        else:
            out.line(f"{indent}{name}: {_value(value)}")


def evidence(detail, colour):
    out = Writer(colour)
    out.part("Status: ").text.append_text(status_text(detail.status, colour))
    out.line()
    if detail.closest is not None:
        _candidate(out, "Closest source (field by field)", detail.closest)
    others = [c for c in detail.candidates if c is not detail.closest and c != detail.closest]
    for number, candidate in enumerate(others[:3], 1):
        _candidate(out, f"Source record {number}" if detail.closest is not None or len(others) > 1 else "Source record",
                   candidate)
    if len(others) > 3:
        out.line(f"  ... and {len(others) - 3} more source records", "muted")
    if detail.closest is None and not detail.candidates:
        out.head("Source records")
        out.line("  (none stored for this entry text)", "muted")
    out.head("Lookups made")
    for attempt in detail.attempts or [None]:
        out.line("  (none)" if attempt is None else
                 "  " + "  ".join(f"{name}={_value(value)}" for name, value in attempt.items()),
                 "muted" if attempt is None else None)
    if detail.external_evidence:
        out.head("External evidence (PDF or model reading; not an approval)")
        _record(out, detail.external_evidence)
    out.head("Human review")
    if detail.human_review:
        _record(out, detail.human_review)
    else:
        out.line("  (no approval recorded for this entry text)", "muted")
    if detail.revoked_approval:
        out.head("Revoked approval")
        _record(out, detail.revoked_approval)
    return out.text


# --- an edit's preview -------------------------------------------------------------------------

def diff(text, colour):
    out = Text()
    for line in text.splitlines():
        role = ("success" if line.startswith("+") and not line.startswith("+++") else
                "error" if line.startswith("-") and not line.startswith("---") else
                "muted" if line.startswith(("@@", "+++", "---")) else None)
        out.append(line[:1] + line[1:].expandtabs(4) + "\n", colour(role) if role else None)
    return out


def preview(found, colour):
    out = Writer(colour)
    if found.problems:
        out.head("Cannot be saved as it is")
        for line in found.problems:
            out.line(f"  {line}", "error")
    out.head("Changes")
    if not found.changed:
        out.line("  (the text is what the file already holds)", "muted")
    out.text.append_text(diff(found.diff, colour))
    if found.key_change is not None:
        change = found.key_change
        out.head("Key")
        out.line(f"  {change.old} -> {change.new} ({change.kind})", "error" if change.kind == "collision" else "warning")
    if found.duplicate_of:
        out.head("Duplicate")
        out.line(f"  The same work is already in the library as {found.duplicate_of}", "warning")
    out.head("Status")
    if found.status_now is not None:
        out.part("  now: ").text.append_text(status_text(found.status_now, colour))
        out.line()
    if found.status is not None:
        out.part("  after saving: ").text.append_text(status_text(found.status, colour))
        out.line()
    if found.invalidates:
        out.line(f"  Saving loses the status {found.invalidates}: the edited text has not been verified or approved.",
                 "warning")
    if found.affected:
        out.head("Other entries whose status changes (they inherit from this one)")
        for other in found.affected:
            out.line(f"  {other.key}: {other.status_now} -> {other.status}", "warning")
    out.head("House format")
    for finding in found.format or [None]:
        if finding is None:
            out.line("  (no findings)", "muted")
            continue
        out.line(f"  {finding.field or 'entry'}: {finding.message}", "warning")
        if finding.field is not None:
            out.line(f"      now:       {finding.current}")
            out.line(f"      formatter: {finding.corrected if finding.corrected is not None else '(removes the field)'}")
    if found.format and found.corrected_raw:
        out.line("  ctrl+r puts the formatter's text into the editor", "muted")
    return out.text


# --- a proposal --------------------------------------------------------------------------------

def changes(item):
    """The rows of a proposal's table of changes: (field, typed, proposed, source, kind)."""
    return [(change.field, "" if change.typed is None else str(change.typed),
             "" if change.proposed is None else str(change.proposed), change.source, change.kind)
            for change in item.changes]


def proposal(item, colour):
    """The findings of a proposal other than its changes, in the words the command line prints."""
    out = Writer(colour)
    if item.unfilled:
        out.head("Unfilled")
        for missing in item.unfilled:
            reason = str(missing.reason)         # the core's reason may already begin with the field's name
            said = reason if reason.startswith(f"{missing.field}:") else f"{missing.field}: {reason}"
            out.line(f"  {said}", "warning")
            for source, value in (missing.source_values or {}).items():
                out.line(f"      {source}: {value}", "muted")
    consequences = [f"Rename: {old} -> {new}" for old, new in item.renames.items()]
    if item.key_typed and item.key_proposed != item.key_typed:
        consequences.append(f"Key: {item.key_typed} -> {item.key_proposed}")
    if item.duplicate_of:
        consequences.append(f"Duplicate: {item.duplicate_of}")
    if item.unsupported:
        consequences.append(f"Unsupported: {item.unsupported}")
    if consequences:
        out.head("Key, renames and duplicates")
        for line in consequences:
            out.line(f"  {line}", "warning")
    out.head("Verification (the first check of the proposed text; not an approval)")
    out.line(f"  Verification: {item.status or 'not checked'}")
    if item.notes:
        out.head("Notes")
        for line in item.notes:
            out.line(f"  {line}")
    if item.issues:
        out.head("Issues")
        for line in item.issues:
            out.line(f"  {line}", "warning")
    return out.text


def lead(candidate):
    return (f"{candidate.get('authors', '')} {candidate.get('year', '')}: {candidate.get('title', '')} "
            f"{candidate.get('doi') or candidate.get('arxiv') or ''}").strip()


# --- what was read from a PDF --------------------------------------------------------------------

def pdf_text(pdf, colour, result=None, name_only=False):
    """What was read from a PDF, as text: its identifiers with the page and line each was read
    from, the title read, the outcome of a lookup, and the text of the first page."""
    out = Writer(colour)
    out.line(f"Read from {pdf.path.name}" if name_only else str(pdf.path), bold=True)
    if pdf.problem:
        out.line(f"problem: {pdf.problem}" + (f" ({pdf.detail})" if pdf.detail else ""), "warning")
    if pdf.ocr:
        out.line("The text is OCR output; it can misread characters.", "warning")
    out.head("Identifiers found")
    for found in pdf.identifiers or [None]:
        if found is None:
            out.line("  (none)", "muted")
            continue
        where = "the PDF's metadata" if found.page is None else f"page {found.page}"
        out.line(f"  {found.kind}: {found.value} ({where})")
        out.line(f"      “{found.quote}”", "muted")
    out.head("Title read")
    out.line(f"  {pdf.title_guess}" + (f" ({pdf.title_source})" if pdf.title_source else "") if pdf.title_guess
             else "  (none)", None if pdf.title_guess else "muted")
    if result is not None:
        out.head("Lookup")
        out.line(f"  {result.message}")
        for line in result.tried:
            out.line(f"    {line}", "muted")
    out.head("Text of the first page")
    out.line(pdf.first_page_text.strip() or "(no text)")
    return out.text
