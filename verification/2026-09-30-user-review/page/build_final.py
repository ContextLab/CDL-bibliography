"""Trimmed review page (v4): only questions still open after the printed-byline check.
Answered items are removed from view (their answers stay in the db). Every manual check has a DOI link."""
import json, re, subprocess, os, sys
from pathlib import Path
ROOT = Path("/Users/jmanning/CDL-bibliography"); HERE = Path(__file__).resolve().parent
ENV = dict(os.environ, DEVELOPER_DIR="/Library/Developer/CommandLineTools")
BIB = subprocess.run(["git", "show", "HEAD:cdl.bib"], cwd=ROOT, env=ENV, check=True, capture_output=True, text=True).stdout
PR = json.loads(Path("/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/printed/printed.json").read_text())
def entry(k):
    m = re.search(r"@\w+\{" + re.escape(k) + r",.*?\n\n", BIB, re.S); return m.group(0).strip() if m else None
def doi(k):
    e = entry(k) or ""; m = re.search(r"Doi = \{([^}]*)\}", e); return m.group(1) if m else None
items = []
items.append(dict(id="rule-unify", section="G", key="Rule",
    question=("The same person's name is sometimes printed differently in different papers. For example, Joseph LeDoux "
              "appears as “Le Doux” in NadeEtal00 but “LeDoux” elsewhere; one paper prints “Dagata” for D'Agata and one prints "
              "“Klosterkoetter” for Klosterkötter. You also noted “Unify the spellings” on the formatting group. Which rule should apply?"),
    options=[["per-paper", "Each entry follows its own printed paper"], ["unify", "One spelling per person everywhere (the one the person uses most)"],
             ["other", "Something else (say what)"]], context=[]))
g = next(r for r in PR if r["id"] == "recheck-RebeEtal02-3")
items.append(dict(id="typo-RebeEtal02-3", section="H", key="RebeEtal02",
    question=("The Journal of Neuroscience printed author 3 as “Darren R. Gitleman”, a typo for Gitelman (PubMed has “Gitelman DR”). "
              "Your rule says cite as printed. Keep the printed typo, or use the correct spelling?"),
    options=[["printed", "“Gitleman” (as printed)"], ["correct", "“Gitelman” (correct spelling)"]],
    links=[["Paper", g.get("url") or f"https://doi.org/{doi('RebeEtal02')}"]],
    context=[["Printed", f"“{g['quote']}” (p. {g.get('page','?')})"]], after=entry("RebeEtal02")))
for r in PR:
    if r["class"] != "NO-ACCESS": continue
    k, d = r["key"], doi(r["key"])
    links = [["DOI", f"https://doi.org/{d}"]] if d else []
    if r.get("url") and (not d or d.lower() not in r["url"].lower()): links.append(["Where the agent tried", r["url"]])
    extra = ""
    if k == "BrisEtal02": extra = " Note: Springer and MEDLINE both list this author as “Arcelin René”, so the entry's surname “René” may itself be wrong; please check the byline."
    items.append(dict(id=f"manual-{r['id']}", section="I", key=k,
        question=(f"Author {r['position']}: the entry has “{r['entry_spelling']}”, the source has “{r['source_spelling']}”. "
                  f"What does the printed byline say?{extra}"),
        options=[["entry", f"“{r['entry_spelling']}” (entry)"], ["source", f"“{r['source_spelling']}” (source)"],
                 ["other", "Something else (type it in the note)"]],
        links=links, context=[["Why I couldn't check", r.get("quote") or r.get("note") or "access blocked"]], after=entry(k)))
SECTIONS = {
    "G": ("One rule question", "Decides how the settled names are written."),
    "H": ("A printing error", "The printed byline has a typo."),
    "I": ("Papers I couldn't open", "Please open each link (you're on the Dartmouth VPN), look at the byline, and pick the printed spelling. Most are ScienceDirect, which asked the automated browser to prove it's human."),
}
page = (HERE / "template.html").read_text()
page = page.replace("Everything still waiting on you before the verification branch (PR #89) is merged.",
    "Only the questions still open. Your earlier answers are saved; the printed papers (read through the Dartmouth VPN) settled 53 of the 73 surname questions.")
page = page.replace("/*DATA*/[]", json.dumps(items, ensure_ascii=False).replace("</", "<\\/").replace("�", "\\ufffd"))
page = page.replace("/*SECTIONS*/{}", json.dumps(SECTIONS, ensure_ascii=False).replace("�", "\\ufffd"))
Path(sys.argv[1]).write_text(page); print(len(items), "items; FFFD:", page.count("�"))
