"""DEM-02 and DEM-05: live mode asks one question of both models with the §7.1 settings and
shows citations only, never the answer prose (D-17); a visitor's own keys still pass the
passkey, the per-request cap and the rate limit, are never counted against the owner's daily
cap, and never reach a log, the store or the page. Every provider call here is a fake."""

from __future__ import annotations

import dataclasses
import logging
import os
from typing import Any

import pytest

from citewatch.cost import load_measured, load_prices
from citewatch.demo.guard import PER_REQUEST_CAP_USD, SpendGuard
from citewatch.demo.kv import SqliteKV
from citewatch.demo.live import (
    LIVE_QUESTION_ID,
    LiveCitation,
    ModelCitations,
    ProviderKeys,
    citations_from,
    live_html,
    make_runners,
    request_bound_usd,
    run_live,
)
from citewatch.runners import anthropic_runner, openai_runner
from citewatch.runners.anthropic_runner import AnthropicRunner
from citewatch.runners.openai_runner import OpenAIRunner
from citewatch.schemas import StudyQuestion
from harness_lib import ROOT
from tests.runners.helpers import CFG, FakeAnthropic, FakeOpenAI, claude_raw, openai_raw

A, B = "claude-sonnet-5-5", "gpt-6.1-sol"
PROSE = "PROSE-SENTINEL the answer says you should rest and drink water"
QUESTION = "QUESTION-SENTINEL how much is a prescription in England?"
# fake keys, built at run time so no key-shaped literal sits in the repo
KEY_A = "-".join(["visitor", "anthropic", "key", "7f3a9c"])
KEY_O = "-".join(["visitor", "openai", "key", "2b8e41"])
PRICES = load_prices()
MEASURED = load_measured(ROOT / "studies" / "uk-health" / "cost_model.yaml")


def with_prose(model: str, raw: dict[str, Any]) -> dict[str, Any]:
    """The recorded response with sentinel prose added to every piece of answer text."""
    if model == A:
        for block in raw["content"]:
            if block.get("type") == "text":
                block["text"] = block["text"] + " " + PROSE
    else:
        for item in raw["output"]:
            if item.get("type") == "message":
                for part in item["content"]:
                    if part.get("type") == "output_text":
                        part["text"] = part["text"] + " " + PROSE  # indices stay valid
    return raw


def fake_runners(*models: str, error: Exception | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if A in models:
        out[A] = AnthropicRunner(A, client=FakeAnthropic([error or with_prose(A, claude_raw())]))
    if B in models:
        out[B] = OpenAIRunner(B, client=FakeOpenAI([error or with_prose(B, openai_raw())]))
    return out


@pytest.fixture
def kv(tmp_path):
    return SqliteKV(tmp_path / "demo.sqlite")


@pytest.fixture
def guard(kv):
    return SpendGuard(kv, today=lambda: "2026-11-17")


def ask(guard: SpendGuard, runners: dict[str, Any], *, owner: bool, question: str = QUESTION):
    return run_live(
        question,
        identity="credential-1",
        cfg=CFG,
        guard=guard,
        runners=runners,
        prices=PRICES,
        measured=MEASURED,
        owner_keys=owner,
    )


# --- citations only (D-17) ----------------------------------------------------------------------


@pytest.mark.safety
def test_live_page_never_shows_answer_prose(guard, caplog):
    caplog.set_level(logging.INFO, logger="citewatch.demo")
    runners = fake_runners(A, B)
    result = ask(guard, runners, owner=True)
    html = live_html(result)
    assert result.refused is None
    # the fakes' answers really did carry the prose ...
    full = anthropic_runner.parse(A, [with_prose(A, claude_raw())], {}).answer_text
    assert PROSE in full
    assert PROSE in openai_runner.parse(B, with_prose(B, openai_raw()), {}).answer_text
    # ... and none of it reaches the result, the page or the log
    for text in (html, repr(result), caplog.text):
        assert "PROSE-SENTINEL" not in text
        assert full not in text
    assert "QUESTION-SENTINEL" not in caplog.text


@pytest.mark.safety
def test_live_result_types_have_no_field_for_prose():
    assert {f.name for f in dataclasses.fields(LiveCitation)} == {
        "url",
        "publisher",
        "quoted_span",
    }
    assert {f.name for f in dataclasses.fields(ModelCitations)} == {
        "model",
        "citations",
        "cost_usd",
        "latency_ms",
        "note",
    }


def test_live_page_shows_url_publisher_and_quoted_span(guard):
    result = ask(guard, fake_runners(A, B), owner=True)
    by = {m.model: m for m in result.models}
    claude, gpt = by[A], by[B]
    assert claude.citations and gpt.citations
    html = live_html(result)
    for c in claude.citations + gpt.citations:
        assert c.url in html.replace("&amp;", "&") and c.publisher in html
    assert all(c.quoted_span for c in claude.citations)  # Claude's cited_text from the page
    assert all(c.quoted_span is None for c in gpt.citations)  # GPT gives no page quote
    assert "No quote" in html


def test_citations_are_canonical_deduplicated_and_mapped_by_publisher_of():
    raw = claude_raw()
    once = citations_from(A, [raw])
    twice = citations_from(A, [raw, claude_raw()])
    assert once == twice  # the same URL and quote twice is one row
    assert all(c.url.startswith("https://") for c in once)
    gpt = citations_from(B, [openai_raw()])
    assert [c.publisher for c in gpt] == ["nhs.uk"]


def test_html_is_escaped(guard):
    evil = ModelCitations(
        A,
        (LiveCitation("https://x.example/<script>", "x.example", "<img src=x onerror=alert(1)>"),),
    )
    from citewatch.demo.live import LiveResult

    html = live_html(LiveResult(models=(evil,)))
    assert "<script>" not in html and "<img" not in html


# --- the §7.1 settings --------------------------------------------------------------------------


@pytest.mark.contract
def test_live_asks_both_models_with_the_study_settings(guard):
    runners = fake_runners(A, B)
    ask(guard, runners, owner=True)
    sq = StudyQuestion(
        id=LIVE_QUESTION_ID,
        text=" ".join(QUESTION.split()),
        intent=CFG.intents[0],
        time_sensitive=False,
    )
    claude_call = runners[A].client.calls[0]
    assert claude_call == {"model": A, **anthropic_runner.build_request(sq, CFG)}
    tool = claude_call["tools"][0]
    assert tool["allowed_callers"] == ["direct"] and tool["max_uses"] == 3
    assert tool["user_location"]["country"] == "GB"
    gpt_call = runners[B].client.calls[0]
    assert gpt_call == {"model": B, **openai_runner.build_request(sq, CFG)}
    assert gpt_call["max_tool_calls"] == 3 and gpt_call["reasoning"] == {"effort": "medium"}


def test_cost_is_priced_from_usage(guard):
    result = ask(guard, fake_runners(A, B), owner=True)
    assert result.cost_usd == pytest.approx(sum(m.cost_usd for m in result.models))
    assert all(m.cost_usd > 0 for m in result.models)
    assert 0 < result.cost_usd < result.bound_usd


# --- caps ----------------------------------------------------------------------------------------


@pytest.mark.safety
def test_owner_keys_are_counted_against_the_daily_cap(guard):
    result = ask(guard, fake_runners(A, B), owner=True)
    assert guard.spent_today() == pytest.approx(result.cost_usd, abs=1e-6)


@pytest.mark.safety
def test_own_keys_are_not_counted_against_the_daily_cap(guard):
    result = ask(guard, fake_runners(A, B), owner=False)
    assert result.refused is None and result.cost_usd > 0
    assert guard.spent_today() == 0


@pytest.mark.safety
def test_own_keys_still_work_when_the_owner_budget_is_spent(kv):
    g = SpendGuard(kv, per_request_cap=3.0, today=lambda: "2026-11-17")
    g.reserve("someone", 3.0, owner_keys=True)
    refused = ask(g, fake_runners(A, B), owner=True)
    assert refused.refused and "used up" in refused.refused
    assert ask(g, fake_runners(A, B), owner=False).refused is None


@pytest.mark.safety
@pytest.mark.parametrize("owner", [True, False])
def test_per_request_cap_refuses_before_any_call(kv, owner):
    g = SpendGuard(kv, per_request_cap=0.05, today=lambda: "2026-11-17")
    runners = fake_runners(A, B)
    result = ask(g, runners, owner=owner)
    assert result.refused and "per-request limit" in result.refused
    assert runners[A].client.calls == [] and runners[B].client.calls == []
    assert g.spent_today() == 0


def test_bound_fits_the_default_cap_and_covers_measured_cost():
    bound = request_bound_usd(CFG, PRICES, MEASURED)
    assert 0.2 < bound <= PER_REQUEST_CAP_USD
    assert MEASURED is not None
    assert bound > 3 * sum(m["mean_cost_usd"] for m in _measured_rows().values())


def _measured_rows() -> dict[str, dict[str, float]]:
    import yaml

    return yaml.safe_load((ROOT / "studies/uk-health/cost_model.yaml").read_text(encoding="utf-8"))[
        "models"
    ]


@pytest.mark.parametrize("question", ["", "   ", "x" * 301])
def test_bad_questions_are_refused_without_calls(guard, question):
    runners = fake_runners(A, B)
    result = ask(guard, runners, owner=True, question=question)
    assert result.refused
    assert runners[A].client.calls == []


def test_a_model_without_a_key_gets_a_note_and_the_other_still_runs(guard):
    result = ask(guard, fake_runners(A), owner=False)
    by = {m.model: m for m in result.models}
    assert by[A].citations and by[B].note == "No openai key given."
    assert result.bound_usd == pytest.approx(request_bound_usd(CFG, PRICES, MEASURED, [A]))


def test_no_keys_at_all_is_refused(guard):
    assert ask(guard, {}, owner=False).refused


# --- the visitor's keys (DEM-05) -----------------------------------------------------------------


@pytest.mark.safety
def test_own_keys_reach_only_the_provider_clients(guard, kv, caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    keys = ProviderKeys(anthropic=KEY_A, openai=KEY_O)
    runners: dict[str, Any] = make_runners(keys, CFG.models)
    assert runners[A].client.api_key == KEY_A  # handed straight to the SDK client
    assert runners[B].client.api_key == KEY_O
    assert KEY_A not in repr(keys) and KEY_O not in repr(keys)
    # swap in fakes so nothing leaves the machine, then run the request
    runners[A].client = FakeAnthropic([with_prose(A, claude_raw())])
    runners[B].client = FakeOpenAI([with_prose(B, openai_raw())])
    result = run_live(
        QUESTION,
        identity="credential-1",
        cfg=CFG,
        guard=guard,
        runners=runners,
        prices=PRICES,
        measured=MEASURED,
        owner_keys=False,
    )
    stored = kv.path.read_bytes()
    for key in (KEY_A, KEY_O):
        assert key not in caplog.text
        assert key.encode() not in stored
        assert key not in live_html(result) and key not in repr(result)
        assert key not in os.environ.values()


@pytest.mark.safety
def test_provider_errors_are_never_echoed(guard, caplog):
    caplog.set_level(logging.DEBUG)

    class AuthError(Exception):
        status_code = 401

    err = AuthError(f"Incorrect API key provided: {KEY_A}")
    result = ask(guard, fake_runners(A, error=err), owner=False)
    by = {m.model: m for m in result.models}
    assert by[A].note == "The provider rejected the API key."
    assert KEY_A not in live_html(result) and KEY_A not in caplog.text


def test_failed_calls_cost_nothing_and_settle_the_hold(guard):
    class Down(Exception):
        status_code = 400

    result = ask(guard, fake_runners(A, B, error=Down("bad request")), owner=True)
    assert result.cost_usd == 0 and guard.spent_today() == 0
    assert all("HTTP 400" in (m.note or "") for m in result.models)
