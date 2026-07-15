"""Runtime configuration for ARA.

All settings can be overridden by environment variables (optionally loaded from a
`.env` file). The tool runs fully offline with the built-in heuristic scorer; the
Azure OpenAI LLM path activates automatically when credentials are present and
`--mock` is not set.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Minimal .env loader (no external dependency).

    Only sets keys that are not already present in the environment.
    """
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Resolved settings for a run."""

    # Scoring / verdict
    rubric_version: str = "2.0-cross-vendor"
    deploy_threshold: float = 7.0
    conditional_threshold: float = 5.0
    strict_gates: bool = True

    # LLM (Azure OpenAI) — optional
    azure_endpoint: str | None = None
    azure_api_key: str | None = None
    azure_api_version: str = "2024-10-21"
    llm_scorer_deployment: str | None = None
    llm_normalizer_deployment: str | None = None
    scorer_temperature: float = 0.0
    normalizer_temperature: float = 0.3

    # Behaviour
    force_mock: bool = False  # set by --mock; forces the heuristic scorer
    input_token_cap: int = 8000

    metadata: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        _load_dotenv()
        s = cls()
        s.rubric_version = os.environ.get("ARA_RUBRIC_VERSION", s.rubric_version)
        s.deploy_threshold = float(os.environ.get("ARA_DEPLOY_THRESHOLD", s.deploy_threshold))
        s.conditional_threshold = float(
            os.environ.get("ARA_CONDITIONAL_THRESHOLD", s.conditional_threshold)
        )
        s.strict_gates = _as_bool(os.environ.get("ARA_STRICT_GATES"), s.strict_gates)

        s.azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        s.azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        s.azure_api_version = os.environ.get("AZURE_OPENAI_API_VERSION", s.azure_api_version)
        s.llm_scorer_deployment = os.environ.get("ARA_LLM_SCORER")
        s.llm_normalizer_deployment = os.environ.get("ARA_LLM_NORMALIZER")
        return s

    @property
    def llm_available(self) -> bool:
        """True when we have enough config to attempt an Azure OpenAI call."""
        return bool(
            self.azure_endpoint
            and self.azure_api_key
            and self.llm_scorer_deployment
            and not self.force_mock
        )

    @property
    def scoring_mode(self) -> str:
        return "llm" if self.llm_available else "heuristic"
