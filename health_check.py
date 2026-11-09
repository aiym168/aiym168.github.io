#!/usr/bin/env python3
"""Validate generated site before publish. Exit 1 if broken."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIN_HTML = 1500


def fail(msg: str) -> None:
    print(f"[health] FAIL: {msg}")
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"[health] OK: {msg}")


def main() -> int:
    required = [
        ROOT / "index.html",
        ROOT / "404.html",
        ROOT / "feed.xml",
        ROOT / "api" / "latest.json",
        ROOT / "api" / "meta.json",
        ROOT / "api" / "index.json",
        ROOT / "api" / "github-hot.json",
        ROOT / "api" / "hot.json",
        ROOT / "m" / "github-hot.html",
        ROOT / "m" / "hot-topics.html",
        ROOT / "m" / "api.html",
        ROOT / "cli.sh",
        ROOT / "fx.css",
        ROOT / "vendor" / "brain-hero.js",
        ROOT / "deals" / "index.html",
        ROOT / "api" / "deals.json",
    ]
    for p in required:
        if not p.exists():
            fail(f"missing {p.relative_to(ROOT)}")
        if p.stat().st_size < (80 if p.suffix == ".sh" else 200):
            fail(f"too small {p.relative_to(ROOT)} ({p.stat().st_size}b)")

    index = (ROOT / "index.html").read_text(encoding="utf-8", errors="replace")
    if len(index) < MIN_HTML:
        fail(f"index.html too short ({len(index)})")
    for needle in ("AI大模型免费资源导航", "brain-hero", "选择模块", "CLI / API") + (("pin-card",) if (ROOT / "data" / "pinned.json").exists() else ()):
        if needle not in index:
            fail(f"index.html missing marker: {needle}")

    meta = json.loads((ROOT / "api" / "meta.json").read_text(encoding="utf-8"))
    counts = meta.get("counts") or {}
    deals = int(counts.get("deals") or 0)
    repos = int(counts.get("github_hot") or 0)
    hot = int(counts.get("hot") or 0)
    if deals <= 0:
        fail("meta counts.deals <= 0")
    if repos <= 0:
        fail("meta counts.github_hot <= 0")
    if hot <= 0:
        fail("meta counts.hot <= 0")

    latest = json.loads((ROOT / "api" / "latest.json").read_text(encoding="utf-8"))
    items = latest.get("items") or []
    if len(items) <= 0:
        fail("api/latest.json items empty")

    # Abnormal shrink guard: new build must keep >= 60% of last good item count
    lg = ROOT / ".last_good" / "api" / "latest.json"
    if lg.exists():
        try:
            prev_n = len(json.loads(lg.read_text(encoding="utf-8")).get("items") or [])
        except Exception:
            prev_n = 0
        # A deliberate curation change (meta.curation_version bump) may legitimately drop many low-quality items.
        try:
            prev_cv = json.loads((ROOT / ".last_good" / "api" / "meta.json").read_text(encoding="utf-8")).get("curation_version")
        except Exception:
            prev_cv = None
        cur_cv = meta.get("curation_version")
        if cur_cv and cur_cv != prev_cv:
            ok(f"shrink guard skipped: curation_version {prev_cv} -> {cur_cv} ({len(items)} vs last good {prev_n})")
            prev_n = 0
        if prev_n >= 10 and len(items) < 0.6 * prev_n:
            fail(f"items shrank abnormally: {len(items)} < 60% of last good {prev_n}")
        ok(f"shrink guard: {len(items)} vs last good {prev_n}")

    dhtml = (ROOT / "deals" / "index.html").read_text(encoding="utf-8", errors="replace")
    if "全球优惠情报中心" not in dhtml or "brain-hero" not in dhtml:
        fail("deals/index.html missing markers")
    dmods = [p for p in ("today", "top", "ai", "crypto", "bank", "cloud", "expiring", "archive") if not (ROOT / "deals" / f"{p}.html").exists()]
    if dmods:
        fail(f"deals module pages missing: {dmods}")
    if (ROOT / "data" / "apiprices" / "prices.json").exists() and not (ROOT / "deals" / "api-prices.html").exists():
        fail("deals/api-prices.html missing")

    cats = list((ROOT / "c").glob("*.html")) if (ROOT / "c").exists() else []
    if len(cats) < 3:
        fail(f"category pages too few: {len(cats)}")

    ok(f"index={len(index)}b deals={deals} repos={repos} hot={hot} cats={len(cats)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
