"""Metric rows and the study summary (Tech Spec §4, §6, SCH-03)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ._base import (
    FiniteFloat,
    FrozenMap,
    HexHash,
    Model,
    ModelId,
    NonBlank,
    NonNegFloat,
    NonNegInt,
    Run,
    Sha256,
    Slug,
    Timestamp,
    Versioned,
)


class Interval(Model):
    point: FiniteFloat
    lo: FiniteFloat
    hi: FiniteFloat
    n: NonNegInt  # count beside every percentage (FR9)
    k: NonNegInt | None = None  # numerator when the metric is a share

    @model_validator(mode="after")
    def _ordered(self) -> Interval:
        if not self.lo <= self.point <= self.hi:
            raise ValueError(
                f"interval must satisfy lo <= point <= hi, got {self.lo}, {self.point}, {self.hi}"
            )
        if self.k is not None and self.k > self.n:
            raise ValueError(f"k ({self.k}) cannot exceed n ({self.n})")
        return self


class ShareRow(Model):
    publisher: NonBlank
    model: ModelId
    intent: Slug | None = None
    run: Run
    kind: Literal["presence", "weighted", "consulted"]
    share: Interval


class ConcentrationRow(Model):
    model: ModelId
    run: Run
    top10_share: Interval
    hhi: NonNegFloat


class FreshnessRow(Model):
    publisher: NonBlank
    model: ModelId | None = None
    dated_pages: NonNegInt
    median_lag_days: NonNegFloat | None = None
    iqr_days: tuple[NonNegFloat, NonNegFloat] | None = None
    modified_after_answer: NonNegInt

    @model_validator(mode="after")
    def _lag(self) -> FreshnessRow:
        if (self.median_lag_days is None) != (self.dated_pages == 0):
            raise ValueError("median_lag_days is set exactly when there are dated pages")
        if self.iqr_days is not None and self.iqr_days[0] > self.iqr_days[1]:
            raise ValueError("iqr_days must be (low, high)")
        return self


class StaleRow(Model):
    model: ModelId
    intent: Slug | None = None
    definition: Literal["primary", "secondary"]
    rate: Interval
    undated: NonNegInt


class OverlapRow(Model):
    intent: Slug | None = None
    run: Run | None = None
    kind: Literal["cross_model", "self", "normalised", "pooled_top20"]
    model: ModelId | None = None
    value: Interval

    @model_validator(mode="after")
    def _model_only_for_self(self) -> OverlapRow:
        if (self.kind == "self") != (self.model is not None):
            raise ValueError("model is set exactly for kind 'self'")
        return self


class StabilityRow(Model):
    model: ModelId
    publisher: NonBlank | None = None
    metric: Literal["self_jaccard", "share_change"]
    value: Interval


class AccuracyRow(Model):
    source: NonBlank  # "overall" or a date source
    within_7_days: Interval
    exact: Interval


class SupportRow(Model):
    model: ModelId
    judge: NonBlank
    support_rate: Interval
    hand_agreement: NonNegFloat | None = None
    kappa: Interval | None = None


class CitationsRow(Model):
    """Citations per valid answer (§6.1): unique canonical URLs, with the raw block count."""

    model: ModelId
    intent: Slug | None = None
    run: Run
    unique_per_answer: Interval
    raw_per_answer: NonNegFloat
    zero_citation: NonNegInt


class OverdueRow(Model):
    """NHS overdue (§6.3): cited pages whose `review_due` is before the answer."""

    model: ModelId | None = None
    share: Interval


class ComparisonRow(Model):
    """A paired model comparison of presence share for one publisher (§6.6)."""

    publisher: NonBlank
    run: Run
    model_a: ModelId
    model_b: ModelId
    difference: Interval  # share(model_a) − share(model_b) over shared questions
    p_value: FiniteFloat
    p_holm: FiniteFloat
    separated: bool

    @model_validator(mode="after")
    def _p(self) -> ComparisonRow:
        if not (0 <= self.p_value <= 1 and self.p_value <= self.p_holm <= 1):
            raise ValueError("need 0 <= p_value <= p_holm <= 1")
        return self


class StudySummary(Versioned):
    runs: tuple[Run, ...]
    config_hash: HexHash
    questions_sha256: Sha256
    preregistration_sha256: Sha256
    share: tuple[ShareRow, ...] = ()
    citations: tuple[CitationsRow, ...] = ()
    concentration: tuple[ConcentrationRow, ...] = ()
    freshness: tuple[FreshnessRow, ...] = ()
    stale: tuple[StaleRow, ...] = ()
    overlap: tuple[OverlapRow, ...] = ()
    stability: tuple[StabilityRow, ...] = ()
    comparisons: tuple[ComparisonRow, ...] = ()
    nhs_overdue: tuple[OverdueRow, ...] = ()
    coverage: Interval
    date_accuracy: tuple[AccuracyRow, ...] = ()
    support: tuple[SupportRow, ...] = ()
    check_methods: FrozenMap[NonBlank] = Field(default_factory=dict)  # how each human check ran
    error_counts: FrozenMap[FrozenMap[NonNegInt]]
    spend_usd: NonNegFloat
    generated_at: Timestamp

    @model_validator(mode="after")
    def _runs(self) -> StudySummary:
        if (
            not self.runs
            or len(set(self.runs)) != len(self.runs)
            or list(self.runs) != sorted(self.runs)
        ):
            raise ValueError("runs must be non-empty, unique and sorted")
        return self
