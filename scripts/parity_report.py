"""Parity report for a run (SMK-04): were both models asked the same way, and how did they answer?

uv run python scripts/parity_report.py studies/uk-health --run 0
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
from collections import defaultdict
from pathlib import Path


def _loc(req: dict) -> str:
    for t in req.get("tools") or []:
        loc = t.get("user_location") or {}
        if loc:
            return f"{loc.get('city')}, {loc.get('country')}"
    return "none"


def _cap(req: dict) -> int | None:
    if "max_tool_calls" in req:
        return req["max_tool_calls"]
    for t in req.get("tools") or []:
        if "max_uses" in t:
            return t["max_uses"]
    return None


def report(study: Path, run: int) -> str:
    data = study / "data"
    raw = defaultdict(list)
    for f in sorted((data / "raw" / "ask").glob("*/*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("run") == run:
            raw[d["model"]].append(d)
    answers = defaultdict(list)
    for line in (data / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        a = json.loads(line)
        if a["run"] == run:
            answers[a["model"]].append(a)
    cites: dict[tuple[str, str], set[str]] = defaultdict(set)
    for line in (data / "citations.jsonl").read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        if c["run"] == run:
            cites[(c["model"], c["question_id"])].add(c["url"])
    rows = [
        "| | " + " | ".join(sorted(answers)) + " |",
        "| --- |" + " --- |" * len(answers),
    ]

    def row(label: str, fn) -> None:
        rows.append(f"| {label} | " + " | ".join(str(fn(m)) for m in sorted(answers)) + " |")

    row("answers", lambda m: len(answers[m]))
    row("location sent", lambda m: ", ".join(sorted({_loc(r["request"]) for r in raw[m]})))
    row(
        "search cap sent",
        lambda m: ", ".join(str(x) for x in sorted({_cap(r["request"]) or 0 for r in raw[m]})),
    )
    row("same prompt hash", lambda m: len({r["prompt_hash"] for r in raw[m]}) == 1)
    row("searches per answer (max)", lambda m: max(a["searches"] for a in answers[m]))
    row(
        "searches per answer (mean)",
        lambda m: round(statistics.fmean(a["searches"] for a in answers[m]), 2),
    )
    row("words (median)", lambda m: statistics.median(a["word_count"] for a in answers[m]))
    row("words (max)", lambda m: max(a["word_count"] for a in answers[m]))
    row("over 150 words", lambda m: sum(a["over_length"] for a in answers[m]))
    row("refusals", lambda m: sum(a["refusal"] for a in answers[m]))
    row("transport errors", lambda m: sum(a["error"] is not None for a in answers[m]))
    row("search errors", lambda m: sum(bool(a["search_errors"]) for a in answers[m]))
    row(
        "unique cited URLs per answer (mean)",
        lambda m: round(statistics.fmean(len(cites[(m, a["question_id"])]) for a in answers[m]), 2),
    )
    row(
        "answers with no citation",
        lambda m: sum(not cites[(m, a["question_id"])] for a in answers[m]),
    )
    row(
        "cost per answer (mean, USD)",
        lambda m: round(statistics.fmean(r["cost_usd"] for r in raw[m]), 4),
    )
    prompts = {r["prompt_hash"] for rs in raw.values() for r in rs}
    same = len(prompts) == 1
    head = f"# Parity report: {study.name}, run {run}\n\nOne instruction, both models: {same}.\n\n"
    return head + "\n".join(rows) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("study", type=Path)
    ap.add_argument("--run", type=int, default=0)
    a = ap.parse_args()
    text = report(a.study, a.run)
    out = a.study / "data" / "runs" / f"run-{a.run}" / "parity.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
