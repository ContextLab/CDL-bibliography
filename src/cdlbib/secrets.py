"""API keys. One lookup: the environment variable, then the system keychain.

The keychain is consulted only when the real process environment is being read
(``environ`` is None or ``os.environ``). A mapping passed in explicitly is the
complete configuration, so results never depend on what a machine has stored.
A key is never printed, logged or written to a file here.
"""
from dataclasses import dataclass
import getpass
import os

from .errors import SecretNotFound


@dataclass(frozen=True)
class Key:
    env: str
    item: str


KEYS = {
    "dartmouth-chat": Key(env="DARTMOUTH_CHAT_API_KEY", item="dartmouth-chat-api-key"),
    "openai": Key(env="OPENAI_API_KEY", item="openai-api-key"),
}


def reads_real_environment(environ):
    return environ is None or environ is os.environ


def from_keychain(name):
    """The stored key, or "" when none is stored or no keychain is usable."""
    try:
        import keyring
        return (keyring.get_password(KEYS[name].item, getpass.getuser()) or "").strip()
    except Exception:  # no backend (headless Linux) or a locked keychain: treated as "not stored"
        return ""


def missing(name):
    key = KEYS[name]
    return SecretNotFound(
        f"No API key found. Store it in the system keychain as '{key.item}' "
        f"(account: your user name), or set the environment variable {key.env}.")


def get(name, environ=None):
    key = KEYS[name]
    real = reads_real_environment(environ)
    source = os.environ if environ is None else environ
    value = (source.get(key.env) or "").strip()
    if not value and real:
        value = from_keychain(name)
    if not value:
        raise missing(name)
    if any(char.isspace() for char in value):
        raise SecretNotFound(f"The key for {name} must be a single token (found whitespace).")
    return value
