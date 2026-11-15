"""Fixture helpers: recorded envelopes, SDK-model responses and fake clients (no network)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from citewatch.schemas import StudyQuestion, load_study_config
from harness_lib import ROOT

FIX = ROOT / "tests" / "fixtures" / "providers"
CFG = load_study_config(ROOT / "studies" / "uk-health" / "study.yaml")
Q1 = StudyQuestion(
    id="v-901",
    text="How much does an NHS prescription cost in England?",
    intent="nhs_services",
    time_sensitive=True,
    ts_reason="prices",
)
Q2 = StudyQuestion(
    id="v-902",
    text="Why do my legs ache the day after a long run?",
    intent="fitness",
    time_sensitive=False,
)


def envelope(model: str, qid: str) -> dict[str, Any]:
    return json.loads((FIX / f"{model}--{qid}.json").read_text(encoding="utf-8"))


def claude_raw(qid: str = "v-901") -> dict[str, Any]:
    return copy.deepcopy(envelope("claude-sonnet-5-5", qid)["answer"]["raw"][-1])


def openai_raw(qid: str = "v-901") -> dict[str, Any]:
    return copy.deepcopy(envelope("gpt-6.1-sol", qid)["answer"]["raw"][-1])


class SDKObj:
    """What the runners need from an SDK response: model_dump(mode="json")."""

    def __init__(self, raw: dict[str, Any], model_cls: Any) -> None:
        self._obj = model_cls.model_validate(raw)  # built from the SDK's own model (L-10)

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return self._obj.model_dump(mode=mode)


class FakeAnthropic:
    def __init__(self, responses: list[Any]) -> None:
        import anthropic

        self._queue = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.messages = self
        self._cls = anthropic.types.Message

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(copy.deepcopy(kwargs))
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return SDKObj(item, self._cls)


class FakeOpenAI:
    def __init__(self, responses: list[Any]) -> None:
        from openai.types.responses import Response

        self._queue = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.responses = self
        self._cls = Response

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(copy.deepcopy(kwargs))
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return SDKObj(item, self._cls)


class StatusError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status


def fixture_path(name: str) -> Path:
    return FIX / name
