"""Local OCR discovery for PDFs whose ordinary text extraction failed.

OCR is fallible source evidence, never a citation approval. Neither the source
library nor the ordinary text index is changed. Cache identity includes the PDF
bytes, extraction settings and installed tool versions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from local_library import POLICY, file_hash, find_candidates


def extraction_profile():
    versions = {}
    for command in (["pdftoppm", "-v"], ["tesseract", "--version"]):
        result = subprocess.run(command, capture_output=True, timeout=10, check=True)
        versions[command[0]] = (result.stdout + result.stderr).decode("utf-8").splitlines()[0]
    return {"ocr_policy": 1, "pages": 3, "scale_to": 2400, "language": "eng",
            "page_segmentation": 3, "tools": versions}


def ocr_front(path, profile):
    with tempfile.TemporaryDirectory(prefix="bibcheck-ocr-") as directory:
        prefix = Path(directory) / "page"
        subprocess.run(["pdftoppm", "-f", "1", "-l", str(profile["pages"]),
                        "-scale-to", str(profile["scale_to"]), "-png", str(path), str(prefix)],
                       capture_output=True, timeout=90, check=True)
        images = sorted(Path(directory).glob("page-*.png"))
        if not 1 <= len(images) <= profile["pages"]:
            raise ValueError("Missing or unexpected rendered pages")
        pages = []
        for image in images:
            number = int(re.fullmatch(r"page-(\d+)\.png", image.name)[1])
            result = subprocess.run(["tesseract", str(image), "stdout", "-l", profile["language"],
                                     "--psm", str(profile["page_segmentation"])],
                                    capture_output=True, timeout=45, check=True)
            pages.append({"page": number, "text": result.stdout.decode("utf-8")})
        if not any(p["text"].strip() for p in pages):
            raise ValueError("OCR produced no text")
        if sum(len(p["text"]) for p in pages) > 300_000:
            raise ValueError("OCR front matter exceeds text limit")
        return pages


def index_failed_pdfs(base_index, output, *, profile=None, extractor=ocr_front,
                      retry_errors=False, progress=None):
    base_index = Path(base_index).resolve(strict=True)
    source_manifest = json.loads((base_index / "manifest.json").read_text())
    root = Path(source_manifest["root"]).resolve(strict=True)
    output = Path(output).resolve()
    if output == base_index or output == root or root in output.parents:
        raise ValueError("OCR output must be separate from the source library and base index")
    profile = extraction_profile() if profile is None else profile
    profile_hash = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
    objects = output / "objects"; objects.mkdir(parents=True, exist_ok=True)
    rows, extracted, reused = [], 0, 0
    failed = [r for r in source_manifest["files"] if r["status"] != "indexed"]
    for source in failed:
        row = {"path": source["path"], "source_kind": "ocr", "verification": "unverified"}
        try:
            path = (root / source["path"]).resolve(strict=True)
            if root not in path.parents:
                raise ValueError("Source path is outside the paper library")
            sha = file_hash(path)
            if sha != source.get("pdf_sha256"):
                raise ValueError("Source changed since text indexing; refresh the base index")
            destination = objects / f"{sha}-ocr-{profile_hash}.json"
            prior = json.loads(destination.read_text()) if destination.exists() else None
            if prior is not None and (prior.get("pdf_sha256") != sha or prior.get("profile") != profile):
                raise ValueError("Inconsistent OCR cache object")
            if prior is not None and not (retry_errors and prior.get("error")):
                record = prior; reused += 1
            else:
                record = {"pdf_sha256": sha, "policy": POLICY, "profile": profile,
                          "source_kind": "ocr", "verification": "unverified"}
                try:
                    record["pages"] = extractor(path, profile)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    record["error"] = f"{type(exc).__name__}: {exc}"
                if file_hash(path) != sha:
                    raise ValueError("Source changed during OCR; retry required")
                temporary = destination.with_suffix(".tmp")
                temporary.write_text(json.dumps(record, ensure_ascii=False) + "\n")
                temporary.replace(destination); extracted += 1
            row.update(pdf_sha256=sha, object=destination.name,
                       status="error" if record.get("error") else "indexed")
            if record.get("error"):
                row["error"] = record["error"]
        except (OSError, ValueError) as exc:
            row.update(status="unreadable", error=f"{type(exc).__name__}: {exc}")
        rows.append(row)
        if progress:
            progress({"processed": len(rows), "total": len(failed), "status": row["status"],
                      "extractions": extracted, "cache_hits": reused})
    manifest = {"root": str(root), "policy": POLICY, "profile": profile, "files": rows,
                "extractions": extracted, "cache_hits": reused, "source_kind": "ocr"}
    temporary = output / "manifest.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path(".bibcheck/local-library"))
    parser.add_argument("--output", type=Path, default=Path(".bibcheck/local-library-ocr"))
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--bibliography", type=Path)
    args = parser.parse_args(); started = time.monotonic()
    result = index_failed_pdfs(args.index, args.output, retry_errors=args.retry_errors,
                              progress=lambda r: print(json.dumps(r), flush=True))
    print(json.dumps({"seconds": round(time.monotonic() - started, 2),
                      "files": len(result["files"]), "extractions": result["extractions"],
                      "cache_hits": result["cache_hits"],
                      "errors": sum(r["status"] != "indexed" for r in result["files"])}), flush=True)
    if args.bibliography:
        from verification import load_entries
        found = find_candidates(args.output, load_entries(args.bibliography))
        (args.output / "candidates.json").write_text(json.dumps(found, indent=2) + "\n")
        print(json.dumps({"candidates": len(found), "entries": len({r["key"] for r in found})}), flush=True)


if __name__ == "__main__":
    main()
