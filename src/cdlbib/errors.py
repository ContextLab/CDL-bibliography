"""Every failure the core reports to a front end."""


class CdlbibError(Exception):
    """Base class. Front ends show str(error) and choose the exit code or dialog."""


class WorkspaceNotFound(CdlbibError):
    pass


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
    pass


class ApprovalRefused(CdlbibError):
    """An approval or revocation the library's records do not allow (stale fingerprint,
    blank field, revoked text replayed, nothing to revoke, unreadable storage)."""


class PublishRefused(CdlbibError):
    def __init__(self, message, needs_fork=False):
        self.needs_fork = needs_fork
        super().__init__(message)
