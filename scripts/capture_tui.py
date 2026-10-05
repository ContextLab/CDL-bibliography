"""Screenshots of the terminal interface's key states, as PNG files.

    python scripts/capture_tui.py [OUTPUT_FOLDER]          (default: docs/media)

Drives the real interface (cdlbib.tui) with Textual's pilot, key by key, against a temporary
library: a managed library cloned from a small upstream made here, in a temporary folder.
HOME, TEXMFHOME, CDLBIB_HOME and CDLBIB_UPSTREAM are set to temporary folders before
anything of cdlbib runs, so neither the user's library, their TeX tree nor the real upstream
is read or written. Lookups are the test suite's saved responses, with the network refused.

Writes tui-library.png, tui-detail-evidence.png, tui-edit-preview.png, tui-review-approve.png,
tui-add-search.png, tui-proposal.png, tui-add-pdf.png and tui-proposal-pdf.png (when pdflatex is
installed), tui-send.png, tui-update-question.png, tui-setup.png and tui-library-light.png.

Each picture is the interface's own screenshot (Textual's SVG export), drawn by headless
Chromium: this needs the package playwright and its Chromium (python -m playwright install
chromium).

    python scripts/capture_tui.py --demo-library FOLDER

makes the small library that scripts/make_screencasts.sh records the "tui" cast in (see
``demo_library``).

tui-review-approve.png shows the approval dialog, which names the GitHub login of the gh CLI of
whoever runs this; in the saved picture that name is replaced by a placeholder of the same
length. Without a login the picture shows what the interface says then.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
SIZE = (132, 40)
IDENTITY = dict(GIT_AUTHOR_NAME="cdlbib demo", GIT_AUTHOR_EMAIL="demo@cdlbib.invalid",
                GIT_COMMITTER_NAME="cdlbib demo", GIT_COMMITTER_EMAIL="demo@cdlbib.invalid", GIT_TERMINAL_PROMPT="0")


def gh_token():
    """The token of the user's gh login, read before HOME is substituted (gh keeps it in the
    user's keychain). Used only so that gh can say who is logged in; never written anywhere."""
    if not shutil.which("gh"):
        return None
    try:
        done = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=dict(os.environ, **IDENTITY))


def commit(work, bare, message, text):
    (work / "cdl.bib").write_text(text, encoding="utf-8")
    git("add", "cdl.bib", cwd=work)
    git("commit", "--quiet", "-m", message, cwd=work)
    git("push", "--quiet", str(bare), "master", cwd=work)


def upstream(folder, text):
    """A small upstream of its own: a bare repository holding cdl.bib and verification/."""
    bare, work = folder / "upstream.git", folder / "upstream-work"
    bare.mkdir(parents=True)
    git("init", "--quiet", "--bare", cwd=bare)
    git("symbolic-ref", "HEAD", "refs/heads/master", cwd=bare)
    (work / "verification").mkdir(parents=True)
    git("init", "--quiet", cwd=work)
    git("symbolic-ref", "HEAD", "refs/heads/master", cwd=work)
    (work / "verification" / ".gitkeep").write_text("", encoding="utf-8")
    git("add", "verification/.gitkeep", cwd=work)
    commit(work, bare, "The demonstration library", text)
    return bare, work


def main(out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    token = gh_token()
    # Chromium is where Playwright put it for this user; HOME is substituted below.
    cache = Path.home() / ("Library/Caches/ms-playwright" if sys.platform == "darwin" else ".cache/ms-playwright")
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(cache))
    folder = Path(tempfile.mkdtemp(prefix="cdlbib-demo-"))
    try:
        # The test suite's helpers first (its conftest points cdlbib's data folder and upstream at
        # temporary folders of its own when imported); then this run's own folders, which win.
        import intake_pdfs
        import tui_support as T
        from test_complete_identify import library_entry          # entries of the frozen test library
        from test_desk import GLOC08, KAHA12, TENE11, ZOLL90
        os.environ.update(T.isolated_environment(folder))
        os.environ.update(IDENTITY)
        os.environ["CROSSREF_MAILTO"] = T.CONTACT
        for name in ("CDLBIB_LIBRARY", "BIBINPUTS", "BSTINPUTS", "TEXINPUTS", "COLORFGBG", "GH_TOKEN", "GITHUB_TOKEN",
                     "DARTMOUTH_CHAT_API_KEY", "OPENAI_API_KEY"):
            os.environ.pop(name, None)
        os.environ["GH_CONFIG_DIR"] = str(folder / "gh-config")
        if token:
            os.environ["GH_TOKEN"] = token
        if sys.platform == "darwin":
            os.environ.setdefault("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")
        game = library_entry("Game62")
        entries = [ZOLL90.replace("{27}", "{28}"), KAHA12, GLOC08, TENE11, game]
        bare, work = upstream(folder, "\n\n".join(entries) + "\n")
        os.environ["CDLBIB_UPSTREAM"] = str(bare)
        from cdlbib import api, workspace
        workspace.select_library(None)
        os.chdir(folder)
        ws = api.ensure_library()
        if folder.resolve() not in ws.root.resolve().parents:        # never anything but this run's own library
            raise SystemExit(f"refusing to go on: the library in use is {ws.root}, not one under {folder}")
        T.seed_responses(ws, T.COMPLETION, T.PDF_LOOKUPS, T.TUI_SEARCH)
        api.check_keys(ws, ["Game62", "Zoll90"], mailto=T.CONTACT)     # the real gate, over the saved responses
        os.environ.update(T.refused_network())                         # after the clone: no source can be asked
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "api.github.com"   # gh may still say who is logged in
        # an unsent edit here, and a newer version upstream
        mine = ("\n@article{Mine26,\n\tAuthor = {A Person},\n\tJournal = {Journal of Tests},\n\tTitle = {My own entry},\n"
                "\tYear = {2026}}\n")
        ws.bib.write_text(ws.bib.read_text(encoding="utf-8") + mine, encoding="utf-8")
        commit(work, bare, "A correction upstream", "\n\n".join([entries[0], KAHA12.replace("2012", "2013"), *entries[2:]]) + "\n")
        pdf = intake_pdfs.build("doi", folder / "pdfs") if intake_pdfs.pdflatex() else None
        made = T.run(journey(T, ws, out, pdf))
        write_pngs(made)
    finally:
        os.chdir(ROOT)
        shutil.rmtree(folder, ignore_errors=True)


async def journey(T, ws, out, pdf):
    from cdlbib.tui import CdlbibApp
    app = CdlbibApp(ws)
    made = []

    def shot(name):
        path = out / f"tui-{name}.png"
        svg = app.export_screenshot(title=f"cdlbib tui: {name}", simplify=True)
        # The picture, and only the picture, names a placeholder where the interface showed the gh
        # login of whoever ran this (the core was asked for real; nothing it returned is changed).
        for login in set(re.findall(r"(?:Approving|Revoking)&#160;as&#160;(@[A-Za-z0-9-]+)", svg)):
            room = len(login) - 1
            name = next((n for n in ("your-github-login", "your-gh-login", "your-login", "you") if len(n) <= room), "")
            svg = svg.replace(login, "@" + name + "&#160;" * (room - len(name)))
        made.append((path, svg))

    async with app.run_test(size=SIZE, notifications=False) as pilot:
        await T.settle(pilot)
        await T.press(pilot, "ctrl+l")                                 # more room: the log is hidden for the stills
        shot("library")

        await T.press(pilot, "d", "d")                                 # Zoll90, checked by the gate: its evidence
        shot("detail-evidence")

        await T.press(pilot, "e")                                      # edit: volume 28 -> 27, previewed
        await T.press(pilot, "pagedown", "up", "end", "left", "left", "backspace", "7", "ctrl+p")
        shot("edit-preview")
        await T.press(pilot, "escape", "y")

        await T.press(pilot, "f3", "t")                                # review: approve, under the gh login
        await T.press(pilot, "a")
        if type(app.screen).__name__ == "PromptScreen":
            await T.type_text(pilot, "the journal's page")
            await T.press(pilot, "enter")
            await T.type_text(pilot, "volume, issue and pages checked")
        shot("review-approve")
        await T.press(pilot, "escape")
        if type(app.screen).__name__ == "ConfirmScreen":               # text was typed: closing asks first
            await T.press(pilot, "y")

        await T.press(pilot, "f4")                                     # add: a title search, then the proposal
        await T.type_text(pilot, "Backward learning in paired associates")
        await T.press(pilot, "enter")
        shot("add-search")
        await T.press(pilot, "enter")
        shot("proposal")
        await T.press(pilot, "q")

        if pdf is not None:                                            # add: a PDF, read and drawn
            await T.press(pilot, "escape", "right", "right", "enter")
            await T.type_text(pilot, str(pdf))
            await T.press(pilot, "enter")
            shot("add-pdf")
            await T.press(pilot, "l")                                  # its record, with the PDF's text beside it
            shot("proposal-pdf")
            await T.press(pilot, "q")

        await T.press(pilot, "f6")                                     # send: what would go
        shot("send")

        await T.press(pilot, "f7", "u")                                # update: the question about unsent changes
        shot("update-question")
        await T.press(pilot, "escape")

        await T.press(pilot, "f8")
        shot("setup")

        await T.press(pilot, "f2", "ctrl+t")                           # the light theme
        shot("library-light")
        app.jobs.stop()
    return made


WIDTH = 1280        # pixels each picture is wide


def write_pngs(made):
    """Each screenshot (Textual's own SVG export of the running interface) drawn by headless
    Chromium and saved as a PNG. The SVG names the font Fira Code and where to fetch it; when
    it cannot be fetched, a monospaced font of this computer is named instead, in the copy
    that is drawn. With ffmpeg installed the PNG is saved with a palette of its own colours,
    which makes the file smaller and changes no pixel's position."""
    from playwright.sync_api import sync_playwright
    clean = {name: value for name, value in os.environ.items() if not name.lower().endswith("_proxy")}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(env=clean)
        page = browser.new_page(viewport={"width": WIDTH, "height": 900})
        for path, svg in made:
            page.set_content(f"<html><body style='margin:0'>{svg}</body></html>")
            page.evaluate("document.querySelector('svg').setAttribute('width', '%d')" % WIDTH)
            try:
                loaded = page.evaluate("""async () => { await Promise.all([document.fonts.load('20px "Fira Code"'),
                    document.fonts.load('bold 20px "Fira Code"')]); await document.fonts.ready;
                    return document.fonts.check('20px "Fira Code"'); }""")
            except Exception:
                loaded = False
            if not loaded:
                local = svg.replace("font-family: Fira Code, monospace", "font-family: Menlo, 'DejaVu Sans Mono', monospace")
                page.set_content(f"<html><body style='margin:0'>{local}</body></html>")
                page.evaluate("document.querySelector('svg').setAttribute('width', '%d')" % WIDTH)
            page.locator("svg").screenshot(path=str(path))
            if shutil.which("ffmpeg"):
                small = path.with_suffix(".small.png")
                done = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf",
                                       "split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=none",
                                       str(small)], capture_output=True)
                if done.returncode == 0 and small.stat().st_size < path.stat().st_size:
                    small.replace(path)
                else:
                    small.unlink(missing_ok=True)
            print(f"{path}  {path.stat().st_size // 1024} KB  ({'Fira Code' if loaded else 'a local monospaced font'})")
        browser.close()


def demo_library(folder):
    """For scripts/make_screencasts.sh (the "tui" cast): a small library in FOLDER/library, a
    folder the caller made outside the repository, with the test suite's saved lookup
    responses in its own response cache, so that the interface recorded there asks no
    service. HOME, TEXMFHOME and CDLBIB_HOME are folders under FOLDER while this runs, as
    they are for the recording."""
    folder = Path(folder).resolve()
    if ROOT in folder.parents or folder == ROOT or not folder.is_dir():
        raise SystemExit(f"refusing: {folder} must be an existing folder outside the repository")
    import tui_support as T
    from test_desk import GLOC08, KAHA12, TENE11, ZOLL90
    os.environ.update(T.isolated_environment(folder))
    os.environ["CROSSREF_MAILTO"] = T.CONTACT
    os.environ.pop("CDLBIB_LIBRARY", None)
    from cdlbib import api
    ws = T.library(folder / "library", ZOLL90.replace("{27}", "{28}"), KAHA12, GLOC08, TENE11)
    T.seed_responses(ws, T.COMPLETION)
    os.environ.update(T.refused_network())
    api.check_keys(ws, ["Zoll90"], mailto=T.CONTACT)          # the real gate, over the saved responses
    print(ws.root)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--demo-library":
        demo_library(sys.argv[2])
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else ROOT / "docs" / "media")
