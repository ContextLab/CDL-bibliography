# Tutorials

Step-by-step walks through the `cdlbib` command: what to type and what you will see. The
[README](../README.md) describes every command; `cdlbib COMMAND --help` lists its options.

- [Add a paper](#add-a-paper)
- [Check the library](#check-the-library)
- [Contribute a pull request from the command line](#contribute-a-pull-request-from-the-command-line)
- [Setting an API key](#setting-an-api-key)

The output shown was recorded with `cdlbib 2.0.0` on October 2, 2026. Progress bars are
left out. Counts and dates will differ when you run the commands.

## Add a paper

After [installation](../README.md#installation), set your contact address and look
up a paper:

```bash
export CROSSREF_MAILTO='you@example.org'
cdlbib add 10.1002/tea.3660271011
```

The command proposes Zoller’s 1990 journal article. If it is already in your
library, the duplicate message gives its key and another copy is not added.
In a library without it, review the fields, sources and verification result before
answering `a`. Use `e` to edit first, `s` to skip, or `q` to stop. A capital `A`
accepts remaining complete proposals that need no decision.

For a duplicate already typed into the library, choose `r` to remove that typed
entry or `k` to keep both for the formatter. In the managed library, accepted
changes in one command share the printed `Batch backup` checkpoint;
`cdlbib update --undo` restores the state before those changes.

### Recorded add/edit session

The recording uses an empty scratch library and saved source responses. The entry
is verified against those records, edited to omit the optional issue number,
checked again, then accepted:

```text
Verification: metadata_verified
[a] accept   [e] edit   [s] skip   [A] accept all remaining   [q] stop
Your choice [a/e/s/A/q]: e
Saved entry.bib with the optional issue number omitted.
```

After the edit, the field display includes:

```text
number: 10 -> None (source: user edit)
Unfilled number: Removed in editor
Verification: metadata_verified
[a] accept   [e] edit   [s] skip   [A] accept all remaining   [q] stop
Your choice [a/e/s/A/q]: a
Added: Zoll90
```

The [full terminal transcript](media/add-session.txt) includes both entry displays
and the retained sources of the unchanged fields.

![Recorded cdlbib add session: review, edit, recheck and accept Zoll90](media/add.gif)

To regenerate this recording from a development checkout, run
`.venv/bin/python scripts/record_add.py --output-dir docs/media`. The recorder
creates an isolated library and cache from the saved responses.

See [the README](../README.md#add) for input forms, editor settings, supported
types, name questions and key renames. Accepting an entry writes the bibliography;
run `cdlbib verify` afterwards, then `cdlbib send` when ready to contribute it.

## Check the library

### 1. Install

`cdlbib` needs Python 3.11 or later:

```bash
python -m pip install cdlbib
cdlbib --version
```

```text
cdlbib 2.0.0
```

No clone is needed. The first command that needs the library downloads it. Run
`cdlbib where` to find the copy to edit; [Installation](../README.md#installation)
lists the locations and lookup order. If you already work in a clone, that copy is
used and never updated by the tool. For the remaining steps, change your terminal
directory to the folder printed by `cdlbib where`. This makes the relative paths
`cdl.bib` and `verification/baseline.jsonl.gz` refer to that library.

### 2. Check the formatting

After the first download, this check can run offline; an update-check failure prints a notice and uses the saved copy.

```bash
cdlbib verify --no-citations
```

```
loading cdl.bib...done
format: looks good!
looks good!
```

If an entry breaks a formatting rule, the problem is printed and the command exits with
`1`. For example, with the page range of `MannEtal11` reversed in a scratch copy:

```
loading cdl.bib...done
errors found: Exception: The following page numbers are ambiguous or incorrect: 
MannEtal11: (False, ['12897--12893', '12897--12893'])
```

Add `--verbose` for the full log.

### 3. Load the saved results

`verification/baseline.jsonl.gz` holds the saved verification result for every entry.
Load it into your local database (`.bibcheck/verification.sqlite3`, which git ignores),
then ask for the totals:

```bash
cdlbib crossref restore verification/baseline.jsonl.gz
cdlbib crossref status cdl.bib
```

```
Restored 6384 matching reviews
6384 entries: human_verified=36, metadata_verified=6348
```

`status` works offline. It exits with `0` when every entry is verified and `1` when some
are not.

### 4. Check formatting and accuracy together

The accuracy check contacts Crossref and other public services, which ask for a contact
address. Set yours, then run `verify` without `--no-citations`:

```bash
export CROSSREF_MAILTO='you@example.org'
cdlbib verify
```

`verify` offers completion for new or changed entries before checking the final
file. Use the same accept/edit/skip choices as `add`; `--no-complete` skips the
offers while retaining the format and citation checks. `verify --no-citations`
skips offers and works offline after the library has been downloaded. Autofix or
output-copy mode also skips offers; review the copy, then run normal `verify` on it.

With no new or edited entries:

```
loading cdl.bib...done
format: looks good!
citations: 0 of 0 new/edited entries verified; network requests: 0
library: 6384 entries: human_verified=36, metadata_verified=6348
looks good!
```

`verify` checks the accuracy of the entries that differ from the `master` version of
`cdl.bib` on GitHub. The `library:` line counts every entry.

### 5. Read an UNRESOLVED line

The output below comes from a scratch copy of the library in which the last page of
`MannEtal11` was changed from 12897 to 12899, so that the check fails:

```
loading cdl.bib...done
format: looks good!
Offline reassessment: 0 accepted
Second-source DOIs checked: 1/1; requests: 2
citations: 0 of 1 new/edited entries verified; network requests: 3
  UNRESOLVED MannEtal11 (needs_review): No unambiguous, fully supported metadata match; DOI-linked publisher/PubMed article coordinates conflict with or are missing from the citation
    closest source crossref 10.1073/pnas.1015174108: pages: missing evidence or mismatch
  Inspect with `cdlbib crossref review-packet KEY`; after checking the source, record a decision with `cdlbib crossref approve`.
library: 6384 entries: human_verified=36, metadata_verified=6347, needs_review=1
```

The command exits with `1`. Each `UNRESOLVED` line gives the citation key, the status in
parentheses, and the reason. The line under it gives the closest source record and the
fields that did not match: here, `pages`. The full record of each check is saved in
`.bibcheck/report.jsonl`.

After the entry is corrected to match the paper (here, the page is changed back), the same
command passes:

```
loading cdl.bib...done
format: looks good!
citations: 0 of 0 new/edited entries verified; network requests: 0
library: 6384 entries: human_verified=36, metadata_verified=6348
looks good!
```

### 6. Record a human review

This step is for an entry that you have checked against the source itself and that the
automatic check cannot confirm. The [README](../README.md#human-review) describes when
it applies. `approve` records your GitHub login as the reviewer, so the
[GitHub CLI](https://cli.github.com) must be installed and logged in (`gh auth login`).

Export the entry, its fingerprint, and what the checker found:

```bash
cdlbib crossref review-packet MannEtal11 --output review-packet.json
```

```
review-packet.json
```

The file is JSON with the fields `key`, `fingerprint`, `entry`, `raw`, `verification` and
`instructions`. Copy the `fingerprint` value into the next command:

```bash
cdlbib crossref approve MannEtal11 \
  --fingerprint 'v2:1c1a69dd7e211570f273bd7690400f9b347bac79b3b285ec7f0e66b237d680a1' \
  --source 'URL or physical edition you checked' \
  --note 'Which fields you checked, and why the automatic check failed'
```

```
Human review recorded for MannEtal11; any source edit invalidates it.
```

`cdlbib crossref status cdl.bib` then counts the entry under `human_verified`:

```
6384 entries: human_verified=37, metadata_verified=6347
```

The example output in this step was recorded on the scratch copy from step 5, before the
entry was corrected. An approval can be withdrawn with
`cdlbib crossref revoke MannEtal11 --reason 'Why'`, which prints:

```
Revoked MannEtal11 approval 3844e6da2f1b (fingerprint v2:1c1a69dd7e211570f273bd7690400f9b347bac79b3b285ec7f0e66b237d680a1); entry now needs_review
```

### Screencast

![Terminal recording of cdlbib verify --no-citations followed by cdlbib crossref status cdl.bib](media/check.gif)

Steps 2 and 3: `cdlbib verify --no-citations`, then `cdlbib crossref status cdl.bib`.
`scripts/make_screencasts.sh` records this GIF again into `docs/media/`, working on a
temporary copy of the library outside the repository.

## Contribute a pull request from the command line

`cdlbib send` checks your change and sends it as a pull request from your own fork. You
do not need write access to the upstream repository.

### 1. Log in to GitHub

Install the [GitHub CLI](https://cli.github.com), then:

```bash
gh auth login
gh auth status
```

`gh auth status` names the account you are logged in as. `cdlbib send` uses that
account for the fork and the pull request.

### 2. Edit `cdl.bib`

Start with `cdlbib` installed (step 1 of
[Check the library](#check-the-library)) and `CROSSREF_MAILTO` set (step 4). Add or
correct entries in `cdl.bib`.

### 3. Check the change

```bash
cdlbib verify
```

Correct anything it reports, as in steps 4 and 5 of [Check the library](#check-the-library),
until it ends with `looks good!`.

### 4. Send it

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

### 5. What the pull request shows

- Its title is the `--summary` text. Without `--summary`, the title is the first line of
  the change list.
- Its body is the list of added, removed and modified entries. If entries in the change
  have a recorded human review, a line `Approved by @login: KEY, KEY` follows for each
  reviewer.
- It comes from the branch `cdlbib/<your login>/<date>-<summary>` of your fork and goes
  into the `master` branch of the repository your checkout was cloned from (or of its
  parent, if you cloned a fork).

### 6. Afterwards

Your checkout stays on the new branch. Running `cdlbib send` again from that branch
adds the new changes to the same pull request. To return to `master`:

```bash
git switch master
```

## Setting an API key

`cdlbib crossref research` and `research-batch` call a language model through an adapter
and need that service's API key. The other commands need no key.

|Service|Environment variable|Keychain item|
|-|-|-|
|Dartmouth Chat|`DARTMOUTH_CHAT_API_KEY`|`dartmouth-chat-api-key`|
|OpenAI|`OPENAI_API_KEY`|`openai-api-key`|

For a Dartmouth Chat key, Dartmouth Research Computing's page
[How do I connect my coding tool to Dartmouth Chat API?](https://rc.dartmouth.edu/ai/online-resources/connecting-ai-clients/)
says:

> To get your API Key, log into Dartmouth Chat and navigate as follows: Profile Picture(in the lower left-hand corner) > Settings > Account > API Key

`cdlbib` looks for the key in the environment variable first, then in the system
keychain, under the item name above with your operating-system user name as the account.
To store a key in the keychain:

```bash
keyring set dartmouth-chat-api-key "$USER"
```

The command asks for the key and does not display it. To use the environment variable
instead:

```bash
export DARTMOUTH_CHAT_API_KEY='paste-your-key-here'
```

On macOS, a keychain item created with the `security` command makes macOS show an
access prompt the first time Python reads it; choose "Always Allow". `cdlbib` waits at
most 60 seconds for the keychain. When no key is found, it prints:

```
No API key found. Store it in the system keychain as 'dartmouth-chat-api-key' (account: your user name), or set the environment variable DARTMOUTH_CHAT_API_KEY.
```

These two commands also read PDFs, which needs the `pypdf` package. Install it with
`python -m pip install "cdlbib[research]"`. If it is missing, the command prints a
notice and installs it. Use `cdlbib --ask crossref research ...` to be asked first;
without a terminal that option leaves the package uninstalled and prints:

```text
Reading PDF files needs the package 'pypdf' (install: pip install 'pypdf<7,>=6.0')
```
