"""Build the cross-wave decision page (crosswave/review.html) from data files.

Reuses the wave-page template (CSS, theme tokens, layout, db decision code) that
build_review.py uses, extended with: per-question single-choice options, info-only
rows ("handled in wave N"), comparison tables for duplicate pairs, and detail lines.

Inputs (read-only):
  git show HEAD:cdl.bib
  verification/journal-alias-audit-2026-09-26.json   (likely_corrupted_cdl_entries)
  verification/research-2026-09-25/wave1..9/merged.json, postcheck.json, batch-*.json
  verification/routes-2026-09-25/measurement.json    (SfN planner route results)
Decisions: db collection "crosswave", one document per item (doc id = item key).
"""
import collections, glob, json, os, re, subprocess
from pathlib import Path

import bibtexparser
from bibtexparser.bparser import BibTexParser

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "crosswave"
WAVES = [f"wave{i}" for i in range(1, 10)]

# ---------------------------------------------------------------- inputs
env = dict(os.environ, DEVELOPER_DIR="/Library/Developer/CommandLineTools")
bib_text = subprocess.run(["git", "show", "HEAD:cdl.bib"], cwd=ROOT, env=env, check=True,
                          capture_output=True, text=True).stdout
parser = BibTexParser(common_strings=True, ignore_nonstandard_types=False)
BIB = {e["ID"]: e for e in bibtexparser.loads(bib_text, parser=parser).entries}
# raw text of each entry, to test whether a key is mentioned outside its own entry
chunks = re.split(r"(?m)^(?=@)", bib_text)
own_chunk = {}
for c in chunks:
    m = re.match(r"@\w+\s*\{\s*([^,\s]+)\s*,", c)
    if m: own_chunk[m.group(1)] = c

MERGED = collections.defaultdict(list)          # key -> [(wave, row)]
for w in WAVES:
    for r in json.loads((HERE / w / "merged.json").read_text()):
        MERGED[r["key"]].append((w, r))
BATCH = collections.defaultdict(list)           # key -> [(wave, researcher row)]
for p in sorted(HERE.glob("wave*/batch-*.json")):
    for r in json.loads(p.read_text()):
        BATCH[r["key"]].append((p.parent.name, r))
POSTCHECK = {w: json.loads((HERE / w / "postcheck.json").read_text())["summary"] for w in WAVES}
AUDIT = json.loads((ROOT / "verification/journal-alias-audit-2026-09-26.json").read_text())
SFN_ROUTE = {e["key"]: e for e in json.loads((ROOT / "verification/routes-2026-09-25/measurement.json").read_text())["entries"]
             if e["route"] == "sfn_review"}

SHOW = ["ENTRYTYPE", "author", "title", "year", "journal", "booktitle", "editor", "publisher",
        "organization", "address", "volume", "number", "pages", "doi"]
wnum = lambda w: w.replace("wave", "")


def fields(key):
    e = BIB.get(key)
    return {k: v for k, v in e.items() if k != "ID"} if e else {}


def reviewer_texts(row):
    rv = row.get("reviewer") or {}
    out = list(rv.get("problems") or [])
    for c in row.get("final_changes") or []:
        for ev in c.get("evidence") or []:
            out += ev.get("reviewer_problems") or []
    for f in row.get("flags") or []:
        out.append(f.get("detail") or f.get("message") or "")
    return [t for t in out if t]


def wave_notes(key):
    """[(label, text)] of researcher notes and reviewer problems for a key, all waves."""
    out = []
    for w, b in BATCH.get(key, []):
        if b.get("notes"): out.append((f"Researcher, wave {wnum(w)}", b["notes"]))
    for w, r in MERGED.get(key, []):
        rp = (r.get("reviewer") or {}).get("problems") or []
        if rp: out.append((f"Reviewer, wave {wnum(w)}", " ".join(rp)))
    return out


# ------------------------------------------------ 1. journal names (alias bug)
def wave_touch(key, field):
    """Waves whose merged.json changes or removes `field` (or the entry type) of `key`."""
    hits = []
    for w, r in MERGED.get(key, []):
        for c in r["final_changes"]:
            if c["field"].lower() in (field, "entrytype"):
                hits.append((w, c["field"], c.get("current"), c.get("proposed")))
        if field in (r.get("removals") or {}):
            hits.append((w, field, (r.get("current") or {}).get(field), None))
    return hits


def norm(v):
    v = re.sub(r"\\[&]", "and", str(v)).replace("&", "and")
    v = re.sub(r"[{}\\]", "", v).lower()
    v = re.sub(r"^the\s+", "", v)
    return re.sub(r"[^a-z0-9]+", " ", v).strip()


items = []
jcount = collections.Counter()
for a in AUDIT["likely_corrupted_cdl_entries"]:
    key, fld = a["key"], a["field"]
    f = fields(key)
    head_val = f.get(fld)
    details = [("Status", a["status"] + (" (Crossref match)" if a["status"] == "confirmed" else " (no Crossref match)")),
               ("Evidence", a["evidence"]), ("Wrong alias row", a["wrong_alias_row"])]
    if a.get("note"): details.append(("Audit note", a["note"]))
    if head_val is None:
        details.append(("HEAD", f"{key} has no {fld} in HEAD cdl.bib" if f else f"{key} is not in HEAD cdl.bib"))
    elif head_val != a["current_journal"]:
        details.append(("HEAD", f"HEAD {fld} is '{head_val}', not the audit's '{a['current_journal']}'"))
    touched = wave_touch(key, fld)
    it = {"key": "j-" + key, "label": key, "tag": f"{fld} · {a['year']}", "fields": f,
          "changes": {fld: {"before": a["current_journal"], "after": a["probable_true_journal"], "evidence": []}},
          "details": details}
    if touched:
        ws = sorted({wnum(w) for w, *_ in touched})
        agree = any(new is not None and norm(new) == norm(a["probable_true_journal"]) for w, fl, cur, new in touched)
        it["group"] = "j-handled"; it["info"] = True
        it["tag"] += " · wave value " + ("matches audit" if agree else "differs from audit")
        it["handled"] = f"Handled in wave {', '.join(ws)}" + ("" if agree else " (wave value differs from the audit's probable name: check it on that wave's page)") + ": " + "; ".join(
            f"{fl}: {cur!r} → {'removed' if new is None else repr(new)}" for w, fl, cur, new in touched)
        jcount["handled"] += 1; jcount["handled_" + ("agree" if agree else "differ")] += 1
        jcount["handled_" + a["status"]] += 1
    else:
        it["group"] = "j-" + a["status"]
        jcount[a["status"]] += 1
    items.append(it)

# ------------------------------------------------ 2. conference abstracts
ABSTRACT_RX = re.compile(r"\b(?:conference|meeting|poster)(?: talk/| |-)abstract", re.I)
VENUE_RX = re.compile(r"\bAbstracts\b")
NOT_ABSTRACT = {  # a regex hit whose text is about another record, not the entry itself
    "MenoEtal96": "the note's 'meeting abstract' names an unrelated DOI record (10.1016/0013-4694(96)88446-x), not this paper",
    "ParkEtal08": "the note's 'conference-abstract records' are other PsycEXTRA DOIs; the entry is a Learning and Memory article"}
EXTRA_ABSTRACTS = ["HowaKaha00", "KahaSeku99", "LongKaha12a", "BurkKaha13", "RamaEtal13", "PolyEtal05b", "HealEtal12b",
                   "CrutEtal12", "vanVEtal06", "LohnEtal09", "LohnEtal10", "PolyEtal06", "MillEtal07e", "MortEtal07", "PolyEtal07"]
ABSTRACT_RULE = ("an entry is listed when (1) the researcher's notes (batch-*.json 'notes') or the reviewer/post-check text "
                 "in merged.json (reviewer problems, flag details) says 'conference abstract', 'meeting abstract', "
                 "'poster abstract' or 'conference talk/abstract' (also with a hyphen), not preceded by 'not a'; or "
                 "(2) its journal or booktitle contains the word 'Abstracts' (except 'Dissertation Abstracts'); or "
                 "(3) it is on the list noted during research. Excluded: " +
                 "; ".join(f"{k} ({v})" for k, v in NOT_ABSTRACT.items()) + ".")


def text_hit(t):
    for m in ABSTRACT_RX.finditer(t or ""):
        if not re.search(r"not an?\s*$", t[max(0, m.start() - 8):m.start()], re.I): return True
    return False


abs_why = collections.defaultdict(list)
for key in sorted(set(MERGED) | set(BATCH)):
    if key in NOT_ABSTRACT: continue
    for w, b in BATCH.get(key, []):
        if text_hit(b.get("notes")): abs_why[key].append(f"researcher notes, wave {wnum(w)}")
    for w, r in MERGED.get(key, []):
        if any(text_hit(t) for t in reviewer_texts(r)): abs_why[key].append(f"reviewer/post-check, wave {wnum(w)}")
        cur = r.get("current") or {}
        venue = " ".join(str(cur.get(k) or "") for k in ("journal", "booktitle"))
        if VENUE_RX.search(venue) and "Dissertation Abstracts" not in venue:
            abs_why[key].append(f"venue named 'Abstracts', wave {wnum(w)}")
for k in EXTRA_ABSTRACTS:
    abs_why[k].append("noted during research (HEAD cdl.bib)")


def planner_status(key):
    urls = []
    for w, r in MERGED.get(key, []):
        for c in r["final_changes"]:
            urls += [(w, e.get("url") or "") for e in c.get("evidence") or []]
    for w, b in BATCH.get(key, []):
        urls.append((w, (b.get("identity") or {}).get("url") or ""))
        for fv in (b.get("fields") or {}).values():
            if isinstance(fv, dict): urls += [(w, e.get("url") or "") for e in fv.get("evidence") or []]
    pw = sorted({wnum(w) for w, u in urls if "abstractsonline.com" in u})
    if pw: return "yes", f"verified: SfN planner (abstractsonline.com) page quoted in wave {', '.join(pw)}"
    rt = SFN_ROUTE.get(key)
    if rt:
        return "no", f"not verified: SfN planner route result '{rt['category']}'" + (f" ({rt['issues'][0]})" if rt["issues"] else "")
    aw = sorted({wnum(w) for w, u in urls if "sfn.org" in u})
    if aw: return "no", f"not the planner: SfN's own archive/PDF quoted in wave {', '.join(aw)}"
    f = fields(key)
    blob = " ".join(str(f.get(k) or "") for k in ("journal", "booktitle", "publisher", "organization"))
    if "Society for Neuroscience" in blob: return "no", "not verified: SfN abstract with no planner result"
    return "n/a", "not an SfN abstract"


def mentioned_elsewhere(key):
    rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(key) + r"(?![A-Za-z0-9])")
    return any(rx.search(c) for k, c in own_chunk.items() if k != key)


uncited = []
for key in sorted(abs_why):
    f = fields(key)
    venue = f.get("booktitle") or f.get("journal") or f.get("howpublished") or ""
    pub = f.get("publisher") or f.get("organization") or ""
    ok, planner = planner_status(key)
    elsewhere = mentioned_elsewhere(key) if f else None
    if f and not elsewhere: uncited.append(key)
    waves = sorted({wnum(w) for w, _ in MERGED.get(key, [])})
    details = [("Venue", " · ".join(x for x in (venue, pub, f.get("year", "")) if x) or "—"),
               ("SfN planner", planner),
               ("Flagged by", "; ".join(dict.fromkeys(abs_why[key]))),
               ("Elsewhere in cdl.bib", "not in HEAD cdl.bib" if not f else
                ("key is mentioned in another entry" if elsewhere else "key is mentioned in no other entry"))]
    if waves:
        nch = sum(len(r["final_changes"]) for _, r in MERGED[key])
        details.append(("If kept", f"wave {', '.join(waves)} proposes {nch} field change(s) on its own wave page"))
    items.append({"key": "a-" + key, "label": key, "tag": f"planner: {ok}", "group": "abstracts", "fields": f,
                  "changes": {}, "proposal": "Remove this entry from cdl.bib (conference abstract).",
                  "details": details, "long": wave_notes(key)})

# ------------------------------------------------ 3. duplicates
pairs = {}
for w in WAVES:
    for dup, keep in (POSTCHECK[w].get("duplicates") or {}).items():
        pairs[(dup, keep)] = f"post-check wave {wnum(w)}"
for dup, keep in [("Rugg00", "RuggAlla00"), ("KahaEtal08b", "KahaEtal08a")]:
    pairs.setdefault((dup, keep), "noted during research")
for (dup, keep), src in pairs.items():
    fd, fk = fields(dup), fields(keep)
    rows = [[k, fd.get(k), fk.get(k)] for k in SHOW if fd.get(k) or fk.get(k)]
    details = [("Source", src)]
    for k, f in ((dup, fd), (keep, fk)):
        if not f: details.append(("HEAD", f"{k} is not in HEAD cdl.bib"))
    items.append({"key": f"dup-{dup}-{keep}", "label": f"{dup} → {keep}", "tag": f"keep {keep}", "group": "duplicates",
                  "fields": fk or fd, "changes": {}, "proposal": f"Merge {dup} into {keep}; remove {dup} and log {dup} → {keep} in key-renames.",
                  "compare": {"head": ["Field", f"{dup} (remove)", f"{keep} (keep)"], "rows": rows},
                  "details": details, "long": wave_notes(dup) + wave_notes(keep)})

# ------------------------------------------------ 4. open questions
hwang = sorted(k for k, e in BIB.items() if re.search(r"\bG(?: M)? Hwang", e.get("author", "")))
QUESTIONS = [
    ("q-ebbinghaus", "Ebbinghaus: original or translation", "Cite the 1885 German original or the 1913 English translation (key Ebbi13)?",
     ["Ebbi85"], [("original-1885", "1885 German original (Über das Gedächtnis)"), ("translation-1913", "1913 English translation, key Ebbi13"), ("other", "Other (note)")]),
    ("q-hwang", "Hwang: printed name or unified", "Keep each paper's printed name (G Hwang-Grodzins 2005 / G M Hwang 2008) or unify?",
     hwang, [("as-printed", "Keep each printed name"), ("unify", "Unify to one form (name it in the note)"), ("other", "Other (note)")]),
    ("q-country", "Country added to address", "Add the country to an address when the source does not print it (e.g. 'Germany' in Herb34, BuzsEtal94)?",
     ["Herb34", "BuzsEtal94"], [("keep-convention", "Keep as house convention"), ("drop", "Drop when not printed"), ("other", "Other (note)")]),
    ("q-shim", "Shim94 year 1995 key collision", "Shim94 → year 1995 collides with the existing Shim95 (a different work). How should the keys go?",
     ["Shim94", "Shim95"], [("shim95a-new", "Shim94 → Shim95a, existing Shim95 → Shim95b"),
                            ("shim95b-new", "Shim94 → Shim95b, existing Shim95 → Shim95a (post-check key plan)"),
                            ("keep-1994", "Keep year 1994 and key Shim94"), ("other", "Other (note)")]),
    ("q-ogrady", "O'Grady Pie Man: which year", "Year of recording (2008, key OGra08) or year of publication/use (2011, keep OGra11)?",
     ["OGra11"], [("2008", "2008 (recorded/podcast; key OGra08)"), ("2011", "2011 (keep OGra11)"), ("other", "Other (note)")]),
    ("q-brainiak", "BrainIAK: which Zenodo version", "Cite the latest Zenodo version of BrainIAK or v0.2 (2016, key CapoEtal16)?",
     ["CapoEtal17"], [("latest", "Latest Zenodo version"), ("v0.2", "v0.2 (2016)"), ("other", "Other (note)")]),
]
for qid, label, question, keys, options in QUESTIONS:
    rows = []
    for k in keys:
        f = fields(k)
        rows.append([k, f.get("author", "—"), f.get("year", "—"), f.get("title", "not in HEAD cdl.bib")])
    plans = []
    for w_k in keys:
        for w, r in MERGED.get(w_k, []):
            kp = r.get("key_plan") or {}
            if kp.get("action") and kp["action"] != "keep":
                also = "; ".join(f"{a} → {b}" for a, b in (kp.get("also_rename") or {}).items())
                plans.append(("Key plan", f"{w_k}, wave {wnum(w)}: {kp['action']} → {kp.get('new_key') or kp.get('merge_into') or kp.get('target_base')}"
                              + (f" (also {also})" if also else "")))
    items.append({"key": qid, "label": label, "tag": "open question", "group": "questions", "fields": {}, "changes": {},
                  "question": question, "options": [list(o) for o in options],
                  "compare": {"head": ["Key", "Author", "Year", "Title / plan"], "rows": rows},
                  "details": plans, "long": [x for k in keys for x in wave_notes(k)]})

# ------------------------------------------------ groups
GROUPS = [
    ("j-confirmed", "Journal names damaged by the alias bug — confirmed",
     f"A wrong row in bibcheck/journal_key.xls rewrote the venue; a Crossref record confirms the true name. {jcount['confirmed']} entries.",
     "restore the probable true name."),
    ("j-unconfirmed", "Journal names damaged by the alias bug — unconfirmed",
     f"Same alias-bug pattern, but no Crossref record confirms the true name. {jcount['unconfirmed']} entries.", "decide individually."),
    ("j-handled", "Journal names already handled by a wave",
     f"A wave's merged.json already changes this field or the entry type; decide it on that wave's page. {jcount['handled']} entries "
     f"({jcount['handled_confirmed']} confirmed, {jcount['handled_unconfirmed']} unconfirmed in the audit); the wave value matches the "
     f"audit's probable name for {jcount['handled_agree']} and differs for {jcount['handled_differ']} (tagged).",
     "nothing to decide here."),
    ("abstracts", "Conference abstracts proposed for removal",
     f"Rule: {ABSTRACT_RULE} Key mentioned in no other HEAD cdl.bib entry: {', '.join(uncited) or 'none'}.",
     "remove (Correct = remove)."),
    ("duplicates", "Duplicates across the library",
     "Two keys for the same work. Correct = merge the first key into the proposed keeper.", "merge into the keeper."),
    ("questions", "Open questions", "One choice per question; add a note for anything else.", "choose one."),
]
NOBULK = ["j-handled", "questions"]
for s in items:
    s["fields"] = {k: v for k, v in s["fields"].items()}

# ------------------------------------------------ template (shared with build_review.py)
tpl = (ROOT / "verification/research-pilot-2026-09-24/review-template.html").read_text()


def sub(old, new, count=1):
    global tpl
    assert tpl.count(old) == count, (old[:60], tpl.count(old))
    tpl = tpl.replace(old, new)


def sub_between(start, end, new):
    global tpl
    i = tpl.index(start); j = tpl.index(end, i)
    tpl = tpl[:i] + new + tpl[j:]


TITLE = "Cross-wave Decisions"
sub("<title>Research Pilot Review</title>", f'<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{TITLE}</title>')
sub("<h1>Research Pilot Review</h1>", f"<h1>{TITLE}</h1>")
sub_between('<p class="intro">', "</p>", '<p class="intro">Decisions that span the nine research waves: venue names damaged by the '
            'journal-alias bug, conference abstracts proposed for removal, duplicate entries, and open questions. Everything '
            'below is generated from the audit, wave and route data files and HEAD <code>cdl.bib</code>. Check a few in each group; '
            '<strong>Approve rest of group</strong> marks every undecided item in it correct. Questions take one choice each.')
start = tpl.index("const GROUPS = ["); end = tpl.index("];", start) + 2
tpl = tpl[:start] + "const GROUPS = " + json.dumps([[g, f"{n} — suggested: {a}", d] for g, n, d, a in GROUPS], ensure_ascii=False) + \
      ";\nconst NOBULK = " + json.dumps(NOBULK) + ";" + tpl[end:]
sub('db.collection("pilot")', 'db.collection("crosswave")')
sub('db.doc("pilot/" + key)', 'db.doc("crosswave/" + key)')
sub('localStorage.setItem("pilot:" + key', 'localStorage.setItem("crosswave:" + key')
sub('localStorage.getItem("pilot:" + s.key)', 'localStorage.getItem("crosswave:" + s.key)')
sub("{key, group: s.group, verdict:", "{key, entry: s.label, group: s.group, verdict:")
sub('g !== "needs-you" && open', '!NOBULK.includes(g) && open')
sub("const open = items.filter(s => !(decisions[s.key]||{}).verdict).length;",
    "const open = items.filter(s => !s.info && !(decisions[s.key]||{}).verdict).length;")
sub('<span class="meta">${items.length} entries</span>', '<span class="meta">${items.length} ${items.length === 1 ? "item" : "items"}</span>')
sub("const keys = DATA.filter(s => s.group === bulk.dataset.g && !(decisions[s.key]||{}).verdict)",
    "const keys = DATA.filter(s => s.group === bulk.dataset.g && !s.info && !s.options && !(decisions[s.key]||{}).verdict)")
sub("const visible = s => {", "const visible = s => { if (s.info) return filter === \"all\";")
sub_between("function tally(){", "const setStatus", """function tally(){
  const dec = DATA.filter(s => !s.info), n = dec.length, c = {correct:0, wrong:0, unsure:0, chosen:0};
  for (const s of dec) { const v = (decisions[s.key]||{}).verdict; if (!v) continue; if (s.options) c.chosen++; else if (v in c) c[v]++; }
  const done = c.correct + c.wrong + c.unsure + c.chosen;
  document.getElementById("tally").innerHTML = `<b>${done}</b>/${n} decided · ${c.correct} correct · ${c.wrong} wrong · ${c.unsure} unsure · ${c.chosen} answered`;
  document.getElementById("m-ok").style.width = (100*(c.correct+c.chosen)/n)+"%"; document.getElementById("m-bad").style.width = (100*c.wrong/n)+"%"; document.getElementById("m-warn").style.width = (100*c.unsure/n)+"%";
}
""")
sub_between("function entryHtml(s){", "const visible", r"""function compare(s){
  if (!s.compare) return "";
  const cell = v => v == null || v === "" ? '<span class="none">absent</span>' : esc(v);
  return `<div class="scroll"><table><thead><tr>${s.compare.head.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${s.compare.rows.map(r =>
    `<tr><td class="f">${esc(r[0])}</td>${r.slice(1).map((v,i) => `<td class="v${s.compare.head[i+1] === "Year" ? " yr" : ""}">${cell(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function details(s){
  const d = (s.details || []).map(([l,t]) => `<div class="notes"><b class="dl">${esc(l)}:</b> ${esc(t)}</div>`).join("");
  const l = (s.long || []).length ? `<details><summary>Wave notes (${s.long.length})</summary><div class="ev">${s.long.map(([k,t]) => `<div><b class="dl">${esc(k)}:</b> ${esc(t)}</div>`).join("")}</div></details>` : "";
  return d + l;
}
function entryHtml(s){
  const d = decisions[s.key] || {};
  const btn = (v,l,c) => `<button type="button"${c ? ` class="${c}"` : ""} data-v="${esc(v)}" aria-pressed="${d.verdict === v}">${esc(l)}</button>`;
  const buttons = s.options ? s.options.map(([v,l]) => btn(v,l,"opt")).join("") : btn("correct","Correct") + btn("wrong","Wrong") + btn("unsure","Unsure");
  const cls = d.verdict ? (s.options ? "v-chosen" : "v-" + d.verdict) : "";
  const decide = s.info ? `<div class="rev"><b>${esc(s.handled)}</b></div>` : `<div class="decide">${buttons}
      <input id="note-${esc(s.key)}" type="text" placeholder="${s.options ? "Note (required for Other)" : "Note (what is wrong, or the right value)"}" value="${esc(d.note || "")}" aria-label="Note for ${esc(s.label)}">
      <span class="saved" id="saved-${esc(s.key)}"></span></div>`;
  return `<article class="entry ${cls}${s.info ? " info" : ""}" data-key="${esc(s.key)}">
    <div class="top"><span class="key">${esc(s.label)}</span><span class="num">${esc(s.tag || "")}</span></div>
    ${s.question ? `<div class="cite">${esc(s.question)}</div>` : (Object.keys(s.fields).length ? citation(s.fields) : "")}
    ${Object.keys(s.changes).length ? changes(s) : ""}${s.proposal ? `<div class="notes"><b class="dl">Proposed:</b> ${esc(s.proposal)}</div>` : ""}
    ${compare(s)}${details(s)}${decide}</article>`;
}
""")
sub(".notes{font-size:13px;color:var(--muted);max-width:75ch}", """.notes{font-size:13px;color:var(--muted);max-width:75ch;overflow-wrap:anywhere}
.dl{color:var(--ink);font-weight:600}
.ev div{overflow-wrap:anywhere}
.entry.v-chosen{border-left:4px solid var(--accent)}
.entry.info{opacity:.85}
.decide button.opt[aria-pressed="true"]{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
code{font:13px var(--mono)}
td.v.yr{white-space:nowrap}""")

data = [{k: v for k, v in s.items()} for s in items]
OUT.mkdir(exist_ok=True)
(OUT / "data.json").write_text(json.dumps({"abstract_rule": ABSTRACT_RULE, "uncited_abstracts": uncited, "items": data},
                                          ensure_ascii=False, indent=1) + "\n")
assert "/*DATA*/null" in tpl
(OUT / "review.html").write_text(tpl.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
                                                        # registry text can carry U+FFFD; keep it as a JSON escape
                                                        .replace("�", "\\ufffd")))
cnt = collections.Counter(s["group"] for s in data)
print(OUT / "review.html", dict(cnt))
print("uncited abstracts:", len(uncited), uncited)
print("journal:", dict(jcount))
