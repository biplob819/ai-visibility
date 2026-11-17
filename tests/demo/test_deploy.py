"""DEM-04 preparation: the Streamlit Community Cloud files are in step with the package, and
the deploy guide names every secret the page reads. (The deploy itself is the owner's step.)"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib

from packaging.requirements import Requirement

from citewatch.demo import settings as S
from harness_lib import ROOT

REQS = ROOT / "demo" / "requirements.txt"
README = ROOT / "demo" / "README.md"


def _requirements() -> list[Requirement]:
    lines = [ln.split("#")[0].strip() for ln in REQS.read_text(encoding="utf-8").splitlines()]
    return [Requirement(ln) for ln in lines if ln]


def _locked() -> dict[str, set[str]]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for p in lock["package"]:
        out.setdefault(p["name"], set()).add(p["version"])
    return out


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_requirements_cover_core_and_the_demo_extras():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    needed = {
        _norm(Requirement(r).name)
        for r in [
            *project["dependencies"],
            *project["optional-dependencies"]["demo"],
            *project["optional-dependencies"]["anthropic"],
            *project["optional-dependencies"]["openai"],
        ]
    }
    listed = {_norm(r.name) for r in _requirements()}
    assert needed == listed


def test_requirements_are_pinned_to_the_lockfile():
    locked = _locked()
    for r in _requirements():
        (spec,) = r.specifier
        assert spec.operator == "==", r
        assert spec.version in locked[_norm(r.name)], f"{r} is not the locked version"


def test_pyproject_demo_extra_is_optional():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    core = {_norm(Requirement(r).name) for r in project["dependencies"]}
    assert not core & {"streamlit", "webauthn"}


def test_readme_names_every_secret_and_the_entrypoint():
    text = README.read_text(encoding="utf-8")
    for name in S.ALL_SECRETS:
        assert name in text, name
    assert "demo/app.py" in text and "make_code_hash" in text
    assert "share.streamlit.io" in text


def test_local_secrets_and_store_are_git_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".streamlit/secrets.toml" in ignored and ".demo-state/" in ignored


def test_make_code_hash_runs_as_a_module():
    out = subprocess.run(
        [sys.executable, "-m", "citewatch.demo.make_code_hash"],
        input="123\n123\n",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode == 2 and "12 to 32 digits" in out.stdout
    assert "123" not in out.stdout.replace("12 to 32", "")


def test_streamlit_config_hides_error_details():
    """Next to the entrypoint, where Streamlit reads script-level config (also on Community
    Cloud): an uncaught error shows no exception text or traceback in the browser."""
    cfg = tomllib.loads((ROOT / "demo" / ".streamlit" / "config.toml").read_text("utf-8"))
    assert cfg["client"]["showErrorDetails"] == "none"


def test_readme_documents_the_registration_lockout_reset():
    text = (ROOT / "demo" / "README.md").read_text(encoding="utf-8")
    assert "citewatch:demo:regcode:all:" in text and "12 to 32 digits" in text
