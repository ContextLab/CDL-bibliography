"""Build prfix001-proposals.json: fixes to the entries merged from PR #87 and PR #88, plus Aust14.

Run after both merges are committed. Every change is source-backed (quotes below, fetched
2026-09-25) and applies the house rules (initials, lowercase bare DOI, ``--`` ranges,
``N\\textsuperscript{..}`` editions, @inproceedings, preprints cite their latest version,
DOIs everywhere). ``verify_keys`` lists every entry the two PRs added or edited, so the
production pipeline verifies all of them with the batch.

    .venv/bin/python verification/apply-2026-09-28/build_prfix.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import load_entries  # noqa: E402

CR = "https://api.crossref.org/works/"
AX = "https://export.arxiv.org/api/query?id_list="
QWEN = ("An Yang | Anfeng Li | Baosong Yang | Beichen Zhang | Binyuan Hui | Bo Zheng | Bowen Yu | Chang Gao | "
        "Chengen Huang | Chenxu Lv | Chujie Zheng | Dayiheng Liu | Fan Zhou | Fei Huang | Feng Hu | Hao Ge | "
        "Haoran Wei | Huan Lin | Jialong Tang | Jian Yang | Jianhong Tu | Jianwei Zhang | Jianxin Yang | Jiaxi Yang | "
        "Jing Zhou | Jingren Zhou | Junyang Lin | Kai Dang | Keqin Bao | Kexin Yang | Le Yu | Lianghao Deng | Mei Li | "
        "Mingfeng Xue | Mingze Li | Pei Zhang | Peng Wang | Qin Zhu | Rui Men | Ruize Gao | Shixuan Liu | Shuang Luo | "
        "Tianhao Li | Tianyi Tang | Wenbiao Yin | Xingzhang Ren | Xinyu Wang | Xinyu Zhang | Xuancheng Ren | Yang Fan | "
        "Yang Su | Yichang Zhang | Yinger Zhang | Yu Wan | Yuqiong Liu | Zekun Wang | Zeyu Cui | Zhenru Zhang | "
        "Zhipeng Zhou | Zihan Qiu")
QWEN_HOUSE = " and ".join(n.split()[0][0] + " " + n.split()[1] for n in QWEN.split(" | "))


def doi(value, url=None, quote=None):
    return {"after": value, "evidence": [{"url": url or CR + value, "quote": quote or f'"DOI":"{value}"'}]}


def ev(after, url, quote):
    return {"after": after, "evidence": [{"url": url, "quote": quote}]}


# key -> {field: change}; "before" is read from the merged entry and frozen with its fingerprint.
FIXES = {
    # ---- PR #87 (add-feature-representation-refs)
    "YangEtal25a": {"volume": ev("2510.00183", AX + "2510.00183", "<id>http://arxiv.org/abs/2510.00183v2</id> "
                                 "(repository id belongs in volume; the DOI moves to doi)"),
                    "doi": doi("10.48550/arxiv.2510.00183", AX + "2510.00183", "arXiv 2510.00183v2, updated 2025-10-02")},
    "BauEtal17": {"ENTRYTYPE": ev("inproceedings", CR + "10.1109/cvpr.2017.354", '"type":"proceedings-article"'),
                  "doi": doi("10.1109/cvpr.2017.354", quote='"DOI":"10.1109/cvpr.2017.354", "page":"3319-3327"')},
    "DalaTrig05": {"ENTRYTYPE": ev("inproceedings", CR + "10.1109/cvpr.2005.177", '"type":"proceedings-article"'),
                   "doi": doi("10.1109/cvpr.2005.177", quote='"DOI":"10.1109/cvpr.2005.177", "volume":"1", "page":"886-893"')},
    "BindEtal16": {"number": ev("3--4", CR + "10.1080/02643294.2016.1147426", '"issue":"3-4"'),
                   "doi": doi("10.1080/02643294.2016.1147426")},
    "BrysEtal14": {"doi": doi("10.3758/s13428-013-0403-5")},
    "BrysNew09": {"doi": doi("10.3758/brm.41.4.977")},
    "HaleEtal09": {"doi": doi("10.1109/mis.2009.36")},
    "Lipt18": {"doi": doi("10.1145/3233231", quote='"DOI":"10.1145/3233231", "container-title":"Communications of the ACM", '
                          '"volume":"61", "issue":"10", "page":"36-43"')},
    "Lowe04": {"doi": doi("10.1023/b:visi.0000029664.99615.94")},
    "McRaEtal05": {"doi": doi("10.3758/bf03192726")},
    "Rudi19": {"doi": doi("10.1038/s42256-019-0048-x")},
    "HassEtal12": {"doi": doi("10.1016/j.tics.2011.12.007")},
    "StepEtal10": {"doi": doi("10.1073/pnas.1008662107")},
    "SilbEtal14": {"doi": doi("10.1073/pnas.1323812111")},
    "ElhaEtal22": {"doi": doi("10.48550/arxiv.2209.10652", AX + "2209.10652", "arXiv 2209.10652v1 (only version)")},
    "KaplEtal20": {"doi": doi("10.48550/arxiv.2001.08361", AX + "2001.08361", "arXiv 2001.08361v1 (only version)")},
    "WangEtal22": {"year": ev("2024", AX + "2212.03533", "<id>http://arxiv.org/abs/2212.03533v2</id> "
                              "<updated>2024-02-22T06:21:51Z</updated> (latest version)"),
                   "doi": doi("10.48550/arxiv.2212.03533", AX + "2212.03533", "arXiv 2212.03533v2")},
    "YangEtal25b": {"author": ev(QWEN_HOUSE, AX + "2505.09388", "60 <name> elements: " + QWEN),
                    "doi": doi("10.48550/arxiv.2505.09388", AX + "2505.09388", "arXiv 2505.09388v1 (only version)")},
    "Sips13": {"edition": ev("3\\textsuperscript{rd}", "https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&recordSchema=mods"
                             "&query=bath.title%3D%22introduction%20to%20the%20theory%20of%20computation%22",
                             "LCCN 2012938665 (Sipser, Michael, 2013): <edition>Third edition.</edition>")},
    "SchaAbel77": {"title": ev("Scripts, plans, goals, and understanding: an inquiry into human knowledge structures",
                               "https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&recordSchema=mods"
                               "&query=bath.title%3D%22scripts%2C%20plans%2C%20goals%2C%20and%20understanding%22",
                               "LCCN 76051963 (Schank, Roger C., 1977): <title>Scripts, plans, goals, and understanding</title>; "
                               "subtitle 'an inquiry into human knowledge structures' (PR check: LoC record)")},
    "Mann26": {"author": ev("J R Manning and {Claude}", "https://api.datacite.org/dois/10.5281/zenodo.19094654",
                            "creators: 'Jeremy R. Manning', 'Claude'")},
    "Chom56": {"doi": doi("10.1109/tit.1956.1056813")},
    "ChomMill58": {"doi": doi("10.1016/s0019-9958(58)90082-2")},
    "Chom59": {"doi": doi("10.1016/s0019-9958(59)90362-6")},
    "ReimGure19": {"doi": doi("10.18653/v1/d19-1410")},
    # ---- PR #88 (nightwarden-refs)
    "KothEtal25": {"pages": ev("IMAG.a.136", CR + "10.1162/imag.a.136", '"article-number":"IMAG.a.136"'),
                   "doi": doi("10.1162/imag.a.136")},
    "KonkEtal21": {"pages": ev("1417--1427.e6", CR + "10.1016/j.cub.2021.01.026", '"page":"1417-1427.e6"')},
    "ChenEtal21": {"pages": ev("4293--4304.e5", CR + "10.1016/j.cub.2021.07.061", '"page":"4293-4304.e5"')},
    "SchwEtal22": {"pages": ev("4808--4816.e4", CR + "10.1016/j.cub.2022.09.032", '"page":"4808-4816.e4"')},
    "Beli92": {"doi": doi("10.1037/0021-843x.101.3.592", quote='"DOI":"10.1037/0021-843x.101.3.592" (APA twin '
                          '10.1037//0021-843x.101.3.592 is the same article; the single-slash form is used)')},
    "KrakEtal02": {"doi": doi("10.1016/s0887-6185(02)00093-2")},
    "Niel17": {"doi": doi("10.3389/fneur.2017.00201")},
    "StroEtal25": {"doi": doi("10.48550/arxiv.2510.21958", AX + "2510.21958", "arXiv 2510.21958v1 (only version)")},
    "VallWalk21": {"doi": doi("10.7554/elife.70092")},
    # ---- Aust14 (Claude's fix, not the user's: Claude's agent instruction of 2026-09-25 11:10 EDT
    #      said to fix the publisher to the real firm; awaiting user confirmation)
    "Aust14": {"publisher": ev("T Egerton", "verification/baseline.jsonl.gz: Aust14 loc-catalogue candidate (LoC MARCXML, field 264)",
                               "<subfield code=\"b\">Printed for T. Egerton, Military Library, Whitehall,</subfield> "
                               "<subfield code=\"c\">1814.</subfield>; 700 'Egerton, Thomas (Bookseller)'"),
               "author": ev("J Austen", "verification/baseline.jsonl.gz: Aust14 loc-catalogue candidate", "house rule: initials (user 2026-09-24)")},
}
RENAMES = {"WangEtal22": "WangEtal24", "Mann26": "MannClau26"}
MERGE_BASES = {"87": "origin/add-feature-representation-refs", "88": "origin/nightwarden-refs"}


def pr_keys(branch):
    """Keys the PR added or edited relative to its merge base with master."""
    env = {"DEVELOPER_DIR": "/Library/Developer/CommandLineTools", "PATH": "/usr/bin:/bin"}
    base = subprocess.run(["git", "merge-base", "master", branch], capture_output=True, text=True, env=env,
                          check=True).stdout.strip()
    tmp = HERE / ".tmp"
    tmp.mkdir(exist_ok=True)
    for name, ref in (("base", base), ("pr", branch)):
        (tmp / f"{name}.bib").write_text(subprocess.run(["git", "show", f"{ref}:cdl.bib"], capture_output=True,
                                                        text=True, env=env, check=True).stdout)
    old, new = load_entries(tmp / "base.bib"), load_entries(tmp / "pr.bib")
    for name in ("base", "pr"):
        (tmp / f"{name}.bib").unlink()
    tmp.rmdir()
    return sorted(k for k, e in new.items() if k not in old or old[k]["fields"] != e["fields"])


def main():
    entries = load_entries(ROOT / "cdl.bib")
    proposals = []
    for key, changes in FIXES.items():
        entry = entries[key]
        fields = entry["fields"]
        frozen = {}
        for field, change in changes.items():
            before = fields.get(field)
            if before == change["after"]:
                continue
            frozen[field] = {"before": before, **change}
        row = {"key": key, "fingerprint": entry["fingerprint"], "kind": "edit",
               "pr": "87" if list(FIXES).index(key) < list(FIXES).index("KothEtal25") else
                     ("88" if key != "Aust14" else None), "changes": frozen}
        if key in RENAMES:
            row["rename"] = RENAMES[key]
        proposals.append(row)
    fixed = {p["key"] for p in proposals}
    verify = {}
    for pr, branch in MERGE_BASES.items():
        for key in pr_keys(branch):
            verify.setdefault(key, pr)
    out = {"batch": "prfix001", "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "count": len(proposals),
           "skipped": {}, "pr_keys": verify, "proposals": proposals,
           "verify_keys": [{"key": k, "fingerprint": entries[k]["fingerprint"]} for k in sorted(verify) if k not in fixed]}
    (HERE / "prfix001-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(len(proposals), "fix proposals;", len(verify), "PR keys;", len(out["verify_keys"]), "verified unchanged")


if __name__ == "__main__":
    main()
