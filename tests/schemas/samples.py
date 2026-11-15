"""Valid sample records for schema tests and the v1 fixtures."""

from __future__ import annotations

from typing import Any

H16 = "0123456789abcdef"
H64 = "ab" * 32


def question(**over: Any) -> dict[str, Any]:
    d = {
        "id": "v-017",
        "text": "How much does an NHS prescription cost in England?",
        "intent": "nhs_services",
        "time_sensitive": True,
        "ts_reason": "prices",
    }
    return {**d, **over}


def answer(**over: Any) -> dict[str, Any]:
    text = "In England a prescription costs a fixed charge per item; many people are exempt."
    d = {
        "run": 1,
        "question_id": "v-017",
        "model": "claude-sonnet-5-5",
        "model_snapshot": "claude-sonnet-5-5",
        "raw_key": H64,
        "answer_text": text,
        "word_count": len(text.split()),
        "over_length": False,
        "searches": 2,
        "search_errors": [],
        "refusal": False,
        "error": None,
        "tokens_in": 21000,
        "tokens_out": 900,
        "cost_usd": 0.071,
        "answered_at": "2026-11-15T10:00:00Z",
        "prompt_hash": H16,
        "config_hash": H16,
    }
    return {**d, **over}


def citation(**over: Any) -> dict[str, Any]:
    d = {
        "run": 1,
        "question_id": "v-017",
        "model": "claude-sonnet-5-5",
        "url_raw": "https://www.nhs.uk/nhs-services/prescriptions/?utm_source=x",
        "url": "https://www.nhs.uk/nhs-services/prescriptions/",
        "host": "www.nhs.uk",
        "publisher": "nhs.uk",
        "publisher_group": None,
        "title": "Prescription charges",
        "quoted_span": "The current prescription charge is",
        "answer_span": "In England a prescription costs a fixed charge per item",
        "ordinal": 1,
    }
    return {**d, **over}


def consulted(**over: Any) -> dict[str, Any]:
    d = {
        "run": 1,
        "question_id": "v-017",
        "model": "claude-sonnet-5-5",
        "url": "https://www.nhs.uk/nhs-services/prescriptions/",
        "publisher": "nhs.uk",
        "page_age": "April 30, 2026",
        "cited": True,
    }
    return {**d, **over}


def candidate(
    kind: str = "modified", value: str = "2026-03-01", source: str = "schema_org", **over: Any
) -> dict[str, Any]:
    d = {
        "kind": kind,
        "value": value,
        "source": source,
        "evidence": "dateModified",
        "rejected": None,
    }
    return {**d, **over}


def page(**over: Any) -> dict[str, Any]:
    d = {
        "url": "https://www.nhs.uk/nhs-services/prescriptions/",
        "fetched_at": "2026-11-15T10:05:00Z",
        "outcome": "ok",
        "status": 200,
        "final_url": None,
        "candidates": [
            candidate(),
            candidate("published", "2024-01-10", "schema_org", evidence="datePublished"),
            candidate(
                "reviewed",
                "2026-02-01",
                "visible_text",
                evidence="Page last reviewed: 1 February 2026",
            ),
            candidate(
                "review_due",
                "2029-02-01",
                "visible_text",
                evidence="Next review due: 1 February 2029",
            ),
            candidate(
                "modified",
                "2026-11-15",
                "http_header",
                evidence="Last-Modified",
                rejected="within 24 hours of fetch",
            ),
        ],
        "date_modified": "2026-03-01",
        "date_published": "2024-01-10",
        "date_reviewed": "2026-02-01",
        "review_due": "2029-02-01",
        "modified_source": "schema_org",
        "published_source": "schema_org",
        "reviewed_source": "visible_text",
        "effective_date": "2026-02-01",
        "effective_source": "visible_text",
    }
    return {**d, **over}


def interval(
    point: float = 0.42, lo: float = 0.33, hi: float = 0.51, n: int = 100, k: int | None = 42
) -> dict[str, Any]:
    return {"point": point, "lo": lo, "hi": hi, "n": n, "k": k}


def summary(**over: Any) -> dict[str, Any]:
    d = {
        "schema_version": "1.0",
        "runs": [1, 2],
        "config_hash": H16,
        "questions_sha256": H64,
        "preregistration_sha256": H64,
        "share": [
            {
                "publisher": "nhs.uk",
                "model": "claude-sonnet-5-5",
                "intent": None,
                "run": 1,
                "kind": "presence",
                "share": interval(),
            }
        ],
        "concentration": [
            {"model": "gpt-6.1-sol", "run": 1, "top10_share": interval(), "hhi": 0.08}
        ],
        "freshness": [
            {
                "publisher": "nhs.uk",
                "model": None,
                "dated_pages": 30,
                "median_lag_days": 190.0,
                "iqr_days": [60.0, 400.0],
                "modified_after_answer": 1,
            }
        ],
        "stale": [
            {
                "model": "claude-sonnet-5-5",
                "intent": None,
                "definition": "primary",
                "rate": interval(0.2, 0.12, 0.3, 48, 10),
                "undated": 2,
            }
        ],
        "overlap": [
            {
                "intent": "fitness",
                "run": 1,
                "kind": "self",
                "model": "claude-sonnet-5-5",
                "value": interval(0.6, 0.5, 0.7, 20, None),
            }
        ],
        "stability": [
            {
                "model": "gpt-6.1-sol",
                "publisher": None,
                "metric": "self_jaccard",
                "value": interval(0.55, 0.45, 0.64, 100, None),
            }
        ],
        "coverage": interval(0.93, 0.9, 0.95, 640, 595),
        "date_accuracy": [
            {
                "source": "overall",
                "within_7_days": interval(0.86, 0.74, 0.93, 50, 43),
                "exact": interval(0.7, 0.56, 0.81, 50, 35),
            }
        ],
        "support": [
            {
                "model": "gpt-6.1-sol",
                "judge": "claude-opus-5-5",
                "support_rate": interval(0.8, 0.63, 0.9, 25, 20),
                "hand_agreement": 0.88,
                "kappa": interval(0.7, 0.45, 0.88, 25, None),
            }
        ],
        "error_counts": {
            "claude-sonnet-5-5": {
                "refusal": 0,
                "transport": 1,
                "over_length": 3,
                "zero_citation": 2,
            }
        },
        "spend_usd": 39.2,
        "generated_at": "2026-11-15T18:00:00Z",
    }
    return {**d, **over}


def card(**over: Any) -> dict[str, Any]:
    d = {
        "publisher": "nhs.uk",
        "share_by_model": {"claude-sonnet-5-5": interval()},
        "share_by_intent": {"nhs_services": interval(0.9, 0.8, 0.95, 40, 36)},
        "citations": 120,
        "answers_citing": 84,
        "median_freshness_lag_days": 190.0,
        "dated_pages": 30,
        "questions_citing": ["v-017"],
        "cited_instead": ["bbc.co.uk"],
    }
    return {**d, **over}


def verdict(**over: Any) -> dict[str, Any]:
    d = {
        "citation_ref": "1:v-017:claude-sonnet-5-5:1",
        "judge": "claude-opus-5-5",
        "verdict": "supported",
        "quote": "The current prescription charge is set each April.",
        "hand_label": "supported",
    }
    return {**d, **over}


def hand_label(**over: Any) -> dict[str, Any]:
    d = {
        "url": "https://www.nhs.uk/nhs-services/prescriptions/",
        "true_modified": "2026-03-01",
        "true_published": None,
        "not_determinable": False,
        "note": "footer",
    }
    return {**d, **over}


def config(**over: Any) -> dict[str, Any]:
    d = {
        "name": "my-study",
        "questions_path": "questions.jsonl",
        "intents": ["symptoms", "nutrition"],
        "models": ["claude-sonnet-5-5", "gpt-6.1-sol"],
        "effort": "medium",
        "user_location": {"type": "approximate", "country": "GB", "city": "London"},
        "max_searches": 3,
        "word_limit": 150,
        "stale_days": 365,
        "seeds": {"order": 1, "support_sample": 2, "hand_sample": 3, "bootstrap": 4},
        "max_cost_usd": 25.0,
        "user_agent": "citewatch/0.1.0 (+https://github.com/biplob819/ai-visibility)",
    }
    return {**d, **over}
