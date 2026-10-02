"""Rebuild records.json from the saved case files beside this folder. No network.

Each record is copied from a case file that holds real saved Crossref and Europe PMC
responses. The one alteration: an e-mail address inside a record's text (PubMed prints the
corresponding author's in the affiliation) is replaced by "[address removed]". Run from the
repository root:

    python tests/fixtures/completion/extract_records.py
"""
import gzip
import json
from pathlib import Path
import re

FIXTURES = Path(__file__).resolve().parents[1]

WANTED = [  # (name in records.json, case file, case key, DOI of the record)
    ("MoheEtal14", "pagination_corrections.json", "MoheEtal14", "10.1177/0956797613511257"),
    ("Zoll90", "phase0_cases.json.gz", "Zoll90", "10.1002/tea.3660271011"),
    ("Game62", "phase0_cases.json.gz", "Game62", "10.1037/h0041332"),
    ("KoelEtal16", "phase0_cases.json.gz", "KoelEtal16", "10.1038/srep19741"),
    ("FiedGloc12", "phase0_cases.json.gz", "FiedGloc12", "10.3389/fpsyg.2012.00335"),
    ("LindEtal21", "phase0_cases.json.gz", "LindEtal21", "10.1017/s1355617720001009"),
    ("Knut07", "phase0_cases.json.gz", "Knut07", "10.1519/r-505011.1"),
    ("AlyTurk16", "fixes-2026-09-24-cases.json.gz", "AlyTurk16", "10.1073/pnas.1518931113"),
    ("ChenEtal21", "machinery-2026-09-25-cases.json.gz", "ChenEtal21", "10.1016/j.cub.2021.07.061"),
    ("Schr03", "machinery-2026-09-25-cases.json.gz", "Schr03", "10.1007/s00406-003-0438-1"),
    ("PigeEtal12", "machinery-2026-09-25-cases.json.gz", "PigeEtal12", "10.4088/jcp.11r07586"),
    ("CleeMcCl91", "apply-2026-09-25-cases.json.gz", "CleeMcCl91", "10.1037/0096-3445.120.3.235"),
    ("all-capitals-title", "phase0_cases.json.gz", "Raic06", "10.1146/annurev.neuro.29.051605.112819"),
    ("erratum", "phase0_cases.json.gz", "HarrEtal20", "10.1038/s41592-020-0772-5"),
    ("corporate-author", "phase0_cases.json.gz", "HarrEtal20", "10.1038/s41592-019-0686-2"),
    ("book-chapter", "apply-2026-09-25d-cases.json.gz", "AltmSchu02", "10.4324/9781315782379-49"),
    ("preprint", "fixes-2026-09-24-cases.json.gz", "AlyTurk16", "10.1101/511782"),
    ("sentence-case-proper-noun", "phase0_cases.json.gz", "Pike84", "10.1037/0033-295x.92.1.130"),
]
# The entry as it stood in cdl.bib when the case was saved (the typed side of a test).
WITH_TYPED_ENTRY = {"CleeMcCl91"}
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def without_addresses(value):
    if isinstance(value, str):
        return ADDRESS.sub("[address removed]", value)
    if isinstance(value, list):
        return [without_addresses(v) for v in value]
    if isinstance(value, dict):
        return {k: without_addresses(v) for k, v in value.items()}
    return value


def load(name):
    path = FIXTURES / name
    return json.loads(gzip.open(path).read() if name.endswith(".gz") else path.read_text(encoding="utf-8"))


def main():
    out = {}
    for name, filename, key, doi in WANTED:
        data = load(filename)
        case = data.get("cases", data)[key]
        item = {"doi": doi, "origin": {"file": "tests/fixtures/" + filename, "case": key}}
        if "record" in case:  # a case that stores the one Crossref record directly
            assert case["record"]["DOI"].lower() == doi
            item["crossref"] = {"record": case["record"], "retrieved_at": None, "url": None}
            item["origin"]["file_source"] = data["source"]
        else:
            candidates = case["previous"]["candidates"]
            crossref = sorted((c for c in candidates if c["source"] == "crossref" and c["doi"].lower() == doi),
                              key=lambda c: c["retrieved_at"])
            latest = crossref[-1]
            item["crossref"] = {"record": latest["record"], "retrieved_at": latest["retrieved_at"],
                                "url": latest["url"]}
            pubmed = sorted((c for c in candidates if c["source"] == "europepmc" and c.get("raw_record")
                             and (c.get("doi") or "").lower() == doi), key=lambda c: c["retrieved_at"])
            assert len({c["raw_record"]["id"] for c in pubmed}) <= 1
            if pubmed:
                latest = pubmed[-1]
                item["europepmc"] = {"raw_record": latest["raw_record"], "retrieved_at": latest["retrieved_at"],
                                     "url": latest["url"], "request_url": latest.get("request_url")}
            if name in WITH_TYPED_ENTRY:
                item["typed"] = case["entry"]["fields"]
        out[name] = item
    text = json.dumps(without_addresses(out), indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    assert "mailto" not in text and "�" not in text and not ADDRESS.search(text)
    (Path(__file__).parent / "records.json").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
