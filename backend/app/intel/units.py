"""One way of writing money and multiples in FINN's own sentences (code, no AI).

The AI's filing summaries copy whatever unit the filing used: "Rs 18,987 million",
"INR 100,000+ million", "Rs. 3,982 crores". Shown beside FINN's "₹953 Cr" that reads as
three products. This rewrites amounts to ₹ crore (the unit Indian investors read), signs
to a true minus and multiples to ×. Applied to summaries only: a verbatim quote from
management is never rewritten.
"""

from __future__ import annotations

import re

_CUR = r"(?:Rs\.?|INR|₹)\s?"
_NUM = r"(-|−)?\s?(\d[\d,]*(?:\.\d+)?)(\+)?"
_SCALE = {"million": 0.1, "mn": 0.1, "billion": 100.0, "bn": 100.0, "crore": 1.0, "cr": 1.0}
_AMOUNT = re.compile(_CUR + _NUM + r"\s?(million|mn|billion|bn|crores?|cr)\b\.?", re.IGNORECASE)
_BARE_CUR = re.compile(r"(?:\bRs\.?|\bINR)\s?(-|−)?\s?(?=\d)")
_MULTIPLE = re.compile(r"(?<![\w.])(-|−)?(\d+(?:\.\d+)?)x\b")


def _fmt(v: float) -> str:
    """Below ₹100 Cr: one decimal (₹5.8 Cr), two below ₹1 Cr."""
    return f"{v:.1f}".rstrip("0").rstrip(".") if v >= 1 else f"{v:.2f}"


def _indian(n: float) -> str:
    """12,34,567 grouping, as the rest of FINN shows rupees."""
    s = f"{round(n)}"
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])


def _amount(m: re.Match) -> str:
    neg, num, plus, unit = m.group(1), m.group(2), m.group(3) or "", m.group(4).lower()
    v = float(num.replace(",", "")) * _SCALE[unit.rstrip("s")]
    shown = _indian(v) if v >= 100 else _fmt(v)
    return f"{'−' if neg else ''}₹{shown}{plus} Cr"


def normalise(text: str | None) -> str | None:
    if not text:
        return text
    out = _AMOUNT.sub(_amount, text)
    out = _BARE_CUR.sub(lambda m: ("−" if m.group(1) else "") + "₹", out)
    out = _MULTIPLE.sub(lambda m: f"{'−' if m.group(1) else ''}{m.group(2)}×", out)
    return out
