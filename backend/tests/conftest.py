import pytest

from app import config


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets its own data/cache dirs and DB; no real keys leak in."""
    monkeypatch.setenv("FINN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FINN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("FINN_DEMO_PASSCODE", "")
    for k in ("LLM_PROVIDER", "GEMINI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    config.get_settings.cache_clear()
    from app.db import init_db

    init_db()
    yield
    config.get_settings.cache_clear()
