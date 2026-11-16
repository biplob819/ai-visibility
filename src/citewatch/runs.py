"""Study-run gates and the run manifest (Tech Spec §13, node S3.1).

Gate G1, before run 1: the frozen questions and pre-registration hashes are recorded in the
decisions log; the smoke run measured the cost model and the estimate fits the cap; prices were
checked within 7 days; the working tree is clean, and its SHA goes in the manifest.

Gate G2, before run 2: no change since run 1's SHA to the runner, extractor, prompt, questions or
`study.yaml` files; at least 2 hours since run 1 finished.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from citewatch.schemas import StudyConfig

MIN_GAP = dt.timedelta(hours=2)
PRICE_MAX_AGE_DAYS = 7
# the code and inputs a study run depends on; any change between runs breaks G2 (E2)
FROZEN_CODE = ("src/citewatch/runners", "src/citewatch/extract")


def sha256(path: Path | None) -> str | None:
    return (
        None
        if path is None or not path.is_file()
        else hashlib.sha256(path.read_bytes()).hexdigest()
    )


def _git(base: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(base), *args], capture_output=True, text=True, timeout=30, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout


def git_sha(base: Path) -> str | None:
    out = _git(base, "rev-parse", "HEAD")
    return out.strip() if out else None


def git_root(base: Path) -> Path | None:
    out = _git(base, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out else None


def dirty(base: Path) -> list[str]:
    out = _git(base, "status", "--porcelain")
    return [] if out is None else [line[3:] for line in out.splitlines() if line.strip()]


def decisions_for(base: Path) -> Path | None:
    for parent in [base, *base.resolve().parents]:
        for p in (parent / "decisions.md", parent / "docs" / "decisions.md"):
            if p.is_file():
                return p
    return None


def gate_g1(
    base: Path,
    cfg: StudyConfig,
    *,
    estimate_usd: float,
    measured: bool,
    cap_usd: float | None,
    prices_age_days: int,
    preregistration: Path | None,
) -> list[str]:
    problems: list[str] = []
    q = sha256(base / cfg.questions_path)
    p = sha256(preregistration)
    log = decisions_for(base)
    if p is None:
        problems.append("no preregistration.md: freeze the metric definitions before a study run")
    if log is None:
        problems.append("no decisions.md recording the frozen hashes")
    else:
        text = log.read_text(encoding="utf-8")
        for name, h in (("questions", q), ("preregistration", p)):
            if h is not None and h[:16] not in text:
                problems.append(f"the {name} sha256 {h[:16]}… is not recorded in {log.name}")
    if not measured:
        problems.append("no cost_model.yaml: run and measure the smoke run (run 0) first")
    if cap_usd is not None and estimate_usd > cap_usd:
        problems.append(f"estimate ${estimate_usd:.2f} is over the cap ${cap_usd:.2f}")
    if prices_age_days > PRICE_MAX_AGE_DAYS:
        problems.append(
            f"prices were checked {prices_age_days} days ago (at most {PRICE_MAX_AGE_DAYS})"
        )
    problems += _clean_tree(base)
    return problems


def _clean_tree(base: Path) -> list[str]:
    if git_sha(base) is None:
        return ["not a git repository: a study run records the commit it ran from"]
    changed = dirty(base)
    if changed:
        return [
            f"the working tree has uncommitted changes ({', '.join(changed[:3])}…): commit first"
        ]
    return []


def gate_g2(base: Path, cfg: StudyConfig, now: dt.datetime) -> list[str]:
    problems: list[str] = []
    manifest = read_manifest(base, 1)
    if manifest is None or not manifest.get("finished_at"):
        return ["run 1 has no finished manifest: complete run 1 first"]
    finished = dt.datetime.fromisoformat(manifest["finished_at"].replace("Z", "+00:00"))
    if now - finished < MIN_GAP:
        wait = MIN_GAP - (now - finished)
        problems.append(f"run 1 finished {now - finished} ago; wait {wait} more (at least 2 hours)")
    root = git_root(base)
    if root is None:
        return [*problems, "not a git repository"]
    rel = (
        base.resolve().relative_to(root.resolve())
        if base.resolve().is_relative_to(root.resolve())
        else None
    )
    paths = list(FROZEN_CODE)
    if rel is not None:
        paths += [str(rel / "study.yaml"), str(rel / cfg.questions_path)]
    out = _git(root, "diff", "--name-only", manifest["git_sha"], "HEAD", "--", *paths)
    if out is None:
        problems.append(f"cannot diff against run 1's commit {manifest['git_sha'][:12]}")
    elif out.strip():
        problems.append(f"changed since run 1: {', '.join(out.split()[:5])} (gate G2)")
    problems += _clean_tree(base)
    return problems


def manifest_path(base: Path, run: int) -> Path:
    return base / "data" / "runs" / f"run-{run}" / "manifest.json"


def read_manifest(base: Path, run: int) -> dict[str, Any] | None:
    p = manifest_path(base, run)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def model_snapshots(base: Path, run: int) -> dict[str, list[str]]:
    """The provider's own model id per answer, as the raw responses report it."""
    found: dict[str, set[str]] = {}
    for f in sorted((base / "data" / "raw" / "ask").glob("*/*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("run") != run:
            continue
        for r in d.get("responses") or []:
            if isinstance(r, dict) and r.get("model"):
                found.setdefault(d["model"], set()).add(str(r["model"]))
    return {m: sorted(v) for m, v in sorted(found.items())}


def write_manifest(
    base: Path,
    run: int,
    *,
    config_hash: str,
    questions_sha256: str | None,
    preregistration_sha256: str | None,
    started_at: dt.datetime,
    finished_at: dt.datetime | None,
    answers: int,
    errors: Iterable[Any] = (),
    run_sha: str | None = None,
) -> Path:
    """Write (or update) the run manifest; a resumed run keeps its first start and commit."""
    old = read_manifest(base, run) or {}
    sha = run_sha or git_sha(base)  # the commit the run started from, read before any call
    stamp = lambda t: t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    data = {
        "run": run,
        "config_hash": config_hash,
        "git_sha": old.get("git_sha") or sha,
        "git_shas": sorted({*old.get("git_shas", []), sha or ""} - {""}),
        "questions_sha256": questions_sha256,
        "preregistration_sha256": preregistration_sha256,
        "model_snapshots": model_snapshots(base, run),
        "started_at": old.get("started_at") or stamp(started_at),
        "finished_at": stamp(finished_at) if finished_at else None,
        "answers": answers,
        "errors": len(list(errors)),
    }
    p = manifest_path(base, run)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return p
