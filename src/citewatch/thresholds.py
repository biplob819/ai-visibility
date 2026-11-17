"""Check a study's threshold rules against its summary (THR-01, OWNER D-65).

Each rule's selector (see `citewatch.schemas.thresholds`) must name a row of the summary; a
selector that matches nothing raises `ThresholdError`, so a typo is never read as a pass. The
one exception is a share selector for a publisher that no answer cited: it reads as 0 (point,
lo and hi), so a rule like "our share stays at least 5%" fails when the site drops out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

from citewatch.schemas import Interval, StudySummary, ThresholdRule
from citewatch.schemas.thresholds import Selector


class ThresholdError(ValueError):
    """A selector names no row of the summary."""


@dataclass(frozen=True)
class RuleResult:
    metric: str
    op: str
    bound: float
    on: str
    severity: str
    value: float
    n: int
    passed: bool
    name: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def describe(self) -> str:
        label = f"{self.name} ({self.metric})" if self.name else self.metric
        side = "below" if self.op == ">=" else "above"
        extra = f"; {self.detail}" if self.detail else ""
        return (
            f"{label}: {self.on} {self.value:.4g} is {side} the bound {self.op} {self.bound:g}"
            f" (n={self.n}){extra}"
        )


def _one(rows: list[Interval], sel: Selector) -> Interval:
    if not rows:
        raise ThresholdError(f"selector {sel.text!r} matches no row in summary.json")
    if len(rows) > 1:  # the summary format keeps one row per scope; never pick one silently
        raise ThresholdError(f"selector {sel.text!r} matches {len(rows)} rows in summary.json")
    return rows[0]


def resolve(summary: StudySummary, sel: Selector) -> tuple[Interval, str | None]:
    """The interval a selector names, and a note when it was filled in (an uncited publisher)."""
    if sel.family == "coverage":
        return summary.coverage, None
    if sel.family == "share":
        scope = [
            r
            for r in summary.share
            if r.kind == sel.kind and r.model == sel.model and r.run == sel.run
            if r.intent == sel.intent
        ]
        hit = [r.share for r in scope if r.publisher.lower() == sel.publisher]
        if not hit and scope:
            n = scope[0].share.n
            return Interval(point=0.0, lo=0.0, hi=0.0, n=n, k=0), "not cited in this scope"
        return _one(hit, sel), None
    if sel.family == "citations":
        rows = [
            r.unique_per_answer
            for r in summary.citations
            if r.model == sel.model and r.run == sel.run and r.intent == sel.intent
        ]
        return _one(rows, sel), None
    if sel.family == "concentration":
        rows = [
            r.top10_share
            for r in summary.concentration
            if r.model == sel.model and r.run == sel.run
        ]
        return _one(rows, sel), None
    if sel.family == "stale":
        rows = [
            r.rate
            for r in summary.stale
            if r.definition == sel.kind and r.model == sel.model and r.intent == sel.intent
        ]
        return _one(rows, sel), None
    if sel.family == "support":
        rows = [
            r.support_rate for r in summary.support if r.judge == sel.judge and r.model == sel.model
        ]
        return _one(rows, sel), None
    if sel.family == "date_accuracy":
        rows = [
            r.within_7_days if sel.kind == "within_7_days" else r.exact
            for r in summary.date_accuracy
            if r.source == sel.source
        ]
        return _one(rows, sel), None
    raise ThresholdError(f"unknown metric selector {sel.text!r}")  # parse_selector prevents it


def check(rule: ThresholdRule, summary: StudySummary) -> RuleResult:
    interval, detail = resolve(summary, rule.selector)
    value = float(getattr(interval, rule.on))
    passed = value >= rule.bound if rule.op == ">=" else value <= rule.bound
    return RuleResult(
        metric=rule.metric,
        op=rule.op,
        bound=rule.bound,
        on=rule.on,
        severity=rule.severity,
        value=value,
        n=interval.n,
        passed=passed,
        name=rule.name,
        detail=detail,
    )


def check_all(rules: Sequence[ThresholdRule], summary: StudySummary) -> list[RuleResult]:
    """Every rule's result, in the order written. Raises ThresholdError on the first selector
    that names nothing, before any result is reported."""
    return [check(r, summary) for r in rules]
