"""Study configuration and question loading (Tech Spec §4, §7.1, SCH-05).

A study is a folder holding `study.yaml` and a questions JSONL. citewatch runs any study:
its own questions, intents, country and supported models (OWNER D-23). The politeness floor
is not part of the config and cannot be loosened (D-25).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field, StringConstraints, ValidationError, field_validator, model_validator

from ._base import FrozenMap, Model, ModelId, NonBlank, NonNegFloat, Slug
from ._iso import COUNTRIES, HINTS
from .study import StudyQuestion

REQUIRED_SEEDS = ("order", "support_sample", "hand_sample", "bootstrap")
# example.org/.com/.net, localhost and the reserved test TLDs are never real contacts
PLACEHOLDER = re.compile(
    r"(?:^|[/@.])(?:example\.(?:org|com|net)|localhost)(?:$|[/:])"
    r"|\.(?:example|test|invalid|localhost)(?:$|[/:])",
    re.I,
)
# a URL with a real host, or an email address
CONTACT = re.compile(
    r"https?://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}"
    r"|[^\s@()<>]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}",
    re.I,
)


class ConfigError(ValueError):
    """A study file is invalid; the message names the file and the field or line."""


class UserLocation(Model):
    type: Literal["approximate"] = "approximate"
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]  # ISO 3166-1 alpha-2

    @field_validator("country")
    @classmethod
    def _assigned(cls, v: str) -> str:
        if v not in COUNTRIES:
            hint = f"; use {HINTS[v]!r}" if v in HINTS else ""
            raise ValueError(f"{v!r} is not an ISO 3166-1 alpha-2 country code{hint}")
        return v

    city: NonBlank | None = None
    region: NonBlank | None = None
    timezone: NonBlank | None = None


class StudyConfig(Model):
    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9\-]*$")]
    questions_path: NonBlank  # relative to the study folder
    intents: tuple[Slug, ...]
    ts_reasons: tuple[Slug, ...] | None = None  # the rubric's time-sensitive clauses; None = any
    models: tuple[ModelId, ...]
    effort: Literal["low", "medium", "high"]
    user_location: UserLocation
    max_searches: Annotated[int, Field(ge=1, le=5, strict=True)]
    word_limit: Annotated[int, Field(ge=1, strict=True)]
    stale_days: Annotated[int, Field(ge=1, strict=True)]
    seeds: FrozenMap[Annotated[int, Field(strict=True)]]
    max_cost_usd: NonNegFloat | None = None
    user_agent: NonBlank

    @field_validator("intents", "models")
    @classmethod
    def _unique_non_empty(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("must not be empty")
        dupes = sorted({x for x in v if v.count(x) > 1})
        if dupes:
            raise ValueError(f"duplicates: {dupes}")
        return v

    @field_validator("user_agent")
    @classmethod
    def _names_tool_and_contact(cls, v: str) -> str:
        # D-25 and §7.2: the agent names the tool and a contact; it cannot pose as a browser
        if not all(32 <= ord(c) < 127 for c in v):
            raise ValueError(
                "must be printable ASCII (an HTTP header value), no control characters"
            )
        if not re.match(r"^citewatch/\S+ ", v):
            raise ValueError("must start with 'citewatch/<version> ' so sites can see the tool")
        m = CONTACT.search(v)
        if not m:
            raise ValueError(
                "must name a contact: a URL with a host (https://...) or an email address"
            )
        if PLACEHOLDER.search(m.group(0)):
            raise ValueError(
                f"{m.group(0)!r} is a placeholder; name a real project page or address that "
                "site owners can use to reach you"
            )
        return v

    @model_validator(mode="after")
    def _seeds(self) -> StudyConfig:
        missing = [s for s in REQUIRED_SEEDS if s not in self.seeds]
        if missing:
            raise ValueError(f"seeds is missing {missing}")
        return self


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _no_duplicates(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ConfigError(f"duplicate key {key!r} (line {key_node.start_mark.line + 1})")
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


def _fmt(path: Path, exc: ValidationError) -> str:
    parts = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e["loc"]) or "(top level)"
        parts.append(f"{path}: {loc}: {e['msg']}")
    return "\n".join(parts)


def load_study_config(path: str | Path) -> StudyConfig:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")  # a BOM from Windows editors is fine
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read ({exc})") from exc
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: (top level): must be a mapping")
    try:
        return StudyConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_fmt(path, exc)) from exc


def load_questions(path: str | Path, config: StudyConfig) -> list[StudyQuestion]:
    """Questions from a JSONL file, each validated, intents declared, ids unique."""
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read ({exc})") from exc
    questions: list[StudyQuestion] = []
    seen: set[str] = set()
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            q = StudyQuestion.model_validate(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path}:{lineno}: not JSON ({exc.msg})") from exc
        except ValidationError as exc:
            raise ConfigError(_fmt(Path(f"{path}:{lineno}"), exc)) from exc
        if q.intent not in config.intents:
            raise ConfigError(
                f"{path}:{lineno}: intent {q.intent!r} is not declared in the study "
                f"(intents: {', '.join(config.intents)})"
            )
        if (
            q.ts_reason is not None
            and config.ts_reasons is not None
            and q.ts_reason not in config.ts_reasons
        ):
            raise ConfigError(
                f"{path}:{lineno}: ts_reason {q.ts_reason!r} is not in the study's rubric "
                f"(ts_reasons: {', '.join(config.ts_reasons)})"
            )
        if q.id in seen:
            raise ConfigError(f"{path}:{lineno}: duplicate question id {q.id!r}")
        seen.add(q.id)
        questions.append(q)
    if not questions:
        raise ConfigError(f"{path}: no questions")
    return questions
