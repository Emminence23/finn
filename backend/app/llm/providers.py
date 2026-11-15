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
    docs_as_text_block,
    json_instruction,
)


# ---------------------------------------------------------------- Gemini
class GeminiProvider:
    name = "gemini"
    supports_pdf = True

    def __init__(self, api_key: str) -> None:
        from google import genai

        self._genai = genai
        self.client = genai.Client(api_key=api_key)

    def complete(self, req: LLMRequest) -> LLMResponse:
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
        resp = self.client.models.generate_content(model=req.model, contents=parts, config=config)
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
            return GeminiProvider(s.gemini_api_key)
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
