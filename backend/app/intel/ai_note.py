"""Today's summary, written by the free model from what code already ranked and computed.

Code still decides what matters (the ranking, the Act / Know / Set aside bands, the figures).
The model only writes: it gets those facts (the portfolio's day, the ranked cards with
their one-liners, position sizes and price moves, events still open) and turns them into a
short note, most important first.

Code then checks the note: every figure in it must appear in the facts, every company of
the portfolio it names must be one the facts mention, and it may not tell the investor to
buy or sell. A note that fails is dropped and the code-written lead is shown instead.

One model call per distinct set of facts: the note is saved in Key Value for a day under a
hash of the facts, and written in the background, so the page never waits for it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading

from pydantic import BaseModel, Field

from app import store

log = logging.getLogger(__name__)
TTL_S = 24 * 3600
PROMPT_VERSION = "today-note-v1"
MAX_CARDS = 12

_running: set[str] = set()
_lock = threading.Lock()


def facts(d: dict) -> dict:
    cards = [c for c in d["cards"] if c.get("band") in ("act", "know")][:MAX_CARDS]
    return {
        "window": d["window"]["name"]
        or f"{d['window']['start'][:10]} to {d['window']['end'][:10]}",
        "computed_summary": d.get("lead", ""),
        "items": [
            {
                "company": c.get("short") or c["company"],
                "band": c["band"],  # act = could change a decision; know = worth knowing
                "level": c["level"],
                "why_ranked": c.get("level_reason"),
                "what": c.get("line"),
                "position": c.get("stake"),
                "price_moves": [a.get("reason") for a in c.get("alerts", []) if a.get("reason")],
            }
            for c in cards
        ],
        "still_open": [x.get("line") for x in d.get("carry", [])][:4],
        "unexplained_moves": d.get("moves_note", [])[:4],
        "set_aside": (d.get("set_aside") or {}).get("count", 0),
    }


class Note(BaseModel):
    paragraphs: list[str] = Field(
        description="2 or 3 short paragraphs; the first, in one or two sentences, what matters most"
    )


SYSTEM = (
    "You write the top of an Indian investor's morning note from facts FINN computed. "
    "Lead with what could change a decision (band 'act'), then what is worth knowing, then "
    "one line on what is still open or set aside. Plain English, short sentences, no "
    "headings or bullets. Use ONLY the facts: every figure exactly as given (₹ amounts, %, "
    "lakh, dates), no new numbers, no outside knowledge, no forecasts. Never tell the "
    "investor to buy, sell, hold or act; describe, don't advise. Under 110 words."
)

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ADVICE = re.compile(
    r"\b(you should|we recommend|consider (buying|selling|adding|trimming)|time to (buy|sell)|"
    r"buy (more|now)|sell (now|off)|book profits?)\b",
    re.I,
)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(text)}


def check(paras: list[str], f: dict, names: list[str]) -> str | None:
    """None when the note says nothing the facts don't."""
    text = " ".join(paras)
    src = json.dumps(f, ensure_ascii=False)
    have = _numbers(src)
    for n in _numbers(text):
        if n not in have and not (len(n) == 1 and n in "0123456789"):  # small counts as words
            return f"figure {n} not in the facts"
    m = _ADVICE.search(text)
    if m:
        return f"advice: '{m.group(0)}'"
    for nm in names:  # a portfolio company named in the note must be in the facts
        if re.search(rf"\b{re.escape(nm)}\b", text) and nm not in src:
            return f"names {nm}, not in the facts"
    if len(text) > 1200:
        return "too long"
    return None


def _key(f: dict) -> str:
    h = hashlib.sha256(json.dumps(f, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return f"todaynote:{h[:24]}"


def _write(key: str, f: dict, names: list[str]) -> None:
    from app.llm.router import get_llm

    try:
        out = get_llm().run(
            "summarise_today",
            system=SYSTEM,
            prompt="Facts:\n" + json.dumps(f, ensure_ascii=False, indent=1),
            schema=Note,
            prompt_version=PROMPT_VERSION,
            max_tokens=800,
        )
        paras = [p.strip() for p in out.paragraphs if p.strip()][:3]
        why = check(paras, f, names)
        if why:
            log.info("today note rejected (%s): %s", why, " ".join(paras)[:160])
            store.put(key, {"rejected": why}, ttl=3 * 3600)
            return
        store.put(key, {"text": "\n\n".join(paras)}, ttl=TTL_S)
        log.info("today note written (%d words)", len(" ".join(paras).split()))
    except Exception as e:  # noqa: BLE001 - the code lead stays
        log.warning("today note failed: %s", e)
    finally:
        with _lock:
            _running.discard(key)


def attach(d: dict, names: list[str]) -> None:
    """Add d['lead_ai'] when a checked note exists for these facts; otherwise start writing
    one and mark d['lead_ai_pending']."""
    if not d["cards"] and not d.get("carry"):
        return
    f = facts(d)
    key = _key(f)
    got = store.get(key)
    if got:
        v = got[0]
        if v.get("text"):
            d["lead_ai"] = {"text": v["text"], "by": "ai"}
        return
    with _lock:
        if key in _running:
            d["lead_ai_pending"] = True
            return
        _running.add(key)
    threading.Thread(target=_write, args=(key, f, names), daemon=True).start()
    d["lead_ai_pending"] = True
