import pytest

from app import config


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets its own data/cache dirs and DB; no real keys leak in."""
    monkeypatch.setenv("FINN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FINN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("FINN_DEMO_PASSCODE", "")
    monkeypatch.setenv("FINN_LIVE_REFRESH", "0")
    monkeypatch.setenv("FINN_WEB_SEARCH", "0")
    monkeypatch.setenv("FINN_AI_NOTE", "0")
    for k in ("LLM_PROVIDER", "GEMINI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    config.get_settings.cache_clear()
    from app.db import init_db

    init_db()
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """A database seeded from the real committed fixtures (read-only symlink)."""
    from pathlib import Path

    data = tmp_path / "seeded"
    data.mkdir()
    (data / "fixtures").symlink_to(Path(__file__).parents[1] / "data" / "fixtures")
    monkeypatch.setenv("FINN_DATA_DIR", str(data))
    config.get_settings.cache_clear()
    from app.ingest import seed

    seed.main()
