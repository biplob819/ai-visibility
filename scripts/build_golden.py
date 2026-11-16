"""Build the golden fixture from a study's smoke run (SMK-05).

Copies the run's raw answers and fetch records, the sitemap lastmods of the cited pages, the
questions asked and the outputs they produced. Page bodies are never stored (NFR6), so the
replay starts from the fetch records' date candidates, not from HTTP bodies (D-52).

    uv run python scripts/build_golden.py studies/uk-health --run 0
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "golden" / "smoke"
OUTPUTS = ("answers.jsonl", "citations.jsonl", "consulted.jsonl", "page_meta.jsonl")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("study", type=Path)
    ap.add_argument("--run", type=int, default=0)
    a = ap.parse_args()
    data = a.study / "data"
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data" / "raw").mkdir(parents=True)
    shutil.copy(a.study / "study.yaml", OUT / "study.yaml")
    asked: set[str] = set()
    for f in sorted((data / "raw" / "ask").glob("*/*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("run") == a.run:
            asked.add(d["question_id"])
            dst = OUT / "data" / "raw" / "ask" / f.parent.name / f.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dst)
    shutil.copytree(data / "raw" / "fetch", OUT / "data" / "raw" / "fetch")
    qs = [
        line
        for line in (a.study / "questions.jsonl").read_text(encoding="utf-8").splitlines()
        if line and json.loads(line)["id"] in asked
    ]
    (OUT / "questions.jsonl").write_text("\n".join(qs) + "\n", encoding="utf-8", newline="\n")
    cited = {
        json.loads(x)["url"]
        for x in (data / "citations.jsonl").read_text("utf-8").splitlines()
        if x
    }
    # the sitemap dates the pages used, read back from their candidates (the cache is local, D-53)
    lastmods: dict[str, str] = {}
    for line in (data / "page_meta.jsonl").read_text(encoding="utf-8").splitlines():
        meta = json.loads(line)
        for c in meta.get("candidates") or []:
            if c["source"] == "sitemap" and meta["url"] in cited:
                lastmods[meta["url"]] = c["evidence"].removeprefix("lastmod: ").strip()
    (OUT / "lastmods.json").write_text(
        json.dumps(lastmods, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "expected").mkdir()
    for name in OUTPUTS:
        shutil.copy(data / name, OUT / "expected" / name)
    print(f"golden: {len(asked)} questions, {len(cited)} URLs, {len(lastmods)} lastmods -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
