"""How accurate is FINN: the measurements behind the app, shown in the app.

Live checks are recomputed from the current data on every request, so the page can't drift
from the product. Build-time measurements (extraction accuracy, model comparison) need a
model run or a hand check, so they are reported as measured, with when and how.
"""

from __future__ import annotations

import json

from app.db import session
from app.ingest.universe import fixtures_dir
from app.intel.digest import build_digest

YEAR = ("2026-01-01T00:00:00", "2026-12-31T23:59:59")


def _labels() -> dict:
    return json.loads((fixtures_dir() / "eval" / "materiality_labels.json").read_text())


def _where(digest: dict) -> dict[str, str]:
    out = {}
    for c in digest["cards"]:
        for fid in [c["id"], *(r["id"] for r in c["related"])]:
            out[str(fid)] = c["level"]
    for r in digest["routine"]["items"]:
        out[str(r["id"])] = "routine"
    return out


def labelled_filings() -> dict:
    """The hand-labelled set next to where FINN puts each filing today, so a reader can
    check every call, including the misses."""
    lab = _labels()
    where = _where(build_digest(start=YEAR[0], end=YEAR[1]))
    ids = [x["id"] for x in lab["labels"]]
    q = ",".join("?" * len(ids))
    with session() as db:
        meta = {
            r["id"]: dict(r)
            for r in db.execute(
                f"SELECT id, symbol, ts, subject, summary, pdf_url FROM announcements "
                f"WHERE id IN ({q})",
                ids,
            )
        }
    rows = []
    for x in lab["labels"]:
        m = meta.get(x["id"], {})
        level = where.get(x["id"], "outside window")
        rows.append(
            {
                "id": x["id"],
                "symbol": m.get("symbol"),
                "ts": m.get("ts"),
                "title": m.get("summary") or m.get("subject"),
                "pdf_url": m.get("pdf_url"),
                "material": x["material"],
                "finn_level": level,
                "agrees": (level in ("important", "notable")) == x["material"],
            }
        )
    return {"definition": lab.get("definition"), "about": lab.get("about"), "filings": rows}


def report() -> dict:
    lab = labelled_filings()["filings"]
    material = [r for r in lab if r["material"]]
    kept = [r for r in material if r["finn_level"] in ("important", "notable")]
    routine_flagged = [r for r in lab if not r["material"] and r["finn_level"] != "routine"]

    live = [
        {
            "what": "Material filings kept out of Routine",
            "result": f"{len(kept)} of {len(material)}",
            "target": "at least 95%",
            "passes": len(material) > 0 and len(kept) / len(material) >= 0.95,
            "how": "100 portfolio filings drawn at random with a fixed seed and labelled from "
            "their text before the levels were tuned",
            "detail": f"{len(routine_flagged)} filings labelled not material are still shown "
            f"(FINN errs towards showing)",
        }
    ]
    for window in ("7d", "30d"):
        d = build_digest(window)
        items = len(d["cards"]) + d["counts"]["routine"]
        imp = sum(c["level"] == "important" for c in d["cards"])
        share = imp / items if items else 0
        live.append(
            {
                "what": f"Items marked Important, last {window.replace('d', ' days')}",
                "result": f"{share:.1%} ({imp} of {items})",
                "target": "at most 20%",
                "passes": share <= 0.20,
                "how": "Cards plus folded filings in the digest",
            }
        )
    with session() as db:
        checks = [
            (json.loads(r[0] or "{}").get("results") or {}).get("cross_check") or {}
            for r in db.execute("SELECT enrichment_json FROM announcements")
        ]
    checks = [c for c in checks if c]
    status = [c.get("status") for c in checks]
    match, basis = status.count("match"), status.count("pat_basis")
    live.append(
        {
            "what": "Results figures that agree with screener.in",
            "result": f"{match} of {len(checks)} match; {basis} differ only on the profit basis",
            "target": None,
            "passes": None,
            "how": "Revenue, PBT and PAT read from each results filing, compared with "
            "screener's figures for the same quarter",
            "detail": f"{len(checks) - match - basis} had no screener figures to compare",
        }
    )

    measured = [
        {
            "what": "Filings decided by rules, with no LLM call",
            "result": "454 of 517",
            "how": "Ingested portfolio filings; the rest went to batched triage",
            "when": "Phase 2",
        },
        {
            "what": "People read from management-change filings",
            "result": "7/7 people and roles, 17/18 prior employers, 8/10 schools",
            "how": "Hand-checked golden set of the seven people in the demo filings",
            "when": "Phase 2",
        },
        {
            "what": "Promises found in Kaynes' four calls, small vs mid model",
            "result": "5 vs 10, including all 3 misses",
            "how": "Same calls, two model tiers; why the scorecard uses the larger one",
            "when": "Phase 3",
        },
        {
            "what": "Ask FINN points that survive the citation check",
            "result": "Uncited points are removed in code",
            "how": "A point citing a page that wasn't sent, or an unknown source, is dropped "
            "and counted; tested with a fake model that invents both",
            "when": "Phase 4b",
        },
    ]
    return {"live": live, "measured": measured}
