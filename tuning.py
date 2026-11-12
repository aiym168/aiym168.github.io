"""Read-only view of the self-evolution tuning (data/evolve/tuning.json) for the collectors.

evolve.py is the only writer. If the file is missing or broken, everything behaves as before
(all sources active, weight 1.0, no promoted sources)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PATH = ROOT / "data" / "evolve" / "tuning.json"
TZ = ZoneInfo("Asia/Shanghai")
W_MIN, W_MAX = 0.5, 2.0
_t: dict | None = None


def load() -> dict:
    global _t
    if _t is None:
        try:
            _t = json.loads(PATH.read_text(encoding="utf-8"))
            if not isinstance(_t, dict):
                _t = {}
        except Exception:
            _t = {}
    return _t


def entry(group: str, key: str) -> dict:
    try:
        e = (load().get(group) or {}).get(key) or {}
        return e if isinstance(e, dict) else {}
    except Exception:
        return {}


def weight(group: str, key: str) -> float:
    try:
        return max(W_MIN, min(W_MAX, float(entry(group, key).get("weight", 1.0))))
    except Exception:
        return 1.0


def should_fetch(group: str, key: str, now: datetime | None = None) -> bool:
    """False when evolution paused the source, or it is on a slower cadence and this is not its hour."""
    try:
        e = entry(group, key)
        st = e.get("state", "active")
        if st == "paused":
            return False
        every = int(e.get("every", 1) or 1)
        if every > 1 and st != "retest":
            h = (now or datetime.now(TZ)).hour
            return h % every == 0
        return True
    except Exception:
        return True


def promoted(group: str = "news") -> list[dict]:
    try:
        L = load().get("promoted_" + group) or []
        return [x for x in L if isinstance(x, dict) and x.get("key") and x.get("feed")]
    except Exception:
        return []
