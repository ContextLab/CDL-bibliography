"""The GitHub copy of the library is fetched with the proxies of the moment of the call."""
import urllib.request

import pytest

from cdlbib import helpers, verification_cli
from test_complete_cli import refused_network


def test_a_proxy_set_after_an_earlier_download_is_still_honoured(monkeypatch, tmp_path):
    """urllib.request.urlopen builds its opener once and keeps it, with the proxies the
    environment held then; a later change of proxy would be ignored for the life of the
    process (a long-running interface, or the next test)."""
    urllib.request.install_opener(urllib.request.build_opener())      # as after any earlier urlopen call
    for name, value in refused_network().items():
        monkeypatch.setenv(name, value)
    with pytest.raises(OSError, match="Cannot download the reference bibliography"):
        verification_cli.reference_bib("github", tmp_path)
    assert not (tmp_path / "reference-github.bib").exists()
    with pytest.raises(OSError):
        helpers.load_bibliography(helpers.LATEST_BIBFILE, verbose=False)
