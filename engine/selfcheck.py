#!/usr/bin/env python3
"""Weekly source self-check (GitHub Actions). Probes every news source; a source that fails two weekly
checks in a row gets "disabled": true; a disabled one that works again is re-enabled. Writes data/news/selfcheck.json."""
from __future__ import annotations
import json, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import news_collect as nc  # noqa: E402

REG = ROOT / "data" / "news" / "sources.json"
OUT = ROOT / "data" / "news" / "selfcheck.json"


def probe(s):
    t = (s["key"], s["name"], s["home"], s["feed"], s["channel"], s.get("lang", "en"), bool(s.get("need_ai")))
    nc.KIND[s["key"]] = s.get("kind", "")
    try:
        _k, rows, err = nc.fetch_source(t)
        return s["key"], (len(rows) > 0 and not err), (err or ("" if rows else "0 rows"))[:120]
    except Exception as e:
        return s["key"], False, f"{type(e).__name__}: {e}"[:120]


def main() -> int:
    reg = json.loads(REG.read_text(encoding="utf-8"))
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8")).get("sources") or {}
        except Exception:
            prev = {}
    with ThreadPoolExecutor(12) as ex:
        res = {k: (ok, err) for k, ok, err in ex.map(probe, reg["sources"])}
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="minutes")
    rep, off, on = {}, [], []
    for s in reg["sources"]:
        ok, err = res[s["key"]]
        fails = 0 if ok else (prev.get(s["key"], {}).get("fails", 0) + 1)
        rep[s["key"]] = {"ok": ok, "fails": fails, "err": err, "checked": now}
        if ok and s.get("disabled"):
            s.pop("disabled", None); s.pop("disabled_reason", None); on.append(s["key"])
        elif not ok and fails >= 2 and not s.get("disabled"):
            s["disabled"] = True; s["disabled_reason"] = f"{now[:10]} 连续 {fails} 周探测失败：{err}"; off.append(s["key"])
    REG.write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    good = sum(1 for v in rep.values() if v["ok"])
    OUT.write_text(json.dumps({"checked": now, "ok": good, "total": len(rep), "disabled_now": off, "re_enabled": on, "sources": rep},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[selfcheck] ok {good}/{len(rep)} · disabled {off} · re-enabled {on}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
