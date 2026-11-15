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
from typing import Annotated, Any, NoReturn

import typer

from citewatch import __version__
from citewatch.cost import PriceError, estimate_run, load_prices, price_age_days
from citewatch.env import MissingKeyError, key_status, load_dotenv
from citewatch.ledger import Ledger
from citewatch.schemas import (
    Citation,
    ConfigError,
    StudyConfig,
    load_questions,
    load_study_config,
    provider_of,
)
from citewatch.store import RawStore

EXIT_OK, EXIT_ERROR, EXIT_CAP, EXIT_PENDING = 0, 2, 3, 4
PRICE_MAX_AGE_DAYS = 7  # doctor flags prices.yaml older than this
NOT_BUILT = {"score": "M3.1", "report": "B4.1"}
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


def _fail(as_json: bool, command: str, message: str, code: int = EXIT_ERROR) -> NoReturn:
    _emit(
        as_json,
        {"ok": False, "command": command, "error": message},
        f"citewatch {command}: {message}",
    )
    raise typer.Exit(code)


def _not_built(command: str, as_json: bool) -> NoReturn:
    _fail(as_json, command, f"not built yet (node {NOT_BUILT[command]})")


def _study_prices(folder: Path) -> Path | None:
    """A study may carry its own prices.yaml, which replaces the packaged one."""
    p = folder / "prices.yaml"
    return p if p.is_file() else None


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
    contact: Annotated[
        str | None,
        typer.Option("--contact", help="A project page or email site owners can reach you at."),
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """Write study.yaml, a questions template, a rubric and .env.example. Never overwrites."""
    targets = {name: folder / name for name in TEMPLATES}
    # is_symlink catches a dangling link that exists() would miss
    existing = sorted(str(p) for p in targets.values() if p.exists() or p.is_symlink())
    if existing:
        _fail(as_json, "init", f"refusing to overwrite {', '.join(existing)}")
    agent = None
    if contact is not None:
        agent = f"citewatch/{__version__} ({'+' if contact.startswith('http') else ''}{contact})"
        try:
            StudyConfig._names_tool_and_contact(agent)  # same rule as study.yaml (D-25)
        except ValueError as exc:
            _fail(as_json, "init", f"--contact: {exc}")
    folder.mkdir(parents=True, exist_ok=True)
    for name, path in targets.items():
        text = files("citewatch.templates").joinpath(TEMPLATES[name]).read_text(encoding="utf-8")
        if name == "study.yaml" and agent:
            text = text.replace(
                '"citewatch/0.1.0 (+https://example.org/your-study)"', json.dumps(agent)
            )
            lines = text.splitlines(keepends=True)
            text = "".join(ln for ln in lines if "Replace the placeholder" not in ln)
        try:
            with path.open("x", encoding="utf-8") as fh:  # exclusive create: never overwrite
                fh.write(text)
        except FileExistsError:
            _fail(as_json, "init", f"refusing to overwrite {path}")
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
        try:
            prices = load_prices(_study_prices(path.parent))
            missing = [m for m in cfg.models if m not in prices]
            age = price_age_days(prices)
            src = "study prices.yaml" if _study_prices(path.parent) else "packaged prices.yaml"
            if missing:
                checks.append(
                    {"check": "prices", "ok": False, "detail": f"no price for {', '.join(missing)}"}
                )
            elif age > PRICE_MAX_AGE_DAYS:
                checks.append(
                    {
                        "check": "prices",
                        "ok": False,
                        "detail": (
                            f"{src} was checked {age} days ago; re-check the provider pricing "
                            "pages and update checked_on, or put a prices.yaml in the study folder"
                        ),
                    }
                )
            else:
                checks.append(
                    {"check": "prices", "ok": True, "detail": f"{src}, checked {age} days ago"}
                )
        except PriceError as exc:
            checks.append({"check": "prices", "ok": False, "detail": str(exc)})
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
    path = _study_file(study)
    try:
        cfg = load_study_config(path)
        qs = load_questions(path.parent / cfg.questions_path, cfg)
        prices = load_prices(_study_prices(path.parent))
    except (ConfigError, PriceError) as exc:
        _fail(as_json, "ask", str(exc))
    if questions:
        wanted = [x.strip() for x in questions.split(",") if x.strip()]
        unknown = sorted(set(wanted) - {q.id for q in qs})
        if unknown:
            _fail(as_json, "ask", f"unknown question ids: {', '.join(unknown)}")
        qs = [q for q in qs if q.id in wanted]
    from citewatch.runners.schedule import ask_key

    stored = RawStore(path.parent)
    missing = {
        m: sum(not stored.has("ask", ask_key(cfg, run, q, m)) for q in qs) for m in cfg.models
    }
    try:
        est = estimate_run(missing, cfg.models, prices)  # a resume counts only what is missing
    except PriceError as exc:
        _fail(as_json, "ask", str(exc))
    cap = max_cost if max_cost is not None else cfg.max_cost_usd
    age = price_age_days(prices)
    if age > PRICE_MAX_AGE_DAYS and not as_json:
        typer.echo(
            f"warning: prices were checked {age} days ago; estimates and the cap may be low",
            err=True,
        )
    plan = {
        "run": run,
        "questions": len(qs),
        "models": list(cfg.models),
        "estimate": est,
        "cap_usd": cap,
        "prices_age_days": price_age_days(prices),
    }
    if dry_run:
        lines = [f"run {run}: {len(qs)} questions x {len(cfg.models)} models, no calls made"]
        lines += [
            f"  {m}: {v['calls']} calls, about ${v['usd']:.2f}" for m, v in est["per_model"].items()
        ]
        lines.append(
            f"  total about ${est['total_usd']:.2f}"
            + (f" (cap ${cap:.2f})" if cap is not None else " (no cap)")
        )
        _emit(as_json, {"ok": True, "command": "ask", "dry_run": True, **plan}, "\n".join(lines))
        raise typer.Exit(EXIT_OK)
    if cap is not None and est["total_usd"] > cap:
        _fail(
            as_json,
            "ask",
            f"estimated ${est['total_usd']:.4g} is over the cap ${cap:.4g}; nothing was asked. "
            "Raise --max-cost or max_cost_usd, or ask fewer questions.",
            EXIT_CAP,
        )
    load_dotenv(path.parent / ".env")
    load_dotenv(Path(".env"))
    from citewatch.runners import make_runner
    from citewatch.runners.schedule import ask_run

    try:
        runners = {m: make_runner(m) for m in cfg.models}
    except MissingKeyError as exc:
        _fail(as_json, "ask", str(exc))
    except ImportError as exc:
        _fail(
            as_json,
            "ask",
            f"{exc}; install the provider SDKs with `pip install 'citewatch[anthropic,openai]'`",
        )
    base = path.parent
    from citewatch.runners.schedule import question_order

    run_dir = base / "data" / "runs" / f"run-{run}"
    run_dir.mkdir(parents=True, exist_ok=True)
    order = [q.id for q in question_order(qs, cfg.seeds["order"], run)]
    (run_dir / "order.json").write_text(  # written before any call
        json.dumps({"seed": cfg.seeds["order"], "run": run, "order": order}, indent=2) + "\n",
        encoding="utf-8",
    )
    import signal

    def _term(*_a: Any) -> None:
        raise KeyboardInterrupt  # SIGTERM stops like Ctrl-C: in-flight calls are recorded

    try:
        old_term = signal.signal(signal.SIGTERM, _term)
    except (ValueError, OSError):  # not the main thread
        old_term = None
    try:
        res = ask_run(
            qs,
            cfg,
            run=run,
            runners=runners,
            store=RawStore(base),
            ledger=Ledger(run_dir),
            prices=prices,
            cap_usd=cap,
            spend_ledger=base / "data" / "spend-ledger.jsonl",  # one line per paid call (D-19)
        )
    finally:
        if old_term is not None:
            signal.signal(signal.SIGTERM, old_term)
    nothing = res.asked == 0 and bool(res.errors)  # every attempted call failed (D-41, v4 L5)
    summary = {
        "ok": not (res.stopped_at_cap or res.interrupted or nothing),
        "command": "ask",
        **plan,
        "asked": res.asked,
        "cached": res.cached,
        "errors": res.errors,
        "stopped_at_cap": res.stopped_at_cap,
        "interrupted": res.interrupted,
        "cancelled": res.cancelled,
        "spent_usd": res.spent_usd,
    }
    text = (
        f"run {run}: asked {res.asked}, already stored {res.cached}, "
        f"errors {len(res.errors)}, spent ${res.spent_usd:.2f}"
    )
    if res.errors:
        kinds = sorted({e["error"] for e in res.errors})
        text += f" (errors: {', '.join(kinds)}; rerun to retry them)"
    if res.stopped_at_cap:
        text += (
            f"; stopped at the cap with {res.skipped_for_cap} left. "
            "Rerun with a higher cap to resume."
        )
    if res.interrupted:
        text += f"; interrupted, {res.cancelled} calls not made. Rerun to resume."
    if nothing and not (res.stopped_at_cap or res.interrupted):
        text += "; nothing was answered: check the keys and the errors above"
    _emit(as_json, summary, text)
    if res.stopped_at_cap:
        raise typer.Exit(EXIT_CAP)
    raise typer.Exit(EXIT_ERROR if res.interrupted or nothing else EXIT_OK)


@app.command()
def extract(study: StudyOpt = Path("."), as_json: JsonOpt = False) -> None:
    """Rebuild citations and consulted sources from the raw store."""
    from citewatch.extract import run_extract, unique_cited_urls

    path = _study_file(study)
    try:
        cfg = load_study_config(path)
    except ConfigError as exc:
        _fail(as_json, "extract", str(exc))
    try:
        qs = load_questions(path.parent / cfg.questions_path, cfg)
    except ConfigError as exc:
        _fail(as_json, "extract", str(exc))
    res = run_extract(path.parent, cfg, qs)
    unique = unique_cited_urls(res.citations)
    summary = {
        "ok": not res.problems,
        "command": "extract",
        "answers": len(res.answers),
        "citations": len(res.citations),
        "unique_cited_urls": sum(len(v) for v in unique.values()),
        "consulted": len(res.consulted),
        "skipped_urls": sum(res.skipped_urls.values()),
        "stale": res.stale,
        "problems": res.problems,
    }
    text = (
        f"{len(res.answers)} answers, {len(res.citations)} citations "
        f"({summary['unique_cited_urls']} unique per answer), {len(res.consulted)} consulted"
    )
    if res.problems:
        text += f"; {len(res.problems)} envelopes could not be read"
    _emit(as_json, summary, text)
    raise typer.Exit(EXIT_ERROR if res.problems else EXIT_OK)


def fetch_logs_for(base: Path) -> list[Path]:
    """Every fetch log the gate-8 audit would read alongside this study's: its own, and its
    sibling studies' when it lives in a `studies/` folder, since the audit's rules hold across
    all of them (A2.2 v2 M-3)."""
    roots = [base / "data"]
    if base.parent.name == "studies":
        roots = [s / "data" for s in sorted(base.parent.iterdir()) if s.is_dir()]
        repo_data = base.parent.parent / "data"
        if repo_data.is_dir():
            roots.append(repo_data)
    found: set[Path] = set()
    for r in roots:
        if r.is_dir():
            found |= {*r.rglob("fetch_log*.jsonl"), *r.rglob("fetch_log*.jsonl.gz")}
    return sorted(found)


@app.command()
def fetch(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List hosts and URL counts only.")
    ] = False,
    study: StudyOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Fetch cited pages politely and resolve their dates."""
    import math as _math
    from collections import Counter

    from citewatch.dates import analyse as date_analyse
    from citewatch.dates import build_page_meta, host_lastmods, write_page_meta
    from citewatch.dates.sitemaps import origins_of
    from citewatch.fetch import FetchLog, PageHistory, PoliteClient, fetch_key, fetch_pages
    from citewatch.fetch.keys import host_of

    path = _study_file(study)
    try:
        cfg = load_study_config(path)
    except ConfigError as exc:
        _fail(as_json, "fetch", str(exc))
    base = path.parent
    cites = base / "data" / "citations.jsonl"
    if not cites.is_file():
        _fail(as_json, "fetch", f"{cites} not found; run `citewatch extract` first")
    urls: list[str] = []
    for n, line in enumerate(cites.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            urls.append(Citation.model_validate_json(line).url)  # canonical URLs only (FET-05)
        except ValueError as exc:
            _fail(as_json, "fetch", f"{cites}:{n}: not a citation row ({exc})")
    store = RawStore(base)
    todo = [u for u in dict.fromkeys(urls) if not store.has("fetch", fetch_key(u))]
    hosts = Counter(host_of(u) for u in todo)
    # one robots.txt per new host plus its pages, 1 s apart; at most 8 hosts at once
    per_host = [n + 1 for n in hosts.values()]
    min_s = max(max(per_host, default=0), _math.ceil(sum(per_host) / 8))
    plan = {
        "urls": len(dict.fromkeys(urls)),
        "to_fetch": len(todo),
        "hosts": len(hosts),
        "min_seconds": min_s,
        "top_hosts": dict(hosts.most_common(10)),
    }
    if dry_run:
        lines = [f"{len(todo)} of {plan['urls']} cited URLs to fetch on {len(hosts)} hosts"]
        lines += [f"  {h}: {c}" for h, c in hosts.most_common(10)]
        lines.append(f"  at least {min_s} s at 1 request per second per host, 8 hosts at once")
        _emit(as_json, {"ok": True, "command": "fetch", "dry_run": True, **plan}, "\n".join(lines))
        raise typer.Exit(EXIT_OK)
    sample = base / "data" / "support_sample.jsonl"
    keep: frozenset[str] = frozenset()
    if sample.is_file():
        keep = frozenset(
            json.loads(x)["url"] for x in sample.read_text(encoding="utf-8").splitlines() if x
        )
    log_path = base / "data" / "fetch_log.jsonl"
    client = PoliteClient(
        cfg.user_agent,
        FetchLog(log_path),
        history=PageHistory.from_logs(fetch_logs_for(base)),
        store=store,
    )
    try:
        res = fetch_pages(todo, client=client, store=store, keep_text=keep, analyse=date_analyse)
        lastmods: dict[str, str] = {}
        all_urls = list(dict.fromkeys(urls))
        if not res.interrupted:
            for origin in origins_of(all_urls):  # sitemaps listed in robots.txt only (DAT-05)
                lastmods.update(host_lastmods(client, store, origin))
        metas = build_page_meta(base, all_urls, lastmods)
        write_page_meta(base, metas)
    finally:
        client.close()
    summary = {
        "ok": not res.interrupted and not res.errors,
        "command": "fetch",
        **plan,
        "fetched": res.fetched,
        "cached": res.cached,
        "outcomes": dict(res.outcomes),
        "dated": sum(1 for m in metas if m.effective_date is not None),
        "errors": res.errors,
        "interrupted": res.interrupted,
    }
    text = f"fetched {res.fetched}, already stored {res.cached}: " + ", ".join(
        f"{k} {v}" for k, v in sorted(res.outcomes.items())
    )
    if res.interrupted:
        text += "; interrupted. Rerun to resume."
    _emit(as_json, summary, text)
    raise typer.Exit(EXIT_ERROR if res.interrupted or res.errors else EXIT_OK)


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
        message = f"unexpected error: {type(exc).__name__}: {' '.join(str(exc).split())}"
        if "--json" in (argv if argv is not None else sys.argv[1:]):
            typer.echo(json.dumps({"ok": False, "error": message}))
        else:
            typer.echo(f"citewatch: {message}", err=True)
        return EXIT_ERROR
    # without standalone mode the framework returns an Exit's code instead of raising it
    return rv if isinstance(rv, int) and not isinstance(rv, bool) else EXIT_OK


def entry() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entry()
