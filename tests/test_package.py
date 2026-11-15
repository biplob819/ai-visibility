import subprocess
import sys
import tomllib

import pytest

import visibility
from harness_lib import ROOT
from visibility import cli


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"visibility {visibility.__version__}"


@pytest.mark.contract
def test_pyproject_metadata():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = meta["project"]
    assert project["name"] == "ai-visibility"
    assert project["license"] == "MIT"
    assert project["requires-python"] == ">=3.12"
    assert project["scripts"]["visibility"] == "visibility.cli:main"
    assert meta["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/visibility"]


def test_module_runs_as_a_script():
    p = subprocess.run(
        [sys.executable, "-m", "visibility.cli", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0 and p.stdout.startswith("visibility ")
