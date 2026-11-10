#!/usr/bin/env python3
"""Submit fresh sitemap URLs to IndexNow (Bing/Yandex/etc). No Bing login required.

Ownership is proven by a public key file at the site root: /{key}.txt
Key stored in data/auto/indexnow_key.json (not secret; must be publicly fetchable).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY_STATE = ROOT / "data" / "auto" / "indexnow_key.json"
PUSHED = ROOT / "data" / "auto" / "indexnow_pushed.json"
SITEMAP_TXT = ROOT / "sitemap.txt"
HOST = "aiym168.github.io"
ENDPOINT = "https://api.indexnow.org/indexnow"


def _load_key() -> str | None:
    if KEY_STATE.exists():
        try:
            k = (json.loads(KEY_STATE.read_text(encoding="utf-8")).get("key") or "").strip()
            if 8 <= len(k) <= 128:
                return k
        except Exception:
            pass
    # discover existing root key files
    for p in ROOT.glob("*.txt"):
        if p.name in ("sitemap.txt", "robots.txt"):
            continue
        body = p.read_text(encoding="utf-8").strip()
        if body and body == p.stem and 8 <= len(body) <= 128:
            KEY_STATE.parent.mkdir(parents=True, exist_ok=True)
            KEY_STATE.write_text(json.dumps({"key": body}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return body
    return None


def main() -> int:
    if os.environ.get("INDEXNOW_DISABLE", "").strip() in ("1", "true", "yes"):
        print("[indexnow] disabled by env")
        return 0
    key = _load_key()
    if not key:
        print("[indexnow] no key — skip")
        return 0
    key_file = ROOT / f"{key}.txt"
    if not key_file.exists() or key_file.read_text(encoding="utf-8").strip() != key:
        key_file.write_text(key + "\n", encoding="utf-8")
        print(f"[indexnow] wrote key file {key_file.name}")
    if not SITEMAP_TXT.exists():
        print("[indexnow] no sitemap.txt — skip")
        return 0
    urls = [u.strip() for u in SITEMAP_TXT.read_text(encoding="utf-8").splitlines() if u.strip()]
    prev: set[str] = set()
    if PUSHED.exists():
        try:
            prev = set(json.loads(PUSHED.read_text(encoding="utf-8")).get("urls") or [])
        except Exception:
            prev = set()
    # prefer fresh URLs; always include homepage + key pages
    priority = [
        f"https://{HOST}/",
        f"https://{HOST}/deals/index.html",
        f"https://{HOST}/m/octopus.html",
        f"https://{HOST}/m/board.html",
        f"https://{HOST}/news/index.html",
    ]
    fresh = [u for u in urls if u not in prev]
    fresh.sort(key=lambda u: (0 if "/news/a/" in u else 1 if "/news/" in u else 2))  # 新闻条目先推
    batch = []
    for u in priority + fresh:
        if u not in batch:
            batch.append(u)
        if len(batch) >= 500:
            break
    if not batch:
        batch = priority[:4]
    payload = {
        "host": HOST,
        "key": key,
        "keyLocation": f"https://{HOST}/{key}.txt",
        "urlList": batch,
    }
    endpoints = [
        ENDPOINT,
        "https://www.bing.com/indexnow",
        "https://yandex.com/indexnow",
    ]
    ok = False
    last = ""
    for ep in endpoints:
        req = urllib.request.Request(
            ep,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "aiym168-indexnow/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                code = resp.getcode()
                body = resp.read().decode("utf-8", "replace")[:300]
                print(f"[indexnow] ok ep={ep} status={code} n={len(batch)} body={body!r}")
                ok = True
                break
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            last = f"http {e.code}: {detail}"
            print(f"[indexnow] {ep} -> {last}")
            # 202 Accepted is success for first-time key verify on some engines
            if e.code == 202:
                ok = True
                break
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            print(f"[indexnow] {ep} -> {last}")
    if not ok:
        print(f"[indexnow] all endpoints failed; last={last}")
        return 0
    prev.update(batch)
    PUSHED.parent.mkdir(parents=True, exist_ok=True)
    PUSHED.write_text(
        json.dumps({"urls": sorted(prev)[-8000:]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
