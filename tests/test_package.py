import subprocess
import sys
import tomllib

import pytest

import citewatch
from citewatch import cli
from harness_lib import ROOT


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"citewatch {citewatch.__version__}"


@pytest.mark.contract
def test_pyproject_metadata():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = meta["project"]
    assert project["name"] == "citewatch"
    assert project["license"] == "MIT"
    assert project["requires-python"] == ">=3.11"
    assert project["scripts"]["citewatch"] == "citewatch.cli:main"
    assert meta["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/citewatch"]


def test_module_runs_as_a_script():
    p = subprocess.run(
        [sys.executable, "-m", "citewatch.cli", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0 and p.stdout.startswith("citewatch ")
