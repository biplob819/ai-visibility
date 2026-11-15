import itertools

import pytest

from citewatch.env import MissingKeyError
from citewatch.runners.anthropic_runner import AnthropicRunner
from citewatch.runners.base import TransportError, is_transient, with_retries

from .helpers import CFG, Q1, FakeAnthropic, StatusError, claude_raw


def test_transient_errors_back_off_and_succeed_on_the_sixth_try():
    sleeps = []
    fake = FakeAnthropic([StatusError(529)] * 5 + [claude_raw()])
    a = AnthropicRunner("claude-sonnet-5-5", client=fake, sleep=sleeps.append).ask(Q1, CFG)
    assert len(fake.calls) == 6 and a.answer_text
    assert len(sleeps) == 5 and all(s2 >= s1 - 1 for s1, s2 in itertools.pairwise(sleeps))


def test_six_failures_become_a_transport_error():
    fake = FakeAnthropic([StatusError(503)] * 6)
    with pytest.raises(TransportError, match="6 attempts"):
        AnthropicRunner("claude-sonnet-5-5", client=fake, sleep=lambda _s: None).ask(Q1, CFG)
    assert len(fake.calls) == 6


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_never_retried(status):
    fake = FakeAnthropic([StatusError(status)])
    with pytest.raises(StatusError):
        AnthropicRunner("claude-sonnet-5-5", client=fake, sleep=lambda _s: None).ask(Q1, CFG)
    assert len(fake.calls) == 1


def test_transient_classification():
    class APIConnectionError(Exception):
        pass

    assert is_transient(StatusError(429)) and is_transient(APIConnectionError())
    assert not is_transient(StatusError(400)) and not is_transient(ValueError("x"))
    calls = []
    assert with_retries(lambda: calls.append(1) or "ok", sleep=lambda _s: None) == "ok"


def test_a_missing_key_is_a_configuration_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="ANTHROPIC_API_KEY"):
        AnthropicRunner("claude-sonnet-5-5")
