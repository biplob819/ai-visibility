import pytest

from citewatch.runners import anthropic_runner, openai_runner
from citewatch.runners.anthropic_runner import AnthropicRunner
from citewatch.runners.openai_runner import OpenAIRunner

from .helpers import CFG, Q1, FakeAnthropic, FakeOpenAI, claude_raw, envelope, openai_raw


@pytest.mark.contract
@pytest.mark.parametrize("qid", ["v-901", "v-902"])
def test_recorded_responses_validate_against_the_sdk_models(qid):
    import anthropic
    from openai.types.responses import Response

    for r in envelope("claude-sonnet-5-5", qid)["answer"]["raw"]:
        anthropic.types.Message.model_validate(r)
    for r in envelope("gpt-6.1-sol", qid)["answer"]["raw"]:
        Response.model_validate(r)


@pytest.mark.parametrize("qid", ["v-901", "v-902"])
def test_parsing_recorded_responses_reproduces_the_stored_answer(qid):
    for model, mod in (("claude-sonnet-5-5", anthropic_runner), ("gpt-6.1-sol", openai_runner)):
        env = envelope(model, qid)["answer"]
        raw = env["raw"] if model.startswith("claude") else env["raw"][0]
        a = mod.parse(model, raw, env["request"])
        for f in (
            "answer_text",
            "searches",
            "tokens_in",
            "tokens_out",
            "cached_in",
            "refusal",
            "stop_reason",
        ):
            assert getattr(a, f) == env[f], (model, qid, f)


def test_recorded_claude_answers_carry_api_citations():
    # D-34: without allowed_callers=["direct"] these were empty
    for qid in ("v-901", "v-902"):
        raw = claude_raw(qid)
        cites = [
            c for b in raw["content"] if b["type"] == "text" for c in (b.get("citations") or [])
        ]
        assert cites and all(c["type"] == "web_search_result_location" for c in cites)


def test_runner_round_trip_through_sdk_models():
    fake = FakeAnthropic([claude_raw()])
    a = AnthropicRunner("claude-sonnet-5-5", client=fake).ask(Q1, CFG)
    assert a.searches == 1 and a.answer_text and len(fake.calls) == 1
    assert fake.calls[0]["model"] == "claude-sonnet-5-5"
    fo = FakeOpenAI([openai_raw()])
    b = OpenAIRunner("gpt-6.1-sol", client=fo).ask(Q1, CFG)
    assert b.searches == 1 and fo.calls[0]["max_tool_calls"] == 3


def test_pause_turn_is_continued_with_the_assistant_content():
    paused = claude_raw()
    paused["stop_reason"] = "pause_turn"
    fake = FakeAnthropic([paused, claude_raw()])
    a = AnthropicRunner("claude-sonnet-5-5", client=fake).ask(Q1, CFG)
    assert a.continuations == 1 and len(fake.calls) == 2
    second = fake.calls[1]["messages"]
    assert second[0]["role"] == "user" and second[1]["role"] == "assistant"
    assert a.searches == 2  # usage summed across both responses


def test_pause_turn_is_continued_at_most_three_times():
    paused = claude_raw()
    paused["stop_reason"] = "pause_turn"
    fake = FakeAnthropic([paused] * 5)
    a = AnthropicRunner("claude-sonnet-5-5", client=fake).ask(Q1, CFG)
    assert len(fake.calls) == 4 and a.stop_reason == "pause_turn"


def test_a_refusal_is_recorded_once_with_its_category():
    refused = claude_raw()
    refused["stop_reason"] = "refusal"
    refused["stop_details"] = {"type": "refusal", "category": "bio", "explanation": "x"}
    fake = FakeAnthropic([refused])
    a = AnthropicRunner("claude-sonnet-5-5", client=fake).ask(Q1, CFG)
    assert a.refusal and a.refusal_category == "bio" and len(fake.calls) == 1


def test_server_tool_errors_are_recorded_not_raised():
    raw = claude_raw()
    for b in raw["content"]:
        if b["type"] == "web_search_tool_result":
            b["content"] = {
                "type": "web_search_tool_result_error",
                "error_code": "max_uses_exceeded",
            }
            break
    a = anthropic_runner.parse("claude-sonnet-5-5", [raw], {})
    assert a.search_errors == ["max_uses_exceeded"]


def test_openai_refusal_and_actions():
    raw = openai_raw("v-902")
    a = openai_runner.parse("gpt-6.1-sol", raw, {})
    assert a.search_actions == ["search", "open_page"] and a.searches == 1  # only search is billed
    for item in raw["output"]:
        if item["type"] == "message":
            item["content"] = [{"type": "refusal", "refusal": "I can't help with that."}]
    r = openai_runner.parse("gpt-6.1-sol", raw, {})
    assert r.refusal and r.stop_reason == "refusal" and r.answer_text == ""


def test_provider_facts_are_recorded_as_decisions():
    from harness_lib import ROOT

    text = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
    for needle in (
        "| D-31 |",
        "$10 per 1,000 searches",
        "max_tool_calls",
        "defaults search to the United States",
        "| D-34 |",
        "allowed_callers",
        "| D-35 |",
        "198 days ago",
        "| D-36 |",
        "utm_source=openai",
    ):
        assert needle in text, needle


def test_usage_is_summed_over_every_continuation():
    """N1.2 v2: pricing only the last response would under-record spend."""
    paused = claude_raw()
    paused["stop_reason"] = "pause_turn"
    final = claude_raw()
    one = anthropic_runner.usage([final])
    both = anthropic_runner.usage([paused, final])
    assert both.tokens_in == 2 * one.tokens_in and both.tokens_out == 2 * one.tokens_out
    assert both.searches == 2 * one.searches and one.tokens_in > 0


def test_any_error_after_a_paid_response_returns_what_was_paid():
    paused = claude_raw()
    paused["stop_reason"] = "pause_turn"
    from .helpers import StatusError

    rc = AnthropicRunner(
        "claude-sonnet-5-5", client=FakeAnthropic([paused, StatusError(413)])
    ).call(Q1, CFG)
    assert len(rc.responses) == 1 and rc.error is not None
    assert rc.error.startswith("provider:413 during continuation")
    with pytest.raises(StatusError):  # before anything is paid, the error is raised as before
        AnthropicRunner("claude-sonnet-5-5", client=FakeAnthropic([StatusError(400)])).call(Q1, CFG)
