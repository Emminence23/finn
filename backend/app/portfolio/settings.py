"""The investor's own portfolio rules. Nothing about the suggestion is fixed in code.

DEFAULTS are only a starting point (a common long-only discipline for 15-20 stocks). Each
account can change any of them, or switch a limit off with null. Values are percent unless
noted. Code adapts when a rule can't be met: a minimum above an equal share, or theme caps
that can't add up to 100%, are relaxed just enough and the page says so.
"""

from __future__ import annotations

import json

from app.db import session
from app.network.owner import current_owner

DEFAULTS: dict[str, float | int | None] = {
    "min_pct": 2.0,  # smallest holding the suggestion keeps (null: no minimum)
    "max_pct": 9.0,  # largest single holding (null: no maximum)
    "theme_cap_pct": 20.0,  # largest theme (null: no cap); also the concentration warning
    "max_step_pct": 3.0,  # most one holding moves in one go (null: straight to target)
    "tilt": 0.30,  # quality tilt strength; 0 = pure risk balance
    "risk_days": 126,  # sessions of daily returns for risk (about six months)
    "ai_nudge_pct": 2.0,  # most the AI review may move one holding
    "ai_max_adjust": 5,  # most holdings the AI review may move
    "lot_pct": 0.5,  # the − / + buttons in Edit move a holding by shares worth about this
    "new_holding_pct": 3.0,  # a company added in Edit comes in at about this
}
# what each value may be: (low, high), inclusive; None limits may also be switched off
RANGE = {
    "min_pct": (0.0, 50.0),
    "max_pct": (1.0, 100.0),
    "theme_cap_pct": (1.0, 100.0),
    "max_step_pct": (0.1, 100.0),
    "tilt": (0.0, 2.0),
    "risk_days": (20, 250),
    "ai_nudge_pct": (0.0, 20.0),
    "ai_max_adjust": (0, 20),
    "lot_pct": (0.01, 25.0),
    "new_holding_pct": (0.01, 50.0),
}
NULLABLE = {"min_pct", "max_pct", "theme_cap_pct", "max_step_pct"}


def get_settings(owner: str | None = None) -> dict:
    owner = owner or current_owner()
    with session() as db:
        row = db.execute(
            "SELECT params_json FROM portfolio_settings WHERE owner_id=?", (owner,)
        ).fetchone()
    saved = json.loads(row["params_json"]) if row else {}
    return {k: saved.get(k, v) for k, v in DEFAULTS.items()}


def is_default(owner: str | None = None) -> bool:
    return get_settings(owner) == DEFAULTS


def set_settings(changes: dict, owner: str | None = None) -> dict:
    """Update some rules. Unknown keys and out-of-range values are refused."""
    owner = owner or current_owner()
    cur = get_settings(owner)
    for k, v in changes.items():
        if k not in DEFAULTS:
            raise KeyError(f"unknown setting '{k}'")
        if v is None:
            if k not in NULLABLE:
                raise ValueError(f"{k} can't be switched off")
            cur[k] = None
            continue
        lo, hi = RANGE[k]
        v = int(v) if isinstance(DEFAULTS[k], int) else round(float(v), 2)
        if not lo <= v <= hi:
            raise ValueError(f"{k} must be between {lo:g} and {hi:g}")
        cur[k] = v
    if (
        cur["min_pct"] is not None
        and cur["max_pct"] is not None
        and cur["min_pct"] > cur["max_pct"]
    ):
        raise ValueError("the minimum holding can't be above the maximum")
    with session() as db:
        db.execute(
            "INSERT OR REPLACE INTO portfolio_settings (owner_id, params_json) VALUES (?,?)",
            (owner, json.dumps(cur)),
        )
    return cur


def reset_settings(owner: str | None = None) -> dict:
    with session() as db:
        db.execute("DELETE FROM portfolio_settings WHERE owner_id=?", (owner or current_owner(),))
    return get_settings(owner)


def limits(n: int, n_themes: int, owner: str | None = None) -> dict:
    """The rules as fractions, made feasible for n holdings across n_themes themes.
    Returns the limits and plain notes on anything that had to be relaxed."""
    s = get_settings(owner)
    notes = []
    lo = (s["min_pct"] or 0) / 100
    hi = (s["max_pct"] if s["max_pct"] is not None else 100) / 100
    cap = (s["theme_cap_pct"] if s["theme_cap_pct"] is not None else 100) / 100
    if n and lo * n > 1:
        notes.append(
            f"A {s['min_pct']:g}% minimum can't hold for {n} stocks; using {100 / n:.1f}%."
        )
        lo = 1 / n
    if n and hi * n < 1:
        notes.append(
            f"A {s['max_pct']:g}% maximum can't add up to 100% with {n} stocks; "
            f"using {100 / n:.1f}%."
        )
        hi = 1 / n
    if n_themes and cap * n_themes < 1:
        notes.append(
            f"A {s['theme_cap_pct']:g}% theme cap can't add up to 100% over {n_themes} themes; "
            f"using {100 / n_themes:.1f}%."
        )
        cap = 1 / n_themes
    step = (s["max_step_pct"] if s["max_step_pct"] is not None else 100) / 100
    return {
        "min": lo,
        "max": hi,
        "theme_cap": cap,
        "step": step,
        "tilt": float(s["tilt"]),
        "risk_days": int(s["risk_days"]),
        "ai_nudge": float(s["ai_nudge_pct"]),
        "ai_max_adjust": int(s["ai_max_adjust"]),
        "settings": s,
        "notes": notes,
    }
