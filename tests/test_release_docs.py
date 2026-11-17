"""OSS-04, OSS-09, OSS-01/02/08 wiring: the guides, the release README and the release flow."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_four_guides_cover_what_oss04_asks():
    quick = (DOCS / "quickstart.md").read_text("utf-8")
    assert "report --example" in quick and "no keys" in quick.lower()
    own = (DOCS / "own-study.md").read_text("utf-8")
    for needle in ("questions.jsonl", "intents", "country", "models", "max_cost_usd", "init"):
        assert needle in own, needle
    dates = (DOCS / "dates.md").read_text("utf-8")
    assert "## Limits" in dates and "page age" in dates and "never guesses" in dates
    cost = (DOCS / "cost.md").read_text("utf-8")
    assert "--dry-run" in cost and "max_cost_usd" in cost and "$15.03" in cost


def test_the_guides_commands_exist_in_the_cli():
    from typer.main import get_command

    from citewatch.cli import app

    names = set(get_command(app).commands)  # type: ignore[attr-defined]
    for doc in ("quickstart.md", "own-study.md", "cost.md"):
        for cmd in re.findall(r"citewatch (\w+)", (DOCS / doc).read_text("utf-8")):
            assert cmd in names or cmd in {"report", "ask"}, (doc, cmd)


def test_the_release_readme_has_screenshots_guides_and_one_links_table():
    """OSS-09: dashboard, CLI and (once deployed) demo screenshots; the guides; every link."""
    text = (ROOT / "README.md").read_text("utf-8")
    for shot in ("dashboard.png", "cli.png"):
        assert f"docs/assets/screenshots/{shot}" in text
        assert (ROOT / "docs" / "assets" / "screenshots" / shot).is_file()
    assert "## Guides" in text and "## Links" in text and "## Install" in text
    for target in (
        "pypi.org/project/citewatch",
        "biplob819.github.io/ai-visibility",
        "signal-spec.pdf",
        "DATA_CARD.md",
        "preregistration.md",
        "deviations.md",
        "decisions.md",
        "evalkit",
    ):
        assert target in text, target


def test_every_local_link_in_the_readme_and_docs_resolves():
    mod = _script("check_links")
    found = mod.links()
    assert len(found) > 40
    assert [p for s, u in found if (p := mod.local_problem(s, u))] == []


def test_release_publishes_by_trusted_publishing_on_a_matching_tag():
    """OSS-01, OSS-08: a v* tag that equals the package version publishes; no token stored."""
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8"))
    on = flow.get("on") or flow.get(True)
    assert on["push"]["tags"] == ["v*.*.*"]
    publish = flow["jobs"]["publish"]
    assert (
        publish["permissions"] == {"id-token": "write"} and publish["environment"]["name"] == "pypi"
    )
    assert any("pypa/gh-action-pypi-publish" in str(s.get("uses")) for s in publish["steps"])
    build = " ".join(str(s.get("run", "")) for s in flow["jobs"]["build"]["steps"])
    assert 'test "v${version}" = "${GITHUB_REF_NAME}"' in build and "pytest" in build
    step = next(s for s in publish["steps"] if "pypi-publish" in str(s.get("uses")))
    assert not step.get("with"), "trusted publishing passes no password or API token"
    assert "secrets." not in (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")


def test_the_published_package_is_smoke_tested_on_three_systems():
    """OSS-02: after release, uvx --version and report --example on Linux, macOS, Windows."""
    flow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "published-smoke.yml").read_text("utf-8")
    )
    job = flow["jobs"]["smoke"]
    assert set(job["strategy"]["matrix"]["os"]) == {
        "ubuntu-latest",
        "macos-latest",
        "windows-latest",
    }
    runs = " ".join(str(s.get("run", "")) for s in job["steps"])
    assert 'uvx "citewatch==${VERSION}" --version' in runs and "report --example" in runs


def test_the_wheel_metadata_has_no_url_dependency(tmp_path):
    """B4.5 pass 1 (H1): PyPI refuses any Requires-Dist with a direct URL, extras included."""
    import shutil
    import subprocess
    import zipfile

    assert shutil.which("uv"), "uv is required to build the wheel"
    p = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stderr
    (wheel,) = tmp_path.glob("citewatch-*.whl")
    with zipfile.ZipFile(wheel) as z:
        meta = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
        requires = [x for x in z.read(meta).decode().splitlines() if x.startswith("Requires-Dist:")]
    assert requires and not [r for r in requires if " @ " in r], requires


def test_the_link_checker_sees_bare_urls_and_autolinks():
    mod = _script("check_links")
    urls = {u for _, u in mod.links()}
    assert "https://pypi.org/project/citewatch/" in urls  # a bare URL in the README links table
