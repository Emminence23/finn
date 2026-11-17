"""Runtime configuration. 12-factor: everything comes from env vars (or backend/.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(_env("FINN_DATA_DIR") or BACKEND_DIR / "data")
    )
    cache_dir: Path = field(
        default_factory=lambda: Path(_env("FINN_CACHE_DIR") or BACKEND_DIR / "cache")
    )
    models_config: Path = field(
        default_factory=lambda: Path(
            _env("FINN_MODELS_CONFIG") or BACKEND_DIR / "config" / "models.yaml"
        )
    )

    # LLM: provider is switchable without code changes (REQUIREMENTS §6.2, NFR-09)
    # LLM_PROVIDER overrides the yaml default_provider
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    # A second key from a different Google project: used when the first key's free daily
    # quota for a model is spent (quota is counted per project, not per key).
    # More fallbacks: GEMINI_API_KEY_FALLBACK_2, _3 … (each its own project), tried in order.
    gemini_api_key_fallbacks: list[str] = field(
        default_factory=lambda: [
            k
            for k in [_env("GEMINI_API_KEY_FALLBACK")]
            + [_env(f"GEMINI_API_KEY_FALLBACK_{i}") for i in range(2, 6)]
            if k
        ]
    )
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    openrouter_api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    ollama_base_url: str = field(
        default_factory=lambda: _env("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    )

    # API security (NFR-07, FR-APP-04)
    demo_passcode: str = field(default_factory=lambda: _env("FINN_DEMO_PASSCODE"))
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in _env("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
            if o.strip()
        )
    )

    # Live research builds spend LLM budget: capped per UTC day on the public demo.
    max_live_builds_per_day: int = field(
        default_factory=lambda: int(_env("FINN_MAX_LIVE_BUILDS_PER_DAY", "20"))
    )

    max_questions_per_day: int = field(
        default_factory=lambda: int(_env("FINN_MAX_QUESTIONS_PER_DAY", "60"))
    )

    # Scraping politeness (NFR-11)
    min_seconds_between_requests: float = field(
        default_factory=lambda: float(_env("FINN_MIN_REQ_INTERVAL", "1.0"))
    )

    @property
    def db_path(self) -> Path:
        return Path(_env("FINN_DB_PATH") or self.data_dir / "finn.db")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    return s
