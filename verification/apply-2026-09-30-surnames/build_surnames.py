"""Write verification/2026-09-30-user-review/SURNAMES.md and surnames.json from the scan.

    python verification/apply-2026-09-30-surnames/build_surnames.py [SNAPSHOT]

SNAPSHOT defaults to verification/baseline.jsonl.gz (run after the batch has exported it).
One row (JSON object) per surname disagreement; order-only differences are listed in
SURNAMES.md but asked about nowhere, since no surname is spelled differently.
"""
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "verification/2026-09-30-user-review"
_spec = importlib.util.spec_from_file_location("surname_scan", HERE / "scan.py")
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)

ORDER = ["spelling", "transliteration", "name-split", "punctuation", "garbled-source"]
TITLES = {
    "spelling": "Spelling differences",
    "transliteration": "Written-out umlauts",
    "name-split": "The source splits the name differently",
    "punctuation": "Punctuation or spacing only",
    "garbled-source": "The source's surname has an unreadable character",
}
ABOUT = {
    "spelling": "The source spells the surname with different letters.",
    "transliteration": "The source writes an umlaut out (ö as oe).",
    "name-split": "One surname contains the other: a particle or second surname is missing, or the "
                  "source's family field also holds a given name or suffix, or holds the given name "
                  "instead (given and family swapped).",
    "punctuation": "Only a period, apostrophe form, space or stray mark differs "
                   "(your answer to CONFIRM.md question 6 called a period after an initial a formatting "
                   "difference).",
    "garbled-source": "The source's surname has a character it could not encode (�, ?, an HTML entity, "
                      "a loose accent), so it does not state a spelling for that letter.",
}
RULE_QUESTION = {
    "transliteration": "Rule question: keep the cited umlaut when a source writes it out (ö as oe)?",
    "name-split": "Rule question: when a source's family field differs only by a particle, a second "
                  "surname, a given name or a suffix, keep the cited form unless a row below says otherwise?",
    "punctuation": "Rule question: treat a period, apostrophe form or space in a surname as formatting, "
                   "and keep the cited form?",
    "garbled-source": "Rule question: when a source's surname has an unreadable character, keep the cited "
                      "spelling?",
}
# The rows the report calls most consequential: every source saved for the work disagrees
# with the entry (three sources for the last four), or the entry lost its approval today.
MOST = [("MeyeEtal88", 4), ("LuriEtal20", 6), ("KragEtal19", 9), ("NybeEtal03", 4), ("HarrEtal20", 17)]
NOTES = {
    ("LuriEtal20", 6): "The decision log's \"Replacements approved (user, 2026-09-25)\" bullet records "
                       "'LuriEtal20 keeps \"Keilholz\"'.",
    ("MeyeEtal88", 4): "PubMed 3375399 prints \"Kounios\"; the entry lost its approval today (it rested on "
                       "the retired registry-surname-typo rule).",
}


def question(row):
    e, s = row["entry_spelling"], row["source_spelling"]
    if row["class"] == "garbled-source":
        return f"Keep '{e}'? (the source's '{s}' has an unreadable character)"
    return f"Keep '{e}' or change to '{s}'?"


def source_text(row):
    parts = []
    for label, url, quote in zip(row["sources"], row["urls"], row["source_quotes"]):
        parts.append(f"{url} ({label}: {quote})")
    return "; ".join(parts)


def printed_quote(row):
    if not row["quotes"]:
        return ""
    q = row["quotes"][0]
    return f"\"{q['quote']}\" ({q['url']})"


def md_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def main():
    snapshot = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "verification/baseline.jsonl.gz"
    rows, compared = scan.scan(snapshot)
    # A research quote that lacks the cited surname is kept with that position's source row.
    extra = defaultdict(list)
    for r in rows:
        if r["class"] == "not-in-quote":
            extra[(r["key"], r["position"])] += r["quotes"]
    main_rows = [r for r in rows if r["class"] not in ("not-in-quote", "order")]
    orphans = [r for r in rows if r["class"] == "not-in-quote"
               and not any((m["key"], m["position"]) == (r["key"], r["position"]) for m in main_rows)]
    assert not orphans, [(r["key"], r["position"]) for r in orphans]  # every such case has a source row
    order_keys = sorted({r["key"] for r in rows if r["class"] == "order"})
    main_rows.sort(key=lambda r: (ORDER.index(r["class"]), r["key"], r["position"], r["source_spelling"]))
    out = [{"key": r["key"], "position": r["position"], "entry_spelling": r["entry_spelling"],
            "source_spelling": r["source_spelling"], "source": source_text(r), "question": question(r),
            "printed_quote": printed_quote(r)} for r in main_rows]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "surnames.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")

    by_class = Counter(r["class"] for r in main_rows)
    status = {r["key"]: r["status"] for r in rows}
    lines = [
        "# Surname mismatches for your decision (2026-09-30)",
        "",
        "Your answer to [CONFIRM.md](../2026-09-29-user-review/CONFIRM.md) question 5 (2026-09-30): \"one source "
        "is sufficient; manual entry is the weakest part. notify user if mismatch is found and ask how they want "
        "to resolve it\".",
        "",
        "One source record that agrees with a cited surname is now enough to verify it. When a source spells a "
        "cited surname differently, nothing is changed and nothing is settled for you. Each row below is one "
        "such mismatch: the entry's surname, the source's, where the source says it, and a question. Where the "
        "research evidence quotes the printed work (not a registry record) with either spelling, the quote is "
        "given; the printed work wins when in doubt. No surname in `cdl.bib` was changed. The same rows are in "
        "[surnames.json](surnames.json) for the review page.",
        "",
        f"How the list was made: every author surname of the {sum(compared.values())} entries that have an "
        "author list and a saved result was compared with the surnames in the source records saved for the entry's DOI (Crossref, "
        "PubMed, PMC full text, the publisher's page) and in the record the entry was verified on, after the "
        "checker's typography normalization (accents, braces, case). Script: "
        "[scan.py](../apply-2026-09-30-surnames/scan.py) (run by "
        "[build_surnames.py](../apply-2026-09-30-surnames/build_surnames.py)) on the baseline exported by "
        "[apply-2026-09-30-surnames](../apply-2026-09-30-surnames/README.md).",
        "",
        f"**{len(out)} mismatches in {len({r['key'] for r in main_rows})} entries**: "
        + ", ".join(f"{by_class[c]} {TITLES[c].lower()}" for c in ORDER if by_class[c]) + ". "
        f"{sum(1 for k in {r['key'] for r in main_rows} if status[k] == 'needs_review')} of these entries are "
        "`needs_review`; the others stay verified on the source that agrees with them (one source is "
        "sufficient) until you answer.",
        "",
        "## Entries that lost their approval today",
        "",
        "Eight entries had been verified only because a rule of Claude's (registry-surname-typo, 2026-09-25) "
        "let the DOI-linked PubMed record and other cdl.bib entries overrule Crossref's spelling. Under your "
        "rule they are `needs_review` until you answer their rows: MeyeEtal88 (Kounios / Kounois), "
        "BragEtal99 (Buzsáki / Buzs�ki), RobeEtal99 (Georges-François / Georges-Fran�ois), NoldEtal98 "
        "(D'Esposito / DʼEsposito), and SchaEtal11, StJaEtal08, StJaEtal12, StJaScha13 (St Jacques / "
        "St. Jacques). In each, PubMed prints the cited spelling.",
        "",
        "## Most consequential",
        "",
        "| Key | Author | Entry | Source | Question | Note |",
        "|-|-|-|-|-|-|",
    ]
    index = {(r["key"], r["position"]): r for r in main_rows}
    for key, pos in MOST:
        r = index[(key, pos)]
        note = NOTES.get((key, pos), f"{len(r['sources'])} sources agree: {', '.join(r['sources'])}.")
        lines.append(f"| {key} | {pos} | {md_cell(r['entry_spelling'])} | {md_cell(r['source_spelling'])} | "
                     f"{md_cell(question(r))} | {md_cell(note)} |")
    for c in ORDER:
        group = [r for r in main_rows if r["class"] == c]
        if not group:
            continue
        lines += ["", f"## {TITLES[c]} ({len(group)})", "", ABOUT[c]]
        if c in RULE_QUESTION:
            lines += ["", f"**{RULE_QUESTION[c]}** A yes answers every row in this section except any you "
                      "mark otherwise."]
        lines += ["", "| Key | Author | Entry | Source spelling | Source | Status | Question | Printed quote |",
                  "|-|-|-|-|-|-|-|-|"]
        for r in group:
            pq = printed_quote(r)
            more = extra.get((r["key"], r["position"]))
            if more and not pq:
                pq = "research quote without the cited spelling: " + "; ".join(
                    f"\"{q['quote']}\" ({q['url']})" for q in more)
            lines.append(f"| {r['key']} | {r['position']} | {md_cell(r['entry_spelling'])} | "
                         f"{md_cell(r['source_spelling'])} | {md_cell(source_text(r))} | {status[r['key']]} | "
                         f"{md_cell(question(r))} | {md_cell(pq)} |")
    lines += ["", f"## Author order only ({len(order_keys)} entries, not asked)", "",
              "In these entries a source prints the same surnames in another order (or with a given name at "
              "another position); no surname is spelled differently: " + ", ".join(order_keys) + ".", ""]
    (OUT / "SURNAMES.md").write_text("\n".join(lines))
    print(json.dumps({"rows": len(out), "entries": len({r['key'] for r in main_rows}), "by_class": dict(by_class),
                      "order_only_entries": len(order_keys)}))


if __name__ == "__main__":
    main()
