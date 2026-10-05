"""Every failure the core reports to a front end."""


class CdlbibError(Exception):
    """Base class. Front ends show str(error) and choose the exit code or dialog."""


class EditedEntryParseError(CdlbibError):
    """The saved editor text cannot be read as exactly one BibTeX entry."""


class EditRefused(CdlbibError):
    """A hand edit that was not saved, with nothing written: the entry changed since it was
    opened, its new key is in use, or the text is not one entry (``problems`` lists why)."""

    def __init__(self, message, problems=()):
        self.problems = list(problems)
        super().__init__(message)


class WorkspaceNotFound(CdlbibError):
    pass


class LibraryUnavailable(CdlbibError):
    """The managed library is not there and could not be downloaded."""


class UpdateConflict(CdlbibError):
    """An update of the managed library collided with the user's changes, and the library is
    exactly as it was. ``entries`` are the citation keys changed both by the user and by the
    upstream (differently); ``files`` the files whose changes collide."""

    def __init__(self, message="", entries=(), files=()):
        self.entries, self.files = list(entries), list(files)
        super().__init__(message)


class UpdateNeedsDecision(CdlbibError):
    """A newer version of the managed library is available and the library holds work that
    has not been sent. Nothing was changed; the user decides (the core never asks).

    ``changed``          the changed and untracked files under cdl.bib and verification/
    ``entries_changed``  how many entries of cdl.bib differ from the upstream's version the
                         library started from (None when cdl.bib is unchanged or the count
                         could not be made)
    ``new_commits``      commits the upstream has that the library does not
    ``local_commits``    commits the library has that the upstream does not
    ``choices``          the decisions library.update() takes in this state, from
                         ("keep", "update", "send", "discard")
    ``seen``             names the state the question is about; passed back with the decision,
                         so that a decision is never applied to a state the user was not shown

    When the library is on the branch of an earlier send (``branch`` is set), the question is
    about that branch instead: its pull request (``pull_request``, a URL) is ``state``
    ("merged", with changes made on the branch since; or "closed", without being merged),
    ``local_commits`` counts the branch's commits that were not sent or not merged,
    ``new_commits`` may be 0, and "update" and "discard" put the library back on ``default``
    (the upstream's default branch).

    ``rewritten``: the upstream's history was changed and the library holds no work of the
    user's (its commit is one the upstream once had): ``local_commits`` are the upstream's own
    earlier commits, the choices are "keep" and "discard", and "discard" moves the library to
    the new history, after a backup.
    """

    def __init__(self, message, changed=(), entries_changed=None, new_commits=0, local_commits=0,
                 choices=("keep", "update", "send", "discard"), seen=None, branch=None, pull_request=None,
                 state=None, default=None, rewritten=False):
        self.changed, self.entries_changed = list(changed), entries_changed
        self.new_commits, self.local_commits = new_commits, local_commits
        self.choices, self.seen = tuple(choices), seen
        self.branch, self.pull_request, self.state, self.default = branch, pull_request, state, default
        self.rewritten = rewritten
        super().__init__(message)


class MissingDependency(CdlbibError):
    def __init__(self, package, extra, feature):
        self.package, self.extra, self.feature = package, extra, feature
        from .deps import manual_command  # deferred: deps imports this module
        super().__init__(f"{feature} needs the package '{package}' (install: {manual_command(extra, package)})")


class MissingProgram(MissingDependency):
    """A TeX program that is not installed and that this computer's TeX package manager can
    install as the current user (texinstall.plan). ``package`` is the program, ``extra`` is
    texinstall.EXTRA, ``command`` the argument list that installs it; deps.install runs it."""

    def __init__(self, program, feature, command, shown):
        self.package, self.extra, self.feature = program, "tex", feature
        self.command, self.shown = list(command), shown
        CdlbibError.__init__(self, f"{feature} needs the TeX program '{program}', which was not found on PATH "
                                   f"(install: {shown})")


class IdentityUnavailable(CdlbibError):
    pass


class SecretNotFound(CdlbibError):
    pass


class SecretMalformed(SecretNotFound):
    """A key is present but contains whitespace (it must be a single token)."""


class GateFailed(CdlbibError):
    """The gate did not pass. ``check`` is the gate's result (an api.LibraryCheck) when the
    gate ran to its verdict and said no; None when the check itself could not be done."""

    def __init__(self, message, check=None):
        self.check = check
        super().__init__(message)


class ApprovalRefused(CdlbibError):
    """An approval or revocation the library's records do not allow (stale fingerprint,
    blank field, revoked text replayed, nothing to revoke, unreadable storage)."""


class PublishRefused(CdlbibError):
    def __init__(self, message, needs_fork=False, upstream=None):
        self.needs_fork = needs_fork  # the user has no fork yet; a front end may offer to create it
        self.upstream = upstream      # the repository that would be forked, when needs_fork
        super().__init__(message)


class WriteConflict(CdlbibError):
    """A write that had to be taken back found that a file it had already replaced was changed
    again by something else. That file was left as it is (``files`` names each); the record
    of the write in progress is kept, so the next write refuses until a person has looked."""

    def __init__(self, message, files=()):
        self.files = [str(name) for name in files]
        super().__init__(message)


class NeedsConfirmation(CdlbibError):
    """Something a front end must ask the person before the core goes on: installing a
    missing optional package (``kind`` "install": ``package``, ``extra``, ``feature``) or
    creating their fork (``kind`` "fork": ``upstream``). ``question`` is the sentence to ask,
    word for word what the command line asks; the refusal that led here is ``__cause__``.
    Nothing was installed or created."""

    def __init__(self, kind, question, package=None, extra=None, feature=None, upstream=None):
        self.kind, self.question = kind, question
        self.package, self.extra, self.feature, self.upstream = package, extra, feature, upstream
        super().__init__(question)


class CompletionRefused(CdlbibError):
    """A source record that cannot be the record of an entry (a correction, erratum or
    retraction notice); the message says why."""


class TexLinkRefused(CdlbibError):
    """The path of the TeX link holds a file or link cdlbib did not make; it was left as it
    is. ``status`` is the tex.TexStatus found."""

    def __init__(self, message, status=None):
        self.status = status
        super().__init__(message)


class ExportFailed(CdlbibError):
    """An export for a manuscript could not be made. ``kind`` names the reason; ``detail`` is
    the text shown; ``names`` the files or citation keys the reason is about.

    Kinds: "no_tex" (a TeX program is not installed), "no_main" / "several_main" (which file
    is the paper), "no_source" (a .bbl needs the .tex), "resource_name" (a bibliography
    resource that is not a plain file name), "no_bibliography" (no bibliography command),
    "no_style" (no \\bibliographystyle and no biblatex), "missing_input" (a .bst, .cls, .sty
    or .bib that TeX could not find), "undefined_keys" (cited keys in no bibliography),
    "engine" / "backend" (LaTeX, or BibTeX/biber, stopped with an error), "engine_choice"
    (the paper asks for LuaLaTeX, which is run only when named), "citation_key" (a cited key with
    characters that cannot be written into a control file), "control_file" (the file LaTeX wrote for
    biber is not of the shape biblatex writes, or declares a source map that runs a regular
    expression), "too_large" (the paper's folder
    holds more than is copied for a compile), "output" (the output file may not be, or could not be,
    written), "files" (another file could not be read, copied or made)."""

    def __init__(self, kind, detail, names=()):
        self.kind, self.detail, self.names = kind, detail, list(names)
        super().__init__(detail)
