"""Build <wave>-proposals.json for one research wave (2..9): the post-checked final changes of every
ready row, and the removal of every entry the post-check marked ``remove_entry``.

Input: ``verification/research-2026-09-25/<wave>/merged.json`` as frozen on 2026-09-26 22:29 ET in
``.bibcheck/apply-2026-09-29-waves2-9/inputs/<wave>/merged.json`` (its sha256 is recorded in the
proposals). The post-check read HEAD cdl.bib (after the wave-1 apply) and the resolution batches
``verification/resolution-2026-09-26/batch-*.json`` as committed.
Batches ``wave2to4`` and ``wave5`` .. ``wave9`` read instead the re-run post-check (93ae192, against cdl.bib
after waves 2-4), frozen on 2026-09-27 in ``.bibcheck/apply-2026-09-29-waves2-9/inputs-93ae192/``.

Rules:
- ``needs_user`` true: not touched (the entry stays exactly as in HEAD; listed under ``held_rows``).
- ``remove_entry`` set: the entry is removed, unless the post-check marked the drop a no-op
  (``resolution.noop``: already absent, or a reused key listed in verification/key-deletions.json).
  KahaEtal08b and JacoEtal05b are never removed (they now name other works).
- ready (``needs_user`` false, no ``remove_entry``): every ``final_changes`` value and every field in
  ``removals`` is applied, with the key plan (``rename``; ``collision``: the new key plus the existing
  entry's ``also_rename``). A row whose entry is no longer in cdl.bib (merged away or removed by the
  wave-1 apply; its resolution is a no-op drop) is skipped. A row with no change and key ``keep`` is
  skipped.
- Rows are addressed by the key plan's ``current_key`` (the post-check follows wave-1 renames), then
  through the renames of the earlier batches of this folder.
- ``HOUSE_FORM``, ``HELD``, ``DEFERRED_RENAMES`` and ``SUFFIX_RENAMES`` hold the per-wave exceptions
  that ``helpers.check_bib`` forces (each with its reason).

    .venv/bin/python verification/apply-2026-09-29-waves2-9/build.py wave2
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import load_entries  # noqa: E402

INPUTS = ROOT / ".bibcheck" / HERE.name / "inputs"
WAVES = tuple(f"wave{n}" for n in range(2, 10))
# After waves 2-4 were applied, the post-check was re-run against that cdl.bib with the final evidence
# rules (commit 93ae192). Its merged.json files (frozen 2026-09-27 under inputs-93ae192/) address every
# row by its current key, so only the renames of the batches built from them are followed. The wave 2-4
# rows that still carry changes (the rows held in waves 2-4 and the check_bib exceptions) form one batch.
POSTCHECK_INPUTS = ROOT / ".bibcheck" / HERE.name / "inputs-93ae192"
POSTCHECKED = ("wave2to4",) + tuple(f"wave{n}" for n in range(5, 10))
BATCHES = WAVES[:3] + POSTCHECKED
SOURCES = {"wave2to4": ("wave2", "wave3", "wave4")}
NEVER_REMOVE = {"KahaEtal08b", "JacoEtal05b"}
RESOLUTIONS = "verification/resolution-2026-09-26"

# helpers.check_bib house forms of approved values: (wave, key, field) -> value.
HOUSE_FORM = {
    # the house journal form (31 entries print "{American} Journal of Psychology")
    ("wave2", "McGe36", "journal"): "{American} Journal of Psychology",
    ("wave2", "Spea04", "journal"): "{American} Journal of Psychology",
    # the formatter lowercases a word after ``; braced initial as in "The ``{N}arratives'' ..." (cdl.bib)
    ("wave2", "Spea04", "title"): "``{G}eneral intelligence,'' objectively determined and measured",
    # the formatter braces University (76 house occurrences of "{University}")
    ("wave3", "Hara96", "booktitle"): "Computer Networking and Scholarly Communication in the Twenty-First-Century {University}",
    ("wave3", "Hara96", "publisher"): "State {University} of New York Press",
    ("wave3", "BotvPlau03", "publisher"): "New Bulgarian {University}",
    # the author formatter strips the dot accent (\\.I -> "{ \\ I }", \\.{e} -> \\{e}) and the "." of "1.0";
    # the house also prints names in Unicode (106 lines of cdl.bib), which the formatter keeps
    ("wave5", "VirtEtal20", "author"): "P Virtanen and R Gommers and T E Oliphant and M Haberland and T Reddy and "
        "D Cournapeau and E Burovski and P Peterson and W Weckesser and J Bright and S J {van der Walt} and M Brett and "
        "J Wilson and K J Millman and N Mayorov and A R J Nelson and E Jones and R Kern and E Larson and C J Carey and "
        "\u0130 Polat and Y Feng and E W Moore and J {VanderPlas} and D Laxalde and J Perktold and R Cimrman and "
        "I Henriksen and E A Quintero and C R Harris and A M Archibald and A H Ribeiro and F Pedregosa and "
        "P {van Mulbregt} and {SciPy 1 0 Contributors}",
    ("wave5", "FallEtal20", "author"): "J Fallon and P G D Ward and L Parkes and S Oldham and "
        "A Arnatkevi\u010di\u016bt\u0117 and A Fornito and B D Fulcher",
    # the formatter lowercases a braced acronym that is not in caps.txt (wave-1 precedent: Kipp01 "({eurospeech})")
    ("wave6", "ClanEtal19", "booktitle"): "Proceedings of the Second Workshop on Fact Extraction and Verification ({fever})",
    ("wave6", "JoneEtal03", "booktitle"): "8\\textsuperscript{th} {European} Conference on Speech Communication and "
                                          "Technology ({eurospeech})",
    ("wave6", "GeisEtal08", "booktitle"): "Proceedings of the 10\\textsuperscript{th} Workshop on Algorithm Engineering "
                                          "and Experiments ({alenex})",
    ("wave6", "BorzEtal23a", "booktitle"): "Proceedings of the 61\\textsuperscript{st} Annual Meeting of the Association "
                                           "for Computational Linguistics (volume 3: System Demonstrations)",
    ("wave6", "Ande04", "booktitle"): "5\\textsuperscript{th} {ieee/acm} International Workshop on Grid Computing",
    ("wave7", "PimeEtal19", "booktitle"): "{ieee/acm} International Conference on Mining Software Repositories",
    # house forms: "{MIT} Press" (49 entries), "{American}" braced by the publisher formatter
    ("wave7", "AlvaEtal05", "publisher"): "{MIT} Press",
    ("wave7", "Amer23b", "publisher"): "{American} Academy of Sleep Medicine",
    # house software title "{Owner}/repo" ("{ContextLab}/chatify"); the formatter capitalises a fully braced title
    ("wave7", "ChanEtal20", "title"): "{naturalistic-data-analysis}/naturalistic\\_data\\_analysis",
    # the formatter capitalises the fully braced repository name ("{word\\_cloud}" -> "Word\\_cloud"); a braced
    # first word is its fixed point and prints the same lowercase name (as Chat{GPT}, {B}{ASIC})
    ("wave7", "MuelEtal18", "title"): "{word}\\_cloud",
    # wave 8: Force removed (Mann23, Open22, Kurt81) exposes values to check_bib; "{A}" after a colon
    # (wave-1 Tulv07); the formatter lowercases braced names ({vygotsky's}, {tulane}) and keeps them unbraced;
    # it strips the braces of a fully braced title ("{ChatGPT}" -> "Chatgpt", "{BASIC}" -> "Basic")
    ("wave8", "Mann23", "booktitle"): "Intracranial {EEG}: {A} Guide for Cognitive Neuroscientists",
    ("wave8", "ChatGPT", "title"): "Chat{GPT}",   # renamed to Open22
    ("wave8", "Kurt81", "title"): "{B}{ASIC}",
    ("wave8", "Chai03", "booktitle"): "Vygotsky's Educational Theory in Cultural Context",
    ("wave8", "RoedChal89", "booktitle"): "Current Issues in Cognitive Processes: the Tulane Flowerree Symposium on Cognition",
    ("wave8", "BjorRich89", "booktitle"): "Current Issues in Cognitive Processes: the Tulane Flowerree Symposium on Cognition",
    ("wave8", "SzpuTulv11", "booktitle"): "Predictions in the Brain: Using Our Past to Generate {A} Future",
    ("wave8", "BrowMcCo06", "booktitle"): "Handbook of Binding and Memory: Perspectives From Cognitive Neuroscience",
    ("wave8", "HallGree08", "booktitle"): "21\\textsuperscript{st} Century Education: {A} Reference Handbook",
    ("wave8", "Murd89", "booktitle"): "Current Issues in Cognitive Processes: the Tulane Flowerree Symposium on Cognition",
    # the formatter lowercases a braced "{W}erke"; the unbraced noun is its fixed point
    ("wave8", "Herb34", "booktitle"): 'S{\\"{a}}mtliche Werke',   # renamed to Herb91
    ("wave8", "TalaTour88", "publisher"): "{Georg} Thieme",
    ("wave8", "Wern84", "publisher"): "{Georg} Thieme",
    # wave 9: braced acronyms lowercased as elsewhere; the formatter's fixed point is the value as cited for
    # Laks01 ("At ... the") and RCor12 ("{ R Core Team}"), so those are not changed; \\L names in Unicode
    ("wave9", "Laks01", "booktitle"): "Biomedical Sciences and Human Experimentation At Kaiser Wilhelm Institutes: the "
                                      "Auschwitz Connection",
    ("wave9", "RCor12", "author"): "{ R Core Team}",
    ("wave9", "TardEtal08", "booktitle"): "{ieee/rsj} International Conference on Intelligent Robots and Systems",
    ("wave9", "Yama08", "booktitle"): "Dynamic Brain -- From Neural Spikes to Behaviors",
    ("wave9", "LiEtal16", "booktitle"): "Proceedings of the 14\\textsuperscript{th} Annual International Conference on "
                                        "Mobile Systems, Applications, and Services ({mobisys})",
    ("wave9", "TianEtal16b", "booktitle"): "Proceedings of the 17\\textsuperscript{th} International Workshop on Mobile "
                                           "Computing Systems and Applications ({hotmobile})",
    ("wave9", "LiEtal17b", "booktitle"): "Proceedings of the 15\\textsuperscript{th} {ACM} Conference on Embedded Network "
                                         "Sensor Systems ({sensys})",
    ("wave9", "TianEtal18", "booktitle"): "Proceedings of the 16\\textsuperscript{th} Annual International Conference on "
                                          "Mobile Systems, Applications, and Services ({mobisys})",
    ("wave9", "TianEtal20b", "booktitle"): "Proceedings of the 21\\textsuperscript{st} International Workshop on Mobile "
                                           "Computing Systems and Applications ({hotmobile})",
    ("wave9", "LiEtal20", "booktitle"): "Proceedings of the 18\\textsuperscript{th} Conference on Embedded Networked "
                                        "Sensor Systems ({sensys})",
    ("wave9", "CarvEtal22b", "booktitle"): "Proceedings of the 20\\textsuperscript{th} Annual International Conference on "
                                           "Mobile Systems, Applications and Services ({mobisys})",
    ("wave9", "vanREtal14", "author"): "G {van Rossum} and J Lehtosalo and \u0141 Langa",
    ("wave9", "VaswEtal17", "author"): "A Vaswani and N Shazeer and N Parmar and J Uszkoreit and L Jones and A N Gomez "
                                       "and \u0141 Kaiser and I Polosukhin",
    ("wave4", "BarnUnde59", "title"): "``{F}ate'' of first-list associations in transfer theory",
    ("wave4", "YoneJaco97", "title"): "``{R}esponse bias and the process-dissociation procedure'': correction to "
                                      "{Yonelinas} and {Jacoby} (1996)",
    # the formatter turns "(1993a)" into "(1993{A})"
    ("wave4", "ShifEtal93", "title"): "{TODAM} and the list-strength and list-length effects: comment on {M}urdock "
                                      "and {K}ahana (1993{a})",
    ("wave6", "Dall65", "title"): "``{P}rimary memory'': the effects of redundancy upon digit repetition",
    ("wave7", "ShoeEtal97", "journal"): "{American} Journal of Physiology-Heart and Circulatory Physiology",
    # the formatter lowercases a braced "{Alzheimer}"; the unbraced name is its fixed point
    ("wave7", "TounEtal99", "journal"): "Alzheimer Disease and Associated Disorders",
    # the formatter turns "$1/f^2$" into "$1/{F}^2$"
    ("wave7", "MilsEtal09", "title"): "Neuronal shot noise and {B}rownian $1/{f}^2$ behavior in the local field potential",
    ("wave9", "YangEtal13", "title"): "``{T}urn on, tune in, drop out'': anticipating student dropouts in massive open "
                                      "online courses",
}
# Approved fields helpers.check_bib cannot accept: (wave, key, field) -> reason. They stay as cited.
HELD = {
    ("wave3", "HeniEtal19", "pages"): "check_bib's page check reads the eNeuro article number 'ENEURO.0306-19.2019' as an "
                                      "ambiguous page range and raises; the entry keeps no pages (as cited)",
    ("wave3", "HeniEtal19", "journal"): "the journal formatter turns 'eNeuro' into 'Eneuro' ('{eNeuro}' into '{eneuro}'); "
                                        "the entry keeps 'Eneuro' (as cited)",
    ("wave5", "KingEtal11", "author"): "the author formatter turns the group author '{RNS System in Epilepsy Study "
                                       "Group}' into '{ R N S System in Epilepsy Study Group}' in every form tried "
                                       "(the wave-1 FoodAdmi20a case); the author list and the key (MorrRNSS11 "
                                       "follows the new author) stay as cited, the title fix is applied",
    ("wave4", "BrinCrag72", "pages"): "check_bib's page check cannot read the suffixed pages '28P--29P' (PubMed 'PG  - "
                                      "28P-29P') and raises; the entry keeps '28'",
    ("wave6", "Fish22", "journal"): "the journal formatter capitalises the article in 'Containing Papers of a Mathematical "
                                    "or Physical Character' ('{A} Mathematical') in every form tried; the entry keeps "
                                    "'Philosophical Transactions of the Royal Society {A}'",
    **{("wave6", k, "pages"): f"check_bib's page check cannot read the roman-to-arabic range {v!r} and raises; the entry "
                              f"keeps its current pages" for k, v in (("Perr14", "i--97"), ("Unde45", "i--33"),
                                                                      ("Ward37", "i--64"), ("Webb17", "i--90"),
                                                                      ("Calk96", "i--56"))},
    ("wave7", "Youn12", "url"): "url is not a house field (bibcheck/keep_fields.txt; check_bib: 'non-essential "
                                "fields'); the removals of volume, number and pages are applied",
    ("wave9", "RangEtal14", "publisher"): "the publisher formatter turns 'PMLR' into 'Pmlr' ('{PMLR}' into '{pmlr}'); "
                                          "the entry keeps no publisher",
    ("wave9", "BartEtal04c", "address"): "the address formatter reads 'La' as the Louisiana code ('{LA} Jolla, {CA}') in "
                                         "every form tried; the entry keeps no address",
    ("wave7", "ViveEtal10", "pages"): "check_bib's page check cannot read the article number '24ra22' and raises; the "
                                      "entry keeps '1--9'",
    ("wave7", "MullSchu94", "pages"): "check_bib's page check cannot read the two-part range '81--190, 257--339' (the "
                                      "user-rule default for an article printed in two parts) in any separator tried "
                                      "(', ', ',', '; ', ' and '); the entry keeps '257--339'",
}
# final_changes rows that name no bibliography field: field -> reason (never written to cdl.bib).
PSEUDO_FIELDS = {
    "needs_user": "not a bibliography field: the reviewer's request (TsitEtal19, wave 7) that the user decide the "
                  "preprint -> published replacement, recorded as a change row; the row's resolution (batch-17, "
                  "'apply', the user's preprint rule) already made that replacement and the row is not needs_user",
}
# needs_user rows of the re-run post-check, resolved here (2026-09-27): (source wave, row key) -> resolution.
# ChanEtal12b, MairEtal09a and LegaEtal11a are flagged not_in_bib (and "duplicate" of the key they now have)
# only because the wave-2/3 suffix rule renamed them (verification/key-renames.json); their approved values
# are applied to the renamed entry, compared with its current fields. McCaEtal06 keeps its DOI by the
# user-rule default of verification/resolution-plan-2026-09-22/README.md (line 281).
NEEDS_USER = {
    ("wave2", "ChanEtal12b"): {"key": "ChanEtal12", "why": "renamed ChanEtal12b -> ChanEtal12 in wave2 "
                               "(key-renames.json, suffix rule); not a duplicate of another entry"},
    ("wave6", "MairEtal09a"): {"key": "MairEtal09", "why": "renamed MairEtal09a -> MairEtal09 in wave2 "
                               "(key-renames.json, suffix rule); not a duplicate of another entry",
                               # the pre-post-check row (inputs/wave6/merged.json) saw the entry and removed it
                               "removals": {"journal": "@inproceedings has no journal (names the same venue as the "
                                            "booktitle 'Proceedings of the 26\\textsuperscript{th} Annual International "
                                            "Conference on Machine Learning')"}},
    ("wave7", "LegaEtal11a"): {"key": "LegaEtal11", "why": "renamed LegaEtal11a -> LegaEtal11 in wave3 "
                               "(key-renames.json, suffix rule); not a duplicate of another entry"},
    ("wave7", "McCaEtal06"): {"key": "McCaEtal06", "why": "user-rule default (resolution-plan-2026-09-22/README.md): a "
                              "DOI that doi.org registers and the publisher's article page prints is kept although "
                              "Crossref's API lacks it",
                              "add": [{"field": "doi", "proposed": "10.1609/aimag.v27i4.1904", "source": "resolution",
                                       "evidence": [
                                           {"url": "https://doi.org/api/handles/10.1609/aimag.v27i4.1904",
                                            "quote": "\"responseCode\":1,\"handle\":\"10.1609/aimag.v27i4.1904\"",
                                            "checked": "2026-09-27"},
                                           {"url": "https://doi.org/10.1609/aimag.v27i4.1904",
                                            "quote": "HTTP 302 -> http://www.aaai.org/ojs/index.php/aimagazine/article/view/1904",
                                            "checked": "2026-09-27"},
                                           {"url": "https://ojs.aaai.org/aimagazine/index.php/aimagazine/article/view/1904",
                                            "quote": "<meta name=\"citation_doi\" content=\"10.1609/aimag.v27i4.1904\"/>",
                                            "checked": "2026-09-27"},
                                           {"url": "https://api.crossref.org/works/10.1609/aimag.v27i4.1904",
                                            "quote": "HTTP 404 (not in Crossref's API)", "checked": "2026-09-27"}]}]},
}
# Key renames of a ready row not applied in this wave (the house suffix rule forbids it here, or the
# key-determining field is held): (wave, key) -> reason.
DEFERRED_RENAMES = {
    ("wave8", "KahaEtal08a"): "rename KahaEtal08a -> KahaEtal08 not applied: the user's decision (cross-wave "
                              "dup-KahaEtal08b-KahaEtal08a) is conditional ('drop the \"a\" ... if this is the only "
                              "KahaEtal08'), and KahaEtal08b (formerly KahaEtal08c, 'Putting short-term memory into "
                              "context', a different work) is still in cdl.bib",
    ("wave5", "KingEtal11"): "rename KingEtal11 -> MorrRNSS11 held with the author list it follows (HELD)",
    ("wave2", "Shim95"): "rename Shim95 -> Shim95a deferred to wave 8, where Shim94 -> Shim95b is applied with "
                         "it (the same cross-wave q-shim decision, also_rename of Shim94's plan): a lone Shim95a "
                         "fails helpers.check_key_suffixes",
}
# Pure key renames the house suffix rule (helpers.check_key_suffixes) forces after a wave's removals and
# renames: wave -> {old: (new, reason)}.
SUFFIX_RENAMES = {
    "wave2": {"ChanEtal12b": ("ChanEtal12", "ChanEtal12a renamed to ChanEtal13"),
              "MairEtal09a": ("MairEtal09", "MairEtal09b renamed to MairEtal08")},
    "wave3": {"LegaEtal11a": ("LegaEtal11", "LegaEtal11b renamed to LegaEtal12")},
    "wave4": {"CoheEtal08b": ("CoheEtal08", "CoheEtal08a renamed to CoheEtal09c")},
    "wave6": {"Arch11a": ("Arch11", "Arch11b renamed to Arch12")},
    "wave9": {"deCa05b": ("deCa05", "deCa05a renamed to deCa04")},
    "wave7": {"LiEtal24a": ("LiEtal24", "LiEtal24b renamed to LiEtal25")},
    "wave8": {"Frie08b": ("Frie08", "Frie08a renamed to Frie12 (wave-1 README: 'Frie08b should become Frie08')")},
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def earlier_renames(wave):
    """old -> new over the batches of this folder applied before ``wave`` (simultaneous per batch); for a
    batch built from the re-run post-check, only over the post-checked batches before it."""
    moved = {}
    order = POSTCHECKED if wave in POSTCHECKED else WAVES
    for earlier in order[:order.index(wave)]:
        path = HERE / f"{earlier}-proposals.json"
        if not path.exists():
            raise SystemExit(f"{earlier}-proposals.json missing: apply the waves in order")
        step = json.loads(path.read_text())["renames"]
        moved = {k: step.get(v, v) for k, v in moved.items()}
        for old, new in step.items():
            moved.setdefault(old, new)
    return moved


def decision_source(row, wave):
    res = row.get("resolution")
    if res:
        return (f"{RESOLUTIONS}/{res['batch']}.json ({res['decision']}; post-check "
                f"research-2026-09-25/{wave}/merged.json): {res['notes']}")
    ud = "; ".join(json.dumps(d, ensure_ascii=False) for d in row.get("user_decisions") or [])
    return f"research-2026-09-25/{wave}/merged.json (post-check remove_entry){'; user: ' + ud if ud else ''}"


def main():
    wave = sys.argv[1]
    assert wave in BATCHES, wave
    if wave in POSTCHECKED:
        merged = [POSTCHECK_INPUTS / src / "merged.json" for src in SOURCES.get(wave, (wave,))]
    else:
        merged = [INPUTS / wave / "merged.json"]
    rows = [dict(r, _src=path.parent.name) for path in merged for r in json.loads(path.read_text())]
    entries = load_entries(ROOT / "cdl.bib")
    text = (ROOT / "cdl.bib").read_text()
    deleted = {d["key"] for d in json.loads((ROOT / "verification/key-deletions.json").read_text())}
    moved = earlier_renames(wave)

    proposals, skipped, held_rows, held, noops = [], {}, {}, {}, {}
    also = {}
    resolved_user = {}
    for r in rows:
        src = r["_src"]
        key0 = r["key_plan"]["current_key"]
        key = moved.get(key0, key0)
        if r["needs_user"] and wave in POSTCHECKED and (src, r["key"]) in NEEDS_USER:
            nu = NEEDS_USER[src, r["key"]]
            key = moved.get(nu["key"], nu["key"])
            assert key in entries, key
            flds = entries[key]["fields"]
            fc = []
            for c in r["final_changes"] + nu.get("add", []):
                cur = flds.get(c["field"]) if c["field"] != "ENTRYTYPE" else flds["ENTRYTYPE"]
                assert c.get("current") is None or c["current"] == cur, (key, c)
                if cur != c["proposed"]:
                    fc.append(dict(c, current=cur))
            r = dict(r, final_changes=fc, removals={f: w for f, w in nu.get("removals", {}).items() if f in flds},
                     needs_user=False, key_plan={"current_key": key, "target_base": key, "action": "keep"})
            resolved_user[r["key"]] = {"key": key, "why": nu["why"],
                                       "applied": [c["field"] for c in fc] + sorted(r["removals"]) or
                                       "nothing: every approved value is already in the entry"}
        if r["needs_user"]:
            held_rows[r["key"]] = "needs_user (residue: " + json.dumps((r.get("resolution") or {}).get("residue"),
                                                                        ensure_ascii=False) + ")"
            continue
        if r["remove_entry"]:
            noop = (r.get("resolution") or {}).get("noop")
            if noop or key not in entries:
                assert key not in entries or key in deleted, (key, noop)
                noops[r["key"]] = noop or "not in the bibliography"
                continue
            assert key not in NEVER_REMOVE and key not in deleted, key
            proposals.append({"key": key, "fingerprint": entries[key]["fingerprint"], "kind": "remove",
                              "reason": r["remove_entry"], "decision": decision_source(r, src),
                              **({"row_key": r["key"]} if key != r["key"] else {})})
            continue
        if key not in entries:
            res = r.get("resolution") or {}
            assert res.get("decision") == "drop" and res.get("noop"), (key, res)
            noops[r["key"]] = f"ready row, entry not in cdl.bib (resolution drop: {res['noop']})"
            continue
        fields = entries[key]["fields"]
        changes = {}
        for c in r["final_changes"]:
            field = c["field"]
            before = fields.get(field) if field != "ENTRYTYPE" else fields["ENTRYTYPE"]
            assert before == c["current"], (key, field, before, c["current"])
            if field in PSEUDO_FIELDS:
                skipped[f"{key}.{field}"] = PSEUDO_FIELDS[field]
                continue
            if (src, key, field) in HELD:
                held[f"{key}.{field}"] = HELD[src, key, field]
                continue
            after = HOUSE_FORM.get((src, key, field), c["proposed"])
            if after == before:   # the house form is the value as cited: no change
                skipped[f"{key}.{field}"] = f"proposed {c['proposed']!r}; house form (check_bib) is the value as cited"
                continue
            changes[field] = {"before": before, "after": after, "source": c["source"],
                              "evidence": c.get("evidence", []),
                              **({"proposed": c["proposed"], "house_form": "check_bib"} if after != c["proposed"] else {})}
        for (w, k, field), value in HOUSE_FORM.items():
            # a house form of a field the research left unchanged, which check_bib reads once a change
            # (e.g. removing Force, its skip flag) exposes it
            if w == src and k == key and field not in {c["field"] for c in r["final_changes"]} \
                    and field not in r["removals"]:
                assert field in fields, (key, field)
                if fields[field] == value:   # already applied by the wave-2/3/4 batch
                    continue
                changes[field] = {"before": fields[field], "after": value, "house_form": "check_bib",
                                  "reason": "house form of the unchanged value (check_bib)"}
        for field, why in r["removals"].items():
            assert field not in changes and field in fields, (key, field)
            if (src, key, field) in HELD:
                held[f"{key}.{field}"] = HELD[src, key, field]
                continue
            changes[field] = {"before": fields[field], "after": None, "reason": why}
        plan = r["key_plan"]
        rename = plan.get("new_key") if plan["action"] in ("rename", "collision") else None
        assert plan["action"] in ("keep", "rename", "collision"), (key, plan)
        if (src, key) in DEFERRED_RENAMES:
            skipped[f"{key} (key)"] = DEFERRED_RENAMES[src, key]
            rename = None
        for old, new in plan.get("also_rename", {}).items():
            also[moved.get(old, old)] = (new, key, rename)
        if not changes and not rename:
            skipped[key] = ("no change left: every approved change is held" if any(h.startswith(key + ".") for h in held)
                            else "no change: the entry stands as cited" + (
                                f" (resolution {r['resolution']['decision']})" if r.get("resolution") else ""))
            continue
        res = r.get("resolution")
        row = {"key": key, "fingerprint": entries[key]["fingerprint"], "kind": "edit",
               "origin": f"{src} merged.json ({r['verdict']}" + (f"; resolution {res['decision']} {res['batch']}" if res else "")
                         + ")", "changes": changes}
        if key != r["key"]:
            row["row_key"] = r["key"]
        if rename:
            row["rename"] = rename
            row["rename_reason"] = (plan.get("rename_reason") or "") + (f"; {plan['detail']}" if plan.get("detail") else "") \
                + (f"; {plan['resolution']}" if plan.get("resolution") else "")
        proposals.append(row)

    by_key = {p["key"]: p for p in proposals}
    for old, (new, cause, cause_new) in sorted(also.items()):
        assert old in entries, old
        if old in by_key:
            p = by_key[old]
            assert not p.get("rename") or p["rename"] == new, (old, p.get("rename"), new)
            p["rename"] = new
            p["rename_reason"] = f"suffix rule: {cause} becomes {cause_new} (also_rename of its key plan)"
            continue
        proposals.append({"key": old, "fingerprint": entries[old]["fingerprint"], "kind": "edit", "changes": {},
                          "rename": new, "origin": f"{wave} key plan of {cause} (collision, house suffix rule)",
                          "rename_reason": f"suffix rule: {cause} becomes {cause_new}"})
        by_key[old] = proposals[-1]
    for old, (new, why) in sorted(SUFFIX_RENAMES.get(wave, {}).items()):
        assert old in entries, old
        if old in by_key:   # the entry has its own row in this wave: add the rename to its edit
            p = by_key[old]
            assert p["kind"] == "edit" and not p.get("rename"), old
            p["rename"], p["rename_reason"] = new, f"suffix rule: {why}"
            continue
        proposals.append({"key": old, "fingerprint": entries[old]["fingerprint"], "kind": "edit", "changes": {},
                          "rename": new, "origin": "house suffix rule (helpers.check_key_suffixes) after this batch",
                          "rename_reason": f"suffix rule: {why}"})
        by_key[old] = proposals[-1]
    srcs = SOURCES.get(wave, (wave,))
    assert {(k, f) for (w, k, f) in HELD if w in srcs} == {tuple(h.split(".")) for h in held}

    # A renamed or removed key must not be referenced from another entry (crossref and the like).
    for p in proposals:
        if p["kind"] == "remove" or p.get("rename"):
            outside = text.replace(entries[p["key"]]["raw"], "", 1)
            assert not re.search(r"[{,=\s]" + re.escape(p["key"]) + r"[},\s]", outside), f"{p['key']} referenced elsewhere"

    assert len({p["key"] for p in proposals}) == len(proposals)
    out = {"batch": wave, "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
           "input": [{"merged": str(path.relative_to(ROOT)), "sha256": sha256(path),
                      "rows": len(json.loads(path.read_text()))} for path in merged],
           "count": len(proposals),
           "counts": {kind: sum(p["kind"] == kind for p in proposals) for kind in ("edit", "remove")},
           "renames": {p["key"]: p["rename"] for p in proposals if p.get("rename")},
           "held_rows": held_rows, "needs_user_resolved": resolved_user, "noops": noops, "skipped": skipped, "held_fields": held, "proposals": proposals}
    (HERE / f"{wave}-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: out[k] for k in ("count", "counts", "renames", "needs_user_resolved")}), f"held_rows {len(held_rows)}",
          f"noops {len(noops)}", f"skipped {len(skipped)}", f"held_fields {len(held)}")


if __name__ == "__main__":
    main()
