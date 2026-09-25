"""Build classes001-proposals.json and needs-spotcheck.json (batch classes001).

Inputs (regenerated over the current cdl.bib and cache by regen.py):
  proposals.json            article proposals (fixes-2026-09-24 schema, with stated_by)
  catalogue/proposals.json  catalogue proposals (catalogue-phase0 schema, one row per field)
Approved versions (spot-checked rule outputs):
  verification/fixes-2026-09-24/proposals.json
  verification/catalogue-phase0-2026-09-22/proposals.json

A regenerated proposal is applied only when
  * its class is user-approved (APPROVED_ARTICLE / APPROVED_CATALOGUE),
  * an approved proposal exists for the same key with IDENTICAL changes,
  * its fingerprint is the entry's current fingerprint, and
  * no stage-1 guard holds it: no page range is shortened
    (correction_proposals.shortens_pages), no name suffix is written, and every
    surname change passes correction_proposals.surname_change_hold (a second
    source counts as corroboration only for article proposals whose author value
    is stated by two sources; the catalogue is one source).
New or changed proposals of any class go to needs-spotcheck.json. Proposals that
change ``year`` are applied only for the two user-approved renames
(GautEtal18 -> GautEtal19, HayeEtal14 -> HayeEtal16); any other year change is held
because the cite key encodes the year.

    .venv/bin/python verification/apply-2026-09-26/select_classes.py
"""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import correction_proposals as cp  # noqa: E402
from verification import load_entries  # noqa: E402

APPROVED_ARTICLE = {"A1b-ARTICLE-NUMBER", "S1-AUTHOR-SURNAME", "S1-COORDINATES", "S1-JOURNAL-HISTORY-OR-TYPO",
                    "S1-JOURNAL-REPLACEMENT", "S1-TITLE-CORROBORATED", "S1-TITLE-CROSSREF-ONLY", "TWO-SOURCE",
                    "S1-AUTHOR-NAMES", "S1-PAGES-COMPLETE", "S1-TWO-FIELDS", "S1-TWO-FIELDS-RISKY"}
APPROVED_CATALOGUE = {"A1", "A2", "D", "E", "L", "P2", "T", "Y"}
RENAMES = {"GautEtal18": "GautEtal19", "HayeEtal14": "HayeEtal16"}
SUFFIX = re.compile(r"(^|\s|,)(Jr|Sr|II|III|IV)\.?(,|\s|$)")


def cat_class(label):
    return label.split(" ", 1)[0]


def catalogue_by_key(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["key"]].append(r)
    return out


def catalogue_proposal(key, rows):
    changes = {r["field"]: {"before": r["before"], "after": r["after"]} for r in rows}
    assert len(changes) == len(rows), f"{key}: two catalogue rows for one field"
    classes = sorted({cat_class(r["class"]) for r in rows})
    return {"key": key, "fingerprint": rows[0]["fingerprint"], "kind": "catalogue", "class": "+".join(classes),
            "catalogue_classes": classes, "rules": sorted({r["rule"] for r in rows}),
            "source": "loc-catalogue", "changes": changes,
            "stated_by": {r["field"]: [f"loc-catalogue:{r['source_record_id']}"] for r in rows},
            "catalogue_url": sorted({r.get("catalogue_url") for r in rows if r.get("catalogue_url")})}


def guard(p, catalogue):
    """Reason a stage-1 guard holds the proposal, or None."""
    for field, change in p["changes"].items():
        if field == "pages" and change["before"] and change["after"] and cp.shortens_pages(change["before"], change["after"]):
            return f"pages: shortens {change['before']} -> {change['after']}"
        if field in ("author", "editor") and change["after"]:
            if SUFFIX.search(change["after"]) and not SUFFIX.search(change["before"] or ""):
                return f"{field}: writes a name suffix"
            sources = {s.split(":")[0] for s in (p.get("stated_by") or {}).get(field, [])}
            corroborated = not catalogue and len(sources) >= 2
            hold = cp.surname_change_hold(p["key"], change["before"], change["after"], corroborated=corroborated)
            if hold:
                return hold
        # House-form rules decided after the catalogue spot-check (resolution plan,
        # 2026-09-24/25): initials everywhere, editions as N\textsuperscript{th}.
        if field in ("author", "editor") and change["after"]:
            for name in change["after"].split(" and "):
                tokens = name.split()
                if len(tokens) > 1 and re.fullmatch(r"[A-Z][a-z]+", tokens[0]):
                    return f"{field}: full given name {tokens[0]!r} (house form uses initials)"
        if field == "edition" and change["after"] and re.fullmatch(r"\d+", change["after"]):
            return f"edition: {change['after']!r} is not the house form N\\textsuperscript{{..}}"
        if field in ("title", "booktitle") and change["after"] and " : " in change["after"]:
            return f"{field}: catalogue ISBD separator ' : ' left in the title"
        if field == "year" and p["key"] not in RENAMES:
            return "year change requires a cite-key rename (not user-approved for this key)"
    return None


def formatter_filter(entries, proposals):
    import importlib.util
    import tempfile
    spec = importlib.util.spec_from_file_location("apply0926", HERE / "apply.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    from helpers import check_bib
    held = []
    while True:
        text = (ROOT / "cdl.bib").read_text()
        for p in proposals:
            raw = entries[p["key"]]["raw"]
            new = runner.base.apply_change_all(raw, p)
            if p.get("rename"):
                new = runner.rename_key(new, p["key"], p["rename"])
            text = text.replace(raw, new, 1)
        with tempfile.NamedTemporaryFile("w", suffix=".bib", dir=runner.WORK, delete=False) as f:
            f.write(text)
        errors, _ = check_bib(f.name, verbose=False)
        Path(f.name).unlink()
        if not errors:
            return proposals, held
        by_new = {p.get("rename", p["key"]): p for p in proposals}
        unknown = sorted(set(errors) - set(by_new))
        assert not unknown, f"check_bib errors outside the batch: {unknown}"
        for key, demand in errors.items():
            p = by_new[key]
            held.append({"key": p["key"], "class": p["class"], "changes": p["changes"],
                         "stated_by": p.get("stated_by"),
                         "reason": "check_bib (house formatter) demands " + json.dumps(demand, ensure_ascii=False)})
        proposals = [p for p in proposals if p.get("rename", p["key"]) not in errors]


def main():
    entries = load_entries(ROOT / "cdl.bib")
    regen = json.loads((HERE / "proposals.json").read_text())["proposals"]
    approved = {p["key"]: p for p in json.loads((ROOT / "verification/fixes-2026-09-24/proposals.json").read_text())["proposals"]}
    cat_regen = catalogue_by_key(json.loads((HERE / "catalogue/proposals.json").read_text())["proposals"])
    cat_approved = catalogue_by_key(json.loads(
        (ROOT / "verification/catalogue-phase0-2026-09-22/proposals.json").read_text())["proposals"])

    apply, spot, held, unapproved = [], [], [], []
    for p in regen:
        a = approved.get(p["key"])
        row = {"key": p["key"], "class": p["class"], "changes": p["changes"], "stated_by": p.get("stated_by")}
        if not a or a["changes"] != p["changes"]:
            spot.append(dict(row, status="new" if not a else "changed",
                             approved_changes=a["changes"] if a else None,
                             approved_class=a["class"] if a else None, doi=p.get("doi")))
            continue
        if a["class"] not in APPROVED_ARTICLE or p["class"] not in APPROVED_ARTICLE:
            unapproved.append(dict(row, reason=f"class {a['class']}/{p['class']} not approved"))
            continue
        if p["fingerprint"] != entries[p["key"]]["fingerprint"]:
            held.append(dict(row, reason="fingerprint differs from the current entry"))
            continue
        why = guard(p, catalogue=False)
        if why:
            held.append(dict(row, reason=why))
            continue
        out = dict(p, approved_in="verification/fixes-2026-09-24/proposals.json")
        if p["key"] in RENAMES:
            out["rename"] = RENAMES[p["key"]]
        apply.append(out)

    for key, rows in sorted(cat_regen.items()):
        p = catalogue_proposal(key, rows)
        a = cat_approved.get(key)
        a_changes = {r["field"]: {"before": r["before"], "after": r["after"]} for r in a} if a else None
        row = {"key": key, "class": p["class"], "changes": p["changes"], "stated_by": p["stated_by"]}
        if a_changes != p["changes"]:
            spot.append(dict(row, status="new" if not a else "changed", approved_changes=a_changes,
                             approved_class="+".join(sorted({cat_class(r["class"]) for r in a})) if a else None))
            continue
        if not set(p["catalogue_classes"]) <= APPROVED_CATALOGUE:
            unapproved.append(dict(row, reason=f"catalogue class {p['class']} not approved"))
            continue
        if p["fingerprint"] != entries[key]["fingerprint"]:
            held.append(dict(row, reason="fingerprint differs from the current entry"))
            continue
        why = guard(p, catalogue=True)
        if why:
            held.append(dict(row, reason=why))
            continue
        apply.append(dict(p, approved_in="verification/catalogue-phase0-2026-09-22/proposals.json"))

    # helpers.check_bib (the house formatter) must accept every edited entry; an edit it
    # would reformat or that changes the key the ID rule demands (first author, author
    # count, editor-only books) is held with the formatter's demand as the reason.
    apply, formatter_held = formatter_filter(entries, apply)
    held += formatter_held
    for h in formatter_held:
        print("HELD", h["key"], h["class"], h["reason"])
    keys = [p["key"] for p in apply]
    assert len(keys) == len(set(keys)), "a key has both an article and a catalogue proposal"
    missing = sorted(set(RENAMES) - set(keys))
    for old, new in RENAMES.items():
        assert new not in entries, f"{new} is already a cite key"
    by_class = Counter(p["class"] for p in apply)
    (HERE / "classes001-proposals.json").write_text(json.dumps({
        "batch": "classes001", "count": len(apply), "by_class": dict(sorted(by_class.items())),
        "renames": {k: v for k, v in RENAMES.items() if k in keys}, "renames_not_applied": missing,
        "skipped": {"guard_or_fingerprint": held, "class_not_approved": unapproved},
        "proposals": apply}, indent=1, ensure_ascii=False) + "\n")
    spot_classes = Counter(s["class"] for s in spot)
    (HERE / "needs-spotcheck.json").write_text(json.dumps({
        "count": len(spot), "by_class": dict(sorted(spot_classes.items())),
        "by_status": dict(Counter(s["status"] for s in spot)), "proposals": spot}, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"apply": len(apply), "by_class": by_class, "held": len(held), "class_not_approved": len(unapproved),
                      "needs_spotcheck": len(spot), "spot_by_class": spot_classes, "renames_not_applied": missing},
                     default=dict, indent=1))
    for h in held:
        print("HELD", h["key"], h["class"], h["reason"])


if __name__ == "__main__":
    main()
