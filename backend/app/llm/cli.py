"""Check LLM setup:  uv run python -m app.llm.cli [models <provider> | ping | routes]"""

from __future__ import annotations

import sys

from pydantic import BaseModel

from app.db import init_db
from app.llm.router import LLMRouter


class Pong(BaseModel):
    ok: bool
    provider_says: str


def main() -> None:
    init_db()
    router = LLMRouter()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "routes"
    if cmd == "models":
        name = sys.argv[2] if len(sys.argv) > 2 else router.config["default_provider"]
        for m in router.provider(name).list_models():
            print(m)
    elif cmd == "routes":
        for task in router.config["tasks"]:
            try:
                r = router.route(task)
                print(f"{task:22} -> {r.provider}:{r.model} ({r.tier})")
            except Exception as e:
                print(f"{task:22} -> NOT CONFIGURED: {e}")
    elif cmd == "ping":
        task = sys.argv[2] if len(sys.argv) > 2 else "classify_filing"
        out = router.run(
            task,
            system="You are a health check.",
            prompt="Reply with ok=true and a five-word greeting.",
            schema=Pong,
            use_cache=False,
            max_tokens=200,
        )
        print(router.route(task), out)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
