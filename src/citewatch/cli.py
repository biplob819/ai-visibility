"""The `citewatch` command line (Tech Spec §5, STO-03, STO-04).

Exit codes: 0 done, 2 configuration or runtime error, 3 stopped at the cost cap, 4 judging
pending. Commands whose node is not built yet exit 2 and say which node, never a fake success.
"""

from __future__ import annotations

import json
import math
import sys
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

import typer

from citewatch import __version__
from citewatch.env import key_status, load_dotenv
from citewatch.schemas import ConfigError, load_study_config, provider_of

EXIT_OK, EXIT_ERROR, EXIT_CAP, EXIT_PENDING = 0, 2, 3, 4
NOT_BUILT = {"ask": "N1.2", "extract": "A2.1", "fetch": "A2.2", "score": "M3.1", "report": "B4.1"}
TEMPLATES = {
    "study.yaml": "study.yaml",
    "questions.jsonl": "questions.jsonl",
    "RUBRIC.md": "RUBRIC.md",
    ".env.example": "env.example",
}

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Measure which websites AI answers with web search cite, and how fresh those pages are.",
    epilog="Exit codes: 0 done, 2 error, 3 stopped at the cost cap, 4 judging pending.",
)
JsonOpt = Annotated[bool, typer.Option("--json", help="Print one JSON object instead of text.")]
StudyOpt = Annotated[
    Path, typer.Option("--study", help="A study folder or its study.yaml.", show_default=True)
]


def _emit(as_json: bool, payload: dict[str, Any], text: str) -> None:
    if as_json:
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(text)


def _fail(as_json: bool, command: str, message: str, code: int = EXIT_ERROR) -> None:
    _emit(
        as_json,
        {"ok": False, "command": command, "error": message},
        f"citewatch {command}: {message}",
    )
    raise typer.Exit(code)


def _not_built(command: str, as_json: bool) -> None:
    _fail(as_json, command, f"not built yet (node {NOT_BUILT[command]})")


def _study_file(study: Path) -> Path:
    return study / "study.yaml" if study.is_dir() else study


def _check_cap(value: float | None, as_json: bool, command: str) -> None:
    if value is not None and (not math.isfinite(value) or value <= 0):
        _fail(as_json, command, f"--max-cost must be a positive amount in USD, got {value}")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"citewatch {__version__}")
        raise typer.Exit(EXIT_OK)


@app.callback()
def main_options(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=version_callback, is_eager=True, help="Print the version."
        ),
    ] = False,
) -> None:
    """Measure which websites AI answers with web search cite, and how fresh those pages are."""


@app.command()
def init(
    folder: Annotated[Path, typer.Argument(help="Folder for the new study.")] = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Write study.yaml, a questions template, a rubric and .env.example. Never overwrites."""
    targets = {name: folder / name for name in TEMPLATES}
    existing = sorted(str(p) for p in targets.values() if p.exists())
    if existing:
        _fail(as_json, "init", f"refusing to overwrite {', '.join(existing)}")
    folder.mkdir(parents=True, exist_ok=True)
    for name, path in targets.items():
        path.write_text(
            files("citewatch.templates").joinpath(TEMPLATES[name]).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    created = sorted(str(p) for p in targets.values())
    _emit(
        as_json,
        {"ok": True, "command": "init", "created": created},
        "Created "
        + ", ".join(created)
        + ". Next: write your rubric and questions, then run `citewatch doctor`.",
    )


@app.command()
def doctor(study: StudyOpt = Path("."), as_json: JsonOpt = False) -> None:
    """Check Python, the study file, which provider keys are set (never their values), and the
    user agent. Exits 2 when anything required is missing."""
    checks: list[dict[str, Any]] = []
    ok_py = sys.version_info >= (3, 11)
    checks.append({"check": "python", "ok": ok_py, "detail": sys.version.split()[0]})
    path = _study_file(study)
    load_dotenv(path.parent / ".env")
    load_dotenv(Path(".env"))
    providers: list[str] = []
    try:
        cfg = load_study_config(path)
        checks.append({"check": "study", "ok": True, "detail": f"{path} ({cfg.name})"})
        checks.append({"check": "user agent", "ok": True, "detail": cfg.user_agent})
        providers = sorted({provider_of(m) for m in cfg.models})
    except ConfigError as exc:
        hint = " (run `citewatch init` to create one)" if not path.exists() else ""
        checks.append({"check": "study", "ok": False, "detail": f"{exc}{hint}"})
    for var, present in key_status(providers).items():
        checks.append({"check": var, "ok": present, "detail": "set" if present else "missing"})
    ok = all(c["ok"] for c in checks)
    lines = [f"{'ok ' if c['ok'] else 'FIX'}  {c['check']}: {c['detail']}" for c in checks]
    lines.append("ready" if ok else "not ready: fix the lines marked FIX")
    _emit(as_json, {"ok": ok, "command": "doctor", "checks": checks}, "\n".join(lines))
    raise typer.Exit(EXIT_OK if ok else EXIT_ERROR)


@app.command()
def ask(
    run: Annotated[
        int, typer.Option("--run", min=0, max=2, help="0 smoke, 1 or 2 study runs.")
    ] = 1,
    questions: Annotated[
        str | None, typer.Option("--questions", help="Comma-separated ids.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print calls and cost, then exit.")
    ] = False,
    max_cost: Annotated[float | None, typer.Option("--max-cost", help="Hard cap in USD.")] = None,
    study: StudyOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Ask every question on every model with web search on."""
    _check_cap(max_cost, as_json, "ask")
    _not_built("ask", as_json)


@app.command()
def extract(study: StudyOpt = Path("."), as_json: JsonOpt = False) -> None:
    """Rebuild citations and consulted sources from the raw store."""
    _not_built("extract", as_json)


@app.command()
def fetch(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List hosts and URL counts only.")
    ] = False,
    study: StudyOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Fetch cited pages politely and resolve their dates."""
    _not_built("fetch", as_json)


@app.command()
def score(
    sample_support: Annotated[bool, typer.Option("--sample-support")] = False,
    labels: Annotated[Path | None, typer.Option("--labels")] = None,
    finalise: Annotated[bool, typer.Option("--finalise")] = False,
    study: StudyOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Compute the metrics and run the support and hand-check samples."""
    _not_built("score", as_json)


@app.command()
def report(
    example: Annotated[bool, typer.Option("--example", help="Render the bundled example.")] = False,
    study: StudyOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Build the dashboard, the post's charts and domain cards."""
    _not_built("report", as_json)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code. Usage errors and unexpected exceptions exit 2 with
    one line, never a traceback and never 1 (which CI reads as a failed threshold)."""
    try:
        rv = app(args=argv, prog_name="citewatch", standalone_mode=False)
    except typer.Exit as exc:
        return int(exc.exit_code or 0)
    except typer.TyperException as exc:  # usage errors: bad option, missing argument, ...
        message = exc.format_message() if hasattr(exc, "format_message") else str(exc)
        if not message.strip():  # bare `citewatch`: help was shown, nothing went wrong
            return EXIT_OK
        typer.echo(f"citewatch: {message}", err=True)
        return EXIT_ERROR
    except typer.Abort:
        typer.echo("citewatch: aborted", err=True)
        return EXIT_ERROR
    except Exception as exc:  # one line, exit 2
        typer.echo(f"citewatch: unexpected error: {type(exc).__name__}: {exc}", err=True)
        return EXIT_ERROR
    # without standalone mode the framework returns an Exit's code instead of raising it
    return rv if isinstance(rv, int) and not isinstance(rv, bool) else EXIT_OK


def entry() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entry()
