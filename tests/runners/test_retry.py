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


@pytest.mark.parametrize("status", [500, 501, 502, 503, 504, 520, 522, 524, 529, 408, 409, 429])
def test_every_server_error_and_rate_limit_is_retried(status):
    assert is_transient(StatusError(status))


def test_openai_missing_key_names_the_variable(monkeypatch):
    from citewatch.runners.openai_runner import OpenAIRunner

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="OPENAI_API_KEY"):
        OpenAIRunner("gpt-6.1-sol")


def test_usage_readers_match_the_parsers_on_recorded_responses():
    from citewatch.runners import anthropic_runner, openai_runner

    from .helpers import envelope

    for qid in ("v-901", "v-902"):
        c = envelope("claude-sonnet-5-5", qid)["answer"]
        u = anthropic_runner.usage(c["raw"])
        assert (u.tokens_in, u.tokens_out, u.cached_in, u.searches) == (
            c["tokens_in"],
            c["tokens_out"],
            c["cached_in"],
            c["searches"],
        )
        o = envelope("gpt-6.1-sol", qid)["answer"]
        v = openai_runner.usage(o["raw"])
        assert (v.tokens_in, v.tokens_out, v.cached_in, v.searches) == (
            o["tokens_in"],
            o["tokens_out"],
            o["cached_in"],
            o["searches"],
        )
    assert (
        anthropic_runner.usage([{"usage": {"input_tokens": "x", "output_tokens": -1}}]).tokens_in
        == 0
    )
