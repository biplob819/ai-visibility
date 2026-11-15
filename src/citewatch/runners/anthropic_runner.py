"""Claude with native web search (Tech Spec §7.1, ASK-01)."""

from __future__ import annotations

from typing import Any

from citewatch.env import key_for
from citewatch.schemas import StudyConfig, StudyQuestion

from .base import Answer, RawCall, TransportError, Usage, instruction, with_retries

TOOL_TYPE = "web_search_20260209"  # D-32
MAX_CONTINUATIONS = 3
MAX_TOKENS = 8000  # room for adaptive thinking before a 150-word answer


def build_request(question: StudyQuestion, cfg: StudyConfig) -> dict[str, Any]:
    loc = cfg.user_location.model_dump(exclude_none=True)
    return {
        "max_tokens": MAX_TOKENS,
        "system": instruction(cfg),
        "messages": [{"role": "user", "content": question.text}],
        "tools": [
            {
                "type": TOOL_TYPE,
                "name": "web_search",
                "max_uses": cfg.max_searches,
                "user_location": loc,
                # D-34: with dynamic filtering the model reads results through code execution and
                # its answer carries no citations; direct calls keep web_search_result_location
                # citations on the text, which the whole study measures
                "allowed_callers": ["direct"],
            }
        ],
        "output_config": {"effort": cfg.effort},
        # no temperature/top_p/top_k (Sonnet 5.5 rejects non-default values) and no `fallbacks`:
        # a refused request is recorded, never rerouted to another model (D-8, H9)
    }


def continuation_error(exc: BaseException) -> str:
    """`<kind> during continuation: <detail>`; the scheduler reads the kind before ` during`."""
    status = getattr(exc, "status_code", None)
    if isinstance(exc, TransportError):
        kind = "transport"
    elif isinstance(status, int):
        kind = f"provider:{status}"
    else:
        kind = f"internal:{type(exc).__name__}"
    return f"{kind} during continuation: {str(exc)[:200]}"


def _int(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def usage(responses: list[dict[str, Any]]) -> Usage:
    """Tokens and billed searches summed over every response, read defensively: the cost of a
    paid call must be known even when the rest of the response is unexpected."""
    t_in = t_out = cached = searches = 0
    for r in responses:
        u = r.get("usage") or {}
        cache_read = _int(u.get("cache_read_input_tokens"))
        t_in += (
            _int(u.get("input_tokens")) + cache_read + _int(u.get("cache_creation_input_tokens"))
        )
        cached += cache_read
        t_out += _int(u.get("output_tokens"))
        searches += _int((u.get("server_tool_use") or {}).get("web_search_requests"))
    return Usage(t_in, t_out, cached, searches)


def parse(model: str, responses: list[dict[str, Any]], request: dict[str, Any]) -> Answer:
    last = responses[-1]
    texts: list[str] = []
    errors: list[str] = []
    actions: list[str] = []
    searches = tokens_in = tokens_out = cached = 0
    for r in responses:
        for block in r.get("content") or []:
            kind = block.get("type")
            if kind == "text":
                texts.append(block.get("text", ""))
            elif kind == "server_tool_use" and block.get("name") == "web_search":
                actions.append("search")
            elif kind == "web_search_tool_result":
                content = block.get("content")
                if isinstance(content, dict):  # an error result is an object, a success a list
                    errors.append(str(content.get("error_code", "unknown")))
        usage = r.get("usage") or {}
        cache_read = usage.get("cache_read_input_tokens") or 0
        cache_write = usage.get("cache_creation_input_tokens") or 0
        tokens_in += (usage.get("input_tokens") or 0) + cache_read + cache_write
        cached += cache_read
        tokens_out += usage.get("output_tokens") or 0
        searches += ((usage.get("server_tool_use") or {}).get("web_search_requests")) or 0
    stop = last.get("stop_reason") or "unknown"
    details = last.get("stop_details") or {}
    return Answer(
        model=model,
        model_snapshot=last.get("model") or model,
        answer_text="".join(texts).strip(),
        stop_reason=stop,
        refusal=stop == "refusal",
        refusal_category=details.get("category") if stop == "refusal" else None,
        searches=searches,
        search_actions=actions,
        search_errors=errors,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cached_in=cached,
        continuations=len(responses) - 1,
        raw=responses,
        request=request,
    )


class AnthropicRunner:
    provider = "anthropic"

    def __init__(self, model: str, client: Any = None, sleep: Any = None) -> None:
        self.model = model
        if client is None:
            import anthropic  # optional extra

            client = anthropic.Anthropic(api_key=key_for("anthropic"), max_retries=0)
        self.client = client
        self._sleep = sleep
        self.stop: Any = None  # the scheduler's stop event; ends retries on Ctrl-C

    def usage(self, responses: list[dict[str, Any]]) -> Usage:
        return usage(responses)

    def call(self, question: StudyQuestion, cfg: StudyConfig) -> RawCall:
        """Ask once, continuing a paused turn at most MAX_CONTINUATIONS times. Never parses.
        A failure after the first response returns what was paid for, with `error` set."""
        request = build_request(question, cfg)
        messages = list(request["messages"])
        responses: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"sleep": self._sleep} if self._sleep else {}
        kwargs["stop"] = self.stop
        for _ in range(MAX_CONTINUATIONS + 1):
            body = {**request, "messages": messages}
            try:
                resp = with_retries(
                    lambda b=body: self.client.messages.create(model=self.model, **b), **kwargs
                )
            except Exception as exc:
                if not responses:
                    raise
                # anything after a paid response returns what was paid for (N1.2 v2 H1)
                return RawCall(self.model, request, responses, error=continuation_error(exc))
            raw = resp.model_dump(mode="json")
            responses.append(raw)
            if raw.get("stop_reason") != "pause_turn":
                break
            if self.stop is not None and self.stop.is_set():  # keep what was paid, ask no more
                return RawCall(
                    self.model, request, responses, error="stopped during continuation: Ctrl-C"
                )
            # continue the paused server-tool turn by sending its content back (§3.4)
            messages = [*messages, {"role": "assistant", "content": raw.get("content") or []}]
        return RawCall(self.model, request, responses)

    def ask(self, question: StudyQuestion, cfg: StudyConfig) -> Answer:
        """call() then parse(): convenient for scripts and tests; the scheduler stores first."""
        rc = self.call(question, cfg)
        return parse(self.model, rc.responses, rc.request)
