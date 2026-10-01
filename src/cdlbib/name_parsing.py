"""BibTeX person-name splitting that keeps tilde accents inside the name.

BibTeX name splitting reads ``~`` as a space (a tie), so a tilde accent written outside
braces splits a surname: bibtexparser's ``splitname("I L Pi\\~{n}a")`` returns the first
names ``I L Pi\\`` and the surname ``{n}a``, and ``"A N\\'{u}\\~{n}ez"`` returns the
surname ``{n}ez`` (PollEtal00 and NuneEtal87; found by the 2026-09-30 surname scan,
verification/apply-2026-09-30-surnames/README.md). BibTeX itself treats a braced
``{\\~{n}}`` as one special character. ``splitname`` here braces every tilde accent that
sits at brace depth 0 (``\\~{n}`` and ``\\~n``) before splitting, so the accent stays in
its word. A bare ``~`` (a tie, ``J~Smith``) is still a space, and an accent already
inside braces (``Go{\\~n}i``) is left as written.
"""
from bibtexparser.customization import splitname as _bibtex_splitname

__all__ = ["protect_tilde_accents", "splitname"]


def protect_tilde_accents(name):
    """Brace each depth-0 tilde accent (``\\~{x}`` or ``\\~x``) so ``~`` is not a space."""
    out, depth, i = [], 0, 0
    while i < len(name):
        char = name[i]
        if char == "\\" and depth == 0 and name.startswith("\\~", i):
            j = i + 2
            if j < len(name) and name[j] == "{":
                close = name.find("}", j)
                if close != -1 and "{" not in name[j + 1:close]:
                    out.append("{" + name[i:close + 1] + "}")
                    i = close + 1
                    continue
            elif j < len(name) and name[j].isalpha():
                out.append("{" + name[i:j + 1] + "}")
                i = j + 1
                continue
        if char == "\\":
            out.append(name[i:i + 2])
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        out.append(char)
        i += 1
    return "".join(out)


def splitname(name, strict_mode=True):
    """``bibtexparser.customization.splitname`` with depth-0 tilde accents kept in their word."""
    return _bibtex_splitname(protect_tilde_accents(name), strict_mode=strict_mode)
