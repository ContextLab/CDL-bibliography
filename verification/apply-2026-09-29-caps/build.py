"""Build caps0929-proposals.json: the acronym / "\\&" / state-abbreviation fixes of 2026-09-29.

Each row below names the entry, the field, the value in cdl.bib at 068fcb1 (``before``), the house form
(``after``) and the record that prints it. Every ``after`` except ClanEtal19's is exactly what
helpers.check_bib now computes from ``before`` (asserted here); ClanEtal19's "({FEVER})" is braced as
printed, because FEVER is an English word and so is not in caps.txt (format_title shares the table).
The Crossref and Library of Congress records were fetched on 2026-09-29 (crossref-records.json and
loc-12064937.json in this folder).

    python verification/apply-2026-09-29-caps/build.py
"""
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import helpers  # noqa: E402
from verification import load_entries  # noqa: E402

BATCH = "caps0929"
CR = "Crossref {doi} container-title {printed!r}"
ROWS = [
    ("JuanRabi85", "journal", r"At\&t Technical Journal", r"{AT\&T} Technical Journal",
     CR.format(doi="10.1002/j.1538-7305.1985.tb00439.x", printed="AT&T Technical Journal")),
    ("RabiEtal85", "journal", r"At\&t Technical Journal", r"{AT\&T} Technical Journal",
     CR.format(doi="10.1002/j.1538-7305.1985.tb00272.x", printed="AT&T Technical Journal")),
    ("CarvEtal22a", "booktitle",
     r"14\textsuperscript{th} International Conference on Communication Systems \& Networks ({comsnets})",
     r"14\textsuperscript{th} International Conference on Communication Systems \& Networks ({COMSNETS})",
     CR.format(doi="10.1109/comsnets53615.2022.9668473",
               printed="2022 14th International Conference on COMmunication Systems & NETworkS (COMSNETS)")),
    ("ClanEtal19", "booktitle",
     "Proceedings of the Second Workshop on Fact Extraction and Verification ({fever})",
     "Proceedings of the Second Workshop on Fact Extraction and Verification ({FEVER})",
     CR.format(doi="10.18653/v1/d19-6607",
               printed="Proceedings of the Second Workshop on Fact Extraction and VERification (FEVER)")),
    ("GeisEtal08", "booktitle",
     r"Proceedings of the 10\textsuperscript{th} Workshop on Algorithm Engineering and Experiments ({alenex})",
     r"Proceedings of the 10\textsuperscript{th} Workshop on Algorithm Engineering and Experiments ({ALENEX})",
     CR.format(doi="10.1137/1.9781611972887.9",
               printed="2008 Proceedings of the Tenth Workshop on Algorithm Engineering and Experiments (ALENEX)")),
    ("JoneEtal03", "booktitle",
     r"8\textsuperscript{th} {European} Conference on Speech Communication and Technology ({eurospeech})",
     r"8\textsuperscript{th} {European} Conference on Speech Communication and Technology ({Eurospeech})",
     CR.format(doi="10.21437/eurospeech.2003-463",
               printed="8th European Conference on Speech Communication and Technology (Eurospeech 2003)")),
    ("Kipp01", "booktitle",
     r"7\textsuperscript{th} {European} Conference on Speech Communication and Technology ({eurospeech})",
     r"7\textsuperscript{th} {European} Conference on Speech Communication and Technology ({Eurospeech})",
     CR.format(doi="10.21437/eurospeech.2001-354",
               printed="7th European Conference on Speech Communication and Technology (Eurospeech 2001)")),
    ("SchiEtal13", "journal", "The {febs} Journal", "The {FEBS} Journal",
     CR.format(doi="10.1111/febs.12253", printed="The FEBS Journal")),
    ("ScheEtal02", "booktitle",
     r"Proceedings of the 25\textsuperscript{th} Annual International {ACM} {sigir} Conference on Research and Development in Information Retrieval",
     r"Proceedings of the 25\textsuperscript{th} Annual International {ACM} {SIGIR} Conference on Research and Development in Information Retrieval",
     CR.format(doi="10.1145/564376.564421",
               printed="Proceedings of the 25th annual international ACM SIGIR conference on Research and development in information retrieval")),
    ("TardEtal08", "booktitle",
     "{ieee/rsj} International Conference on Intelligent Robots and Systems",
     "{IEEE/RSJ} International Conference on Intelligent Robots and Systems",
     CR.format(doi="10.1109/iros.2008.4651205",
               printed="2008 IEEE/RSJ International Conference on Intelligent Robots and Systems")),
    ("Ande04", "booktitle",
     r"5\textsuperscript{th} {ieee/acm} International Workshop on Grid Computing",
     r"5\textsuperscript{th} {IEEE/ACM} International Workshop on Grid Computing",
     CR.format(doi="10.1109/grid.2004.14", printed="Fifth IEEE/ACM International Workshop on Grid Computing")),
    ("PimeEtal19", "booktitle",
     "{ieee/acm} International Conference on Mining Software Repositories",
     "{IEEE/ACM} International Conference on Mining Software Repositories",
     CR.format(doi="10.1109/msr.2019.00077",
               printed="2019 IEEE/ACM 16th International Conference on Mining Software Repositories (MSR)")),
]
EVENT = "Crossref {doi} event acronym {printed!r}"
for key, doi, prefix, acronym, lower in [
    ("LiEtal16", "10.1145/2906388.2906401",
     r"Proceedings of the 14\textsuperscript{th} Annual International Conference on Mobile Systems, Applications, and Services", "MobiSys'16", "mobisys"),
    ("TianEtal18", "10.1145/3210240.3210340",
     r"Proceedings of the 16\textsuperscript{th} Annual International Conference on Mobile Systems, Applications, and Services", "MobiSys '18", "mobisys"),
    ("CarvEtal22b", "10.1145/3498361.3539773",
     r"Proceedings of the 20\textsuperscript{th} Annual International Conference on Mobile Systems, Applications and Services", "MobiSys '22", "mobisys"),
    ("TianEtal16b", "10.1145/2873587.2873598",
     r"Proceedings of the 17\textsuperscript{th} International Workshop on Mobile Computing Systems and Applications", "HotMobile '16", "hotmobile"),
    ("TianEtal20b", "10.1145/3376897.3377854",
     r"Proceedings of the 21\textsuperscript{st} International Workshop on Mobile Computing Systems and Applications", "HotMobile '20", "hotmobile"),
    ("LiEtal17b", "10.1145/3131672.3131682",
     r"Proceedings of the 15\textsuperscript{th} {ACM} Conference on Embedded Network Sensor Systems", "SenSys '17", "sensys"),
    ("LiEtal20", "10.1145/3384419.3430720",
     r"Proceedings of the 18\textsuperscript{th} Conference on Embedded Networked Sensor Systems", "SenSys '20", "sensys"),
]:
    house = {"mobisys": "MobiSys", "hotmobile": "HotMobile", "sensys": "SenSys"}[lower]
    ROWS.append((key, "booktitle", f"{prefix} ({{{lower}}})", f"{prefix} ({{{house}}})",
                 EVENT.format(doi=doi, printed=acronym)))
ROWS += [
    ("CarvEtal19", "journal", "Xrds: Crossroads, the {ACM} Magazine for Students",
     "{XRDS}: Crossroads, the {ACM} Magazine for Students",
     CR.format(doi="10.1145/3357229", printed="XRDS: Crossroads, The ACM Magazine for Students")),
    ("BorzEtal23a", "booktitle",
     r"Proceedings of the 61\textsuperscript{st} Annual Meeting of the Association for Computational Linguistics (volume 3: System Demonstrations)",
     r"Proceedings of the 61\textsuperscript{st} Annual Meeting of the Association for Computational Linguistics (Volume 3: System Demonstrations)",
     CR.format(doi="10.18653/v1/2023.acl-demo.54",
               printed="Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics (Volume 3: System Demonstrations)")
     + " (and the ACL Anthology record in the stored evidence)"),
]
for key, doi in [("Nied90", "10.1177/155005949002100410"), ("Nied91", "10.1177/155005949102200208"),
                 ("ShinEtal99", "10.1177/155005949903000405")]:
    ROWS.append((key, "journal", "Clinical {EEG} (electroencephalography)",
                 "Clinical {EEG} (Electroencephalography)",
                 f"Europe PMC / NLM journal title 'Clinical EEG (electroencephalography)' (stored evidence, "
                 f"accepted source europepmc; Crossref {doi} prints the later title 'Clinical Electroencephalography'); "
                 "house title case: the formatter now capitalizes the word after an opening parenthesis"))
ROWS.append(("Albe00", "address", "Cambridge, Mass.", "Cambridge, {MA}",
             "Library of Congress record 12064937 (LCCN 00056732) 260 $a 'Cambridge, Mass. :' $b 'Harvard "
             "University Press,'; house form 'City, {ST}' (verification/resolution-plan-2026-09-22/README.md)"))

FIELD_FORMAT = {
    "journal": lambda v: helpers.format_journal_name(v),
    "booktitle": lambda v: helpers.format_journal_name(v),
    "address": lambda v: helpers.format_journal_name(v, key=helpers.address_key, force_caps=helpers.address_codes),
}


def main():
    entries = load_entries(ROOT / "cdl.bib")
    proposals = []
    for key, field, before, after, source in ROWS:
        entry = entries[key]
        assert entry["fields"][field] == before, (key, entry["fields"][field])
        formatted = FIELD_FORMAT[field](before)
        if key == "ClanEtal19":
            assert formatted == before and FIELD_FORMAT[field](after) == after, key
        else:
            assert formatted == after, (key, formatted, after)
        assert FIELD_FORMAT[field](after) == after, key
        proposals.append({"key": key, "kind": "edit", "fingerprint": entry["fingerprint"],
                          "changes": {field: {"before": before, "after": after}}, "source": source})
    assert len({p["key"] for p in proposals}) == len(proposals)
    bib_sha = hashlib.sha256((ROOT / "cdl.bib").read_bytes()).hexdigest()
    out = {"batch": BATCH, "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
           "input": [{"file": "cdl.bib", "sha256": bib_sha}],
           "count": len(proposals), "counts": {"edit": len(proposals), "remove": 0}, "renames": {},
           "proposals": proposals}
    (HERE / f"{BATCH}-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(proposals)} proposals written")


if __name__ == "__main__":
    main()
