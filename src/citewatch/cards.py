"""Domain cards, lookup and the improvement report (node D5.1, Tech Spec §9, OWNER D-65).

One `DomainCard` per publisher cited in the scored runs, built from `summary.json` and the
frozen study data, so the demo answers "is my site cited, how often, how fresh, and what would
help?" without calling a model. The improvement rows describe sourcing, dates and readability
only; they never judge medical accuracy (NFR4), and they never state more than the data shows
about a publisher's site (D-69).
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from citewatch.extract.urls import UrlError, publisher_of
from citewatch.metrics.data import StudyData
from citewatch.schemas import DomainCard, Improvement, StudySummary

CARDS_FILE = "domain_cards.json"
CITED_INSTEAD_TOP = 5
EXAMPLES = 3
# date sources a reader never sees on the page: the search tool's page age, sitemaps, headers
HIDDEN_SOURCES = frozenset({"sitemap", "http_header", "page_age"})
TOP_FOR_INTENT = 5
TS_PAGES = "dated pages cited on time-sensitive questions"
# a missing intent is reported only for publishers cited broadly enough for the gap to mean
# something: on this many distinct questions, across at least two intents (D-69)
INTENT_MIN_QUESTIONS = 5
INTENT_MIN_INTENTS = 2


@dataclass(frozen=True)
class _Study:
    """Everything the improvement rows read, loaded once."""

    meta: Mapping[str, Mapping[str, Any]]
    robots: Mapping[str, int | None]  # host -> status of its robots.txt, if never readable
    verdicts: Mapping[str, Mapping[str, str]]
    hand: Mapping[str, str]
    cite_pub: Mapping[str, str]
    newest_ts: Mapping[str, dt.date]  # url -> latest time-sensitive answer citing it
    intent_leaders: Mapping[str, tuple[str, ...]]
    stale_days: int
    answers: Sequence[Any] = field(default_factory=tuple)


def _key(*parts: object) -> str:
    return "/".join(str(p) for p in parts)


def _rows(path: Path) -> Iterable[dict[str, Any]]:
    if path.is_file():
        for x in path.read_text(encoding="utf-8").splitlines():
            if x.strip():
                yield json.loads(x)


def _unreadable_robots(base: Path) -> dict[str, int | None]:
    """Hosts whose robots.txt never returned 200, with the last status seen (H1, D-69): the
    fetcher treats an unreadable robots.txt as disallowing the host, which is not the same as
    the site's robots.txt disallowing citewatch."""
    seen: dict[str, list[int | None]] = defaultdict(list)
    for r in _rows(base / "data" / "fetch_log.jsonl"):
        if urlsplit(r["url"]).path == "/robots.txt":
            seen[r["host"]].append(r.get("status"))
    ok = {h for h, s in seen.items() if 200 in s}
    bare = {h.removeprefix("www.") for h in ok}
    return {h: s[-1] for h, s in seen.items() if h not in ok and h.removeprefix("www.") not in bare}


def _verdicts(base: Path) -> dict[str, dict[str, str]]:
    """citation_ref -> {judge: verdict} from the support check, if it ran."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for v in _rows(base / "data" / "support_verdicts.jsonl"):
        out[v["citation_ref"]][v["judge"]] = v["verdict"]
    return out


def _citation_publishers(base: Path, runs: set[int]) -> dict[str, str]:
    out = {}
    for c in _rows(base / "data" / "citations.jsonl"):
        if c["run"] in runs:
            out[f"{c['run']}:{c['question_id']}:{c['model']}:{c['ordinal']}"] = c["publisher"]
    return out


def _of(k: int, n: int, noun: str, verbs: tuple[str, str] = ("is", "are")) -> str:
    """'1 of 3 cited pages is' / '2 of 3 cited pages are'."""
    return f"{k} of {n} {noun} {verbs[0] if k == 1 else verbs[1]}"


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


def _intent_leaders(summary: StudySummary) -> dict[str, tuple[str, ...]]:
    """intent -> publishers cited in most answers to that intent (presence k over model/run)."""
    k: dict[str, Counter[str]] = defaultdict(Counter)
    for r in summary.share:
        if r.kind == "presence" and r.intent:
            k[r.intent][r.publisher] += r.share.k or 0
    return {
        i: tuple(p for p, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])) if n)[
            :TOP_FOR_INTENT
        ]
        for i, c in k.items()
    }


def _improvements(publisher: str, summary: StudySummary, st: _Study) -> list[Improvement]:
    rows: list[Improvement] = []
    answers = st.answers
    urls = sorted({c.url for a in answers for c in a.cites if c.publisher == publisher})
    meta = st.meta
    outcome = {u: meta.get(u, {}).get("outcome", "missing") for u in urls}

    # intent_absent: broad presence elsewhere, none on an intent (summary presence rows)
    cited_intents = {
        r.intent
        for r in summary.share
        if r.kind == "presence" and r.publisher == publisher and r.intent and (r.share.k or 0) > 0
    }
    intents = sorted({a.intent for a in answers})
    questions = {a.qid for a in answers if any(c.publisher == publisher for c in a.cites)}
    absent = [i for i in intents if i not in cited_intents]
    if (
        absent
        and len(questions) >= INTENT_MIN_QUESTIONS
        and len(cited_intents) >= INTENT_MIN_INTENTS
    ):
        names = ", ".join(i.replace("_", " ") for i in absent)
        leaders = sorted(
            {p for i in absent for p in st.intent_leaders.get(i, ())[:3]} - {publisher}
        )
        lead = f" Cited most on those questions: {', '.join(leaders)}." if leaders else ""
        rows.append(
            Improvement(
                code="intent_absent",
                finding=f"Cited on {len(questions)} questions across {len(cited_intents)} topics, "
                f"but on no {names} question. This may simply be outside the site's remit.",
                fix="If the site covers these topics, check that a page answers such questions "
                f"directly, in plain text near the top, with a visible date.{lead}",
                count=len(absent),
                of=len(intents),
                sources=("summary.json",),
                examples=tuple(absent[:EXAMPLES]),
            )
        )

    ok = [u for u in urls if outcome[u] == "ok"]
    undated = [u for u in ok if not meta[u].get("effective_date")]
    if undated:
        rows.append(
            Improvement(
                code="undated",
                finding=f"{_of(len(undated), len(ok), 'cited pages that loaded', ('has', 'have'))} "
                "no date citewatch could read on the page.",
                fix='Add a visible "last updated" date and schema.org dateModified to each page.',
                count=len(undated),
                of=len(ok),
                sources=("page_meta.jsonl",),
                examples=tuple(undated[:EXAMPLES]),
            )
        )
    dated_ok = [u for u in ok if meta[u].get("effective_date")]
    hidden = [u for u in dated_ok if meta[u].get("effective_source") in HIDDEN_SOURCES]
    if hidden:
        rows.append(
            Improvement(
                code="hidden_date",
                finding=f"{_of(len(hidden), len(dated_ok), 'dated pages that loaded')} dated "
                "only by a sitemap, an HTTP header or the search tool's page age, none of which "
                "a reader sees.",
                fix="Show the last-updated date on the page itself, and in schema.org markup.",
                count=len(hidden),
                of=len(dated_ok),
                sources=("page_meta.jsonl",),
                examples=tuple(hidden[:EXAMPLES]),
            )
        )
    # stale (§6.3 reading): pages that loaded, cited on time-sensitive questions, dated more
    # than stale_days before the latest such answer
    ts = [u for u in dated_ok if u in st.newest_ts]
    stale = [
        u
        for u in ts
        if (st.newest_ts[u] - dt.date.fromisoformat(meta[u]["effective_date"])).days > st.stale_days
    ]
    if stale:
        rows.append(
            Improvement(
                code="stale",
                finding=f"{_of(len(stale), len(ts), TS_PAGES)} dated more than "
                f"{st.stale_days} days before the answers that cited them.",
                fix="Review these pages: if the guidance has changed, update and re-date them; "
                "if it has not, a visible reviewed date says so.",
                count=len(stale),
                of=len(ts),
                sources=("page_meta.jsonl", "answers.jsonl", "questions.jsonl"),
                examples=tuple(stale[:EXAMPLES]),
            )
        )
    disallowed = [u for u in urls if outcome[u] == "robots_disallowed"]
    unreadable = [u for u in disallowed if urlsplit(u).hostname in st.robots]
    real = [u for u in disallowed if u not in set(unreadable)]
    if real:
        rows.append(
            Improvement(
                code="robots_blocked",
                finding=f"{_of(len(real), len(urls), 'cited pages')} disallowed by the site's "
                "robots.txt for citewatch's reader, so the dates could not be checked.",
                fix="Decide whether independent checkers may read these pages; AI search tools "
                "use their own crawlers, so this does not by itself stop citation.",
                count=len(real),
                of=len(urls),
                sources=("page_meta.jsonl", "fetch_log.jsonl"),
                examples=tuple(real[:EXAMPLES]),
            )
        )
    if unreadable:
        statuses = sorted(
            {str(st.robots[urlsplit(u).hostname or ""] or "no response") for u in unreadable}
        )
        rows.append(
            Improvement(
                code="robots_unreadable",
                finding=f"{_of(len(unreadable), len(urls), 'cited pages')} on a host whose "
                f"robots.txt could not be read (HTTP {', '.join(statuses)}), so citewatch did "
                "not read them.",
                fix="Bot protection that refuses robots.txt also hides the site's rules from "
                "well-behaved readers; serving robots.txt to them keeps its rules visible.",
                count=len(unreadable),
                of=len(urls),
                sources=("page_meta.jsonl", "fetch_log.jsonl"),
                examples=tuple(unreadable[:EXAMPLES]),
            )
        )
    refused = [u for u in urls if outcome[u] in ("blocked", "gated")]
    if refused:
        rows.append(
            Improvement(
                code="blocked",
                finding=f"{_of(len(refused), len(urls), 'cited pages')} refused to automated "
                "readers or behind a sign-in when checked.",
                fix="If these pages are public guidance, let well-behaved readers load them so "
                "their dates can be checked.",
                count=len(refused),
                of=len(urls),
                sources=("page_meta.jsonl",),
                examples=tuple(refused[:EXAMPLES]),
            )
        )
    files = [u for u in urls if outcome[u] in ("not_html", "too_large")]
    if files:
        rows.append(
            Improvement(
                code="not_html",
                finding=f"{_of(len(files), len(urls), 'cited links')} documents rather than web "
                "pages (for example PDFs), which carry no machine-readable date.",
                fix="Publish key guidance as an HTML page with a visible date, and link the "
                "document from it.",
                count=len(files),
                of=len(urls),
                sources=("page_meta.jsonl",),
                examples=tuple(files[:EXAMPLES]),
            )
        )
    broken = [u for u in urls if outcome[u] == "fetch_error"]
    if broken:
        rows.append(
            Improvement(
                code="fetch_error",
                finding=f"{_of(len(broken), len(urls), 'cited pages')} failing to load when "
                "checked (for example a 404 or a timeout).",
                fix="Fix or redirect these URLs; AI answers still link to them.",
                count=len(broken),
                of=len(urls),
                sources=("page_meta.jsonl",),
                examples=tuple(broken[:EXAMPLES]),
            )
        )
    # unsupported: both AI judges say the claim is not on the page, and the owner's check did
    # not find it supported either (D-69: never contradict the owner's labels)
    mine = {ref: v for ref, v in st.verdicts.items() if st.cite_pub.get(ref) == publisher}
    both_no = sorted(
        r
        for r, v in mine.items()
        if len(v) >= 2 and "supported" not in v.values() and st.hand.get(r) != "supported"
    )
    if both_no:
        rows.append(
            Improvement(
                code="unsupported",
                finding=f"In the support sample, both AI judges found the cited claim not stated "
                f"on the page for {len(both_no)} of {len(mine)} sampled citations, and the "
                "owner's check did not find it supported.",
                fix="State the key facts these answers rely on explicitly in the page text "
                "(numbers, eligibility, steps), not only in images, tables or linked files.",
                count=len(both_no),
                of=len(mine),
                sources=("support_verdicts.jsonl", "support_labels.jsonl"),
                examples=tuple(both_no[:EXAMPLES]),
            )
        )
    return rows


def build_cards(
    base: Path, data: StudyData, summary: StudySummary, stale_days: int
) -> list[DomainCard]:
    from citewatch.support.report import load_hand_labels

    answers = [a for a in data.answers if a.valid]
    newest_ts: dict[str, dt.date] = {}
    for a in answers:
        if a.time_sensitive:
            for c in a.cites:
                d = a.answered_at.date()
                if c.url not in newest_ts or d > newest_ts[c.url]:
                    newest_ts[c.url] = d
    st = _Study(
        meta={r["url"]: r for r in _rows(base / "data" / "page_meta.jsonl")},
        robots=_unreadable_robots(base),
        verdicts=_verdicts(base),
        hand=load_hand_labels(base),
        cite_pub=_citation_publishers(base, set(summary.runs)),
        newest_ts=newest_ts,
        intent_leaders=_intent_leaders(summary),
        stale_days=stale_days,
        answers=answers,
    )
    pooled = {r.publisher: r for r in summary.freshness if r.model is None}
    presence = [r for r in summary.share if r.kind == "presence"]
    citations: Counter[str] = Counter()
    citing: dict[str, set[tuple[int, str, str]]] = defaultdict(set)
    questions: dict[str, set[str]] = defaultdict(set)
    for a in answers:
        for c in a.cites:
            citations[c.publisher] += 1
            citing[c.publisher].add((a.run, a.qid, a.model))
            questions[c.publisher].add(a.qid)
    cards = []
    for p in sorted(citations, key=lambda p: (-citations[p], p)):
        fresh = pooled.get(p)
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
                cited_instead=cited_instead(data, p),
                improvement=tuple(_improvements(p, summary, st)),
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
    """Strip scheme, user info, `www.`, path, query and port; lower-case; IDN shown as Unicode."""
    q = query.strip()
    try:
        host = urlsplit(q if "//" in q else f"//{q}").hostname or ""
    except ValueError:
        return ""
    host = host.removeprefix("www.").rstrip(".").lower()
    try:
        return host.encode("ascii").decode("idna") if "xn--" in host else host
    except UnicodeError:
        return host


def _intents(cards: Sequence[DomainCard]) -> set[str]:
    return {k.split("/")[0] for c in cards for k in c.share_by_intent}


def lookup(
    query: str,
    cards: Sequence[DomainCard],
    answers: int,
    intent: str | None = None,
) -> DomainCard | NotCited:
    """The card for the publisher `query` maps to, through the extractor's own `publisher_of`;
    else a not-cited result naming the study's `answers` and the top publishers for `intent`.
    An intent the study does not have raises ValueError."""
    if intent is not None and intent not in _intents(cards):
        raise ValueError(f"unknown intent {intent!r}; this study has {sorted(_intents(cards))}")
    host = normalise(query)
    publisher = None
    if host and "." in host and " " not in host:
        try:
            publisher = publisher_of(host)[0]
        except UrlError:
            publisher = None
    by = {c.publisher: c for c in cards}
    if publisher in by:
        return by[publisher]
    if intent:

        def k_for(c: DomainCard) -> int:
            return sum(
                (s.k or 0) for key, s in c.share_by_intent.items() if key.startswith(f"{intent}/")
            )

        top = tuple(
            c.publisher for c in sorted(cards, key=lambda c: (-k_for(c), c.publisher)) if k_for(c)
        )
    else:
        top = tuple(c.publisher for c in cards)
    if publisher is None:
        message = f"{query.strip()!r} is not a web address citewatch can look up."
    else:
        message = f"{publisher} was not cited in any of the {answers} answers in this study."
    return NotCited(
        query=query,
        publisher=publisher,
        answers=answers,
        message=message,
        top_for_intent=top[:TOP_FOR_INTENT],
    )
