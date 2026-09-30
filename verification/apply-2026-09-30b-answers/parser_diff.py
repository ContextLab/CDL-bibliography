"""Compare two parser_scan.py outputs (pre-fix code, fixed code) and write parser-fix-effect.json.

    python parser_diff.py OLD.json NEW.json
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
old, new = (json.loads(Path(p).read_text())["rows"] for p in sys.argv[1:3])
assert set(old) == set(new)
changed = {}
for key in sorted(old):
    a, b = old[key], new[key]
    if a == b:
        continue
    changed[key] = {
        "status_before_fix": a["status"], "status_after_fix": b["status"],
        "issues_removed": sorted(set(a.get("issues", [])) - set(b.get("issues", []))),
        "issues_added": sorted(set(b.get("issues", [])) - set(a.get("issues", []))),
        "candidate_issues_removed": sorted(set(a.get("candidate_issues", [])) - set(b.get("candidate_issues", []))),
        "candidate_issues_added": sorted(set(b.get("candidate_issues", [])) - set(a.get("candidate_issues", []))),
    }
out = {"entries": len(old),
       "errors_before_fix": sorted(k for k, r in old.items() if r["status"] == "error"),
       "errors_after_fix": sorted(k for k, r in new.items() if r["status"] == "error"),
       "status_changes": sorted(k for k, v in changed.items() if v["status_before_fix"] != v["status_after_fix"]),
       "changed": changed}
(HERE / "parser-fix-effect.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
print(json.dumps({k: v for k, v in out.items() if k != "changed"}), sorted(changed))
