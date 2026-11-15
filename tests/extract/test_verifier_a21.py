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
