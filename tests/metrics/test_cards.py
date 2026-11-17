"""CRD-01..03, IMP-01..02: domain cards, lookup and the improvement report (node D5.1).

The tiny study's cards are worked out by hand from tests/metrics/conftest.py; the flagship
study's cards are checked against its summary.json and page_meta.jsonl.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from citewatch import cards as cards_module
from citewatch.cards import NotCited, build_cards, cited_instead, lookup, normalise, read_cards
from citewatch.extract import urls as urls_module
from citewatch.metrics import build_summary
from citewatch.metrics.data import load
from citewatch.schemas import StudySummary, load_questions, load_study_config

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "studies" / "uk-health"
A, B = "claude-sonnet-5-5", "gpt-6.1-sol"
MEDICAL_CLAIMS = re.compile(
    r"\b(accura|inaccura|correct|incorrect|wrong|misinform|unsafe|safe advice|medically|"
    r"clinical(ly)? (valid|sound)|harmful)",
    re.I,
)


def _tiny_cards(tiny: Path):
    cfg = load_study_config(tiny / "study.yaml")
    qs = load_questions(tiny / "questions.jsonl", cfg)
    summary = build_summary(tiny, cfg, qs, resamples=200)
    data = load(tiny, cfg, qs, list(summary.runs))
    return build_cards(tiny, data, summary, cfg.stale_days), summary, data


def test_tiny_cards_count_citations_answers_and_questions(tiny: Path):
    cards, _, _ = _tiny_cards(tiny)
    assert [(c.publisher, c.citations, c.answers_citing) for c in cards] == [
        ("nhs.uk", 7, 7),
        ("bbc.co.uk", 4, 4),
        ("x.com", 3, 2),
    ]
    assert cards[0].questions_citing == ("t-001", "t-002", "t-003")


def test_every_card_share_is_the_summary_row(tiny: Path):
    cards, summary, _ = _tiny_cards(tiny)
    rows = {
        (r.publisher, r.model, r.intent, r.run): r.share
        for r in summary.share
        if r.kind == "presence"
    }
    for card in cards:
        for key, share in card.share_by_model.items():
            model, run = key.split("/")
            assert share == rows[(card.publisher, model, None, int(run.removeprefix("run-")))]
        for key, share in card.share_by_intent.items():
            intent, model, run = key.split("/")
            assert share == rows[(card.publisher, model, intent, int(run.removeprefix("run-")))]
    assert cards[0].share_by_model[f"{A}/run-1"].k == 2


def test_cited_instead_ranks_who_answered_without_the_publisher(tiny: Path):
    """§9 by hand: nhs.uk is missing from t-002 (bbc, x) and t-003 on GPT (bbc twice)."""
    cards, _, data = _tiny_cards(tiny)
    by = {c.publisher: c for c in cards}
    assert by["nhs.uk"].cited_instead == ("bbc.co.uk", "x.com")
    assert by["x.com"].cited_instead == ("bbc.co.uk",)
    assert cited_instead(data, "nobody.org") == ()
    assert all(c.publisher not in c.cited_instead for c in cards)


def test_improvement_rows_by_hand(tiny: Path):
    """Stale reads §6.3: only pages cited on time-sensitive questions (t-001, t-003). nhs.uk/b
    (2024-01-01, on t-003) is over 365 days before the 2026-11-20 answers; nhs.uk/a (323 days)
    is not; nhs.uk/c is cited only on t-002, which is not time-sensitive. x.com's two pages
    loaded with no date; bbc's page is newer than the answer."""
    cards, _, _ = _tiny_cards(tiny)
    by = {c.publisher: {i.code: i for i in c.improvement} for c in cards}
    stale = by["nhs.uk"]["stale"]
    assert (stale.count, stale.of) == (1, 2)
    assert stale.examples == ("https://nhs.uk/b",)
    assert "page_meta.jsonl" in stale.sources and "answers.jsonl" in stale.sources
    undated = by["x.com"]["undated"]
    assert (undated.count, undated.of) == (2, 2)
    assert undated.finding.startswith("2 of 2 cited pages that loaded have no date")
    assert by["bbc.co.uk"] == {}
    assert "intent_absent" not in by["nhs.uk"]  # cited on both intents


def _set_outcomes(tiny: Path, changes: dict[str, dict]) -> None:
    meta = tiny / "data" / "page_meta.jsonl"
    rows = [json.loads(x) for x in meta.read_text("utf-8").splitlines()]
    for r in rows:
        r.update(changes.get(r["url"], {}))
    meta.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")


def test_page_outcomes_and_hidden_dates_become_rows(tiny: Path):
    _set_outcomes(
        tiny,
        {
            "https://nhs.uk/a": {"effective_source": "page_age"},
            "https://x.com/b": {"outcome": "robots_disallowed"},
            "https://bbc.co.uk/a": {"outcome": "fetch_error", "effective_date": None},
            "https://nhs.uk/c": {"outcome": "not_html", "effective_date": None},
        },
    )
    cards, _, _ = _tiny_cards(tiny)
    by = {c.publisher: {i.code: i for i in c.improvement} for c in cards}
    assert (by["nhs.uk"]["hidden_date"].count, by["nhs.uk"]["hidden_date"].of) == (1, 2)
    assert (by["nhs.uk"]["not_html"].count, by["nhs.uk"]["not_html"].of) == (1, 3)
    assert (by["x.com"]["robots_blocked"].count, by["x.com"]["robots_blocked"].of) == (1, 2)
    assert by["x.com"]["robots_blocked"].finding.startswith("1 of 2 cited pages is disallowed")
    assert (by["x.com"]["undated"].count, by["x.com"]["undated"].of) == (1, 1)
    assert (by["bbc.co.uk"]["fetch_error"].count, by["bbc.co.uk"]["fetch_error"].of) == (1, 1)


def test_an_unreadable_robots_txt_is_never_called_a_disallow(tiny: Path):
    """D-5.1 pass 1 H1: a 403 on robots.txt is reported as such, not as the site's rule."""
    _set_outcomes(
        tiny,
        {
            "https://x.com/a": {"outcome": "robots_disallowed"},
            "https://x.com/b": {"outcome": "blocked"},
        },
    )
    log = [
        {"url": "https://x.com/robots.txt", "host": "x.com", "status": 403, "outcome": "blocked"},
        {
            "url": "https://bbc.co.uk/robots.txt",
            "host": "bbc.co.uk",
            "status": 200,
            "outcome": "ok",
        },
    ]
    (tiny / "data" / "fetch_log.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in log), "utf-8"
    )
    cards, _, _ = _tiny_cards(tiny)
    rows = {i.code: i for i in next(c for c in cards if c.publisher == "x.com").improvement}
    assert "robots_blocked" not in rows
    assert "(HTTP 403)" in rows["robots_unreadable"].finding
    assert "disallowed" not in rows["robots_unreadable"].finding
    assert (rows["blocked"].count, rows["blocked"].of) == (1, 2)


def test_unsupported_rows_never_contradict_the_owners_labels(tiny: Path):
    data = tiny / "data"
    refs = ["1:t-001:claude-sonnet-5-5:1", "1:t-003:claude-sonnet-5-5:1"]
    (data / "support_verdicts.jsonl").write_text(
        "".join(
            json.dumps({"citation_ref": r, "judge": j, "verdict": "unsupported"}) + "\n"
            for r in refs
            for j in ("opus", "sol")
        ),
        "utf-8",
    )
    (data / "support_label_key.jsonl").write_text(
        "".join(json.dumps({"id": f"s{i}", "citation_ref": r}) + "\n" for i, r in enumerate(refs)),
        "utf-8",
    )
    (data / "support_labels.jsonl").write_text(
        json.dumps({"id": "s0", "label": "supported"})
        + "\n"
        + json.dumps({"id": "s1", "label": "unsupported"})
        + "\n",
        "utf-8",
    )
    cards, _, _ = _tiny_cards(tiny)
    row = {i.code: i for i in cards[0].improvement}["unsupported"]
    assert (row.count, row.of, row.examples) == (1, 2, (refs[1],))
    assert "support_labels.jsonl" in row.sources


def test_lookup_normalises_input_through_the_extractors_publisher_of(tiny: Path):
    cards, _, _ = _tiny_cards(tiny)
    for q in ("https://www.NHS.uk/conditions/flu?x=1", "nhs.uk", "http://nhs.uk:8080/", "NHS.UK."):
        hit = lookup(q, cards, answers=15)
        assert not isinstance(hit, NotCited) and hit.publisher == "nhs.uk", q
    assert normalise("https://user@www.Example.org:443/a/b?c") == "example.org"
    assert vars(cards_module)["publisher_of"] is urls_module.publisher_of  # one function


def test_lookup_of_an_uncited_publisher_names_the_study_and_the_intents_leaders(tiny: Path):
    cards, _, _ = _tiny_cards(tiny)
    miss = lookup("https://example.org/page", cards, answers=15, intent="beta")
    assert isinstance(miss, NotCited)
    assert miss.message == "example.org was not cited in any of the 15 answers in this study."
    assert miss.top_for_intent == ("bbc.co.uk", "nhs.uk")
    with pytest.raises(ValueError, match="unknown intent"):
        lookup("nhs.uk", cards, answers=15, intent="gamma")


@pytest.mark.parametrize(
    "junk", ["", "   ", "://", "http://", "nhs .uk", "nhs", "javascript:alert(1)"]
)
def test_junk_is_never_echoed_as_a_publisher(tiny: Path, junk: str):
    cards, _, _ = _tiny_cards(tiny)
    miss = lookup(junk, cards, answers=15)
    assert isinstance(miss, NotCited) and miss.publisher is None
    assert "is not a web address" in miss.message


def test_an_idn_is_shown_in_unicode():
    assert normalise("https://xn--bcher-kva.example/x") == "bücher.example"


def test_flagship_cards_match_the_summary_and_reproduce_on_a_rerun(tmp_path: Path):
    cfg = load_study_config(STUDY / "study.yaml")
    qs = load_questions(STUDY / cfg.questions_path, cfg)
    summary = StudySummary.model_validate_json(
        (STUDY / "results" / "summary.json").read_text("utf-8")
    )
    cards = build_cards(STUDY, load(STUDY, cfg, qs, list(summary.runs)), summary, cfg.stale_days)
    committed = read_cards(STUDY / "results" / "domain_cards.json")
    assert cards == committed
    cited = {
        json.loads(x)["publisher"]
        for x in (STUDY / "data" / "citations.jsonl").read_text("utf-8").splitlines()
        if x.strip() and json.loads(x)["run"] in summary.runs
    }
    assert {c.publisher for c in cards} == cited


def test_flagship_page_counts_reproduce_from_the_study_files():
    """IMP-01: every page-based code recomputed here from page_meta, fetch_log, answers and
    questions, independently of citewatch.cards."""
    import datetime as dt
    from urllib.parse import urlsplit

    cards = read_cards(STUDY / "results" / "domain_cards.json")
    rows_of = lambda name: [  # noqa: E731
        json.loads(x) for x in (STUDY / "data" / name).read_text("utf-8").splitlines() if x.strip()
    ]
    meta = {r["url"]: r for r in rows_of("page_meta.jsonl")}
    ts = {q["id"] for q in rows_of("../questions.jsonl") if q["time_sensitive"]}
    when = {
        (a["run"], a["question_id"], a["model"]): dt.date.fromisoformat(a["answered_at"][:10])
        for a in rows_of("answers.jsonl")
    }
    robots: dict[str, list] = {}
    for r in rows_of("fetch_log.jsonl"):
        if urlsplit(r["url"]).path == "/robots.txt":
            robots.setdefault(r["host"], []).append(r.get("status"))
    hidden_src = ("sitemap", "http_header", "page_age")

    def readable(h: str) -> bool:
        twin = h.removeprefix("www.") if h.startswith("www.") else f"www.{h}"
        moved = any(s is not None and 300 <= s < 400 for s in robots.get(h, []))
        return 200 in robots.get(h, []) or (moved and 200 in robots.get(twin, []))

    urls: dict[str, set[str]] = {}
    newest: dict[str, dt.date] = {}
    for c in rows_of("citations.jsonl"):
        if c["run"] in (1, 2):
            urls.setdefault(c["publisher"], set()).add(c["url"])
            if c["question_id"] in ts:
                d = when[(c["run"], c["question_id"], c["model"])]
                newest[c["url"]] = max(d, newest.get(c["url"], d))
    for card in cards:
        got = {i.code: (i.count, i.of) for i in card.improvement}
        us = urls[card.publisher]
        out = {u: meta.get(u, {}).get("outcome") for u in us}
        ok = [u for u in us if out[u] == "ok"]
        dated = [u for u in ok if meta[u]["effective_date"]]
        tsd = [u for u in dated if u in newest]
        dis = [u for u in us if out[u] == "robots_disallowed"]

        def host(u: str) -> str:
            final = urlsplit(meta[u].get("final_url") or u).hostname or ""
            return final if final in robots and not readable(final) else urlsplit(u).hostname or ""

        unread = [u for u in dis if host(u) in robots and not readable(host(u))]
        want = {
            "undated": (len(ok) - len(dated), len(ok)),
            "hidden_date": (
                sum(
                    meta[u]["effective_source"] in hidden_src
                    and not any(
                        c["source"] not in hidden_src and not c.get("rejected")
                        for c in meta[u].get("candidates", ())
                    )
                    for u in dated
                ),
                len(dated),
            ),
            "stale": (
                sum(
                    (newest[u] - dt.date.fromisoformat(meta[u]["effective_date"])).days > 365
                    for u in tsd
                ),
                len(tsd),
            ),
            "robots_blocked": (len(dis) - len(unread), len(us)),
            "robots_unreadable": (len(unread), len(us)),
            "blocked": (sum(out[u] in ("blocked", "gated") for u in us), len(us)),
            "not_html": (sum(out[u] in ("not_html", "too_large") for u in us), len(us)),
            "fetch_error": (sum(out[u] == "fetch_error" for u in us), len(us)),
        }
        for code, (k, n) in want.items():
            assert got.get(code, (0, n)) == (k, n) or (k == 0 and code not in got), (
                card.publisher,
                code,
            )


def test_every_finding_has_a_fix_and_evidence_and_no_medical_claim():
    cards = read_cards(STUDY / "results" / "domain_cards.json")
    rows = [i for c in cards for i in c.improvement]
    assert rows
    for i in rows:
        assert i.fix and 0 < i.count <= i.of and i.sources
        assert not MEDICAL_CLAIMS.search(i.finding + " " + i.fix), (i.code, i.finding, i.fix)


def test_lookup_on_the_flagship_cards_is_fast():
    cards = read_cards(STUDY / "results" / "domain_cards.json")
    start = time.perf_counter()
    for q in ("nhs.uk", "https://www.bbc.co.uk/news", "nobody.example", "nice.org.uk"):
        lookup(q, cards, answers=400, intent="treatment")
    assert time.perf_counter() - start < 1.0


def test_a_page_showing_any_date_is_never_called_hidden(tiny: Path):
    """D5.1 pass 2 M-a: a visible published date means the page shows a date."""
    cand = [
        {"source": "page_age", "kind": "modified", "rejected": None, "value": "2026-01-01"},
        {"source": "visible_text", "kind": "published", "rejected": None, "value": "2025-01-01"},
    ]
    _set_outcomes(tiny, {"https://nhs.uk/a": {"effective_source": "page_age", "candidates": cand}})
    cards, _, _ = _tiny_cards(tiny)
    assert "hidden_date" not in {i.code for i in cards[0].improvement}


@pytest.mark.parametrize(
    ("status", "words", "bot"),
    [
        (403, "refused the request (HTTP 403)", True),
        (503, "returned a server error (HTTP 503)", False),
        (None, "did not respond", False),
        (301, "redirected away from /robots.txt (HTTP 301)", False),
    ],
)
def test_robots_failures_are_worded_by_what_happened(tiny: Path, status, words, bot):
    """Pass 2 M-b: bot protection is named only for refusals; 'HTTP no response' never."""
    _set_outcomes(tiny, {"https://x.com/a": {"outcome": "robots_disallowed"}})
    log = [{"url": "https://x.com/robots.txt", "host": "x.com", "status": status, "outcome": "x"}]
    (tiny / "data" / "fetch_log.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in log), "utf-8"
    )
    cards, _, _ = _tiny_cards(tiny)
    row = {i.code: i for i in next(c for c in cards if c.publisher == "x.com").improvement}[
        "robots_unreadable"
    ]
    assert words in row.finding and "HTTP no response" not in row.finding
    assert row.finding.endswith("did not read it.")
    assert ("Bot protection" in row.fix) == bot


def test_a_www_twin_answering_200_does_not_make_an_unredirected_host_readable(tiny: Path):
    """Pass 2 L-d: robots rules are per origin."""
    _set_outcomes(tiny, {"https://x.com/a": {"outcome": "robots_disallowed"}})
    log = [
        {"url": "https://x.com/robots.txt", "host": "x.com", "status": 403, "outcome": "blocked"},
        {
            "url": "https://www.x.com/robots.txt",
            "host": "www.x.com",
            "status": 200,
            "outcome": "ok",
        },
    ]
    (tiny / "data" / "fetch_log.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in log), "utf-8"
    )
    cards, _, _ = _tiny_cards(tiny)
    codes = {i.code for i in next(c for c in cards if c.publisher == "x.com").improvement}
    assert "robots_unreadable" in codes and "robots_blocked" not in codes


def test_lookup_shows_idns_in_unicode_and_rejects_public_suffixes(tiny: Path):
    cards, _, _ = _tiny_cards(tiny)
    miss = lookup("bücher.example", cards, answers=15)
    assert isinstance(miss, NotCited) and miss.message.startswith("bücher.example was not cited")
    for suffix in ("co.uk", ".uk", "nhs.uk\\@evil.com"):
        hit = lookup(suffix, cards, answers=15)
        assert isinstance(hit, NotCited) and hit.publisher is None, suffix
