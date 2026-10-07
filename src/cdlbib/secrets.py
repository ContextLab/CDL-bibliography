"""API keys. One lookup: the environment variable, then the system keychain.

The keychain is consulted only when the real process environment is being read
(``environ`` is None or ``os.environ`` itself). A mapping passed in explicitly,
including a copy such as ``dict(os.environ)``, is the complete configuration, so
results never depend on what a machine has stored. A key is never printed,
logged or written to a file here.

The keychain read waits at most KEYCHAIN_TIMEOUT seconds. On macOS the read can
block on a GUI "allow access" prompt (for example for an item made with the
``security`` tool); an unattended process would otherwise hang. On timeout
SecretNotFound says so: choose "Always Allow" in the prompt, then retry.

When the environment variable CDLBIB_NO_KEYCHAIN is set to 1, the keychain is
never read: only the key's environment variable counts. This is for unattended
runs (a scheduled job, a test run) on a machine whose keychain holds a key.
"""
from dataclasses import dataclass
import getpass
import os
import threading

from .errors import SecretMalformed, SecretNotFound

KEYCHAIN_TIMEOUT = 60
NO_KEYCHAIN = "CDLBIB_NO_KEYCHAIN"


@dataclass(frozen=True)
class Key:
    env: str
    item: str


KEYS = {
    "dartmouth-chat": Key(env="DARTMOUTH_CHAT_API_KEY", item="dartmouth-chat-api-key"),
    "openai": Key(env="OPENAI_API_KEY", item="openai-api-key"),
}


class KeychainTimeout(Exception):
    pass


def reads_real_environment(environ):
    return environ is None or environ is os.environ


def keychain_off(environ=None):
    """CDLBIB_NO_KEYCHAIN=1: this process is not to read the keychain."""
    return (os.environ if environ is None else environ).get(NO_KEYCHAIN) == "1"


def _within(seconds, fn):
    """Return fn()'s value, surface its exception, or raise KeychainTimeout after `seconds`."""
    outcome = {}

    def work():
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # handed to the caller below, not swallowed
            outcome["error"] = exc

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise KeychainTimeout()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def places(name):
    key = KEYS[name]
    return (f"Store it in the system keychain as '{key.item}' "
            f"(account: your user name), or set the environment variable {key.env}.")


def from_keychain(name):
    """The stored key ("" when no item is stored). Raises SecretNotFound if the keychain cannot be read."""
    import keyring
    from keyring.errors import KeyringError

    try:
        value = _within(KEYCHAIN_TIMEOUT, lambda: keyring.get_password(KEYS[name].item, getpass.getuser()))
    except KeychainTimeout:
        raise SecretNotFound(
            f"The keychain did not answer within {KEYCHAIN_TIMEOUT} seconds; macOS may be showing an "
            f"access prompt (choose \"Always Allow\", then retry). {places(name)}") from None
    except KeyringError as exc:  # locked or denied keychain, or no backend (headless Linux)
        raise SecretNotFound(
            f"No API key found (the keychain could not be read: {type(exc).__name__}). {places(name)}") from None
    return value or ""


def get(name, environ=None):
    """The API key for `name`: the environment variable, then (real environment only) the keychain.

    Only None or os.environ itself reaches the keychain; a copy such as dict(os.environ) is treated
    as a complete, explicit configuration. A missing or empty value is SecretNotFound; a present
    value containing any whitespace is SecretMalformed (a SecretNotFound), never stripped.
    """
    key = KEYS[name]
    source = os.environ if environ is None else environ
    value = source.get(key.env) or ""
    if not value and reads_real_environment(environ):
        if keychain_off():
            raise SecretNotFound(f"No API key found ({NO_KEYCHAIN}=1: the system keychain was not read). "
                                 f"Set the environment variable {key.env}.")
        value = from_keychain(name)
    if not value:
        raise SecretNotFound(f"No API key found. {places(name)}")
    if any(char.isspace() for char in value):
        raise SecretMalformed(f"The key for {name} must be a single token (found whitespace).")
    return value
