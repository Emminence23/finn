"""Task-based routing, caching, validation and usage logging for every LLM call.

Callers only ever do:   llm.run("classify_filing", system=..., prompt=..., schema=Model)
Which provider/model serves the task is decided by config/models.yaml + env (NFR-09).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TypeVar, overload

import yaml
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.db import session
from app.llm.base import Doc, LLMError, LLMRequest, Provider, QuotaExhausted
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
        self._exhausted: dict[tuple[str, str], float] = {}  # (provider, model) -> when
        self._recorders: list[dict[str, str]] = []
        self._rec_lock = threading.Lock()

    # ------------------------------------------------------------ provenance
    @contextmanager
    def recording(self):
        """Collect {task: 'provider/model'} for every call answered inside the block, cache
        hits included, so a view can say which model wrote each section. Builds that record
        run one at a time (the API gates them), so worker threads can share recorders."""
        rec: dict[str, str] = {}
        with self._rec_lock:
            self._recorders.append(rec)
        try:
            yield rec
        finally:
            with self._rec_lock:
                self._recorders.remove(rec)

    def _served(self, r: Route) -> None:
        with self._rec_lock:
            for rec in self._recorders:
                rec[r.task] = f"{r.provider}/{r.model}"

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

    def routes(self, task: str) -> list[Route]:
        """Primary route, then the tier's fallback models (models.yaml `fallbacks`), used only
        when a model's quota is exhausted. Env-pinned models get no fallbacks."""
        r = self.route(task)
        if os.getenv(f"LLM_MODEL_{r.provider.upper()}_{r.tier.upper()}"):
            return [r]
        spec = self.config["tasks"][task]
        if isinstance(spec.get("fallbacks"), dict) and r.provider in spec["fallbacks"]:
            extra = spec["fallbacks"][r.provider]  # task-level policy beats the tier default
        else:
            extra = self.config.get("fallbacks", {}).get(r.provider, {}).get(r.tier, [])
        return [r] + [Route(task, r.provider, m, r.tier) for m in extra if m != r.model]

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
        routes = self.routes(task)
        if use_cache:
            for r in routes:
                key = _cache_key(r, prompt_version, system, prompt, schema, docs)
                if (cached := self._cache_get(key)) is not None:
                    self._log_call(r, cache_hit=True)
                    self._served(r)
                    return _parse(cached, schema)
        quota_err: QuotaExhausted | None = None
        last_err: LLMError | None = None
        for r in routes:
            if time.time() - self._exhausted.get((r.provider, r.model), 0) < 3600:
                continue  # out of quota recently; re-probe after an hour
            try:
                return self._call(
                    r, system, prompt, schema, docs, prompt_version, max_tokens, use_cache
                )
            except QuotaExhausted as e:
                self._exhausted[(r.provider, r.model)] = time.time()
                self._log_call(r, cache_hit=False, error=str(e)[:500])
                log.warning("llm %s: %s quota exhausted, trying next fallback", task, r.model)
                quota_err = e
            except LLMError as e:
                # a bad key or missing permission won't be fixed by another model: stop.
                # Anything else (server errors and timeouts after the provider's own
                # retries, or two invalid outputs) moves on to the next model, if any;
                # the model that answered is recorded, so the switch shows in the label.
                if _is_auth_error(e):
                    raise
                log.warning("llm %s: %s failed (%s), trying next fallback", task, r.model, e)
                last_err = e
        if last_err is not None and quota_err is None:
            raise last_err
        tried = ", ".join(r.model for r in routes)
        raise LLMError(
            f"task {task}: every configured model is out of quota ({tried})"
            + (f": {quota_err}" if quota_err else "")
        )

    def _call(self, r: Route, system, prompt, schema, docs, prompt_version, max_tokens, use_cache):
        task = r.task
        key = _cache_key(r, prompt_version, system, prompt, schema, docs)
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
            except QuotaExhausted:
                raise
            except (LLMError, ValidationError, json.JSONDecodeError) as e:
                if isinstance(e, LLMError) and _is_auth_error(e):
                    raise  # retrying a bad key only burns time
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
            self._served(r)
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


_AUTH = re.compile(
    r"\b(401|403)\b|api key not valid|permission_denied|unauthenticated|is not set", re.I
)


def _is_auth_error(e: Exception) -> bool:
    return bool(_AUTH.search(str(e)))


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
