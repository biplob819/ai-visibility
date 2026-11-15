"""Answer runners: one per provider, all asking the same instruction (Tech Spec §7.1)."""

from __future__ import annotations

from citewatch.schemas import provider_of

from .base import Answer, Runner, TransportError, instruction, prompt_hash, with_retries


def make_runner(model: str) -> Runner:
    provider = provider_of(model)
    if provider == "anthropic":
        from .anthropic_runner import AnthropicRunner

        return AnthropicRunner(model)
    from .openai_runner import OpenAIRunner

    return OpenAIRunner(model)


__all__ = [
    "Answer",
    "Runner",
    "TransportError",
    "instruction",
    "make_runner",
    "prompt_hash",
    "with_retries",
]
