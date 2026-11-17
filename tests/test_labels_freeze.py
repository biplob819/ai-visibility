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
HAND_LABELS_SHA256 = "e8accb0484f21304ed5d0a4a4434be9c1c0b002e7675f5a953db3f665ff2ad5d"
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


def test_the_held_out_rule_holds_for_the_current_resolver():
    versions = {r["dates_version"] for r in _rows("hand_labels.jsonl")}
    assert versions == {dates_fingerprint()}
    assert publish_problems({"version": versions.pop()}) == []
