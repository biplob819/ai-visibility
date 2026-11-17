"""SUP-05 / HND-01..03 on the real study: the owner's frozen label sets, imported once.

OWNER D-62 (support labels) and D-63/D-64 (agent-checked, owner-approved date labels). Never
edit the pinned hashes to make a test pass: a changed label file is a new labelling round.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from citewatch.handcheck import dates_fingerprint, publish_problems
from citewatch.schemas import HandDateLabel, SupportVerdict
from citewatch.support.report import load_hand_labels

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "studies" / "uk-health" / "data"
SUPPORT_LABELS_SHA256 = "304274556d55a79c369e205a884c6e693c70b436906dd414b18947372795e939"
HAND_LABELS_SHA256 = "338c02b89feb8fb8d1bbd9bffc91879caaf43256a105f8f589791b768dcffb25"
PARSER_FIELDS = {"effective_date", "effective_source", "stratum", "candidates", "verdict"}


def _rows(name: str) -> list[dict]:
    text = (DATA / name).read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def test_the_support_labels_are_frozen():
    assert hashlib.sha256((DATA / "support_labels.jsonl").read_bytes()).hexdigest() == (
        SUPPORT_LABELS_SHA256
    )


def test_the_hand_date_labels_are_frozen():
    assert hashlib.sha256((DATA / "hand_labels.jsonl").read_bytes()).hexdigest() == (
        HAND_LABELS_SHA256
    )


def test_every_sheet_item_has_one_valid_label_and_the_key_is_blind():
    key = _rows("support_label_key.jsonl")
    labels = _rows("support_labels.jsonl")
    assert sorted(r["id"] for r in labels) == sorted(r["id"] for r in key)
    assert all(r["label"] in ("supported", "unsupported", "cant_tell") for r in labels)
    # the sheet's key maps an opaque id to a citation and carries no judge verdict
    assert all(set(r) == {"id", "citation_ref"} for r in key)
    hand = load_hand_labels(DATA.parent)
    assert set(hand) == {r["citation_ref"] for r in key}


def test_judged_citations_are_the_labelled_ones():
    verdicts = [SupportVerdict.model_validate(r) for r in _rows("support_verdicts.jsonl")]
    hand = load_hand_labels(DATA.parent)
    assert {v.citation_ref for v in verdicts} <= set(hand)


def test_hand_labels_cover_the_sample_and_hide_the_parser():
    sample = [r["url"] for r in _rows("hand_sample.jsonl")]
    labels = _rows("hand_labels.jsonl")
    assert [r["url"] for r in labels] == sample
    for r in labels:
        assert not PARSER_FIELDS & set(r)
        HandDateLabel.model_validate(
            {k: v for k, v in r.items() if k in HandDateLabel.model_fields}
        )
        assert r["checked_by"] == "agent" and r["approved_by"] == "owner"  # OWNER D-63
        assert isinstance(r["checker_loaded"], bool)  # D-68
        assert r["checker_loaded"] or r["not_determinable"]


def test_the_held_out_rule_holds_for_the_current_resolver():
    versions = {r["dates_version"] for r in _rows("hand_labels.jsonl")}
    assert versions == {dates_fingerprint()}
    assert publish_problems({"version": versions.pop()}) == []


def test_the_committed_hand_sample_redraws_from_committed_data():
    """HND-01 (M3.3 pass 1): the documented rule, seed and inputs give the committed sample."""
    from citewatch.handcheck import draw_hand_sample, study_pages, tuning_urls
    from citewatch.schemas import load_study_config

    base = DATA.parent
    tuning = tuning_urls(ROOT / "tests" / "fixtures" / "dates")
    seed = load_study_config(base / "study.yaml").seeds["hand_sample"]
    rows = draw_hand_sample(study_pages(base), seed, exclude=tuning)
    assert rows == _rows("hand_sample.jsonl")
    assert len(tuning) >= 20 and not tuning & {r["url"] for r in rows}
