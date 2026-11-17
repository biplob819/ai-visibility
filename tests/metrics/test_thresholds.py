"""THR-01 (OWNER D-65): threshold rules in study.yaml, checked by `citewatch score`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from citewatch.cli import main
from citewatch.runners.schedule import config_hash
from citewatch.schemas import (
    ConfigError,
    StudyConfig,
    StudySummary,
    ThresholdRule,
    load_study_config,
    parse_selector,
)
from citewatch.thresholds import ThresholdError, check, check_all
from harness_lib import ROOT

from .conftest import A, B

FLAGSHIP = ROOT / "studies" / "uk-health"


def with_rules(study: Path, rules: list[dict]) -> Path:
    path = study / "study.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["thresholds"] = rules
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def score(study: Path, capsys, *extra: str) -> tuple[int, str]:
    capsys.readouterr()
    code = main(["score", "--study", str(study), *extra])
    return code, capsys.readouterr().out


# -- selectors ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "fields"),
    [
        ("coverage", {"family": "coverage"}),
        (
            "share:presence:NHS.uk:gpt-6.1-sol:run-1",
            {"kind": "presence", "publisher": "nhs.uk", "model": B, "run": 1, "intent": None},
        ),
        ("share:weighted:nhs.uk:gpt-6.1-sol:run-2:all", {"run": 2, "intent": None}),
        ("share:consulted:nhs.uk:gpt-6.1-sol:run-1:symptoms", {"intent": "symptoms"}),
        ("citations:gpt-6.1-sol:run-1:alpha", {"model": B, "run": 1, "intent": "alpha"}),
        ("concentration:gpt-6.1-sol:run-2", {"model": B, "run": 2}),
        ("stale:primary:gpt-6.1-sol:all", {"kind": "primary", "model": B, "intent": None}),
        ("stale:secondary:gpt-6.1-sol", {"kind": "secondary", "intent": None}),
        ("support:claude-opus-5-5:gpt-6.1-sol", {"judge": "claude-opus-5-5", "model": B}),
        ("date_accuracy:overall", {"source": "overall", "kind": "within_7_days"}),
        ("date_accuracy:schema_org:exact", {"source": "schema_org", "kind": "exact"}),
    ],
)
def test_documented_selectors_parse(text, fields):
    sel = parse_selector(text)
    for k, v in fields.items():
        assert getattr(sel, k) == v, k


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("shares:presence:nhs.uk:gpt-6.1-sol:run-1", "unknown metric selector"),
        ("share:presence:nhs.uk:gpt-6.1-sol", "the form is share:"),
        ("share:presence:nhs.uk:gpt-6.1-sol:run-1:a:b", "the form is share:"),
        ("share:cited:nhs.uk:gpt-6.1-sol:run-1", "share kind 'cited'"),
        ("share:presence:nhs.uk:gpt-6.1-sol:run-3", "not a run"),
        ("share:presence::gpt-6.1-sol:run-1", "the form is share:"),
        ("coverage:all", "the form is coverage"),
        ("stale:tertiary:gpt-6.1-sol", "primary or secondary"),
        ("date_accuracy:overall:roughly", "within_7_days or exact"),
        ("", "non-empty"),
    ],
)
def test_bad_selectors_are_refused_naming_the_selector(text, says):
    with pytest.raises(ValueError, match=says):
        parse_selector(text)


# -- config ------------------------------------------------------------------------------


def test_unknown_selector_is_a_config_error_naming_it(tiny, capsys):
    p = with_rules(tiny, [{"metric": "freshness:nhs.uk", "op": ">=", "bound": 0.5}])
    with pytest.raises(ConfigError, match=r"freshness:nhs\.uk"):
        load_study_config(p)
    code, out = score(tiny, capsys)
    assert code == 2 and "freshness:nhs.uk" in out and "unknown metric selector" in out
    assert not (tiny / "results" / "summary.json").exists()  # refused before scoring


def test_a_model_or_intent_outside_the_study_is_a_config_error(tiny):
    p = with_rules(tiny, [{"metric": "stale:primary:gpt-9:all", "op": "<=", "bound": 0.5}])
    with pytest.raises(ConfigError, match="names model 'gpt-9'"):
        load_study_config(p)
    p = with_rules(tiny, [{"metric": f"stale:primary:{B}:gamma", "op": "<=", "bound": 0.5}])
    with pytest.raises(ConfigError, match="names intent 'gamma'"):
        load_study_config(p)


@pytest.mark.parametrize(
    ("rule", "says"),
    [
        ({"metric": "coverage", "op": ">", "bound": 0.5}, "op"),
        ({"metric": "coverage", "op": ">=", "bound": "high"}, "bound"),
        ({"metric": "coverage", "op": ">=", "bound": float("nan")}, "bound"),
        ({"metric": "coverage", "op": ">=", "bound": 0.5, "on": "mid"}, "on"),
        ({"metric": "coverage", "op": ">=", "bound": 0.5, "severity": "info"}, "severity"),
        ({"metric": "coverage", "op": ">=", "bound": 0.5, "scope": "x"}, "scope"),
        ({"metric": "coverage", "bound": 0.5}, "op"),
    ],
)
def test_malformed_rules_are_config_errors(tiny, rule, says):
    with pytest.raises(ConfigError, match=says):
        load_study_config(with_rules(tiny, [rule]))


def test_a_bare_yaml_on_key_is_read_as_on(tiny):
    """YAML 1.1 reads `on:` as the boolean true; the rule still means what it says."""
    path = tiny / "study.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + 'thresholds:\n  - metric: coverage\n    op: ">="\n    bound: 0.2\n    on: lo\n',
        encoding="utf-8",
    )
    (rule,) = load_study_config(path).thresholds
    assert rule.on == "lo" and rule.severity == "fail"


def test_thresholds_never_change_the_config_hash_or_a_rule_free_dump():
    """Repro: adding rules never makes run 2's config differ from run 1's (gate G2), and a
    study with no rules serialises exactly as before THR-01."""
    cfg = load_study_config(FLAGSHIP / "study.yaml")
    summary = StudySummary.model_validate_json(
        (FLAGSHIP / "results" / "summary.json").read_text(encoding="utf-8")
    )
    assert config_hash(cfg) == summary.config_hash
    ruled = StudyConfig.model_validate(
        {
            **cfg.model_dump(mode="json"),
            "thresholds": [{"metric": "coverage", "op": ">=", "bound": 0.8}],
        }
    )
    assert config_hash(ruled) == config_hash(cfg)
    assert "thresholds" not in cfg.model_dump(mode="json")
    assert ruled.model_dump(mode="json")["thresholds"][0]["metric"] == "coverage"
    assert StudyConfig.model_validate_json(ruled.model_dump_json()) == ruled


# -- operators and bounds (on the tiny study, whose figures are worked out on paper) ---------


@pytest.fixture
def tiny_summary(tiny) -> StudySummary:
    assert main(["score", "--study", str(tiny), "--json"]) == 0
    return StudySummary.model_validate_json(
        (tiny / "results" / "summary.json").read_text(encoding="utf-8")
    )


def rule(**kw) -> ThresholdRule:
    return ThresholdRule.model_validate(kw)


NHS_A = f"share:presence:nhs.uk:{A}:run-1"  # 2 of 3 valid answers: point 2/3


@pytest.mark.parametrize(
    ("op", "bound", "passed"),
    [
        (">=", 0.6, True),
        (">=", 2 / 3, True),
        (">=", 0.7, False),
        ("<=", 0.7, True),
        ("<=", 2 / 3, True),
        ("<=", 0.6, False),
    ],
)
def test_each_operator_compares_the_point_inclusively(tiny_summary, op, bound, passed):
    r = check(rule(metric=NHS_A, op=op, bound=bound), tiny_summary)
    assert r.value == pytest.approx(2 / 3) and r.n == 3 and r.passed is passed


def test_on_picks_the_declared_end_of_the_interval(tiny_summary):
    (row,) = [
        x.share
        for x in tiny_summary.share
        if (x.publisher, x.model, x.run, x.kind, x.intent) == ("nhs.uk", A, 1, "presence", None)
    ]
    assert row.lo < row.point < row.hi
    for on in ("point", "lo", "hi"):
        r = check(rule(metric=NHS_A, op=">=", bound=row.point, on=on), tiny_summary)
        assert r.value == getattr(row, on)
        assert r.passed is (on != "lo")  # lo is below the point, hi above it


def test_every_family_resolves_on_a_real_summary(tiny_summary):
    for metric in (
        "coverage",
        f"share:weighted:nhs.uk:{B}:run-2:alpha",
        f"citations:{A}:run-1",
        f"concentration:{B}:run-2",
        f"stale:secondary:{A}:beta",
    ):
        assert check(rule(metric=metric, op=">=", bound=0), tiny_summary).passed


def test_an_uncited_publisher_reads_as_zero_not_as_an_error(tiny_summary):
    metric = f"share:presence:mysite.org:{B}:run-1"
    r = check(rule(metric=metric, op=">=", bound=0.01), tiny_summary)
    assert (r.value, r.passed, r.n) == (0.0, False, 4) and "not cited" in (r.detail or "")


def test_a_selector_matching_no_row_raises(tiny_summary):
    for metric in (
        f"share:presence:nhs.uk:{A}:run-0",  # run 0 was not scored
        "date_accuracy:overall",  # no hand labels in the tiny study
        f"support:hand:{A}",
    ):
        with pytest.raises(ThresholdError, match="matches no row"):
            check_all([rule(metric=metric, op=">=", bound=0)], tiny_summary)


# -- the command ---------------------------------------------------------------------------


def test_no_rules_exits_0_as_before(tiny, capsys):
    code, out = score(tiny, capsys, "--json")
    payload = json.loads(out)
    assert code == 0 and payload["ok"] is True and "thresholds" not in payload


@pytest.mark.contract
def test_a_failed_fail_rule_exits_1_naming_metric_value_and_bound(tiny, capsys):
    with_rules(
        tiny,
        [
            {"metric": NHS_A, "op": ">=", "bound": 0.9},
            {"metric": "coverage", "op": ">=", "bound": 0.1, "on": "lo"},
        ],
    )
    code, out = score(tiny, capsys)
    assert code == 1
    assert "thresholds: 1 of 2 rules pass" in out
    assert f"FAIL {NHS_A}: point 0.6667 is below the bound >= 0.9 (n=3)" in out
    assert "coverage" not in out.split("thresholds:")[1]  # a passing rule is not listed
    assert (tiny / "results" / "summary.json").is_file()  # written before the check


@pytest.mark.contract
def test_a_failed_warn_rule_exits_0_and_is_printed_and_in_json(tiny, capsys):
    rules = [{"metric": NHS_A, "op": "<=", "bound": 0.5, "severity": "warn", "name": "cap"}]
    with_rules(tiny, rules)
    code, out = score(tiny, capsys)
    assert code == 0 and f"WARN cap ({NHS_A}): point 0.6667 is above the bound <= 0.5" in out
    code, out = score(tiny, capsys, "--json")
    payload = json.loads(out)
    assert code == 0 and payload["ok"] is True
    assert payload["thresholds_warned"] == [NHS_A] and payload["thresholds_failed"] == []
    (r,) = payload["thresholds"]
    assert r["passed"] is False and r["severity"] == "warn" and r["value"] == pytest.approx(2 / 3)


@pytest.mark.contract
def test_json_reports_every_rule_and_exit_1_on_a_fail(tiny, capsys):
    with_rules(
        tiny,
        [
            {"metric": NHS_A, "op": ">=", "bound": 0.9},
            {"metric": NHS_A, "op": ">=", "bound": 0.1, "severity": "warn"},
        ],
    )
    code, out = score(tiny, capsys, "--json")
    payload = json.loads(out)
    assert code == 1 and payload["ok"] is False
    assert [r["passed"] for r in payload["thresholds"]] == [False, True]
    assert payload["thresholds_failed"] == [NHS_A] and payload["thresholds_warned"] == []


@pytest.mark.contract
def test_a_selector_matching_nothing_exits_2_not_1(tiny, capsys):
    with_rules(tiny, [{"metric": "date_accuracy:overall", "op": ">=", "bound": 0.5}])
    code, out = score(tiny, capsys)
    assert code == 2 and "date_accuracy:overall" in out and "matches no row" in out


# -- the flagship ---------------------------------------------------------------------------


def test_rules_on_the_flagship_summary():
    summary = StudySummary.model_validate_json(
        (FLAGSHIP / "results" / "summary.json").read_text(encoding="utf-8")
    )
    data = load_study_config(FLAGSHIP / "study.yaml").model_dump(mode="json")
    rules = [
        {"metric": "share:presence:nhs.uk:gpt-6.1-sol:run-1", "op": ">=", "bound": 0.8},
        {"metric": "share:presence:nhs.uk:gpt-6.1-sol:run-1", "op": ">=", "bound": 0.8, "on": "lo"},
        {"metric": "coverage", "op": ">=", "bound": 0.9},
        {"metric": "coverage", "op": ">=", "bound": 0.9, "on": "hi"},
        {"metric": "stale:primary:gpt-6.1-sol:all", "op": "<=", "bound": 0.5},
        {"metric": "support:claude-opus-5-5:gpt-6.1-sol", "op": ">=", "bound": 0.5},
        {"metric": "date_accuracy:overall", "op": ">=", "bound": 0.7, "severity": "warn"},
        {"metric": "concentration:gpt-6.1-sol:run-1", "op": "<=", "bound": 0.8},
        {"metric": "citations:gpt-6.1-sol:run-1:symptoms", "op": ">=", "bound": 1},
    ]
    cfg = StudyConfig.model_validate({**data, "thresholds": rules})
    results = check_all(cfg.thresholds, summary)
    got = [(round(r.value, 4), r.passed) for r in results]
    assert got[:8] == [
        (0.83, True),
        (0.75, False),
        (0.8859, False),
        (0.9056, True),
        (0.4298, True),
        (0.5652, True),
        (0.6667, False),
        (0.7813, True),
    ]
    assert results[8].passed and results[8].n > 0
