"""The cdlbib command. Parsing and formatting only; the work is in cdlbib.api."""
import os
import re
import sys
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import typer

from . import __version__, api, deps, verification_cli
from .errors import CdlbibError, GateFailed, LibraryUnavailable, MissingDependency, PublishRefused, WorkspaceNotFound
from .errors import UpdateNeedsDecision, EditedEntryParseError
from . import workspace
from .verification_cli import app as crossref_app, library, named
from .workspace import BIB_NAME

app = typer.Typer()
app.add_typer(crossref_app, name="crossref")


def _version(value: bool):
    if value:
        typer.echo(f"cdlbib {__version__}")
        raise typer.Exit()


@app.callback()
def root(library_path: str = typer.Option(None, "--library", help="Folder containing cdl.bib."),
         version: bool = typer.Option(False, "--version", callback=_version, is_eager=True,
                                      help="Show the version and exit."),
         ask: bool = typer.Option(False, "--ask", help="Ask before installing a missing package or creating your fork.")):
    workspace.select_library(library_path)
    deps.set_ask(ask)


def report_format(result, ws, fname):
    """Print the format check's log; a check that could not finish (check_bib raised) is
    shown and exits nonzero.

    A bare ``except`` used to print only 'errors found' and return success,
    which hid e.g. 'page numbers are ambiguous or incorrect: KothEtal25'.
    """
    # The log names the file as the user would from here, when that is the file checked.
    named = fname if Path(fname).resolve() == ws.bib else str(ws.bib)
    typer.echo(result.log.replace(f"loading {ws.bib}...", f"loading {named}...", 1), nl=False)
    if result.failure:
        typer.echo(f"errors found: {result.failure}", err=True)
        raise typer.Exit(code=1)


def report_check(check, verbose, autofix, outfile):
    if outfile:
        typer.echo(f"saved updated bibliography to {outfile}")
    if check.format.ok:
        typer.echo("format: looks good!")
        return
    if autofix:
        typer.echo(f"errors found; autocorrected and saved to {outfile}" if outfile
                   else "errors found; specify outfile to save autocorrections")
    typer.echo("errors found; see log for details" if verbose
               else "errors found; run with verbose flag for details")
    if check.needs_review_of_autofix:
        typer.echo("citations not checked: review the autocorrected file, then run verify on it")


def run_gate(ctx, fname, reference="github", citations=True, all_entries=False, autofix=False,
             outfile=None, verbose=False, database=None, mailto=None):
    """The gate of api.check_library, reported as it runs: the format log and verdict
    first, then each line of the citation check as it is produced."""
    ws = library(ctx, fname)
    fmt = api.check_format(ws, autofix=autofix, outfile=outfile, verbose=verbose, bars=sys.stderr)
    report_format(fmt, ws, fname)
    check = api.gate_after_format(fmt, citations=citations, autofix=autofix, outfile=outfile)
    report_check(check, verbose, autofix, outfile)
    if check.citations_due:
        check = api.check_citations(ws, fmt, reference=reference, all_entries=all_entries,
                                    database=database, mailto=mailto, progress=typer.echo,
                                    bars=sys.stderr)
    return check


def show_proposal(item):
    """Render the two exact texts and every completion finding."""
    typer.echo(f"Entry: {item.key_typed or item.key_proposed or '(new)'}")
    left, right = (item.typed_raw or '(no typed entry)').splitlines(), (item.proposed_raw or '(no proposed entry)').splitlines()
    if shutil.get_terminal_size().columns >= 100:
        from itertools import zip_longest
        width = (shutil.get_terminal_size().columns - 3) // 2
        typer.echo(f"{'Typed':<{width}} | Proposed")
        import textwrap
        for a, b in zip_longest(left, right, fillvalue=''):
            wrapped_a = textwrap.wrap(a.expandtabs(4), width=width, replace_whitespace=False, drop_whitespace=False) or ['']
            wrapped_b = textwrap.wrap(b.expandtabs(4), width=width, replace_whitespace=False, drop_whitespace=False) or ['']
            for row_a, row_b in zip_longest(wrapped_a, wrapped_b, fillvalue=''):
                typer.echo(f"{row_a:<{width}} | {row_b}")
    else:
        typer.echo('Typed:\n' + '\n'.join(left) + '\nProposed:\n' + '\n'.join(right))
    for change in item.changes:
        typer.echo(f"{change.field}: {change.typed} -> {change.proposed} (source: {change.source})")
    for missing in item.unfilled:
        typer.echo(f"Unfilled {missing.field}: {missing.reason}")
    for old, new in item.renames.items():
        typer.echo(f"Rename: {old} -> {new}")
    if item.key_typed and item.key_proposed != item.key_typed:
        typer.echo(f"Key: {item.key_typed} -> {item.key_proposed}")
    if item.duplicate_of:
        typer.echo(f"Duplicate: {item.duplicate_of}")
    if item.unsupported:
        typer.echo(f"Unsupported: {item.unsupported}")
    typer.echo(f"Verification: {item.status or 'not checked'}")
    for line in item.notes + item.issues:
        typer.echo(line)


def _editable(item, recheck):
    with tempfile.TemporaryDirectory(prefix='cdlbib-editor-') as folder:
        path = Path(folder) / 'entry.bib'
        original = item.proposed_raw or item.typed_raw or ''
        path.write_text(original, encoding='utf-8')
        while True:
            try:
                command = shlex.split(os.environ.get('VISUAL') or os.environ.get('EDITOR') or 'vi')
                result = subprocess.run([*command, str(path)])
                if result.returncode:
                    typer.echo(f'Editor exited with status {result.returncode}; returning to choices.')
                    return item
                raw = path.read_text(encoding='utf-8')
            except (OSError, ValueError) as exc:
                typer.echo(f'Could not start or read the editor: {exc}. Set EDITOR to an executable.')
                return item
            if raw == original:
                typer.echo('The editor left the entry unchanged.')
                return item
            try:
                return recheck(item, raw)
            except EditedEntryParseError as exc:
                typer.echo(f'Edited entry could not be read: {exc}. Reopening the editor.')
            except CdlbibError as exc:
                typer.echo(f'Edited entry could not be checked: {exc}. Returning to choices.')
                return item


def decide(proposals, *, recheck=None, choose_candidate=None, session=None):
    """Return explicitly accepted proposals; never infer human verification."""
    if not proposals:
        return []
    session = session if session is not None else {}
    accepted, all_remaining = [], session.get("all", False)
    terminal = sys.stdin.isatty() and sys.stderr.isatty()
    for item in proposals:
        if terminal and item.candidates and choose_candidate:
            for number, candidate in enumerate(item.candidates, 1):
                typer.echo(f"[{number}] {candidate.get('authors', '')} {candidate.get('year', '')}: {candidate.get('title', '')} {candidate.get('doi') or candidate.get('arxiv') or ''}")
            letters = ['0'] + [str(n) for n in range(1, len(item.candidates) + 1)]
            choice = _chosen('[0] none of these', letters)
            if choice == '0':
                continue
            item = choose_candidate(item, item.candidates[int(choice)-1])
        if terminal and recheck and item.proposed_raw:
            for change in list(item.changes):
                if change.kind == 'question' and change.field in ('author', 'editor') and change.typed and change.proposed:
                    typed_names = change.typed.split(' and ')
                    source_names = change.proposed.split(' and ')
                    if len(typed_names) != len(source_names):
                        continue
                    names = []
                    for typed_name, source_name in zip(typed_names, source_names):
                        if typed_name != source_name:
                            choice = _chosen(f'Name: [k] keep typed {typed_name} / [u] use source {source_name}', ['k', 'u'])
                            names.append(source_name if choice == 'u' else typed_name)
                        else:
                            names.append(typed_name)
                    from . import complete
                    fields = complete._completion_fields(item)
                    fields[change.field] = ' and '.join(names)
                    item = recheck(item, complete.render(item.entry_type, item.key_typed or item.key_proposed, fields),
                                   resolved_fields=(change.field,))
        while True:
            show_proposal(item)
            if not terminal:
                break
            if item.duplicate_of and item.duplicate_in_library:
                choice = _chosen('[r] remove this typed duplicate   [k] keep both for the formatter   [q] stop', ['r', 'k', 'q'])
                if choice == 'q':
                    session['stop'] = True
                    return accepted
                if choice == 'r':
                    from dataclasses import replace
                    accepted.append(replace(item, remove_duplicate=True))
                break
            safe = api.acceptable(item)
            if all_remaining and safe and not item.needs_decision:
                accepted.append(item)
                break
            choice = _chosen('[a] accept   [e] edit   [s] skip   [A] accept all remaining   [q] stop', ['a','e','s','A','q'], case_sensitive=True)
            if choice == 'q':
                session['stop'] = True
                return accepted
            if choice == 's':
                break
            if choice == 'e':
                if recheck:
                    item = _editable(item, recheck)
                else:
                    typer.echo('Editing needs a workspace recheck.')
            elif choice == 'A':
                all_remaining = True
                session["all"] = True
                if safe and not item.needs_decision:
                    accepted.append(item)
                    break
            elif safe:
                accepted.append(item)
                break
            else:
                typer.echo('Cannot accept: complete required fields and resolve duplicate or unsupported entries first.')
    if not terminal:
        typer.echo('nothing was changed')
    return accepted


def report_checkpoint(applied, session):
    if applied.backup is not None and not session.get('checkpoint'):
        session['checkpoint'] = applied.backup.stamp
        typer.echo(f'Batch backup: {applied.backup.stamp}; cdlbib update --undo restores the state before this command’s accepted changes.')


def proposal_recheck(ws, mailto=None, database=None):
    """The common editor/name-choice callback for every completion command."""
    def recheck(item, raw, resolved_fields=()):
        return api.recheck_proposal(ws, item, raw, mailto=mailto, database=database,
                                    resolved_fields=resolved_fields)
    return recheck


@app.command()
def add(ctx: typer.Context, queries: list[str] = typer.Argument(None),
        author: str = typer.Option(None, '--author'), year: str = typer.Option(None, '--year'),
        from_file: Path = typer.Option(None, '--from'),
        database: str = typer.Option(None, '--database'),
        mailto: str = typer.Option(None, '--mailto', envvar='CROSSREF_MAILTO')):
    """Look up entries, then accept, edit or skip each proposal."""
    from .complete import Query
    from .verification import load_entries
    ws = library(ctx, BIB_NAME)
    try:
        inputs = list(queries or [])
        if from_file:
            inputs.extend(line.strip() for line in from_file.read_text(encoding='utf-8').splitlines() if line.strip())
        parsed = [Query.parse(text, author=author, year=year) for text in inputs]
        if not parsed and not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                with tempfile.TemporaryDirectory(prefix='cdlbib-input-') as folder:
                    path = Path(folder) / 'stdin.bib'
                    path.write_text(raw, encoding='utf-8')
                    parsed = [Query.from_entry(entry) for entry in load_entries(path).values()]
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise typer.BadParameter(f'Could not read entry input: {exc}') from exc
    if not parsed:
        raise typer.BadParameter('Provide a query, --from FILE, or BibTeX on standard input')
    failures = False
    from .library import completion_batch
    with completion_batch(ws) as batch:
        session = {}
        for query in parsed:
            try:
                results = api.propose_new(ws, [query], mailto=mailto, database=database)
            except CdlbibError as exc:
                typer.echo(f'{query.title or query.doi or query.pmid or query.arxiv}: {exc}')
                failures = True
                continue
            failures |= bool(results.errors)
            recheck = proposal_recheck(ws, mailto=mailto, database=database)
            def candidate(item, selected):
                nonlocal failures
                chosen = api.choose_candidate(ws, item, selected, mailto=mailto, database=database)
                failures |= api.proposal_failed(chosen)
                return chosen
            accepted = decide(results, recheck=recheck, choose_candidate=candidate, session=session)
            if accepted:
                applied = api.apply_proposals(ws, accepted, batch=batch)
                report_checkpoint(applied, session)
                for key in applied.removed:
                    typer.echo(f'Removed duplicate: {key}')
                for key in applied.written:
                    typer.echo(f'Added: {key}')
                for key, reason in applied.refused:
                    typer.echo(f'Not written {key}: {reason}')
                    failures = True
            if session.get("stop"):
                break
        if failures:
            raise typer.Exit(code=1)


_completion_seen = None


def offer_completion(ws, reference="github", database=None, mailto=None):
    """Decide and persist one entry at a time, before the ordinary gate."""
    from .verification import load_entries
    from .library import completion_batch
    with completion_batch(ws) as batch:
        session = {}
        if _completion_seen is not None and ('stop', str(ws.bib)) in _completion_seen:
            return
        try:   # an unreadable library gives no offers: the ordinary format gate reports it
            offers = api.completion_offers(ws, reference=reference, database=database, mailto=mailto,
                                           seen=_completion_seen)
        except CdlbibError as exc:
            typer.echo(f"Completion unavailable: {exc}")
            return
        for offer in offers:
            key = offer.key
            accepted, applied = [], None
            try:
                if offer.error is not None:
                    raise CdlbibError(offer.error)
                results = offer.proposals
                recheck = proposal_recheck(ws, mailto=mailto, database=database)
                def candidate(item, selected):
                    return api.choose_candidate(ws, item, selected, mailto=mailto, database=database, in_library=True)
                accepted = decide(results, recheck=recheck, choose_candidate=candidate, session=session) if results else []
                if accepted:
                    applied = api.apply_proposals(ws, accepted, batch=batch)
                    report_checkpoint(applied, session)
                    for removed in applied.removed:
                        typer.echo(f'Removed duplicate: {removed}')
                    for written in applied.written:
                        typer.echo(f'Completed: {written}')
                    for refused, reason in applied.refused:
                        typer.echo(f'Not written {refused}: {reason}')
            except CdlbibError as exc:
                typer.echo(f'{key}: completion unavailable: {exc}')
            if _completion_seen is not None:
                for current_key, entry in load_entries(ws.bib).items():
                    if current_key == key or (applied is not None and current_key in applied.written):
                        _completion_seen.add((str(ws.bib), current_key, entry['fingerprint']))
            if session.get('stop'):
                if _completion_seen is not None:
                    _completion_seen.add(('stop', str(ws.bib)))
                break


@app.command()
def verify(ctx: typer.Context, fname: str = BIB_NAME, autofix: bool = False, outfile: str = None, verbose: bool = False,
           reference: str = "github",
           no_complete: bool = typer.Option(False, "--no-complete", help="Skip entry completion proposals."),
           no_citations: bool = typer.Option(False, "--no-citations",
                                             help="Offline, format-only check (no citation verification)."),
           all: bool = typer.Option(False, "--all", help="Verify the citations of every entry, not only changed ones."),
           database: str = typer.Option(None, "--database", help="Verification cache (default .bibcheck/verification.sqlite3)."),
           mailto: str = typer.Option(None, "--mailto", envvar="CROSSREF_MAILTO", help="Contact email for Crossref.")):
    """Format check, then citation verification of new/edited entries."""
    if not no_complete and not no_citations and not autofix and not outfile:
        offer_completion(library(ctx, fname), reference=reference, database=database, mailto=mailto)
    check = run_gate(ctx, fname, reference=reference, citations=not no_citations, all_entries=all, autofix=autofix,
                     outfile=outfile, verbose=verbose, database=database, mailto=mailto)
    if not check.ok:
        raise typer.Exit(code=1)
    typer.echo("looks good!")


@app.command()
def compare(fname1: str, fname2: str, verbose: bool = False, outfile: str = None):
    """Show the differences between two .bib files."""
    result = api.compare(fname1, fname2, verbose=verbose, outfile=outfile, bars=sys.stderr)
    typer.echo(result.log, nl=False)
    if result.match:
        typer.echo("files match!")
    else:
        typer.echo("files do not match; see log for details" if verbose
                   else "files do not match; run with verbose flag for details")


@app.command()
def send(ctx: typer.Context, fname: str = BIB_NAME, reference: str = "github", verbose: bool = False,
           no_complete: bool = typer.Option(False, "--no-complete", help="Skip entry completion proposals."),
           outfile: str = None,
           summary: str = typer.Option(None, "--summary", help="One line describing the change."),
           database: str = typer.Option(None, "--database", help="Verification cache (default .bibcheck/verification.sqlite3)."),
           mailto: str = typer.Option(None, "--mailto", envvar="CROSSREF_MAILTO", help="Contact email for Crossref.")):
    """Run the verify gate, then send the change as a pull request from your fork."""
    _send(library(ctx, fname), fname, reference=reference, verbose=verbose, outfile=outfile, summary=summary,
          database=database, mailto=mailto, no_complete=no_complete)


from .library import batch_command


@batch_command
def _send(ws, fname=BIB_NAME, reference="github", verbose=False, outfile=None, summary=None, database=None, mailto=None, no_complete=False):
    """The send command, for the library ``ws`` (also run by the answer "send my changes first")."""

    from . import publish
    publish.require_canonical(ws)
    publish.require_branch(ws)
    publish.require_identity(ws)
    api.validate_summary_path(outfile, ws=ws, inputs=(reference,), database=database)
    if not no_complete:
        offer_completion(ws, reference=reference, database=database, mailto=mailto)

    def shown(check):
        report_format(check.format, ws, fname)
        report_check(check, verbose, False, None)

    def attempt(report=None, progress=None, allow_fork_creation=False):
        return api.send(ws, summary=summary, reference=reference, mailto=mailto, database=database,
                        progress=progress, bars=sys.stderr, report=report, allow_fork_creation=allow_fork_creation,
                        outfile=outfile, verbose=verbose)

    try:
        try:
            result = attempt(report=shown, progress=typer.echo)
        except PublishRefused as exc:
            if not exc.needs_fork:
                raise
            if not fork_wanted(exc):
                typer.echo(f"{exc} Create one with: gh repo fork {exc.upstream} --clone=false", err=True)
                raise typer.Exit(code=1)
            result = attempt(allow_fork_creation=True)  # the gate runs again, from its cache, unreported
    except GateFailed as exc:
        if exc.check is None:  # the check could not be done; main() reports it
            raise
        typer.echo(str(exc))  # "not sent: fix the format errors and resolve every new/edited entry first ..."
        raise typer.Exit(code=1)
    if result.created_fork:
        typer.echo(f"created fork {result.fork}")
    if result.files:
        typer.echo("committed: " + ", ".join(result.files))
    typer.echo(f"pull request: {result.url}")
    typer.echo(f"you are now on branch {result.branch}")
    if result.left:
        typer.echo("left uncommitted: " + ", ".join(result.left))


@app.command()
def web(port: int = typer.Option(0, "--port", help="The port to listen on (default: one the system picks)."),
        no_open: bool = typer.Option(False, "--no-open", help="Do not open the browser; print the address only.")):
    """Open the local web interface (this computer only) on the library in use."""
    from .web import server
    server.run(port=port, open_browser=not no_open, say=lambda line: typer.echo(line, err=True))


@app.command()
def tui(ctx: typer.Context):
    """Open the terminal interface on the library."""
    deps.need("textual", "tui", "the terminal interface")
    ws = library(ctx, BIB_NAME)   # as every command: the managed library is downloaded when it is the one in use
    from .tui import run
    run(ws)


from .prompts import ANSWERS, MOVED, answers, unsent_question, CHOSEN_BY


@app.command()
def where(ctx: typer.Context, fname: str = BIB_NAME):
    """Show which library is in use and how it was chosen."""
    library(ctx, fname)  # as every command: the managed library is downloaded when it is the one in use
    found = api.where(fname if named(ctx) else None)
    typer.echo(str(found.root))
    typer.echo(f"chosen by: {CHOSEN_BY[found.origin]}")
    if found.origin == workspace.Origin.MANAGED:
        typer.echo("last update check: " + (found.last_check.strftime("%Y-%m-%d %H:%M UTC") if found.last_check else "never"))


def _backup_line(backup):
    changed = len(backup.changed)
    return ((f"branch {backup.branch}" if backup.branch else "no branch")
            + f" at {backup.commit[:8]}, {changed} changed file{'' if changed == 1 else 's'}"
            + (", local commits saved" if backup.has_bundle else "")
            + (", holds commits kept nowhere else" if api.holds_only_copy(backup) else ""))


@app.command()
def update(stamp: str = typer.Argument(None, help="With --undo: the backup to restore, named as --list shows it "
                                                  "(default: the command checkpoint, otherwise newest)."),
           show: bool = typer.Option(False, "--list", help="Show the backups of the library cdlbib manages."),
           undo: bool = typer.Option(False, "--undo", help="Put that library back as it was at a backup.")):
    """Bring the library cdlbib downloads and manages up to date now; --list shows its backups, --undo restores one."""
    if show and undo:
        raise typer.BadParameter("--list and --undo cannot be used together")
    if stamp and not undo:
        raise typer.BadParameter("a backup is named only with --undo: cdlbib update --undo STAMP")
    if undo:
        done = api.undo(stamp)
        restored = done.restored
        typer.echo(f"restored backup {restored.stamp} ({restored.when}): {_backup_line(restored)}")
        typer.echo(f"the library as it was just before is backup {done.before.stamp}")
        typer.echo("run `cdlbib update --undo` again to return to it")
        for branch, commit in done.taken_off:
            typer.echo(f"branch {branch} was on commit {commit[:8]}, which is on no other branch and not in the "
                       f"upstream; backup {done.before.stamp} keeps it, and `cdlbib update --undo {done.before.stamp}` "
                       "puts the branch back on it")
        for note in done.notes:
            typer.echo(note, err=True)
    elif show:
        saved = api.backups()
        unreadable = api.unreadable_backups()
        root = api.managed_root()
        if not saved and not unreadable:
            typer.echo(f"no backups of {root} yet")
            return
        typer.echo(f"{len(saved)} {'readable ' if unreadable else ''}backup{'' if len(saved) == 1 else 's'} of {root}"
                   + (f" and {len(unreadable)} unreadable" if unreadable else "")
                   + f", newest first (kept in {api.backups_folder()}):")
        lines = {backup.stamp: f"  {backup.stamp}  {backup.when}  {_backup_line(backup)}" for backup in saved}
        lines.update({stamp: f"  {stamp}: unreadable ({reason})" for stamp, reason in unreadable})
        for stamp in sorted(lines, reverse=True):
            typer.echo(lines[stamp])
        checkpoint = api.completion_undo_checkpoint()
        if checkpoint:
            typer.echo(f"`cdlbib update --undo` restores command checkpoint {checkpoint}; "
                       "`cdlbib update --undo STAMP` restores the one named.")
        elif saved:
            typer.echo("`cdlbib update --undo` puts the library back as it was at the newest one; "
                       "`cdlbib update --undo STAMP` at the one named.")
    else:
        def say(line):
            typer.echo(line, err=True)

        try:
            result = api.update(force=True, progress=say)
        except UpdateNeedsDecision as exc:
            try:
                result = settle_unsent(workspace.Workspace(api.managed_root()), exc, True, say)
            except verification_cli.SendFirst as first:
                first.run()
                raise typer.Exit()       # the send was the command
            if result is None:      # asked for, and nobody can be asked what to do with the unsent changes
                say(verification_cli.unsent_line(exc))
                raise typer.Exit(code=1)
        for note in result.notes:
            typer.echo(note, err=True)
        if result.action in ("skipped_offline", "interrupted"):      # asked for, and it could not be done
            typer.echo(result.message, err=True)
            raise typer.Exit(code=1)
        typer.echo(result.message)


from .errors import TexLinkRefused


def _tex_state(status):
    """The line that says what the state of the TeX link means."""
    return {
        "linked": "linked: TeX finds this library's cdl.bib from any folder (\\bibliography{cdl} or \\addbibresource{cdl.bib})",
        "absent": "not linked",
        "other_library": f"linked to another library: {status.target}",
        "foreign": f"not linked: {status.link} exists and was not made by cdlbib",
        "shadowed": "linked, but TeX does not resolve cdl.bib to it",
        "no_tex": {"linked": "linked; TeX was not found, so it could not be shown that TeX resolves it",
                   "absent": "not linked; TeX was not found",
                   "other_library": f"linked to another library: {status.target}; TeX was not found",
                   "foreign": f"not linked: {status.link} exists and was not made by cdlbib; TeX was not found",
                   }[status.present],
    }[status.state]


def report_setup(report, status, asked=False):
    """Print the setup report: the library, the TeX link, what cdlbib can use here."""
    found = report.where
    typer.echo(f"library: {found.root}")
    typer.echo(f"chosen by: {CHOSEN_BY[found.origin]}")
    typer.echo(f"TeX tree: {status.texmf_home}")
    typer.echo(f"link: {status.link}" + (f" -> {status.target}" if status.target else ""))
    for line in status.changes:
        typer.echo(line)
    typer.echo(f"state: {_tex_state(status)}")
    if status.kpsewhich:
        typer.echo(f"kpsewhich cdl.bib: {status.resolves_to or 'not found'}")
    for line in status.notes:
        typer.echo(line)
    if asked:
        typer.echo("the link was not made (not confirmed); `cdlbib setup` without --ask makes it")
    if status.state != "linked":
        typer.echo(f"without a link, this shell line does the same (cdlbib does not write it anywhere): {status.bibinputs_line}")
    typer.echo("available on this computer:")
    for feature in report.features:
        typer.echo(f"  {feature.name}: {'not checked' if feature.available is None else 'yes' if feature.available else 'no'}"
                   f" ({feature.detail})"
                   + (f" {feature.how}" if feature.how else ""))


@app.command()
def setup(ctx: typer.Context,
          check: bool = typer.Option(False, "--check", help="Report only; exit 1 when cdl.bib is not linked."),
          remove: bool = typer.Option(False, "--remove", help="Remove the link cdlbib made in the TeX tree."),
          replace: bool = typer.Option(False, "--replace", help="Move a cdl.bib that cdlbib did not put in the TeX "
                                                                "tree aside (it is kept), then make the link.")):
    """Link cdl.bib into your TeX tree so every manuscript finds it; report what cdlbib can use here."""
    if check + remove + replace > 1:
        raise typer.BadParameter("--check, --remove and --replace cannot be used together")
    if remove:
        done = api.tex_unlink()
        typer.echo(f"removed {done.link}" if done.removed else f"nothing removed at {done.link}: {done.reason}")
        for line in done.notes:
            typer.echo(line)
        return
    ws = library(ctx, BIB_NAME)   # as every command: the managed library is downloaded when it is the one in use
    report = api.setup_report(ws, probe="all", progress=lambda line: typer.echo(line, err=True))   # the setup command checks everything
    status, declined, refused = report.tex, False, None
    if not check and status.present != "linked":
        if deps.ask() and not _confirmed(f"Link {status.link} to {ws.bib}?"):
            declined = True
        else:
            try:
                status = api.tex_link(ws, replace=replace)
            except TexLinkRefused as exc:
                refused = exc
    report_setup(report, status, asked=declined)
    if refused is not None:
        typer.echo(f"{refused} Run: cdlbib setup --replace", err=True)
        raise typer.Exit(code=1)
    if status.state != "linked" and (check or declined or status.state != "no_tex"):
        raise typer.Exit(code=1)


@app.command()
def export(ctx: typer.Context,
           paper: Path = typer.Argument(..., help="The paper: its main .tex file, its folder, or a .aux/.bcf file."),
           out: Path = typer.Option(None, "-o", "--out", help="The file to write (default: cdl.bib beside the paper; "
                                                               "with --bbl, the paper's name with .bbl)."),
           bbl: bool = typer.Option(False, "--bbl", help="Write the paper's compiled .bbl instead of a .bib. This runs "
                                                         "LaTeX on the paper's files, as compiling it yourself does."),
           inputs: list[Path] = typer.Option(None, "--inputs", help="A style or class file the paper needs, or a folder "
                                                                    "of them (repeat for several)."),
           main: str = typer.Option(None, "--main", help="The main .tex file, when the folder has several."),
           engine: str = typer.Option(None, "--engine", help="pdflatex, xelatex, lualatex or latex (default: what the "
                                                             "paper asks for, else pdflatex)."),
           force: bool = typer.Option(False, "--force", help="Replace the output file when it exists.")):
    """Write the entries a paper cites as a .bib of its own, or its compiled .bbl."""
    ws = library(ctx, BIB_NAME)
    if bbl:
        made = api.export_bbl(ws, paper, out=out, inputs=inputs or (), main=main, engine=engine, force=force)
        count = len(made.keys)
        typer.echo(f"wrote {made.path}: {made.backend}" + (f", style {made.style}" if made.style else "")
                   + f", {made.engine}, {count} cited key{'' if count == 1 else 's'}"
                   + (" and every other entry (\\nocite{*})" if made.cited.all_entries else ""))
        for line in made.notes:
            typer.echo(line)
        return
    made = api.export_bib(ws, paper, out=out, main=main, inputs=inputs or (), engine=engine, force=force)
    cited = made.cited
    read_from = {"aux": "the .aux file", "bcf": "the .bcf file", "compiled": "a fresh LaTeX run of the paper",
                 "source": "the .tex source"}[cited.how]
    count, entries = len(cited.keys), len(made.written)
    typer.echo(f"citations read from {read_from}: {count} key{'' if count == 1 else 's'}"
               + (" and \\nocite{*} (every entry)" if cited.all_entries else ""))
    for line in made.notes:
        typer.echo(line)
    typer.echo(f"wrote {made.path}: {entries} entr{'y' if entries == 1 else 'ies'} from {ws.bib}")
    if made.parents:
        typer.echo("included because a cited entry inherits from them: " + ", ".join(made.parents))
    if made.missing:
        typer.echo("cited, but not in the library: " + ", ".join(str(item) for item in made.missing), err=True)
        raise typer.Exit(code=1)


# (prompts moved to prompts.py)


def settle_unsent(ws, exc, force, say, sending=False):
    """An update is available and the managed library ``ws`` has unsent changes: ask what to
    do, and do it. Returns the update's result; None when no question can be asked (no
    terminal), and then nothing was changed. No option answers this question. "Send my
    changes first" runs the send command and ends there; when the command being run is
    `send` itself (``sending``), it just goes on."""
    letters = [answers(exc)[choice][0] for choice in exc.choices]
    letter = _chosen(unsent_question(exc), letters, words=exc.choices)
    if letter is None:
        return None
    decision = exc.choices[letters.index(letter)]
    result = api.update(ws, decision=decision, force=force, progress=say, seen=exc.seen)
    if decision == "send" and not sending:
        for note in result.notes:
            say(note)
        say(result.message)
        # The send is the command from here on, exactly as if `cdlbib send` had been typed: the
        # caller runs it outside its own error handling, so its failures end the command with
        # the send's message and exit code, and a missing package is offered as it is there.
        raise verification_cli.SendFirst(lambda: _installing(
            lambda: _send(ws, mailto=os.environ.get("CROSSREF_MAILTO"))))
    return result


verification_cli.settle_unsent = settle_unsent


def fork_wanted(exc):
    """Whether to create the user's fork now. By default it is, after saying so; with --ask the
    user is asked first (no terminal means no)."""
    if deps.ask():
        return _confirmed(f"{exc} Create one now?")
    login = re.match(r"@(\S+) has no fork of ", str(exc))
    name = exc.upstream.split("/", 1)[1] if exc.upstream and "/" in exc.upstream else "the upstream repository"
    typer.echo(f"creating your fork {login.group(1)}/{name} ..." if login else f"creating your fork of {exc.upstream} ...")
    return True


def install_wanted(exc):
    """Whether to install the missing package now: by default yes, after saying so; with --ask
    the user is asked first (no terminal means no)."""
    if deps.ask():
        return _confirmed(f"{exc.feature} needs '{exc.package}'. Install it now?")
    typer.echo(f"installing {exc.package} (needed for: {exc.feature}) ...")
    return True


def _run_once(argv):
    try:
        app(args=argv)
    except (WorkspaceNotFound, LibraryUnavailable) as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(2)
    except GateFailed as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(2)
    except MissingDependency:
        raise  # main() offers the install
    except CdlbibError as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1)


def main(argv=None):
    """Run the command. A missing optional package is installed (after a question with --ask)
    and the command is run again once; click keeps reporting its own usage errors."""
    global _completion_seen
    previous = _completion_seen
    _completion_seen = set()
    try:
        _installing(lambda: _run_once(argv))
    finally:
        _completion_seen = previous


def _installing(run):
    """Call ``run``; when it stops for a missing optional package, install the package (after
    a question with --ask) and call it again, once."""
    for attempt in (1, 2):
        try:
            run()
            return
        except MissingDependency as exc:
            if attempt == 2 or not install_wanted(exc):
                typer.echo(str(exc), err=True)
                raise SystemExit(1)
            try:
                deps.install(exc.extra, package=exc.package)
            except CdlbibError as failure:
                typer.echo(str(failure), err=True)
                raise SystemExit(1)


class _interruptible:
    """While a question is on the terminal, Ctrl-C ends it, also when the command was started
    with interrupts ignored (a shell's background job, nohup: Python then installs no handler
    and the read would never return). The inherited setting is put back afterwards."""

    def __enter__(self):
        import signal
        self.previous = None
        try:
            if signal.getsignal(signal.SIGINT) == signal.SIG_IGN:
                self.previous = signal.signal(signal.SIGINT, signal.default_int_handler)
        except (ValueError, OSError):       # not the main thread: nothing to change
            pass

    def __exit__(self, *exc):
        import signal
        if self.previous is not None:
            signal.signal(signal.SIGINT, self.previous)
        return False


def _confirmed(question):
    """Ask only at a terminal; with none, the caller prints the manual command and exits."""
    if not sys.stdin.isatty():
        return False
    try:
        with _interruptible():
            return typer.confirm(question, default=False)
    except (typer.Abort, KeyboardInterrupt):  # Ctrl-C or end of input at the prompt
        typer.echo("Aborted.", err=True)
        raise SystemExit(1)


def _chosen(question, letters, words=(), case_sensitive=False):
    """Ask ``question`` (on stderr) until one of ``letters`` is answered, or the whole word
    for one (``words``, in the letters' order). Returns the letter. Only at a terminal: with
    none, None, and nothing is printed."""
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        return None
    typer.echo(question, err=True)
    while True:
        typer.echo(f"Your choice [{'/'.join(letters)}]: ", nl=False, err=True)     # nothing of it on stdout
        try:
            with _interruptible():
                answer = sys.stdin.readline()
        except KeyboardInterrupt:
            answer = ""
        if not answer:  # Ctrl-C or end of input at the prompt
            typer.echo("\nAborted.", err=True)
            raise SystemExit(1)
        value = answer.strip() if case_sensitive else answer.strip().lower()
        if value in letters:
            return value
        if answer.strip().lower() in words:
            return letters[list(words).index(answer.strip().lower())]
        typer.echo(f"Please answer {', '.join(letters[:-1])} or {letters[-1]}.", err=True)
