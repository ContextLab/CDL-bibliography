"""Build the frozen proposals for the stage 2B-ii batches (2026-09-27) from the current cdl.bib.

User decisions (verification/resolution-plan-2026-09-22/README.md):

  suffix-strip  No name suffixes: Jr/Sr/II/III/IV are removed from every author/editor
                name ('Roediger, III, H L' -> 'H L Roediger').
  initials      Initials everywhere: full given names become initials (one per given
                name, hyphenated initials kept), surnames, particles and braced groups
                unchanged. A name whose surname may be compound/unbraced or whose
                given/family split is ambiguous is held (initials-held.json). Also the
                PosnEtal87 byline typo 'adn' -> 'and' (Crossref 10.1016/0028-3932(87)90049-2
                lists four authors: Posner, Walker, Friedrich, Rafal).
  formats       Issue ranges 'N-M' -> 'N--M' in `number`; proceedings booktitles omit the
                year; bare editions in house form 'N\\textsuperscript{..}'; no `pages` on @book.
  adddoi002     Built by build_adddoi.py (needs the verification cache).

Every proposal carries the entry fingerprint; helpers.check_bib must accept the staged
entry, and the cite key (ID rule) must not change: a proposal that would rename a key is
held and reported instead.

    .venv/bin/python verification/apply-2026-09-27/build.py BATCH
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "bibcheck"))
sys.path.insert(0, str(HERE))
from verification import load_entries  # noqa: E402
import helpers  # noqa: E402
from names import SUFFIX_TOKEN, split_names, strip_suffix, to_initials, tokens  # noqa: E402

_spec = importlib.util.spec_from_file_location("apply0923", ROOT / "verification/apply-2026-09-23/apply.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
os.chdir(ROOT)

NAME_FIELDS = ("author", "editor")
ORDINAL = {1: "st", 2: "nd", 3: "rd"}
YEAR_WORD = re.compile(r"(?<![\d{])(?:18|19|20)\d\d(?![\d}])")


def ordinal(n):
    n = int(n)
    return f"{n}\\textsuperscript{{{'th' if 11 <= n % 100 <= 13 else ORDINAL.get(n % 10, 'th')}}}"


def has_suffix(name):
    return "," in name or any(SUFFIX_TOKEN.match(t) for t in tokens(name))


def propose_suffix(entries):
    rows, held = [], {}
    for key, entry in entries.items():
        changes = {}
        for field in NAME_FIELDS:
            value = entry["fields"].get(field)
            if not value:
                continue
            names = split_names(value)
            new = [strip_suffix(n) if has_suffix(n) else n for n in names]
            if new != names:
                changes[field] = {"before": value, "after": " and ".join(new)}
        if changes:
            rows.append({"key": key, "fingerprint": entry["fingerprint"], "kind": "strip_name_suffix",
                         "rule": "user-2026-09-24/25 no name suffixes", "changes": changes})
    return rows, held


def propose_initials(entries):
    rows, held_names = [], []
    for key, entry in entries.items():
        changes, notes = {}, {}
        for field in NAME_FIELDS:
            value = entry["fields"].get(field)
            if not value:
                continue
            if key == "PosnEtal87" and field == "author" and " adn " in value:
                fixed = value.replace(" adn ", " and ")
                notes["author_typo"] = ("'adn' -> 'and': Crossref 10.1016/0028-3932(87)90049-2 lists four authors "
                                        "(Posner, Walker, Friedrich, Rafal)")
            else:
                fixed = value
            names = split_names(fixed)
            new = []
            for name in names:
                converted, why = to_initials(name)
                if why:
                    held_names.append({"key": key, "field": field, "name": name, "reason": why})
                    new.append(name)
                    continue
                if helpers.last_name(converted) != helpers.last_name(name):
                    held_names.append({"key": key, "field": field, "name": name,
                                       "reason": f"ID-rule surname would change ({helpers.last_name(name)} -> "
                                                 f"{helpers.last_name(converted)})"})
                    new.append(name)
                    continue
                if helpers.reformat_author(converted) != converted:
                    held_names.append({"key": key, "field": field, "name": name,
                                       "reason": f"house formatter rewrites '{converted}'"})
                    new.append(name)
                    continue
                new.append(converted)
            after = " and ".join(new)
            if after != value:
                changes[field] = {"before": value, "after": after}
        if changes:
            rows.append({"key": key, "fingerprint": entry["fingerprint"], "kind": "given_names_to_initials",
                         "rule": "user-2026-09-24/25 initials everywhere", "changes": changes,
                         **({"form_notes": notes} if notes else {})})
    return rows, held_names


def propose_formats(entries):
    rows, held = [], {}
    for key, entry in entries.items():
        fields, changes, notes = entry["fields"], {}, {}
        number = fields.get("number")
        match = re.fullmatch(r"(\d+)-(\d+)", number or "")
        if match:
            a, b = int(match[1]), int(match[2])
            if fields["ENTRYTYPE"] == "techreport":
                held[key] = f"number '{number}' of a @techreport is a report number, not an issue range"
            elif b <= a or a >= 50:
                held[key] = (f"number '{number}' looks like a page range (or report code), not an issue range; "
                             "needs a source-backed correction, not a form change")
            else:
                changes["number"] = {"before": number, "after": f"{a}--{b}"}
                notes["number"] = "issue range in house form N--M (user 2026-09-25)"
        elif number and re.fullmatch(r"\S+-\S+", number) and "--" not in number:
            held[key] = f"number '{number}' is not a digit range (identifier/label), left as is"
        booktitle = fields.get("booktitle")
        if booktitle and fields["ENTRYTYPE"] in ("inproceedings", "proceedings") and YEAR_WORD.search(booktitle):
            new = YEAR_WORD.sub("", booktitle)
            new = re.sub(r"\s+([,:;])", r"\1", " ".join(new.split()))
            new = re.sub(r"^[,:;]\s*", "", new).strip()
            new = re.sub(r"\bthe the\b", "the", new)
            changes["booktitle"] = {"before": booktitle, "after": new}
            notes["booktitle"] = "proceedings name without its year (user 2026-09-25; year is in `year`)"
        edition = fields.get("edition")
        if edition and re.fullmatch(r"\d+", edition):
            changes["edition"] = {"before": edition, "after": ordinal(edition)}
            notes["edition"] = "edition in house form N\\textsuperscript{..} (user 2026-09-25)"
        if fields["ENTRYTYPE"] == "book" and "pages" in fields:
            changes["pages"] = {"before": fields["pages"], "after": None}
            notes["pages"] = "@book has no pages (user 2026-09-25)"
        if changes:
            rows.append({"key": key, "fingerprint": entry["fingerprint"], "kind": "house_forms",
                         "rule": "user-2026-09-25 formats", "changes": changes, "form_notes": notes})
    return rows, held


def check_rows(entries, rows):
    """Apply every proposal to a copy; keep those check_bib accepts with the same key."""
    text = Path("cdl.bib").read_text()
    kept, held = [], {}
    for row in rows:
        raw = entries[row["key"]]["raw"]
        try:
            new = base.apply_change_all(raw, row)
        except ValueError as exc:
            held[row["key"]] = f"edit not applicable: {exc}"
            continue
        row["_new"] = new
        kept.append(row)
    modified = text
    for row in kept:
        modified = modified.replace(entries[row["key"]]["raw"], row.pop("_new"), 1)
    with tempfile.NamedTemporaryFile("w", suffix=".bib", dir=ROOT / ".bibcheck", delete=False) as handle:
        handle.write(modified)
    try:
        errors, _ = helpers.check_bib(handle.name, verbose=False)
    finally:
        os.unlink(handle.name)
    for key, fix in errors.items():
        held[key] = f"check_bib: {fix}"
    if errors:
        print("check_bib errors (held):", json.dumps(errors, ensure_ascii=False)[:2000])
    return [r for r in kept if r["key"] not in errors], held


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", choices=("suffix-strip", "initials", "formats"))
    args = parser.parse_args()
    entries = load_entries("cdl.bib")
    extra = {}
    if args.batch == "suffix-strip":
        rows, held = propose_suffix(entries)
    elif args.batch == "initials":
        rows, held_names = propose_initials(entries)
        held = {}
        extra["held_names"] = len(held_names)
    else:
        rows, held = propose_formats(entries)
    rows, check_held = check_rows(entries, rows)
    held.update(check_held)
    out = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "batch": args.batch, "count": len(rows),
           **extra, "skipped": held, "proposals": rows}
    (HERE / f"{args.batch}-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    if args.batch == "initials":
        by_entry = {r["key"] for r in rows}
        for h in held_names:
            h["entry_otherwise_converted"] = h["key"] in by_entry
        (HERE / "initials-held.json").write_text(json.dumps(
            {"generated": out["generated"], "count": len(held_names),
             "entries": len({h["key"] for h in held_names}), "names": held_names},
            indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in ("proposals", "skipped")}),
          "skipped:", json.dumps(held, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()
