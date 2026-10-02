# cdlbib

`cdlbib` is a command-line tool and Python library for the
[CDL bibliography](https://github.com/ContextLab/CDL-bibliography), a shared BibTeX file
(`cdl.bib`). It checks that every entry follows the bibliography's formatting rules, and it
checks each entry's citation against published records (Crossref, Europe PMC, publisher
pages, library catalogues, preprint servers and others). It can also send a change to the
bibliography as a GitHub pull request.

## What it needs

- Python 3.11 or later.
- A clone of the bibliography repository. The package does not contain `cdl.bib` or the
  saved verification results; they are in the repository.
- The [GitHub CLI](https://cli.github.com) (`gh`), logged in with `gh auth login`, for
  three commands: `send`, `crossref approve` and `crossref revoke`. The other commands do
  not use it.

## Install

From a clone of the repository:

```bash
git clone https://github.com/ContextLab/CDL-bibliography.git
cd CDL-bibliography
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install .
cdlbib --version
```

```
cdlbib 2.0.0
```

From PyPI, once a release has been published there:

```bash
python -m pip install cdlbib
```

The clone is needed either way, because it holds `cdl.bib`.

## How it finds the library

`cdlbib` works on one folder that contains `cdl.bib`. It looks, in this order, at:

1. a file named with a command's `--fname` option or file argument;
2. the folder given with `cdlbib --library PATH`;
3. the folder named in the environment variable `CDLBIB_LIBRARY`;
4. the current folder, then each folder above it, until one contains `cdl.bib`.

If none is found it prints the following and exits with `2`:

```
No library found. Run inside a checkout that contains cdl.bib, pass --library PATH, or set CDLBIB_LIBRARY.
```

## Commands

`cdlbib --help` lists the commands, and `cdlbib COMMAND --help` lists a command's options.

|Command|What it does|
|-|-|
|`verify`|Format check, then citation verification of new/edited entries.|
|`compare`|Prints the differences between two `.bib` files.|
|`send`|Run the verify gate, then send the change as a pull request from your fork.|
|`magic`|Corrects the formatting of `cdl.bib` in place, then runs `send`. It prints `WARNING: potentially unsafe`.|
|`crossref`|Check citation accuracy against external evidence. Never edits BibTeX.|

Options before the command: `--library PATH`, `--version`, and `--yes` ("Answer yes to
confirmations: install a missing package, create your fork.").

The `crossref` group:

|Command|What it does|
|-|-|
|`crossref verify`|Verify new/modified entries; save every result so interrupted runs resume.|
|`crossref status`|Offline check: recompute fingerprints and fail on every unresolved entry.|
|`crossref restore`|Restore matching reviews from a trusted snapshot; changed entries stay pending.|
|`crossref snapshot`|Export a portable compressed JSONL audit snapshot for backup or sharing.|
|`crossref auto-review`|Automatically review cached findings; batch PubMed lookups through Europe PMC.|
|`crossref fulltext-review`|Review remaining entries using publisher front matter from open-access PMC XML.|
|`crossref discover-review`|Try twenty title-search candidates; apply the existing strict source checks.|
|`crossref review-packet`|Export source evidence and exact fingerprint for PDF/LLM/human review.|
|`crossref approve`|Record an explicit human decision, bound to the exact reviewed entry.|
|`crossref revoke`|Withdraw a human approval: audited, bound to its fingerprint, never restored.|
|`crossref attach-evidence`|Attach optional external research findings; human review remains required.|
|`crossref research`|Run optional LLM web search, download PDF, extract and check quoted evidence.|
|`crossref research-batch`|Collect actual PDF evidence in a bounded, resumable batch; never human-approve.|

## Checking the library

The output below was recorded with `cdlbib 2.0.0` on October 2, 2026, inside a clone.
Progress bars are left out. Counts will differ when you run the commands.

Check the formatting. This works offline.

```bash
cdlbib verify --no-citations
```

```
loading cdl.bib...done
format: looks good!
looks good!
```

Load the saved verification results from the repository into your local database, then
ask for the totals. Both commands work offline.

```bash
cdlbib crossref restore verification/baseline.jsonl.gz
cdlbib crossref status cdl.bib
```

```
Restored 6384 matching reviews
6384 entries: human_verified=36, metadata_verified=6348
```

Check formatting and accuracy together. The accuracy check contacts Crossref and other
public services, which ask for a contact address; give yours in `CROSSREF_MAILTO` or with
`--mailto`. Only entries that differ from the `master` version of `cdl.bib` on GitHub are
checked for accuracy; `--all` checks every entry.

```bash
export CROSSREF_MAILTO='you@example.org'
cdlbib verify
```

With one entry edited so that its last page is wrong (`MannEtal11`, in a scratch copy):

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

Each `UNRESOLVED` line gives the citation key, the status and the reason. The line under
it gives the closest source record and the fields that did not match. After the entry is
corrected, the same command ends with `looks good!`.

`verify`, `crossref verify` and `crossref status` exit with `0` when every selected entry
passes, `1` when the format check fails or an entry is not verified, and `2` when the
check could not be run (no library found, no contact address, a service error).

The statuses:

|Status|Meaning|
|-|-|
|`metadata_verified`|Every field agrees with a source record.|
|`human_verified`|A person checked this exact entry against the source and recorded an approval.|
|`needs_review`|Missing evidence, a disagreement with the source, or an unsupported field.|
|`provider_error`|A network or service failure prevented the check; it is retried next time.|
|`pending`|Not checked yet.|

A result belongs to an entry's exact text. Editing the entry, apart from renaming its key,
sends it back to `pending`.

## Recording a human review

For an entry that you have checked against the source itself and that the automatic check
cannot confirm:

```bash
cdlbib crossref review-packet MannEtal11 --output review-packet.json
```

The file holds the entry, its fingerprint and what the checker found. Pass the
`fingerprint` value to `approve`:

```bash
cdlbib crossref approve MannEtal11 \
  --fingerprint 'v2:1c1a69dd7e211570f273bd7690400f9b347bac79b3b285ec7f0e66b237d680a1' \
  --source 'URL or physical edition you checked' \
  --note 'Which fields you checked, and why the automatic check failed'
```

```
Human review recorded for MannEtal11; any source edit invalidates it.
```

The reviewer is recorded as the GitHub login that `gh` is logged in with. There is no
option for typing a name. `cdlbib crossref revoke KEY --reason 'Why'` withdraws an
approval and records who revoked it the same way; the revocation is appended to
`verification/revocations.jsonl`.

## Sending a change

```bash
cdlbib send --summary "Fix the page range of MannEtal11"
```

`send` runs the checks of `verify`. If one fails it prints the line below, exits with
`1`, and sends nothing:

```
not sent: fix the format errors and resolve every new/edited entry first (see `cdlbib verify`).
```

If the checks pass, `send`:

1. commits the changes to `cdl.bib` and to files under `verification/` on a new branch
   named `cdlbib/<your GitHub login>/<date>-<summary>`;
2. pushes that branch to your own fork of the repository;
3. opens a pull request from the branch into the repository the checkout was cloned from
   (or into its parent, if the checkout is a clone of a fork).

Other files with uncommitted changes are neither committed nor pushed. They are left as
they are and listed on a final line beginning `left uncommitted:`.

If your GitHub account has no fork of the repository, `send` asks before creating one.
`cdlbib --yes send` creates it without asking. Without a terminal, `send` prints the
`gh repo fork` command to run by hand and sends nothing.

The pull request's title is the `--summary` text. Its body lists the added, removed and
modified entries, followed by a line `Approved by @login: KEY, KEY` for each reviewer
whose approvals are part of the change. `send` prints the pull request's address and
leaves the checkout on the new branch. Running `send` again from that branch adds to the
same pull request.

## API keys

Only `crossref research` and `crossref research-batch` need an API key. They call a
language model through an adapter; two adapters are installed with the package,
`cdlbib-adapter-dartmouth` and `cdlbib-adapter-openai`.

|Service|Environment variable|Keychain item|
|-|-|-|
|Dartmouth Chat|`DARTMOUTH_CHAT_API_KEY`|`dartmouth-chat-api-key`|
|OpenAI|`OPENAI_API_KEY`|`openai-api-key`|

The key is read from the environment variable first, then from the system keychain, under
the item name above with your operating-system user name as the account. To store a key in
the keychain:

```bash
keyring set dartmouth-chat-api-key "$USER"
```

For a Dartmouth Chat key, Dartmouth Research Computing's page
[How do I connect my coding tool to Dartmouth Chat API?](https://rc.dartmouth.edu/ai/online-resources/connecting-ai-clients/)
says:

> To get your API Key, log into Dartmouth Chat and navigate as follows: Profile Picture(in the lower left-hand corner) > Settings > Account > API Key

On macOS, a keychain item created with the `security` command makes macOS show an access
prompt the first time Python reads it; choose "Always Allow". `cdlbib` waits at most 60
seconds for the keychain. When no key is found, it prints:

```
No API key found. Store it in the system keychain as 'dartmouth-chat-api-key' (account: your user name), or set the environment variable DARTMOUTH_CHAT_API_KEY.
```

## Reading PDFs

`crossref research` and `research-batch` read PDFs with the `pypdf` package, which is an
optional extra. From a clone, `python -m pip install ".[research]"` installs it; from
PyPI, once a release has been published there, `python -m pip install "cdlbib[research]"`.

If `pypdf` is missing when a command needs it, the command asks before installing it.
`cdlbib --yes ...` installs it without asking. Without a terminal, the command prints the
install command instead:

```
Reading PDF files needs the package 'pypdf' (install: pip install 'pypdf<7,>=6.0')
```

## Where results are stored

|Place|What it holds|
|-|-|
|`.bibcheck/verification.sqlite3`|Your local database of results and cached responses. Git ignores `.bibcheck/`.|
|`.bibcheck/report.jsonl`|A report with one JSON line per entry, including the evidence found for it.|
|`verification/baseline.jsonl.gz`|The saved result for every entry, shared through the repository. `crossref restore` reads it; `crossref snapshot` writes it.|
|`verification/revocations.jsonl`|Every withdrawn approval.|
|`verification/key-renames.json`, `verification/key-deletions.json`|Citation keys that were renamed or removed.|

`.bibcheck/` is created next to `cdl.bib`.

## Using it from Python

The functions behind the commands are in `cdlbib.api`. They return results and raise
errors; they do not print or prompt.

```python
from cdlbib import api, workspace

ws = workspace.Workspace("/path/to/CDL-bibliography")
print(api.check_format(ws).errors)
print(api.status(ws).counts)
```

```
[]
{'metadata_verified': 6348, 'human_verified': 36}
```

## More documentation

- Tutorials: <https://github.com/ContextLab/CDL-bibliography/blob/master/docs/tutorials.md>
- How verification works: <https://github.com/ContextLab/CDL-bibliography/blob/master/docs/verification.md>
- The formatting rules and the rest of the repository's documentation: <https://github.com/ContextLab/CDL-bibliography/blob/master/README.md>

## Licence

MIT. See <https://github.com/ContextLab/CDL-bibliography/blob/master/LICENSE>.
