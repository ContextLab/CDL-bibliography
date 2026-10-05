"""What the core returned, laid out as text. Nothing here decides anything: every status,
issue and message is shown as the core gave it."""
import json
import struct
import zlib

from rich.color import Color
from rich.style import Style
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


def _candidate(out, title, candidate):
    out.head(title)
    for name in ("source", "doi", "url", "retrieved_at"):
        if candidate.get(name):
            out.line(f"  {name}: {candidate[name]}")
    evidence = candidate.get("evidence") or {}
    if evidence:
        out.line("  field       in the library  |  in the source", "muted")
    for name, found in evidence.items():
        if not isinstance(found, dict):
            out.line(f"  {name}: {_value(found)}")
            continue
        match = found.get("match")
        role = "success" if match is True else "error" if match is False else "muted"
        source = found.get("source")
        shown = _people(source) if isinstance(source, list) else _value(source)
        out.part(f"  {'=' if match is True else '≠' if match is False else '·'} {name:<9} ", role, bold=True)
        out.line(f"{_value(found.get('local'))}  |  {shown}")
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

def proposal(item, colour):
    """The findings of a proposal, in the words the command line prints them."""
    out = Writer(colour)
    out.line(f"Entry: {item.key_typed or item.key_proposed or '(new)'}", bold=True)
    out.head("Changes (each with its source)")
    for change in item.changes or [None]:
        if change is None:
            out.line("  (none)", "muted")
            continue
        role = {"question": "warning", "dropped": "error", "kept": "muted"}.get(change.kind)
        out.line(f"  {change.field}: {change.typed} -> {change.proposed} (source: {change.source}) [{change.kind}]", role)
    if item.unfilled:
        out.head("Unfilled")
        for missing in item.unfilled:
            out.line(f"  Unfilled {missing.field}: {missing.reason}", "warning")
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


# --- a PDF's first page ------------------------------------------------------------------------

def _decode_png(data):
    """(width, height, rows of (r, g, b)) of an 8-bit, non-interlaced PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    position, chunks, header = 8, [], None
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            chunks.append(body)
    width, height, depth, colour_type, _, _, interlace = header
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour_type)
    if depth != 8 or channels is None or interlace:
        raise ValueError("unsupported PNG layout")
    raw, stride = zlib.decompress(b"".join(chunks)), width * channels
    rows, previous = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
        rows.append(line)
        previous = line

    def pixel(line, x):
        at = x * channels
        if channels in (1, 2):
            return (line[at],) * 3
        return line[at], line[at + 1], line[at + 2]

    return width, height, [[pixel(line, x) for x in range(width)] for line in rows]


def half_blocks(png, columns):
    """The image as text, ``columns`` cells wide: each cell is an upper half block whose
    foreground is the pixel above and whose background is the pixel below. The picture is
    averaged down to ``columns`` pixels across."""
    width, height, pixels = _decode_png(png)
    scale = max(1, width // columns)
    wide, high = width // scale, height // scale

    def averaged(x, y):
        total, count = [0, 0, 0], 0
        for yy in range(y * scale, min((y + 1) * scale, height)):
            row = pixels[yy]
            for xx in range(x * scale, min((x + 1) * scale, width)):
                r, g, b = row[xx]
                total[0] += r; total[1] += g; total[2] += b
                count += 1
        return tuple(value // max(count, 1) for value in total)

    out = Text(no_wrap=True)
    for y in range(0, high - 1, 2):
        for x in range(wide):
            top, bottom = averaged(x, y), averaged(x, y + 1)
            out.append("▀", Style(color=Color.from_rgb(*top), bgcolor=Color.from_rgb(*bottom)))
        out.append("\n")
    return out
