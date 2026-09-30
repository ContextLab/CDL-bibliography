"""Map every one of the 137 surname mismatches (../2026-09-30-user-review/surnames.json) to the
user's decision (batch surnames0930c).

Inputs (all frozen in this folder or its siblings):
  answers/            the review page's answer documents (collection review0930), read with the
                      ArtifactData tool on 2026-09-30
  printed/printed.json the printed-byline evidence (73 rows) collected through the Dartmouth VPN
  ../2026-09-30-user-review/page/surnames-classified.json  the page's grouping of the rows

Output: decisions.json, one row per mismatch: decision (keep / change / hold), the new author
name for a change, the rule or document that decides it and the printed evidence.

    python verification/apply-2026-09-30c-surnames/build_decisions.py
"""
from collections import Counter
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REVIEW = HERE.parent / "2026-09-30-user-review"
PAGE = "https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM"
COLLECTION = "review0930"

ROWS = json.loads((REVIEW / "surnames.json").read_text())
CLASSIFIED = json.loads((REVIEW / "page/surnames-classified.json").read_text())
PRINTED = {(r["key"], r["position"]): r for r in json.loads((HERE / "printed/printed.json").read_text())}
DOCS = {p.stem: json.loads(p.read_text()) for p in (HERE / "answers").glob("*.json")}

# The page's individually asked rows (build_page.py GENUINE).
GENUINE = {("AndeEtal66", 3), ("BahrPhel87", 2), ("Buzs98", 1), ("FreeEtal03b", 3), ("IshiEtal75", 3),
           ("KatzEtal89", 3), ("KimbEtal08", 1), ("LuriEtal20", 6), ("Madi71", 1), ("MallEtal97", 3),
           ("MeyeEtal88", 4), ("NewmBuck62", 2), ("RebeEtal02", 3), ("SlamFevr83", 1), ("TulvHast72", 1),
           ("WaszWalt83", 1), ("WatkPeyn83", 2), ("Wick69", 1), ("AndeEtal66", 2), ("KragEtal19", 9),
           ("LopeEtal73", 4), ("dBakEtal08", 1)}
SUFFIX_ROWS = {("EngeEtal10", 6), ("GomeEtal96", 3), ("IyyeEtal15", 4), ("PollGero68", 2), ("Roed08", 1),
               ("Warr98", 1)}
SUFFIX_RULE = ("user rule, decision log (verification/resolution-plan-2026-09-22/README.md), section "
               "'Spot-check completed (2026-09-24/25) and resulting decisions': \"No name suffixes (Jr, Sr, "
               "II, III, IV): never added; the 27 existing ones are stripped; the comparator ignores suffixes.\"")
PER_PAPER = {("FreuEtal09", 6): "J Klosterkoetter", ("LatiEtal10", 7): "F Dagata", ("NadeEtal00", 3): "J E {Le Doux}"}
# Changes: (key, position) -> (old author name, new author name), house form.
CHANGES = {
    ("KragEtal19", 9): ("L F Barrett", "L {Feldman Barrett}"),
    ("LopeEtal73", 4): ("W S {van Leeuwen}", "W {Storm van Leeuwen}"),
    ("LopeEtal73", 1): ("F H {Lopes Da Silva}", "F H {Lopes da Silva}"),
    ("PennEtal94", 3): ("F H {Lopes Da Silva}", "F H {Lopes da Silva}"),
    ("dBakEtal08", 1): ("R S J {d Baker}", "R S J {d} Baker"),
    ("MurdVomS67", 2): ("W {Vom {S}aal}", "W {vom Saal}"),
    ("IshiEtal75", 3): ("N Yoshimasu", "N Yoshimasa"),
    ("FreuEtal09", 6): ("J Klosterk{\\\"o}tter", "J Klosterkoetter"),
    ("LatiEtal10", 7): ("F D'Agata", "F Dagata"),
    ("NadeEtal00", 3): ("J E LeDoux", "J E {Le Doux}"),
    ("ConwEtal00", 4): ("M Racsm\\'{a}ny", "M Racsma'ny"),
    ("MillEtal07c", 2): ("M {den Nijs}", "M denNijs"),
    ("MillEtal07d", 5): ("M {den Nijs}", "M denNijs"),
}
# The user's message in the orchestrating session resolving the three rows the page left on hold
# (2026-09-30, relayed verbatim by the orchestrator).
HOLD_MESSAGE = ("1. ConwEtal00 had an apostrophe, not an accent / 2. denNijs is printed as one word in the "
                "example pub")
# Held for the user: the user's text uses \dot, a math-mode accent that stops LaTeX in text mode
# (README, "WatkPeyn83").
HELD = {("WatkPeyn83", 2)}


def doc_ref(doc_id):
    d = DOCS[doc_id]
    return {"doc": doc_id, "section": d["section"], "choice": d["choice"], "note": d["note"],
            "answered": d["updatedAt"], "source": f"review page {PAGE}, collection {COLLECTION}, doc {doc_id}, "
                                                    f"answered {d['updatedAt']}"}


def printed_ref(k, pos):
    p = PRINTED.get((k, pos))
    if not p:
        return None
    return {k2: p.get(k2) for k2 in ("id", "class", "printed", "quote", "page", "url", "pdf_sha256", "how", "note")}


def decide(r):
    k, pos = r["key"], r["position"]
    kp = (k, pos)
    pr = printed_ref(k, pos)
    out = {"key": k, "position": pos, "entry_spelling": r["entry_spelling"], "source_spelling": r["source_spelling"],
           "source": r["source"], "printed": pr, "docs": []}
    if kp in GENUINE:
        c = doc_ref(f"surname-{k}-{pos}")
        out["docs"].append(c)
        if pr and pr["class"] == "PRINTED=ENTRY":
            out.update(decision="keep", why=f"printed paper = entry; overrides the user's earlier '{c['choice']}' "
                                            "(Crossref) pick, because the printed paper wins")
        elif kp == ("RebeEtal02", 3):
            t = doc_ref("typo-RebeEtal02-3")
            out["docs"].append(t)
            assert t["choice"] == "correct"
            out.update(decision="keep", why="printed 'Gitleman' (a typo); the user chose 'correct' (Gitelman): "
                                            "user-approved exception to the as-printed rule")
        elif kp == ("IshiEtal75", 3):
            m = doc_ref("manual-recheck-IshiEtal75-3")
            out["docs"].append(m)
            assert c["choice"] == m["choice"] == "source"
            out.update(decision="change", why="the user checked the print: 'Yoshimasa' (source)")
        elif kp in HELD:
            assert c["choice"] == "other"
            out.update(decision="hold", why="user's text uses \\dot{i}, a math-mode accent that stops LaTeX in "
                                            "text mode; the user decides the spelling")
        elif c["choice"] == "entry":
            out.update(decision="keep", why="user chose the entry's spelling")
        elif c["choice"] == "source":
            out.update(decision="change", why="user chose the source's spelling")
        else:
            raise AssertionError((kp, c))
    elif kp in SUFFIX_ROWS:
        out.update(decision="keep", why="name suffix: " + SUFFIX_RULE)
    elif pr is None:
        cl = next(x for x in CLASSIFIED if (x["key"], x["position"]) == kp)
        assert cl["class"] == "words", cl
        g = doc_ref("surname-group-longer")
        out["docs"].append(g)
        assert g["choice"] == "except"
        if kp == ("MurdVomS67", 2):
            out.update(decision="change", why="group 'longer': the user's exception, note: " + g["note"])
        else:
            out.update(decision="keep", why="group 'longer' (source adds words): keep all except MurdVomS67")
    elif pr["class"] == "PRINTED=ENTRY":
        out.update(decision="keep", why="printed paper = entry")
    elif kp in PER_PAPER:
        u = doc_ref("rule-unify")
        out["docs"].append(u)
        assert u["choice"] == "per-paper" and pr["class"] == "PRINTED=SOURCE"
        out.update(decision="change", why="printed form, under the user's rule answer 'per-paper' (each entry "
                                          "follows its own printed paper)")
    elif pr["class"] == "NO-ACCESS":
        m = doc_ref(f"manual-{pr['id']}")
        out["docs"].append(m)
        if m["choice"] == "entry":
            out.update(decision="keep", why="the user read the printed byline: entry's spelling")
        elif kp in {("SchaEtal11", 3), ("StJaEtal12", 1)}:
            assert m["choice"] == "source"
            out.update(decision="keep", why="the user read 'St. Jacques' (source); the house form strips periods, "
                                            "so it is '{St Jacques}', the entry's spelling: no edit")
        elif kp in {("ConwEtal00", 4), ("MillEtal07c", 2), ("MillEtal07d", 5)}:
            assert m["choice"] == "source"
            out.update(decision="change", why="the user chose the source's spelling; the user's message "
                                              f"(2026-09-30): \"{HOLD_MESSAGE}\"")
            out["user_message"] = HOLD_MESSAGE
        elif m["choice"] == "other":
            assert m["note"] == '"{Lopes da Silva}"', m
            out.update(decision="change", why="the user's text: " + m["note"])
        else:
            raise AssertionError((kp, m))
    else:
        raise AssertionError((kp, pr["class"]))
    if out["decision"] == "change":
        out["old_name"], out["new_name"] = CHANGES[kp]
    return out


def main():
    rows = [decide(r) for r in ROWS]
    # 137 rows, 136 author positions: ElHaEtal19 author 2 has two rows (Crossref "M. J. Janssen" and
    # PubMed/PMC "M J Janssen"); both are in the "longer" group.
    assert len(rows) == 137 and len({(r["key"], r["position"]) for r in rows}) == 136
    changed = {(r["key"], r["position"]) for r in rows if r["decision"] == "change"}
    assert changed == set(CHANGES), sorted(changed ^ set(CHANGES))
    # every answer document of sections C, E, F, G, H and I is used
    used = {d["doc"] for r in rows for d in r["docs"]}
    wanted = {k for k, d in DOCS.items() if d["section"] in "CEFGHI"}
    unused = sorted(wanted - used)
    assert unused == ["surname-group-corrupt", "surname-group-format", "surname-group-shorter"], unused
    print(json.dumps({"decisions": dict(Counter(r["decision"] for r in rows)),
                      "printed_classes": dict(Counter((r["printed"] or {}).get("class") for r in rows)),
                      "unused_docs (group 'show': answered row by row through printed.json and section I)": unused}))
    (HERE / "decisions.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
