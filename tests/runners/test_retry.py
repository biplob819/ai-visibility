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


def test_a_stop_ends_retries_at_once():
    import threading

    from citewatch.runners.base import TransportError, with_retries

    from .helpers import StatusError

    stop = threading.Event()
    stop.set()
    slept: list[float] = []
    calls = []

    def flaky():
        calls.append(1)
        raise StatusError(503)

    with pytest.raises(TransportError, match="stopped"):
        with_retries(flaky, sleep=slept.append, stop=stop)
    assert len(calls) == 1 and slept == []


def test_a_stop_during_the_backoff_makes_no_further_request():
    """v5 M1: Ctrl-C while a worker sleeps between retries ends the retries at once."""
    import threading
    import time

    from citewatch.runners.base import TransportError, with_retries

    from .helpers import StatusError

    stop = threading.Event()
    calls: list[float] = []
    t0 = time.monotonic()

    def flaky():
        calls.append(time.monotonic() - t0)
        raise StatusError(529)

    threading.Timer(0.3, stop.set).start()
    with pytest.raises(TransportError, match="during backoff"):
        with_retries(flaky, stop=stop)
    assert len(calls) == 1 and time.monotonic() - t0 < 1.5


def test_a_stop_ends_a_paused_turn_and_keeps_what_was_paid():
    import threading

    from citewatch.runners.anthropic_runner import AnthropicRunner

    from .helpers import CFG, Q1, FakeAnthropic, claude_raw

    paused = claude_raw()
    paused["stop_reason"] = "pause_turn"
    fake = FakeAnthropic([paused, claude_raw()])
    r = AnthropicRunner("claude-sonnet-5-5", client=fake)
    r.stop = threading.Event()
    r.stop.set()
    rc = r.call(Q1, CFG)
    assert len(fake.calls) == 1 and len(rc.responses) == 1
    assert rc.error is not None and rc.error.startswith("stopped during continuation")


@pytest.mark.parametrize("which", ["anthropic", "openai"])
def test_each_runner_hands_its_stop_to_the_retries(which):
    """N1.2 v6 M-1: a Ctrl-C during a runner's backoff makes no further paid request."""
    import threading

    from citewatch.runners.anthropic_runner import AnthropicRunner
    from citewatch.runners.openai_runner import OpenAIRunner

    from .helpers import CFG, Q1, FakeAnthropic, FakeOpenAI, StatusError, claude_raw, openai_raw

    if which == "anthropic":
        fake = FakeAnthropic([StatusError(529), claude_raw()])
        r = AnthropicRunner("claude-sonnet-5-5", client=fake)
    else:
        fake = FakeOpenAI([StatusError(529), openai_raw()])
        r = OpenAIRunner("gpt-6.1-sol", client=fake)
    r.stop = threading.Event()
    threading.Timer(0.2, r.stop.set).start()
    from citewatch.runners.base import TransportError

    with pytest.raises(TransportError, match="during backoff"):
        r.call(Q1, CFG)
    assert len(fake.calls) == 1
