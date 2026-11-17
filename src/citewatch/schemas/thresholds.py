"""Threshold rules in `study.yaml` (THR-01, OWNER D-65).

A rule names one interval in `results/summary.json` by a selector, compares one of its bounds
(`point`, `lo` or `hi`) with a number, and says whether a miss fails the run or only warns.
`citewatch score` checks the rules after writing the summary (see docs/thresholds.md).

Selector grammar (parts separated by `:`; `all`, or leaving the intent out, means the whole
study rather than one intent):

    coverage
    share:<presence|weighted|consulted>:<publisher>:<model>:run-<n>[:<intent>|all]
    citations:<model>:run-<n>[:<intent>|all]          unique cited URLs per answer
    concentration:<model>:run-<n>                     share of the top 10 publishers
    stale:<primary|secondary>:<model>[:<intent>|all]
    support:<judge>:<model>                           support rate by one judge
    date_accuracy:<source>[:within_7_days|exact]      default within_7_days
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import StringConstraints, field_validator, model_validator

from ._base import FiniteFloat, Model

FAMILIES = ("coverage", "share", "citations", "concentration", "stale", "support", "date_accuracy")
SHARE_KINDS = ("presence", "weighted", "consulted")
STALE_DEFINITIONS = ("primary", "secondary")
ACCURACY_MEASURES = ("within_7_days", "exact")
_RUN = re.compile(r"^run-([0-2])$")
_PART = re.compile(r"^[^\s:]+$")
USAGE = {
    "coverage": "coverage",
    "share": "share:<presence|weighted|consulted>:<publisher>:<model>:run-<n>[:<intent>]",
    "citations": "citations:<model>:run-<n>[:<intent>]",
    "concentration": "concentration:<model>:run-<n>",
    "stale": "stale:<primary|secondary>:<model>[:<intent>]",
    "support": "support:<judge>:<model>",
    "date_accuracy": "date_accuracy:<source>[:within_7_days|exact]",
}


@dataclass(frozen=True)
class Selector:
    """A parsed metric selector. `intent` None means the whole study."""

    family: str
    text: str
    kind: str | None = None  # share kind, stale definition or accuracy measure
    publisher: str | None = None
    model: str | None = None
    run: int | None = None
    intent: str | None = None
    judge: str | None = None
    source: str | None = None


def _run(part: str, text: str) -> int:
    m = _RUN.match(part)
    if not m:
        raise ValueError(f"selector {text!r}: {part!r} is not a run (use run-0, run-1 or run-2)")
    return int(m.group(1))


def _intent(parts: list[str]) -> str | None:
    if not parts or parts[0] == "all":
        return None
    return parts[0]


def parse_selector(text: str) -> Selector:
    """Parse a selector; ValueError names the selector and the form it should take."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("a metric selector must be a non-empty string")
    parts = text.strip().split(":")
    family, rest = parts[0], parts[1:]
    if family not in FAMILIES:
        raise ValueError(
            f"unknown metric selector {text!r}; it must start with one of {', '.join(FAMILIES)}"
        )
    bad = [p for p in rest if not _PART.match(p)]
    sizes = {
        "coverage": (0, 0),
        "share": (4, 5),
        "citations": (2, 3),
        "concentration": (2, 2),
        "stale": (2, 3),
        "support": (2, 2),
        "date_accuracy": (1, 2),
    }[family]
    if bad or not sizes[0] <= len(rest) <= sizes[1]:
        raise ValueError(f"unknown metric selector {text!r}; the form is {USAGE[family]}")
    if family == "coverage":
        return Selector("coverage", text)
    if family == "share":
        kind, publisher, model, run = rest[:4]
        if kind not in SHARE_KINDS:
            raise ValueError(
                f"selector {text!r}: share kind {kind!r} must be one of {', '.join(SHARE_KINDS)}"
            )
        return Selector(
            "share",
            text,
            kind=kind,
            publisher=publisher.lower(),
            model=model,
            run=_run(run, text),
            intent=_intent(rest[4:]),
        )
    if family == "citations":
        return Selector(
            "citations", text, model=rest[0], run=_run(rest[1], text), intent=_intent(rest[2:])
        )
    if family == "concentration":
        return Selector("concentration", text, model=rest[0], run=_run(rest[1], text))
    if family == "stale":
        if rest[0] not in STALE_DEFINITIONS:
            raise ValueError(
                f"selector {text!r}: stale definition {rest[0]!r} must be primary or secondary"
            )
        return Selector("stale", text, kind=rest[0], model=rest[1], intent=_intent(rest[2:]))
    if family == "support":
        return Selector("support", text, judge=rest[0], model=rest[1])
    measure = rest[1] if len(rest) > 1 else "within_7_days"
    if measure not in ACCURACY_MEASURES:
        raise ValueError(
            f"selector {text!r}: date accuracy measure {measure!r} must be within_7_days or exact"
        )
    return Selector("date_accuracy", text, kind=measure, source=rest[0])


class ThresholdRule(Model):
    """One rule: `metric` (a selector), `op` (">=" or "<="), `bound`, the interval end it is
    checked `on` (point, lo or hi; default point), and `severity` (fail or warn; default fail).

    YAML 1.1 reads a bare `on:` key as the boolean true, so that key is accepted as `on`."""

    metric: Annotated[str, StringConstraints(min_length=1)]
    op: Literal[">=", "<="]
    bound: FiniteFloat
    on: Literal["point", "lo", "hi"] = "point"
    severity: Literal["fail", "warn"] = "fail"
    name: Annotated[str, StringConstraints(min_length=1, pattern=r"\S")] | None = None

    @model_validator(mode="before")
    @classmethod
    def _yaml_on(cls, data: Any) -> Any:
        if isinstance(data, dict) and True in data:
            if "on" in data:
                raise ValueError("`on` is given twice")
            data = {("on" if k is True else k): v for k, v in data.items()}
        return data

    @field_validator("metric")
    @classmethod
    def _parses(cls, v: str) -> str:
        parse_selector(v)
        return v.strip()

    @property
    def selector(self) -> Selector:
        return parse_selector(self.metric)
