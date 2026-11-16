import pytest
from pydantic import BaseModel

from app.db import session
from app.llm.base import LLMError, LLMResponse
from app.llm.router import LLMRouter


class Out(BaseModel):
    category: str


class FakeProvider:
    name = "fake"
    supports_pdf = False

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, req):
        self.calls += 1
        return LLMResponse(text=self.replies.pop(0), input_tokens=100, output_tokens=10)

    def list_models(self):
        return ["fake-1"]


@pytest.fixture
def router(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_GEMINI_FAST", "fake-model")
    return LLMRouter()


def test_route_uses_yaml_default_and_env_model_override(router):
    r = router.route("classify_filing")
    assert (r.provider, r.model, r.tier) == ("gemini", "fake-model", "fast")


def test_per_task_provider_override(router, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_CLASSIFY_FILING", "anthropic")
    assert router.route("classify_filing").model == "claude-haiku-5-5"


def test_unconfigured_model_fails_loudly(router):
    router.config["default_provider"] = "groq"  # groq tiers are TBD
    with pytest.raises(LLMError, match="no model configured"):
        router.route("promise_vs_delivery")


def test_structured_output_is_cached(router):
    fake = FakeProvider(['{"category": "results"}'])
    router._providers["gemini"] = fake
    a = router.run("classify_filing", system="s", prompt="p", schema=Out)
    b = router.run("classify_filing", system="s", prompt="p", schema=Out)
    assert a == b == Out(category="results")
    assert fake.calls == 1
    with session() as db:
        hits = [r["cache_hit"] for r in db.execute("SELECT cache_hit FROM llm_calls ORDER BY id")]
    assert hits == [0, 1]


def test_invalid_json_retries_once_then_succeeds(router):
    fake = FakeProvider(["not json", '```json\n{"category": "M&A"}\n```'])
    router._providers["gemini"] = fake
    assert router.run("classify_filing", system="s", prompt="p", schema=Out).category == "M&A"
    assert fake.calls == 2


def test_gives_up_after_two_invalid_outputs(router):
    router._providers["gemini"] = FakeProvider(["nope", "still nope"])
    with pytest.raises(LLMError, match="failed after retries"):
        router.run("classify_filing", system="s", prompt="p", schema=Out)


def test_missing_key_message_is_actionable(router):
    with pytest.raises(LLMError, match="GEMINI_API_KEY is not set"):
        router.provider("gemini")


def test_quota_exhaustion_falls_back_to_next_model_and_remembers(monkeypatch):
    from app.llm.base import QuotaExhausted

    monkeypatch.delenv("LLM_MODEL_GEMINI_MID", raising=False)
    router = LLMRouter()
    router.config["providers"]["gemini"]["mid"] = "m-primary"
    router.config["fallbacks"] = {"gemini": {"mid": ["m-backup"]}}
    seen = []

    class Quota(FakeProvider):
        def complete(self, req):
            seen.append(req.model)
            if req.model == "m-primary":
                raise QuotaExhausted("daily quota")
            return super().complete(req)

    router._providers["gemini"] = Quota(['{"category": "a"}', '{"category": "b"}'])
    assert router.run("bull_bear", system="s", prompt="p1", schema=Out).category == "a"
    assert router.run("bull_bear", system="s", prompt="p2", schema=Out).category == "b"
    assert seen == ["m-primary", "m-backup", "m-backup"]  # primary skipped once exhausted


def test_env_pinned_model_has_no_fallbacks(router):
    router.config["fallbacks"] = {"gemini": {"fast": ["other"]}}
    assert [r.model for r in router.routes("classify_filing")] == ["fake-model"]


def test_task_level_fallbacks_override_tier_default(monkeypatch):
    monkeypatch.delenv("LLM_MODEL_GEMINI_STRONG", raising=False)
    router = LLMRouter()
    router.config["fallbacks"] = {"gemini": {"strong": ["lite-model"]}}
    models = [r.model for r in router.routes("promise_vs_delivery")]
    assert "lite-model" not in models and models[1:] == ["gemini-3.5-flash"]


def test_server_error_falls_back_but_a_bad_key_does_not(monkeypatch):
    monkeypatch.delenv("LLM_MODEL_GEMINI_MID", raising=False)
    router = LLMRouter()
    router.config["providers"]["gemini"]["mid"] = "m-primary"
    router.config["fallbacks"] = {"gemini": {"mid": ["m-backup"]}}
    seen = []

    class Flaky(FakeProvider):
        error = "gemini 503: overloaded"

        def complete(self, req):
            seen.append(req.model)
            if req.model == "m-primary":
                raise LLMError(self.error)
            return super().complete(req)

    router._providers["gemini"] = Flaky(['{"category": "a"}'])
    assert router.run("bull_bear", system="s", prompt="p1", schema=Out).category == "a"
    assert seen == ["m-primary", "m-primary", "m-backup"]  # one retry, then the fallback
    Flaky.error = "gemini 400: API key not valid"
    with pytest.raises(LLMError, match="API key not valid"):
        router.run("bull_bear", system="s", prompt="p2", schema=Out)
    assert seen[-2:] == ["m-backup", "m-primary"]  # tried once: no retry, no fallback
