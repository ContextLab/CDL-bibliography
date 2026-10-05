"""PDFs for the intake tests, made at test time by real tools (pdflatex, pypdf, Ghostscript).

Nothing is committed as a binary: each PDF is typeset from the LaTeX source below, so what
a test expects to read is what the source says. tests/fixtures/intake/record_lookups.py
builds the same files to record the lookups they lead to.
"""
from pathlib import Path
import shutil
import subprocess

ZOLLER_TITLE = "Students' misunderstandings and misconceptions in college freshman chemistry (general and organic)"
ZOLLER_DOI = "10.1002/tea.3660271011"
MURDOCK_TITLE = "Backward learning in paired associates"
ARXIV_ID = "1706.03762"
ARXIV_TITLE = "Attention Is All You Need"
OTHER_TITLE = "Seasonal variation in the song repertoire of an imaginary warbler"
UNKNOWN_TITLE = "Plorbnix dynamics in zzyzxqv lattices under qwxzvk forcing"

_PAGE = r"""\documentclass[11pt]{article}
\usepackage[T1]{fontenc}
\usepackage[margin=1in]{geometry}
\usepackage{graphicx}
%(preamble)s
\begin{document}
\thispagestyle{empty}
%(stamp)s
\noindent{\small %(header)s}

\vspace{2em}
\begin{center}
{\LARGE\bfseries %(title)s\par}
\vspace{1.5em}
{\large %(authors)s\par}
\vspace{0.5em}
{\small %(affiliation)s\par}
\end{center}
\vspace{1em}
\noindent\textbf{Abstract.} %(abstract)s

\section{Introduction}
%(body)s
\newpage
\section{Method}
%(body)s
\section*{References}
\noindent Someone, A. (1999). Another work entirely. \emph{Journal of Other Things}, 3, 1--9. doi:10.9999/not.this.one
\end{document}
"""

_BODY = ("The study reported here was carried out over two terms. Participants were given written problems "
         "and their answers were scored by two readers working independently. ") * 6

SOURCES = {
    # A DOI printed on page 1, under the journal's running head.
    "doi": dict(title=ZOLLER_TITLE, authors="Uri Zoller", affiliation="Haifa University, Israel",
                header=r"J. Res. Sci. Teach. 27(10), 1053--1065 (1990) \hfill DOI: " + ZOLLER_DOI),
    # An arXiv stamp, as arXiv prints it: large, turned, in the left margin.
    "arxiv": dict(title=ARXIV_TITLE, authors="Ashish Vaswani, Noam Shazeer and Niki Parmar",
                  affiliation="Google Brain", header="Provided proper attribution is provided",
                  stamp=r"\noindent\makebox[0pt][r]{\rotatebox{90}{\Huge arXiv:" + ARXIV_ID
                        + r"v7 [cs.CL] 2 Aug 2023}\hspace{2em}}"),
    # No identifier anywhere: only the title, and the author in the PDF's metadata.
    "title": dict(title=MURDOCK_TITLE, authors="Bennet B. Murdock, Jr.", affiliation="University of Vermont",
                  header="Journal of Experimental Psychology", preamble=r"\pdfinfo{/Author (Bennet B. Murdock)}"),
    # No identifier either, but the title and the metadata's author name exactly one record.
    "titled": dict(title=ZOLLER_TITLE, authors="Uri Zoller", affiliation="Haifa University, Israel",
                   header="Journal of Research in Science Teaching", preamble=r"\pdfinfo{/Author (Uri Zoller)}"),
    # Another paper that prints someone else's DOI on its first page.
    "mismatch": dict(title=OTHER_TITLE, authors="A. N. Author", affiliation="Nowhere College",
                     header="Reprinted with a comment on doi:" + ZOLLER_DOI),
    # A paper no source knows.
    "unknown": dict(title=UNKNOWN_TITLE, authors="Ada Q. Example and Bo R. Sample",
                    affiliation="Department of Imaginary Physics, Nowhere College",
                    header=r"\emph{Annals of Improbable Lattices}, vol.~12 (2031) 45--67"),
}


def pdflatex():
    return shutil.which("pdflatex") or (Path("/opt/homebrew/bin/pdflatex").exists() and "/opt/homebrew/bin/pdflatex")


def build(name, folder):
    """Typeset SOURCES[name] into <folder>/<name>.pdf with pdflatex; returns the path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    values = dict(preamble="", stamp="", abstract="We describe what was done and what was found.", body=_BODY)
    values.update(SOURCES[name])
    (folder / f"{name}.tex").write_text(_PAGE % values, encoding="utf-8")
    done = subprocess.run([pdflatex(), "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", f"{name}.tex"],
                          cwd=folder, capture_output=True, text=True, timeout=120,
                          env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/Library/TeX/texbin", "HOME": str(folder),
                               "SOURCE_DATE_EPOCH": "1700000000", "FORCE_SOURCE_DATE": "1"})
    if done.returncode != 0 or not (folder / f"{name}.pdf").exists():
        raise RuntimeError("pdflatex failed:\n" + done.stdout[-2000:])
    return folder / f"{name}.pdf"


def encrypted(source, target, user_password="secret", owner_password="owner"):
    """A real RC4-encrypted copy of ``source`` (pypdf's writer)."""
    import pypdf
    writer = pypdf.PdfWriter(clone_from=str(source))
    writer.encrypt(user_password=user_password, owner_password=owner_password, algorithm="RC4-128")
    with open(target, "wb") as handle:
        writer.write(handle)
    return Path(target)


def image_only(source, target):
    """``source`` with every page turned into one picture (Ghostscript's pdfimage24): a scan."""
    done = subprocess.run([shutil.which("gs"), "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfimage24",
                           "-r200", "-dLastPage=2", f"-sOutputFile={target}", str(source)],
                          capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError("gs failed: " + done.stderr[-1000:])
    return Path(target)
