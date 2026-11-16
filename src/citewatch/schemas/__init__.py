"""citewatch results format v1: every record the study writes or reads (Tech Spec §4)."""

from ._base import SCHEMA_VERSION, FrozenDict, provider_of
from .cards import DomainCard, HandDateLabel, SupportVerdict
from .config import ConfigError, StudyConfig, UserLocation, load_questions, load_study_config
from .pages import DateCandidate, PageMeta
from .study import AnswerRecord, Citation, ConsultedSource, StudyQuestion, count_words
from .summary import (
    AccuracyRow,
    CitationsRow,
    ComparisonRow,
    ConcentrationRow,
    FreshnessRow,
    Interval,
    OverdueRow,
    OverlapRow,
    ShareRow,
    StabilityRow,
    StaleRow,
    StudySummary,
    SupportRow,
)

__all__ = [
    "SCHEMA_VERSION",
    "AccuracyRow",
    "AnswerRecord",
    "Citation",
    "CitationsRow",
    "ComparisonRow",
    "ConcentrationRow",
    "ConfigError",
    "ConsultedSource",
    "DateCandidate",
    "DomainCard",
    "FreshnessRow",
    "FrozenDict",
    "HandDateLabel",
    "Interval",
    "OverdueRow",
    "OverlapRow",
    "PageMeta",
    "ShareRow",
    "StabilityRow",
    "StaleRow",
    "StudyConfig",
    "StudyQuestion",
    "StudySummary",
    "SupportRow",
    "SupportVerdict",
    "UserLocation",
    "count_words",
    "load_questions",
    "load_study_config",
    "provider_of",
]
