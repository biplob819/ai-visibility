"""OSS-05, OSS-06, OSS-07 documents: responsible use (with the real floor values), no
telemetry, the community files and templates, and the versioning policy's public API."""

from __future__ import annotations

import ast
import re

import pytest
import yaml

import citewatch
from citewatch.fetch import client as client_mod
from citewatch.fetch import rate as rate_mod
from harness_lib import ROOT

DOCS = ROOT / "docs"


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# -- OSS-05 ---------------------------------------------------------------------------------


def test_responsible_use_states_purpose_b9_telemetry_and_privacy():
    doc = text("docs/responsible-use.md")
    assert "measures **sourcing**" in doc
    assert "**not** a tool for gaming AI answers" in doc and "B9" in doc
    assert "## No telemetry" in doc and "no analytics" in doc
    assert "## Privacy" in doc
    for stored in ("data/raw/", "results/", "**Not stored:** page HTML and page text"):
        assert stored in doc
    assert "only to these" in doc and "The AI providers you configure" in doc
    assert "The sites your answers cited" in doc


def test_responsible_use_quotes_the_real_floor():
    doc = text("docs/responsible-use.md")
    assert rate_mod.INTERVAL_S == 1.0 and "at most 1 request per second per host" in doc
    assert f"at most {rate_mod.MAX_IN_FLIGHT} requests in flight" in doc
    assert (
        f"at most {client_mod.MAX_RETRIES} ({client_mod.MAX_RETRIES + 1} requests per page)" in doc
    )
    assert "tests/fetch/test_politeness_floor.py" in doc


@pytest.mark.safety
def test_no_telemetry_only_the_fetcher_and_provider_runners_touch_the_network():
    """Static: the only network-capable imports are the fetcher (httpx), the provider runners
    (their SDKs) and the support judge (EvalKit, which calls the same providers)."""
    net = {"httpx", "socket", "urllib.request", "http.client", "requests", "aiohttp", "urllib3"}
    sdks = {"anthropic", "openai", "evalkit"}
    src = ROOT / "src" / "citewatch"
    found: dict[str, set[str]] = {}
    for path in sorted(src.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for n in names:
                root = n.split(".")[0]
                if n in net or root in net or root in sdks:
                    found.setdefault(path.relative_to(src).as_posix(), set()).add(root)
    assert found == {
        "fetch/client.py": {"httpx"},
        "fetch/keys.py": {"httpx"},  # URL encoding only
        "runners/anthropic_runner.py": {"anthropic"},
        "runners/openai_runner.py": {"openai"},
        "support/calibrate.py": {"evalkit"},  # statistics only, no calls
        "support/judge.py": {"evalkit"},
    }


# -- OSS-06 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel", "must"),
    [
        ("CONTRIBUTING.md", ["uv run pytest -q", "politeness floor", "No telemetry", "B9"]),
        ("SECURITY.md", ["security/advisories/new", "Supported versions", "robots.txt"]),
        ("CODE_OF_CONDUCT.md", ["Contributor Covenant, version 2.1", "## Enforcement"]),
        (".github/pull_request_template.md", ["uv run pytest -q", "politeness floor"]),
    ],
)
def test_community_files_exist_and_say_what_matters(rel, must):
    doc = text(rel)
    for phrase in must:
        assert phrase in doc, (rel, phrase)


@pytest.mark.parametrize("name", ["bug_report", "feature_request"])
def test_issue_templates_have_valid_front_matter(name):
    doc = text(f".github/ISSUE_TEMPLATE/{name}.md")
    m = re.match(r"^---\n(.*?)\n---\n", doc, re.S)
    assert m, "front matter"
    meta = yaml.safe_load(m.group(1))
    assert {"name", "about", "title", "labels"} <= set(meta)
    assert "SECURITY.md" in doc or "responsible-use" in doc


def test_community_links_resolve():
    for rel in ("CONTRIBUTING.md", "SECURITY.md", "docs/responsible-use.md", "docs/versioning.md"):
        base = (ROOT / rel).parent
        for target in re.findall(r"\]\(((?!https?://)[^)#]+)\)", text(rel)):
            assert (base / target).exists(), (rel, target)


# -- OSS-07 ---------------------------------------------------------------------------------


def test_the_versioning_policy_names_every_public_name():
    doc = text("docs/versioning.md")
    assert "Semantic Versioning" in doc and "tests/test_public_api.py" in doc
    for name in set(citewatch.__all__) - {"__version__"}:
        shown = "citewatch.schemas" if name == "schemas" else name
        assert re.search(rf"`{re.escape(shown)}[`(]", doc), name
    for module in ("citewatch.extract.urls", "citewatch.cards"):
        assert f"`{module}`" in doc
