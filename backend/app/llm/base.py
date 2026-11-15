"""Provider-neutral types for the LLM layer (REQUIREMENTS §6.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


@dataclass
class Doc:
    """A source document passed alongside the prompt (filing, transcript, annual report)."""

    title: str
    text: str | None = None
    pdf_path: Path | None = None

    def as_text(self) -> str:
        if self.text is not None:
            return self.text
        if self.pdf_path is None:
            return ""
        from pypdf import PdfReader

        reader = PdfReader(str(self.pdf_path))
        pages = [f"[page {i + 1}]\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages)]
        return "\n\n".join(pages)


@dataclass
class LLMRequest:
    system: str
    prompt: str
    model: str
    schema: type[BaseModel] | None = None
    docs: list[Doc] = field(default_factory=list)
    max_tokens: int = 4096


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMError(Exception):
    pass


class QuotaExhausted(LLMError):
    """The model's quota is used up for a long period (e.g. a free tier's daily limit).
    Retrying the same model is pointless; the router moves to the next fallback model."""


class Provider(Protocol):
    name: str
    supports_pdf: bool

    def complete(self, req: LLMRequest) -> LLMResponse: ...

    def list_models(self) -> list[str]: ...


def docs_as_text_block(docs: list[Doc]) -> str:
    """Fallback for providers without native PDF input: inline extracted text."""
    return "\n\n".join(f'<document title="{d.title}">\n{d.as_text()}\n</document>' for d in docs)


def json_instruction(schema: type[BaseModel]) -> str:
    import json

    return (
        "\n\nRespond with ONLY a JSON object that validates against this JSON Schema "
        "(no prose, no code fences):\n" + json.dumps(schema.model_json_schema())
    )
