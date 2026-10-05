# LaTeX setup and export

`cdlbib setup` makes the library's `cdl.bib` available to every LaTeX manuscript on the
computer. `cdlbib export` writes the entries one paper cites as a `.bib` of its own, or
the paper's compiled `.bbl`. `cdlbib setup --help` and `cdlbib export --help` list the
options.

- [Link `cdl.bib` into the TeX tree](#link-cdlbib-into-the-tex-tree)
- [Check, remove or replace the link](#check-remove-or-replace-the-link)
- [The `BIBINPUTS` alternative](#the-bibinputs-alternative)
- [Export the cited entries as a `.bib`](#export-the-cited-entries-as-a-bib)
- [Export the compiled `.bbl`](#export-the-compiled-bbl)
- [Messages when an input is missing](#messages-when-an-input-is-missing)
- [What `export --bbl` does not run](#what-export---bbl-does-not-run)
- [In the web interface](#in-the-web-interface)

The output shown was recorded with `cdlbib 2.0.0` on October 5, 2026, on macOS with TeX
Live, in a temporary folder with a copy of the bibliography chosen with `--library` and
with `TEXMFHOME` set to a folder inside it. `~/demo` stands for that temporary folder and
`@you` for the GitHub login. The global option `--library ~/demo/library`, which came
before the command name in each recorded command, is left out of the commands below.

In [the terminal interface](terminal-interface.md) (`cdlbib tui`), the Setup view (`F8`)
shows the state of the link. `l` makes the link and `x` removes it. To export, type the
paper's path in the form of that view and press `b` for the `.bib` or `B` for the `.bbl`.

## Link `cdl.bib` into the TeX tree

```bash
cdlbib setup
```

`setup` makes one symbolic link, `bibtex/bib/cdl.bib` in your personal TeX tree, that
points to the `cdl.bib` of the library in use. The personal TeX tree is the first folder
that `kpsewhich` reports for `TEXMFHOME`. When TeX is not installed, it is the `TEXMFHOME`
environment variable, or `~/Library/texmf` on macOS and `~/texmf` elsewhere. The link
names the file's path, so it stays valid when the library is updated. `cdlbib` records the
link it made in `tex-link.json` in its data folder.

`setup` first prints two progress lines, then the report:

```text
asking gh who is logged in (gh api user) ...
reading the system keychain for the Dartmouth Chat key ...
library: ~/demo/library
chosen by: --library
TeX tree: ~/demo/texmf
link: ~/demo/texmf/bibtex/bib/cdl.bib -> ~/demo/library/cdl.bib
linked ~/demo/texmf/bibtex/bib/cdl.bib -> ~/demo/library/cdl.bib
state: linked: TeX finds this library's cdl.bib from any folder (\bibliography{cdl} or \addbibresource{cdl.bib})
kpsewhich cdl.bib: ~/demo/texmf/bibtex/bib/cdl.bib
available on this computer:
  git: yes (/usr/bin/git)
  gh login: yes (@you)
  TeX: yes (/opt/homebrew/bin/kpsewhich)
  bibtex: yes (/opt/homebrew/bin/bibtex)
  biber: yes (/opt/homebrew/bin/biber)
  pypdf: yes (installed)
```

The list under `available on this computer:` continues with one line for each API key and
optional package. A line that says `no` ends with how to set that item up. The command
exits with `0` when the state is `linked`.

From any other folder, `kpsewhich` then finds the linked file:

```bash
kpsewhich cdl.bib
```

```text
~/demo/texmf/bibtex/bib/cdl.bib
```

A manuscript refers to it by name. For BibTeX:

```latex
\bibliographystyle{plain} % or the style required by your venue
\bibliography{cdl}
```

For `biblatex`, use `\addbibresource{cdl.bib}`.

In a folder that holds its own `cdl.bib`, `kpsewhich cdl.bib` prints `./cdl.bib`: that
file is found before the linked one.

With `cdlbib --ask setup`, the command asks before making the link. Without a terminal
it makes no link, prints the line below and exits with `1`:

```text
the link was not made (not confirmed); `cdlbib setup` without --ask makes it
```

## Check, remove or replace the link

`--check` prints the same report and changes nothing in the TeX tree. As with every
command, the library `cdlbib` manages is downloaded or updated first when it is the one in
use. It exits with `1` when `cdl.bib` is not linked. Before the link was made:

```bash
cdlbib setup --check
```

```text
TeX tree: ~/demo/texmf
link: ~/demo/texmf/bibtex/bib/cdl.bib
state: not linked
kpsewhich cdl.bib: not found
without a link, this shell line does the same (cdlbib does not write it anywhere): export BIBINPUTS="~/demo/library:${BIBINPUTS}"
```

`--remove` removes the link that `cdlbib` made:

```bash
cdlbib setup --remove
```

```text
removed ~/demo/texmf/bibtex/bib/cdl.bib
```

Run again, it prints:

```text
nothing removed at ~/demo/texmf/bibtex/bib/cdl.bib: there is no link
```

If a `cdl.bib` that `cdlbib` did not make is already at the link's place, `setup` leaves
it there, prints the report with the state below, and exits with `1`:

```text
state: not linked: ~/demo/texmf/bibtex/bib/cdl.bib exists and was not made by cdlbib
```

The last line it prints is:

```text
~/demo/texmf/bibtex/bib/cdl.bib exists and was not made by cdlbib; it was left as it is. With replace, it is moved aside to cdl.bib.cdlbib-saved-<time> in the same folder and the link is made. Run: cdlbib setup --replace
```

`--replace` moves that file aside and makes the link. The file is kept:

```bash
cdlbib setup --replace
```

```text
moved the existing ~/demo/texmf/bibtex/bib/cdl.bib aside to ~/demo/texmf/bibtex/bib/cdl.bib.cdlbib-saved-20261005T091208Z
linked ~/demo/texmf/bibtex/bib/cdl.bib -> ~/demo/library/cdl.bib
```

`--check`, `--remove` and `--replace` cannot be combined.

If the `BIBINPUTS` environment variable makes TeX find another file first, or stops TeX
from searching the TeX trees, the report says so. With `BIBINPUTS=/nonexistent`:

```text
state: linked, but TeX does not resolve cdl.bib to it
kpsewhich cdl.bib: not found
kpsewhich does not find cdl.bib: BIBINPUTS is set to '/nonexistent' with no empty component, so the TeX trees are not searched for .bib files
```

In that state `setup` exits with `1`.

## The `BIBINPUTS` alternative

When `cdl.bib` is not linked, the report includes a shell line that makes TeX search the
library's folder for `.bib` files:

```text
without a link, this shell line does the same (cdlbib does not write it anywhere): export BIBINPUTS="~/demo/library:${BIBINPUTS}"
```

`cdlbib` does not add this line to any file. To use it, put it in the startup file your
shell reads. The [README](../../README.md#using-the-bibtex-file-as-a-common-bibliography-for-all-local-latex-files)
describes this method and the manual link.

## Export the cited entries as a `.bib`

The example paper is `~/demo/paper/main.tex`:

```latex
\documentclass{article}
\begin{document}
Memory search \cite{MannEtal11} and chemistry \cite{Zoll90}.
\bibliographystyle{plain}
\bibliography{cdl}
\end{document}
```

Name the paper by its folder, its main `.tex` file, or a `.aux` or `.bcf` file:

```bash
cdlbib export ~/demo/paper
```

```text
citations read from a fresh LaTeX run of the paper: 2 keys
wrote ~/demo/paper/cdl.bib: 2 entries from ~/demo/library/cdl.bib
```

The output file is `cdl.bib` beside the paper unless `--out FILE` (or `-o FILE`) names
another. An existing output file is not replaced:

```text
Not written: ~/demo/paper/cdl.bib already exists; --force replaces it.
```

```bash
cdlbib export ~/demo/paper/main.tex --out ~/demo/paper/refs.bib --force
```

```text
citations read from a fresh LaTeX run of the paper: 2 keys
wrote ~/demo/paper/refs.bib: 2 entries from ~/demo/library/cdl.bib
```

The first line says where the citations were read from. Given a `.aux` file, they are
read from that file:

```bash
cdlbib export ~/demo/paper/main.aux --out ~/demo/p7/from-aux.bib
```

```text
citations read from the .aux file: 2 keys
wrote ~/demo/p7/from-aux.bib: 2 entries from ~/demo/library/cdl.bib
```

A paper with `\nocite{*}` exports every entry:

```text
citations read from a fresh LaTeX run of the paper: 0 keys and \nocite{*} (every entry)
```

When the paper cannot be compiled, the citations are read from the `.tex` source and a
line says so. Here the paper loads a package, `labmacros.sty`, that is not installed, and
cites a key that is not in the library:

```text
citations read from the .tex source: 2 keys
the paper could not be compiled (pdflatex could not find: labmacros.sty. Supply the file, or the folder that holds it, as an input (--inputs PATH).); citations were read from the source; citations made by custom macros are not seen
wrote ~/demo/paper2/cdl.bib: 1 entry from ~/demo/library/cdl.bib
cited, but not in the library: NotInLibrary99
```

The command exits with `1` when a cited key is not in the library. The entries that were
found are still written.

When a folder holds several `.tex` files with a `\documentclass`, name the main one with
`--main`:

```text
~/demo/paper2 holds several files with a \documentclass: main.tex, notes.tex. Name the main one (--main FILE).
```

```bash
cdlbib export ~/demo/paper2 --main main.tex
```

An export is not written onto the library's own file:

```text
Not written: ~/demo/library/cdl.bib is the library's own file.
```

## Export the compiled `.bbl`

`--bbl` runs LaTeX and then BibTeX or biber on a temporary copy of the paper's files, and
writes the `.bbl`. It needs a TeX installation.

```bash
cdlbib export ~/demo/paper --bbl
```

```text
wrote ~/demo/paper/main.bbl: bibtex, style plain, pdflatex, 2 cited keys
cdl.bib in the paper's folder was used as it is
```

The first line names the output file, the program that made the bibliography, the
bibliography style, and the LaTeX program. The second line appears when the paper's
folder already holds a `cdl.bib`, such as the one written by `cdlbib export` above. The
output file is the paper's name with `.bbl` unless `--out` names another, and an existing
file is replaced only with `--force`.

A paper that uses `biblatex` with biber is compiled with biber:

```text
wrote ~/demo/p5/main.bbl: biber, pdflatex, 1 cited key
```

`--engine` chooses the LaTeX program: `pdflatex`, `xelatex`, `lualatex` or `latex`.
Without it, the program the paper asks for is used, otherwise `pdflatex`.

```bash
cdlbib export ~/demo/paper --bbl --engine xelatex --out ~/demo/paper/x.bbl
```

```text
wrote ~/demo/paper/x.bbl: bibtex, style plain, xelatex, 2 cited keys
cdl.bib in the paper's folder was used as it is
```

Another name is refused:

```text
tectonic is not one of the LaTeX programs used here: pdflatex, latex, lualatex, xelatex.
```

## Messages when an input is missing

A `.bbl` is compiled only when every style and class file the paper needs is found. A
missing file is named, and no style is chosen in its place. Each of these messages ends
the command with exit status `1`.

A package the paper loads is not installed:

```text
pdflatex could not find: labmacros.sty. Supply the file, or the folder that holds it, as an input (--inputs PATH).
```

The bibliography style is not installed:

```text
BibTeX could not find: labstyle.bst. Supply the file, or the folder that holds it, as an input (--inputs PATH).
```

`--inputs` names such a file, or a folder that holds it. Repeat the option for several.

```bash
cdlbib export ~/demo/p3 --bbl --inputs ~/demo/styles3
```

```text
wrote ~/demo/p3/main.bbl: bibtex, style labstyle, pdflatex, 1 cited key
```

A style installed in your personal TeX tree is found without `--inputs`. With
`treestyle.bst` in `~/demo/texmf/bibtex/bst/lab/`:

```text
wrote ~/demo/p3/main.bbl: bibtex, style treestyle, pdflatex, 1 cited key
```

The paper names a bibliography but no style:

```text
main.tex names a bibliography but no \bibliographystyle (and does not use biblatex), so there is no style to compile a .bbl with. No style is chosen for it.
```

The paper cites a key that no bibliography of the paper has:

```text
Cited, but in no bibliography of the paper: NotInLibrary99.
```

A `.aux` file was given, and its `.tex` file is not beside it:

```text
A .bbl is compiled from the paper's .tex file; ~/demo/p8/main.tex is not there. Give the .tex file or its folder.
```

## What `export --bbl` does not run

A paper that asks for LuaLaTeX (for example with `\usepackage{luacode}`) is not compiled
with LuaLaTeX unless `--engine lualatex` is given:

```text
main.tex asks for lualatex, which is not run unless it is named: Lua code in a document can read and write files. To compile it with LuaLaTeX, pass --engine lualatex.
```

```bash
cdlbib export ~/demo/p4 --bbl --engine lualatex
```

```text
wrote ~/demo/p4/main.bbl: bibtex, style plain, lualatex, 1 cited key
cdl.bib in the paper's folder was used as it is
```

For the same paper, `cdlbib export` without `--bbl` reads the citations from the `.tex`
source, prints the message above followed by `Not compiled`, and writes the `.bib`.

A `biblatex` source map whose match or replacement contains code is refused. For a paper
that declares a map with the match `\regexp{T(?{ system('true') })}`:

```text
The control file LaTeX wrote for biber is not used: the paper, or the bibliography style it loads, declares a source map whose match or replacement holds more than a plain regular expression or plain text with $1..$9 (map_match: T(?{system('true')})); biber would run it as Perl. No .bbl was compiled.
```

`cdlbib export` without `--bbl` still writes the `.bib` for that paper.

## In the web interface

The **Setup** view of [the web interface](web-interface.md) shows the same report. Its
"cdl.bib for every manuscript" panel shows the TeX tree, the link, the state and what
`kpsewhich cdl.bib` gives. Its button is "Link cdl.bib into the TeX tree" when there is
no link and "Remove the link" when there is one. When the link names another library, the
state is "linked to another library" and both buttons are shown. "Remove the link" asks
first ("Only the link cdlbib made is removed.") and then reports, for example,
`removed ~/demo/texmf/bibtex/bib/cdl.bib`.

![The Setup view of the web interface: a table headed "Available on this computer" with a row each for git, gh login, TeX, bibtex, biber, pypdf, Dartmouth Chat key, OpenAI key and textual, the columns "What was found" and "How to set it up", "check" buttons beside the rows that were not checked, and a "Check everything" button](../media/web-setup.png)

The "A paper's own .bib" panel takes uploaded `.tex`, `.aux` or `.bcf` files and gives
the `.bib` of the cited entries as a download. The web interface does not make a `.bbl`.
The panel says:

```text
A compiled .bbl is not made here. In a terminal: cdlbib export PAPER --bbl (PAPER is the paper's main .tex file or its folder).
```
