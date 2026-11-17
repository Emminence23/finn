"""Provider adapters. Each turns an LLMRequest into an LLMResponse; nothing else in the app
knows which vendor is in use, so switching providers is a config/env change (NFR-09)."""

from __future__ import annotations

import base64

from app.config import Settings
from app.llm.base import (
    LLMError,
    LLMRequest,
    LLMResponse,
    Provider,
    QuotaExhausted,
    docs_as_text_block,
    json_instruction,
)


# ---------------------------------------------------------------- Gemini
class GeminiProvider:
    name = "gemini"
    supports_pdf = True

    # Busy/overloaded models (503/504) and per-minute quota (429) are transient on the free tier.
    RETRYABLE = (429, 500, 503, 504)

    def __init__(self, api_key: str, timeout_s: int = 120, fallback_keys: list[str] = ()) -> None:
        import threading

        from google import genai
        from google.genai import types

        self._genai = genai
        # Without a timeout an overloaded model can hang a request indefinitely.
        keys = [k for k in [api_key, *fallback_keys] if k]
        self.clients = [
            genai.Client(api_key=k, http_options=types.HttpOptions(timeout=timeout_s * 1000))
            for k in dict.fromkeys(keys)
        ]
        self.client = self.clients[0]
        # (key index, model) -> when its daily quota ran out; re-probed after an hour
        self._spent: dict[tuple[int, str], float] = {}
        self._lock = threading.Lock()

    def complete(self, req: LLMRequest) -> LLMResponse:
        """Each key in turn: a key whose daily quota for this model is spent hands over to
        the next (the fallback key's own Google project). Only when every key is spent does
        the router move to another model."""
        import time

        spent_now = []
        for i, client in enumerate(self.clients):
            with self._lock:
                if time.time() - self._spent.get((i, req.model), 0) < 3600:
                    continue
            try:
                return self._complete_with(client, req)
            except QuotaExhausted:
                with self._lock:
                    self._spent[(i, req.model)] = time.time()
                spent_now.append("primary" if i == 0 else f"fallback {i}")
                import logging

                logging.getLogger(__name__).warning(
                    "gemini %s: daily quota spent on the %s key%s",
                    req.model,
                    spent_now[-1],
                    ", trying the next key" if i + 1 < len(self.clients) else "",
                )
        n = len(self.clients)
        raise QuotaExhausted(
            f"gemini {req.model}: daily free quota spent on "
            + ("the only key" if n == 1 else f"all {n} keys")
        )

    def probe(self, model: str) -> list[dict]:
        """One tiny request per key, no retries: does each key work? Never returns a key."""
        from google.genai import errors

        out = []
        for i, client in enumerate(self.clients):
            name = (
                "GEMINI_API_KEY"
                if i == 0
                else ("GEMINI_API_KEY_FALLBACK" if i == 1 else f"GEMINI_API_KEY_FALLBACK_{i}")
            )
            row = {"key": name, "model": model}
            try:
                self._complete_once(
                    LLMRequest(model=model, system="Reply with OK.", prompt="OK?", max_tokens=8),
                    client,
                )
                row |= {"status": "works"}
            except errors.APIError as e:
                code, msg = getattr(e, "code", None), str(e)
                if code == 429 and "PerDay" in msg:
                    row |= {"status": "quota_used_up", "detail": "today's free quota is spent"}
                elif code == 429:
                    row |= {"status": "works", "detail": "busy this minute (429), key is valid"}
                elif code in (500, 503, 504):
                    row |= {
                        "status": "works",
                        "detail": f"model busy at Google ({code}), key is valid",
                    }
                elif code in (400, 401, 403) and ("API key" in msg or "PERMISSION" in msg):
                    row |= {"status": "rejected", "detail": f"Google refused the key ({code})"}
                else:
                    row |= {"status": "error", "detail": f"{code}: {msg[:120]}"}
            except LLMError as e:  # answered, but empty: the key works
                row |= {"status": "works", "detail": str(e)[:80]}
            except Exception as e:  # noqa: BLE001
                row |= {"status": "error", "detail": f"{type(e).__name__}: {str(e)[:120]}"}
            out.append(row)
        return out

    def _complete_with(self, client, req: LLMRequest) -> LLMResponse:
        import time

        from google.genai import errors

        for attempt in range(4):
            try:
                return self._complete_once(req, client)
            except errors.APIError as e:
                if getattr(e, "code", None) == 429 and "PerDay" in str(e):
                    raise QuotaExhausted(f"gemini {req.model}: daily quota exhausted") from e
                if getattr(e, "code", None) not in self.RETRYABLE or attempt == 3:
                    raise LLMError(f"gemini {getattr(e, 'code', '?')}: {str(e)[:200]}") from e
                time.sleep(2 ** (attempt + 1))  # 2s, 4s, 8s
        raise LLMError("unreachable")

    def _complete_once(self, req: LLMRequest, client=None) -> LLMResponse:
        from google.genai import types

        parts: list = []
        for d in req.docs:
            if d.pdf_path is not None and d.text is None:
                parts.append(
                    types.Part.from_bytes(data=d.pdf_path.read_bytes(), mime_type="application/pdf")
                )
            else:
                parts.append(f'<document title="{d.title}">\n{d.as_text()}\n</document>')
        parts.append(req.prompt)

        config = types.GenerateContentConfig(
            system_instruction=req.system,
            max_output_tokens=req.max_tokens,
            **(
                {"response_mime_type": "application/json", "response_schema": req.schema}
                if req.schema
                else {}
            ),
        )
        resp = (client or self.client).models.generate_content(
            model=req.model, contents=parts, config=config
        )
        if not resp.text:
            raise LLMError(f"gemini returned no text (finish={_gemini_finish(resp)})")
        usage = resp.usage_metadata
        return LLMResponse(
            text=resp.text,
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
        )

    def list_models(self) -> list[str]:
        return sorted(m.name.removeprefix("models/") for m in self.client.models.list())


def _gemini_finish(resp) -> str:
    try:
        return str(resp.candidates[0].finish_reason)
    except (AttributeError, IndexError, TypeError):
        return "unknown"


# ------------------------------------------------- OpenAI-compatible (Groq, OpenRouter, Ollama)
class OpenAICompatProvider:
    supports_pdf = False

    def __init__(self, name: str, base_url: str, api_key: str) -> None:
        from openai import OpenAI

        self.name = name
        self.client = OpenAI(base_url=base_url, api_key=api_key or "unused")

    def complete(self, req: LLMRequest) -> LLMResponse:
        user = req.prompt
        if req.docs:
            user = docs_as_text_block(req.docs) + "\n\n" + user
        system = req.system + (json_instruction(req.schema) if req.schema else "")
        resp = self.client.chat.completions.create(
            model=req.model,
            max_tokens=req.max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            **({"response_format": {"type": "json_object"}} if req.schema else {}),
        )
        text = resp.choices[0].message.content or ""
        if not text:
            raise LLMError(f"{self.name} returned no text")
        u = resp.usage
        return LLMResponse(
            text=text,
            input_tokens=u.prompt_tokens if u else 0,
            output_tokens=u.completion_tokens if u else 0,
        )

    def list_models(self) -> list[str]:
        return sorted(m.id for m in self.client.models.list())


# ---------------------------------------------------------------- Anthropic
class AnthropicProvider:
    name = "anthropic"
    supports_pdf = True

    def __init__(self, api_key: str) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key)

    def complete(self, req: LLMRequest) -> LLMResponse:
        content: list[dict] = []
        for d in req.docs:
            if d.pdf_path is not None and d.text is None:
                data = base64.standard_b64encode(d.pdf_path.read_bytes()).decode()
                source = {"type": "base64", "media_type": "application/pdf", "data": data}
            else:
                source = {"type": "text", "media_type": "text/plain", "data": d.as_text()}
            content.append({"type": "document", "source": source, "title": d.title})
        content.append({"type": "text", "text": req.prompt})

        kwargs = dict(
            model=req.model,
            max_tokens=req.max_tokens,
            system=req.system,
            messages=[{"role": "user", "content": content}],
            cache_control={"type": "ephemeral"},  # cache long document prefixes
        )
        try:
            if req.schema:
                resp = self.client.messages.parse(output_format=req.schema, **kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"anthropic {e.status_code}: {e.message}") from e
        if resp.stop_reason == "refusal":
            raise LLMError("anthropic refused the request")
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResponse(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

    def list_models(self) -> list[str]:
        return sorted(m.id for m in self.client.models.list())


# ---------------------------------------------------------------- factory
def build_provider(name: str, s: Settings) -> Provider:
    match name:
        case "gemini":
            _require(s.gemini_api_key, "GEMINI_API_KEY")
            return GeminiProvider(s.gemini_api_key, fallback_keys=s.gemini_api_key_fallbacks)
        case "groq":
            _require(s.groq_api_key, "GROQ_API_KEY")
            return OpenAICompatProvider("groq", "https://api.groq.com/openai/v1", s.groq_api_key)
        case "openrouter":
            _require(s.openrouter_api_key, "OPENROUTER_API_KEY")
            return OpenAICompatProvider(
                "openrouter", "https://openrouter.ai/api/v1", s.openrouter_api_key
            )
        case "ollama":
            return OpenAICompatProvider("ollama", s.ollama_base_url, "ollama")
        case "anthropic":
            _require(s.anthropic_api_key, "ANTHROPIC_API_KEY")
            return AnthropicProvider(s.anthropic_api_key)
    raise LLMError(f"unknown provider '{name}'")


def _require(value: str, env_name: str) -> None:
    if not value:
        raise LLMError(f"{env_name} is not set (add it to backend/.env)")
