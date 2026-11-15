#!/usr/bin/env python3
"""Run every gate for a build node and report all of them, even after a failure.

Usage:
    python scripts/node_converge.py W0.1          # run all 12 gates
    python scripts/node_converge.py --self-test   # prove every gate can fail

Exit 0 only when no gate FAILs. SKIP means the gate had nothing to check yet
(for example no golden tests exist before node A2.4); SKIP never hides a failure.

Gates:
   1 claims-work     at least one capability row of the node is building or green
   2 eligibility     graph has no cycles and nothing builds ahead of its dependencies
   3 proofs          every row has a proof for all five dimensions, and each proof resolves
   4 ruff            uv run ruff check .
   5 pyright         uv run pyright
   6 pytest          unit, property and contract tests
   7 golden          pytest -m golden
   8 politeness      pytest -m polite, plus the fetch-log audit (scripts/fetch_audit.py)
   9 safety          pytest -m safety, the secret scan and the storage audit
  10 build           uv build, install the wheel in a clean venv, run the smoke commands
  11 changed-tests   if source changed since node start, tests changed too
  12 records         changelog entry, criteria cover every row, RUN-STATE.md exists
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import fetch_audit
import secret_scan
import storage_audit
from harness_lib import (
    PROOF_DIMENSIONS,
    ROOT,
    SPECS_DIR,
    Cap,
    HarnessError,
    Node,
    eligibility_problems,
    load_catalog,
    load_graph,
    mentions,
    parse_catalog,
    parse_graph,
    safe_console,
    spec_dir,
)

# Commands run inside the clean venv by gate 10. N1.3 adds `report --example` and `ask --dry-run`.
# (command, expected exit code); run with no provider keys in the environment.
SMOKE_COMMANDS: list[tuple[list[str], int]] = [(["citewatch", "--version"], 0)]
PYTEST_UNIT_MARKERS = "not golden and not polite and not safety"
NA_MIN_REASON = 10
NA_FORBIDDEN = {"logical"}  # every capability needs at least a real unit test


@dataclass
class Result:
    status: str  # PASS | FAIL | SKIP
    detail: str


@dataclass
class Ctx:
    node: str
    root: Path
    nodes: dict[str, Node]
    caps: list[Cap]
    specs: Path


def _run(
    cmd: list[str], cwd: Path, timeout: int = 900, env: dict[str, str] | None = None
) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as exc:  # Windows' message does not name the program, so we do
        return 127, f"{cmd[0]}: not found ({exc})"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]}: timed out after {timeout}s"
    return p.returncode, (p.stdout + p.stderr).strip()


def _tail(text: str, n: int = 12) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


# ---------- gates ----------


def gate_claims_work(ctx: Ctx) -> Result:
    rows = [c for c in ctx.caps if c.node == ctx.node]
    active = [c for c in rows if c.status in ("building", "green")]
    if not rows:
        return Result("FAIL", f"{ctx.node} has no catalog rows")
    if not active:
        return Result(
            "FAIL", f"no row of {ctx.node} is building or green (run node_start --mark-building)"
        )
    return Result("PASS", f"{len(active)}/{len(rows)} rows active")


def gate_eligibility(ctx: Ctx) -> Result:
    problems = eligibility_problems(ctx.nodes, ctx.caps)
    return Result("FAIL", "; ".join(problems)) if problems else Result("PASS", "eligible")


PROOF_RE = re.compile(r'^(?P<path>[^›"]+)›"(?P<test>[^"]+)"$')


SKIP_MARKS = {"skip", "skipif", "xfail"}
RUNTIME_SKIPS = {"skip", "xfail", "importorskip"}


def _dotted(expr: ast.expr) -> list[str]:
    if isinstance(expr, ast.Call):
        expr = expr.func
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if isinstance(expr, ast.Name):
        parts.append(expr.id)
    return parts[::-1]


UNITTEST_SKIPS = {"skip", "skipIf", "skipUnless", "expectedFailure"}
MARK_ALIASES: set[str] = {
    "mark"
}  # names `pytest.mark` is bound to (`from pytest import mark as mk`)


def _is_skip_mark(expr: ast.expr, bare_marks: set[str]) -> bool:
    """pytest.mark.skip / skipif / xfail (called or not), mark.skip after `from pytest import
    mark`, or a bare skip/xfail imported from pytest.mark. Arguments are never inspected, so
    parametrize("x", ["skip_header"]) is not a skip."""
    if isinstance(expr, ast.List | ast.Tuple):
        return any(_is_skip_mark(e, bare_marks) for e in expr.elts)
    parts = _dotted(expr)
    if not parts:
        return False
    if len(parts) >= 2 and parts[-2] in MARK_ALIASES and parts[-1] in SKIP_MARKS:
        return True
    if len(parts) >= 2 and parts[0] == "unittest" and parts[-1] in UNITTEST_SKIPS:
        return True
    if len(parts) >= 2 and parts[-1] == "parametrize" and isinstance(expr, ast.Call):
        # a parameter carrying marks=pytest.mark.skip never runs that case
        for node in ast.walk(expr):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "marks"
                and _is_skip_mark(node.value, bare_marks)
            ):
                return True
    return len(parts) == 1 and parts[0] in bare_marks


def _pytest_imports(tree: ast.Module) -> tuple[set[str], set[str], set[str]]:
    """Names imported from pytest that skip at runtime, names imported from pytest.mark, and
    the names pytest itself is bound to (`import pytest as pt`)."""
    runtime: set[str] = set()
    marks: set[str] = set()
    aliases: set[str] = {"pytest"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases |= {a.asname or a.name for a in node.names if a.name == "pytest"}
        if isinstance(node, ast.ImportFrom) and node.module == "unittest":
            marks |= {a.asname or a.name for a in node.names if a.name in UNITTEST_SKIPS}
        if isinstance(node, ast.ImportFrom) and node.module == "pytest":
            MARK_ALIASES.update(a.asname or a.name for a in node.names if a.name == "mark")
    for node in tree.body:  # skip = pytest.mark.skip; @skip
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and _is_skip_mark(node.value, marks)
        ):
            marks.add(node.targets[0].id)
        if isinstance(node, ast.ImportFrom) and node.module in ("pytest", "_pytest.outcomes"):
            runtime |= {a.asname or a.name for a in node.names if a.name in RUNTIME_SKIPS}
        if isinstance(node, ast.ImportFrom) and node.module == "pytest.mark":
            marks |= {a.asname or a.name for a in node.names if a.name in SKIP_MARKS}
    return runtime, marks, aliases


def _calls_skip(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, runtime_names: set[str], aliases: set[str]
) -> bool:
    """A body that calls pytest.skip/xfail/importorskip (or the same names imported from
    pytest) never proves anything. pytest.fail is a legitimate assertion and is allowed."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Raise) and node.exc is not None:
            raised = _dotted(node.exc)
            if raised[-1:] == ["SkipTest"] or raised[-2:] == ["skip", "Exception"]:
                return True
        if not isinstance(node, ast.Call):
            continue
        parts = _dotted(node.func)
        if parts[-1:] == ["skipTest"]:
            return True
        if len(parts) == 2 and parts[0] in aliases and parts[-1] in RUNTIME_SKIPS:
            return True
        if len(parts) == 1 and parts[0] in runtime_names:
            return True
    return False


def _pytestmark_skips(body: list[ast.stmt], bare_marks: set[str]) -> bool:
    for n in body:
        targets = (
            n.targets
            if isinstance(n, ast.Assign)
            else [n.target]
            if isinstance(n, ast.AnnAssign)
            else []
        )
        value = getattr(n, "value", None)
        if (
            value is not None
            and any(isinstance(tg, ast.Name) and tg.id == "pytestmark" for tg in targets)
            and _is_skip_mark(value, bare_marks)
        ):
            return True
    return False


def _test_functions(path: Path) -> dict[str, bool]:
    """Map each real test function name to whether it is skipped (or can never run).

    Only `def test_*` at module level or inside `Test*` classes (nested too) count, so names
    in comments, strings or as prefixes of other names do not. A test counts as skipped when a
    skip/skipif/xfail mark applies to it (its decorators, an enclosing class's decorators or
    pytestmark, or the module's pytestmark), or when its body calls a runtime skip.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    MARK_ALIASES.clear()
    MARK_ALIASES.add("mark")
    runtime_names, bare_marks, aliases = _pytest_imports(tree)
    # a module-level skip or importorskip skips every test in the file
    module_calls_skip = any(
        isinstance(n, ast.Expr | ast.Assign)
        and isinstance(n.value, ast.Call)
        and (
            (
                len(_dotted(n.value.func)) == 2
                and _dotted(n.value.func)[0] in aliases
                and _dotted(n.value.func)[1] in RUNTIME_SKIPS
            )
            or _dotted(n.value.func) in ([r] for r in runtime_names)
        )
        for n in tree.body
    )
    found: dict[str, bool] = {}
    # `name.__test__ = False` at module level, or `__test__ = False` in a class body
    disabled = {
        tg.value.id
        for n in tree.body
        if isinstance(n, ast.Assign)
        for tg in n.targets
        if isinstance(tg, ast.Attribute)
        and tg.attr == "__test__"
        and isinstance(tg.value, ast.Name)
        and isinstance(n.value, ast.Constant)
        and not n.value.value
    }

    def test_off(body: list[ast.stmt]) -> bool:
        return any(
            isinstance(n, ast.Assign)
            and any(isinstance(tg, ast.Name) and tg.id == "__test__" for tg in n.targets)
            and isinstance(n.value, ast.Constant)
            and not n.value.value
            for n in body
        )

    def is_test_class(node: ast.ClassDef) -> bool:
        if any(_dotted(b)[-1:] == ["TestCase"] for b in node.bases):
            return True
        has_init = any(isinstance(n, ast.FunctionDef) and n.name == "__init__" for n in node.body)
        return node.name.startswith("Test") and not has_init  # pytest skips classes with __init__

    def visit(body: list[ast.stmt], inherited: bool) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name.startswith("test"):
                    found[node.name] = (
                        inherited
                        or node.name in disabled
                        or any(_is_skip_mark(d, bare_marks) for d in node.decorator_list)
                        or _calls_skip(node, runtime_names, aliases)
                    )
            elif isinstance(node, ast.ClassDef) and is_test_class(node):
                skip = (
                    inherited
                    or node.name in disabled
                    or test_off(node.body)
                    or any(_is_skip_mark(d, bare_marks) for d in node.decorator_list)
                    or _pytestmark_skips(node.body, bare_marks)
                )
                visit(node.body, skip)

    visit(tree.body, module_calls_skip or _pytestmark_skips(tree.body, bare_marks))
    return found


def proof_problems(cap: Cap, root: Path) -> list[str]:
    if not cap.proof:
        return [f"{cap.cap_id}: no proof"]
    entries: dict[str, str] = {}
    for part in cap.proof.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            return [f"{cap.cap_id}: malformed proof entry {part!r}"]
        key, value = (s.strip() for s in part.split("=", 1))
        if key in entries:
            return [f"{cap.cap_id}: duplicate proof key {key!r}"]
        entries[key] = value
    problems: list[str] = []
    tests_root = (root / "tests").resolve()
    for dim in PROOF_DIMENSIONS:
        value = entries.get(dim)
        if value is None:
            problems.append(f"{cap.cap_id}: missing {dim} proof")
            continue
        if value.startswith("n/a:"):
            if dim in NA_FORBIDDEN:
                problems.append(f"{cap.cap_id}: {dim} proof cannot be n/a")
            elif len(value[4:].strip()) < NA_MIN_REASON:
                problems.append(f"{cap.cap_id}: {dim} n/a needs a reason of {NA_MIN_REASON}+ chars")
            continue
        m = PROOF_RE.match(value)
        if not m:
            problems.append(f'{cap.cap_id}: {dim} proof must be path›"test" or n/a:<reason>')
            continue
        rel, test = m["path"].strip(), m["test"].strip()
        path = (root / rel).resolve()
        if not path.is_relative_to(tests_root) or path.suffix != ".py":
            problems.append(f"{cap.cap_id}: {dim} proof file {rel} must be a .py file under tests/")
            continue
        if not path.is_file():
            problems.append(f"{cap.cap_id}: {dim} proof file {rel} not found")
            continue
        try:
            tests = _test_functions(path)
        except SyntaxError as exc:
            problems.append(f"{cap.cap_id}: {dim} proof file {rel} does not parse: {exc.msg}")
            continue
        if test not in tests:
            problems.append(f"{cap.cap_id}: {dim} test {test!r} is not a test function in {rel}")
        elif tests[test]:
            problems.append(f"{cap.cap_id}: {dim} test {test!r} is skipped")
    extra = set(entries) - set(PROOF_DIMENSIONS)
    if extra:
        problems.append(f"{cap.cap_id}: unknown proof keys {sorted(extra)}")
    return problems


def gate_proofs(ctx: Ctx) -> Result:
    rows = [c for c in ctx.caps if c.node == ctx.node]
    problems = [p for c in rows for p in proof_problems(c, ctx.root)]
    if problems:
        shown = "; ".join(problems[:6]) + (
            f"; … {len(problems) - 6} more" if len(problems) > 6 else ""
        )
        return Result("FAIL", shown)
    return Result("PASS", f"{len(rows)} rows × {len(PROOF_DIMENSIONS)} dimensions resolve")


def _tool_gate(cmd: list[str], root: Path, label: str) -> Result:
    code, out = _run(cmd, root)
    if code == 0:
        return Result("PASS", label)
    return Result("FAIL", _tail(out))


def gate_ruff(ctx: Ctx) -> Result:
    return _tool_gate([sys.executable, "-m", "ruff", "check", "."], ctx.root, "ruff clean")


def gate_pyright(ctx: Ctx) -> Result:
    return _tool_gate([sys.executable, "-m", "pyright"], ctx.root, "pyright clean")


def _pytest(root: Path, marker: str, label: str) -> Result:
    code, out = _run([sys.executable, "-m", "pytest", "-q", "-m", marker], root)
    if code == 0:
        last = out.splitlines()[-1] if out else ""
        if not re.search(r"\b\d+ passed\b", last):
            return Result("FAIL", f"no {label} test passed ({last or 'no output'})")
        return Result("PASS", f"{label}: {last}")
    if code == 5:
        return Result("SKIP", f"no {label} tests collected yet")
    return Result("FAIL", _tail(out))


def gate_pytest(ctx: Ctx) -> Result:
    return _pytest(ctx.root, PYTEST_UNIT_MARKERS, "unit")


MIN_PYTHON = "3.11"  # requires-python floor; float and stdlib behaviour can differ (L-13)


Runner = Callable[[list[str], Path, dict[str, str]], "subprocess.CompletedProcess[str]"]


def _default_runner(
    cmd: list[str], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)


def golden_min_python(
    root: Path,
    which: Callable[[str], str | None] | None = None,
    runner: Runner | None = None,
) -> Result:
    """Run the golden replays again on the minimum supported Python. Never silently skipped:
    no uv, or a failing replay, is a FAIL."""
    if not (which or shutil.which)("uv"):
        return Result("FAIL", f"uv not found, so golden cannot run on Python {MIN_PYTHON}")
    private = os.environ.get("UV_PROJECT_ENVIRONMENT")
    venv = (
        f"{private}-py{MIN_PYTHON.replace('.', '')}"
        if private
        else str(root / f".venv-py{MIN_PYTHON.replace('.', '')}")
    )
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": venv}
    cmd = ["uv", "run", "--python", MIN_PYTHON, "python", "-m", "pytest", "-q", "-m", "golden"]
    try:
        proc = (runner or _default_runner)(cmd, root, env)
    except subprocess.TimeoutExpired:
        return Result("FAIL", f"golden on Python {MIN_PYTHON} timed out")
    out = (proc.stdout + proc.stderr).strip()
    last = out.splitlines()[-1] if out else ""
    if proc.returncode != 0 or not re.search(r"\b\d+ passed\b", last):
        return Result("FAIL", f"golden on Python {MIN_PYTHON}: " + _tail(out))
    return Result("PASS", f"Python {MIN_PYTHON}: {last}")


def gate_golden(ctx: Ctx, min_python: Callable[[Path], Result] = golden_min_python) -> Result:
    """Golden replays compare bytes, so they must pass on this interpreter and on the minimum
    supported Python (L-13)."""
    here = _pytest(ctx.root, "golden", "golden")
    if here.status != "PASS":
        return here
    low = min_python(ctx.root)
    if low.status != "PASS":
        return low
    return Result("PASS", f"{here.detail}; {low.detail}")


def _combine(parts: list[tuple[str, Result]]) -> Result:
    """Every sub-check is reported, so one failure cannot hide another."""
    failed = [f"{name}: {r.detail}" for name, r in parts if r.status == "FAIL"]
    if failed:
        return Result("FAIL", "\n".join(failed))
    if all(r.status == "SKIP" for _, r in parts):
        return Result("SKIP", "; ".join(f"{n}: {r.detail}" for n, r in parts))
    return Result("PASS", "; ".join(f"{n}: {r.detail}" for n, r in parts))


def gate_politeness(ctx: Ctx) -> Result:
    """Fetch logs obey the politeness rules, and the politeness tests pass (Tech Spec §7.2)."""
    logs = fetch_audit.log_files(ctx.root)
    problems = fetch_audit.audit_paths(logs) if logs else []
    audit = (
        Result("FAIL", "; ".join(problems[:5]))
        if problems
        else Result("PASS", f"{len(logs)} logs clean")
        if logs
        else Result("SKIP", "no fetch logs yet")
    )
    return _combine([("fetch audit", audit), ("tests", _pytest(ctx.root, "polite", "polite"))])


def gate_safety(ctx: Ctx, cache: Path | None = None) -> Result:
    hits = secret_scan.scan(secret_scan.candidate_files(ctx.root))
    stored = storage_audit.audit(
        ctx.root, cache if cache is not None else storage_audit.body_cache_dir(), ctx.caps
    )
    return _combine(
        [
            (
                "secret scan",
                Result("FAIL", "; ".join(hits[:5])) if hits else Result("PASS", "clean"),
            ),
            (
                "storage audit",
                Result("FAIL", "; ".join(stored[:5])) if stored else Result("PASS", "clean"),
            ),
            ("tests", _pytest(ctx.root, "safety", "safety")),
        ]
    )


def _venv_bin(venv: Path, exe: str) -> Path:
    sub = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv / sub / f"{exe}{suffix}"


def keyless_env() -> dict[str, str]:
    """The environment minus every provider credential, so smoke commands prove the no-key
    paths (EvalKit L-40)."""
    return {
        k: v
        for k, v in os.environ.items()
        if not (k.endswith(("_API_KEY", "_TOKEN", "_SECRET")) or k == "ANTHROPIC_PROFILE")
    }


def gate_build(ctx: Ctx, smoke: list[tuple[list[str], int]] | None = None) -> Result:
    smoke = SMOKE_COMMANDS if smoke is None else smoke
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "dist"
        code, log = _run(["uv", "build", "--wheel", "--out-dir", str(out)], ctx.root)
        if code != 0:
            return Result("FAIL", "uv build: " + _tail(log))
        wheels = sorted(out.glob("*.whl"))
        if not wheels:
            return Result("FAIL", "uv build produced no wheel")
        venv = Path(tmp) / "venv"
        code, log = _run(["uv", "venv", "-q", str(venv)], ctx.root)
        if code != 0:
            return Result("FAIL", "uv venv: " + _tail(log))
        py = _venv_bin(venv, "python")
        code, log = _run(
            ["uv", "pip", "install", "-q", "--python", str(py), str(wheels[0])], ctx.root
        )
        if code != 0:
            return Result("FAIL", "install wheel: " + _tail(log))
        env = keyless_env()
        for cmd, expected in smoke:
            exe = _venv_bin(venv, cmd[0])
            code, log = _run([str(exe), *cmd[1:]], Path(tmp), env=env)
            if code != expected:
                return Result(
                    "FAIL", f"{' '.join(cmd)}: exit {code}, expected {expected}: {_tail(log)}"
                )
        shown = ", ".join(f"{' '.join(c)} (exit {e})" for c, e in smoke)
        return Result("PASS", f"{wheels[0].name} installs; smoke with no keys: {shown}")


def _git_names(root: Path, args: list[str]) -> tuple[int, list[str], str]:
    try:
        p = subprocess.run(["git", *args, "-z"], cwd=root, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, [], str(exc)
    names = [os.fsdecode(n) for n in p.stdout.split(b"\0") if n]
    return p.returncode, names, p.stderr.decode("utf-8", "replace")


def changed_files(root: Path, base: str) -> list[str] | None:
    """Files changed since base: committed, staged, unstaged and untracked, NUL-separated so
    no name is quoted. Returns None when git is unusable."""
    code, _ = _run(["git", "rev-parse", "--git-dir"], root)
    if code != 0:
        return None
    files: set[str] = set()
    code, _ = _run(["git", "rev-parse", "HEAD"], root)
    if code == 0 and base not in ("", "none"):
        code, names, err = _git_names(root, ["diff", "--name-only", base])
        if code != 0:
            raise HarnessError(f"git diff against base {base!r} failed: {_tail(err, 2)}")
        files.update(names)
    else:
        files.update(_git_names(root, ["ls-files"])[1])
    files.update(_git_names(root, ["ls-files", "--others", "--exclude-standard"])[1])
    return sorted(f for f in files if f)


def changed_tests_problem(files: list[str], root: Path | None = None) -> str | None:
    src = [
        f for f in files if f.startswith("src/") or (f.startswith("scripts/") and f.endswith(".py"))
    ]
    tests = [
        f
        for f in files
        if f.startswith("tests/")
        and re.search(r"(?:^|/)(?:test_[^/]*|[^/]*_test|conftest)\.py$", f)
        and (root is None or (root / f).is_file())  # a deleted test is not a changed test
    ]
    if src and not tests:
        return f"{len(src)} source files changed but no tests changed (e.g. {src[0]})"
    return None


def gate_changed_tests(ctx: Ctx) -> Result:
    d = spec_dir(ctx.node, ctx.specs)
    base_file = d / ".base" if d else None
    base = (
        base_file.read_text(encoding="utf-8").strip()
        if base_file and base_file.is_file()
        else "none"
    )
    try:
        files = changed_files(ctx.root, base)
    except HarnessError as exc:
        return Result("FAIL", str(exc))
    if files is None:
        return Result("SKIP", "not a git repository")
    problem = changed_tests_problem(files, ctx.root)
    if problem:
        return Result("FAIL", problem)
    return Result(
        "PASS", f"{len(files)} files changed since {base[:10]}; tests changed with source"
    )


def records_problems(node: str, caps: list[Cap], root: Path, specs: Path) -> list[str]:
    problems: list[str] = []
    changelog = root / "changelog.md"
    if not changelog.is_file() or f"[{node}]" not in changelog.read_text(encoding="utf-8"):
        problems.append(f"changelog.md has no [{node}] entry")
    d = spec_dir(node, specs)
    if d is None:
        return [*problems, f"no spec folder for {node}"]
    criteria = d / "criteria.md"
    text = criteria.read_text(encoding="utf-8") if criteria.is_file() else ""
    missing = [c.cap_id for c in caps if c.node == node and not mentions(text, c.cap_id)]
    if missing:
        problems.append(f"criteria.md misses {', '.join(missing)}")
    if not (d / "RUN-STATE.md").is_file():
        problems.append("RUN-STATE.md missing")
    return problems


def gate_records(ctx: Ctx) -> Result:
    problems = records_problems(ctx.node, ctx.caps, ctx.root, ctx.specs)
    return Result("FAIL", "; ".join(problems)) if problems else Result("PASS", "records complete")


GATES: list[tuple[str, Callable[[Ctx], Result]]] = [
    ("claims-work", gate_claims_work),
    ("eligibility", gate_eligibility),
    ("proofs", gate_proofs),
    ("ruff", gate_ruff),
    ("pyright", gate_pyright),
    ("pytest", gate_pytest),
    ("golden", gate_golden),
    ("politeness", gate_politeness),
    ("safety", gate_safety),
    ("build", gate_build),
    ("changed-tests", gate_changed_tests),
    ("records", gate_records),
]


def run_gates(ctx: Ctx, gates: list[tuple[str, Callable[[Ctx], Result]]]) -> tuple[list[str], int]:
    """Run every gate and report every one, whatever failed before it."""
    lines: list[str] = []
    failed = 0
    for i, (name, fn) in enumerate(gates, start=1):
        try:
            r = fn(ctx)
        except Exception as exc:  # a crashing gate is a failing gate
            r = Result("FAIL", f"gate crashed: {exc!r}")
        failed += r.status == "FAIL"
        first, *rest = r.detail.splitlines() or [""]
        lines.append(f"{i:>2} {name:<14} {r.status:<4}  {first}")
        lines.extend(f"{'':>22}{ln}" for ln in rest)
    return lines, failed


# ---------- self-test: every gate must be shown to fail on bad input ----------


def self_test() -> int:
    """Feed each gate a planted defect and require FAIL that names the defect."""
    failures = 0

    def check(name: str, ok: bool) -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  [{'ok' if ok else 'WRONG'}] {name}")

    graph = parse_graph("| **W0.1** | Harness | — |\n| **N1.1** | Schemas | W0.1 |\n")
    hdr = "cap_id\tnode\tstatus\tproof\tnote\n"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        specs = root / "specs"
        (specs / "W0.1-harness").mkdir(parents=True)

        def ctx(cat: str, node: str = "W0.1", at: Path = root) -> Ctx:
            return Ctx(node, at, graph, parse_catalog(hdr + cat), specs)

        # 1 claims-work
        r = gate_claims_work(ctx("H-1\tW0.1\tspec\t\t\n"))
        check(
            "1 claims-work fails when nothing started",
            r.status == "FAIL" and "no row of W0.1 is building" in r.detail,
        )
        r = gate_claims_work(ctx("H-1\tW0.1\tbuilding\t\t\n"))
        check("1 claims-work passes when building", r.status == "PASS")

        # 2 eligibility
        r = gate_eligibility(ctx("H-1\tW0.1\tbuilding\t\t\nS-1\tN1.1\tbuilding\t\t\n", "N1.1"))
        check("2 eligibility fails when building ahead", r.status == "FAIL" and "W0.1" in r.detail)

        # 3 proofs
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_x.py").write_text(
            "import pytest\n\n"
            "# test_in_comment\n"
            "NAME = 'test_in_string'\n\n"
            "def test_real():\n    pass\n\n"
            "def test_realistic():\n    pass\n\n"
            "@pytest.mark.skip\ndef test_skipped():\n    pass\n",
            encoding="utf-8",
        )
        (root / "outside.py").write_text("def test_real():\n    pass\n", encoding="utf-8")
        ok = "; ".join(
            [f'{d}=tests/test_x.py›"test_real"' for d in PROOF_DIMENSIONS[:3]]
            + ["repro=n/a:no state to reproduce here", "safety=n/a:no secrets or spend involved"]
        )
        r = gate_proofs(ctx(f"H-1\tW0.1\tgreen\t{ok}\t\n"))
        check("3 proofs pass on resolvable proof", r.status == "PASS")
        bad = {  # label -> (proof, text the failure must name)
            "empty proof": "",
            "missing dimension": 'logical=tests/test_x.py›"test_real"',
            "unknown test": ok.replace('"test_real"', '"test_ghost"', 1),
            "name only in a comment": ok.replace('"test_real"', '"test_in_comment"', 1),
            "name only in a string": ok.replace('"test_real"', '"test_in_string"', 1),
            "prefix of another test": ok.replace('"test_real"', '"test_rea"', 1),
            "skipped test": ok.replace('"test_real"', '"test_skipped"', 1),
            "path outside tests/": ok.replace("tests/test_x.py", "outside.py", 1),
            "path escaping repo": ok.replace("tests/test_x.py", "tests/../../x.py", 1),
            "short n/a reason": ok.replace("n/a:no state to reproduce here", "n/a:x"),
            "logical n/a": ok.replace(
                'logical=tests/test_x.py›"test_real"', "logical=n/a:nothing to unit test here"
            ),
            "duplicate key": ok + '; logical=tests/test_x.py›"test_real"',
        }
        needles = {
            "empty proof": "no proof",
            "missing dimension": "missing contract proof",
            "unknown test": "test_ghost",
            "name only in a comment": "test_in_comment",
            "name only in a string": "test_in_string",
            "prefix of another test": "test_rea",
            "skipped test": "is skipped",
            "path outside tests/": "must be a .py file under tests/",
            "path escaping repo": "must be a .py file under tests/",
            "short n/a reason": "needs a reason",
            "logical n/a": "cannot be n/a",
            "duplicate key": "duplicate proof key",
        }
        for label, proof in bad.items():
            r = gate_proofs(ctx(f"H-1\tW0.1\tgreen\t{proof}\t\n"))
            check(f"3 proofs fail on {label}", r.status == "FAIL" and needles[label] in r.detail)
        (tests_dir / "test_y.py").write_text(
            "import pytest\n\npytestmark = pytest.mark.skip\n\ndef test_mod():\n    pass\n",
            encoding="utf-8",
        )
        (tests_dir / "test_z.py").write_text(
            "import pytest\n\n@pytest.mark.skip\nclass TestC:\n    def test_cls(self):\n"
            "        pass\n\ndef test_rt():\n    pytest.skip('x')\n\n"
            "@pytest.mark.xfail(run=False)\ndef test_xf():\n    pass\n",
            encoding="utf-8",
        )
        (tests_dir / "test_w.py").write_text(
            "import pytest as pt\n\n"
            "pytestmark = [pt.mark.usefixtures('x'), pt.mark.skip]\n\n"
            "def test_listmark():\n    pass\n",
            encoding="utf-8",
        )
        (tests_dir / "test_v.py").write_text(
            "import pytest as pt\nimport unittest\nfrom pytest.mark import skip\n\n"
            "@skip\ndef test_bare():\n    pass\n\n"
            "def test_alias():\n    pt.skip('x')\n\n"
            "def test_imp():\n    pt.importorskip('nope')\n\n"
            "@unittest.skip('x')\ndef test_ut():\n    pass\n\n"
            "@pt.mark.parametrize('a', [pt.param(1, marks=pt.mark.skip)])\n"
            "def test_param(a):\n    pass\n\n"
            "def test_off():\n    pass\n\ntest_off.__test__ = False\n\n"
            "class Helper:\n    def test_helper(self):\n        pass\n\n"
            "class Cases(unittest.TestCase):\n    def test_tc(self):\n        pass\n",
            encoding="utf-8",
        )
        found_v = _test_functions(tests_dir / "test_v.py")
        skipped_names = ("test_bare", "test_alias", "test_imp", "test_ut", "test_param", "test_off")
        check(
            "3 skip detection: bare marks, aliases, importorskip, unittest, params, __test__",
            all(found_v.get(n) is True for n in skipped_names),
        )
        check(
            "3 methods of non-Test classes are not tests; TestCase subclasses are",
            "test_helper" not in found_v and found_v.get("test_tc") is False,
        )
        check(
            "3 a skip inside a pytestmark list counts",
            _test_functions(tests_dir / "test_w.py") == {"test_listmark": True},
        )
        (tests_dir / "test_broken.py").write_text("def test_b(:\n", encoding="utf-8")
        proof = ok.replace("tests/test_x.py", "tests/test_broken.py", 1)
        r = gate_proofs(ctx(f"H-1\tW0.1\tgreen\t{proof}\t\n"))
        check(
            "3 proofs fail on a test file that does not parse",
            r.status == "FAIL" and "does not parse" in r.detail,
        )
        for path, name in [
            ("tests/test_y.py", "test_mod"),
            ("tests/test_z.py", "test_cls"),
            ("tests/test_z.py", "test_rt"),
            ("tests/test_z.py", "test_xf"),
        ]:
            proof = ok.replace('tests/test_x.py›"test_real"', f'{path}›"{name}"', 1)
            r = gate_proofs(ctx(f"H-1\tW0.1\tgreen\t{proof}\t\n"))
            check(
                f"3 proofs fail on skipped {name}", r.status == "FAIL" and "is skipped" in r.detail
            )

        # 4 ruff — must name the planted rule, so a missing tool cannot pass for a caught defect
        lint = root / "lint"
        lint.mkdir()
        (lint / "bad.py").write_text("import os\n", encoding="utf-8")
        r = gate_ruff(ctx("H-1\tW0.1\tbuilding\t\t\n", at=lint))
        check("4 ruff fails naming F401", r.status == "FAIL" and "F401" in r.detail)
        code, out = _run([sys.executable, "-c", "import time; time.sleep(5)"], lint, timeout=1)
        check("4/5 a hung tool times out as a failure", code == 124 and "timed out" in out)
        r = _tool_gate(["citewatch-no-such-tool-xyz"], lint, "")
        check(
            "4/5 a missing tool is a FAIL, never a pass (L-3)",
            r.status == "FAIL" and "citewatch-no-such-tool-xyz" in r.detail,
        )

        # 5 pyright
        types = root / "types"
        types.mkdir()
        (types / "bad.py").write_text('x: int = "a"\n', encoding="utf-8")
        (types / "pyrightconfig.json").write_text("{}", encoding="utf-8")
        r = gate_pyright(ctx("H-1\tW0.1\tbuilding\t\t\n", at=types))
        check("5 pyright fails naming bad.py", r.status == "FAIL" and "bad.py" in r.detail)

        # 6-9 pytest-backed gates, each on its own failing fixture
        pt = root / "pt"
        pt.mkdir()
        (pt / "test_fail.py").write_text(
            "import pytest\n\n"
            "def test_unit_fails():\n    assert False\n\n"
            "@pytest.mark.golden\ndef test_golden_fails():\n    assert False\n\n"
            "@pytest.mark.polite\ndef test_polite_fails():\n    assert False\n\n"
            "@pytest.mark.safety\ndef test_safety_fails():\n    assert False\n",
            encoding="utf-8",
        )
        building = "H-1\tW0.1\tbuilding\t\t\n"
        r = gate_pytest(ctx(building, at=pt))
        check(
            "6 pytest fails naming the failing test",
            r.status == "FAIL" and "test_unit_fails" in r.detail,
        )
        never_low = lambda _root: Result("PASS", "not reached")  # noqa: E731
        r = gate_golden(ctx(building, at=pt), min_python=never_low)
        check(
            "7 golden fails naming the failing test",
            r.status == "FAIL" and "test_golden_fails" in r.detail,
        )
        skipped = root / "skipped"
        skipped.mkdir()
        (skipped / "test_s.py").write_text(
            "import pytest\n\n@pytest.mark.golden\n@pytest.mark.skip\ndef test_g():\n    pass\n\n"
            "@pytest.mark.skip\ndef test_u():\n    pass\n",
            encoding="utf-8",
        )
        r = gate_golden(ctx(building, at=skipped), min_python=never_low)
        check(
            "7 golden fails when every golden test is skipped",
            r.status == "FAIL" and "no golden test passed" in r.detail,
        )
        r = gate_pytest(ctx(building, at=skipped))
        check(
            "6 pytest fails when every unit test is skipped",
            r.status == "FAIL" and "no unit test passed" in r.detail,
        )
        green = root / "green"
        green.mkdir()
        (green / "test_g.py").write_text(
            "import pytest\n\n@pytest.mark.golden\ndef test_g():\n    pass\n", encoding="utf-8"
        )
        r = gate_golden(
            ctx(building, at=green),
            min_python=lambda _root: Result("FAIL", "golden on Python 3.11: boom"),
        )
        check(
            "7 golden fails when the Python 3.11 replay fails",
            r.status == "FAIL" and "3.11" in r.detail,
        )
        seen: list[list[str]] = []

        def fake(code: int, out: str, boom: bool = False) -> Runner:
            def run(cmd: list[str], _cwd: Path, _env: dict[str, str]):
                seen.append(cmd)
                if boom:
                    raise subprocess.TimeoutExpired(cmd, 900)
                return subprocess.CompletedProcess(cmd, code, out, "")

            return run

        uv_here = lambda _n: "/usr/bin/uv"  # noqa: E731
        for label, runner, needle in [
            ("a failing replay", fake(1, "1 failed"), "golden on Python 3.11"),
            ("an all-skipped replay", fake(0, "1 skipped"), "golden on Python 3.11"),
            ("a timed-out replay", fake(0, "", boom=True), "timed out"),
        ]:
            r = golden_min_python(green, which=uv_here, runner=runner)
            check(
                f"7 the Python 3.11 leg fails on {label}", r.status == "FAIL" and needle in r.detail
            )
        r = golden_min_python(green, which=uv_here, runner=fake(0, "2 passed in 0.1s"))
        check(
            "7 the Python 3.11 leg really asks uv for Python 3.11 and the golden marker",
            r.status == "PASS"
            and seen[-1][:4] == ["uv", "run", "--python", MIN_PYTHON]
            and seen[-1][-2:] == ["-m", "golden"],
        )
        r = gate_golden(
            ctx(building, at=green),
            min_python=lambda rt: golden_min_python(rt, which=lambda _n: None),
        )
        check(
            "7 golden fails when Python 3.11 cannot be run (no uv)",
            r.status == "FAIL" and "uv not found" in r.detail,
        )
        r = gate_politeness(ctx("H-1\tW0.1\tbuilding\t\t\n", at=pt))
        check(
            "8 politeness fails naming the failing test",
            r.status == "FAIL" and "test_polite_fails" in r.detail,
        )
        line = fetch_audit._line
        rude_logs = {
            "robots": ([line(robots="disallowed")], "although robots disallowed"),
            "rate": ([line(), line(at="2026-11-15T10:00:00.4+00:00")], "0.400 s apart"),
            "retry after a block": (
                [line(status=403, outcome="blocked"), line(at="2026-11-15T10:00:09+00:00")],
                "after it was blocked",
            ),
            "two user agents": (
                [line(), line(url="https://a.com/", host="a.com", user_agent="Other/1")],
                "different user agents",
            ),
            "unparseable line": (["{oops"], "not JSON"),
            "request after a robots refusal": (
                [
                    line(robots="disallowed", outcome="robots_disallowed", status=None, bytes=None),
                    line(at="2026-11-15T10:00:09+00:00"),
                ],
                "after robots refused it",
            ),
            "more than three requests for a page": (
                [line(at=f"2026-11-15T10:00:0{i}+00:00") for i in range(0, 8, 2)],
                "requested 4 times",
            ),
            "a skipped line with a status": (
                [line(robots="disallowed", outcome="robots_disallowed", status=200)],
                "status and bytes must be null",
            ),
        }
        for label, (lines, needle) in rude_logs.items():
            rude = root / f"rude-{label.replace(' ', '-')}"
            (rude / "data").mkdir(parents=True)
            (rude / "data" / "fetch_log.jsonl").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
            r = gate_politeness(ctx("H-1\tW0.1\tbuilding\t\t\n", at=rude))
            check(
                f"8 politeness fails on a log breaking {label}",
                r.status == "FAIL" and needle in r.detail,
            )
        check(
            "8 politeness reports SKIP with no logs and no tests",
            gate_politeness(ctx("H-1\tW0.1\tbuilding\t\t\n", at=root / "lint")).status == "SKIP",
        )
        nocache = root / "no-cache"
        r = gate_safety(ctx("H-1\tW0.1\tbuilding\t\t\n", at=pt), cache=nocache)
        check(
            "9 safety fails on a failing safety test",
            r.status == "FAIL" and "test_safety_fails" in r.detail,
        )
        empty = root / "empty"
        empty.mkdir()
        (empty / "test_none.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
        check(
            "7 golden reports SKIP, not PASS, with no golden tests",
            gate_golden(ctx(building, at=empty), min_python=never_low).status == "SKIP",
        )
        leak = root / "leak"
        leak.mkdir()
        (leak / "k.py").write_text('K = "sk-ant-' + "Q" * 30 + '"\n', encoding="utf-8")
        r = gate_safety(ctx("H-1\tW0.1\tbuilding\t\t\n", at=leak), cache=nocache)
        check("9 safety fails on a leaked key", r.status == "FAIL" and "anthropic key" in r.detail)
        body = root / "body"
        (body / "data").mkdir(parents=True)
        (body / "data" / "page.html").write_text("<html><body>x</body></html>", encoding="utf-8")
        r = gate_safety(ctx("H-1\tW0.1\tbuilding\t\t\n", at=body), cache=nocache)
        check(
            "9 safety fails on a stored page body", r.status == "FAIL" and "page.html" in r.detail
        )

        # 10 build
        broken = root / "broken"
        broken.mkdir()
        (broken / "pyproject.toml").write_text("[project\nname=", encoding="utf-8")
        r = gate_build(Ctx("W0.1", broken, graph, [], specs), smoke=[])
        check(
            "10 build fails naming the broken pyproject (not a missing uv)",
            r.status == "FAIL" and "expected `]`" in r.detail and "No such file" not in r.detail,
        )
        proj = root / "proj"
        (proj / "src" / "fakepkg").mkdir(parents=True)
        (proj / "src" / "fakepkg" / "__init__.py").write_text(
            "import os\n\n"
            "def main():\n"
            "    creds = [k for k in os.environ\n"
            "             if k.endswith(('_API_KEY', '_TOKEN', '_SECRET'))\n"
            "             or k == 'ANTHROPIC_PROFILE']\n"
            "    raise SystemExit(5 if creds else 3)\n",
            encoding="utf-8",
        )
        (proj / "pyproject.toml").write_text(
            '[project]\nname = "fakepkg"\nversion = "0.0.1"\n'
            '[project.scripts]\nfakecli = "fakepkg:main"\n'
            '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
            '[tool.hatch.build.targets.wheel]\npackages = ["src/fakepkg"]\n',
            encoding="utf-8",
        )
        r = gate_build(Ctx("W0.1", proj, graph, [], specs), smoke=[(["fakecli", "--version"], 0)])
        check(
            "10 build fails when a smoke command exits wrongly, naming it",
            r.status == "FAIL" and "fakecli --version: exit 3, expected 0" in r.detail,
        )
        planted = {
            "OPENAI_API_KEY": "x",
            "ANTHROPIC_AUTH_TOKEN": "x",
            "CLAUDE_CODE_OAUTH_TOKEN": "x",
            "ANTHROPIC_PROFILE": "x",
        }
        saved_env = {k: os.environ.get(k) for k in planted}
        os.environ.update(planted)
        try:
            r = gate_build(Ctx("W0.1", proj, graph, [], specs), smoke=[(["fakecli"], 3)])
        finally:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        check(
            "10 smoke commands run with every credential removed (expected exit seen)",
            r.status == "PASS",
        )
        pyproject = proj / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace(
                'version = "0.0.1"\n',
                'version = "0.0.1"\ndependencies = ["citewatch-no-such-dependency-xyz==9.9.9"]\n',
            ),
            encoding="utf-8",
        )
        r = gate_build(Ctx("W0.1", proj, graph, [], specs), smoke=[])
        check(
            "10 build fails when the wheel cannot install",
            r.status == "FAIL" and "install wheel" in r.detail,
        )

        # 11 changed-tests, through the gate itself
        repo = root / "repo"
        rspecs = repo / "specs" / "W0.1-x"
        rspecs.mkdir(parents=True)
        (repo / "tests").mkdir()
        (repo / "tests" / "test_old.py").write_text("def test_o():\n    pass\n", encoding="utf-8")
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        _run(["git", "init", "-q"], repo)
        _run(["git", "add", "-A"], repo)
        _run([*git, "commit", "-q", "-m", "a"], repo)
        head = _run(["git", "rev-parse", "HEAD"], repo)[1]
        (rspecs / ".base").write_text(head + "\n", encoding="utf-8")

        def changed() -> Result:
            return gate_changed_tests(Ctx("W0.1", repo, graph, [], repo / "specs"))

        (repo / "src").mkdir()
        (repo / "src" / "committed.py").write_text("x = 1\n", encoding="utf-8")
        _run(["git", "add", "-A"], repo)
        _run([*git, "commit", "-q", "-m", "source only"], repo)
        r = changed()
        check(
            "11 fails on a committed source-only change",
            r.status == "FAIL" and "committed.py" in r.detail,
        )
        _run(["git", "rm", "-q", "src/committed.py"], repo)
        _run([*git, "commit", "-q", "-m", "undo"], repo)
        (repo / "src").mkdir(exist_ok=True)  # git rm removed the emptied folder
        (repo / "src" / "café.py").write_text("x = 1\n", encoding="utf-8")
        r = changed()
        check(
            "11 fails when only source changed, even with a non-ASCII name",
            r.status == "FAIL" and "café.py" in r.detail,
        )
        (repo / "tests" / "test_old.py").unlink()
        r = changed()
        check("11 a deleted test does not count as a changed test", r.status == "FAIL")
        (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
        check("11 an __init__.py does not count as a test change", changed().status == "FAIL")
        (repo / "tests" / "test_new.py").write_text("def test_n():\n    pass\n", encoding="utf-8")
        check("11 passes when tests changed with source", changed().status == "PASS")
        (rspecs / ".base").write_text("deadbeef\n", encoding="utf-8")
        r = changed()
        check(
            "11 an unknown base commit fails naming it",
            r.status == "FAIL" and "deadbeef" in r.detail,
        )

        # 12 records
        cat = parse_catalog(hdr + "H-1\tW0.1\tgreen\t\t\n")
        changelog = root / "changelog.md"
        criteria = specs / "W0.1-harness" / "criteria.md"
        run_state = specs / "W0.1-harness" / "RUN-STATE.md"
        changelog.write_text("[FEAT] [W0.1] — harness\n", encoding="utf-8")
        criteria.write_text("H-1\n", encoding="utf-8")
        run_state.write_text("ok\n", encoding="utf-8")
        check("12 records passes when complete", records_problems("W0.1", cat, root, specs) == [])
        for path, broken, needle in [
            (changelog, "[FEAT] [N1.1] — other\n", "changelog.md has no [W0.1] entry"),
            (criteria, "H-10\n", "criteria.md misses H-1"),
            (run_state, None, "RUN-STATE.md missing"),
        ]:
            saved = path.read_text(encoding="utf-8")
            if broken is None:
                path.unlink()
            else:
                path.write_text(broken, encoding="utf-8")
            r = gate_records(Ctx("W0.1", root, graph, cat, specs))
            check(f"12 records fails naming: {needle}", r.status == "FAIL" and needle in r.detail)
            path.write_text(saved, encoding="utf-8")

        # every gate is reported, whatever failed before it
        ok = lambda _c: Result("PASS", "second ran")  # noqa: E731

        def boom(_c: Ctx) -> Result:
            raise ZeroDivisionError("planted crash")

        two = lambda _c: Result("FAIL", "first problem\nsecond problem")  # noqa: E731
        lines, failed = run_gates(ctx(building), [("a", two), ("b", boom), ("c", ok)])
        check(
            "every gate is reported, with every detail line, after a failure and a crash",
            failed == 2
            and len(lines) == 4
            and "second problem" in lines[1]
            and "crashed" in lines[2]
            and "second ran" in lines[3],
        )
    print("self-test", "PASSED" if failures == 0 else f"FAILED ({failures})")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    safe_console()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("node", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--no-log", action="store_true", help="do not write a log under .harness/")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.node:
        ap.error("node is required")
    try:
        ctx = Ctx(args.node, ROOT, load_graph(), load_catalog(), SPECS_DIR)
    except (HarnessError, OSError) as exc:
        print(f"node-converge: cannot read inputs: {exc}")
        return 1
    if args.node not in ctx.nodes:
        print(f"node-converge: unknown node {args.node}")
        return 1
    lines = [f"node-converge {args.node} — {dt.datetime.now().isoformat(timespec='seconds')}"]
    gate_lines, failed = run_gates(ctx, GATES)
    lines.extend(gate_lines)
    lines.append(
        f"RESULT: {'FAIL' if failed else 'PASS'} "
        f"({failed} failing gate{'s' if failed != 1 else ''})"
    )
    report = "\n".join(lines)
    print(report)
    if args.no_log:
        return 1 if failed else 0
    log_dir = ROOT / ".harness" / args.node
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    (log_dir / f"converge-{stamp}.txt").write_text(report + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
