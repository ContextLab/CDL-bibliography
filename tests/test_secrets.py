import getpass
import os
import sys
import uuid

import keyring
import pytest

from cdlbib import secrets
from cdlbib.errors import SecretNotFound


def test_names_and_places():
    assert secrets.KEYS["dartmouth-chat"].env == "DARTMOUTH_CHAT_API_KEY"
    assert secrets.KEYS["dartmouth-chat"].item == "dartmouth-chat-api-key"
    assert secrets.KEYS["openai"].env == "OPENAI_API_KEY"
    assert secrets.KEYS["openai"].item == "openai-api-key"


def test_environment_variable_wins():
    assert secrets.get("openai", environ={"OPENAI_API_KEY": "sk-from-env"}) == "sk-from-env"


def test_whitespace_in_a_key_is_rejected():
    with pytest.raises(SecretNotFound, match="single token"):
        secrets.get("openai", environ={"OPENAI_API_KEY": "two words"})


@pytest.fixture
def scratch_key(monkeypatch):
    """A real keychain item under a throwaway name, removed afterwards."""
    item = "cdlbib-test-" + uuid.uuid4().hex
    try:
        keyring.set_password(item, getpass.getuser(), "value-from-keychain")
    except keyring.errors.KeyringError as exc:
        pytest.skip(f"no usable system keychain here ({type(exc).__name__})")
    monkeypatch.setitem(secrets.KEYS, "scratch", secrets.Key(env="CDLBIB_TEST_SCRATCH_KEY", item=item))
    monkeypatch.delenv("CDLBIB_TEST_SCRATCH_KEY", raising=False)
    yield item
    try:
        keyring.delete_password(item, getpass.getuser())
    except keyring.errors.PasswordDeleteError:
        pass  # the test already removed it


def test_keychain_is_read_when_the_variable_is_unset(scratch_key):
    assert secrets.get("scratch") == "value-from-keychain"


def test_the_real_environment_object_also_reaches_the_keychain(scratch_key):
    assert secrets.get("scratch", os.environ) == "value-from-keychain"


def test_environment_variable_beats_the_keychain(scratch_key, monkeypatch):
    monkeypatch.setenv("CDLBIB_TEST_SCRATCH_KEY", "from-env")
    assert secrets.get("scratch") == "from-env"


def test_an_explicit_mapping_never_consults_the_keychain(scratch_key):
    with pytest.raises(SecretNotFound):
        secrets.get("scratch", environ={})


def test_an_explicit_mapping_containing_the_variable_is_used(scratch_key):
    assert secrets.get("scratch", environ={"CDLBIB_TEST_SCRATCH_KEY": "explicit"}) == "explicit"


def test_missing_key_names_both_places(scratch_key):
    keyring.delete_password(scratch_key, getpass.getuser())
    with pytest.raises(SecretNotFound) as err:
        secrets.get("scratch")
    assert "CDLBIB_TEST_SCRATCH_KEY" in str(err.value) and scratch_key in str(err.value)


def test_missing_key_with_an_explicit_mapping_names_both_places():
    with pytest.raises(SecretNotFound) as err:
        secrets.get("openai", environ={})
    assert "OPENAI_API_KEY" in str(err.value) and "openai-api-key" in str(err.value)


@pytest.mark.skipif(sys.platform != "darwin", reason="the security command is macOS only")
@pytest.mark.skipif(
    os.environ.get("CDLBIB_TEST_KEYCHAIN_PROMPT") != "1",
    reason="an item made by the security tool makes macOS show a GUI 'allow access' prompt to the "
    "Python process, which hangs an unattended run; set CDLBIB_TEST_KEYCHAIN_PROMPT=1 and click Always Allow",
)
def test_an_item_made_the_way_dartmouths_page_says_is_found(monkeypatch):
    import subprocess
    item = "cdlbib-test-" + uuid.uuid4().hex
    subprocess.run(["security", "add-generic-password", "-s", item, "-a", getpass.getuser(), "-w", "made-by-security"], check=True)
    try:
        monkeypatch.setitem(secrets.KEYS, "scratch", secrets.Key(env="CDLBIB_TEST_SCRATCH_KEY", item=item))
        monkeypatch.delenv("CDLBIB_TEST_SCRATCH_KEY", raising=False)
        assert secrets.get("scratch") == "made-by-security"
    finally:
        subprocess.run(["security", "delete-generic-password", "-s", item, "-a", getpass.getuser()], check=True, capture_output=True)


# ---- fix round 1: whitespace, bounded keychain wait, unreadable keychain ----

import threading
import time

import keyring.backend
import keyring.backends.fail

from cdlbib import dartmouth_research_adapter as dra


@pytest.mark.parametrize("value", ["two words", "abc\n", " abc", "a\tb"])
def test_dartmouth_variable_with_whitespace_is_a_single_token_error(value):
    with pytest.raises(ValueError, match="single token"):
        dra.configuration({"DARTMOUTH_CHAT_API_KEY": value})


@pytest.mark.parametrize("env", [{}, {"DARTMOUTH_CHAT_API_KEY": ""}])
def test_dartmouth_missing_variable_names_both_places(env):
    with pytest.raises(ValueError) as err:
        dra.configuration(env)
    assert "DARTMOUTH_CHAT_API_KEY" in str(err.value) and "dartmouth-chat-api-key" in str(err.value)


@pytest.mark.parametrize("value", ["two words", "abc\n", " abc"])
def test_secrets_get_rejects_whitespace_without_stripping(value):
    with pytest.raises(SecretNotFound, match="single token"):
        secrets.get("openai", {"OPENAI_API_KEY": value})


@pytest.mark.parametrize("env", [{}, {"OPENAI_API_KEY": ""}])
def test_secrets_get_missing_or_empty_is_not_found(env):
    with pytest.raises(SecretNotFound, match="No API key found"):
        secrets.get("openai", env)


def test_within_returns_a_value_in_time():
    assert secrets._within(5, lambda: "ok") == "ok"


def test_within_times_out_on_a_slow_function():
    started = time.monotonic()
    with pytest.raises(secrets.KeychainTimeout):
        secrets._within(0.2, lambda: time.sleep(3))
    assert time.monotonic() - started < 2


def test_within_surfaces_an_exception():
    def boom():
        raise KeyError("x")
    with pytest.raises(KeyError):
        secrets._within(5, boom)


@pytest.fixture
def backend(monkeypatch):
    """Install a real keyring backend for a test, restoring the previous one afterwards."""
    previous = keyring.get_keyring()
    monkeypatch.setitem(secrets.KEYS, "scratch", secrets.Key(env="CDLBIB_TEST_SCRATCH_KEY", item="cdlbib-test-unused"))
    monkeypatch.delenv("CDLBIB_TEST_SCRATCH_KEY", raising=False)
    yield keyring.set_keyring
    keyring.set_keyring(previous)


class SlowBackend(keyring.backend.KeyringBackend):
    priority = 1

    def get_password(self, service, username):
        time.sleep(3)

    def set_password(self, service, username, password):
        pass

    def delete_password(self, service, username):
        pass


class EmptyBackend(SlowBackend):
    def get_password(self, service, username):
        return None


def test_a_slow_keychain_becomes_a_timeout_message(backend, monkeypatch):
    backend(SlowBackend())
    monkeypatch.setattr(secrets, "KEYCHAIN_TIMEOUT", 0.2)
    with pytest.raises(SecretNotFound, match="did not answer") as err:
        secrets.get("scratch")
    assert "Always Allow" in str(err.value) and "CDLBIB_TEST_SCRATCH_KEY" in str(err.value)


def test_no_keyring_backend_says_the_keychain_could_not_be_read(backend):
    backend(keyring.backends.fail.Keyring())
    with pytest.raises(SecretNotFound) as err:
        secrets.get("scratch")
    assert "the keychain could not be read: NoKeyringError" in str(err.value)
    assert "cdlbib-test-unused" in str(err.value)


def test_an_absent_item_keeps_the_plain_message(backend):
    backend(EmptyBackend())
    with pytest.raises(SecretNotFound) as err:
        secrets.get("scratch")
    assert "could not be read" not in str(err.value) and "No API key found" in str(err.value)


def test_a_copy_of_the_environment_never_reaches_the_keychain(backend, monkeypatch):
    class Loud(EmptyBackend):
        def get_password(self, service, username):
            return "from-keychain"
    backend(Loud())
    assert secrets.get("scratch") == "from-keychain"
    with pytest.raises(SecretNotFound):
        secrets.get("scratch", dict(os.environ))
