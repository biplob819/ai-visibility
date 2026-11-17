"""RUN-03: the flagship runs' spend reconciles: ledger, raw-record costs and a recomputation
from provider usage agree within 10% (they agree exactly), with matching counts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _reconcile(*runs: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "reconcile_spend.py"),
            "studies/uk-health",
            "--runs",
            *runs,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_both_study_runs_reconcile():
    out = _reconcile("1", "2")
    assert out.returncode == 0, out.stdout + out.stderr


def test_a_run_with_no_records_is_not_reported_as_reconciled():
    out = _reconcile("9")
    assert out.returncode == 1 and "MISMATCH" in out.stdout
