"""Domain cards, lookup and the improvement report (node D5.1, Tech Spec §9, OWNER D-65).

One `DomainCard` per publisher cited in the scored runs, built from `summary.json` and the
frozen study data, so the demo answers "is my site cited, how often, how fresh, and what would
help?" without calling a model. The improvement rows describe sourcing, dates and readability
only; they never judge medical accuracy (NFR4).
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from citewatch.extract.urls import UrlError, publisher_of
from citewatch.metrics.data import StudyData
from citewatch.schemas import DomainCard, Improvement, StudySummary

CARDS_FILE = "domain_cards.json"
CITED_INSTEAD_TOP = 5
EXAMPLES = 3
HIDDEN_SOURCES = frozenset({"sitemap", "http_header"})
TOP_FOR_INTENT = 5
INTENT_MIN_CITATIONS = 5  # below this, missing intents say more about volume than gaps


def _key(*parts: object) -> str:
    return "/".join(str(p) for p in parts)


def _page_meta(base: Path) -> dict[str, dict[str, Any]]:
    path = base / "data" / "page_meta.jsonl"
    rows = (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())
    return {r["url"]: r for r in rows}


def _verdicts(base: Path) -> dict[str, dict[str, str]]:
    """citation_ref -> {judge: verdict} from the support check, if it ran."""
    path = base / "data" / "support_verdicts.jsonl"
    out: dict[str, dict[str, str]] = defaultdict(dict)
    if path.is_file():
        for x in path.read_text(encoding="utf-8").splitlines():
            if x.strip():
                v = json.loads(x)
                out[v["citation_ref"]][v["judge"]] = v["verdict"]
    return out


def _citation_publishers(base: Path, runs: set[int]) -> dict[str, str]:
    """citation_ref -> publisher for the scored runs."""
    path = base / "data" / "citations.jsonl"
    out = {}
    for x in path.read_text(encoding="utf-8").splitlines():
        if x.strip():
            c = json.loads(x)
            if c["run"] in runs:
                out[f"{c['run']}:{c['question_id']}:{c['model']}:{c['ordinal']}"] = c["publisher"]
    return out


def cited_instead(data: StudyData, publisher: str) -> tuple[str, ...]:
    """§9: on questions where `publisher` was cited by one model or run but not another, the
    publishers cited in the answers that left it out, by count then name."""
    by_q: dict[str, list[Any]] = defaultdict(list)
    for a in data.answers:
        if a.valid:
            by_q[a.qid].append(a)
    counts: Counter[str] = Counter()
    for answers in by_q.values():
        has = [any(c.publisher == publisher for c in a.cites) for a in answers]
        if any(has) and not all(has):
            for a, h in zip(answers, has, strict=True):
                if not h:
                    counts.update({c.publisher for c in a.cites} - {publisher})
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return tuple(p for p, _ in ranked[:CITED_INSTEAD_TOP])


def _improvements(
    publisher: str,
    data: StudyData,
    summary: StudySummary,
    meta: Mapping[str, Mapping[str, Any]],
    stale_days: int,
    verdicts: Mapping[str, Mapping[str, str]],
    cite_pub: Mapping[str, str],
    instead: Sequence[str],
    newest_answer: Mapping[str, Any],
    hand: Mapping[str, str],
) -> list[Improvement]:
    rows: list[Improvement] = []
    answers = [a for a in data.answers if a.valid]
    urls = sorted({c.url for a in answers for c in a.cites if c.publisher == publisher})

    # intent_absent: cited somewhere, but on no question of an intent (summary presence rows)
    cited_intents = {
        r.intent
        for r in summary.share
        if r.kind == "presence" and r.publisher == publisher and r.intent and (r.share.k or 0) > 0
    }
    intents = sorted({a.intent for a in answers})
    absent = [i for i in intents if i not in cited_intents]
    cited_n = sum(c.publisher == publisher for a in answers for c in a.cites)
    if absent and len(absent) < len(intents) and cited_n >= INTENT_MIN_CITATIONS:
        names = ", ".join(i.replace("_", " ") for i in absent)
        others = f" Cited instead in this study: {', '.join(instead[:3])}." if instead else ""
        rows.append(
            Improvement(
                code="intent_absent",
                finding=f"Not cited on any {names} question, though cited on other topics.",
                fix="Check that a page answers these questions directly, in plain text near the "
                f"top, with a visible date.{others}",
                count=len(absent),
                of=len(intents),
                source="summary.json",
                examples=tuple(absent[:EXAMPLES]),
            )
        )

    ok = [u for u in urls if meta.get(u, {}).get("outcome") == "ok"]
    undated = [u for u in ok if not meta[u].get("effective_date")]
    if undated:
        rows.append(
            Improvement(
                code="undated",
                finding=f"{len(undated)} of {len(ok)} cited pages that loaded state no date "
                "citewatch could read.",
                fix='Add a visible "last updated" date and schema.org dateModified to each page.',
                count=len(undated),
                of=len(ok),
                source="page_meta.jsonl",
                examples=tuple(undated[:EXAMPLES]),
            )
        )
    dated = [u for u in urls if meta.get(u, {}).get("effective_date")]
    hidden = [u for u in dated if meta[u].get("effective_source") in HIDDEN_SOURCES]
    if hidden:
        rows.append(
            Improvement(
                code="hidden_date",
                finding=f"{len(hidden)} of {len(dated)} dated cited pages are dated only by a "
                "sitemap or HTTP header, which readers never see.",
                fix="Show the last-updated date on the page itself, and in schema.org markup.",
                count=len(hidden),
                of=len(dated),
                source="page_meta.jsonl",
                examples=tuple(hidden[:EXAMPLES]),
            )
        )
    stale = [
        u for u in dated if (newest_answer[u] - _date(meta[u]["effective_date"])).days > stale_days
    ]
    if stale:
        rows.append(
            Improvement(
                code="stale",
                finding=f"{len(stale)} of {len(dated)} dated cited pages were last updated more "
                f"than {stale_days} days before the answers that cited them.",
                fix="Review these pages: update and re-date them, or retire them with a redirect "
                "to a current page.",
                count=len(stale),
                of=len(dated),
                source="page_meta.jsonl",
                examples=tuple(stale[:EXAMPLES]),
            )
        )
    blocked = [u for u in urls if meta.get(u, {}).get("outcome") == "robots_disallowed"]
    if blocked:
        rows.append(
            Improvement(
                code="robots_blocked",
                finding=f"{len(blocked)} of {len(urls)} cited pages are disallowed by robots.txt "
                "for citewatch's reader, so their dates could not be checked.",
                fix="Decide whether independent checkers may read these pages; AI search tools "
                "use their own crawlers, so this does not by itself stop citation.",
                count=len(blocked),
                of=len(urls),
                source="page_meta.jsonl",
                examples=tuple(blocked[:EXAMPLES]),
            )
        )
    broken = [u for u in urls if meta.get(u, {}).get("outcome") == "fetch_error"]
    if broken:
        rows.append(
            Improvement(
                code="fetch_error",
                finding=f"{len(broken)} of {len(urls)} cited pages failed to load when checked "
                "(for example a 404 or a timeout).",
                fix="Fix or redirect these URLs; AI answers still link to them.",
                count=len(broken),
                of=len(urls),
                source="page_meta.jsonl",
                examples=tuple(broken[:EXAMPLES]),
            )
        )
    mine = {ref: v for ref, v in verdicts.items() if cite_pub.get(ref) == publisher}
    both_no = sorted(r for r, v in mine.items() if len(v) >= 2 and "supported" not in v.values())
    if both_no:
        owner_yes = sum(hand.get(r) == "supported" for r in both_no)
        owner_note = (
            f" The owner's own check found {owner_yes} of these {len(both_no)} supported, so "
            "treat this as a hint that the fact is hard to find, not that it is missing."
            if owner_yes
            else ""
        )
        rows.append(
            Improvement(
                code="unsupported",
                finding=f"In the support sample, both AI judges found the cited claim not stated "
                f"on the page for {len(both_no)} of {len(mine)} sampled citations.{owner_note}",
                fix="State the key facts these answers rely on explicitly in the page text "
                "(numbers, eligibility, steps), not only in images, tables or linked files.",
                count=len(both_no),
                of=len(mine),
                source="support_verdicts.jsonl",
                examples=tuple(both_no[:EXAMPLES]),
            )
        )
    return rows


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def build_cards(
    base: Path, data: StudyData, summary: StudySummary, stale_days: int
) -> list[DomainCard]:
    from citewatch.support.report import load_hand_labels

    meta = _page_meta(base)
    verdicts = _verdicts(base)
    hand = load_hand_labels(base)
    cite_pub = _citation_publishers(base, set(summary.runs))
    pooled = {r.publisher: r for r in summary.freshness if r.model is None}
    presence = [r for r in summary.share if r.kind == "presence"]
    answers = [a for a in data.answers if a.valid]
    citations: Counter[str] = Counter()
    citing: dict[str, set[tuple[int, str, str]]] = defaultdict(set)
    questions: dict[str, set[str]] = defaultdict(set)
    for a in answers:
        for c in a.cites:
            citations[c.publisher] += 1
            citing[c.publisher].add((a.run, a.qid, a.model))
            questions[c.publisher].add(a.qid)
    newest: dict[str, Any] = {}  # url -> date of the latest answer citing it
    for a in answers:
        for c in a.cites:
            d = a.answered_at.date()
            if c.url not in newest or d > newest[c.url]:
                newest[c.url] = d
    cards = []
    for p in sorted(citations, key=lambda p: (-citations[p], p)):
        fresh = pooled.get(p)
        instead = cited_instead(data, p)
        cards.append(
            DomainCard(
                publisher=p,
                share_by_model={
                    _key(r.model, f"run-{r.run}"): r.share
                    for r in presence
                    if r.publisher == p and r.intent is None
                },
                share_by_intent={
                    _key(r.intent, r.model, f"run-{r.run}"): r.share
                    for r in presence
                    if r.publisher == p and r.intent is not None
                },
                citations=citations[p],
                answers_citing=len(citing[p]),
                median_freshness_lag_days=fresh.median_lag_days if fresh else None,
                dated_pages=fresh.dated_pages if fresh else 0,
                questions_citing=tuple(sorted(questions[p])),
                cited_instead=instead,
                improvement=tuple(
                    _improvements(
                        p,
                        data,
                        summary,
                        meta,
                        stale_days,
                        verdicts,
                        cite_pub,
                        instead,
                        newest,
                        hand,
                    )
                ),
            )
        )
    return cards


def write_cards(base: Path, cards: Iterable[DomainCard]) -> Path:
    path = base / "results" / CARDS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [c.model_dump(mode="json") for c in cards]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def read_cards(path: Path) -> list[DomainCard]:
    return [DomainCard.model_validate(c) for c in json.loads(path.read_text(encoding="utf-8"))]


@dataclass(frozen=True)
class NotCited:
    query: str
    publisher: str | None
    answers: int
    message: str
    top_for_intent: tuple[str, ...]


def normalise(query: str) -> str:
    """Strip scheme, user info, `www.`, path, query and port; lower-case."""
    q = query.strip()
    host = urlsplit(q if "//" in q else f"//{q}").hostname or ""
    return host.removeprefix("www.").rstrip(".").lower()


def lookup(
    query: str,
    cards: Sequence[DomainCard],
    answers: int,
    intent: str | None = None,
) -> DomainCard | NotCited:
    """The card for the publisher `query` maps to, through the extractor's own `publisher_of`;
    else a not-cited result naming the study's answers and the top publishers for `intent`."""
    host = normalise(query)
    try:
        publisher = publisher_of(host)[0] if host else None
    except UrlError:
        publisher = None
    by = {c.publisher: c for c in cards}
    if publisher in by:
        return by[publisher]
    if intent:
        ranked = sorted(
            cards,
            key=lambda c: (
                -sum(
                    (s.k or 0) for k, s in c.share_by_intent.items() if k.startswith(f"{intent}/")
                ),
                c.publisher,
            ),
        )
        top = tuple(
            c.publisher
            for c in ranked
            if any((s.k or 0) for k, s in c.share_by_intent.items() if k.startswith(f"{intent}/"))
        )[:TOP_FOR_INTENT]
    else:
        top = tuple(c.publisher for c in cards[:TOP_FOR_INTENT])
    name = publisher or query.strip()
    return NotCited(
        query=query,
        publisher=publisher,
        answers=answers,
        message=f"{name} was not cited in any of the {answers} answers in this study.",
        top_for_intent=top,
    )
