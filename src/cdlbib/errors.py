"""Every failure the core reports to a front end."""


class CdlbibError(Exception):
    """Base class. Front ends show str(error) and choose the exit code or dialog."""


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
    """

    def __init__(self, message, changed=(), entries_changed=None, new_commits=0, local_commits=0,
                 choices=("keep", "update", "send", "discard"), seen=None, branch=None, pull_request=None,
                 state=None, default=None):
        self.changed, self.entries_changed = list(changed), entries_changed
        self.new_commits, self.local_commits = new_commits, local_commits
        self.choices, self.seen = tuple(choices), seen
        self.branch, self.pull_request, self.state, self.default = branch, pull_request, state, default
        super().__init__(message)


class MissingDependency(CdlbibError):
    def __init__(self, package, extra, feature):
        self.package, self.extra, self.feature = package, extra, feature
        from .deps import manual_command  # deferred: deps imports this module
        super().__init__(f"{feature} needs the package '{package}' (install: {manual_command(extra, package)})")


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
