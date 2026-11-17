"""The hand date check (Tech Spec §8.2, node M3.3).

50 dated cited pages, stratified by the chosen `effective_source` in proportion to its
frequency (at least 5 for each source with 5 or more pages), plus 5 undated pages, drawn with
the study's `hand_sample` seed from the pages cited in the study runs (`study_pages`). A checker
records each page's true dates without seeing the parser's: for the flagship study an agent that
never sees the parser's output, approved by the owner (OWNER D-63). Pages in the resolver's
tuning set (`tests/fixtures/dates`) are never drawn: the check must be held out (D-6).

Correct: the parser's effective date is within 7 days of the hand date (the checked modified
date, else the checked published date); exact matches are reported too. An undated page is
correct when the checker also finds no date.

Held-out rule (D-6, C5): every label row records the date code's fingerprint. If the resolver
changes after labelling, publishing (finalise and the summary's accuracy rows) is blocked until
25 pages are labelled afresh against the new code; only those fresh labels are then scored.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from citewatch.metrics.stats import wilson
from citewatch.schemas import AccuracyRow, HandDateLabel

SAMPLE_FILE = "hand_sample.jsonl"
LABELS_FILE = "hand_labels.jsonl"
DATED = 50
UNDATED = 5
MIN_PER_SOURCE = 5
NEAR_DAYS = 7
FRESH_AFTER_CHANGE = 25
DATES_PACKAGE = Path(__file__).resolve().parent / "dates"


def dates_fingerprint(package: Path = DATES_PACKAGE) -> str:
    """sha256 over the date resolver's source files, in name order (its behaviour version)."""
    h = hashlib.sha256()
    for f in sorted(package.glob("*.py")):
        h.update(f.name.encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def _allocate(counts: Mapping[str, int], total: int) -> dict[str, int]:
    """Proportional allocation with at least MIN_PER_SOURCE for sources that have that many
    pages; largest remainders fill the rest; never more than a source holds."""
    alloc = {s: (MIN_PER_SOURCE if n >= MIN_PER_SOURCE else 0) for s, n in counts.items()}
    left = total - sum(alloc.values())
    pool = sum(counts.values())
    if left > 0 and pool:
        shares = {s: left * counts[s] / pool for s in counts}
        for s in counts:
            alloc[s] += math.floor(shares[s])
        order = sorted(counts, key=lambda s: (-(shares[s] - math.floor(shares[s])), s))
        for s in order[: total - sum(alloc.values())]:
            alloc[s] += 1
    for s in alloc:  # cap at what the source has, then hand the spare to the largest sources
        alloc[s] = min(alloc[s], counts[s])
    spare = total - sum(alloc.values())
    for s in sorted(counts, key=lambda s: (-counts[s], s)):
        take = min(spare, counts[s] - alloc[s])
        alloc[s] += take
        spare -= take
    return alloc


def study_pages(base: Path, runs: Iterable[int] = (1, 2)) -> list[dict[str, Any]]:
    """`page_meta` rows for pages cited in the study runs (smoke-run pages are left out)."""
    data = base / "data"
    keep = set(runs)
    cited = set()
    for x in (data / "citations.jsonl").read_text(encoding="utf-8").splitlines():
        if x.strip():
            c = json.loads(x)
            if c["run"] in keep:
                cited.add(c["url"])
    rows = (data / "page_meta.jsonl").read_text(encoding="utf-8").splitlines()
    return [p for p in (json.loads(x) for x in rows if x.strip()) if p["url"] in cited]


def draw_hand_sample(
    pages: Iterable[Mapping[str, Any]],
    seed: int,
    exclude: Iterable[str] = (),
    dated: int = DATED,
    undated: int = UNDATED,
) -> list[dict[str, Any]]:
    """Rows of url, stratum (the effective source, or `undated`) and role, in a seeded order."""
    skip = set(exclude)
    by_source: dict[str, list[str]] = defaultdict(list)
    no_date: list[str] = []
    for p in pages:
        url = p["url"]
        if url in skip or p.get("outcome") != "ok":  # the owner must be able to open the page
            continue
        if p.get("effective_date"):
            by_source[str(p.get("effective_source") or "unknown")].append(url)
        else:
            no_date.append(url)
    rng = random.Random(seed)
    alloc = _allocate({s: len(v) for s, v in by_source.items()}, dated)
    rows: list[dict[str, Any]] = []
    for source in sorted(by_source):
        for url in rng.sample(sorted(by_source[source]), alloc[source]):
            rows.append({"url": url, "stratum": source, "role": "dated", "seed": seed})
    for url in rng.sample(sorted(no_date), min(undated, len(no_date))):
        rows.append({"url": url, "stratum": "undated", "role": "undated", "seed": seed})
    rng.shuffle(rows)  # the sheet's order says nothing about the stratum
    return rows


def tuning_urls(fixtures: Path) -> set[str]:
    """The resolver's tuning-set URLs (never part of the held-out check)."""
    index = fixtures / "index.json"
    if not index.is_file():
        return set()
    data = json.loads(index.read_text(encoding="utf-8"))
    rows = data.values() if isinstance(data, dict) else data
    return {r["url"] for r in rows if isinstance(r, dict) and "url" in r}


def write_once(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    if path.is_file():
        raise FileExistsError(f"{path} already exists; the hand sample is drawn once")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8", newline="\n"
    )
    return path


def hand_date(label: HandDateLabel) -> dt.date | None:
    return label.true_modified or label.true_published


def accuracy(
    sample: Sequence[Mapping[str, Any]],
    labels: Mapping[str, HandDateLabel],
    effective: Mapping[str, dt.date | None],
) -> list[AccuracyRow]:
    """Overall and per-source accuracy with Wilson intervals. A dated page the owner could not
    date is left out of its rate (it cannot be judged); undated pages form their own row."""
    within: Counter[str] = Counter()
    exact: Counter[str] = Counter()
    n: Counter[str] = Counter()
    for row in sample:
        label = labels.get(row["url"])
        if label is None:
            continue
        source = row["stratum"]
        if row["role"] == "undated":
            n[source] += 1
            ok = label.not_determinable
            within[source] += ok
            exact[source] += ok
            continue
        truth, got = hand_date(label), effective.get(row["url"])
        if truth is None or got is None:
            continue
        days = abs((got - truth).days)
        for key in (source, "overall"):
            n[key] += 1
            within[key] += days <= NEAR_DAYS
            exact[key] += days == 0
    order = ["overall", *sorted(s for s in n if s not in ("overall", "undated")), "undated"]
    return [
        AccuracyRow(source=s, within_7_days=wilson(within[s], n[s]), exact=wilson(exact[s], n[s]))
        for s in order
        if n[s]
    ]


def labels_meta(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The fingerprint state of a label set: one `version` if every row shares it (else None),
    and how many rows were labelled under each version."""
    counts = Counter(str(r.get("dates_version")) for r in rows)
    return {
        "version": next(iter(counts)) if len(counts) == 1 else None,
        "labelled_by_version": dict(counts),
    }


def current_labels(rows: Sequence[Mapping[str, Any]], current: str | None = None) -> list:
    """The rows that count: all of them when none is stale, else only those made against the
    current resolver (publish_problems says whether there are enough)."""
    current = current or dates_fingerprint()
    return [r for r in rows if r.get("dates_version") == current]


def publish_problems(labels_meta: Mapping[str, Any], current: str | None = None) -> list[str]:
    """The held-out rule: labels made against older resolver code block publishing until 25
    pages are labelled against the current code."""
    current = current or dates_fingerprint()
    fresh = int(labels_meta.get("labelled_by_version", {}).get(current, 0))
    if labels_meta.get("version") == current or fresh >= FRESH_AFTER_CHANGE:
        return []
    return [
        f"the date resolver changed since the hand labels "
        f"({labels_meta.get('version')} -> {current}); label {FRESH_AFTER_CHANGE - fresh} more "
        "pages against the current code before publishing (D-6)"
    ]
