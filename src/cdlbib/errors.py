"""Every failure the core reports to a front end."""


class CdlbibError(Exception):
    """Base class. Front ends show str(error) and choose the exit code or dialog."""


class WorkspaceNotFound(CdlbibError):
    pass


class MissingDependency(CdlbibError):
    def __init__(self, package, extra, feature):
        self.package, self.extra, self.feature = package, extra, feature
        super().__init__(f"{feature} needs the package '{package}' (install: pip install 'cdlbib[{extra}]')")


class IdentityUnavailable(CdlbibError):
    pass


class SecretNotFound(CdlbibError):
    pass


class GateFailed(CdlbibError):
    pass


class PublishRefused(CdlbibError):
    def __init__(self, message, needs_fork=False):
        self.needs_fork = needs_fork
        super().__init__(message)
