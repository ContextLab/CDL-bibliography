"""Build replace001-proposals.json: the 8 user-approved preprint -> published replacements
(../apply-2026-09-25e/replacement-candidates.json; user approval recorded in
../resolution-plan-2026-09-22/README.md, "Replacements approved", 2026-09-25).

Each published entry is written in house form from its Crossref record (saved under
crossref/ in this folder): initials without periods, all initials the source gives, no name
suffixes, lowercase DOI, sentence-case title with braced acronyms, the journal name as cdl.bib
already writes it, full page ranges with ``--``, LaTeX accents.
User rules applied per entry:
- LeeEtal20 (Lee, Bellana & Chen) is renamed LeeEtal20a first, so the published LeeEtal19
  becomes LeeEtal20b (suffix rule).
- LuriEtal20 keeps "Keilholz" (Crossref's "Kheilholz" is a single-source typo; house and
  library spelling win).
- ZhenEtal20 uses the published five-author byline. "M. Ángeles Serrano" is written "M A Serrano":
  helpers.reformat_author breaks an accented initial ("\\'{A}" becomes "\\ ' { A }"), so check_bib
  rejects every LaTeX form of it (formatter limitation, not a source difference).

    .venv/bin/python verification/apply-2026-09-25f/build_replace.py
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import load_entries  # noqa: E402

CANDIDATES = ROOT / "verification/apply-2026-09-25e/replacement-candidates.json"
REASON = "published version replaces preprint (user-approved 2026-09-25)"

RAW = {
    "BetzEtal19": ("BetzEtal20", """@article{BetzEtal20,
	Author = {R F Betzel and L Byrge and F Z Esfahlani and D P Kennedy},
	Doi = {10.1016/j.neuroimage.2020.116687},
	Journal = {{NeuroImage}},
	Pages = {116687},
	Title = {Temporal fluctuations in the brain's modular architecture during movie-watching},
	Volume = {213},
	Year = {2020}}"""),
    "ChieHone19": ("ChieHone20", """@article{ChieHone20,
	Author = {H-Y S Chien and C J Honey},
	Doi = {10.1016/j.neuron.2020.02.013},
	Journal = {Neuron},
	Number = {4},
	Pages = {675--686.e11},
	Title = {Constructing and forgetting temporal context in the human cerebral cortex},
	Volume = {106},
	Year = {2020}}"""),
    "GralFinn21": ("GralFinn22", """@article{GralFinn22,
	Author = {C Grall and E S Finn},
	Doi = {10.1093/scan/nsac019},
	Journal = {Social Cognitive and Affective Neuroscience},
	Number = {6},
	Pages = {598--608},
	Title = {Leveraging the power of media to drive cognition: a media-informed approach to naturalistic neuroscience},
	Volume = {17},
	Year = {2022}}"""),
    "LeeEtal19": ("LeeEtal20b", """@article{LeeEtal20b,
	Author = {J S Lee and J J Briguglio and J D Cohen and S Romani and A K Lee},
	Doi = {10.1016/j.cell.2020.09.024},
	Journal = {Cell},
	Number = {3},
	Pages = {620--635.e22},
	Title = {The statistical structure of the hippocampal code for space as a function of time, context, and value},
	Volume = {183},
	Year = {2020}}"""),
    "LuriEtal18": ("LuriEtal20", """@article{LuriEtal20,
	Author = {D J Lurie and D Kessler and D S Bassett and R F Betzel and M Breakspear and S Keilholz and A Kucyi and R Li\\'{e}geois and M A Lindquist and A R {McIntosh} and R A Poldrack and J M Shine and W H Thompson and N Z Bielczyk and L Douw and D Kraft and R L Miller and M Muthuraman and L Pasquini and A Razi and D Vidaurre and H Xie and V D Calhoun},
	Doi = {10.1162/netn_a_00116},
	Journal = {Network Neuroscience},
	Number = {1},
	Pages = {30--69},
	Title = {Questions and controversies in the study of time-varying functional connectivity in resting {fMRI}},
	Volume = {4},
	Year = {2020}}"""),
    "NussEtal18": ("NussEtal20", """@article{NussEtal20,
	Author = {K Nussenbaum and E Prentis and C A Hartley},
	Doi = {10.1037/xge0000753},
	Journal = {Journal of Experimental Psychology: General},
	Number = {10},
	Pages = {1919--1934},
	Title = {Memory's reflection of learned information value increases across development},
	Volume = {149},
	Year = {2020}}"""),
    "SilvEtal19": ("SilvEtal19", """@article{SilvEtal19,
	Author = {M Silva and C Baldassano and L Fuentemilla},
	Doi = {10.1523/jneurosci.0360-19.2019},
	Journal = {The Journal of Neuroscience},
	Number = {43},
	Pages = {8538--8548},
	Title = {Rapid memory reactivation at movie event boundaries promotes episodic encoding},
	Volume = {39},
	Year = {2019}}"""),
    "ZhenEtal19": ("ZhenEtal20", """@article{ZhenEtal20,
	Author = {M Zheng and A Allard and P Hagmann and Y Alem\\'{a}n-G\\'{o}mez and M A Serrano},
	Doi = {10.1073/pnas.1922248117},
	Journal = {Proceedings of the National Academy of Sciences, {USA}},
	Number = {33},
	Pages = {20244--20253},
	Title = {Geometric renormalization unravels self-similarity of the multiscale human connectome},
	Volume = {117},
	Year = {2020}}"""),
}


def main():
    entries = load_entries(ROOT / "cdl.bib")
    cands = {c["key"]: c for c in json.loads(CANDIDATES.read_text())["candidates"]}
    assert set(cands) == set(RAW), set(cands) ^ set(RAW)
    proposals = []
    lee = entries["LeeEtal20"]
    assert lee["fields"]["author"] == "H Lee and B Bellana and J Chen"
    proposals.append({"key": "LeeEtal20", "fingerprint": lee["fingerprint"], "kind": "edit", "changes": {},
                      "rename": "LeeEtal20a",
                      "reason": "suffix rule: LeeEtal20b (published version of LeeEtal19) joins; " + REASON})
    for key in sorted(RAW):
        new_key, raw = RAW[key]
        cand = cands[key]
        assert cand["proposed_key"] == new_key, (key, cand["proposed_key"], new_key)
        doi = cand["published"]["doi"].lower()
        record = json.loads((HERE / "crossref" / (doi.replace("/", "_") + ".json")).read_text())["message"]
        assert record["DOI"].lower() == doi and f"Doi = {{{doi}}}" in raw, key
        proposals.append({"key": key, "fingerprint": entries[key]["fingerprint"], "kind": "replace",
                          "new_key": new_key, "raw": raw, "reason": REASON,
                          "evidence": [{"url": f"https://api.crossref.org/works/{doi}",
                                        "quote": "; ".join([
                                            "title " + record["title"][0],
                                            "container " + record["container-title"][0],
                                            f"volume {record.get('volume')} issue {record.get('issue')} page {record.get('page')}",
                                            "print " + str(record.get("published-print", {}).get("date-parts"))
                                            + " issued " + str(record["issued"]["date-parts"]),
                                            "authors " + ", ".join(f"{a.get('given', '')} {a['family']}" for a in record["author"])])},
                                       {"source": "replacement-candidates.json (preprint relation)", "quote": cand["evidence"]}],
                          "notes": cand["notes"]})
    out = {"batch": "replace001", "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "count": len(proposals),
           "proposals": proposals}
    (HERE / "replace001-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(len(proposals), "proposals:", {p["key"]: p.get("rename") or p.get("new_key") for p in proposals})


if __name__ == "__main__":
    main()
