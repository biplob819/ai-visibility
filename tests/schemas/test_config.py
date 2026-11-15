import json

import pytest
import yaml

from citewatch.schemas import (
    ConfigError,
    StudyConfig,
    load_questions,
    load_study_config,
    provider_of,
)
from harness_lib import ROOT

from . import samples as s


def write_yaml(tmp_path, data, name="study.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_flagship_study_matches_the_tech_spec():
    c = load_study_config(ROOT / "studies" / "uk-health" / "study.yaml")
    assert c.models == ("claude-sonnet-5-5", "gpt-6.1-sol")
    assert c.effort == "medium"
    assert (c.user_location.country, c.user_location.city) == ("GB", "London")
    assert (c.max_searches, c.word_limit, c.stale_days) == (3, 150, 365)
    assert c.intents == ("symptoms", "treatment", "nhs_services", "fitness", "nutrition")


def test_a_custom_study_validates(tmp_path):
    data = s.config(
        intents=["parenting", "sleep"],
        models=["gpt-6.1-sol"],
        user_location={"type": "approximate", "country": "IN", "city": "Pune"},
    )
    c = load_study_config(write_yaml(tmp_path, data))
    assert c.user_location.country == "IN" and c.models == ("gpt-6.1-sol",)


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"models": ["llama-3"]}, "models"),
        ({"user_location": {"type": "approximate", "country": "gb"}}, "user_location.country"),
        ({"intents": ["sleep", "sleep"]}, "intents"),
        ({"intents": []}, "intents"),
        ({"user_agent": "citewatch/0.1.0"}, "user_agent"),
        ({"max_searches": 9}, "max_searches"),
        ({"effort": "max"}, "effort"),
        ({"seeds": {"order": 1}}, "(top level)"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_bad_values_name_the_file_and_field(tmp_path, over, field):
    p = write_yaml(tmp_path, s.config(**over))
    with pytest.raises(ConfigError) as exc:
        load_study_config(p)
    assert str(p) in str(exc.value) and field in str(exc.value)


def test_duplicate_keys_and_unreadable_files(tmp_path):
    p = tmp_path / "dup.yaml"
    p.write_text("name: a\nname: b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="duplicate key 'name'"):
        load_study_config(p)
    bad = tmp_path / "bad.yaml"
    bad.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ConfigError, match="cannot read"):
        load_study_config(bad)
    with pytest.raises(ConfigError, match="mapping"):
        load_study_config(write_yaml(tmp_path, ["a"], "list.yaml"))


def test_load_questions_checks_intents_and_ids(tmp_path):
    cfg = StudyConfig.model_validate(s.config())
    q1 = s.question(id="v-001", intent="symptoms", time_sensitive=False, ts_reason=None)
    q2 = s.question(id="v-002", intent="nutrition", time_sensitive=False, ts_reason=None)
    p = tmp_path / "q.jsonl"
    p.write_text("\n".join(json.dumps(q) for q in (q1, q2)) + "\n", encoding="utf-8")
    assert [q.id for q in load_questions(p, cfg)] == ["v-001", "v-002"]
    p.write_text(json.dumps(q1) + "\n" + json.dumps(q1) + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"q.jsonl:2: duplicate question id"):
        load_questions(p, cfg)
    p.write_text(json.dumps(s.question(id="v-003")) + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not declared"):
        load_questions(p, cfg)
    p.write_text("{nope\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=":1: not JSON"):
        load_questions(p, cfg)


def test_provider_routing():
    assert provider_of("claude-sonnet-5-5") == "anthropic"
    assert provider_of("gpt-6.1-sol") == "openai"
    for bad in ("claude-", "gemini-2", ""):
        with pytest.raises(ValueError):
            provider_of(bad)
