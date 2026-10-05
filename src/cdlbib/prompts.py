"""The wording of the questions and choices every front end shows. Text only: nothing here
prints, prompts or decides."""
from . import workspace
from .workspace import BIB_NAME

CHOSEN_BY = {
    workspace.Origin.NAMED: "the file you named",
    workspace.Origin.OPTION: "--library",
    workspace.Origin.ENVIRONMENT: "CDLBIB_LIBRARY",
    workspace.Origin.FOUND: f"{BIB_NAME} found in or above the current folder",
    workspace.Origin.MANAGED: "no library named or found; this is the copy cdlbib downloads and manages",
}


ANSWERS = {"keep": ("k", "Keep working without updating (ask again tomorrow)"),
           "update": ("u", "Update and keep my changes"),
           "send": ("s", "Send my changes first (runs `cdlbib send`)"),
           "discard": ("d", "Discard my changes and update (they are saved first; `cdlbib update --undo` brings them back)")}


MOVED = {"keep": ("k", "Keep working with the copy here (ask again tomorrow)"),
         "discard": ("m", "Move to the new version (the copy here is saved first; `cdlbib update --undo` brings it back)")}


def answers(exc):
    """{choice: (letter, what it does)} for the question ``exc`` asks."""
    return MOVED if exc.rewritten else ANSWERS


def unsent_question(exc):
    """The question about unsent changes, as it is printed (errors.UpdateNeedsDecision)."""
    if exc.rewritten:       # no changes of the user's: the upstream replaced its own history
        return "\n".join(["The history of the bibliography's upstream was changed, and the copy here matches an older "
                          "version of it (it holds no changes of yours).", "What would you like to do?"]
                         + [f"  [{MOVED[choice][0]}] {MOVED[choice][1]}" for choice in exc.choices])
    count, commits, new = exc.entries_changed, exc.local_commits, exc.new_commits
    counted = f" ({count} {'entry' if count == 1 else 'entries'} changed)" if count else ""
    lines = [f"A newer version of the bibliography is available ({new} new commit{'' if new == 1 else 's'}), "
             "and you have changes that have not been sent:"]
    if exc.branch:       # on the branch of an earlier send: the question is about that branch
        lines = [f"Your pull request {exc.pull_request} was merged, and you have changes on branch {exc.branch} that "
                 "have not been sent:" if exc.state == "merged" else
                 f"Your pull request {exc.pull_request} was closed without being merged. Branch {exc.branch} is still "
                 "selected."]
    if commits:
        lines.append(f"  {commits} commit{'' if commits == 1 else 's'} that the upstream does not have"
                     + ("" if BIB_NAME in exc.changed else counted.replace(" changed)", f" of {BIB_NAME} changed)")))
    lines += [f"  {name}{counted if name == BIB_NAME else ''}" for name in exc.changed[:10]]
    if len(exc.changed) > 10:
        lines.append(f"  ... and {len(exc.changed) - 10} more")
    lines.append("What would you like to do?")
    lines += [f"  [{ANSWERS[choice][0]}] {ANSWERS[choice][1]}" for choice in exc.choices]
    if exc.branch:
        if "update" not in exc.choices and commits:
            lines.append("  (Updating and keeping your changes is not offered: the branch has commits that the upstream "
                         "does not have.)")
        if "send" not in exc.choices:
            lines.append("  (Sending is not offered: the branch has commits that the upstream does not have.)"
                         if exc.state == "merged" else
                         "  (Sending is not offered: the pull request was closed, and a new change needs a new branch.)")
        lines.append(f"  (Updating or discarding puts the library back on branch {exc.default}; your changes are saved "
                     "in a backup first.)")
        return "\n".join(lines)
    if "update" not in exc.choices:
        lines.append("  (Updating and keeping your changes is not offered: the library has commits that the upstream "
                     "does not have.)")
    if "send" not in exc.choices:
        lines.append("  (Sending is not offered: there are no uncommitted changes to send.)")
    return "\n".join(lines)
