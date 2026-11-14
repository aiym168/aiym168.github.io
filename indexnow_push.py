#!/usr/bin/env python3
"""Submit fresh sitemap URLs to IndexNow (Bing/Yandex/etc). No Bing login required.

Ownership is proven by a public key file at the site root: /{key}.txt
Key stored in data/auto/indexnow_key.json (not a secret; it must be publicly fetchable).

Bing and api.indexnow.org answer 403 UserForbiddedToAccessSite when the key
value itself is rejected, even if the file is already being served. A new random
key clears that. The first submit after the new file is deployed can still 403
until their crawler fetches it; INDEXNOW_WAIT_SEC retries through that window.
Yandex often answers 200 without doing that check, so a Yandex 200 is not treated
as proof the key is verified.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY_STATE = ROOT / "data" / "auto" / "indexnow_key.json"
PUSHED = ROOT / "data" / "auto" / "indexnow_pushed.json"
SITEMAP_TXT = ROOT / "sitemap.txt"
WELL_KNOWN = ROOT / ".well-known" / "indexnow.txt"
HOST = "aiym168.github.io"
PRIMARY = (
    "https://api.indexnow.org/indexnow",
    "https://www.bing.com/indexnow",
)
SECONDARY = ("https://yandex.com/indexnow",)


def _load_key() -> str | None:
    if KEY_STATE.exists():
        try:
            k = (json.loads(KEY_STATE.read_text(encoding="utf-8")).get("key") or "").strip()
            if 8 <= len(k) <= 128 and all(c.isalnum() or c == "-" for c in k):
                return k
        except Exception:
            pass
    for p in ROOT.glob("*.txt"):
        if p.name in ("sitemap.txt", "robots.txt"):
            continue
        body = p.read_text(encoding="utf-8").strip()
        if body and body == p.stem and 8 <= len(body) <= 128:
            KEY_STATE.parent.mkdir(parents=True, exist_ok=True)
            KEY_STATE.write_text(json.dumps({"key": body}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return body
    return None


def _ensure_local(key: str) -> None:
    key_file = ROOT / f"{key}.txt"
    current = key_file.read_text(encoding="utf-8").strip() if key_file.exists() else ""
    if current != key:
        # Exact key bytes. A trailing newline is accepted by verifiers that strip,
        # but writing only the key keeps the public file identical to the JSON.
        key_file.write_bytes(key.encode("utf-8"))
        print(f"[indexnow] wrote key file {key_file.name}")
    WELL_KNOWN.parent.mkdir(parents=True, exist_ok=True)
    known = WELL_KNOWN.read_text(encoding="utf-8").strip() if WELL_KNOWN.exists() else ""
    if known != key:
        WELL_KNOWN.write_bytes(key.encode("utf-8"))


def key_matches(body: str, key: str) -> bool:
    return body.strip() == key


def check_local() -> int:
    key = _load_key()
    if not key:
        print("[indexnow] no key")
        return 1
    root_file = ROOT / f"{key}.txt"
    root_body = root_file.read_text(encoding="utf-8") if root_file.exists() else ""
    well_body = WELL_KNOWN.read_text(encoding="utf-8") if WELL_KNOWN.exists() else ""
    if not key_matches(root_body, key) or not key_matches(well_body, key):
        print("[indexnow] local key files do not match data/auto/indexnow_key.json")
        return 1
    if (ROOT / "cPVql59NwdhOJ5dmXGgRmGuf59RJXt9g.txt").exists():
        print("[indexnow] retired key file is still present")
        return 1
    print(f"[indexnow] local key ok len={len(key)}")
    return 0


def _live_key(key: str) -> str | None:
    url = f"https://{HOST}/{key}.txt?t={int(time.time())}"
    req = urllib.request.Request(url, headers={"User-Agent": "aiym168-indexnow/1.0", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                return None
            return resp.read().decode("utf-8", "replace")
    except Exception:
        return None


def _post(ep: str, payload: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        ep,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "aiym168-indexnow/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.getcode(), resp.read().decode("utf-8", "replace")[:300]
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return e.code, detail
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def _save(prev: set[str], batch: list[str]) -> None:
    prev.update(batch)
    PUSHED.parent.mkdir(parents=True, exist_ok=True)
    PUSHED.write_text(json.dumps({"urls": sorted(prev)[-8000:]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if os.environ.get("INDEXNOW_DISABLE", "").strip() in ("1", "true", "yes"):
        print("[indexnow] disabled by env")
        return 0
    key = _load_key()
    if not key:
        print("[indexnow] no key — skip")
        return 0
    _ensure_local(key)
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
    priority = [
        f"https://{HOST}/",
        f"https://{HOST}/deals/index.html",
        f"https://{HOST}/m/octopus.html",
        f"https://{HOST}/m/board.html",
        f"https://{HOST}/news/index.html",
    ]
    fresh = [u for u in urls if u not in prev]
    fresh.sort(key=lambda u: (0 if "/news/a/" in u else 1 if "/news/" in u else 2))
    batch: list[str] = []
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
    wait = int(os.environ.get("INDEXNOW_WAIT_SEC", "0") or "0")
    deadline = time.time() + max(0, wait)
    while True:
        live = _live_key(key)
        if live is not None and key_matches(live, key):
            print("[indexnow] live key file matches")
            break
        if time.time() >= deadline:
            print(f"[indexnow] key file not live yet at https://{HOST}/{key}.txt — skip until it is deployed")
            return 0
        print("[indexnow] waiting for the key file to be deployed")
        time.sleep(15)

    secondary_tried = False
    while True:
        verified = False
        for ep in PRIMARY:
            code, body = _post(ep, payload)
            print(f"[indexnow] {ep} -> {code} {body!r}")
            if code in (200, 202):
                verified = True
                break
        if verified:
            _save(prev, batch)
            print(f"[indexnow] verified n={len(batch)}")
            return 0
        if not secondary_tried:
            secondary_tried = True
            for ep in SECONDARY:
                code, body = _post(ep, payload)
                print(f"[indexnow] {ep} -> {code} {body!r}")
        if time.time() >= deadline:
            print("[indexnow] Bing/IndexNow still rejecting the key; will try again next run")
            return 0
        print("[indexnow] key not verified yet, retrying")
        time.sleep(30)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        raise SystemExit(check_local())
    raise SystemExit(main())
