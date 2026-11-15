"""GPT with native web search through the Responses API (Tech Spec §7.1, ASK-02)."""

from __future__ import annotations

from typing import Any

from citewatch.env import key_for
from citewatch.schemas import StudyConfig, StudyQuestion

from .base import Answer, instruction, with_retries


def build_request(question: StudyQuestion, cfg: StudyConfig) -> dict[str, Any]:
    loc = cfg.user_location.model_dump(exclude_none=True)  # omitted would mean the US (D-31)
    return {
        "instructions": instruction(cfg),
        "input": question.text,
        "tools": [{"type": "web_search", "user_location": loc}],
        "max_tool_calls": cfg.max_searches,
        "include": ["web_search_call.action.sources"],
        "reasoning": {"effort": cfg.effort},
    }


def parse(model: str, raw: dict[str, Any], request: dict[str, Any]) -> Answer:
    texts: list[str] = []
    actions: list[str] = []
    refusal = False
    for item in raw.get("output") or []:
        kind = item.get("type")
        if kind == "web_search_call":
            actions.append(((item.get("action") or {}).get("type")) or "unknown")
        elif kind == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
                elif part.get("type") == "refusal":
                    refusal = True
    usage = raw.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    status = raw.get("status") or "unknown"
    incomplete = (raw.get("incomplete_details") or {}).get("reason")
    return Answer(
        model=model,
        model_snapshot=raw.get("model") or model,
        answer_text="".join(texts).strip(),
        stop_reason="refusal"
        if refusal
        else (f"incomplete:{incomplete}" if incomplete else status),
        refusal=refusal,
        refusal_category=None,
        searches=sum(1 for a in actions if a == "search"),  # only search actions are billed (D-31)
        search_actions=actions,
        search_errors=[],
        tokens_in=usage.get("input_tokens") or 0,
        tokens_out=usage.get("output_tokens") or 0,
        cached_in=details.get("cached_tokens") or 0,
        continuations=0,
        raw=[raw],
        request=request,
    )


class OpenAIRunner:
    provider = "openai"

    def __init__(self, model: str, client: Any = None, sleep: Any = None) -> None:
        self.model = model
        if client is None:
            import openai  # optional extra

            client = openai.OpenAI(api_key=key_for("openai"), max_retries=0)
        self.client = client
        self._sleep = sleep

    def ask(self, question: StudyQuestion, cfg: StudyConfig) -> Answer:
        request = build_request(question, cfg)
        kwargs = {"sleep": self._sleep} if self._sleep else {}
        resp = with_retries(
            lambda: self.client.responses.create(model=self.model, **request), **kwargs
        )
        return parse(self.model, resp.model_dump(mode="json"), request)
