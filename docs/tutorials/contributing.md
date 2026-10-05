# Contribute a pull request

`cdlbib send` checks your change and sends it as a pull request from your own fork. You
do not need write access to the upstream repository.

## 1. Log in to GitHub

Install the [GitHub CLI](https://cli.github.com), then:

```bash
gh auth login
gh auth status
```

`gh auth status` names the account you are logged in as. `cdlbib send` uses that
account for the fork and the pull request.

## 2. Edit `cdl.bib`

Start with `cdlbib` installed (step 1 of
[Check the library](checking.md#1-install)) and `CROSSREF_MAILTO` set (step 4). Add or
correct entries in `cdl.bib`.

## 3. Check the change

```bash
cdlbib verify
```

Correct anything it reports, as in steps 4 and 5 of [Check the library](checking.md),
until it ends with `looks good!`.

## 4. Send it

```bash
cdlbib send --summary "Fix the page range of MannEtal11"
```

`send` runs the checks of `verify` again and prints the same lines. If a check fails
it prints the line below, exits with `1`, and sends nothing:

```
not sent: fix the format errors and resolve every new/edited entry first (see `cdlbib verify`).
```

If the checks pass it prints `checks passed; generating commit message...` and the list
of added, removed and modified entries.

If your GitHub account has no fork of the repository yet, `send` prints a notice
and creates one. Run `cdlbib --ask send` to be asked first. With `--ask`, an answer
of `n` or a run without a terminal sends nothing and prints the manual fork command.

`send` requires the tracked `cdl.bib`; another filename can be checked with
`verify` or `compare`. It also checks every outgoing commit against the upstream
pull request base. Unrelated committed files cause a refusal, even if a later
commit deleted them. Preserve that branch and prepare a bibliography-only branch
from the upstream base.

`send` then commits your changes to `cdl.bib` and to files under `verification/` on a
new branch, pushes the branch to your fork, and opens the pull request. Other files with
uncommitted changes are neither committed nor pushed; they are left as they are. `send` ends
with these lines (the first only when a fork was created, the last only when other files
have uncommitted changes; `notes.txt` stands for such a file):

```
created fork you/CDL-bibliography
committed: cdl.bib
pull request: <address of the pull request>
you are now on branch cdlbib/you/2026-10-02-fix-the-page-range-of-mannetal11
left uncommitted: notes.txt
```

## 5. What the pull request shows

- Its title is the `--summary` text. Without `--summary`, the title is the first line of
  the change list.
- Its body is the list of added, removed and modified entries. If entries in the change
  have a recorded human review, a line `Approved by @login: KEY, KEY` follows for each
  reviewer.
- It comes from the branch `cdlbib/<your login>/<date>-<summary>` of your fork and goes
  into the `master` branch of the repository your checkout was cloned from (or of its
  parent, if you cloned a fork).

## 6. Afterwards

Your checkout stays on the new branch. Running `cdlbib send` again from that branch
adds the new changes to the same pull request. To return to `master`:

```bash
git switch master
```

<!-- TUI steps: added with the terminal interface -->

## In the web interface

Start [the web interface](web-interface.md) with `cdlbib web` and open the **Send** view.

- "What will be sent" shows the library's folder, its branch and the files to send.
- "Look for completions" shows, for new or changed entries that are not yet verified,
  what the sources would fill in or change. Nothing is written unless a proposal is
  accepted.
- "Check and send" runs the format check and the citation check of every new or edited
  entry, then commits `cdl.bib` and `verification/` on a branch, pushes it to your fork
  and opens or updates the pull request. The box above the button takes one line
  describing the change; it is optional.

The lines of the checks appear under "Log".

![The Send view of the web interface on a managed library with one changed file: "What will be sent" lists the library folder, the branch master and the file cdl.bib; below it are the "Completion offers" panel with a "Look for completions" button and the "Send the change" panel with a one-line description box, a "Check and send" button and an empty log](../media/web-send.png)

For a library that is not a git checkout, the view shows instead:

```text
~/demo/library is not a git checkout of its own, so there is no branch and nothing to send
```

(`~/demo` stands for the temporary folder used for this recording, on October 5, 2026.)

## What was not verified

Creating a fork for a GitHub account that has none has not been run against GitHub. The
lines about it above describe what the command prints.
