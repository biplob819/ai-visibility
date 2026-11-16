"""DAT-04: the 20-page test set (trimmed real snapshots, owner-confirmed labels; D-6 tuning set)."""

import datetime as dt
import json

import pytest

from citewatch.dates import from_header, from_html, resolve_dates
from harness_lib import ROOT

SET = ROOT / "tests" / "fixtures" / "dates"
LABELS = json.loads((SET / "labels.json").read_text(encoding="utf-8"))
INDEX = json.loads((SET / "index.json").read_text(encoding="utf-8"))


def test_the_set_has_at_least_twenty_pages_with_snapshots():
    assert len(LABELS["pages"]) >= 20
    for slug in LABELS["pages"]:
        assert (SET / "pages" / f"{slug}.html").is_file() and slug in INDEX


@pytest.mark.parametrize("slug", sorted(LABELS["pages"]))
def test_the_resolver_matches_each_label(slug):
    label, meta = LABELS["pages"][slug], INDEX[slug]
    html = (SET / "pages" / f"{slug}.html").read_text(encoding="utf-8")
    cands = from_html(html, meta["final_url"]) + from_header(meta["last_modified"])
    pm = resolve_dates(
        meta["url"],
        outcome="ok",
        status=200,
        fetched_at=dt.datetime.fromisoformat(meta["fetched_at"]),
        final_url=meta["final_url"],
        candidates=cands,
    )
    got = {
        "reviewed": pm.date_reviewed,
        "modified": pm.date_modified,
        "published": pm.date_published,
        "review_due": pm.review_due,
    }
    for kind, value in got.items():
        assert (None if value is None else value.isoformat()) == label[kind], (slug, kind)


def test_snapshots_hold_only_date_bearing_parts():
    for f in (SET / "pages").glob("*.html"):
        text = f.read_text(encoding="utf-8")
        assert len(text) < 6000, f.name  # trimmed, never a whole page


def test_the_labels_are_owner_confirmed():
    """DAT-04 needs labels the owner checked against the live pages (OWNER D-46)."""
    assert LABELS["status"] == "confirmed" and LABELS["confirmed_at"]
