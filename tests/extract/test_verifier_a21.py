"""A2.1 verifier pass 1 findings, each pinned."""

import gzip

import pytest

from citewatch.extract import (
    extract_claude,
    extract_envelope,
    extract_openai,
    publisher_of,
    run_extract,
)
from citewatch.runners.schedule import ask_key
from citewatch.store import RawStore

from ..runners.helpers import CFG, Q1, Q2
from .test_extractors import stored_env


def _gpt(text, annotations):
    return [
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": text, "annotations": annotations}],
                }
            ]
        }
    ]


def _ann(url, s, e):
    return {"type": "url_citation", "url": url, "start_index": s, "end_index": e, "title": "T"}


def test_adjacent_and_duplicate_markers_share_the_claim():
    """M1: never the link or the URL as the span."""
    claim = "Rest helps sore legs. "
    m1, m2 = "([a.com](https://a.com/x))", "([b.com](https://b.com/y))"
    text = claim + m1 + m2
    s1 = len(claim)
    s2 = s1 + len(m1)
    ex = extract_openai(
        _gpt(
            text,
            [
                _ann("https://a.com/x", s1, s2),
                _ann("https://b.com/y", s2, len(text)),
                _ann("https://c.com/z", s2, len(text)),
            ],
        )
    )
    assert [c.answer_span for c in ex.citations] == ["Rest helps sore legs."] * 3


def test_a_missing_annotation_index_keeps_the_answer():
    ex = extract_openai(
        _gpt(
            "Claim. ([a](https://a.com/))",
            [
                {
                    "type": "url_citation",
                    "url": "https://a.com/",
                    "start_index": None,
                    "end_index": None,
                }
            ],
        )
    )
    assert len(ex.citations) == 1 and ex.citations[0].answer_span


def test_output_text_parts_never_run_together():
    gpt = [
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "First part ends", "annotations": []},
                        {"type": "output_text", "text": "second begins", "annotations": []},
                    ],
                }
            ]
        }
    ]
    assert extract_openai(gpt).answer_text == "First part ends\n\nsecond begins"


def test_only_current_answers_are_extracted_and_odd_files_never_stop_the_stage(tmp_path):
    """M2, M3: an edited question's old answer stays in the store but is not pooled."""
    store = RawStore(tmp_path)
    store.put("ask", ask_key(CFG, 1, Q1, "claude-sonnet-5-5"), stored_env("claude-sonnet-5-5", Q1))
    old_q = Q1.model_copy(update={"text": "An older wording?"})
    store.put(
        "ask", ask_key(CFG, 1, old_q, "claude-sonnet-5-5"), stored_env("claude-sonnet-5-5", Q1)
    )
    bad = tmp_path / "data" / "raw" / "ask" / "ff" / ("ff" * 32 + ".json.gz")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not gzip")
    res = run_extract(tmp_path, CFG, [Q1, Q2])
    assert len(res.answers) == 1 and res.stale == 1 and len(res.problems) == 1
    assert [c.ordinal for c in res.citations] == list(range(1, len(res.citations) + 1))


def test_row_fields_come_from_the_response():
    """M4: url_raw, title, group, cited, dedup, refusal and searches are all checked."""
    rec, cites, cons, _ = extract_envelope("a" * 64, stored_env("gpt-6.1-sol", Q1), CFG)
    assert any("utm_source=openai" in c.url_raw for c in cites)  # url_raw keeps the API spelling
    assert all("utm_" not in c.url for c in cites)
    assert all(c.title for c in cites)
    assert rec.searches == stored_env("gpt-6.1-sol", Q1)["usage"]["searches"] > 0
    assert len({s.url for s in cons}) == len(cons)  # one row per URL
    assert {s.url for s in cons if s.cited} == {c.url for c in cites} & {s.url for s in cons}
    assert any(not s.cited for s in cons)
    trust = [c for c in cites if c.host.endswith(".nhs.uk") and c.host != "www.nhs.uk"]
    assert all(c.publisher_group == "nhs.uk" for c in trust)


def test_only_typed_citation_entries_count():
    claude = [
        {
            "content": [
                {
                    "type": "text",
                    "text": "Claim.",
                    "citations": [
                        {"type": "char_location", "url": "https://doc.example/", "cited_text": "x"},
                        {
                            "type": "web_search_result_location",
                            "url": "https://ok.example/",
                            "cited_text": "y",
                        },
                    ],
                }
            ]
        }
    ]
    assert [c.url_raw for c in extract_claude(claude).citations] == ["https://ok.example/"]
    gpt = _gpt(
        "Claim. [f]",
        [
            {
                "type": "file_citation",
                "url": "https://doc.example/",
                "start_index": 7,
                "end_index": 10,
            },
            _ann("https://ok.example/", 7, 10),
        ],
    )
    assert [c.url_raw for c in extract_openai(gpt).citations] == ["https://ok.example/"]


def test_an_opened_page_alone_is_consulted():
    gpt = [
        {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {"type": "open_page", "url": "https://opened.example/p"},
                }
            ]
        }
    ]
    assert list(extract_openai(gpt).consulted) == ["https://opened.example/p"]


def test_out_of_order_annotations_are_read_in_text_order():
    text = "One. ([a](https://a.com/)) Two. ([b](https://b.com/))"
    a = text.index("([a]")
    b = text.index("([b]")
    ex = extract_openai(
        _gpt(
            text,
            [
                _ann("https://b.com/", b, len(text)),
                _ann("https://a.com/", a, a + len("([a](https://a.com/))")),
            ],
        )
    )
    assert [(c.url_raw, c.answer_span) for c in ex.citations] == [
        ("https://a.com/", "One."),
        ("https://b.com/", "Two."),
    ]


def test_a_refusal_is_recorded():
    env = stored_env("claude-sonnet-5-5", Q1)
    env["responses"] = [dict(env["responses"][-1], stop_reason="refusal")]
    rec, *_ = extract_envelope("a" * 64, env, CFG)
    assert rec.refusal is True


@pytest.mark.parametrize(("n", "over"), [(150, False), (151, True)])
def test_the_word_limit_boundary(n, over):
    env = stored_env("gpt-6.1-sol", Q1)
    env["responses"] = _gpt(" ".join(["word"] * n) + ".", [])
    rec, *_ = extract_envelope("a" * 64, env, CFG)
    assert rec.word_count == n and rec.over_length is over


def test_schools_keep_their_own_publisher():
    assert publisher_of("https://www.stmarys.hants.sch.uk/") == ("stmarys.hants.sch.uk", "sch.uk")
    assert publisher_of("https://stjohns.hants.sch.uk/") == ("stjohns.hants.sch.uk", "sch.uk")


def test_gzip_is_what_the_store_writes():
    assert gzip.decompress(gzip.compress(b"{}")) == b"{}"


# --- pass 2 -------------------------------------------------------------------------------


def test_every_row_field_comes_from_its_source(tmp_path):
    """v2 M-B: publisher, group, spans, titles, usage and order pinned row by row."""
    import json

    from citewatch.extract import canonical_url, extract_openai
    from citewatch.extract.extractors import extract_claude as ec

    store = RawStore(tmp_path)
    units = [("gpt-6.1-sol", Q2), ("claude-sonnet-5-5", Q1), ("gpt-6.1-sol", Q1)]
    envs = {}
    for model, q in units:
        env = stored_env(model, q)
        envs[(model, q.id)] = env
        store.put("ask", ask_key(CFG, 1, q, model), env)
    res = run_extract(tmp_path, CFG, [Q1, Q2])
    assert any(c.publisher_group == "nhs.uk" for c in res.citations)  # leicspart.nhs.uk
    for c in res.citations:
        assert (c.publisher, c.publisher_group) == publisher_of(c.url)
    for a in res.answers:
        env = envs[(a.model, a.question_id)]
        assert a.model_snapshot == env["responses"][-1]["model"]
        assert (a.tokens_in, a.tokens_out) == (
            env["usage"]["tokens_in"],
            env["usage"]["tokens_out"],
        )
        assert a.cost_usd == env["cost_usd"] and a.searches == env["usage"]["searches"]
    for (model, qid), env in envs.items():
        ex = (
            ec(env["responses"]) if model.startswith("claude") else extract_openai(env["responses"])
        )
        rows = [c for c in res.citations if (c.model, c.question_id) == (model, qid)]
        assert [(c.url_raw, c.title, c.quoted_span, c.answer_span) for c in rows] == [
            (r.url_raw, r.title, r.quoted_span, r.answer_span) for r in ex.citations
        ]
        cons = [s for s in res.consulted if (s.model, s.question_id) == (model, qid)]
        assert {s.url for s in cons} == {canonical_url(u) for u in ex.consulted}
        assert {s.url: s.page_age for s in cons} == {
            canonical_url(u): age for u, age in ex.consulted.items()
        }
    keys = [(c.run, c.question_id, c.model, c.ordinal) for c in res.citations]
    assert keys == sorted(keys)
    lines = (tmp_path / "data" / "answers.jsonl").read_text(encoding="utf-8").splitlines()
    assert [(r["question_id"], r["model"]) for r in map(json.loads, lines)] == sorted(
        (q.id, m) for m, q in units
    )


def test_consulted_variants_of_one_page_are_one_row():
    env = stored_env("gpt-6.1-sol", Q1)
    env["responses"] = [
        {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "type": "search",
                        "sources": [
                            {"type": "url", "url": "https://a.example/p?utm_source=openai"},
                            {"type": "url", "url": "https://A.example/p"},
                            {"type": "url", "url": "https://b.example/q"},
                            {"type": "url", "url": "https://c.example/r"},
                            {"type": "url", "url": "https://d.example/s"},
                        ],
                    },
                }
            ]
        }
    ]
    _, _, cons, _ = extract_envelope("a" * 64, env, CFG)
    assert sorted(s.url for s in cons) == [
        "https://a.example/p",
        "https://b.example/q",
        "https://c.example/r",
        "https://d.example/s",
    ]


def test_a_gpt_refusal_is_recorded():
    env = stored_env("gpt-6.1-sol", Q1)
    env["responses"] = [
        dict(
            env["responses"][-1],
            output=[
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "refusal", "refusal": "I can't help with that."}],
                }
            ],
        )
    ]
    rec, *_ = extract_envelope("a" * 64, env, CFG)
    assert rec.refusal is True


def test_old_settings_and_dropped_models_are_stale(tmp_path):
    store = RawStore(tmp_path)
    store.put("ask", ask_key(CFG, 1, Q1, "claude-sonnet-5-5"), stored_env("claude-sonnet-5-5", Q1))
    old = CFG.model_copy(update={"word_limit": 120})
    store.put("ask", ask_key(old, 1, Q1, "claude-sonnet-5-5"), stored_env("claude-sonnet-5-5", Q1))
    one_model = CFG.model_copy(update={"models": ("gpt-6.1-sol",)})
    store.put("ask", ask_key(CFG, 1, Q1, "gpt-6.1-sol"), stored_env("gpt-6.1-sol", Q1))
    res = run_extract(tmp_path, CFG, [Q1])
    assert len(res.answers) == 2 and res.stale == 1
    res2 = run_extract(tmp_path, one_model, [Q1])
    assert [a.model for a in res2.answers] == [] or all(
        a.model == "gpt-6.1-sol" for a in res2.answers
    )
    assert res2.stale >= 2


def test_punctuation_is_never_a_span_or_a_word():
    t1 = "Claim one ([x](https://a.example/)), ([y](https://b.example/))"
    a1, b1 = t1.index("([x]"), t1.index("([y]")
    ex = extract_openai(
        _gpt(t1, [_ann("https://a.example/", a1, a1 + 25), _ann("https://b.example/", b1, len(t1))])
    )
    assert [c.answer_span for c in ex.citations] == ["Claim one"] * 2
    t2 = "Claim ([x](https://a.example/)). Claim two ([y](https://b.example/))."
    a2, b2 = t2.index("([x]"), t2.index("([y]")
    ex2 = extract_openai(
        _gpt(t2, [_ann("https://a.example/", a2, a2 + 25), _ann("https://b.example/", b2, b2 + 25)])
    )
    assert ex2.citations[1].answer_span == "Claim two"
    assert ex2.answer_text == "Claim. Claim two."


# --- pass 3: expected values written out, never taken from the extractor -----------------


def test_literal_values_for_a_gpt_answer():
    """v3 M-1: consulted publisher, cited flag across utm spellings, paragraph-cut spans."""
    text = "Uncited intro para.\n\nRest helps. ([nhs.uk](https://www.nhs.uk/a?utm_source=openai))"
    s = text.index("([nhs")
    env = stored_env("gpt-6.1-sol", Q1)
    env["responses"] = [
        {
            "model": "gpt-6.1-sol",
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "type": "search",
                        "sources": [
                            {"type": "url", "url": "https://www.nhs.uk/a?utm_source=openai"},
                            {"type": "url", "url": "https://www.gov.uk/b"},
                        ],
                    },
                },
                {
                    "type": "web_search_call",
                    "action": {"type": "find", "url": "https://found.example/f", "pattern": "x"},
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": text,
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://www.nhs.uk/a?utm_source=openai",
                                    "title": "NHS A",
                                    "start_index": s,
                                    "end_index": len(text),
                                }
                            ],
                        }
                    ],
                },
            ],
        }
    ]
    rec, cites, cons, _ = extract_envelope("a" * 64, env, CFG)
    assert [(c.url, c.publisher, c.publisher_group, c.title, c.answer_span) for c in cites] == [
        ("https://www.nhs.uk/a", "nhs.uk", None, "NHS A", "Rest helps.")
    ]
    assert sorted((s.url, s.publisher, s.cited) for s in cons) == [
        ("https://found.example/f", "found.example", False),
        ("https://www.gov.uk/b", "gov.uk", False),
        ("https://www.nhs.uk/a", "nhs.uk", True),
    ]
    assert rec.answer_text == "Uncited intro para.\n\nRest helps." and rec.word_count == 5


def test_literal_values_for_a_claude_citation():
    ex = extract_claude(stored_env("claude-sonnet-5-5", Q1)["responses"])
    first = ex.citations[0]
    assert first.title == "NHS prescription charges frozen for second year in a row - The ..."
    assert first.url_raw == (
        "https://pharmaceutical-journal.com/article/news/nhs-prescription-charges-frozen-for-second-year-in-a-row"
    )


def test_punctuation_spacing_is_only_closed_where_a_marker_was_cut():
    text = "Sites ending in .nhs.uk or .gov.uk are official. Wait ... Install .NET first ([a](https://a.example/))."
    s = text.index("([a]")
    ex = extract_openai(
        _gpt(text, [_ann("https://a.example/", s, s + len("([a](https://a.example/))"))])
    )
    assert (
        ex.answer_text
        == "Sites ending in .nhs.uk or .gov.uk are official. Wait ... Install .NET first."
    )
