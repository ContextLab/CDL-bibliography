"""Build the 2026-09-30 user-review page (review.html) from committed records.

Sections:
  A. Approved entries edited by the brace cleanup (4cdc644): before/after + old approval.
  B. Open page notes from the notes audit (FLAG / NO-REQUEST rows) and the KahaEtal08b key reuse.
  C. Surname mismatches (rule 5, user 2026-09-30), read from surnames.json when present.
  D. Resolved under the user's 2026-09-30 rule (information only; the user can object).
Decisions: db collection "review0930", one document per item id.
Usage: python build_page.py <out.html> [surnames.json]
"""
import gzip, html, json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path("/Users/jmanning/CDL-bibliography")
HERE = Path(__file__).resolve().parent
ENV = dict(os.environ, DEVELOPER_DIR="/Library/Developer/CommandLineTools")
NOTES = json.loads(Path("/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/"
                        "0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/notes-audit/notes-audit.json").read_text())


def git(*a, binary=False):
    out = subprocess.run(["git", *a], cwd=ROOT, env=ENV, check=True, capture_output=True)
    return out.stdout if binary else out.stdout.decode()


def entry_text(rev, key):
    m = re.search(r"@\w+\{" + re.escape(key) + r",.*?\n\n", git("show", f"{rev}:cdl.bib"), re.S)
    return m.group(0).strip() if m else None


def approvals(rev, keys):
    out = {}
    for line in gzip.decompress(git("show", f"{rev}:verification/baseline.jsonl.gz", binary=True)).splitlines():
        r = json.loads(line)
        if r.get("key") in keys:
            out[r["key"]] = r.get("human_review") or {}
    return out


items = []

# ---- A. brace-edited approved entries -------------------------------------------
BRACE = ["Bart32", "KahaEtal24", "Mink15", "Youn61"]
old = approvals("7f3eead", set(BRACE))
for k in BRACE:
    hr = old.get(k, {})
    items.append(dict(
        id=f"brace-{k}", section="A", key=k,
        question="The brace cleanup changed this approved entry (braces only). Approve the new text?",
        options=[["approve", "Approve"], ["change", "Needs a change (say what)"]],
        before=entry_text("7f3eead", k), after=entry_text("HEAD", k),
        context=[["Your earlier approval",
                  f"{hr.get('reviewer','?')}; source: {hr.get('source','?')}; note: {hr.get('note','?')}"]]))

# ---- B. open page notes -----------------------------------------------------------
OPTIONS = {
    "Murd71": [["drop", "Drop the number field (as your note said)"], ["keep", "Keep Number = 4 (Crossref states issue 4)"]],
    "Hint03": [["drop", "Drop the number field"], ["keep", "Keep Number = 1 (Crossref states issue 1)"]],
    "a-CronEtal94": [["restore", "Restore it as an article, Brain and Language 47:466--468"], ["drop", "Confirm the drop"]],
    "DougPeuc73": [["keep", "Keep 'The Canadian Cartographer' (name printed in 1973)"], ["current", "Use Crossref's current name 'Cartographica'"]],
    "Mann06": [["keep", "Keep @mastersthesis with Type = {Senior thesis}"], ["change", "Change it (say how)"]],
}
for r in NOTES:
    if r["class"] not in ("FLAG", "NO-REQUEST"):
        continue
    k = r["key"]
    shown = "CronEtal94" if k == "a-CronEtal94" else (r.get("current_key") or k)
    ev = "; ".join(f"{e.get('quote','')} ({e.get('url','')})" for e in r.get("evidence") or [])
    items.append(dict(
        id=f"note-{shown}", section="B", key=shown,
        question=r["reason"], options=OPTIONS.get(k, [["resolved", "Resolved as is"], ["change", "Change it (say how)"]]),
        after=r.get("current_entry"),
        context=[["Your page note", f"{r['verdict']}: “{r['note'] or '(no note)'}” ({r['updated_edt']}, {r['page'].split(' (')[0]})"],
                 ["Evidence", ev or "none recorded"]]))

items.append(dict(
    id="note-KahaEtal08b", section="B", key="KahaEtal08b",
    question=("On the cross-wave page you marked the duplicate pair KahaEtal08b/KahaEtal08a “unsure” and wrote "
              "“drop the \"a\" at the end of the key if this is the only KahaEtal08”. The old KahaEtal08b (the same chapter, "
              "titled “Associative processes in episodic memory”, pp 476--490) was merged into KahaEtal08a, and the key "
              "KahaEtal08b now names a different work (the Psychological Review reply, formerly KahaEtal08c). A paper that "
              "cites KahaEtal08b meaning the chapter would now print the reply. What should happen?"),
    options=[["accept", "Accept the merge and the reused key"],
             ["nokey-reuse", "Accept the merge, but don't reuse KahaEtal08b (give the reply a fresh key)"],
             ["change", "Something else (say what)"]],
    before=entry_text("282d321^", "KahaEtal08b"), after=entry_text("HEAD", "KahaEtal08b"),
    context=[["Keeper now", entry_text("HEAD", "KahaEtal08a") or "(missing)"]]))

# ---- C. surnames (grouped by class; genuine spelling differences asked one by one) --
GENUINE = {("AndeEtal66",3),("BahrPhel87",2),("Buzs98",1),("FreeEtal03b",3),("IshiEtal75",3),("KatzEtal89",3),
           ("KimbEtal08",1),("LuriEtal20",6),("Madi71",1),("MallEtal97",3),("MeyeEtal88",4),("NewmBuck62",2),
           ("RebeEtal02",3),("SlamFevr83",1),("TulvHast72",1),("WaszWalt83",1),("WatkPeyn83",2),("Wick69",1),
           ("AndeEtal66",2),("KragEtal19",9),("LopeEtal73",4),("dBakEtal08",1)}
if len(sys.argv) > 2 and Path(sys.argv[2]).exists():
    rows = json.loads(Path(sys.argv[2]).read_text())
    groups = {"format": [], "longer": [], "shorter": [], "corrupt": []}
    for s in rows:
        if (s["key"], s["position"]) in GENUINE:
            items.append(dict(
                id=f"surname-{s['key']}-{s['position']}", section="C", key=s["key"],
                question=f"Author {s['position']}: the entry has “{s['entry_spelling']}”, the source has “{s['source_spelling']}”. {s['question']}",
                options=[["entry", f"Keep “{s['entry_spelling']}”"], ["source", f"Change to “{s['source_spelling']}”"],
                         ["other", "Something else (say what)"]],
                after=entry_text("HEAD", s["key"]),
                context=[["Source", s.get("source", "")]] + ([["Printed paper", s["printed_quote"]]] if s.get("printed_quote") else [])))
        else:
            if s["class"] == "words":
                longer = len(s["source_spelling"].replace("{", "").split()) > len(s["entry_spelling"].replace("{", "").split())
                groups["longer" if longer else "shorter"].append(s)
            else:
                groups["corrupt" if s["class"] == "spelling" else s["class"]].append(s)
    GQ = {
        "format": ("The two spellings are the same name and differ only in formatting: accents, periods, apostrophes, spacing, "
                   "capitals, a name suffix (Jr, III) run into the surname, or stray marks (“Miller $^*$”, “Berdan,”)."),
        "longer": ("The source's surname field has extra words, which look like given names or initials (e.g. “SAMI UYANIK”, "
                   "“Kluyver Thomas”, “Yves von Cramon”). Check the list for any that are really part of a compound surname."),
        "shorter": ("The source keeps only part of the entry's compound surname (e.g. “Linden” for “{van der Linden}”, "
                    "“Neely” for “{Stigsdotter Neely}”, “del Río” for “{Fernández del Río}”)."),
        "corrupt": ("The source's text is garbled: broken characters (“M�ller”, “Branka?k”), HTML codes (“P&eacute;rez”), a transliteration "
                    "(“Klosterkoetter”), or given names where surnames belong (every author of BabiEtal04; “III” for Gerow)."),
    }
    for g, lst in groups.items():
        if not lst: continue
        items.append(dict(
            id=f"surname-group-{g}", section="C", key=f"{len(lst)} mismatches",
            question=GQ[g] + " Keep the entry's spelling for all of these?",
            options=[["keep-all", "Keep the entry's spelling for all"], ["show", "List them one by one for me"],
                     ["except", "Keep all except those I name in the note"]],
            rows=[f"{s['key']} (author {s['position']}): entry “{s['entry_spelling']}” / source “{s['source_spelling']}”" for s in lst],
            context=[]))

# ---- D. resolved under the user's rule (information) ------------------------------
for r in NOTES:
    k = r.get("current_key") or r["key"]
    if k in ("ScotEtal07", "KahaMill13", "Hook69", "Palm78") and r["class"].startswith("RESOLVED"):
        items.append(dict(
            id=f"resolved-{k}", section="D", key=k,
            question=r["reason"], options=[["ok", "Fine"], ["object", "Object (say why)"]],
            after=entry_text("HEAD", k),
            context=[["Your page note", f"{r['verdict']}: “{r['note']}” ({r['updated_edt']})"]]))

SECTIONS = {
    "A": ("Approved entries changed by the brace cleanup",
          "You approved these earlier. The brace cleanup (4cdc644) removed braces that protect nothing, so the approvals lapsed. Nothing else changed."),
    "B": ("Page notes that weren't followed, or that you left open",
          "From the check of all 61 notes you left on the review pages: 56 were followed or resolved; these were not."),
    "C": ("Surname mismatches",
          "Your rule (2026-09-30): one source is sufficient, but where the entry and the source spell a surname differently, you decide."),
    "D": ("Resolved under your rule (for information)",
          "Your rule (2026-09-30): if your request was followed, it's resolved; a DOI that doesn't exist counts as resolved. These will be marked resolved unless you object."),
}

page = (HERE / "template.html").read_text()
page = page.replace("/*DATA*/[]", json.dumps(items, ensure_ascii=False).replace("</", "<\\/").replace("\ufffd", "\\ufffd"))
page = page.replace("/*SECTIONS*/{}", json.dumps(SECTIONS, ensure_ascii=False).replace("\ufffd", "\\ufffd"))
Path(sys.argv[1]).write_text(page)
print(len(items), "items:", {s: sum(1 for i in items if i["section"] == s) for s in SECTIONS})
