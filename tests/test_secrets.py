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
