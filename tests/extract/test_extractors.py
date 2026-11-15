"""CIT-01..03, CIT-06 on the recorded provider responses."""

import copy
import json

import pytest

from citewatch.extract import (
    extract_claude,
    extract_envelope,
    extract_openai,
    run_extract,
    unique_cited_urls,
)
from citewatch.runners.base import instruction, prompt_hash
from citewatch.runners.schedule import answer_config_hash, ask_key
from citewatch.store import RawStore

from ..runners.helpers import CFG, Q1, Q2, envelope


def raw(model, qid):
    return copy.deepcopy(envelope(model, qid)["answer"]["raw"])


def stored_env(model, q, responses=None, run=1):
    rec = envelope(model, q.id)
    return {
        "schema_version": "1.0",
        "run": run,
        "question_id": q.id,
        "model": model,
        "answered_at": rec["answered_at"],
        "latency_ms": 1,
        "cost_usd": rec["cost_usd"],
        "usage": {
            "tokens_in": rec["answer"]["tokens_in"],
            "tokens_out": rec["answer"]["tokens_out"],
            "cached_in": 0,
            "searches": rec["answer"]["searches"],
        },
        "prompt_hash": prompt_hash(instruction(CFG)),
        "answer_config_hash": answer_config_hash(CFG),
        "request": rec["answer"]["request"],
        "responses": responses if responses is not None else raw(model, q.id),
        "error": None,
    }


def test_claude_citations_and_consulted_sources():
    responses = raw("claude-sonnet-5-5", "v-901")
    ex = extract_claude(responses)
    blocks = [b for r in responses for b in r["content"] if b["type"] == "text"]
    api = [(c, b) for b in blocks for c in b.get("citations") or []]
    assert len(ex.citations) == len(api) == 5
    for got, (c, b) in zip(ex.citations, api, strict=True):
        assert got.url_raw == c["url"] and got.quoted_span == c["cited_text"]
        assert got.answer_span == b["text"].strip()
    assert "198 days ago" in ex.consulted.values()
    assert ex.answer_text == "".join(b["text"] for b in blocks).strip()


def test_openai_citations_take_the_claim_before_the_marker():
    responses = raw("gpt-6.1-sol", "v-902")
    ex = extract_openai(responses)
    assert len(ex.citations) == 5
    assert ex.citations[0].answer_span.startswith(
        "It’s most likely **delayed-onset muscle soreness"
    )
    assert ex.citations[0].answer_span.endswith("particularly likely to trigger it.")
    assert ex.citations[1].answer_span.startswith("DOMS typically appears")
    assert ex.citations[4].answer_span.startswith("Seek urgent medical help")
    assert "](" not in ex.answer_text and "utm_source" not in ex.answer_text
    assert any("clevelandclinic" in u for u in ex.consulted)  # the opened page counts as consulted
    assert all(c.quoted_span is None for c in ex.citations)


def test_typed_links_and_consulted_only_urls_are_never_citations():
    claude = [
        {
            "content": [
                {
                    "type": "text",
                    "text": "See https://typed.example/x and [this](https://md.example/y).",
                    "citations": None,
                },
                {
                    "type": "web_search_tool_result",
                    "content": [
                        {
                            "type": "web_search_result",
                            "url": "https://seen.example/z",
                            "page_age": None,
                        }
                    ],
                },
            ]
        }
    ]
    ex = extract_claude(claude)
    assert ex.citations == [] and list(ex.consulted) == ["https://seen.example/z"]
    gpt = [
        {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "type": "search",
                        "sources": [{"type": "url", "url": "https://seen.example/z"}],
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Typed ([x](https://typed.example/)) link.",
                            "annotations": [],
                        }
                    ],
                },
            ]
        }
    ]
    ex2 = extract_openai(gpt)
    assert ex2.citations == [] and list(ex2.consulted) == ["https://seen.example/z"]


def test_bad_annotation_indices_never_crash_or_overlap():
    gpt = [
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Claim one. Claim two.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://a.example/",
                                    "start_index": 50,
                                    "end_index": 60,
                                },
                                {
                                    "type": "url_citation",
                                    "url": "https://b.example/",
                                    "start_index": 5,
                                    "end_index": 2,
                                },
                            ],
                        }
                    ],
                }
            ]
        }
    ]
    ex = extract_openai(gpt)
    assert len(ex.citations) == 2 and all(c.answer_span for c in ex.citations)


@pytest.mark.parametrize(("model", "q"), [("claude-sonnet-5-5", Q1), ("gpt-6.1-sol", Q2)])
def test_envelopes_become_valid_records(model, q):
    rec, cites, cons, skipped = extract_envelope("a" * 64, stored_env(model, q), CFG)
    assert rec.word_count > 0 and rec.over_length == (rec.word_count > CFG.word_limit)
    assert [c.ordinal for c in cites] == list(range(1, len(cites) + 1))
    assert all("utm_" not in c.url for c in cites) and skipped == []
    cited = {c.url for c in cites}
    assert {s.url for s in cons if s.cited} <= cited
    assert all(c.publisher in c.host for c in cites)


def test_unique_urls_per_answer_keep_the_raw_count():
    _rec, cites, _, _ = extract_envelope("a" * 64, stored_env("claude-sonnet-5-5", Q1), CFG)
    u = unique_cited_urls(cites)[(1, Q1.id, "claude-sonnet-5-5")]
    assert len(cites) == 5 and len(u) == 4  # pharmaceutical-journal cited twice


def test_the_stage_rebuilds_identical_files_and_reports_odd_envelopes(tmp_path):
    store = RawStore(tmp_path)
    for model, q in (("claude-sonnet-5-5", Q1), ("gpt-6.1-sol", Q1), ("gpt-6.1-sol", Q2)):
        store.put("ask", ask_key(CFG, 1, q, model), stored_env(model, q))
    bad = stored_env("claude-sonnet-5-5", Q2)
    del bad["answered_at"]
    store.put("ask", ask_key(CFG, 1, Q2, "claude-sonnet-5-5"), bad)
    r1 = run_extract(tmp_path, CFG, [Q1, Q2])
    first = {
        n: (tmp_path / "data" / n).read_bytes()
        for n in ("answers.jsonl", "citations.jsonl", "consulted.jsonl")
    }
    r2 = run_extract(tmp_path, CFG, [Q1, Q2])
    assert first == {n: (tmp_path / "data" / n).read_bytes() for n in first}
    assert len(r1.answers) == 3 and len(r1.problems) == 1 and r2.problems == r1.problems
    rows = [json.loads(x) for x in first["citations.jsonl"].decode().splitlines()]
    assert rows and all(
        set(r) >= {"url", "url_raw", "publisher", "answer_span", "ordinal"} for r in rows
    )


def test_the_cli_extracts_with_no_keys(tmp_path, monkeypatch, capsys):
    from citewatch import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["init", "s", "--contact", "https://github.com/me/study"]) == 0
    from citewatch.schemas import load_questions, load_study_config

    cfg = load_study_config(tmp_path / "s" / "study.yaml")
    q = load_questions(tmp_path / "s" / cfg.questions_path, cfg)[0]
    env = stored_env("gpt-6.1-sol", Q2)
    env["question_id"] = q.id
    env["answer_config_hash"] = answer_config_hash(cfg)
    store = RawStore(tmp_path / "s")
    store.put("ask", ask_key(cfg, 1, q, "gpt-6.1-sol"), env)
    stale = dict(env, question_id="q-999")
    store.put("ask", "f" * 64, stale)  # an answer to a question no longer in the study
    capsys.readouterr()
    assert cli.main(["extract", "--study", str(tmp_path / "s"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["answers"] == 1 and out["citations"] == 5 and out["unique_cited_urls"] == 3
    assert out["stale"] == 1
