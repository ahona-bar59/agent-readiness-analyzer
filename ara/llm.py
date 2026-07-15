"""LLM factory (the "brain").

Mirrors the `build_llm()` pattern from the agents ARA evaluates. Returns an
Azure OpenAI chat client when configured, else None (the pipeline then uses the
heuristic scorer). Import of langchain is lazy so the tool has no hard dependency
on it.
"""
from __future__ import annotations

from .config import Settings


def build_llm(settings: Settings, role: str = "scorer"):
    """Return a chat model for the given role, or None if unavailable.

    role: "scorer" (deterministic, temp 0) or "normalizer" (higher temp).
    """
    if not settings.llm_available:
        return None
    try:
        from langchain_openai import AzureChatOpenAI  # type: ignore
    except ImportError:
        return None

    deployment = (
        settings.llm_scorer_deployment
        if role == "scorer"
        else (settings.llm_normalizer_deployment or settings.llm_scorer_deployment)
    )
    temperature = (
        settings.scorer_temperature if role == "scorer" else settings.normalizer_temperature
    )
    try:
        return AzureChatOpenAI(
            azure_endpoint=settings.azure_endpoint,
            api_key=settings.azure_api_key,
            api_version=settings.azure_api_version,
            azure_deployment=deployment,
            temperature=temperature,
            timeout=60,
            max_retries=2,
        )
    except Exception:  # noqa: BLE001 - any construction error -> heuristic path
        return None
