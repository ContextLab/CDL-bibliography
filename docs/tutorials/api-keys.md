# API keys

`cdlbib crossref research` and `research-batch` call a language model through an adapter
and need that service's API key. So does reading a PDF with a language model in the web
interface ([Add references](adding-references.md#reading-a-pdf-with-a-language-model)).
The other commands need no key.

|Service|Environment variable|Keychain item|
|-|-|-|
|Dartmouth Chat|`DARTMOUTH_CHAT_API_KEY`|`dartmouth-chat-api-key`|
|OpenAI|`OPENAI_API_KEY`|`openai-api-key`|

- [A Dartmouth Chat key](#a-dartmouth-chat-key)
- [Where `cdlbib` looks for a key](#where-cdlbib-looks-for-a-key)
- [An OpenAI key (optional)](#an-openai-key-optional)
- [Checking what is set up](#checking-what-is-set-up)
- [Optional packages](#optional-packages)
- [What was not verified](#what-was-not-verified)

In [the terminal interface](terminal-interface.md), the Setup view (`F8`) lists both keys
as `not checked` until `c` is pressed; `c` reads the system keychain.

## A Dartmouth Chat key

Dartmouth Chat is the default model service. For a Dartmouth Chat key, Dartmouth Research
Computing's page
[How do I connect my coding tool to Dartmouth Chat API?](https://rc.dartmouth.edu/ai/online-resources/connecting-ai-clients/)
says:

> To get your API Key, log into Dartmouth Chat and navigate as follows: Profile Picture(in the lower left-hand corner) > Settings > Account > API Key

## Where `cdlbib` looks for a key

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

## An OpenAI key (optional)

OpenAI is the second, optional service. `cdlbib` gives these steps for it:

```text
Create an OpenAI API key. Store it in the system keychain as 'openai-api-key' (account: your user name), or set the environment variable OPENAI_API_KEY. Also set the environment variable BIBCHECK_RESEARCH_MODEL to the model to use.
```

With `OPENAI_API_KEY` set and `BIBCHECK_RESEARCH_MODEL` not set, the web interface's
"Read with OpenAI" button is marked "not set up".

For Dartmouth Chat, the steps `cdlbib` gives end with the sentence "Only models the
Dartmouth catalogue lists as free are used."

## Checking what is set up

Recorded with `cdlbib 2.0.0` on October 5, 2026, on a computer with `OPENAI_API_KEY` set
and a Dartmouth Chat key stored in the system keychain with `keyring set`.

`cdlbib setup --check` reports each key in its list headed `available on this computer:`.
It reads the system keychain to do so, and prints
`reading the system keychain for the Dartmouth Chat key ...` first.

```text
  Dartmouth Chat key: yes (stored in the system keychain)
  OpenAI key: yes (set in the environment variable OPENAI_API_KEY)
```

Without a stored key, the first of these lines is:

```text
  Dartmouth Chat key: no (No API key found.) Store it in the system keychain as 'dartmouth-chat-api-key' (account: your user name), or set the environment variable DARTMOUTH_CHAT_API_KEY.
```

The **Setup** view of [the web interface](web-interface.md) shows the same list without
reading the keychain. A key that is not in an environment variable is "not checked":

```text
not checked: DARTMOUTH_CHAT_API_KEY is not set, and the system keychain was not read
```

The "check" button beside it reads the keychain. The view says:

```text
A check of the GitHub login asks gh over the network; a check of a key reads the system keychain, which may ask for permission.
```

## Optional packages

The two `crossref` commands also read PDFs, which needs the `pypdf` package. Install it with
`python -m pip install "cdlbib[research]"`. If it is missing, the command prints a
notice and installs it. Use `cdlbib --ask crossref research ...` to be asked first;
without a terminal that option leaves the package uninstalled and prints:

```text
Reading PDF files needs the package 'pypdf' (install: pip install 'pypdf<7,>=6.0')
```

## What was not verified

The macOS keychain access prompt (the "Always Allow" window) did not appear during the
recordings for these tutorials: the key was stored with `keyring set`, and macOS did not
ask when `cdlbib` read it.
