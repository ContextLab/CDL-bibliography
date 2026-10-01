"""One-off: turn bare imports of bibcheck modules into package imports.

    python scripts/rewrite_imports.py            # rewrite in place
    python scripts/rewrite_imports.py --check    # exit 1 if anything would change
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "cdlbib"
MODULES = sorted(p.stem for p in PKG.glob("*.py") if p.stem != "__init__")
NAMES = "|".join(map(re.escape, MODULES))

def rules(prefix_from, prefix_import):
    return [
        # from helpers import x          -> from .helpers import x / from cdlbib.helpers import x
        (re.compile(rf"^(\s*)from ({NAMES}) import "), rf"\1from {prefix_from}\2 import "),
        # import verification as v       -> from . import verification as v
        (re.compile(rf"^(\s*)import ({NAMES}) as (\w+)"), rf"\1from {prefix_import} import \2 as \3"),
        # import verification            -> from . import verification
        (re.compile(rf"^(\s*)import ({NAMES})(\s*(#.*)?)$"), rf"\1from {prefix_import} import \2\3"),
    ]

PATCH = re.compile(rf"""(setattr\(\s*["'])({NAMES})\.""")          # monkeypatch.setattr("verification.x", ...)
SYS_PATH = re.compile(r"""^\s*sys\.path\.insert\(0,\s*str\(.*["']bibcheck["']\s*\)\s*\)\s*(#.*)?$""")
GUARDED = re.compile(r"""^\s*if str\(ROOT / ["']bibcheck["']\) not in sys\.path:\s*$""")

def rewrite(path, table, tests):
    out, changed, skip_next = [], False, False
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        new = line
        if SYS_PATH.match(line) or GUARDED.match(line):
            new = ""
        else:
            for pattern, repl in table:
                new, n = pattern.subn(repl, new)
                if n:
                    break
            if tests:
                new = PATCH.sub(r"\1cdlbib.\2.", new)
        changed |= new != line
        out.append(new)
    if changed and "--check" not in sys.argv:
        path.write_text("".join(out), encoding="utf-8")
    return changed

changed = [p for p in sorted(PKG.glob("*.py")) if rewrite(p, rules(".", "."), False)]
outside = [*sorted((ROOT / "tests").glob("*.py")), *sorted((ROOT / "verification").rglob("*.py")),
           ROOT / "bibcheck.py", ROOT / "bibverify.py"]
changed += [p for p in outside if p.exists() and rewrite(p, rules("cdlbib.", "cdlbib"), True)]
print(f"{len(changed)} files " + ("would change" if "--check" in sys.argv else "rewritten"))
sys.exit(1 if changed and "--check" in sys.argv else 0)
