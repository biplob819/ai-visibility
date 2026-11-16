"""Gate 7's minimum-Python check reads pytest's own summary, not a trailing uv warning."""

from __future__ import annotations

import subprocess
from pathlib import Path

import node_converge


def _proc(stdout: str, stderr: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_a_uv_warning_after_the_summary_does_not_fail_the_gate(tmp_path: Path):
    seen = {}

    def runner(cmd, root, env):
        seen["env"] = env
        return _proc(
            "..\n2 passed, 9 deselected in 0.4s\n", "warning: `VIRTUAL_ENV=.venv` does not match\n"
        )

    r = node_converge.golden_min_python(tmp_path, which=lambda _: "/usr/bin/uv", runner=runner)
    assert r.status == "PASS"
    assert "VIRTUAL_ENV" not in seen["env"]


def test_a_failing_replay_still_fails(tmp_path: Path):
    r = node_converge.golden_min_python(
        tmp_path,
        which=lambda _: "/usr/bin/uv",
        runner=lambda *a: _proc("F.\n1 failed, 1 passed\n", code=1),
    )
    assert r.status == "FAIL"
