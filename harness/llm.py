"""Unified streaming client for Anthropic and Mistral.

Models are addressed as `provider:model` strings, e.g. `anthropic:claude-sonnet-4-6`
or `mistral:mistral-large-latest`.
"""
from __future__ import annotations

import os
from typing import Iterator, Literal

Provider = Literal["anthropic", "mistral"]


class LLMError(RuntimeError):
    pass


def parse_model(spec: str) -> tuple[Provider, str]:
    if ":" not in spec:
        raise LLMError(
            f"Model spec '{spec}' is missing provider prefix. "
            f"Use 'anthropic:<model>' or 'mistral:<model>'."
        )
    provider, model = spec.split(":", 1)
    if provider not in ("anthropic", "mistral"):
        raise LLMError(f"Unknown provider '{provider}'. Use 'anthropic' or 'mistral'.")
    return provider, model  # type: ignore[return-value]


def _temperature_for(provider: Provider) -> float | None:
    """Per-provider temperature from env, with defaults.

    Anthropic native default is 1.0.
    Mistral native default is 0.7.
    Override with ANTHROPIC_TEMPERATURE / MISTRAL_TEMPERATURE in .env.
    """
    var = "ANTHROPIC_TEMPERATURE" if provider == "anthropic" else "MISTRAL_TEMPERATURE"
    raw = os.getenv(var)
    if raw is None or raw.strip() == "":
        return None  # use SDK default
    try:
        return float(raw)
    except ValueError:
        raise LLMError(f"{var}={raw!r} is not a valid float.")


def stream(
    *,
    model_spec: str,
    system: str,
    messages: list[dict],
    max_tokens: int = 600,
    temperature: float | None = None,
) -> Iterator[str]:
    """Stream text chunks from the chosen provider.

    `messages` is a list of {"role": "user"|"assistant", "content": str}.
    If `temperature` is None, it is read from env (ANTHROPIC_TEMPERATURE /
    MISTRAL_TEMPERATURE). If still unset, the SDK default is used.
    """
    provider, model = parse_model(model_spec)
    temp = temperature if temperature is not None else _temperature_for(provider)

    if provider == "anthropic":
        yield from _stream_anthropic(model, system, messages, max_tokens, temp)
    else:
        yield from _stream_mistral(model, system, messages, max_tokens, temp)


def _stream_anthropic(
    model: str,
    system: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float | None,
) -> Iterator[str]:
    import anthropic

    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set.")
    client = anthropic.Anthropic(api_key=key)

    kwargs: dict = dict(
        model=model,
        system=system,
        messages=messages,
        max_tokens=max_tokens,
    )
    if temperature is not None:
        kwargs["temperature"] = temperature

    with client.messages.stream(**kwargs) as resp:
        for text in resp.text_stream:
            yield text


def _stream_mistral(
    model: str,
    system: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float | None,
) -> Iterator[str]:
    try:
        from mistralai import Mistral  # v1
    except ImportError:
        from mistralai.client import Mistral  # v2

    key = os.getenv("MISTRAL_API_KEY")
    if not key:
        raise LLMError("MISTRAL_API_KEY is not set.")
    client = Mistral(api_key=key)

    full = [{"role": "system", "content": system}, *messages]
    kwargs: dict = dict(model=model, messages=full, max_tokens=max_tokens)
    if temperature is not None:
        kwargs["temperature"] = temperature

    response = client.chat.stream(**kwargs)
    for event in response:
        delta = event.data.choices[0].delta
        if delta and delta.content:
            yield delta.content


def collect(stream_iter: Iterator[str]) -> str:
    """Drain a stream into a single string."""
    return "".join(stream_iter)
