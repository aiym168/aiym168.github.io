#!/usr/bin/env python3
"""Write run marker, update log, public /api/status.json + /m/status.html (更新动态) and data/_internal_status.json.

env:
  ENGINE=A|B|C        which engine ran (marker data/engine_a.json / engine_b.json / engine_c.json)
  ENGINE_MODE=...     scheduled / takeover / forced / dispatch
  RUN_RESULT=ok|rolled_back|failed
  RUN_URL=...         link to the run (Actions URL or box log)
  STATUS_MARK=0       only render page, don't update the marker
"""
from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import build as B

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TZ = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")


def j(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def lbl(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M Asia/Shanghai")


def next_engine_a(now: datetime) -> datetime:
    """cron '7 * * * *' + '37 */2 * * *' (UTC)."""
    u = now.astimezone(UTC).replace(second=0, microsecond=0)
    cands = []
    for h in range(0, 4):
        base = (u + timedelta(hours=h)).replace(minute=0)
        cands.append(base.replace(minute=7))
        if base.hour % 2 == 0:
            cands.append(base.replace(minute=37))
    return min(c for c in cands if c > u)


def next_minute(now: datetime, minutes: tuple[int, ...]) -> datetime:
    t = now.astimezone(TZ).replace(second=0, microsecond=0)
    for _ in range(0, 120):
        t += timedelta(minutes=1)
        if t.minute in minutes:
            return t
    return t


def write_marker(now: datetime) -> None:
    eng = (os.environ.get("ENGINE") or "").upper()
    if eng not in ("A", "B", "C") or os.environ.get("STATUS_MARK", "1") == "0":
        return
    meta = j(ROOT / "api" / "meta.json")
    path = DATA / f"engine_{eng.lower()}.json"
    prev = j(path)
    result = os.environ.get("RUN_RESULT", "ok")
    marker = {
        "engine": eng,
        "name": {"A": "GitHub Actions 云端引擎", "B": "Simular 云服务器引擎", "C": "Simular 云服务器引擎（二）"}[eng],
        "mode": os.environ.get("ENGINE_MODE", "scheduled"),
        "result": result,
        "last_run_at": now.isoformat(timespec="seconds"),
        "last_run_label": lbl(now),
        "last_success_label": lbl(now) if result in ("ok", "rolled_back") else prev.get("last_success_label"),
        "run_url": os.environ.get("RUN_URL", ""),
        "host": "github-actions" if eng == "A" else socket.gethostname(),
        "counts": (meta.get("counts") or {}),
        "runs_total": int(prev.get("runs_total") or 0) + 1,
    }
    if os.environ.get("ENGINE_SEEN_ONLY") == "1":
        marker = dict(prev or {}, engine=eng, name=marker["name"])
        marker["standby_seen_label"] = lbl(now)
        marker["standby_seen_at"] = now.isoformat(timespec="seconds")
    path.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[status] marker {path.name}: {marker.get('mode')} {marker.get('result')}")


def age_min(iso: str | None, now: datetime) -> int | None:
    if not iso:
        return None
    try:
        return int((now - datetime.fromisoformat(iso)).total_seconds() // 60)
    except Exception:
        return None


def build_status(now: datetime) -> dict:
    a, b, c = j(DATA / "engine_a.json"), j(DATA / "engine_b.json"), j(DATA / "engine_c.json")
    c_seen = max(filter(None, [c.get("last_run_at"), c.get("standby_seen_at")]), default=None)
    meta = j(ROOT / "api" / "meta.json")
    health = j(DATA / "sources_health.json")
    disc = j(DATA / "auto" / "discovered.json")
    dstate = j(DATA / "auto" / "discovery_state.json")
    links = j(DATA / "link_health.json")
    xs = j(DATA / "auto" / "x_fetch_status.json")
    hb = j(DATA / "heartbeat.json")
    b_seen = max(filter(None, [b.get("last_run_at"), b.get("standby_seen_at")]), default=None)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_label": lbl(now),
        "site": "https://aiym168.github.io/",
        "engines": {
            "A": {
                **a,
                "schedule": "每小时第 7 分钟 + 每 2 小时第 37 分钟（备用）",
                "next_run_label": lbl(next_engine_a(now)),
                "age_min": age_min(a.get("last_run_at"), now),
            },
            "B": {
                **b,
                "schedule": "服务器每小时第 25 分钟检查；GitHub 超过 90 分钟没更新就接管",
                "next_run_label": lbl(next_minute(now, (25,))),
                "last_seen_at": b_seen,
                "age_min": age_min(b_seen, now),
            },
            "C": {
                **c,
                "schedule": "第二台服务器每小时第 55 分钟检查；网站超过 75 分钟没更新才接管；另每天 08:30 / 20:30 生成羊毛电台",
                "next_run_label": lbl(next_minute(now, (55,))),
                "last_seen_at": c_seen,
                "age_min": age_min(c_seen, now),
            },
            "watchdog": {
                "schedule": "每 30 分钟（第 23 / 53 分钟）",
                "next_run_label": lbl(next_minute(now, (23, 53))),
            },
        },
        "counts": meta.get("counts") or {},
        "data_updated_label": meta.get("updated_at_label"),
        "sources": health.get("sources") or {},
        "translators": health.get("translators") or {},
        "discovery": {
            "last_run_label": dstate.get("last_run_label"),
            "items": len(disc.get("items") or []),
            "new_this_run": disc.get("new_this_run"),
            "learned_topics": dstate.get("learned_topics") or [],
        },
        "links": {
            "checked_at_label": links.get("checked_at_label"),
            "checked": links.get("checked"),
            "dead_count": links.get("dead_count"),
        },
        "x": {
            "updated_at_label": xs.get("updated_at_label"),
            "primary_route": xs.get("primary_route"),
            "kept": xs.get("kept"),
        },
        "heartbeat_label": hb.get("updated_at_label"),
        "server": _server(j(DATA / "box_state.json")),
        "server2": _server(j(DATA / "box_state_2.json")),
    }


def _server(b: dict) -> dict:
    if not b:
        return {}
    keep = ("box_id", "checked_at_label", "state_before", "state_after", "state_after_zh", "wake_reasons", "actions",
            "wake_schedule", "last_saved_label", "ok", "error", "engine_b_age_min")
    out = {k: b.get(k) for k in keep if k in b}
    out["box_id"] = "已隐藏"
    return out


UPDATE_LOG = DATA / "_update_log.json"
INTERNAL = DATA / "_internal_status.json"


def record_update(now: datetime) -> None:
    """Append this run's newly added items to data/_update_log.json (kept 7 days)."""
    if (os.environ.get("ENGINE") or "") == "" or os.environ.get("STATUS_MARK", "1") == "0" or os.environ.get("ENGINE_SEEN_ONLY") == "1":
        return
    prev_p = ROOT / ".last_good" / "api" / "latest.json"
    cur = j(ROOT / "api" / "latest.json").get("items") or []
    if not prev_p.exists() or not cur:
        return
    prev_urls = {(it.get("url") or "").rstrip("/") for it in (j(prev_p).get("items") or [])}
    new = [it for it in cur if not it.get("pinned") and (it.get("url") or "").rstrip("/") not in prev_urls]
    log = j(UPDATE_LOG, {"entries": []})
    entries = log.get("entries") or []
    entries.insert(0, {
        "at": now.isoformat(timespec="seconds"),
        "at_label": lbl(now),
        "added": len(new),
        "total": len([it for it in cur if not it.get("pinned")]),
        "new": [{"title": it.get("title"), "url": it.get("url"), "path": it.get("path"), "category": it.get("category")} for it in new[:30]],
    })
    cutoff = now - timedelta(days=7)
    entries = [e for e in entries if datetime.fromisoformat(e["at"]) >= cutoff][:400]
    UPDATE_LOG.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def public_status(now: datetime) -> dict:
    meta = j(ROOT / "api" / "meta.json")
    latest = j(ROOT / "api" / "latest.json").get("items") or []
    entries = j(UPDATE_LOG, {"entries": []}).get("entries") or []
    days = {}
    for k in range(7):
        d = (now - timedelta(days=k)).strftime("%Y-%m-%d")
        days[d] = {"date": d, "added": 0, "updates": 0}
    for e in entries:
        d = e["at_label"][:10]
        if d in days:
            days[d]["added"] += int(e.get("added") or 0)
            days[d]["updates"] += 1
    newest, seen = [], set()
    for e in entries:
        for it in e.get("new") or []:
            u = it.get("url")
            if u and u not in seen:
                seen.add(u)
                newest.append(dict(it, added_at_label=e["at_label"]))
    if len(newest) < 20:
        rest = sorted((it for it in latest if not it.get("pinned") and it.get("url") not in seen),
                      key=lambda x: x.get("posted_at") or "", reverse=True)
        for it in rest[: 20 - len(newest)]:
            newest.append({"title": it.get("title"), "url": it.get("url"), "path": it.get("path"),
                           "category": it.get("category"), "added_at_label": it.get("posted_at")})
    c = meta.get("counts") or {}
    return {
        "last_update": meta.get("generated_at_label") or meta.get("updated_at_label"),
        "next_update": lbl(next_engine_a(now)),
        "update_frequency": "每小时",
        "totals": {"free_resources": c.get("deals", 0), "github_hot": c.get("github_hot", 0), "hot_topics": c.get("hot", 0),
                   "modules": c.get("modules") or {}},
        "recent_additions": {
            "last_7_days": sum(v["added"] for v in days.values()),
            "by_day": list(days.values()),
            "recent_updates": [{"at": e["at_label"], "added": e.get("added", 0)} for e in entries[:24]],
        },
        "newest_items": newest[:30],
    }


def render(st: dict) -> str:
    esc = B.esc
    t = st["totals"]
    days = st["recent_additions"]["by_day"]
    mx = max([d["added"] for d in days] + [1])
    bars = "".join(
        f'<div class="ud-bar"><i style="height:{max(4, int(100 * d["added"] / mx))}%"></i><b>{d["added"]}</b><span>{esc(d["date"][5:])}</span></div>'
        for d in reversed(days)
    )
    ups = "".join(
        f'<tr><td>{esc(u["at"])}</td><td>{"+" + str(u["added"]) + " 条" if u["added"] else "内容刷新"}</td></tr>'
        for u in st["recent_additions"]["recent_updates"][:12]
    ) or '<tr><td colspan="2">暂无记录</td></tr>'
    items = "".join(
        f'<li><a href="../{esc(it.get("path"))}">{esc(it.get("title"))}</a> <span class="badge">{esc(it.get("category") or "")}</span>'
        f' <a class="src" href="{esc(it.get("url"))}" target="_blank" rel="noopener nofollow">来源 ↗</a>'
        f'<div class="meta">{esc(it.get("added_at_label") or "")}</div></li>'
        for it in st["newest_items"] if it.get("title")
    )
    mods = t.get("modules") or {}
    pills = "".join(f'<div class="pill">{esc(title)} <b data-count="{mods.get(mid, 0)}">{mods.get(mid, 0)}</b></div>' for mid, title, *_ in B.MODULES)
    stats = (f'<div class="pill live">最近更新 <b>{esc((st.get("last_update") or "-")[:16])}</b></div>'
             f'<div class="pill">下次更新 <b>{esc(st["next_update"][:16])}</b></div>'
             f'<div class="pill">免费资源 <b data-count="{t["free_resources"]}">{t["free_resources"]}</b></div>'
             f'<div class="pill">近 7 天新增 <b data-count="{st["recent_additions"]["last_7_days"]}">{st["recent_additions"]["last_7_days"]}</b></div>')
    canonical = f"{B.CANONICAL}m/status.html"
    ki_items = B.load_known_issues()
    ki_open = sum(1 for it in ki_items if it["status"] != "已修复")
    ki_html = B.render_known_issues(ki_items, compact=False, prefix="../")
    return f"""{B.head_block(f"更新动态 · {B.SITE_NAME}", f"{B.SITE_NAME}更新动态：最近更新时间、下次更新时间、近 7 天新增的大模型免费资源与最新收录条目。", canonical)}
<body>
<div class="fx-aurora" aria-hidden="true"></div>
<div class="fx-grid" aria-hidden="true"></div>
<div class="fx-noise" aria-hidden="true"></div>
<div class="fx-scan" aria-hidden="true"></div>
<div class="fx-spot" aria-hidden="true"></div>
<canvas id="fx-particles" aria-hidden="true"></canvas>
{B.topnav("../")}
{B.mod_hero("UPDATES", "更新动态", "本站每小时自动收录新的大模型免费资源、GitHub 热门项目与 AI 热议。这里是最近的更新记录与最新收录。", stats, '<a href="../">首页</a> › 更新动态', "../vendor/", [("每小时", ""), ("新增", st["recent_additions"]["last_7_days"]), ("资源", t["free_resources"]), ("最新", "")])}
<div class="wrap">
  <section class="section"><div class="sec-head"><span class="sec-idx">01 / LAST 7 DAYS</span><h2>近 7 天新增</h2>
    <p class="sec-desc">每天新收录的免费资源条数。</p></div>
    <div class="panel-box"><div class="ud-chart">{bars}</div></div>
  </section>
  <section class="section"><div class="sec-head"><span class="sec-idx">02 / TOTALS</span><h2>收录总量</h2></div>
    <div class="stats">{pills}</div>
  </section>
  <section class="section"><div class="sec-head"><span class="sec-idx">03 / NEWEST</span><h2>最新收录</h2></div>
    <div class="panel-box"><ol class="ud-list">{items or "<li>暂无</li>"}</ol></div>
  </section>
  <section class="section" id="known-issues-section"><div class="sec-head"><span class="sec-idx">04 / ISSUES</span><h2>已知问题</h2>
    <p class="sec-desc">目前已知、会影响阅读或领取的问题（{ki_open} 条未关闭）。修复后会标成「已修复」。</p></div>
    <div class="panel-box">{ki_html or "<p>暂无已知问题。</p>"}</div>
  </section>
  <section class="section"><div class="sec-head"><span class="sec-idx">05 / RECENT</span><h2>最近更新记录</h2></div>
    <div class="panel-box" style="overflow:auto"><table class="api-table"><tr><th>时间</th><th>新增</th></tr>{ups}</table></div>
  </section>
  <p class="linkrow">数据接口：<a href="../api/status.json">api/status.json</a></p>
  {B.site_footer("../")}
</div>
<style>
.ud-chart{{display:flex;align-items:flex-end;gap:12px;height:180px;padding:10px 4px 0}}
.ud-bar{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;gap:6px}}
.ud-bar i{{display:block;width:100%;max-width:56px;border-radius:10px 10px 4px 4px;background:linear-gradient(180deg,var(--cyan),var(--violet));box-shadow:0 0 18px rgba(92,225,255,.35);animation:udgrow 1s ease-out both}}
.ud-bar b{{font-family:var(--mono);color:var(--cyan);font-size:.85rem}} .ud-bar span{{font-family:var(--mono);color:var(--muted);font-size:.75rem}}
@keyframes udgrow{{from{{transform:scaleY(0);transform-origin:bottom}}to{{transform:scaleY(1);transform-origin:bottom}}}}
.ud-list{{margin:0;padding-left:1.3rem;line-height:1.7}} .ud-list li{{margin:10px 0}} .ud-list .src{{font-size:.8rem;margin-left:6px}}
@media (prefers-reduced-motion:reduce){{.ud-bar i{{animation:none}}}}
</style>
<script>{B.SITE_JS}</script>
</body></html>"""


def main() -> int:
    now = datetime.now(TZ)
    write_marker(now)
    record_update(now)
    internal = build_status(now)
    INTERNAL.write_text(json.dumps(internal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pub = public_status(now)
    (ROOT / "api").mkdir(exist_ok=True)
    (ROOT / "m").mkdir(exist_ok=True)
    (ROOT / "api" / "status.json").write_text(json.dumps(pub, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "m" / "status.html").write_text(render(pub), encoding="utf-8")
    print("[status] wrote api/status.json + m/status.html (+ data/_internal_status.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
