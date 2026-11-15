"""Every fetch test writes support-sample text to a temporary body cache, never ~/.cache."""

import pytest


@pytest.fixture(autouse=True)
def _private_body_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CITEWATCH_BODY_CACHE", str(tmp_path / "body-cache"))
