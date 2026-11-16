"""SUP-02, SUP-03: claim and evidence, the replacement rule, EvalKit items and verdicts.

Fully offline: EvalKit is driven by a scripted fake adapter, never a provider.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from citewatch.fetch import fetch_pages
from citewatch.schemas import StudyQuestion
from citewatch.schemas.cards import SupportVerdict
from citewatch.store import RawStore
from citewatch.support import judge as J
from tests.fetch.web import HTML, FakeWeb, make


@pytest.fixture
def evalkit():
    return pytest.importorskip("evalkit")


# ---- SUP-02: sentences -------------------------------------------------------------------------


def test_sentences_are_split_and_headings_and_fragments_dropped():
    text = "\n".join(
        [
            "Best Project Management Tools for 2026",  # title
            "Pricing",  # heading
            "Home About Contact Blog Careers Press Partners Help Center",  # menu, title-case
            "Asana costs $10.99 per user per month. It offers a free plan for small teams!",
            "Read more.",  # fragment
            "Dr. Smith said the U.S. plan is cheaper than most rivals today.",
            "Is it worth the money for a team? Most reviewers say yes for teams of ten or more.",
        ]
    )
    assert J.evidence_sentences(text) == (
        "Asana costs $10.99 per user per month.",
        "It offers a free plan for small teams!",
        "Dr. Smith said the U.S. plan is cheaper than most rivals today.",
        "Is it worth the money for a team?",
        "Most reviewers say yes for teams of ten or more.",
    )


def test_a_long_unpunctuated_line_of_prose_is_kept():
    line = "the free tier includes unlimited tasks and up to fifteen collaborators per workspace"
    assert J.evidence_sentences(line) == (line,)
    assert J.evidence_sentences("") == ()


def test_one_sentence_quote():
    assert J.one_sentence("It is free. It also has a paid plan.") == "It is free."
    assert J.one_sentence("  Only   one sentence here.  ") == "Only one sentence here."
    assert J.one_sentence("") is None
    long = "word " * 100
    q = J.one_sentence(long)
    assert q is not None and len(q) == J.QUOTE_MAX and q.endswith("…")
    SupportVerdict(citation_ref="1:v-001:claude-x:1", judge="j", verdict="supported", quote=q)


def test_text_path_matches_what_the_fetcher_writes(tmp_path):
    url = "https://a.example/s"
    body = b"<html><body><p>Asana costs ten dollars per user per month.</p></body></html>"
    web = FakeWeb({url: httpx.Response(200, headers=HTML, content=body)})
    store = RawStore(tmp_path)
    cache = tmp_path / "bodies"
    client, _log, _ = make(tmp_path, web, store=store)
    fetch_pages([url], client=client, store=store, keep_text=frozenset({url}), body_cache=cache)
    assert J.text_path(url, cache).is_file()
    assert J.cached_sentences(url, cache) == ("Asana costs ten dollars per user per month.",)


def test_item_ids_round_trip():
    ref = "1:v-017:gpt-6.1-sol:3"
    assert ":" not in J.item_id(ref) and J.ref_of(J.item_id(ref)) == ref


# ---- SUP-01: the replacement rule --------------------------------------------------------------


def row(model: str, intent: str, rank: int, *, per_stratum: int = 2) -> dict[str, Any]:
    q = {"compare": 1, "howto": 2}[intent]
    return {
        "citation_ref": f"1:v-{q:03d}:{model}:{rank + 1}",
        "url": f"https://{model}.example/{intent}/{rank}",
        "model": model,
        "intent": intent,
        "question_id": f"v-{q:03d}",
        "rank": rank,
        "role": "sample" if rank < per_stratum else "reserve",
        "seed": 7,
    }


def sample_rows() -> list[dict[str, Any]]:
    # 2 sampled + 2 reserves per stratum, shuffled to prove order comes from (stratum, rank)
    rows = [
        row(m, i, r)
        for m in ("gpt-6.1-sol", "claude-x")
        for i in ("howto", "compare")
        for r in range(4)
    ]
    return rows[::-1]


def refs(rows):
    return [r["citation_ref"] for r in rows]


def test_all_ok_keeps_the_sample_in_stratum_and_rank_order():
    rows = sample_rows()
    final, log = J.replacements(rows, {r["url"] for r in rows})
    assert log == []
    assert refs(final) == [
        "1:v-001:claude-x:1",
        "1:v-001:claude-x:2",
        "1:v-002:claude-x:1",
        "1:v-002:claude-x:2",
        "1:v-001:gpt-6.1-sol:1",
        "1:v-001:gpt-6.1-sol:2",
        "1:v-002:gpt-6.1-sol:1",
        "1:v-002:gpt-6.1-sol:2",
    ]
    assert all(r["role"] == "sample" and "replaces" not in r for r in final)


def test_a_failed_sample_takes_the_next_reserve_of_its_own_stratum():
    rows = sample_rows()
    bad = {"https://claude-x.example/compare/0", "https://claude-x.example/compare/2"}
    ok = {r["url"] for r in rows} - bad
    final, log = J.replacements(rows, ok)
    stratum = [r for r in final if r["model"] == "claude-x" and r["intent"] == "compare"]
    # rank 0 failed, reserve rank 2 failed too, so reserve rank 3 takes rank 0's slot
    assert refs(stratum) == ["1:v-001:claude-x:4", "1:v-001:claude-x:2"]
    assert stratum[0]["replaces"] == "1:v-001:claude-x:1" and stratum[0]["role"] == "reserve"
    assert log == [
        {
            "model": "claude-x",
            "intent": "compare",
            "replaced": "1:v-001:claude-x:1",
            "reason": "fetch not ok",
            "by": "1:v-001:claude-x:4",
            "skipped": ["1:v-001:claude-x:3"],
        }
    ]
    assert len(final) == 8


def test_a_stratum_that_runs_out_of_reserves_stays_short():
    rows = sample_rows()
    bad = {f"https://gpt-6.1-sol.example/howto/{r}" for r in (0, 1, 2)}
    final, log = J.replacements(rows, {r["url"] for r in rows} - bad)
    stratum = [r for r in final if r["model"] == "gpt-6.1-sol" and r["intent"] == "howto"]
    assert refs(stratum) == ["1:v-002:gpt-6.1-sol:4"]  # rank 0 replaced by rank 3; rank 1 lost
    assert [(e["replaced"], e["by"], e["skipped"]) for e in log] == [
        ("1:v-002:gpt-6.1-sol:1", "1:v-002:gpt-6.1-sol:4", ["1:v-002:gpt-6.1-sol:3"]),
        ("1:v-002:gpt-6.1-sol:2", None, []),
    ]
    assert len(final) == 7


def test_an_ok_page_without_cached_text_is_replaced(tmp_path):
    rows = sample_rows()
    for r in rows:
        if r["url"] != "https://claude-x.example/howto/1":
            J.text_path(r["url"], tmp_path).write_text(
                "A sentence with enough words in it.", encoding="utf-8"
            )
    J.text_path("https://claude-x.example/howto/0", tmp_path).write_text(
        "Just A Title", encoding="utf-8"
    )
    final, log = J.replacements(rows, {r["url"] for r in rows}, cache_dir=tmp_path)
    assert [(e["replaced"], e["reason"], e["by"]) for e in log] == [
        ("1:v-002:claude-x:1", "no cached text", "1:v-002:claude-x:3"),
        ("1:v-002:claude-x:2", "no cached text", "1:v-002:claude-x:4"),
    ]
    assert len(final) == 8


# ---- SUP-03: items -----------------------------------------------------------------------------


QUESTIONS = [
    StudyQuestion(
        id="v-001", text="Which tool is cheapest?", intent="compare", time_sensitive=False
    ),
    StudyQuestion(id="v-002", text="How do I start?", intent="howto", time_sensitive=False),
]


def citations_for(rows):
    return [
        {
            "run": 1,
            "question_id": r["question_id"],
            "model": r["model"],
            "ordinal": r["rank"] + 1,
            "url": r["url"],
            "answer_span": f"Span for {r['citation_ref']}.",
        }
        for r in rows
    ]


def test_items_use_the_sample_and_promoted_reserves_only(tmp_path, evalkit):
    rows = sample_rows()
    text = "Heading\nThe tool costs ten dollars a month. It has a free plan for small teams."
    for r in rows:
        if r["url"] != "https://claude-x.example/compare/1":  # no cached text: needs a reserve
            J.text_path(r["url"], tmp_path).write_text(text, encoding="utf-8")
    final, log = J.replacements(rows, {r["url"] for r in rows}, cache_dir=tmp_path)
    assert [e["replaced"] for e in log] == ["1:v-001:claude-x:2"]

    raw_items = J.items_for(rows, citations_for(rows), QUESTIONS, tmp_path)
    assert len(raw_items) == 7  # reserves ignored, the uncached sample skipped

    items = J.items_for(final, citations_for(rows), QUESTIONS, tmp_path)
    assert len(items) == 8
    first = items[0]
    assert first.id == "1_v-001_claude-x_1" and ":" not in first.id
    assert first.question == "Which tool is cheapest?"
    assert first.explanation == "Span for 1:v-001:claude-x:1."
    assert first.evidence == (
        "The tool costs ten dollars a month.",
        "It has a free plan for small teams.",
    )
    assert items[1].id == "1_v-001_claude-x_3"  # the promoted reserve
    assert isinstance(first, evalkit.scorers.faithfulness.FaithfulnessItem)


# ---- SUP-03: judging through EvalKit with a fake adapter ---------------------------------------

# EvalKit's faithfulness extractor prompt (EvalKit D-60): no citation list, claims carry none
EXTRACT_RE = re.compile(r"\nAnswer: (.*?)\n")


def words(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", "", s.casefold()).split()


def reply(prompt: str, model: str) -> str:
    """Extractor: one claim per sentence. Judge: supported only if every content word of the
    claim appears in the shown sentences; evidence = the first overlapping sentence."""
    if model == "extractor":
        m = EXTRACT_RE.search(prompt)
        assert m is not None
        claims = [
            {"text": s.strip() + ".", "addresses_question": True}
            for s in m.group(1).split(".")
            if s.strip()
        ]
        return json.dumps({"claims": claims})
    claim = prompt.split("Claim: ", 1)[1].split("\n", 1)[0]
    shown = re.findall(r"^\[(\d+)\] (.+)$", prompt.split("Cited source sentences:", 1)[1], re.M)
    seen = {w for _, s in shown for w in words(s)}
    ok = all(w in seen for w in words(claim) if len(w) > 3)
    first = [int(n) for n, s in shown if {w for w in words(claim) if len(w) > 3} & set(words(s))]
    return json.dumps(
        {
            "verdict": "supported" if ok else "unsupported",
            "evidence": first[:1] if ok else [],
            "quote": None,
            "rationale": "scripted",
        }
    )


def fake_adapter():
    from evalkit.adapters import (
        BatchRequest,
        BatchResult,
        CompletionRequest,
        ModelAdapter,
        RawCompletion,
    )

    class Fake(ModelAdapter):
        def __init__(self) -> None:
            self.requests: list[CompletionRequest] = []

        async def complete(self, req: CompletionRequest) -> RawCompletion:
            await asyncio.sleep(0)
            self.requests.append(req)
            return RawCompletion(
                model=req.model,
                model_snapshot=req.model_id + "-snap",
                params=dict(req.params),
                raw_text=reply(req.prompt, req.model),
                tokens_in=600,
                tokens_out=60,
                latency_ms=10,
                cost_usd=0.0,
            )

        async def submit_batch(self, reqs: list[BatchRequest]) -> str:
            raise AssertionError("support judging is live only")

        async def collect_batch(
            self, batch_id: str, reqs: Mapping[str, CompletionRequest]
        ) -> list[BatchResult] | None:
            raise AssertionError("support judging is live only")

    return Fake()


def judged_items(evalkit):
    from evalkit.scorers.faithfulness import FaithfulnessItem

    evidence = (
        "Pricing starts at ten dollars per user each month.",
        "A free plan covers teams of up to fifteen people.",
        "Support is available by email on weekdays only.",
    )
    return [
        FaithfulnessItem(
            id="1_v-001_claude-x_1",
            question="Which tool is cheapest?",
            explanation="A free plan covers teams of up to fifteen people.",
            evidence=evidence,
        ),
        FaithfulnessItem(
            id="1_v-001_claude-x_2",
            question="Which tool is cheapest?",
            explanation="Pricing starts at ten dollars. Phone support runs around the clock.",
            evidence=evidence,
        ),
    ]


def test_judge_maps_results_to_one_verdict_per_citation_and_judge(tmp_path, evalkit):
    fake = fake_adapter()
    items = judged_items(evalkit)
    out = asyncio.run(
        J.judge(
            items,
            store_dir=tmp_path / "store",
            adapters={"anthropic": fake, "openai": fake},
        )
    )
    assert [(v.citation_ref, v.judge, v.verdict) for v in out] == [
        ("1:v-001:claude-x:1", "claude-opus-5-5", "supported"),
        ("1:v-001:claude-x:1", "gpt-6.1-sol", "supported"),
        ("1:v-001:claude-x:2", "claude-opus-5-5", "unsupported"),  # one claim of two fails
        ("1:v-001:claude-x:2", "gpt-6.1-sol", "unsupported"),
    ]
    assert out[0].quote == "A free plan covers teams of up to fifteen people."
    assert out[2].quote is None
    judged = {r.model_id for r in fake.requests if r.model == "judge"}
    assert judged == set(J.DEFAULT_JUDGES)
    assert {r.model_id for r in fake.requests if r.model == "extractor"} == {J.DEFAULT_EXTRACTOR}
    assert any((tmp_path / "store").rglob("*.json"))  # EvalKit's store went where we said
    calls = len(fake.requests)
    again = asyncio.run(
        J.judge(items, store_dir=tmp_path / "store", adapters={"anthropic": fake, "openai": fake})
    )
    assert again == out and len(fake.requests) == calls  # cached: a rerun is free


def test_the_store_must_be_outside_the_repo(evalkit):
    root = Path(J.__file__).resolve().parents[3]
    with pytest.raises(ValueError, match="outside the repository"):
        asyncio.run(J.judge([], store_dir=root / "tmp-store", adapters={}))


def test_default_store_is_inside_the_body_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CITEWATCH_BODY_CACHE", str(tmp_path / "bodies"))
    assert J.default_store_dir() == tmp_path / "bodies" / J.STORE_DIRNAME


def _result(evalkit, rid, claims, **kw):
    from evalkit.scorers.faithfulness import FaithfulnessResult, JudgedClaim

    js = J.DEFAULT_JUDGES
    return FaithfulnessResult(
        id=rid,
        score=dict.fromkeys(js, 0.0),
        fully_faithful=dict.fromkeys(js, False),
        n_claims=len(claims),
        claims=tuple(
            JudgedClaim(text="c", cited=(1, 2, 3), verdicts=v, evidence=e) for v, e in claims
        ),
        extraction_error=kw.get("extraction_error"),
        judge_errors=kw.get("judge_errors", dict.fromkeys(js, 0)),
        pending=dict.fromkeys(js, 0),
    )


def test_verdict_rule_every_claim_supported_and_one_sentence_quote(evalkit):
    a, b = J.DEFAULT_JUDGES
    items = [
        i.model_copy(update={"evidence": ("First fact here. Second fact follows it.", "Other.")})
        for i in judged_items(evalkit)
    ]
    results = [
        _result(
            evalkit,
            items[0].id,
            [
                ({a: "supported", b: "supported"}, {a: (), b: (2,)}),
                ({a: "supported", b: "unsupported"}, {a: (1,), b: ()}),
            ],
        ),
        _result(evalkit, items[1].id, []),  # nothing extracted: unsupported
    ]
    out = J.verdicts_for(items, results, (a, b))
    assert [(v.judge, v.verdict, v.quote) for v in out] == [
        (a, "supported", "First fact here."),  # cut to one sentence
        (b, "unsupported", None),
        (a, "unsupported", None),
        (b, "unsupported", None),
    ]


def test_incomplete_judging_raises_unless_not_strict(evalkit):
    a, b = J.DEFAULT_JUDGES
    items = judged_items(evalkit)[:1]
    res = [
        _result(
            evalkit,
            items[0].id,
            [({a: "supported"}, {a: (1,)})],
            judge_errors={a: 0, b: 1},
        )
    ]
    with pytest.raises(J.SupportJudgingIncomplete, match="1:v-001:claude-x:1"):
        J.verdicts_for(items, res, (a, b))
    out = J.verdicts_for(items, res, (a, b), strict=False)
    assert [v.verdict for v in out] == ["supported", "unsupported"]


# ---- cost estimate -----------------------------------------------------------------------------


def test_planning_estimate_scales_with_items_and_judges(evalkit):
    est = J.planning_estimate(50, evidence_tokens=2000)
    assert [(x.node, x.model, x.calls) for x in est.lines] == [
        ("extract", J.DEFAULT_EXTRACTOR, 50),
        ("judge", "claude-opus-5-5", 100),
        ("judge", "gpt-6.1-sol", 100),
    ]
    assert 0.5 < est.total_usd < 3.0
    assert J.planning_estimate(100).total_usd == pytest.approx(2 * est.total_usd)
    one = J.planning_estimate(50, judges=("gpt-6.1-sol",))
    assert one.total_usd < est.total_usd


def test_item_estimate_counts_the_evidence(evalkit):
    items = judged_items(evalkit)
    small = J.estimate_cost(items)
    big = J.estimate_cost([i.model_copy(update={"evidence": i.evidence * 50}) for i in items])
    assert 0 < small.total_usd < big.total_usd


# ---- contract: the imported EvalKit symbols (SUP-03) -------------------------------------------


@pytest.mark.contract
def test_imported_evalkit_symbols_have_the_expected_signatures(evalkit):
    from evalkit.adapters import ModelAdapter, get_adapter
    from evalkit.cost import (
        CostEstimate,
        CostLine,
        TokenAssumptions,
        call_cost,
        estimate_tokens,
        load_prices,
    )
    from evalkit.pipeline.extract import EXTRACTOR_PROMPT
    from evalkit.pipeline.generate import adapter_key, provider_for
    from evalkit.pipeline.judge import JUDGE_RUBRIC, SENTENCE_FORMAT
    from evalkit.runtime import Executor, Store
    from evalkit.schemas import RunConfig
    from evalkit.scorers.faithfulness import (
        FaithfulnessItem,
        FaithfulnessResult,
        JudgedClaim,
        faithfulness,
    )

    assert inspect.iscoroutinefunction(faithfulness)
    params = inspect.signature(faithfulness).parameters
    for name in ("executor", "config", "adapters", "prices", "judges", "live", "run_id"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
    assert set(FaithfulnessItem.model_fields) == {"id", "question", "explanation", "evidence"}
    assert {"id", "n_claims", "claims", "extraction_error", "judge_errors", "pending"} <= set(
        FaithfulnessResult.model_fields
    )
    assert {"text", "verdicts", "evidence"} <= set(JudgedClaim.model_fields)
    assert {"store", "concurrency", "max_cost_usd"} <= set(inspect.signature(Executor).parameters)
    assert list(inspect.signature(Store).parameters) == ["root"]
    assert {"models", "judges", "extractor", "judge_effort", "max_cost_usd"} <= set(
        RunConfig.model_fields
    )
    assert {"t_ext_out", "t_ext_reason", "t_j_out", "t_j_reason"} <= set(
        TokenAssumptions.model_fields
    )
    assert {"tokens_in", "tokens_out", "tokens_reasoning"} <= set(
        inspect.signature(call_cost).parameters
    )
    assert {"node", "model", "calls", "usd"} <= set(CostLine.model_fields)
    assert "total_usd" in CostEstimate.model_fields
    assert callable(estimate_tokens) and callable(get_adapter) and callable(ModelAdapter)
    assert adapter_key(provider_for("claude-opus-5-5"), "claude-opus-5-5") == "anthropic"
    assert adapter_key(provider_for("gpt-6.1-sol"), "gpt-6.1-sol") == "openai"
    assert "{claim}" in JUDGE_RUBRIC and "{sentences}" in JUDGE_RUBRIC
    assert SENTENCE_FORMAT.format(n=1, text="x") == "[1] x"
    assert "{answer}" in EXTRACTOR_PROMPT
    prices = load_prices()
    assert {J.DEFAULT_EXTRACTOR, *J.DEFAULT_JUDGES} <= set(prices)
