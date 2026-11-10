#!/usr/bin/env python3
"""Link checker for listed offers (runs before build.py in the pipeline).

For every listed item it checks the link a visitor would click (official page first, else the source post):
  * x.com / twitter.com posts  -> public oEmbed endpoint (404 = post deleted)
  * everything else            -> HEAD, falling back to a small GET
Result per item: ok / dead (404, 410, unknown host) / unsure (403, 429, 5xx, timeout).
A link is only treated as gone after it is dead on 2 runs in a row (build.py then hides the item);
a single failure shows "待复查". If more than 40% of links look dead in one run the run is ignored
(probably our own network), so a bad connection never empties the site.
Writes data/auto/linkcheck.json. Never fails the pipeline.
"""
from __future__ import annotations

import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "auto" / "linkcheck.json"
TZ = ZoneInfo("Asia/Shanghai")
UA = "Mozilla/5.0 (compatible; aiym168-linkcheck/1.0; +https://aiym168.github.io/)"
TIMEOUT = 10
DEAD_CODES = {404, 410}
DEAD_AFTER = 2


def target(it: dict) -> str:
    return (it.get("start_url") or it.get("url") or "").strip()


def _open(url: str, method: str) -> int:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": "*/*"})
    if method == "GET":
        req.add_header("Range", "bytes=0-2047")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def check(url: str) -> tuple[str, int | None, str]:
    """-> (state, http_code, note)"""
    if not url.startswith(("http://", "https://")):
        return "unsure", None, "no link"
    host = urllib.parse.urlparse(url).netloc.lower()
    try:
        if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com") and "/status/" in url:
            code = _open("https://publish.twitter.com/oembed?omit_script=1&url=" + urllib.parse.quote(url, safe=""), "GET")
            note = "post"
        else:
            code = _open(url, "HEAD")
            if code in (400, 403, 405, 501) or code >= 500:
                code = _open(url, "GET")
            note = "page"
    except urllib.error.URLError as e:
        r = e.reason
        if isinstance(r, socket.gaierror):
            return "dead", None, "unknown host"
        return "unsure", None, str(r)[:60]
    except (socket.timeout, TimeoutError):
        return "unsure", None, "timeout"
    except Exception as e:  # noqa: BLE001
        return "unsure", None, type(e).__name__
    if 200 <= code < 400:
        return "ok", code, note
    if code in DEAD_CODES:
        return "dead", code, note
    return "unsure", code, note


def main() -> int:
    src = ROOT / "api" / "latest.json"
    try:
        items = json.loads(src.read_text(encoding="utf-8")).get("items") or []
    except Exception as e:  # noqa: BLE001
        print(f"[linkcheck] no item list ({e}); skip")
        return 0
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8")).get("items") or {}
    except Exception:  # noqa: BLE001
        prev = {}
    jobs = [(it["id"], target(it)) for it in items if it.get("id")]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=12) as ex:
        res = list(ex.map(lambda j: (j[0], j[1], check(j[1])), jobs))
    now = datetime.now(TZ).isoformat(timespec="seconds")
    dead_now = sum(1 for _i, _u, (s, _c, _n) in res if s == "dead")
    unreliable = len(res) >= 10 and dead_now > 0.4 * len(res)
    out = {}
    for iid, url, (state, code, note) in res:
        p = prev.get(iid) or {}
        if unreliable:  # keep yesterday's verdict, just note the attempt
            out[iid] = dict(p, url=url, last_attempt=now) if p else {"url": url, "state": "unsure", "fails": 0, "checked_at": None, "last_attempt": now}
            continue
        fails = (int(p.get("fails") or 0) + 1) if state == "dead" else 0
        rec = {"url": url, "state": state, "code": code, "note": note, "fails": fails, "checked_at": now,
               "last_ok": now if state == "ok" else p.get("last_ok")}
        rec["verdict"] = "gone" if fails >= DEAD_AFTER else "recheck" if fails else ("ok" if state == "ok" else "unsure")
        out[iid] = rec
    counts = {}
    for r in out.values():
        counts[r.get("verdict", "unsure")] = counts.get(r.get("verdict", "unsure"), 0) + 1
    doc = {"checked_at": now, "seconds": round(time.time() - t0, 1), "total": len(out), "unreliable_run": unreliable,
           "counts": counts, "items": out}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[linkcheck] {len(out)} links in {doc['seconds']}s counts={counts}" + (" (run ignored: too many failures)" if unreliable else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"[linkcheck] error {e}; continue")
        sys.exit(0)
