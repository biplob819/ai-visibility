"""OSS-07: the public API (docs/versioning.md) imports from the built wheel, installed in a
clean virtual environment with no extras, exactly as listed. The same build-and-install steps
as gate 10 (scripts/node_converge.py gate_build); no provider SDK is present."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import citewatch
import citewatch.schemas as schemas
from harness_lib import ROOT

TOP_LEVEL = {
    "NotCited",
    "UrlError",
    "__version__",
    "canonical_url",
    "lookup",
    "publisher_of",
    "read_cards",
    "schemas",
}
SCHEMAS = {
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
    "Improvement",
    "Interval",
    "OverdueRow",
    "OverlapRow",
    "PageMeta",
    "Selector",
    "ShareRow",
    "StabilityRow",
    "StaleRow",
    "StudyConfig",
    "StudyQuestion",
    "StudySummary",
    "SupportRow",
    "SupportVerdict",
    "ThresholdRule",
    "UserLocation",
    "count_words",
    "load_questions",
    "load_study_config",
    "parse_selector",
    "provider_of",
}

PROBE = r"""
import importlib.util, json, sys
import citewatch
from citewatch import (
    NotCited, UrlError, canonical_url, lookup, publisher_of, read_cards, schemas,
)
from citewatch.cards import lookup as cards_lookup
from citewatch.extract.urls import canonical_url as urls_canonical
import citewatch.schemas as s

card = s.DomainCard.model_validate_json(open(sys.argv[1], encoding="utf-8").read())
hit = lookup("https://" + card.publisher + "/x", [card], answers=10)
miss = lookup("https://unknown-site.org/", [card], answers=10)
try:
    canonical_url("not a url")
    bad = None
except UrlError as exc:
    bad = type(exc).__name__
print(json.dumps({
    "top": sorted(citewatch.__all__),
    "schemas": sorted(s.__all__),
    "missing": [n for n in s.__all__ if not hasattr(s, n)],
    "same": cards_lookup is lookup and urls_canonical is canonical_url,
    "canonical": canonical_url("HTTPS://WWW.NHS.uk/a?utm_source=x#top"),
    "publisher": list(publisher_of("https://www.nhs.uk/conditions/")),
    "hit": hit.publisher == card.publisher,
    "miss": isinstance(miss, NotCited),
    "bad": bad,
    "file": citewatch.__file__,
    "extras": [m for m in ("anthropic", "openai", "evalkit") if importlib.util.find_spec(m)],
}))
"""


def test_the_source_tree_exposes_the_same_names():
    assert set(citewatch.__all__) == TOP_LEVEL
    assert set(schemas.__all__) == SCHEMAS
    for name in TOP_LEVEL - {"__version__"}:
        assert getattr(citewatch, name) is not None
    assert citewatch.lookup is __import__("citewatch.cards").cards.lookup
    with pytest.raises(AttributeError):
        _ = citewatch.not_public  # type: ignore[attr-defined]


def test_import_citewatch_stays_light():
    """The re-exports load on first use: `import citewatch` (and so the CLI's --version)
    pulls in neither the extractor nor the cards module."""
    code = (
        "import sys, citewatch; print(sorted(m for m in sys.modules if m.startswith('citewatch')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    assert "citewatch.cards" not in out and "citewatch.extract" not in out


def _bin(venv: Path, name: str) -> Path:
    return (
        venv
        / ("Scripts" if os.name == "nt" else "bin")
        / (name + (".exe" if os.name == "nt" else ""))
    )


def _run(cmd: list[str | Path], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # uv would warn
    return subprocess.run(
        [str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, timeout=600, env=env
    )


@pytest.mark.contract
def test_the_built_wheel_imports_exactly_the_public_api(tmp_path):
    if not shutil.which("uv"):
        pytest.skip("uv is not installed (gate 10 needs it too)")
    dist = tmp_path / "dist"
    p = _run(["uv", "build", "--wheel", "--out-dir", dist], ROOT)
    assert p.returncode == 0, p.stdout + p.stderr
    (wheel,) = dist.glob("citewatch-*.whl")
    venv = tmp_path / "venv"
    p = _run(["uv", "venv", "-q", "--python", sys.executable, venv], tmp_path)
    assert p.returncode == 0, p.stderr
    py = _bin(venv, "python")
    # the dependencies come from uv's cache, filled by `uv sync`: no network is needed
    p = _run(["uv", "pip", "install", "-q", "--offline", "--python", py, wheel], tmp_path)
    assert p.returncode == 0, p.stderr
    card = ROOT / "tests" / "fixtures" / "v1" / "domain_card.json"
    p = _run([py, "-I", "-c", PROBE, card], tmp_path)  # -I: the source tree is not on the path
    assert p.returncode == 0, p.stderr
    got = json.loads(p.stdout)
    assert set(got["top"]) == TOP_LEVEL
    assert set(got["schemas"]) == SCHEMAS and got["missing"] == []
    assert got["same"] and got["hit"] and got["miss"] and got["bad"] == "UrlError"
    assert got["canonical"] == "https://www.nhs.uk/a"
    assert got["publisher"] == ["nhs.uk", None]
    assert str(venv) in got["file"]  # the installed wheel, not the source tree
    assert got["extras"] == []  # no extras: the public API needs no provider SDK
