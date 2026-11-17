"""Lookup mode (DEM-01, US7): a domain box over the bundled domain cards, and a top-ten picker
by intent. Reads `domain_cards.json` only; it never calls a model.

The HTML here is built from the cards' own fields, every value made inert for markdown and
HTML by `citewatch.demo.markup` (one line, syntax characters as character references). The
cards hold shares, dates, publishers and improvement rows; they hold no answer text (D-17).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from citewatch.cards import NotCited, lookup, read_cards
from citewatch.demo.markup import link, text
from citewatch.schemas import DomainCard
from citewatch.schemas.summary import Interval

TOP_N = 10


@dataclass(frozen=True)
class Bundle:
    cards: tuple[DomainCard, ...]
    answers: int  # answers in the scored runs, the denominator of "not cited in any of N"
    intents: tuple[str, ...]


@dataclass(frozen=True)
class TopRow:
    rank: int
    publisher: str
    answers_citing: int  # answers to this intent (all models and runs) that cite the publisher
    answers: int  # answers to this intent

    @property
    def share(self) -> float:
        return self.answers_citing / self.answers if self.answers else 0.0


def study_answers(cards: Sequence[DomainCard]) -> int:
    """Scored answers: for each model and run, the largest presence denominator any card
    shows (every card's n for that model/run is the same count of valid answers)."""
    per: dict[str, int] = {}
    for c in cards:
        for key, s in c.share_by_model.items():
            per[key] = max(per.get(key, 0), s.n)
    return sum(per.values())


def load_bundle(path: Path) -> Bundle:
    cards = tuple(read_cards(path))
    intents = tuple(sorted({k.split("/")[0] for c in cards for k in c.share_by_intent}))
    return Bundle(cards=cards, answers=study_answers(cards), intents=intents)


def find(bundle: Bundle, query: str, intent: str | None = None) -> DomainCard | NotCited:
    """The card for a typed domain or URL, or a not-cited result naming the top publishers for
    `intent` (the shared `citewatch.cards.lookup`, so the extractor's `publisher_of` decides)."""
    return lookup(query, bundle.cards, bundle.answers, intent=intent)


def _intent_counts(card: DomainCard, intent: str | None) -> tuple[int, int]:
    shares = (
        card.share_by_model.values()
        if intent is None
        else [s for k, s in card.share_by_intent.items() if k.split("/")[0] == intent]
    )
    return sum(s.k or 0 for s in shares), sum(s.n for s in shares)


def top_ten(bundle: Bundle, intent: str | None = None, n: int = TOP_N) -> list[TopRow]:
    """The publishers cited in the most answers to `intent` (all intents when None), pooled
    over models and runs; ties by name."""
    if intent is not None and intent not in bundle.intents:
        raise ValueError(f"unknown intent {intent!r}; this study has {list(bundle.intents)}")
    rows = []
    denominator = 0
    for c in bundle.cards:
        k, total = _intent_counts(c, intent)
        denominator = max(denominator, total)
        if k:
            rows.append((c.publisher, k))
    rows.sort(key=lambda r: (-r[1], r[0]))
    return [TopRow(i, p, k, denominator) for i, (p, k) in enumerate(rows[:n], start=1)]


def label(intent: str) -> str:
    return intent.replace("_", " ")


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _share(s: Interval) -> str:
    return f"{_pct(s.point)} ({_pct(s.lo)}–{_pct(s.hi)}), {s.k or 0} of {s.n} answers"


def card_html(card: DomainCard) -> str:
    """A domain card: shares by model and run, freshness, who was cited instead, and the
    improvement rows with their fixes and examples."""
    h = [f"<div class='cw-card'><h3>{text(card.publisher)}</h3>"]
    questions = len(card.questions_citing)
    h.append(
        f"<p>Cited {card.citations} times in {card.answers_citing} answers, "
        f"on {questions} question{'s' if questions != 1 else ''}.</p>"
    )
    h.append("<h4>Share of answers citing it, by model</h4><table class='cw-shares'>")
    h.append("<tr><th>Model</th><th>Run</th><th>Share (95% interval), count</th></tr>")
    for key in sorted(card.share_by_model):
        model, _, run = key.partition("/")
        h.append(
            f"<tr><td>{text(model)}</td><td>{text(run.removeprefix('run-'))}</td>"
            f"<td>{text(_share(card.share_by_model[key]))}</td></tr>"
        )
    h.append("</table>")
    if card.median_freshness_lag_days is not None:
        h.append(
            f"<p><b>Freshness:</b> median {card.median_freshness_lag_days:.0f} days between a "
            f"cited page's date and the answer, over {card.dated_pages} dated pages.</p>"
        )
    else:
        h.append("<p><b>Freshness:</b> no cited page had a date citewatch could read.</p>")
    if card.cited_instead:
        h.append(
            "<p><b>Cited instead</b> (in answers to the same questions that left it out): "
            + ", ".join(text(p) for p in card.cited_instead)
            + "</p>"
        )
    if card.improvement:
        h.append("<h4>What could help</h4><ul class='cw-improve'>")
        for row in card.improvement:
            items = "".join(f"<li>{link(e)}</li>" for e in row.examples)
            examples = (
                f"<details><summary>Examples</summary><ul>{items}</ul></details>" if items else ""
            )
            h.append(
                f"<li><p>{text(row.finding)}</p><p><b>Fix:</b> {text(row.fix)}</p>{examples}</li>"
            )
        h.append("</ul>")
    else:
        h.append("<p>No improvement rows: nothing in the data points to a fix.</p>")
    h.append("</div>")
    return "".join(h)


def not_cited_html(result: NotCited, intent: str | None) -> str:
    h = [f"<div class='cw-card'><p>{text(result.message)}</p>"]
    if result.top_for_intent:
        where = f" on {text(label(intent))} questions" if intent else ""
        h.append(f"<p>Most-cited publishers{where}:</p><ol>")
        h.extend(f"<li>{text(p)}</li>" for p in result.top_for_intent)
        h.append("</ol>")
    h.append("</div>")
    return "".join(h)
