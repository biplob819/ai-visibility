"""Shared base model and strict field types for every citewatch schema.

Adapted from EvalKit's schema base (same author, MIT). Models are deeply immutable: list
fields are tuples and dict fields become `FrozenDict`, so an object's JSON is identical from
the moment it is stored to the moment it is read back (EvalKit L-8, L-9).
"""

from __future__ import annotations

import copy
import datetime as dt
import re
from collections.abc import Iterator, Mapping
from typing import Annotated, Any, NoReturn, TypeVar
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

SCHEMA_VERSION = "1.0"
VERSION_PATTERN = r"^\d+\.\d+$"


class FrozenDict(dict):
    """A dict that refuses mutation and can be hashed."""

    def _blocked(self, *_: Any, **__: Any) -> NoReturn:
        raise TypeError("citewatch schema objects are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _blocked  # type: ignore[assignment]
    __ior__ = _blocked  # type: ignore[assignment]

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(frozenset(self.items()))

    # pickle and deepcopy rebuild a dict subclass with __setitem__, which is blocked; rebuild
    # from a plain dict instead (multiprocessing, caching and model_copy(deep=True) need this)
    def __reduce__(self) -> tuple[type[FrozenDict], tuple[dict[Any, Any]]]:
        return (type(self), (dict(self),))

    def __copy__(self) -> FrozenDict:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenDict:
        return type(self)({copy.deepcopy(k, memo): copy.deepcopy(v, memo) for k, v in self.items()})

    def __iter__(self) -> Iterator[Any]:
        return super().__iter__()


def _freeze_mapping(value: Mapping[Any, Any]) -> FrozenDict:
    return FrozenDict(value)


# Strict scalars: no bool-as-int, no "5"-as-5, no NaN or infinity.
NonNegInt = Annotated[int, Field(ge=0, strict=True)]
PosInt = Annotated[int, Field(ge=1, strict=True)]
# strict floats: no bools, no numeric strings (ints are fine)
NonNegFloat = Annotated[float, Field(ge=0.0, allow_inf_nan=False, strict=True)]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False, strict=True)]
NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
HexHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16,64}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Run = Annotated[int, Field(ge=0, le=2, strict=True)]  # 0 = smoke, 1 and 2 = study runs


def _utc(v: dt.datetime) -> dt.datetime:
    if v.utcoffset() != dt.timedelta(0):
        raise ValueError("timestamps must be UTC (offset +00:00 or Z)")
    return v


Timestamp = Annotated[AwareDatetime, AfterValidator(_utc)]  # aware and UTC, so dates agree

V = TypeVar("V")
FrozenMap = Annotated[dict[str, V], AfterValidator(_freeze_mapping)]

PROVIDER_PREFIXES = {"claude-": "anthropic", "gpt-": "openai"}


def provider_of(model: str) -> str:
    """The provider whose runner serves this model id; ValueError when none does."""
    for prefix, provider in PROVIDER_PREFIXES.items():
        if model.startswith(prefix) and len(model) > len(prefix):
            return provider
    raise ValueError(
        f"model {model!r} has no supported provider (ids start with "
        + " or ".join(repr(p) for p in PROVIDER_PREFIXES)
        + ")"
    )


def _check_model_id(v: str) -> str:
    provider_of(v)
    return v


ModelId = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9.\-]*$"), AfterValidator(_check_model_id)
]


def canonical_problems(url: str) -> list[str]:
    """Invariants a canonical URL must satisfy (the full canonicaliser lands in A2.1)."""
    problems = []
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return ["no whitespace or control characters allowed"]  # urlsplit strips some silently
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        return [f"not a URL ({exc})"]
    if url.split(":", 1)[0] not in ("http", "https"):  # urlsplit lower-cases the scheme itself
        problems.append("scheme must be http or https, in lower case")
    if "@" in parts.netloc:
        problems.append("no user info allowed")
    if not parts.hostname:
        problems.append("no host")
    elif (
        parts.netloc.split("@")[-1].split(":")[0]
        != parts.netloc.split("@")[-1].split(":")[0].lower()
    ):
        problems.append("host must be lower case")
    if parts.fragment or url.endswith("#"):
        problems.append("no fragment allowed")
    return problems


# A sentence end followed by a new sentence (space, then an opening mark or a capital letter), so
# abbreviations like "U.K. guidance" and "e.g. brisk walking" do not count as two sentences.
SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s+[\"'(\[]?[A-Z0-9]")


class Model(BaseModel):
    """Frozen, strict base: unknown fields are errors, objects are immutable, floats finite."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Versioned(Model):
    """A top-level file record that carries the results-format version. It is required."""

    schema_version: Annotated[str, StringConstraints(pattern=VERSION_PATTERN)]

    @field_validator("schema_version")
    @classmethod
    def _same_major(cls, v: str) -> str:
        if v.split(".", 1)[0] != SCHEMA_VERSION.split(".", 1)[0]:
            raise ValueError(
                f"results format {v} is not compatible with this citewatch "
                f"(expects {SCHEMA_VERSION.split('.')[0]}.x)"
            )
        return v
