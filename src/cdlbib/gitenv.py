"""The environment of every git (and gh) subprocess cdlbib runs.

git reads its repository from the environment before it looks at the folder it is run in:
with GIT_DIR exported (as inside a git hook, `git rebase --exec` and some editor tooling) a
command meant for one clone acts on another. Every subprocess is therefore given an
environment without those variables, and names its repository itself (cwd or -C). This
module imports nothing from the package, so any module can use it.
"""
import os

# The variables that tell git which repository, index, object store or work tree to use, or
# where to stop looking for one. Identity (GIT_AUTHOR_*, GIT_COMMITTER_*), configuration
# (GIT_CONFIG_*), transport (GIT_SSH*, GIT_ASKPASS, GIT_ALLOW_PROTOCOL) and tracing are kept.
REPOSITORY_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_PREFIX",
                        "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM")


def git_env(environ=None):
    """A copy of the environment for a git subprocess: no variable that points git at a
    repository, and GIT_TERMINAL_PROMPT=0 (git never stops to ask for a password)."""
    environ = os.environ if environ is None else environ
    env = {name: value for name, value in environ.items() if name not in REPOSITORY_VARIABLES}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env
