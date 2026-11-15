"""Task-based routing, caching, validation and usage logging for every LLM call.

Callers only ever do:   llm.run("classify_filing", system=..., prompt=..., schema=Model)
Which provider/model serves the task is decided by config/models.yaml + env (NFR-09).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import TypeVar, overload

import yaml
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.db import session
from app.llm.base import Doc, LLMError, LLMRequest, Provider
from app.llm.providers import build_provider

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Route:
    task: str
    provider: str
    model: str
    tier: str


class LLMRouter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.config = yaml.safe_load(self.settings.models_config.read_text())
        self._providers: dict[str, Provider] = {}

    # ------------------------------------------------------------ routing
    def route(self, task: str) -> Route:
        tasks = self.config["tasks"]
        if task not in tasks:
            raise LLMError(f"unknown task '{task}' (add it to models.yaml)")
        spec = tasks[task]
        provider = (
            os.getenv(f"LLM_PROVIDER_{task.upper()}")  # per-task override
            or spec.get("provider")
            or self.settings.llm_provider
            or self.config["default_provider"]
        )
        tier = spec["tier"]
        model = os.getenv(f"LLM_MODEL_{provider.upper()}_{tier.upper()}") or self.config[
            "providers"
        ].get(provider, {}).get(tier)
        if not model or model == "TBD":
            raise LLMError(
                f"no model configured for provider={provider} tier={tier}; "
                f"set it in models.yaml or LLM_MODEL_{provider.upper()}_{tier.upper()}"
            )
        return Route(task, provider, model, tier)

    def provider(self, name: str) -> Provider:
        if name not in self._providers:
            self._providers[name] = build_provider(name, self.settings)
        return self._providers[name]

    # ------------------------------------------------------------ main API
    @overload
    def run(
        self,
        task: str,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        docs: list[Doc] | None = ...,
        prompt_version: str = ...,
        max_tokens: int = ...,
        use_cache: bool = ...,
    ) -> T: ...
    @overload
    def run(
        self,
        task: str,
        *,
        system: str,
        prompt: str,
        schema: None = ...,
        docs: list[Doc] | None = ...,
        prompt_version: str = ...,
        max_tokens: int = ...,
        use_cache: bool = ...,
    ) -> str: ...

    def run(
        self,
        task: str,
        *,
        system: str,
        prompt: str,
        schema: type[BaseModel] | None = None,
        docs: list[Doc] | None = None,
        prompt_version: str = "v1",
        max_tokens: int = 4096,
        use_cache: bool = True,
    ):
        docs = docs or []
        r = self.route(task)
        key = _cache_key(r, prompt_version, system, prompt, schema, docs)

        if use_cache and (cached := self._cache_get(key)) is not None:
            self._log_call(r, cache_hit=True)
            return _parse(cached, schema)

        req = LLMRequest(
            system=system,
            prompt=prompt,
            model=r.model,
            schema=schema,
            docs=docs,
            max_tokens=max_tokens,
        )
        last_err: Exception | None = None
        for attempt in range(2):  # one retry on invalid structured output
            t0 = time.perf_counter()
            try:
                resp = self.provider(r.provider).complete(req)
                value = _parse(resp.text, schema)
            except (LLMError, ValidationError, json.JSONDecodeError) as e:
                last_err = e
                self._log_call(r, cache_hit=False, error=str(e)[:500])
                log.warning("llm %s attempt %d failed: %s", task, attempt + 1, e)
                continue
            except Exception as e:  # vendor SDK errors (rate limits, network)
                self._log_call(r, cache_hit=False, error=f"{type(e).__name__}: {e}"[:500])
                raise LLMError(f"{r.provider} call failed for task {task}: {e}") from e
            latency = int((time.perf_counter() - t0) * 1000)
            self._log_call(
                r,
                cache_hit=False,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                latency_ms=latency,
            )
            if use_cache:
                self._cache_put(key, r, prompt_version, resp.text)
            return value
        raise LLMError(f"task {task} failed after retries: {last_err}")

    # ------------------------------------------------------------ cache + usage
    def _cache_get(self, key: str) -> str | None:
        with session() as db:
            row = db.execute("SELECT output FROM llm_cache WHERE key = ?", (key,)).fetchone()
        return row["output"] if row else None

    def _cache_put(self, key: str, r: Route, prompt_version: str, output: str) -> None:
        with session() as db:
            db.execute(
                "INSERT OR REPLACE INTO llm_cache (key, task, provider, model, prompt_version, "
                "output) VALUES (?, ?, ?, ?, ?, ?)",
                (key, r.task, r.provider, r.model, prompt_version, output),
            )

    def _log_call(
        self,
        r: Route,
        *,
        cache_hit: bool,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        error: str | None = None,
    ) -> None:
        price = self.config.get("pricing", {}).get(r.model, {"input": 0, "output": 0})
        cost = (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000
        with session() as db:
            db.execute(
                "INSERT INTO llm_calls (task, provider, model, cache_hit, input_tokens, "
                "output_tokens, latency_ms, cost_usd, error) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    r.task,
                    r.provider,
                    r.model,
                    int(cache_hit),
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    cost,
                    error,
                ),
            )


def _cache_key(r: Route, version: str, system: str, prompt: str, schema, docs: list[Doc]) -> str:
    h = hashlib.sha256()
    for part in (
        r.task,
        r.provider,
        r.model,
        version,
        system,
        prompt,
        json.dumps(schema.model_json_schema(), sort_keys=True) if schema else "",
    ):
        h.update(part.encode())
        h.update(b"\x00")
    for d in docs:
        h.update(d.title.encode())
        h.update(d.pdf_path.read_bytes() if d.pdf_path and d.text is None else d.as_text().encode())
    return h.hexdigest()


def _parse(text: str, schema: type[BaseModel] | None):
    if schema is None:
        return text
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    return schema.model_validate_json(cleaned)


_router: LLMRouter | None = None


def get_llm() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
