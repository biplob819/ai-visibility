import pytest

from citewatch.runners import anthropic_runner, openai_runner
from citewatch.runners.base import instruction, prompt_hash

from .helpers import CFG, Q1


@pytest.mark.contract
def test_anthropic_request_matches_the_spec():
    req = anthropic_runner.build_request(Q1, CFG)
    tool = req["tools"][0]
    assert tool["type"] == "web_search_20260209" and tool["name"] == "web_search"
    assert tool["max_uses"] == 3 and tool["allowed_callers"] == ["direct"]
    assert tool["user_location"] == {
        "type": "approximate",
        "country": "GB",
        "city": "London",
        "region": "England",
        "timezone": "Europe/London",
    }
    assert req["output_config"] == {"effort": "medium"}
    for banned in ("temperature", "top_p", "top_k", "fallbacks", "betas"):
        assert banned not in req
    assert req["messages"] == [{"role": "user", "content": Q1.text}]


@pytest.mark.contract
def test_openai_request_matches_the_spec():
    req = openai_runner.build_request(Q1, CFG)
    assert req["tools"] == [
        {
            "type": "web_search",
            "user_location": {
                "type": "approximate",
                "country": "GB",
                "city": "London",
                "region": "England",
                "timezone": "Europe/London",
            },
        }
    ]
    assert req["max_tool_calls"] == 3
    assert req["include"] == ["web_search_call.action.sources"]
    assert req["reasoning"] == {"effort": "medium"}
    assert req["input"] == Q1.text


def test_both_models_get_byte_identical_instructions():
    a = anthropic_runner.build_request(Q1, CFG)["system"]
    o = openai_runner.build_request(Q1, CFG)["instructions"]
    assert (
        a
        == o
        == (
            "Answer for a reader in the UK in under 150 words. "
            "Use web search to find current sources and cite them."
        )
    )


def test_prompt_hash_changes_exactly_when_the_instruction_changes():
    other = CFG.model_copy(update={"word_limit": 120})
    assert prompt_hash(instruction(CFG)) == prompt_hash(instruction(CFG))
    assert prompt_hash(instruction(CFG)) != prompt_hash(instruction(other))
    same_text = CFG.model_copy(update={"max_searches": 2})
    assert prompt_hash(instruction(same_text)) == prompt_hash(instruction(CFG))


def test_other_countries_get_a_readable_place():
    from citewatch.schemas import UserLocation

    de = CFG.model_copy(update={"user_location": UserLocation(country="DE", city="Berlin")})
    assert "a reader in Germany" in instruction(de)
    br = CFG.model_copy(update={"user_location": UserLocation(country="BR", city="Recife")})
    assert "a reader in Recife" in instruction(br)
