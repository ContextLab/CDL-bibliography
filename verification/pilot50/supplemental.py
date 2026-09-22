"""Serial, restartable source retrieval; never creates verification decisions."""

import json
from pathlib import Path
import time
import requests
import xml.etree.ElementTree as ET
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bibcheck"))
from search_tools import get_source

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / ".bibcheck/pilot50/sources"

EXTRA = {
    "TianEtal16a": "https://www.cs.dartmouth.edu/~xia/publication/mobicom16-darklight/mobicom16-darklight.pdf",
    "CarvEtal22a": "https://par.nsf.gov/servlets/purl/10340818",
    "AherBeat81": "https://link.springer.com/chapter/10.1007/978-1-4684-1083-9_9",
    "Scha03": "https://link.springer.com/chapter/10.1007/978-0-387-21579-2_9",
    "Cohe90": "https://bpspsychub.onlinelibrary.wiley.com/doi/abs/10.1111/j.2044-8295.1990.tb02362.x",
    "WickNorm66": "https://www.sciencedirect.com/science/article/abs/pii/0022249666900186",
    "WitmEtal96": "https://www.sciencedirect.com/science/article/pii/S1071581996900609",
    "Lang05": "https://www.sciencedirect.com/science/article/pii/S0749596X05000847",
}


def extra_sources(session):
    for key, url in EXTRA.items():
        meta = DIRECTORY / (key + "-extra.json")
        if meta.exists():
            continue
        try:
            if key in ("TianEtal16a", "CarvEtal22a"):
                time.sleep(1)
                response = session.get(url, timeout=(10, 40), allow_redirects=False)
                response.raise_for_status()
                if not response.content.startswith(b"%PDF"):
                    raise ValueError("Not a PDF")
                (DIRECTORY / (key + ".pdf")).write_bytes(response.content)
                result = {"status": "retrieved", "url": url, "format": "pdf"}
            else:
                body, final = get_source(
                    session, url, {urlparse(url).hostname, "link.springernature.com"}
                )
                (DIRECTORY / (key + "-extra.html")).write_text(body)
                result = {"status": "retrieved", "url": final, "format": "html"}
        except (requests.RequestException, ValueError) as exc:
            result = {"status": "unavailable", "url": url, "error": str(exc)}
        meta.write_text(json.dumps(result, indent=2))
        print(key, result["status"], flush=True)


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "CDL-bibliography citation verification pilot"
    extra_sources(session)
    rows = json.loads(Path(__file__).with_name("manifest.json").read_text())["entries"]
    for i, row in enumerate(rows, 1):
        prior = json.loads((DIRECTORY / (row["key"] + "-prior.json")).read_text())
        record = next(
            (c["raw_record"] for c in prior if c.get("source") == "europepmc"), None
        )
        if record:
            # The registry record is an alternative source, not original article text.
            (DIRECTORY / (row["key"] + "-registry.json")).write_text(
                json.dumps(record, indent=2, ensure_ascii=False)
            )
        pmcid = (record or {}).get("pmcid")
        if not pmcid:
            continue
        path = DIRECTORY / (row["key"] + "-fulltext.json")
        if path.exists():
            print(f"{i}/50 {row['key']}: cached fulltext", flush=True)
            continue
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        time.sleep(1)
        response = session.get(url, timeout=(10, 40), allow_redirects=False)
        result = {"url": url, "http_status": response.status_code}
        if response.status_code == 200:
            ET.fromstring(response.content)
            (DIRECTORY / (row["key"] + ".xml")).write_bytes(response.content)
        path.write_text(json.dumps(result, indent=2))
        print(f"{i}/50 {row['key']}: fulltext {response.status_code}", flush=True)


if __name__ == "__main__":
    main()
