"""Build the grouped review page for one research wave from its post-checked merged.json."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
wave = Path(sys.argv[1])
rows = json.loads((wave / "merged.json").read_text())
GROUPS = [
 ("clean_numbers_doi", "Numbers and DOIs", "Volume, issue, pages, year or DOI added/corrected; every DOI resolves.", "Apply."),
 ("clean_authors", "Author lists", "Missing authors, initials or spellings (house format).", "Apply."),
 ("clean_title", "Titles", "Typos, missing words, subtitles.", "Apply."),
 ("clean_book", "Book details", "Editors, publisher, place, edition of the cited edition.", "Apply."),
 ("clean_venue_type", "Journal, proceedings or entry type", "Wrong venue, proceedings title or entry type.", "Apply."),
 ("no_change", "Already correct", "Research confirmed the entry; nothing to change.", "Mark verified."),
 ("duplicate", "Duplicates of existing entries", "Same work already in cdl.bib under another key.", "Merge into the existing entry; log the removed key."),
 ("key_collision", "Key collisions", "The corrected key belongs to a different work.", "Next free suffix; log both keys."),
 ("key_rename", "Key renames", "Year, first author or author count changed.", "Rename; log."),
 ("patent_filing_year", "Patents dated by filing year", "Year was the filing/priority date.", "Use the grant year; rename."),
 ("print_year_conflict", "Print vs online year", "Evidence shows an online-first year.", "Use the print year."),
 ("doi_unregistered", "Unregistered DOIs", "DOI does not exist at doi.org.", "Drop the DOI."),
 ("doi_title_mismatch", "DOI registry title differs", "Registry title is a stub or product name.", "Keep the DOI."),
 ("doi_record_conflict", "DOI record disagrees on a field", "Crossref/DataCite states a different value.", "Keep the cited value for that field."),
 ("surname_single_source", "Surname change with one source", "Only one source supports the new spelling.", "Hold for a second source."),
 ("quote_check_failed", "Quote check failed", "Some quotes did not cover the value.", "Apply only fields whose quotes passed."),
 ("verdict_inconsistent", "Verdict inconsistent", "Reviewer disagrees with the researcher's verdict.", "Use the reviewer's verdict."),
 ("partial", "Partly confirmed", "Some fields confirmed, one or more not found anywhere.", "Apply confirmed fields; keep unconfirmed fields as cited and sign them off."),
 ("ambiguous", "Ambiguous identity", "More than one candidate work, or version unclear.", "Decide individually (notes show the candidates)."),
 ("no_source", "No source found", "No acceptable source after catalogue searches.", "Hold; decide after all waves (removal or sign-off).")]
PRI = [g[0] for g in GROUPS[6:17]]
def group(r):
    codes = {f.get("code") for f in r["flags"]}
    if r["verdict"] == "no_source": return "no_source"
    if r["verdict"] == "ambiguous": return "ambiguous"
    for c in PRI:
        if c in codes: return c
    if r["needs_user"]: return "partial"
    if not r["final_changes"]: return "no_change"
    fs = {c["field"].lower() for c in r["final_changes"]}
    if fs <= {"doi", "volume", "number", "pages", "year", "issn"}: return "clean_numbers_doi"
    if fs & {"entrytype", "journal", "booktitle", "howpublished"}: return "clean_venue_type"
    if fs & {"publisher", "address", "editor", "edition"}: return "clean_book"
    if "title" in fs: return "clean_title"
    return "clean_authors"
data = []
for r in rows:
    ch = {c["field"]: {"before": c.get("current"), "after": c.get("proposed"), "evidence": c.get("evidence") or [],
                       "reviewer_corrected": c.get("source") == "reviewer"} for c in r["final_changes"]}
    notes = "; ".join(f"{f.get('code')}: {f.get('detail') or f.get('message') or ''}".strip(": ") for f in r["flags"])
    kp = r.get("key_plan") or {}
    if kp.get("action") and kp["action"] != "keep":
        notes = f"key {kp['action']}: {kp.get('current_key')} → {kp.get('new_key') or kp.get('target') or kp.get('existing') or kp.get('target_base')}. " + notes
    rv = r.get("reviewer") or {}
    data.append({"key": r["key"], "verdict": r["verdict"], "group": group(r), "fields": r["current"], "changes": ch,
                 "notes": notes, "reviewer": {"agree": rv.get("agree"), "problems": rv.get("problems", [])} if rv else {}})
tpl = (ROOT / "verification/research-pilot-2026-09-24/review-template.html").read_text()
start = tpl.index("const GROUPS = ["); end = tpl.index("];", start) + 2
groups_js = "const GROUPS = " + json.dumps([[g, f"{n} — suggested: {a}", d] for g, n, d, a in GROUPS], ensure_ascii=False) + ";"
tpl = tpl[:start] + groups_js + tpl[end:]
tpl = tpl.replace("<title>Research Pilot Review</title>", f"<title>Research Review — {wave.name}</title>")
tpl = tpl.replace("<h1>Research Pilot Review</h1>", f"<h1>Research Review — {wave.name}</h1>")
tpl = tpl.replace('db.collection("pilot")', f'db.collection("{wave.name}")').replace('db.doc("pilot/" + key)', f'db.doc("{wave.name}/" + key)')
tpl = tpl.replace('g !== "needs-you" && open', 'open')
out = wave / "review.html"
out.write_text(tpl.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))
import collections
print(out, collections.Counter(d["group"] for d in data))
