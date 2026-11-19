"""The headline chart (docs/assets/headline.svg) is rebuilt from summary.json and matches the
committed file, so its numbers cannot drift from the study."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "build_headline_chart", ROOT / "scripts" / "build_headline_chart.py"
)
assert _spec and _spec.loader
chart = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chart)
SUMMARY = json.loads(chart.SUMMARY.read_text(encoding="utf-8"))


def test_the_committed_chart_is_the_one_the_summary_builds():
    assert chart.OUT.read_text(encoding="utf-8") == chart.build(SUMMARY)


def test_the_chart_states_each_headline_with_its_count_and_interval():
    svg = chart.build(SUMMARY)
    desc = re.search(r"<desc id=\"d\">(.*?)</desc>", svg, re.S)
    assert desc
    text = desc[1]
    assert "Answers citing nhs.uk run 1: Claude Sonnet 5.5 10% (10/100, 95% CI 5.0% to 16%)" in text
    assert "GPT-6.1 Sol 83% (83/100, 95% CI 75% to 90%)" in text
    assert "GPT-6.1 Sol 84% (84/100" in text  # run 2
    assert "GPT-6.1 Sol 43% (49/114" in text and "Claude Sonnet 5.5 12% (14/114" in text
    assert svg.count("<circle") == 1 + 3 and svg.count('rx="1.5"') == 1 + 3  # legend + rows
