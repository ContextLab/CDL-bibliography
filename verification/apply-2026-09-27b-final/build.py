"""Build <batch>-proposals.json for the final apply (2026-09-27): the
resolution batches 27-39 (``verification/resolution-2026-09-26/batch-27.json`` .. ``batch-39.json``),
which are not wave rows (``"wave": null``), applied directly against the CURRENT cdl.bib entry, and the
fields that ``helpers.check_bib`` used to reject in waves 2-9 (``../apply-2026-09-27-waves2-9/build.py``
``HELD``), now accepted by the formatter of 9f84506.

Batches (one commit each):  res27 (batch 27), res28to33 (batches 28-33), res34to39 (batches 34-39 and the
held forms of entries no batch row names).

Rules:
- decision ``apply``: every ``set`` value is checked with ``postcheck.resolution_quote`` (the research
  validator: each quote found at its URL, the value's words in the quotes, the user's inference rules).
  A value that fails is applied only when the row's notes say it was read in a browser or transcribed
  from a scan (``postcheck.BROWSER_OR_SCAN``); it is then flagged. Any other failure is reported and the
  field is left unchanged. The value is put in house form with the post-check's own normalisers (names:
  ``normalise_names`` and ``house_surname``; em dash ``a---b``; issue ranges, pages, proceedings
  booktitles, editions, US addresses and unprinted countries, DOI case, title / journal / publisher
  formatter forms guarded, ordinals). ``remove`` drops fields, ``entrytype`` sets the type. ``withdraw``
  names research proposals of the waves (already applied or not); it changes nothing here.
- decision ``drop``: the entry is deleted (never KahaEtal08b or JacoEtal05b; a key already absent or in
  key-deletions.json is a no-op). ElliAshb88 is kept: batch 18 (reconciled) wins over batch 30
  (resolution-plan README, "NOTE for final apply").
- decision ``keep``: nothing.
- Keys: the key plan follows the house rules. After the batch, every entry's key must equal
  ``helpers.authors2key`` of its (author or editor, year), with the suffix rule. When an entry's key base
  changes, it takes the new base; when that base is already used, the existing entries keep their order
  and take the first suffixes and the moved entry the next one (Buzs01 -> Buzs02b, the existing Buzs02
  -> Buzs02a; resolution-plan README default). A row's ``new_key`` must agree with the plan. Keys that
  cdl.bib renamed since the row was written are followed through ``verification/key-renames.json``.
- Conflicts: a key decided in an earlier resolution batch (01-26) and again here: the later row wins
  (it was written against the current entry, after the earlier batch was applied), except ElliAshb88.
  Every field where the two rows set different values is listed under ``conflicts``.

    .venv/bin/python verification/apply-2026-09-27b-final/build.py res27 [--offline]
"""
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
sys.path.insert(0, str(ROOT / "verification/research-2026-09-25"))
from verification import load_entries  # noqa: E402
import helpers as H  # noqa: E402
import postcheck as pc  # noqa: E402

RESOLUTIONS = ROOT / "verification/resolution-2026-09-26"
BATCHES = {"res27": (27,), "res28to33": tuple(range(28, 34)), "res34to39": tuple(range(34, 40))}
ORDER = tuple(BATCHES)
NEVER_REMOVE = {"KahaEtal08b", "JacoEtal05b"}
WORK = ROOT / ".bibcheck" / HERE.name

# Rows whose decision is overridden by the user's notes: key -> (decision, reason).
OVERRIDE = {
    "ElliAshb88": ("keep", "resolution-plan-2026-09-22/README.md, NOTE for final apply: batch 18 (reconciled) keeps "
                           "it because Google's full text of the book itself shows the chapter title (p. 33); batch 30 "
                           "drops it on reference-list grounds. The book's own text is primary evidence: keep (batch 18 "
                           "wins)"),
}
# Values set outside the resolution batches: (key, field) -> {value, source, evidence}.
EXTRA_SET = {
    ("HeniEtal19", "pages"): {
        "value": "ENEURO.0306-19.2019",
        "source": "verification/resolution-2026-09-27/NOTICES.md (HeniEtal19 coordinate_conflict: 'pages missing; "
                  "Crossref=PubMed=PMC give ENEURO.0306-19.2019, so add it'); wave3 merged.json final change, held in "
                  "waves 2-9 because check_bib rejected the eLocator (accepted since 9f84506)"},
}
# The 15 fields check_bib rejected in waves 2-9 (../apply-2026-09-27-waves2-9/build.py HELD). Each is applied
# from the wave's final change, unless a batch row here sets the field (the later row wins), or check_bib
# still rejects it (STILL_REJECTED, with the reason).
STILL_REJECTED = {
    ("Youn12", "url"): "url is not a house field (bibcheck/keep_fields.txt; check_bib 'non-essential fields'); 9f84506 "
                       "did not change that",
}

# check_bib house forms of approved values (the waves 2-9 HOUSE_FORM rule): (key, field) -> value. The
# formatter strips the braces of a fully braced title ("{CELEX2}" -> "Celex2"; the braced-first fixed point,
# as "{B}{ASIC}" in wave 8), turns "(f)" into "({F})" (braced lowercase, as "(1993{a})" in wave 4), and keeps a
# braced word exactly as given since 9f84506 ("{PMLR}", "{eNeuro}").
HOUSE_FORM = {
    ("BaayEtal95", "title"): "{C}{ELEX2}",
    ("RangEtal14", "publisher"): "{PMLR}",
    ("HeniEtal19", "journal"): "{eNeuro}",
}
# Approved changes check_bib still rejects in every form tried: (key, field) -> reason. The field stays as
# in HEAD.
HOLD_CHANGE = {
    ("FoodAdmi20a", "force"): "removing Force exposes the group author '{U.S. Food and Drug Administration}', which "
                              "the author formatter splits at ' and ' ('{ U S Food and Drug Administration}'); "
                              "'{U.S. Food {and} Drug Administration}' survives the formatter but changes the key "
                              "base, so Force stays (the wave-1 FoodAdmi20a case); the howpublished fix is applied",
    ("FoodAdmi20b", "force"): "as FoodAdmi20a: removing Force exposes the same group author (and the title's '(f)'); "
                              "Force stays; the howpublished fix is applied",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rows_of(n):
    path = RESOLUTIONS / f"batch-{n:02d}.json"
    return path, [dict(r, _batch=path.stem) for r in json.loads(path.read_text())]


def held_items():
    """[(src wave, key, field, proposed)] of the waves 2-9 HELD fields, from the frozen merged.json files the
    waves 2-9 batches read (the re-run post-check first)."""
    w29 = load_module("waves29build", ROOT / "verification/apply-2026-09-27-waves2-9/build.py")
    out = []
    for (src, key, field) in w29.HELD:
        proposed = None
        for base in (w29.POSTCHECK_INPUTS, w29.INPUTS):
            path = base / src / "merged.json"
            if not path.exists():
                continue
            for r in json.loads(path.read_text()):
                if key in (r["key"], r["key_plan"]["current_key"]):
                    for c in r["final_changes"]:
                        if c["field"] == field:
                            proposed = c
            if proposed:
                break
        assert proposed, (src, key, field)
        out.append((src, key, field, proposed))
    return out


def follow(key, entries, renames, deleted):
    chain, cur = [key], key
    while cur not in entries and cur not in deleted and cur in renames and renames[cur] not in chain:
        cur = renames[cur]
        chain.append(cur)
    return (cur, chain) if len(chain) > 1 and cur in entries else (key, [])


def house_form(field, value, current, bib, cities, quotes):
    """The post-check's house normalisation of a resolution value. Returns (value, notes, flags)."""
    notes, flags = [], []
    v = str(value)

    def put(new, why):
        nonlocal v
        if why and new != v:
            notes.extend(why)
            v = new

    if field in pc.NAME_FIELDS:
        new, why = pc.normalise_names(v)
        bad = [n for n in why if "could not parse" in n or "cannot parse" in n]
        flags += [f"name_unparsed: {b}" for b in bad]
        put(new, [n for n in why if n not in bad])
        names, why = [], []
        for n in pc.split_names(v):
            hn, note = pc.house_surname(n, bib, exclude=current)
            names.append(hn)
            if note:
                why.append(note)
        put(" and ".join(names), why)
        return v, notes, flags
    if field in ("title", "booktitle"):
        put(*pc.normalise_emdash(v))
    if field == "number":
        put(*pc.normalise_number(v))
    elif field == "pages":
        put(*pc.normalise_pages(v))
    elif field == "booktitle":
        put(*pc.normalise_booktitle(v))
    elif field == "edition":
        put(*pc.normalise_edition(v))
    elif field == "address":
        ac = pc.address_country(v)
        if ac and not pc.country_printed(ac[2], quotes):
            if not ac[0]:
                return None, notes + [f"address {v!r} is only a country that no quote prints: left out"], \
                    flags + ["country_dropped"]
            flags.append(f"country_dropped: {v!r} -> {ac[0]!r}")
            put(ac[0], [f"country {ac[1]!r} not printed by any quote"])
        new, why, problems = pc.normalise_address(v, cities)
        flags += [f"us_address_state_unknown: {p}" for p in problems]
        added = pc.address_country(new) if new != v else None
        if added and added[0] and not pc.country_printed(added[2], quotes):
            why = [n for n in why if "house form" not in n] + [f"house address form {new!r} adds an unprinted country"]
            new = added[0]
        put(new, why)
    elif field == "doi":
        put(pc.clean_doi(v), ["doi lowercased"])
    elif field == "title":
        try:
            ft = pc.guarded(v, H.format_title(v))
        except Exception as err:  # format_title raises bare Exception on unbalanced braces
            flags.append(f"title_unformattable: {err}")
            ft = None
        if ft:
            put(ft, [f"title house form: {v!r} -> {ft!r}"])
    elif field == "journal":
        fj = pc.guarded(v, H.format_journal_name(v))
        if fj:
            put(fj, [f"journal house form: {v!r} -> {fj!r}"])
    elif field == "publisher":
        fp = pc.guarded(v, H.format_journal_name(v, key=H.publisher_key, dotted_initials=True))
        if fp:
            put(fp, [f"publisher house form: {v!r} -> {fp!r}"])
    if field in pc.ORDINAL_FIELDS and field not in ("booktitle", "edition"):
        put(*pc.normalise_ordinals(v))
    return v, notes, flags


def stage_text(text, entries, proposals, edit_raw):
    """cdl.bib after the proposals' edits and removals (renames not yet planned)."""
    out = text
    for p in proposals:
        raw = entries[p["key"]]["raw"]
        if p["kind"] == "remove":
            target = raw + "\n\n" if out.count(raw + "\n\n") == 1 else "\n\n" + raw
            out = out.replace(target, "", 1)
        else:
            out = out.replace(raw, edit_raw(raw, dict(p, rename=None)), 1)
    return out


def key_plan(staged_text, changed_keys):
    """{old: new} so that every key obeys helpers' base and suffix rules after the batch; entries whose key
    base the batch moves (changed_keys) come after the existing entries of their new base."""
    with tempfile.NamedTemporaryFile("w", suffix=".bib", dir=WORK, delete=False) as tmp:
        tmp.write(staged_text)
    try:
        bd = H.load_bibliography(tmp.name, verbose=False)
    finally:
        Path(tmp.name).unlink()
    ids = H.get_vals(bd, "ID")
    bases = [H.authors2key(a, y) for a, y in zip(H.key_names(bd), H.get_vals(bd, "year"))]
    targets = H.check_key_suffixes(bd)
    # a key exempt by bibcheck's key overrides (check_entries) is never bad
    # (check_entries also skips an entry with a Force field)
    bad = {i for i, t in zip(ids, targets) if i != t and H.key_overrides.get(i) != t and "force" not in bd[i]}

    def of_base(m, b):
        return m == b or (m.startswith(b) and re.fullmatch(r"[a-z]+", m[len(b):]) is not None)

    groups = {}
    for i, b in zip(ids, bases):
        groups.setdefault(b, []).append(i)
    plan = {}
    for b, members in groups.items():
        if not any(m in bad for m in members):
            continue
        moved = [m for m in members if not of_base(m, b)]
        assert all(m in changed_keys for m in moved), (b, moved)
        stay = sorted((m for m in members if m not in moved), key=lambda m: (len(m), m))
        order = stay + moved
        new = [b] if len(order) == 1 else [b + s for s in H.get_key_suffixes(len(order))]
        for old, nk in zip(order, new):
            if old != nk:
                plan[old] = nk
    return plan


def check_bib_forms(text, entries, proposals, edit_raw):
    """helpers.check_bib on the staged batch (after HOUSE_FORM and HOLD_CHANGE). A changed field whose
    formatter form is the value as cited is not changed (the waves 2-9 rule: "the value as cited: no
    change"); any other rejection is held (the field stays as in HEAD) and listed, and the batch must then
    stage clean. Returns (house, rejected)."""
    from helpers import check_bib
    house, rejected = [], []
    for _ in range(4):
        staged = text
        for p in proposals:
            raw = entries[p["key"]]["raw"]
            if p["kind"] == "remove":
                target = raw + "\n\n" if staged.count(raw + "\n\n") == 1 else "\n\n" + raw
                staged = staged.replace(target, "", 1)
            else:
                staged = staged.replace(raw, edit_raw(raw, p), 1)
        path = WORK / f"build-check-{time.time_ns()}.bib"
        path.write_text(staged)
        errors, _ = check_bib(str(path), verbose=False)
        path.unlink()
        if not errors:
            return house, rejected
        by_new = {p.get("rename") or p["key"]: p for p in proposals if p["kind"] == "edit"}
        for k, errs in errors.items():
            p = by_new.get(k)
            assert p is not None, f"check_bib rejects {k}, which this batch does not edit: {errs}"
            for field, want in errs.items():
                field = field.lower()
                assert field != "id", (k, errs)
                ch = p["changes"].get(field)
                before = entries[p["key"]]["fields"].get(field)
                if ch is not None and ch["after"] is not None and want == before:
                    house.append({"key": p["key"], "field": field, "value": ch["after"], "applied": want,
                                  "note": "the formatter's form is the value as cited: no change"})
                    del p["changes"][field]
                    continue
                rejected.append({"key": p["key"], "field": field, "value": None if ch is None else ch["after"],
                                 "formatter": want, "stays": before,
                                 "note": "unchanged value exposed by the batch" if ch is None else ""})
                if ch is not None:
                    del p["changes"][field]
    raise SystemExit(f"check_bib still rejects the staged batch: {rejected} {errors}")


def apply_manual_forms(proposals, entries):
    """HOUSE_FORM and HOLD_CHANGE on the built proposals; returns (house, held) rows for the report."""
    house, held = [], []
    for p in proposals:
        if p["kind"] != "edit":
            continue
        for field in list(p["changes"]):
            ch = p["changes"][field]
            if (p["key"], field) in HOLD_CHANGE:
                held.append({"key": p["key"], "field": field, "value": ch["after"], "stays": ch["before"],
                             "why": HOLD_CHANGE[p["key"], field]})
                del p["changes"][field]
            elif (p["key"], field) in HOUSE_FORM and ch["after"] is not None:
                form = HOUSE_FORM[p["key"], field]
                house.append({"key": p["key"], "field": field, "value": ch["after"], "applied": form,
                              "note": "the value as cited: no change" if form == ch["before"] else "house form"})
                if form == ch["before"]:
                    del p["changes"][field]
                else:
                    ch.setdefault("proposed", ch["after"])
                    ch["after"], ch["house_form"] = form, "check_bib"
    return house, held

    raise SystemExit(f"check_bib still rejects the staged batch: {errors}")


def main():
    batch = sys.argv[1]
    offline = "--offline" in sys.argv
    assert batch in BATCHES, batch
    WORK.mkdir(parents=True, exist_ok=True)
    applyer = load_module("final_apply", HERE / "apply.py")
    edit_raw = applyer.runner.edit_raw
    entries = load_entries(ROOT / "cdl.bib")
    text = (ROOT / "cdl.bib").read_text()
    bib = pc.load_bib(ROOT / "cdl.bib")
    cities = pc.city_states(bib)
    renames = {r["old_key"]: r["new_key"] for r in json.loads((ROOT / "verification/key-renames.json").read_text())}
    deleted = {d["key"] for d in json.loads((ROOT / "verification/key-deletions.json").read_text())}

    early = {}
    for n in range(1, 27):
        for r in rows_of(n)[1]:
            early.setdefault(r["key"], []).append(r)
    inputs, rows = [], []
    for n in BATCHES[batch]:
        path, rs = rows_of(n)
        inputs.append({"file": str(path.relative_to(ROOT)), "sha256": sha256(path), "rows": len(rs)})
        rows += rs
    later_batches = [n for b in ORDER[ORDER.index(batch) + 1:] for n in BATCHES[b]]
    later_keys = {r["key"] for n in later_batches for r in rows_of(n)[1]}
    held = [h for h in held_items()]

    proposals, skipped, noops, failed, flags, conflicts, notes_out, followed = [], {}, {}, {}, {}, [], {}, {}
    questions = {}
    for r in rows:
        k0 = r["key"]
        key, chain = follow(k0, entries, renames, deleted)
        if chain:
            followed[k0] = " -> ".join(chain)
        decision, why_override = r["decision"], None
        if k0 in OVERRIDE:
            decision, why_override = OVERRIDE[k0]
            conflicts.append({"key": k0, "field": "(decision)", "rows": [
                {"batch": e["_batch"], "decision": e["decision"]} for e in early.get(k0, [])] +
                [{"batch": r["_batch"], "decision": r["decision"]}], "resolved": decision, "why": why_override})
        if r.get("questions"):
            questions[k0] = r["questions"]
        for e in early.get(k0, []):
            for f, spec in (r.get("set") or {}).items():
                es = (e.get("set") or {}).get(f)
                if es is not None and str((es if isinstance(es, dict) else {"value": es}).get("value")) != \
                        str(spec.get("value")):
                    conflicts.append({"key": k0, "field": f, "rows": [
                        {"batch": e["_batch"], "value": (es if isinstance(es, dict) else {"value": es}).get("value")},
                        {"batch": r["_batch"], "value": spec.get("value")}],
                        "resolved": r["_batch"], "why": "the later row, written against the current entry (after "
                                                        f"{e['_batch']} was applied), wins"})
            if e.get("decision") != decision and k0 not in OVERRIDE:
                conflicts.append({"key": k0, "field": "(decision)", "rows": [
                    {"batch": e["_batch"], "decision": e["decision"]}, {"batch": r["_batch"], "decision": decision}],
                    "resolved": r["_batch"], "why": "the later row wins"})
        if decision == "keep":
            skipped[k0] = "decision keep" + (f" ({why_override})" if why_override else "")
            continue
        if decision == "drop":
            if key not in entries or key in deleted:
                assert key not in entries or key in deleted
                noops[k0] = "drop: " + ("already deleted (key-deletions.json)" if key in deleted else "not in cdl.bib")
                continue
            assert key not in NEVER_REMOVE, key
            proposals.append({"key": key, "fingerprint": entries[key]["fingerprint"], "kind": "remove",
                              "reason": r.get("drop_reason") or r.get("notes") or "",
                              "decision": f"verification/resolution-2026-09-26/{r['_batch']}.json (drop): {r.get('notes', '')}",
                              **({"row_key": k0} if key != k0 else {})})
            continue
        assert decision == "apply", (k0, decision)
        assert key in entries, (k0, key)
        fields = entries[key]["fields"]
        current = bib[key]
        lenient = pc.BROWSER_OR_SCAN.search(str(r.get("notes") or ""))
        changes = {}
        for f, spec in (r.get("set") or {}).items():
            f = f.lower()
            spec = spec if isinstance(spec, dict) else {"value": spec}
            if spec.get("value") in (None, "") or not str(spec["value"]).strip():
                failed[f"{key}.{f}"] = "the set has no value"
                continue
            q = pc.resolution_quote(f, spec, offline=offline)
            if not q["ok"]:
                if q.get("refused") or not lenient:
                    failed[f"{key}.{f}"] = f"{spec['value']!r}: {q['why']}" + ("" if q.get("refused") else
                                                                              " (notes say no browser read or scan)")
                    continue
                flags.setdefault(key, []).append(
                    f"resolution_quote_unverified: {f} = {spec['value']!r}: {q['why']}; applied: the notes say it "
                    f"was read in a browser or transcribed from a scan ({lenient[0]!r}; user rule)")
            if q.get("rule"):
                flags.setdefault(key, []).append(f"resolution_inferred_value: {f} = {spec['value']!r}: {q['rule']}")
            quotes = [i["quote"] for i in pc.evidence_items(spec)]
            value, why, fl = house_form(f, spec["value"], current, bib, cities, quotes)
            if why:
                notes_out.setdefault(key, []).extend(f"{f}: {w}" for w in why)
            if fl:
                flags.setdefault(key, []).extend(f"{f}: {x}" for x in fl)
            before = fields.get(f)
            if value is None:
                if before is not None:
                    changes[f] = {"before": before, "after": None, "reason": "; ".join(why)}
                continue
            if value != before:
                changes[f] = {"before": before, "after": value, "source": f"resolution {r['_batch']}",
                              "evidence": pc.evidence_items(spec) +
                              ([dict(spec["next_start"], role="next_start")] if spec.get("next_start") else []),
                              **({"proposed": spec["value"]} if value != str(spec["value"]) else {})}
        for f in r.get("remove") or []:
            f = f.lower()
            if f in changes:
                raise SystemExit(f"{key}: {f} both set and removed")
            if f in fields:
                changes[f] = {"before": fields[f], "after": None, "reason": f"resolution {r['_batch']} remove"}
        if r.get("entrytype"):
            et, why, err = pc.normalise_entrytype(r["entrytype"])
            assert not err, (key, err)
            if et != fields["ENTRYTYPE"]:
                changes["ENTRYTYPE"] = {"before": fields["ENTRYTYPE"], "after": et, "source": f"resolution {r['_batch']}"}
        row = {"key": key, "fingerprint": entries[key]["fingerprint"], "kind": "edit",
               "origin": f"resolution {r['_batch']} (apply)", "changes": changes}
        if key != k0:
            row["row_key"] = k0
        if r.get("new_key"):
            row["_new_key_hint"] = r["new_key"]
        proposals.append(row)

    # The fields check_bib used to reject (waves 2-9 HELD), for keys of this batch (res34to39 also takes
    # those of keys no batch row names).
    by_key = {p["key"]: p for p in proposals}
    batch_row_keys = {r["key"] for r in rows}
    all_row_keys = {r["key"] for n in range(27, 40) for r in rows_of(n)[1]}
    held_report = []
    for src, hk, field, c in held:
        mine = hk in batch_row_keys or (batch == ORDER[-1] and hk not in all_row_keys)
        if not mine:
            continue
        item = {"wave": src, "key": hk, "field": field, "proposed": c["proposed"]}
        if (hk, field) in STILL_REJECTED:
            item["outcome"] = "still rejected: " + STILL_REJECTED[hk, field]
            held_report.append(item)
            continue
        row = next((r for r in rows if r["key"] == hk), None)
        if row and field in {f.lower() for f in (row.get("set") or {})} | {f.lower() for f in row.get("remove") or []}:
            spec = (row.get("set") or {}).get(field)
            after = by_key.get(hk, {}).get("changes", {}).get(field, {}).get("after", entries[hk]["fields"].get(field))
            item["outcome"] = f"the batch row ({row['_batch']}) decides it: {after!r}"
            if spec is not None and str(spec.get("value")) != str(c["proposed"]):
                conflicts.append({"key": hk, "field": field, "rows": [
                    {"batch": f"{src} merged.json (held)", "value": c["proposed"]},
                    {"batch": row["_batch"], "value": spec.get("value")}], "resolved": row["_batch"],
                    "why": "the later resolution row, written against the current entry, wins"})
            held_report.append(item)
            continue
        extra = EXTRA_SET.get((hk, field))
        value = extra["value"] if extra else c["proposed"]
        before = entries[hk]["fields"].get(field)
        if row is None and hk in later_keys:
            continue
        if value == before:
            item["outcome"] = "already in the entry"
            held_report.append(item)
            continue
        p = by_key.get(hk)
        if p is None:
            p = {"key": hk, "fingerprint": entries[hk]["fingerprint"], "kind": "edit",
                 "origin": f"{src} merged.json final change held in waves 2-9 by check_bib (accepted since 9f84506)",
                 "changes": {}}
            proposals.append(p)
            by_key[hk] = p
        p["changes"][field] = {"before": before, "after": value,
                               "source": extra["source"] if extra else f"{src} merged.json final change "
                               f"({c.get('source')}), held in waves 2-9 by check_bib", "evidence": c.get("evidence", [])}
        if hk == "KingEtal11" and field == "author":
            pass  # its key follows the author (key plan below): MorrRNSS11
        item["outcome"] = f"applied: {value!r}"
        held_report.append(item)

    for p in proposals:
        if p["kind"] == "edit" and not p["changes"] and not p.get("_new_key_hint"):
            skipped[p.get("row_key", p["key"])] = "no change: every set value equals the entry (evidence only)"
    proposals = [p for p in proposals if p["kind"] == "remove" or p["changes"] or p.get("_new_key_hint")]

    # key plan
    staged = stage_text(text, entries, proposals, edit_raw)
    changed = {p["key"] for p in proposals if p["kind"] == "edit"}
    plan = key_plan(staged, changed)
    by_key = {p["key"]: p for p in proposals}
    key_mismatch = {}
    for p in proposals:
        hint = p.pop("_new_key_hint", None)
        if hint and plan.get(p["key"]) != hint:
            key_mismatch[p["key"]] = f"row new_key {hint!r}, key plan {plan.get(p['key'])!r}"
    for old, new in sorted(plan.items()):
        assert old in entries, old
        if old in by_key:
            by_key[old]["rename"] = new
            by_key[old]["rename_reason"] = "house key rule (authors2key of author/editor and year, suffix rule)"
        else:
            p = {"key": old, "fingerprint": entries[old]["fingerprint"], "kind": "edit", "changes": {}, "rename": new,
                 "origin": "house suffix rule (helpers.check_key_suffixes) after this batch",
                 "rename_reason": "suffix rule: another entry moves to this key base"}
            proposals.append(p)
            by_key[old] = p
    manual_house, held_changes = apply_manual_forms(proposals, entries)
    house, rejected = check_bib_forms(text, entries, proposals, edit_raw)
    house = manual_house + house
    proposals = [p for p in proposals if p["kind"] == "remove" or p["changes"] or p.get("rename")]
    for p in proposals:
        if p["kind"] == "remove" or p.get("rename"):
            outside = text.replace(entries[p["key"]]["raw"], "", 1)
            assert not re.search(r"[{,=\s]" + re.escape(p["key"]) + r"[},\s]", outside), f"{p['key']} referenced elsewhere"
    assert len({p["key"] for p in proposals}) == len(proposals)

    out = {"batch": batch, "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "input": inputs,
           "count": len(proposals),
           "counts": {kind: sum(p["kind"] == kind for p in proposals) for kind in ("edit", "remove")},
           "renames": {p["key"]: p["rename"] for p in proposals if p.get("rename")},
           "key_mismatch": key_mismatch, "followed_renames": followed, "noops": noops, "skipped": skipped,
           "set_not_applied": failed, "house_form_check_bib": house, "check_bib_rejects": rejected,
           "held_changes": held_changes, "flags": flags, "conflicts": conflicts, "held_forms": held_report,
           "questions": questions, "normalised": notes_out, "proposals": proposals}
    (HERE / f"{batch}-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: out[k] for k in ("count", "counts", "renames", "key_mismatch", "noops", "set_not_applied")},
                     ensure_ascii=False))
    print(f"skipped {len(skipped)} conflicts {len(conflicts)} flags {sum(map(len, flags.values()))} "
          f"held_forms {len(held_report)} questions {len(questions)}")


if __name__ == "__main__":
    main()
