#!/usr/bin/env python3
"""Build the static site (GitHub Pages): landing + module pages + item pages + archives + API.

v3: every piece of content goes through curate.py (relevance, dedupe, rewrite, facts, status),
so the hourly automated rebuild always reproduces the same curated output. Never hand-edit
generated files (index.html, item/, c/, m/, archives/, api/) — change this generator instead.
"""
from __future__ import annotations

import hashlib
import sys
import html
import json
import os
import re
import urllib.parse
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import curate

SITE = Path(__file__).resolve().parent
DATA = SITE / "data"
AUTO = DATA / "auto"
ARCHIVES = SITE / "archives"
ITEMS = SITE / "item"
CATS = SITE / "c"
MODS = SITE / "m"
CFG_PATH = SITE / "seo_config.json"
TZ = ZoneInfo("Asia/Shanghai")
REPO_URL = "https://github.com/aiym168/aiym168.github.io"
ISSUE_URL = REPO_URL + "/issues/new"

DEFAULT_CFG = {
    "site_name": "AI大模型免费资源导航",
    "canonical": "https://aiym168.github.io/",
    "baidu_site_verification": "",
    "baidu_push_site": "https://aiym168.github.io",
}

CATEGORIES = list(curate.CATEGORIES)

CAT_SLUG = {
    "大模型 API 免费额度": "damoxing-mianfei-api",
    "AI 产品会员/试用": "ai-huiyuan-shiyong",
    "AI 开发工具与编程助手": "ai-kaifa-gongju",
    "云服务/GPU/开发者资源": "mianfei-gpu-yunfuwu",
    "科技软件/App 限免": "keji-app-xianmian",
    "AI 课程/活动": "ai-kecheng-huodong",
    "其他科技": "qita-keji",
}

CAT_INTRO = {
    "大模型 API 免费额度": "大模型免费 API、免费 Token 与免费额度：Gemini、DeepSeek、Qwen、GLM 等平台的公开试用与免费层，附领取方式和限制。",
    "AI 产品会员/试用": "AI 产品的会员限免、免费试用与免费计划，覆盖写作、绘画、语音、视频与办公类工具。",
    "AI 开发工具与编程助手": "面向开发者的免费 AI 编程助手、Agent、MCP 服务器与开源 AI 工具。",
    "云服务/GPU/开发者资源": "免费 GPU、云算力、云电脑与开发者云资源，适合训练、推理与实验。",
    "科技软件/App 限免": "科技软件与 App 的限时免费、终身内购限免。",
    "AI 课程/活动": "免费的 AI 课程、讲座、电子书、认证与线上活动（含报名截止时间）。",
    "其他科技": "暂时无法归入其他模块、但与 AI / 科技相关的免费资源。",
}

LONGTAIL = "大模型免费API、免费GPT、Claude免费、DeepSeek免费额度、AI工具免费、免费GPU、GitHub热门项目、最新AI新闻"
KEYWORDS = (
    "AI大模型免费资源,大模型免费API,免费GPT,Claude免费,DeepSeek免费额度,"
    "AI工具免费,免费GPU,GitHub热门项目,AI开源项目推荐,最新AI新闻"
)

# (id, title, one-line description, href, kind, category)
MODULES = [
    ("damoxing-mianfei-api", "大模型 API 免费额度", "免费 Token、免费 API 与免费层", "c/damoxing-mianfei-api.html", "cat", "大模型 API 免费额度"),
    ("ai-huiyuan-shiyong", "AI 产品会员/试用", "会员限免、免费试用与免费计划", "c/ai-huiyuan-shiyong.html", "cat", "AI 产品会员/试用"),
    ("ai-kaifa-gongju", "AI 开发工具与编程助手", "编程助手、Agent、MCP 与开源工具", "c/ai-kaifa-gongju.html", "cat", "AI 开发工具与编程助手"),
    ("mianfei-gpu-yunfuwu", "免费 GPU / 云服务", "免费算力、云电脑与开发者云资源", "c/mianfei-gpu-yunfuwu.html", "cat", "云服务/GPU/开发者资源"),
    ("keji-app-xianmian", "科技软件 / App 限免", "App 限免与终身内购限免", "c/keji-app-xianmian.html", "cat", "科技软件/App 限免"),
    ("ai-kecheng-huodong", "AI 课程 / 活动", "免费课程、讲座、电子书与活动", "c/ai-kecheng-huodong.html", "cat", "AI 课程/活动"),
    ("qita-keji", "其他科技资源", "其他 AI / 科技相关免费资源", "c/qita-keji.html", "cat", "其他科技"),
    ("github-hot", "GitHub 新热门", "近期新建的 AI 开源项目", "m/github-hot.html", "github", None),
    ("hot-topics", "最近热议", "社区里的 AI 与科技热议", "m/hot-topics.html", "hot", None),
]
MOD_BY_CAT = {cat: mid for mid, _t, _d, _h, kind, cat in MODULES if kind == "cat"}
MOD_TITLE = {mid: t for mid, t, *_ in MODULES}

NAV_SHORT = {
    "damoxing-mianfei-api": "免费API", "ai-huiyuan-shiyong": "会员试用", "ai-kaifa-gongju": "开发工具",
    "mianfei-gpu-yunfuwu": "免费GPU", "keji-app-xianmian": "App限免", "ai-kecheng-huodong": "课程活动",
    "qita-keji": "其他", "github-hot": "GitHub热门", "hot-topics": "热议",
}

FACT_LABELS = {
    "requires_card": ("要不要绑卡", {"no": "免绑卡", "yes": "需绑卡", "partial": "部分需绑卡", "unknown": "未注明"}),
    "requires_realname": ("实名/手机号", {"no": "无需实名", "yes": "需实名或手机号", "partial": "部分需实名", "unknown": "未注明"}),
    "china_accessible": ("国内能否直连", {"yes": "国内可直连", "no": "需海外网络", "unknown": "未注明"}),
    "type": ("免费类型", {"permanent": "永久免费", "trial": "试用", "quota": "限额", "unknown": "未注明"}),
    "expiry_kind": ("额度有效期", {k: v for k, v in curate.EXPIRY_LABEL.items()}),
    "status": ("状态", {"available": "可领（已核实）", "expiring": "即将过期", "unverified": "未核实"}),
}
FACT_SHORT = {  # compact badge text on cards
    "requires_card": {"no": "免绑卡", "yes": "需绑卡", "partial": "部分需绑卡", "unknown": "绑卡：未注明"},
    "requires_realname": {"no": "无需实名", "yes": "需实名/手机号", "partial": "部分需实名", "unknown": "实名：未注明"},
    "china_accessible": {"yes": "国内可直连", "no": "需海外网络", "unknown": "直连：未注明"},
    "type": {"permanent": "永久免费", "trial": "试用", "quota": "限额", "unknown": "类型：未注明"},
}
STATUS_LABEL = dict(curate.STATUS_LABEL)
STATUS_CLASS = {"available": "ok", "expiring": "warn", "expired": "bad", "unverified": "muted", "archived": "muted"}


def _load_asset(name: str) -> str:
    try:
        return (SITE / name).read_text(encoding="utf-8")
    except Exception:
        return ""


CSS = _load_asset("fx.css")
FX_JS = _load_asset("fx.js")
INTERACT_JS = ""  # v3: cursor trail / scramble / brain-highlight removed
SITE_JS = _load_asset("vendor/site.js") + "\n" + FX_JS


def load_cfg() -> dict:
    cfg = dict(DEFAULT_CFG)
    if CFG_PATH.exists():
        try:
            cfg.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[warn] seo_config: {e}")
    env_v = (os.environ.get("VERIFY_BAIDU") or os.environ.get("BAIDU_SITE_VERIFICATION") or "").strip()
    if env_v:
        cfg["baidu_site_verification"] = env_v
    cfg["canonical"] = (cfg.get("canonical") or DEFAULT_CFG["canonical"]).rstrip("/") + "/"
    legacy = ("netlify.app", "aidamoxing-mianfei", "aiyangmao", "9499758-wq.github.io", "/x-yangmao")
    if any(h in cfg["canonical"] for h in legacy):
        cfg["canonical"] = "https://aiym168.github.io/"
        cfg["baidu_push_site"] = "https://aiym168.github.io"
    return cfg


CFG = load_cfg()
SITE_NAME = CFG["site_name"]
CANONICAL = CFG["canonical"]
META_DESC = (
    "免费AI资源每小时更新：大模型免费API、免费Token、免费GPU、AI工具免费额度和AI羊毛，"
    "逐条标注是否绑卡、实名、国内能否直连。"
)


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"skip {path}: {e}")
        return None



def load_known_issues() -> list[dict]:
    """Public known issues from data/known_issues.json (user-facing only)."""
    raw = load_json(DATA / "known_issues.json") or {}
    items = raw.get("items") if isinstance(raw, dict) else raw
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        if not title:
            continue
        status = (it.get("status") or "处理中").strip()
        if status not in ("处理中", "已修复", "计划中"):
            status = "处理中"
        out.append({
            "id": (it.get("id") or title)[:48],
            "title": title,
            "detail": (it.get("detail") or "").strip(),
            "status": status,
            "date": (it.get("date") or "").strip(),
        })
    return out


def render_known_issues(items: list[dict] | None = None, *, compact: bool = False, prefix: str = "./") -> str:
    """HTML for known issues. compact=True = homepage teaser; False = full list on status page."""
    items = items if items is not None else load_known_issues()
    if not items:
        return ""
    st_cls = {"处理中": "open", "计划中": "plan", "已修复": "done"}
    open_n = sum(1 for it in items if it["status"] != "已修复")
    if compact:
        preview = items[:3]
        lis = "".join(
            f'<li><span class="ki-st ki-{st_cls.get(it["status"], "open")}">{esc(it["status"])}</span>'
            f'<span class="ki-t">{esc(it["title"])}</span></li>'
            for it in preview
        )
        more = f'<a class="ki-more" href="{prefix}m/status.html#known-issues">查看全部 {len(items)} 条已知问题 →</a>'
        return (
            f'<div class="known-issues compact" id="known-issues-teaser">'
            f'<div class="ki-head"><strong>已知问题</strong>'
            f'<span class="ki-count">{open_n} 条处理中 / 计划中</span></div>'
            f'<ul class="ki-list">{lis}</ul>{more}</div>'
        )
    rows = []
    for it in items:
        date_html = f'<time>{esc(it["date"])}</time>' if it.get("date") else ""
        detail_html = f'<p class="ki-d">{esc(it["detail"])}</p>' if it.get("detail") else ""
        rows.append(
            f'<li id="ki-{esc(it["id"])}">'
            f'<div class="ki-row"><span class="ki-st ki-{st_cls.get(it["status"], "open")}">{esc(it["status"])}</span>'
            f'<strong class="ki-t">{esc(it["title"])}</strong>{date_html}</div>'
            f'{detail_html}</li>'
        )
    lis = "".join(rows)
    return (
        f'<div class="known-issues" id="known-issues">'
        f'<ul class="ki-list">{lis}</ul>'
        f'<p class="ki-note">以上为目前已知、会影响阅读或领取的问题；修复后会改成「已修复」。发现新问题可在'
        f'<a href="{prefix}m/board.html">留言板</a>告诉我们。</p></div>'
    )


def ym_label(date_str: str) -> str:
    m = re.match(r"(20\d{2})-(\d{2})", date_str or "")
    if m:
        return f"{m.group(1)}年{int(m.group(2))}月最新"
    now = datetime.now(TZ)
    return f"{now.year}年{now.month}月最新"


def item_slug(item: dict) -> str:
    key = item.get("id") or item.get("url") or item.get("title") or ""
    h = hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:10]
    src = item.get("slug_hint") or item.get("title") or ""
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", src).strip("-").lower()
    ascii_part = re.sub(r"-{2,}", "-", ascii_part)[:36].strip("-")
    cat = CAT_SLUG.get(item.get("category") or "", "item")
    return f"{ascii_part}-{h}" if len(ascii_part) >= 4 else f"{cat}-{h}"


def fmt_dt(iso_s: str | None, with_time: bool = True) -> str:
    d = curate.parse_dt(iso_s) if iso_s else None
    if not d:
        return "未知"
    d = d.astimezone(TZ)
    return d.strftime("%Y-%m-%d %H:%M") if with_time else d.strftime("%Y-%m-%d")


def json_ld(obj) -> str:
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "</script>"


def vendor_versions() -> dict:
    """Content-hashed URLs for every vendor JS module, used for cache-busting (import map + script src)."""
    out = {}
    vd = SITE / "vendor"
    for p in sorted(vd.rglob("*.js")):
        rel = "/" + p.relative_to(SITE).as_posix()
        out[rel] = rel + "?v=" + hashlib.sha1(p.read_bytes()).hexdigest()[:10]
    return out


VENDOR_V = vendor_versions()


def vurl(prefix: str, name: str) -> str:
    """Versioned relative URL for vendor/<name>."""
    v = VENDOR_V.get("/vendor/" + name, "")
    return prefix + "vendor/" + name + (v[v.index("?"):] if "?" in v else "")


def import_map() -> str:
    return '<script type="importmap">' + json.dumps({"imports": VENDOR_V}, separators=(",", ":")) + "</script>"


REDUCE_BOOT = ("<script>try{if(localStorage.getItem('ai168-reduce')==='1')document.documentElement.classList.add('reduce-motion')}"
               "catch(e){}</script>")


def head_block(title, description, canonical, og_title=None, pubdate=None, extra_ld=None, og_image=None):
    og_title = og_title or title
    verify = (CFG.get("baidu_site_verification") or "").strip()
    verify_meta = (
        f'<meta name="baidu-site-verification" content="{esc(verify)}" />'
        if verify else "<!-- VERIFY_BAIDU / seo_config.baidu_site_verification -->"
    )
    pub_meta = ""
    if pubdate:
        pub_meta = (f'<meta property="og:article:published_time" content="{esc(pubdate)}" />\n'
                    f'<meta name="pubdate" content="{esc(pubdate)}" />')
    img = (og_image or "").strip() or f"{CANONICAL}assets/og-card.jpg"
    if img.startswith("/"):
        img = CANONICAL.rstrip("/") + img
    elif not img.startswith("http"):
        img = CANONICAL + img.lstrip("./")
    ld_html = "\n".join(json_ld(x) for x in (extra_ld or []))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5" />
<meta name="color-scheme" content="dark" />
<meta name="theme-color" content="#02040a" />
{REDUCE_BOOT}
{import_map()}
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0' stop-color='%235ce1ff'/%3E%3Cstop offset='1' stop-color='%23a78bfa'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='32' height='32' rx='8' fill='%2302040a'/%3E%3Crect x='5' y='5' width='22' height='22' rx='6' fill='none' stroke='url(%23g)' stroke-width='3'/%3E%3Ccircle cx='16' cy='16' r='4' fill='%235ef0c0'/%3E%3C/svg%3E" />
<meta http-equiv="X-UA-Compatible" content="IE=edge" />
<meta name="renderer" content="webkit" />
<meta name="force-rendering" content="webkit" />
<meta name="applicable-device" content="pc,mobile" />
<meta name="MobileOptimized" content="width" />
<meta name="HandheldFriendly" content="true" />
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}" />
<meta name="keywords" content="{esc(KEYWORDS)}" />
<meta name="robots" content="index,follow" />
<meta name="author" content="{esc(SITE_NAME)}" />
{verify_meta}
<link rel="canonical" href="{esc(canonical)}" />
<meta property="og:type" content="website" />
<meta property="og:locale" content="zh_CN" />
<meta property="og:site_name" content="{esc(SITE_NAME)}" />
<meta property="og:title" content="{esc(og_title)}" />
<meta property="og:description" content="{esc(description)}" />
<meta property="og:url" content="{esc(canonical)}" />
<meta property="og:image" content="{esc(img)}" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{esc(og_title)}" />
<meta name="twitter:description" content="{esc(description)}" />
<meta name="twitter:image" content="{esc(img)}" />
{pub_meta}
<style>
{CSS}
</style>
{ld_html}
</head>
"""


ICONS = {
    "damoxing-mianfei-api": '<path d="M12 2a4 4 0 0 1 4 4v1a3 3 0 0 1 3 3v1a3 3 0 0 1-1 5.2V17a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4v-.8A3 3 0 0 1 5 11v-1a3 3 0 0 1 3-3V6a4 4 0 0 1 4-4z"/><path d="M12 6v14M9 10h6M9 14h6"/>',
    "ai-huiyuan-shiyong": '<path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8L3.5 9.2l5.9-.9z"/>',
    "ai-kaifa-gongju": '<path d="M8 8l-5 4 5 4M16 8l5 4-5 4M14 4l-4 16"/>',
    "mianfei-gpu-yunfuwu": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "keji-app-xianmian": '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 18h4M9 9l2 2 4-4"/>',
    "ai-kecheng-huodong": '<path d="M2 8l10-5 10 5-10 5z"/><path d="M6 10v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5M22 8v6"/>',
    "qita-keji": '<circle cx="12" cy="12" r="9"/><path d="M8 12h.01M12 12h.01M16 12h.01"/>',
    "github-hot": '<path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/>',
    "hot-topics": '<path d="M12 22c4.4 0 7-2.9 7-7 0-4-3-6-4-10-2 2-2.5 4-2.5 4S10 6 9 3C7 6 5 9 5 15c0 4.1 2.6 7 7 7z"/><path d="M12 22c-1.7 0-3-1.3-3-3.2 0-2 1.5-3 3-5 1.5 2 3 3 3 5 0 1.9-1.3 3.2-3 3.2z"/>',
}


def icon_svg(mid: str) -> str:
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{ICONS.get(mid, ICONS["qita-keji"])}</svg>')


def brain_block(vendor_prefix: str = "vendor/", tags=None, nodes: int = 4200) -> str:
    """Decorative WebGL brain (no data overlays — v3 removed the misleading floating count tags)."""
    return f"""
<div class="brain-stage" aria-hidden="true">
  <span class="ring r3"></span><span class="ring r1"></span><span class="ring r2"></span>
  <span class="hud-corner tl"></span><span class="hud-corner tr"></span><span class="hud-corner bl"></span><span class="hud-corner br"></span>
  <div id="brain-hero" data-vendor="{esc(vendor_prefix)}" data-nodes="{nodes}"></div>
</div>
"""


def brain_loader_script(vendor_prefix: str = "vendor/") -> str:
    _v = VENDOR_V.get("/vendor/brain-loader.js", "")
    return f'<script src="{esc(vendor_prefix)}brain-loader.js{esc(_v[_v.index("?"):] if "?" in _v else "")}" defer></script>'


def topnav(prefix="./"):
    links = "".join(
        f'<a href="{prefix}{esc(href)}" title="{esc(title)}">{esc(NAV_SHORT.get(mid, title))}</a>'
        for mid, title, _, href, _, _ in MODULES
    )
    links = (f'<a class="nav-hot" href="{prefix}deals/index.html" title="全球优惠情报中心">优惠情报</a>'
             f'<a href="{prefix}deals/api-prices.html" title="大模型 API 最低价榜">API最低价</a>'
             f'<a href="{prefix}radio/index.html" title="AI 羊毛电台 · 每天三分钟听完">电台</a>'
             f'<a class="nav-wan" href="https://wan.is-my.app/" title="玩点啥：今日热榜、你画我猜、打字背单词、在线工具">玩点啥</a>'
             f'<a href="https://wan.is-my.app/gongju/" title="免费在线工具大全：图片压缩、PDF合并、二维码、房贷个税计算器">免费工具</a>') + links
    links += f'<a href="{prefix}m/board.html" title="匿名留言板 · 星际信号站">留言板</a>'
    links += f'<a href="{prefix}m/status.html" title="更新动态">更新动态</a>'
    return f"""
<header class="topnav">
  <a class="brand-mini" href="{prefix}"><span class="mark"></span><span class="txt">{esc(SITE_NAME)}</span></a>
  <nav class="navlinks" id="navlinks" aria-label="模块导航">{links}</nav>
  <div class="nav-more" hidden>
    <button type="button" class="nav-more-btn" aria-expanded="false" aria-controls="nav-more-menu">更多 <i aria-hidden="true">▾</i></button>
    <div class="nav-more-menu" id="nav-more-menu" hidden role="menu"></div>
  </div>
  <div class="nav-tools">
    <a class="nav-search" href="{prefix}#search" data-search-open aria-label="搜索免费资源"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg><span>搜索</span><kbd>Ctrl K</kbd></a>
    <button type="button" class="reduce-btn" data-reduce-toggle aria-pressed="false" title="关闭背景与大脑动画（会记住你的选择）">减少动态 <b>关</b></button>
    <button type="button" class="nav-toggle" aria-controls="navlinks" aria-expanded="false" aria-label="打开菜单"><span></span><span></span><span></span></button>
  </div>
</header>"""


def site_footer(prefix="./", extra="") -> str:
    return f"""<footer>
  <div><span class="foot-brand">{esc(SITE_NAME)}</span>{(" · " + esc(extra)) if extra else ""}<br/>每小时自动更新 · 信息来自公开网页，参与前请以官网为准</div>
  <div class="foot-links"><a href="{prefix}deals/index.html">全球优惠情报</a> · <a href="{prefix}deals/api-prices.html">API 最低价榜</a> · <a href="{prefix}radio/index.html">AI 羊毛电台</a> · <a href="{prefix}live/">AI 羊毛信号站（直播）</a> · <a href="{prefix}m/api.html">CLI / API</a> · <a href="{prefix}m/status.html">更新动态</a> · <a href="{prefix}archives/index.html">已归档</a> · <a href="{prefix}m/board.html">留言板</a> · <a href="{prefix}m/octopus.html">机械章鱼 3D</a> · <a href="{prefix}feed.xml">RSS</a> · <a href="{prefix}feed.atom">Atom</a> · <a href="{prefix}digest/today.txt">今日速递</a> · <a href="{prefix}sitemap.xml">网站地图</a> · <a href="{REPO_URL}" rel="noopener">GitHub 仓库</a></div>
  <div class="foot-links">免费在线工具：<a href="https://wan.is-my.app/gongju/">免费在线工具大全</a> · <a href="https://wan.is-my.app/image-compress/">图片压缩</a> · <a href="https://wan.is-my.app/pdf-merge/">PDF 合并</a> · <a href="https://wan.is-my.app/id-photo/">证件照换底色</a> · <a href="https://wan.is-my.app/qrcode/">二维码生成器</a> · <a href="https://wan.is-my.app/fangdai/">房贷计算器</a> · <a href="https://wan.is-my.app/geshui/">个税计算器</a> · <a href="https://wan.is-my.app/fanjian/">繁简转换</a> · <a href="https://wan.is-my.app/json/">JSON 格式化</a> · <a href="https://hot.is-my.app/">今日热榜</a> · <button type="button" class="reduce-btn link" data-reduce-toggle aria-pressed="false">减少动态 <b>关</b></button></div>
</footer>"""


EYEBROW_ZH = {"UPDATES": "更新动态", "MODULE": "模块", "GITHUB": "GitHub 新热门", "PULSE": "最近热议", "ARCHIVE": "归档", "DETAIL": "详情"}


def mod_hero(eyebrow: str, title: str, lead: str, stats: str, crumbs: str, vendor_prefix: str, tags=None) -> str:
    """Compact page hero (also used by status.py). Static — no clock, no countdown."""
    eb = EYEBROW_ZH.get(eyebrow, eyebrow)
    return f"""<header class="hero-xl compact hero-brain">
  <div class="hero-xl-inner">
    <div class="hero-copy">
      <div class="crumbs">{crumbs}</div>
      <div class="eyebrow"><i class="live-dot"></i> {esc(eb)}</div>
      <h1 class="hero-title"><span class="kl">{esc(title)}</span></h1>
      <p class="lead">{esc(lead)}</p>
      <div class="stats">{stats}</div>
    </div>
    {brain_block(vendor_prefix, None, 2600)}
  </div>
</header>
{brain_loader_script(vendor_prefix)}"""


def page_shell_start(prefix: str, body_class: str = "") -> str:
    return f'<body class="{body_class}" data-base="{esc(prefix)}">\n{topnav(prefix)}'


def page_scripts() -> str:
    return f"<script>{SITE_JS}</script>"


# ============================================================ data
def load_pinned(now: datetime) -> list[dict]:
    """Pinned items from data/pinned.json (editorial, never touched by fetchers) + data/item_facts.json overrides."""
    d = load_json(DATA / "pinned.json") if (DATA / "pinned.json").exists() else None
    overrides = ((load_json(DATA / "item_facts.json") or {}) if (DATA / "item_facts.json").exists() else {}).get("items") or {}
    out = []
    for it in (d or {}).get("items") or []:
        if not (it.get("title") and it.get("url")):
            continue
        text = " ".join([it.get("title") or "", it.get("summary") or ""] + list(it.get("features") or []))
        facts = curate.infer_facts(text)
        rec = {
            "id": it.get("id") or "pinned",
            "title": it.get("title"),
            "summary": it.get("summary") or "",
            "url": it.get("url"),
            "start_url": it.get("start_url") or it.get("url"),
            "source": it.get("source") or curate.domain(it.get("url")),
            "source_domain": curate.domain(it.get("url")),
            "source_name": it.get("source") or "",
            "author": it.get("author") or "",
            "category": it.get("category") if it.get("category") in CATEGORIES else "其他科技",
            "how": it.get("how") or "",
            "links": [],
            "features": it.get("features") or [],
            "reason": it.get("reason") or "",
            "badge": it.get("badge") or "置顶推荐",
            "published_at": curate.iso(curate.parse_dt(it.get("posted_at"))),
            "fetched_at": curate.iso(curate.parse_dt(it.get("posted_at"))) or curate.iso(now),
            "verified_at": it.get("verified_at"),
            "verified_source": it.get("verified_source") or [],
            "expires_at": it.get("expires_at"),
            "pinned": True,
            "_kind": "pinned",
            **facts,
        }
        rec["time_limited"] = "yes" if rec["expires_at"] else "unknown"
        ov = overrides.get(rec["id"]) or overrides.get(curate.norm_url(rec["url"]))
        if ov:
            rec.update({k: v for k, v in ov.items() if not k.startswith("_")})
        rec["expiry_kind"] = curate.expiry_kind(text, rec.get("expires_at"))
        if ov and ov.get("expiry_kind"):
            rec["expiry_kind"] = ov["expiry_kind"]
        curate.set_status(rec, now)
        out.append(rec)
    return out


def finalize(it: dict) -> dict:
    it["module"] = MOD_BY_CAT.get(it.get("category"), "qita-keji")
    it["module_name"] = MOD_TITLE.get(it["module"], "")
    it["status_label"] = STATUS_LABEL.get(it.get("status"), "未核实")
    it["_slug"] = item_slug(it)
    it["_path"] = f"item/{it['_slug']}.html"
    it["favicon"] = curate.favicon(it.get("source_domain") or "")
    return it


def sort_key_default(it: dict):
    """Default order: pinned → closing soon → editorial/offer posts → open-source repos; newest first within a group."""
    grp = 0 if it.get("pinned") else 1 if it.get("status") == "expiring" else 3 if it.get("_kind") == "github" else 2
    ts = (curate.parse_dt(it.get("published_at") or it.get("fetched_at")) or datetime(2000, 1, 1, tzinfo=TZ)).timestamp()
    return (grp, -ts)


LINKCHECK = {"counts": {}, "checked_at": None, "hidden": [], "total": 0, "unreliable_run": False}


def load_linkcheck() -> dict:
    """Results of linkcheck.py (run just before this build). Missing file = nothing checked yet."""
    d = load_json(AUTO / "linkcheck.json") if (AUTO / "linkcheck.json").exists() else None
    return d if isinstance(d, dict) else {}


def collect(now: datetime):
    pins = load_pinned(now)
    res = curate.curate(pins)
    items = res["items"]
    for it in pins + items:
        finalize(it)
    lc = load_linkcheck()
    lc_items = lc.get("items") or {}
    hidden = []
    for it in pins + items:
        it["_lc"] = lc_items.get(it.get("id")) or {}
        if it["_lc"].get("verdict") == "gone" and not it.get("pinned") and it["status"] not in ("archived", "expired"):
            it["status"] = "archived"
            it["status_label"] = STATUS_LABEL.get("archived", "已归档")
            it["archive_reason"] = "链接失效：连续两次检查都打不开，已自动下架"
            hidden.append({"id": it.get("id"), "title": it.get("title"), "url": it["_lc"].get("url"), "code": it["_lc"].get("code")})
    LINKCHECK.update({"counts": lc.get("counts") or {}, "checked_at": lc.get("checked_at"), "hidden": hidden,
                      "total": lc.get("total") or 0, "unreliable_run": bool(lc.get("unreliable_run"))})
    active = [it for it in pins + items if it["status"] not in ("archived", "expired")]
    active.sort(key=sort_key_default)
    archived = [it for it in items if it["status"] in ("archived", "expired")]
    archived.sort(key=lambda i: -(curate.parse_dt(i.get("published_at")) or datetime(2000, 1, 1, tzinfo=TZ)).timestamp())
    gh_raw = (load_json(AUTO / "github_hot.json") or {}).get("items") or [] if (AUTO / "github_hot.json").exists() else []
    hot_raw = (load_json(AUTO / "hot_topics.json") or {}).get("items") or [] if (AUTO / "hot_topics.json").exists() else []
    repos, rep_g = curate.curate_side(gh_raw, "github")
    topics, rep_h = curate.curate_side(hot_raw, "hot")
    for r in repos + topics:
        r["favicon"] = curate.favicon(r.get("source_domain") or "")
    report = res["report"]
    report["side"] = {"github_hot": dict(rep_g), "hot_topics": dict(rep_h)}
    report["linkcheck"] = {"counts": LINKCHECK["counts"], "hidden": len(hidden), "checked_at": LINKCHECK["checked_at"]}
    curate.save(AUTO / "curation_report.json", report)
    return active, archived, repos, topics, res["days"], report


# ============================================================ cards
def issue_link(it: dict, kind: str = "报错") -> str:
    title = f"[{kind}] {it.get('title', '')[:60]}"
    body = (f"条目：{it.get('title', '')}\n站内页面：{CANONICAL}{it.get('_path', '')}\n来源链接：{it.get('url', '')}\n"
            f"条目 ID：{it.get('id', '')}\n\n问题类型（保留一项）：已过期 / 链接失效 / 信息有误 / 不是免费资源 / 其他\n说明：\n")
    return ISSUE_URL + "?" + urllib.parse.urlencode({"title": title, "body": body, "labels": "报错"})


def src_avatar(it: dict, prefix: str) -> str:
    dom = it.get("source_domain") or ""
    letter = (re.sub(r"^(www\.)", "", dom)[:1] or "?").upper()
    if it.get("favicon"):
        return f'<span class="src-ico"><img src="{prefix}{esc(it["favicon"])}" alt="" width="18" height="18" loading="lazy" /></span>'
    return f'<span class="src-ico letter" aria-hidden="true">{esc(letter)}</span>'


def fact_badges(it: dict) -> str:
    out = []
    for k in ("requires_card", "requires_realname", "china_accessible", "type"):
        v = it.get(k) or "unknown"
        cls = "fact unk" if v == "unknown" else f"fact v-{v}"
        out.append(f'<span class="{cls}" title="{esc(FACT_LABELS[k][0])}">{esc(FACT_SHORT[k].get(v, v))}</span>')
    ek = it.get("expiry_kind") or "unknown"
    if it.get("expires_at"):
        out.append(f'<span class="fact v-deadline" title="截止时间">截止 {esc(fmt_dt(it["expires_at"], False))}</span>')
    elif ek != "unknown":
        out.append(f'<span class="fact" title="额度有效期">{esc(curate.EXPIRY_LABEL[ek])}</span>')
    else:
        out.append('<span class="fact unk" title="额度有效期">有效期：未注明</span>')
    return "".join(out)


def updated_at(it: dict) -> str | None:
    """Latest moment the listing was refreshed: editor check, crawl, or publication."""
    c = [x for x in (it.get("verified_at"), it.get("fetched_at"), it.get("published_at")) if x]
    c = [(curate.parse_dt(x), x) for x in c]
    c = [x for x in c if x[0]]
    return max(c)[1] if c else None


def link_state(it: dict) -> tuple[str, str]:
    """-> (css class, label) for the automatic link check."""
    lc = it.get("_lc") or {}
    v = lc.get("verdict")
    if v == "ok":
        return "ok", f'链接已验证 {fmt_dt(lc.get("checked_at"))}'
    if v == "recheck":
        return "warn", "链接待复查（上次没打开）"
    if v == "gone":
        return "bad", "链接失效"
    if lc.get("checked_at"):
        return "", f'链接检查 {fmt_dt(lc.get("checked_at"))}：对方限制访问，未能确认'
    return "", "链接尚未检查"


def trust_line(it: dict) -> str:
    ver = f'已核实 {fmt_dt(it["verified_at"], False)}' if it.get("verified_at") else "未核实"
    pub = fmt_dt(it.get("published_at"), False) if it.get("published_at") else "未知"
    up = updated_at(it)
    lcls, ltxt = link_state(it)
    return (f'<span class="upd">更新于 {esc(fmt_dt(up)) if up else "未知"}</span>'
            f'<span>来源 {esc(it.get("source") or "未知")}</span><span>发布 {esc(pub)}</span>'
            f'<span>收录 {esc(fmt_dt(it.get("fetched_at")))}</span><span class="{"ok" if it.get("verified_at") else ""}">{esc(ver)}</span>'
            f'<span class="lc {lcls}">{esc(ltxt)}</span>')


SHARE_ROW = ('<div class="share-row" aria-label="分享">'
             '<span class="share-lab">分享</span>'
             '<button type="button" data-share="x">X</button>'
             '<button type="button" data-share="wx">复制微信文案</button>'
             '<button type="button" data-share="xhs">复制小红书文案</button>'
             '<button type="button" data-share="link">复制链接</button></div>')


def card_text(it: dict) -> str:
    bits = [it.get("title"), it.get("summary"), it.get("how"), it.get("source"), it.get("module_name"), it.get("category")]
    for k in ("requires_card", "requires_realname", "china_accessible", "type"):
        bits.append(FACT_SHORT[k].get(it.get(k) or "unknown"))
    bits.append(curate.EXPIRY_LABEL.get(it.get("expiry_kind") or "unknown"))
    bits.append(it.get("status_label"))
    return " ".join(str(b) for b in bits if b)


def _load_aff() -> dict:
    """affiliate.json: optional referral links / invite codes. Empty = plain links everywhere (default)."""
    try:
        return json.loads((Path(__file__).resolve().parent / "affiliate.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


AFF = _load_aff()


def aff_link(it: dict):
    """Returns (url, rel, invite_code). Matches by item id first, then by the link's domain."""
    go = it.get("start_url") or it.get("url") or ""
    rel = "noopener noreferrer"
    if not AFF.get("enabled"):
        return go, rel, ""
    from urllib.parse import urlparse
    host = (urlparse(go).hostname or "").lower()
    e = (AFF.get("by_id") or {}).get(str(it.get("id"))) or next(
        (v for k, v in (AFF.get("by_domain") or {}).items() if host == k or host.endswith("." + k)), None)
    if not e:
        return go, rel, ""
    return (e.get("url") or go), ("sponsored nofollow noopener noreferrer" if e.get("url") else rel), (e.get("code") or "")


def aff_note(code: str) -> str:
    return f' <span class="aff-code" title="填写邀请码通常双方都有额外奖励">邀请码 <b>{esc(code)}</b></span>' if code else ""


def card_deal(it: dict, prefix: str = "") -> str:
    st = it.get("status") or "unverified"
    path = prefix + it["_path"]
    pin = it.get("pinned")
    badge = f'<span class="pin-badge">📌 置顶 · 编辑推荐</span>' if pin else ""
    reason = ""
    if pin:
        reason = (f'<p class="pin-reason"><b>推荐理由：</b>{esc(it.get("reason") or "")}'
                  f' <span class="pin-note">非广告，未收费</span></p>')
    how = f'<div class="how"><strong>怎么领：</strong><span data-s-how>{esc(it["how"])}</span></div>' if it.get("how") else ""
    attrs = " ".join(
        f'data-{k}="{esc(it.get(k) or "unknown")}"'
        for k in ("module", "requires_card", "requires_realname", "china_accessible", "type", "expiry_kind", "status")
    )
    go, go_rel, go_code = aff_link(it)
    return f"""
<article class="card{' pin-card' if pin else ''}" id="i-{esc(it['_slug'])}" data-id="{esc(it['id'])}" data-share-url="{esc(CANONICAL + it['_path'])}" {attrs} data-pub="{esc(it.get('published_at') or '')}" data-exp="{esc(it.get('expires_at') or '')}" data-text="{esc(card_text(it))}">
  <div class="card-top">{src_avatar(it, prefix)}<span class="src-name">{esc(it.get('source') or '')}{(' · @' + esc(it['author'])) if it.get('author') and it.get('source') == 'X' else ''}</span>{badge}<span class="st st-{STATUS_CLASS.get(st, 'muted')}" data-s-st>{esc(STATUS_LABEL.get(st, '未核实'))}</span></div>
  <h3 class="title"><a href="{esc(path)}" data-s-title>{esc(it['title'])}</a></h3>
  {reason}
  <p class="summary" data-s-sum>{esc(it.get('summary') or '')}</p>
  <div class="facts">{fact_badges(it)}</div>
  {how}
  <div class="trust">{trust_line(it)}</div>
  <div class="linkrow"><a href="{esc(path)}">详情</a><a href="{esc(go)}" target="_blank" rel="{go_rel}">{'官网' if pin else '原文'} ↗</a>{aff_note(go_code)}<a class="report" href="{esc(issue_link(it))}" target="_blank" rel="noopener">报错 / 已过期</a><span class="mod-tag" data-s-mod>{esc(it.get('module_name') or '')}</span></div>
  {SHARE_ROW}
</article>"""


def card_repo(it: dict, prefix: str = "") -> str:
    stars = it.get("stars")
    meta = " · ".join(x for x in [f"⭐ {stars}" if stars else "", it.get("language") or "", ("创建于 " + fmt_dt(it.get("created_at"), False)) if it.get("created_at") else ""] if x)
    return f"""
<article class="card" data-id="{esc(it.get('id'))}" data-text="{esc((it.get('title') or '') + ' ' + (it.get('summary') or '') + ' ' + (it.get('name') or ''))}">
  <div class="card-top">{src_avatar(it, prefix)}<span class="src-name">GitHub · {esc(it.get('name') or '')}</span></div>
  <h3 class="title"><a href="{esc(it.get('url'))}" target="_blank" rel="noopener noreferrer">{esc(it.get('title'))}</a></h3>
  <p class="summary">{esc(it.get('summary') or '')}</p>
  <div class="trust"><span>{esc(meta)}</span></div>
</article>"""


def card_hot(it: dict, prefix: str = "") -> str:
    return f"""
<article class="card" data-id="{esc(it.get('id'))}" data-text="{esc((it.get('title') or '') + ' ' + (it.get('summary') or ''))}">
  <div class="card-top">{src_avatar(it, prefix)}<span class="src-name">{esc(it.get('source') or '')}</span></div>
  <h3 class="title"><a href="{esc(it.get('url'))}" target="_blank" rel="noopener noreferrer">{esc(it.get('title'))}</a></h3>
  {f'<p class="summary">{esc(it["summary"])}</p>' if it.get('summary') else ''}
</article>"""


# ============================================================ filters UI
def filter_panel(items: list[dict], with_module: bool, placeholder: str) -> str:
    """Compact filters: search + 模块 chips always visible; other facets behind a remembered “更多筛选” toggle."""
    def chips_for(k):
        cnt = Counter(it.get(k) or "unknown" for it in items)
        if k == "module":
            opts = [(mid, NAV_SHORT.get(mid, t)) for mid, t, _d, _h, kind, _c in MODULES if kind == "cat"]
        else:
            opts = list(FACT_LABELS[k][1].items())
        return "".join(
            f'<button type="button" class="chip" data-f="{k}" data-v="{esc(v)}" aria-pressed="false">{esc(n)} <i>{cnt.get(v, 0)}</i></button>'
            for v, n in opts if cnt.get(v, 0) or v == "unknown")
    more_keys = ["requires_card", "requires_realname", "china_accessible", "type", "expiry_kind", "status"]
    more = "".join(
        f'<div class="fgroup"><span class="flabel">{esc(FACT_LABELS[k][0])}</span><div class="chips">{chips_for(k)}</div></div>'
        for k in more_keys)
    module_row = (f'<div class="fgroup fmod"><span class="flabel">模块</span><div class="chips">{chips_for("module")}</div></div>'
                  if with_module else "")
    return f"""
<div class="filters compact" data-filter-root>
  <form class="searchbar" role="search" action="" method="get" onsubmit="return false">
    <label class="sr-only" for="q">搜索</label>
    <input id="q" name="q" type="search" placeholder="{esc(placeholder)}" autocomplete="off" />
    <button type="submit" class="btn primary">搜索</button>
  </form>
  <div class="fgroups">{module_row}
    <div class="fmore" id="f-more-panel" hidden>{more}</div>
  </div>
  <div class="fbar">
    <button type="button" class="fmore-btn" id="f-more-btn" aria-expanded="false" aria-controls="f-more-panel">更多筛选 <span class="fmore-hint">绑卡 · 实名 · 直连 · 类型 · 有效期 · 状态</span><b class="fmore-n hidden" id="f-more-n"></b><i aria-hidden="true">▾</i></button>
    <span id="f-count" class="f-count">共 {len(items)} 条</span>
    <label class="sort">排序 <select id="f-sort"><option value="default">默认（置顶 + 最新）</option><option value="pub">按发布时间</option><option value="exp">按截止日期</option></select></label>
    <button type="button" id="f-clear" class="btn sm hidden">清除筛选</button></div>
  <noscript><p class="note">未启用 JavaScript：下方列出全部条目，可按模块页面浏览；搜索与筛选需要启用 JavaScript。</p></noscript>
</div>"""


def home_showcase(prefix: str = "./") -> str:
    """Two equal featured cards on the homepage: the octopus demo and the board."""
    cards = [
        ("octo", f"{prefix}m/octopus.html", f"{prefix}assets/octopus-poster.jpg", "玻璃机械章鱼 3D 拆解演示截图",
         "实验室 · 3D 拆解", "机械章鱼 HYALOS GX-8", "完全由代码在浏览器里生成，上千个零件，会自己一件件拆开再组装。", "打开 3D 演示"),
        ("board", f"{prefix}m/board.html", f"{prefix}assets/board-poster.jpg", "星际信号站留言板星系截图",
         "匿名留言 · 无需登录", "星际信号站 留言板", "写下想说的话，它会化作一颗信号星，飞进可以拖动旋转的星系。", "进入信号站"),
    ]
    html = "".join(f"""<a class="show-card sc-{k}" href="{href}">
      <span class="sc-media"><img src="{img}" alt="{esc(alt)}" loading="lazy" decoding="async" width="960" height="540" /><span class="sc-scan" aria-hidden="true"></span></span>
      <span class="sc-body"><span class="sc-kicker"><i class="live-dot"></i>{esc(kick)}</span><b class="sc-title">{esc(title)}</b>
        <span class="sc-desc">{esc(desc)}</span><span class="sc-cta">{esc(cta)} <i aria-hidden="true">→</i></span></span>
    </a>""" for k, href, img, alt, kick, title, desc, cta in cards)
    wan = """<a class="wan-banner" href="https://wan.is-my.app/" aria-label="玩点啥：今日热榜、你画我猜、打字背单词、在线工具箱">
      <span class="wb-mark" aria-hidden="true">玩</span>
      <span class="wb-body"><span class="wb-kicker">新栏目 · 免费 · 免登录</span>
        <b class="wb-title">玩点啥？今天上网玩什么，这一页就够了</b>
        <span class="wb-chips"><span>今日热榜</span><span>你画我猜</span><span>打字背单词</span><span>在线工具箱</span><span>摸鱼首页</span></span></span>
      <span class="wb-cta">去看看 <i aria-hidden="true">→</i></span>
    </a>"""
    return f'<div class="showcase" aria-label="本站展示">{wan}{html}</div>'


# ============================================================ pages
def write_item_pages(items: list[dict], all_for_related: list[dict]) -> list[str]:
    ITEMS.mkdir(parents=True, exist_ok=True)
    paths = []
    for it in items:
        slug = it["_slug"]
        t = it["title"]
        page_title = f"{t} - 免费领取方法 | {SITE_NAME}"
        desc = (it.get("summary") or t)[:150]
        canonical = f"{CANONICAL}item/{slug}.html"
        mid = it["module"]
        mhref = next((h for m, _t, _d, h, *_ in MODULES if m == mid), "")
        rel = [x for x in all_for_related if x is not it and x.get("module") == mid][:6]
        rel_html = "".join(f'<li><a href="../{esc(r["_path"])}">{esc(r["title"])}</a></li>' for r in rel) or "<li>暂无</li>"
        rows = []
        for k in ("requires_card", "requires_realname", "china_accessible", "type"):
            label, names = FACT_LABELS[k]
            v = it.get(k) or "unknown"
            rows.append(f"<tr><th>{esc(label)}</th><td class=\"{'unk' if v == 'unknown' else ''}\">{esc(names.get(v, v))}</td></tr>")
        rows.append(f"<tr><th>额度有效期</th><td>{esc(curate.EXPIRY_LABEL.get(it.get('expiry_kind') or 'unknown'))}</td></tr>")
        rows.append(f"<tr><th>截止时间</th><td>{esc(fmt_dt(it['expires_at']) + ' 北京时间') if it.get('expires_at') else '未注明'}</td></tr>")
        rows.append(f"<tr><th>状态</th><td>{esc(it['status_label'])}</td></tr>")
        rows.append(f"<tr><th>来源</th><td>{esc(it.get('source'))}{(' · @' + esc(it['author'])) if it.get('author') else ''}</td></tr>")
        rows.append(f"<tr><th>发布时间</th><td>{esc(fmt_dt(it.get('published_at')) + ' 北京时间') if it.get('published_at') else '未知'}</td></tr>")
        rows.append(f"<tr><th>本站收录</th><td>{esc(fmt_dt(it.get('fetched_at')))} 北京时间</td></tr>")
        ver = (f"已核实（{fmt_dt(it['verified_at'])} 北京时间，对照官网）" if it.get("verified_at") else "未核实：信息来自公开帖子/网页，本站尚未对照官网核实")
        rows.append(f"<tr><th>核实情况</th><td>{esc(ver)}</td></tr>")
        up = updated_at(it)
        rows.append(f"<tr><th>更新于</th><td>{esc(fmt_dt(up)) + ' 北京时间' if up else '未知'}</td></tr>")
        lcls, ltxt = link_state(it)
        rows.append(f"<tr><th>链接检查</th><td class=\"lc {lcls}\">{esc(ltxt)}（本站程序每小时自动检查打开情况）</td></tr>")
        feats = "".join(f"<li>{esc(f)}</li>" for f in it.get("features") or [])
        links = "".join(f'<li><a href="{esc(u)}" target="_blank" rel="noopener noreferrer">{esc(u)}</a></li>' for u in it.get("links") or [])
        vs = "".join(f'<li><a href="{esc(u)}" target="_blank" rel="noopener noreferrer">{esc(u)}</a></li>' for u in it.get("verified_source") or [])
        ld = [
            {"@context": "https://schema.org", "@type": "Article", "headline": t, "description": desc,
             "datePublished": it.get("published_at") or it.get("fetched_at"), "dateModified": it.get("fetched_at"),
             "mainEntityOfPage": canonical, "author": {"@type": "Organization", "name": SITE_NAME}},
            {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "首页", "item": CANONICAL},
                {"@type": "ListItem", "position": 2, "name": it["module_name"], "item": f"{CANONICAL}{mhref}"},
                {"@type": "ListItem", "position": 3, "name": t, "item": canonical},
            ]},
        ]
        go, go_rel, go_code = aff_link(it)
        page = f"""{head_block(page_title, desc, canonical, t, pubdate=it.get('published_at'), extra_ld=ld)}
{page_shell_start("../", "detail")}
<div class="wrap" data-share-url="{esc(canonical)}">
  <div class="crumbs"><a href="../">首页</a> › <a href="../{esc(mhref)}" data-s-mod>{esc(it['module_name'])}</a> › 详情</div>
  <header class="hero">
    <div class="eyebrow"><i class="live-dot"></i> {esc(it['module_name'])}</div>
    <h1 data-s-title>{esc(t)}</h1>
    <p class="lead" data-s-sum>{esc(it.get('summary') or '')}</p>
    <div class="facts big">{fact_badges(it)}<span class="st st-{STATUS_CLASS.get(it['status'], 'muted')}" data-s-st>{esc(it['status_label'])}</span></div>
    {SHARE_ROW}
  </header>
  <section class="panel-box">
    <h2>关键信息</h2>
    <table class="facts-table">{''.join(rows)}</table>
    {f'<ul class="pin-feats">{feats}</ul>' if feats else ''}
    {f'<div class="how"><strong>怎么领：</strong><span data-s-how>{esc(it["how"])}</span></div>' if it.get('how') else '<p class="note">原文没有写明具体领取步骤，请打开原文或官网查看。</p>'}
    <p class="actions"><a class="btn primary" href="{esc(go)}" target="_blank" rel="{go_rel}">{'打开官网' if it.get('pinned') else '打开原文'} ↗</a>{aff_note(go_code)}
    <a class="btn" href="../{esc(mhref)}">同模块更多</a>
    <a class="btn" href="{esc(issue_link(it))}" target="_blank" rel="noopener">报错 / 已过期</a></p>
    {f'<h3>原文中的链接</h3><ul class="plain">{links}</ul>' if links else ''}
    {f'<h3>核实依据</h3><ul class="plain">{vs}</ul>' if vs else ''}
  </section>
  <section class="panel-box"><h2>同模块推荐</h2><ul class="plain">{rel_html}</ul></section>
  {site_footer("../")}
</div>
{page_scripts()}
</body></html>"""
        (ITEMS / f"{slug}.html").write_text(page, encoding="utf-8")
        paths.append(f"item/{slug}.html")
    keep = {Path(p).name for p in paths}
    for f in ITEMS.glob("*.html"):
        if f.name not in keep:
            f.unlink()  # stale page of an item that is no longer published (dropped by curation)
    return paths


def write_category_pages(active: list[dict], date: str, ym: str) -> list[str]:
    CATS.mkdir(parents=True, exist_ok=True)
    paths = []
    for mid, title, desc, href, kind, cat in MODULES:
        if kind != "cat":
            continue
        sub = [it for it in active if it["module"] == mid]
        intro = CAT_INTRO[cat]
        canonical = f"{CANONICAL}{href}"
        cards = "\n".join(card_deal(it, prefix="../") for it in sub)
        ld = [
            {"@context": "https://schema.org", "@type": "CollectionPage", "name": title, "url": canonical, "description": intro},
            {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "url": f"{CANONICAL}{it['_path']}", "name": it["title"]} for i, it in enumerate(sub[:50])]},
        ]
        stats = (f'<div class="pill">本模块 <b>{len(sub)}</b> 条</div>'
                 f'<div class="pill">更新 <b>{esc(date)}</b></div>')
        page = f"""{head_block(f"{title} | {SITE_NAME} · {ym}", intro, canonical, extra_ld=ld)}
{page_shell_start("../", "module")}
{mod_hero("MODULE", title, intro, stats, f'<a href="../">首页</a> › {esc(title)}', "../vendor/")}
<div class="wrap">
  <section class="section" id="search">
    {filter_panel(sub, False, "在本模块内搜索…")}
    <div class="grid" data-list>{cards or '<div class="empty">本模块暂无条目</div>'}</div>
    <div id="f-empty" class="empty hidden">没有符合条件的条目，试试清除筛选</div>
  </section>
  {site_footer("../", title)}
</div>
{page_scripts()}
</body></html>"""
        (CATS / f"{CAT_SLUG[cat]}.html").write_text(page, encoding="utf-8")
        paths.append(href)
    return paths


def write_module_special(repos: list[dict], topics: list[dict], date: str, ym: str) -> list[str]:
    MODS.mkdir(parents=True, exist_ok=True)
    specs = [
        ("github-hot.html", "GitHub 新热门", f"GitHub 新热门 | {SITE_NAME} · {ym}", "近 7–14 天新建的 AI / 大模型 / Agent 开源项目，按星标排序；仅收录与 AI 相关的仓库。",
         "GITHUB", repos, card_repo, "项目"),
        ("hot-topics.html", "最近热议", f"最近热议 / 最新AI新闻 | {SITE_NAME} · {ym}", "Hacker News、V2EX 等社区里与 AI、科技相关的热门讨论（非 AI 话题已过滤），标题已译为中文。",
         "PULSE", topics, card_hot, "话题"),
    ]
    paths = []
    for fname, title, ptitle, lead, eb, rows, fn, unit in specs:
        cards = "\n".join(fn(r, "../") for r in rows) or '<div class="empty">暂无</div>'
        stats = f'<div class="pill">{unit} <b>{len(rows)}</b></div><div class="pill">更新 <b>{esc(date)}</b></div>'
        page = f"""{head_block(ptitle, lead, f"{CANONICAL}m/{fname}")}
{page_shell_start("../", "module")}
{mod_hero(eb, title, lead, stats, f'<a href="../">首页</a> › {esc(title)}', "../vendor/")}
<div class="wrap">
  <section class="section" id="search">
    <div class="filters" data-filter-root>
      <form class="searchbar" role="search" onsubmit="return false"><label class="sr-only" for="q">搜索</label><input id="q" type="search" placeholder="搜索{esc(title)}…" autocomplete="off" /><button type="submit" class="btn primary">搜索</button></form>
      <div class="fbar"><span id="f-count" class="f-count">共 {len(rows)} 条</span></div>
    </div>
    <div class="grid" data-list>{cards}</div>
    <div id="f-empty" class="empty hidden">没有匹配条目</div>
  </section>
  {site_footer("../")}
</div>
{page_scripts()}
</body></html>"""
        (MODS / fname).write_text(page, encoding="utf-8")
        paths.append(f"m/{fname}")
    return paths


def write_archives(active: list[dict], archived: list[dict], days: list[str]) -> list[str]:
    """archives/index.html = expired + >30-day-old items; archives/<day>.html = items first collected that day."""
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    paths = []
    everything = active + archived
    by_day: dict[str, list[dict]] = {}
    for it in everything:
        d = fmt_dt(it.get("fetched_at"), False)
        by_day.setdefault(d, []).append(it)
    day_list = sorted((d for d in by_day if d != "未知"), reverse=True)
    for day in day_list:
        rows = by_day[day]
        cards = "\n".join(card_deal(it, "../") for it in rows)
        page = f"""{head_block(f"{day} 收录 · {SITE_NAME}", f"{SITE_NAME} {day} 收录的免费资源", f"{CANONICAL}archives/{day}.html")}
{page_shell_start("../", "archive")}
<div class="wrap">
  <div class="crumbs"><a href="../">首页</a> › <a href="index.html">归档</a> › {esc(day)}</div>
  <header class="hero"><div class="eyebrow"><i class="live-dot"></i> 按日归档</div><h1>{esc(day)} 收录</h1>
  <p class="lead">这一天本站首次收录的 {len(rows)} 条资源（含之后已过期或已归档的条目，状态见卡片右上角）。</p></header>
  <div class="grid">{cards}</div>
  <div class="panel-box"><h2>其他日期</h2>{''.join(f'<a class="arch{" current" if d == day else ""}" href="{d}.html">{d}</a>' for d in day_list[:60])}</div>
  {site_footer("../")}
</div>
{page_scripts()}
</body></html>"""
        (ARCHIVES / f"{day}.html").write_text(page, encoding="utf-8")
        paths.append(f"archives/{day}.html")
    # legacy day pages that no longer have items: keep the URL alive with a pointer page
    for f in ARCHIVES.glob("????-??-??.html"):
        if f.stem not in by_day:
            f.write_text(f"""{head_block(f"{f.stem} · {SITE_NAME}", "归档", f"{CANONICAL}archives/{f.stem}.html")}
{page_shell_start("../", "archive")}<div class="wrap"><header class="hero"><h1>{esc(f.stem)}</h1><p class="lead">这一天的条目已在内容整理中合并或移除，请查看<a href="index.html">归档</a>或<a href="../">首页</a>。</p></header>{site_footer("../")}</div>{page_scripts()}</body></html>""", encoding="utf-8")
    cards = "\n".join(card_deal(it, "../") for it in archived) or '<div class="empty">暂无已归档条目</div>'
    page = f"""{head_block(f"已归档 / 已过期 · {SITE_NAME}", "已过期或超过 30 天的免费资源归档", f"{CANONICAL}archives/index.html")}
{page_shell_start("../", "archive")}
<div class="wrap">
  <div class="crumbs"><a href="../">首页</a> › 归档</div>
  <header class="hero"><div class="eyebrow"><i class="live-dot"></i> 归档</div><h1>已归档 / 已过期</h1>
  <p class="lead">已过截止日期的条目，以及发布超过 30 天且没有未来截止日期的自动收录条目，会从首页移到这里（共 {len(archived)} 条），仅供参考，大多已无法领取。</p>
  <p class="lead">按收录日期浏览：{''.join(f'<a class="arch" href="{d}.html">{d}</a>' for d in day_list[:60])}</p></header>
  <div class="grid">{cards}</div>
  {site_footer("../")}
</div>
{page_scripts()}
</body></html>"""
    (ARCHIVES / "index.html").write_text(page, encoding="utf-8")
    paths.append("archives/index.html")
    return paths, day_list


# ============================================================ API
V1_FIELDS = ["id", "title", "summary", "url", "source", "module", "type", "requires_card", "requires_realname",
             "china_accessible", "expires_at", "verified_at", "fetched_at", "status"]
V1_EXTRA = ["module_name", "category", "status_label", "published_at", "expiry_kind", "time_limited", "how", "links",
            "source_domain", "pinned", "path"]
ENUMS = {
    "type": ["permanent", "trial", "quota", "unknown"],
    "requires_card": ["no", "yes", "partial", "unknown"],
    "requires_realname": ["no", "yes", "partial", "unknown"],
    "china_accessible": ["yes", "no", "unknown"],
    "status": ["available", "expiring", "expired", "unverified", "archived"],
    "expiry_kind": list(curate.EXPIRY_LABEL),
    "time_limited": ["yes", "no", "unknown"],
}


def v1_item(it: dict) -> dict:
    out = {}
    for k in V1_FIELDS + V1_EXTRA:
        v = it.get(k)
        if k == "path":
            v = it.get("_path")
        elif k == "pinned":
            v = bool(it.get("pinned"))
        elif k == "links":
            v = list(it.get("links") or [])
        elif k in ENUMS:
            v = v if v in ENUMS[k] else "unknown"
        elif k in ("expires_at", "verified_at", "published_at", "fetched_at"):
            v = v or None
        elif v is None:
            v = ""
        out[k] = v
    return out


def legacy_item(it: dict) -> dict:
    d = v1_item(it)
    d.update({
        "category": it.get("category") or "",
        "author": it.get("author") or "",
        "deadline": fmt_dt(it["expires_at"], False) if it.get("expires_at") else None,
        "posted_at": (fmt_dt(it.get("published_at")) + " Asia/Shanghai") if it.get("published_at") else "",
    })
    if it.get("pinned"):
        d.update(features=it.get("features") or [], start_url=it.get("start_url") or it.get("url"), badge="置顶 · 编辑推荐", reason=it.get("reason") or "")
    return d


def side_item(it: dict, kind: str) -> dict:
    d = {"id": it.get("id") or "", "title": it.get("title") or "", "summary": it.get("summary") or "", "url": it.get("url") or "",
         "source": it.get("source") or ""}
    if kind == "github":
        d.update(name=it.get("name") or "", stars=it.get("stars"), language=it.get("language") or "", created_at=it.get("created_at"))
    return d


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


DEFINITIONS = {
    "free_resources": "免费资源 = 去重后仍在有效期内的资源条目（含置顶与编辑整理条目；不含 GitHub 新热门与最近热议；已过期、或发布超过 30 天且没有未来截止日期的自动收录条目会移入归档）。",
    "modules": "七个资源模块的条数之和 = 免费资源总数；GitHub 新热门、最近热议单独计数。",
    "today_new": "今日新增 = 今天（北京时间）首次被本站收录、且仍有效的条目数。",
    "unknown": "枚举字段无法从原文确定时一律为 \"unknown\"（页面显示为“未注明”），本站不做猜测；时间字段缺失时为 null。",
    "verified_at": "verified_at 仅在编辑对照官网核实后填写，否则为 null（页面显示“未核实”）。",
}


def write_api(active, archived, repos, topics, counts, now, report) -> None:
    api = SITE / "api"
    now_iso = curate.iso(now)
    now_label = now.strftime("%Y-%m-%d %H:%M Asia/Shanghai")
    # ---------------- v1
    v1 = api / "v1"
    items = [v1_item(it) for it in active]
    per = 50
    pages = max(1, (len(items) + per - 1) // per)
    for old in (v1 / "items").glob("page-*.json") if (v1 / "items").exists() else []:
        old.unlink()
    for p in range(pages):
        chunk = items[p * per:(p + 1) * per]
        dump(v1 / "items" / f"page-{p + 1}.json", {
            "page": p + 1, "per_page": per, "total": len(items), "total_pages": pages,
            "next": f"api/v1/items/page-{p + 2}.json" if p + 1 < pages else None,
            "prev": f"api/v1/items/page-{p}.json" if p > 0 else None,
            "generated_at": now_iso, "items": chunk})
    dump(v1 / "archived.json", {"generated_at": now_iso, "total": len(archived), "items": [v1_item(it) for it in archived]})
    for mid, title, desc, href, kind, cat in MODULES:
        if kind == "cat":
            sub = [v1_item(it) for it in active if it["module"] == mid]
        elif kind == "github":
            sub = [side_item(r, "github") for r in repos]
        else:
            sub = [side_item(t, "hot") for t in topics]
        dump(v1 / "modules" / f"{mid}.json", {"id": mid, "title": title, "description": desc, "href": href, "count": len(sub), "generated_at": now_iso, "items": sub})
    dump(v1 / "github-hot.json", {"generated_at": now_iso, "count": len(repos), "items": [side_item(r, "github") for r in repos]})
    dump(v1 / "hot.json", {"generated_at": now_iso, "count": len(topics), "items": [side_item(t, "hot") for t in topics]})
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{CANONICAL}api/v1/schema.json",
        "title": "AI大模型免费资源导航 · 资源条目 (v1)",
        "type": "object",
        "required": V1_FIELDS,
        "properties": {
            "id": {"type": "string", "description": "稳定 ID"},
            "title": {"type": "string", "description": "中文标题：谁提供了什么"},
            "summary": {"type": "string", "description": "1–2 句摘要，不重复标题"},
            "url": {"type": "string", "format": "uri", "description": "原文 / 官网链接（Google News 跳转已解析为原始链接）"},
            "source": {"type": "string", "description": "来源站点（X / GitHub / Hacker News / 官网域名…）"},
            "module": {"type": "string", "enum": [m for m, *_ in MODULES if _[3] == "cat"]},
            "type": {"type": "string", "enum": ENUMS["type"], "description": "permanent=永久免费 trial=试用 quota=限额"},
            "requires_card": {"type": "string", "enum": ENUMS["requires_card"]},
            "requires_realname": {"type": "string", "enum": ENUMS["requires_realname"], "description": "是否需要实名或手机号"},
            "china_accessible": {"type": "string", "enum": ENUMS["china_accessible"], "description": "国内能否直连"},
            "expires_at": {"type": ["string", "null"], "format": "date-time", "description": "截止时间（北京时间 ISO 8601），未注明为 null"},
            "verified_at": {"type": ["string", "null"], "format": "date-time", "description": "编辑对照官网核实的时间，未核实为 null"},
            "fetched_at": {"type": "string", "format": "date-time", "description": "本站首次收录时间"},
            "status": {"type": "string", "enum": ENUMS["status"], "description": "available=可领(已核实) expiring=7 天内截止 expired=已过期 unverified=未核实 archived=已归档"},
            "module_name": {"type": "string"}, "category": {"type": "string"}, "status_label": {"type": "string"},
            "published_at": {"type": ["string", "null"], "format": "date-time"},
            "expiry_kind": {"type": "string", "enum": ENUMS["expiry_kind"], "description": "deadline=有截止日期 daily=按日重置 periodic=按周/月发放 limited=限期试用 long=长期有效"},
            "time_limited": {"type": "string", "enum": ENUMS["time_limited"]},
            "how": {"type": "string", "description": "原文中的具体领取步骤；没有则为空字符串"},
            "links": {"type": "array", "items": {"type": "string"}, "description": "原文中出现的外部链接（t.co 已展开）"},
            "source_domain": {"type": "string"}, "pinned": {"type": "boolean"}, "path": {"type": "string", "description": "站内详情页路径"},
        },
        "x-definitions": DEFINITIONS,
    }
    dump(v1 / "schema.json", schema)
    idx = {
        "name": SITE_NAME, "version": "v1", "canonical": CANONICAL, "generated_at": now_iso,
        "counts": counts, "definitions": DEFINITIONS, "curation_version": curate.CURATION_VERSION,
        "pagination": {"per_page": per, "total_pages": pages, "first": "api/v1/items/page-1.json"},
        "endpoints": {
            "items": "api/v1/items/page-{n}.json", "archived": "api/v1/archived.json", "schema": "api/v1/schema.json",
            "modules": {mid: f"api/v1/modules/{mid}.json" for mid, *_ in MODULES},
            "github_hot": "api/v1/github-hot.json", "hot": "api/v1/hot.json",
        },
        "legacy": ["api/latest.json", "api/meta.json", "api/index.json", "api/github-hot.json", "api/hot.json"] + [f"api/{m}.json" for m, *_ in MODULES],
    }
    dump(v1 / "index.json", idx)
    # ---------------- legacy endpoints (kept working)
    leg = [legacy_item(it) for it in active]
    dump(api / "latest.json", {"updated_at_label": now_label, "generated_at_label": now_label, "generated_at": now_iso,
                               "date": now.strftime("%Y-%m-%d"), "count": len(leg), "pinned_count": sum(1 for x in leg if x["pinned"]),
                               "definition": DEFINITIONS["free_resources"], "items": leg})
    dump(api / "github-hot.json", {"updated_at_label": now_label, "count": len(repos), "items": [side_item(r, "github") for r in repos]})
    dump(api / "hot.json", {"updated_at_label": now_label, "count": len(topics), "items": [side_item(t, "hot") for t in topics]})
    for mid, title, desc, href, kind, cat in MODULES:
        sub = ([legacy_item(it) for it in active if it["module"] == mid] if kind == "cat"
               else [side_item(r, "github") for r in repos] if kind == "github" else [side_item(t, "hot") for t in topics])
        dump(api / f"{mid}.json", {"id": mid, "title": title, "description": desc, "href": href, "count": len(sub), "items": sub})
    meta = {
        "name": SITE_NAME, "canonical": CANONICAL, "version": "3.0.0", "curation_version": curate.CURATION_VERSION,
        "updated_at_label": now_label, "generated_at_label": now_label, "generated_at": now_iso,
        "next_update_label": counts.get("next_update_label"),
        "date": now.strftime("%Y-%m-%d"), "counts": counts, "definitions": DEFINITIONS,
        "curation": {k: v for k, v in (report.get("counts") or {}).items()},
        "cli": {
            "download_inspect_run": [f"curl -fsSLo ai168.sh {CANONICAL}cli.sh", "less ai168.sh", "bash ai168.sh list"],
            "plain_curl": f"curl {CANONICAL}api/latest.json",
            "npx": "npx github:aiym168/aiym168.github.io list",
        },
    }
    dump(api / "meta.json", meta)
    dump(api / "index.json", {"canonical": CANONICAL, "endpoints": [
        {"path": "api/v1/index.json", "desc": "v1 接口目录（推荐）：分页、字段定义、计数"},
        {"path": "api/v1/schema.json", "desc": "v1 条目 JSON Schema"},
        {"path": "api/v1/items/page-1.json", "desc": "v1 全部有效资源（每页 50 条）"},
        {"path": "api/v1/archived.json", "desc": "v1 已归档 / 已过期"},
        {"path": "api/meta.json", "desc": "站点元信息与计数"},
        {"path": "api/latest.json", "desc": "全部有效免费资源（旧版，字段向下兼容）"},
        {"path": "api/github-hot.json", "desc": "GitHub 新热门"},
        {"path": "api/hot.json", "desc": "最近热议"},
        {"path": "feed.xml", "desc": "RSS 订阅"},
        {"path": "feed.atom", "desc": "Atom 订阅（含更新时间）"},
        {"path": "api/digest.json", "desc": "今日速递文案（X / 微信 / 小红书草稿）"},
        {"path": "api/linkcheck.json", "desc": "链接自动检查结果与下架记录"},
    ] + [{"path": f"api/{mid}.json", "desc": title} for mid, title, *_ in MODULES]})

    def x(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    rows = []
    for it in active[:60]:
        rows.append(f"  <item>\n    <title>{x(it['title'])}</title>\n    <link>{x(CANONICAL + it['_path'])}</link>\n"
                    f"    <guid isPermaLink=\"false\">{x(it['id'])}</guid>\n    <description>{x(it.get('summary') or '')}</description>\n"
                    f"    <category>{x(it.get('module_name') or '')}</category>\n  </item>")
    (SITE / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">\n<channel>\n'
        f"<title>{x(SITE_NAME)}</title>\n<link>{x(CANONICAL)}</link>\n<description>{x(META_DESC)}</description>\n"
        f"<language>zh-CN</language>\n<lastBuildDate>{x(now_label)}</lastBuildDate>\n" + "\n".join(rows) + "\n</channel>\n</rss>\n",
        encoding="utf-8")
    print(f"[api] v1 pages={pages} items={len(items)} archived={len(archived)} repos={len(repos)} hot={len(topics)}")


def cli_steps() -> str:
    c = CANONICAL
    return (f"curl -fsSLo ai168.sh {c}cli.sh   # 1. 下载脚本\n"
            f"less ai168.sh                                       # 2. 先检查内容\n"
            f"bash ai168.sh list                                  # 3. 确认无误后再运行\n"
            f"bash ai168.sh search 免费GPU")


def write_api_docs_page(date: str, counts: dict) -> str:
    MODS.mkdir(parents=True, exist_ok=True)
    canonical = f"{CANONICAL}m/api.html"
    intro = (f"{SITE_NAME} 提供免密钥的静态 JSON 接口与一个可审阅的命令行脚本，数据每小时随站点重建。"
             f"所有字段与页面一致：是否需绑卡、实名、国内直连、免费类型、截止时间、核实时间与状态。")
    plain = f"curl {CANONICAL}api/latest.json\ncurl {CANONICAL}api/v1/items/page-1.json"
    npx = "npx github:aiym168/aiym168.github.io list"
    rows = "".join(f"<tr><td><code>api/v1/modules/{esc(mid)}.json</code></td><td>{esc(t)}</td></tr>" for mid, t, *_ in MODULES)
    fields = "".join(f"<tr><td><code>{esc(k)}</code></td><td>{esc(v)}</td></tr>" for k, v in [
        ("id", "稳定 ID"), ("title / summary", "中文标题与 1–2 句摘要"), ("url", "原文或官网链接"), ("source", "来源站点"),
        ("module", "所属模块 ID"), ("type", "permanent 永久免费 / trial 试用 / quota 限额 / unknown"),
        ("requires_card", "no / yes / partial / unknown"), ("requires_realname", "no / yes / partial / unknown（实名或手机号）"),
        ("china_accessible", "yes / no / unknown（国内能否直连）"), ("expires_at", "截止时间 ISO 8601（北京时间），无则 null"),
        ("verified_at", "编辑核实时间，未核实为 null"), ("fetched_at", "本站首次收录时间"),
        ("status", "available 可领 / expiring 即将过期 / expired 已过期 / unverified 未核实 / archived 已归档")])
    page = f"""{head_block(f"CLI / API · {SITE_NAME}", intro, canonical)}
{page_shell_start("../", "api-page")}
<div class="wrap">
  <div class="crumbs"><a href="../">首页</a> › CLI / API</div>
  <header class="hero">
    <div class="eyebrow"><i class="live-dot"></i> 开发者接口</div>
    <h1 class="hero-title">CLI / API</h1>
    <p class="lead">{esc(intro)}</p>
  </header>
  <section class="section">
    <h2>最简单：直接读 JSON</h2>
    <p class="sec-desc">不需要安装任何东西，也不执行远程脚本。</p>
    <div class="term-block"><div class="term-bar"><span></span><span></span><span></span><em>curl</em><button type="button" class="copy-btn" data-copy="{esc(plain)}">复制</button></div><pre><code>{esc(plain)}</code></pre></div>
  </section>
  <section class="section">
    <h2>命令行脚本：先下载、检查，再运行</h2>
    <p class="sec-desc">脚本只做 HTTP GET 读取本站 JSON，并用本机 python3 格式化输出。建议先用 <code>less</code> 看一遍内容再运行；我们不推荐把远程脚本直接管道给 bash。</p>
    <div class="term-block"><div class="term-bar"><span></span><span></span><span></span><em>bash</em><button type="button" class="copy-btn" data-copy="{esc(cli_steps())}">复制</button></div><pre><code>{esc(cli_steps())}</code></pre></div>
    <div class="panel-box"><ul class="api-cmds">
      <li><code>list [模块ID]</code> 列出全部或某个模块的资源</li><li><code>search &lt;关键词&gt;</code> 搜索</li>
      <li><code>hot</code> / <code>github</code> 最近热议 / GitHub 新热门</li><li><code>open &lt;id&gt;</code> 打开条目链接</li>
      <li><code>meta</code> 更新时间与计数</li><li><code>--limit N</code> 限制条数</li></ul>
      <p class="note">有 Node.js 也可以用：<code>{esc(npx)}</code>（同样只读取公开 JSON）。</p></div>
  </section>
  <section class="section">
    <h2>v1 接口（推荐）</h2>
    <p class="sec-desc">分页（每页 50 条）、固定字段、未知值统一为 <code>"unknown"</code>。旧接口 <code>api/latest.json</code> 等继续可用。</p>
    <div class="panel-box"><table class="api-table"><thead><tr><th>路径</th><th>说明</th></tr></thead><tbody>
      <tr><td><code>api/v1/index.json</code></td><td>目录、计数、字段定义、分页信息</td></tr>
      <tr><td><code>api/v1/schema.json</code></td><td>条目 JSON Schema</td></tr>
      <tr><td><code>api/v1/items/page-1.json</code></td><td>有效资源，第 1 页（共 {counts.get('api_pages', 1)} 页）</td></tr>
      <tr><td><code>api/v1/archived.json</code></td><td>已归档 / 已过期</td></tr>
      <tr><td><code>api/v1/github-hot.json</code> · <code>api/v1/hot.json</code></td><td>GitHub 新热门 · 最近热议</td></tr>
      {rows}
    </tbody></table></div>
    <div class="panel-box"><h3>条目字段</h3><table class="api-table"><tbody>{fields}</tbody></table>
    <p class="note">{esc(DEFINITIONS['free_resources'])}</p></div>
  </section>
  {site_footer("../", date)}
</div>
{page_scripts()}
</body></html>"""
    (MODS / "api.html").write_text(page, encoding="utf-8")
    return "m/api.html"


def write_404() -> None:
    (SITE / "404.html").write_text(f"""{head_block(f"页面未找到 | {SITE_NAME}", META_DESC, CANONICAL + "404.html")}
{page_shell_start("/", "notfound")}
<div class="wrap"><header class="hero"><div class="eyebrow"><i class="live-dot"></i> 404</div><h1>页面不存在</h1>
<p class="lead">这个条目可能已过期、被合并或移除。可以返回首页搜索，或查看已归档的条目。</p>
<p class="actions"><a class="btn primary" href="/">返回首页</a> <a class="btn" href="/archives/index.html">查看归档</a></p></header>
{site_footer("/")}</div>
{page_scripts()}
</body></html>""", encoding="utf-8")


def write_sitemaps(urls) -> None:
    now = datetime.now(TZ).strftime("%Y-%m-%d")
    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    abs_urls = []
    for path, lastmod, freq, pri in urls:
        loc = CANONICAL if path in ("", "/") else f"{CANONICAL}{path.lstrip('/')}"
        abs_urls.append(loc)
        body.append(f"  <url><loc>{esc(loc)}</loc><lastmod>{esc(lastmod or now)}</lastmod><changefreq>{esc(freq)}</changefreq><priority>{esc(pri)}</priority></url>")
    body.append("</urlset>")
    (SITE / "sitemap.xml").write_text("\n".join(body) + "\n", encoding="utf-8")
    (SITE / "sitemap.txt").write_text("\n".join(abs_urls) + "\n", encoding="utf-8")
    (SITE / "sitemap_index.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>{CANONICAL}sitemap.xml</loc><lastmod>{now}</lastmod></sitemap>
  <sitemap><loc>{CANONICAL}sitemap.txt</loc><lastmod>{now}</lastmod></sitemap>
</sitemapindex>
""", encoding="utf-8")
    dis = "Disallow: /data/\nDisallow: /engine/\nDisallow: /board/\n"
    (SITE / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n{dis}User-agent: Baiduspider\nAllow: /\n{dis}User-agent: Baiduspider-render\nAllow: /\n{dis}"
        f"Sitemap: {CANONICAL}sitemap_index.xml\nSitemap: {CANONICAL}sitemap.xml\nSitemap: {CANONICAL}sitemap.txt\n", encoding="utf-8")


def _board_teaser() -> str:
    try:
        from board.page import home_teaser_html
        return home_teaser_html("")
    except Exception as e:  # board must never break the main build
        print("[board] teaser skipped:", e)
        return ""


def _board_page(ym: str):
    try:
        from board.page import write_board_page
        return write_board_page(SITE, head_block=head_block, topnav=topnav, site_footer=site_footer, site_js=SITE_JS,
                                canonical=CANONICAL, site_name=SITE_NAME, ym=ym, esc=esc)
    except Exception as e:
        print("[board] page skipped:", e)
        return None


# ============================================================ 机械章鱼 3D 拆解演示（页面由此生成，脚本在 vendor/octopus.js）
OCTO_PARTS = [("玻璃头罩", "抬起并翻转"), ("光学眼", "镜组分离"), ("反应核心", "升出机体"), ("虹吸喷射管", "伸缩展开"), ("机械腕", "链节展开")]
OCTO_STEPS = ["入场", "头罩", "光学眼", "核心", "喷射管", "机械腕", "全拆解", "重组", "离场"]


def write_octopus_page(date: str) -> str:
    """/m/octopus.html — procedural three.js teardown simulator (no model files)."""
    prefix = "../"
    canonical = CANONICAL + "m/octopus.html"
    title = "HYALOS GX-8 玻璃机械章鱼 · 3D 拆解演示"
    desc = "一只完全由代码在浏览器里实时生成的玻璃机械章鱼：玻璃头罩、光学眼、反应核心、虹吸喷射管和 8 条机械腕，可自动演示拆解，也可拖动旋转、逐个拆开零件。"
    pills = "".join(f'<button type="button" class="octo-pill" data-octo-part="{i}"><i>0{i + 1}</i>{esc(n)}</button>'
                    for i, (n, _v) in enumerate(OCTO_PARTS))
    steps = "".join(f'<span data-octo-step="{i}">{esc(n)}</span>' for i, n in enumerate(OCTO_STEPS))
    labels = "".join(f'<div class="octo-label" data-octo-label="{i}"><i>0{i + 1}</i>{esc(n)}</div>' for i, (n, _v) in enumerate(OCTO_PARTS))
    rows = "".join(f'<li><b>0{i + 1} · {esc(n)}</b><span>{esc(v)}</span></li>' for i, (n, v) in enumerate(OCTO_PARTS))
    crumbs = f'<a href="{prefix}">首页</a> / 实验室 / 机械章鱼'
    ld = {"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": canonical, "description": desc, "inLanguage": "zh-CN"}
    page = f"""{head_block(title + " · " + SITE_NAME, desc, canonical, title, extra_ld=[ld], og_image=CANONICAL + "assets/octopus-poster.jpg")}
{page_shell_start(prefix, "octo-page")}
<main class="wrap octo-wrap">
  <div class="crumbs octo-crumbs">{crumbs}</div>
  <header class="octo-head">
    <div class="eyebrow"><i class="live-dot"></i> 实验室 · 浏览器实时生成</div>
    <h1 class="octo-title"><span class="kl">HYALOS GX-8</span><span class="octo-sub">玻璃机械章鱼 · 3D 拆解演示</span></h1>
    <p class="lead">没有导入任何 3D 模型文件：玻璃头罩、齿轮、舵机、反应核心、吸盘和 8 条机械腕，全部是页面打开时由代码在你的浏览器里现场生成的。</p>
  </header>
  <section class="octo-stage is-demo" id="octo-stage" aria-label="机械章鱼 3D 演示">
    <div class="octo-canvas" data-octo-canvas></div>
    <div class="octo-vignette" aria-hidden="true"></div>
    <svg class="octo-leaders" data-octo-leaders aria-hidden="true"></svg>
    <div class="octo-hud tl"><b class="brand">HYALOS GX-8</b><span>零件 <b data-octo-parts>—</b></span><span>图层 <b data-octo-layer>整机</b></span></div>
    <div class="octo-hud tr"><button type="button" class="octo-snd" data-octo-sound aria-pressed="false" title="机械变形音效（浏览器需要点击后才能出声）">🔊 声音 <b>关</b></button><span class="rec"><i></i>SIM</span><b data-octo-time>00:00.0</b></div>
    <div class="octo-status"><div class="octo-steps">{steps}</div><div class="octo-stline" data-octo-stage>正在生成零件…</div></div>
    <div class="octo-caption" data-octo-caption><span class="t" data-octo-caption-time>00:00.0</span><b data-octo-caption-title></b><span class="s" data-octo-caption-sub></span></div>
    <div class="octo-card" data-octo-card><div class="en" data-card-en></div><h3 data-card-name></h3><p data-card-fn></p><div class="read" data-card-read></div></div>
    {labels}
    <div class="octo-pills">{pills}<button type="button" class="octo-pill all" data-octo-all>全部拆解</button></div>
    <button type="button" class="octo-snd-cta" data-octo-sound-cta>🔊 点击开启音效</button>
    <div class="octo-cursor" data-octo-cursor aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 2l15 10.5-6.6 1.2 3.8 7.3-2.7 1.4-3.8-7.3L4 20z"/></svg></div>
    <noscript><p class="octo-fallback">需要开启 JavaScript 才能看到 3D 演示。</p></noscript>
    <p class="octo-fallback hidden" data-octo-nogl>你的浏览器没有开启 WebGL，暂时看不到 3D 演示。</p>
  </section>
  <div class="octo-controls" role="toolbar" aria-label="演示控制">
    <button type="button" class="btn" data-octo-demo aria-pressed="true">▶ 自动演示</button>
    <button type="button" class="btn" data-octo-explode>拆解</button>
    <button type="button" class="btn" data-octo-xray aria-pressed="false">线框 / 透视：<b>实体</b></button>
    <button type="button" class="btn" data-octo-sound aria-pressed="false">🔊 声音：<b>关</b></button>
    <button type="button" class="btn ghost" data-octo-reset>重置视角</button>
    <span class="octo-tip">拖动旋转 · 滚轮或双指缩放 · 点上面的零件按钮单独拆开 · 音效需点“声音”或“自动演示”后开启</span>
  </div>
  <section class="section octo-info">
    <div class="sec-head"><span class="sec-idx">拆解顺序</span><h2>自动演示约 30 秒</h2>
      <p class="sec-desc">喷射入场 → 5 个零件依次拆开（每个约 1 秒展开、停留运转、0.5 秒合上，各有自己的镜头）→ 330° 转台全机拆解 → 边转边快速重组 → 喷射离场。</p></div>
    <ol class="octo-list">{rows}</ol>
    <div class="disclaimer-card about"><p>这是一个代码生成的演示作品，“HYALOS GX-8”是虚构的产品名，零件功能和读数都是设定，不对应任何真实产品。手机上会自动减少零件数；开启“减少动态”或系统的减少动态效果时不会自动播放。音效全部由浏览器实时合成（Web Audio），没有使用任何录音素材，默认静音。</p>
      <p>本页共 <b data-octo-total>—</b> 个零件（重复的零件用实例化方式绘制，按个计数）。源码在 <a href="{REPO_URL}" rel="noopener">GitHub 仓库</a> 的 vendor/octopus.js。</p></div>
  </section>
  {site_footer(prefix, "页面生成于 " + date)}
</main>
{page_scripts()}
<script type="module">
import {{ mountOctopus }} from "{vurl(prefix, "octopus.js")}";
const st = document.getElementById("octo-stage");
let ok = false; try {{ const c = document.createElement("canvas"); ok = !!(c.getContext("webgl2") || c.getContext("webgl")); }} catch (e) {{}}
if (!ok || !mountOctopus(st)) {{ st.classList.add("no-gl"); st.querySelector("[data-octo-nogl]").classList.remove("hidden"); }}
</script>
</body></html>"""
    (SITE / "m" / "octopus.html").write_text(page, encoding="utf-8")
    return "m/octopus.html"


def octopus_teaser(prefix: str = "./") -> str:
    return f"""<section class="section" id="lab">
    <div class="sec-head"><span class="sec-idx">实验室</span><h2>HYALOS GX-8 · 玻璃机械章鱼</h2>
      <p class="sec-desc">一只完全由代码在浏览器里生成的 3D 机械章鱼，会自己一件件拆开再组装回去。</p></div>
    <a class="octo-teaser" href="{prefix}m/octopus.html">
      <span class="ot-img"><img src="{prefix}assets/octopus-poster.jpg" alt="玻璃机械章鱼 3D 拆解演示截图" loading="lazy" width="960" height="540" /></span>
      <span class="ot-body"><b>3D 拆解演示</b><span>玻璃头罩、光学眼、反应核心、喷射管、8 条机械腕，上千个零件，可拖动旋转、逐个拆开。</span><em>打开演示 →</em></span>
    </a>
  </section>"""


# ============================================================ homepage + build
def next_update(now: datetime) -> datetime:
    n = now.replace(minute=7, second=0, microsecond=0)
    return n if n > now else n + timedelta(hours=1)


def build():
    global CFG, SITE_NAME, CANONICAL, META_DESC
    CFG = load_cfg()
    SITE_NAME = CFG["site_name"]
    CANONICAL = CFG["canonical"]
    now = datetime.now(TZ)
    date = now.strftime("%Y-%m-%d")
    ym = ym_label(date)

    active, archived, repos, topics, days, report = collect(now)
    today = now.date()
    today_new = sum(1 for it in active if (curate.parse_dt(it.get("fetched_at")) or now).astimezone(TZ).date() == today)
    try:
        import freshness
        today_html = freshness.today_section(sys.modules[__name__], active, now)
        freshness.write_atom(sys.modules[__name__], active, now)
        freshness.write_linkcheck_report(sys.modules[__name__], now)
        dg = freshness.write_digest(sys.modules[__name__], active, now)
        print(f"[fresh] today={dg['today_new']} digest x={dg['x_single_len']}/280 linkcheck={LINKCHECK['counts']} hidden={len(LINKCHECK['hidden'])}")
    except Exception as e:  # 新鲜度模块出错不能拖垮主站
        import traceback
        traceback.print_exc()
        print("[fresh] skipped:", e)
        today_html = ""
    mod_counts = {mid: sum(1 for it in active if it["module"] == mid) for mid, *_r in MODULES if _r[3] == "cat"}
    mod_counts["github-hot"] = len(repos)
    mod_counts["hot-topics"] = len(topics)
    assert sum(v for k, v in mod_counts.items() if k not in ("github-hot", "hot-topics")) == len(active)
    nxt = next_update(now)
    counts = {
        "deals": len(active), "free_resources": len(active), "github_hot": len(repos), "hot": len(topics),
        "today_new": today_new, "archived": len(archived), "modules": mod_counts,
        "api_pages": max(1, (len(active) + 49) // 50), "next_update_label": nxt.strftime("%H:%M") + " 北京时间（约）",
    }

    item_paths = write_item_pages(active + archived, active)
    cat_paths = write_category_pages(active, date, ym)
    mod_paths = write_module_special(repos, topics, date, ym)
    arch_paths, day_list = write_archives(active, archived, days)
    write_404()
    write_api(active, archived, repos, topics, counts, now, report)
    write_api_docs_page(date, counts)
    octo_path = write_octopus_page(date)
    try:
        import deals_build
        deal_paths = deals_build.build_pages(sys.modules[__name__], now)
    except Exception as e:  # 情报中心出错不能拖垮主站
        import traceback
        traceback.print_exc()
        print("[deals] pages skipped:", e)
        deal_paths = []
    try:
        import apiprice_build
        ap_path = apiprice_build.build_page(sys.modules[__name__], now)
        if ap_path:
            deal_paths.append(ap_path)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("[apiprice] page skipped:", e)
    try:
        import radio_build
        rd_path = radio_build.build_page(sys.modules[__name__], now)
        if rd_path:
            deal_paths.append(rd_path)
        radio_home = radio_build.home_section("./")
    except Exception as e:  # 电台出错不能拖垮主站
        import traceback
        traceback.print_exc()
        print("[radio] skipped:", e)
        radio_home = ""
    try:
        import live_build
        lv_path = live_build.build_page(sys.modules[__name__], now)
        if lv_path:
            deal_paths.append(lv_path)
    except Exception as e:  # 信号站入口出错不能拖垮主站
        print("[live] skipped:", e)
    try:
        deals_home = deals_build.home_section("./")
    except Exception as e:
        print("[deals] home section skipped:", e)
        deals_home = ""

    # ---- module cards (uniform, server-rendered)
    tiles = []
    for mid, title, desc, href, kind, cat in MODULES:
        if kind == "cat":
            sub = [it for it in active if it["module"] == mid]
            latest = sorted(sub, key=lambda i: i.get("fetched_at") or "", reverse=True)
            latest_t = next((x["title"] for x in latest if not x.get("pinned")), latest[0]["title"] if latest else "")
        elif kind == "github":
            sub, latest_t = repos, (repos[0]["title"] if repos else "")
        else:
            sub, latest_t = topics, (topics[0]["title"] if topics else "")
        tiles.append(f"""<a class="module-card" href="{esc(href)}">
  <span class="mc-ico">{icon_svg(mid)}</span>
  <span class="mc-body"><h3>{esc(title)}</h3><span class="mc-desc">{esc(desc)}</span>
  <span class="mc-latest">{('最新：' + esc(latest_t)) if latest_t else '暂无条目'}</span></span>
  <span class="mc-count"><b>{len(sub)}</b>条</span>
</a>""")

    latest5 = sorted([it for it in active if not it.get("pinned")], key=lambda i: (i.get("fetched_at") or "", i.get("published_at") or ""), reverse=True)[:5]
    latest_html = "".join(
        f'<li><a href="{esc(it["_path"])}">{esc(it["title"])}</a><span>{esc(it["module_name"])} · 收录 {esc(fmt_dt(it.get("fetched_at")))}</span></li>'
        for it in latest5)
    cards = "\n".join(card_deal(it) for it in active)
    arch_section = ""
    if len(day_list) > 1:
        arch_section = ('<section class="section" id="archives"><div class="sec-head"><span class="sec-idx">按日归档</span><h2>每日收录</h2></div><div class="panel-box">'
                        + "".join(f'<a class="arch" href="archives/{d}.html">{d}</a>' for d in day_list[:30]) + "</div></section>")
    upd = now.strftime("%H:%M")
    website_ld = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": CANONICAL, "description": META_DESC,
                  "inLanguage": "zh-CN", "potentialAction": {"@type": "SearchAction", "target": f"{CANONICAL}?q={{search_term_string}}",
                                                             "query-input": "required name=search_term_string"}}
    home_faq = [
        ("这个网站是免费的吗？", "完全免费。AI大模型免费资源导航不收费、不用注册，收录的也都是免费或有免费额度的 AI 资源；置顶条目为编辑推荐，非广告、未收费。"),
        ("哪里能找到免费的大模型 API？", "看「大模型免费API」栏目：DeepSeek、通义千问、智谱、Kimi、Gemini 等平台的免费额度和新人赠送 Token 都在这里，每条标注是否需要绑卡和实名。"),
        ("有免费的 GPU 和 AI 工具吗？", "有。免费 GPU 算力、AI 工具免费试用、免费课程分别在对应栏目，每小时自动更新，过期的会自动归档。"),
        ("国内能直接用吗？", "每条都标注了「国内能否直连」，看不到明确说明的会写“未注明”，不替你猜。"),
        ("还有其他免费工具吗？", "有，姊妹站「玩点啥」提供 30 多个免费在线工具（图片压缩、PDF 合并、证件照换底色、二维码、房贷个税计算器），地址 wan.is-my.app/gongju/。"),
    ]
    faq_ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in home_faq]}
    faq_section = ('<section class="section" id="faq"><div class="sec-head"><span class="sec-idx">常见问题</span><h2>免费 AI 资源常见问题</h2></div><div class="panel-box">'
                   + "".join(f"<h3>{esc(q)}</h3><p>{esc(a)}</p>" for q, a in home_faq) + "</div></section>")
    page = f"""{head_block(f"免费AI资源导航 - 大模型免费API、免费GPU、AI羊毛", META_DESC, CANONICAL, SITE_NAME + " · " + ym, extra_ld=[website_ld, faq_ld])}
{page_shell_start("./", "home")}
<header class="hero-xl hero-brain home-hero">
  <div class="hero-xl-inner">
    <div class="hero-copy">
      <div class="eyebrow"><i class="live-dot"></i> 每小时自动更新 · 北京时间</div>
      <h1 class="hero-title"><span class="kl">AI大模型</span><span class="kl">免费资源导航</span></h1>
      <p class="lead">收集大模型免费 API、免费 Token、免费 GPU、AI 工具试用与免费课程。每条都标注是否需要绑卡、实名、国内能否直连和截止时间；不确定的写“未注明”，不替你猜。</p>
      <div class="stats" aria-label="站点数据">
        <div class="pill"><span>免费资源</span><b>{len(active)}</b><span>条</span></div>
        <a class="pill" href="#today"><span>今日新增</span><b>{today_new}</b><span>条</span></a>
        <div class="pill"><span>最后更新</span><b>{esc(upd)}</b></div>
        <div class="pill"><span>下次更新约</span><b>{esc(nxt.strftime('%H:%M'))}</b></div>
      </div>
      <p class="def-note">{esc(DEFINITIONS['free_resources'])}</p>
    </div>
    {brain_block("vendor/", None, 4200)}
  </div>
</header>
{brain_loader_script("vendor/")}
<main class="wrap">
  {today_html}
  {deals_home}
  {radio_home}
  <section class="section" id="search">
    <div class="sec-head"><span class="sec-idx">01 · 找资源</span><h2>搜索与筛选</h2>
      <p class="sec-desc">搜索关键词，或按模块筛选；绑卡、实名、直连等条件在“更多筛选”里。标“未注明”的，是原文没写清楚。</p></div>
    {filter_panel(active, True, "搜索：Gemini、DeepSeek、免费 GPU、免绑卡…")}
    {home_showcase('./')}
    <div class="grid" data-list data-limit="24">{cards}</div>
    <div id="f-empty" class="empty hidden">没有符合条件的条目，试试清除筛选</div>
    <p class="more-row"><button type="button" id="f-more" class="btn hidden">显示全部 {len(active)} 条</button></p>
  </section>

  <section class="section" id="modules">
    <div class="sec-head"><span class="sec-idx">02 · 模块</span><h2>选择模块</h2>
      <p class="sec-desc">七个资源模块的条数相加 = 免费资源总数 {len(active)}；GitHub 新热门与最近热议单独计数。</p></div>
    <div class="module-list">{''.join(tiles)}</div>
  </section>

  <section class="section" id="latest">
    <div class="sec-head"><span class="sec-idx">03 · 最新</span><h2>最新收录 5 条</h2></div>
    <ol class="latest5">{latest_html}</ol>
  </section>


  <section class="section disclaimer" id="about">
    <div class="sec-head"><span class="sec-idx">04 · 关于与声明</span><h2>关于本站与免责声明</h2></div>
    <div class="disclaimer-card about">
      <p>本站是一个开源的个人维护项目：抓取、过滤、翻译与页面生成的代码都公开在 <a href="{REPO_URL}" rel="noopener">GitHub 仓库 aiym168/aiym168.github.io</a>。置顶条目为编辑推荐，非广告、未收费。</p>
      <p>本站信息来自公开网页、社交媒体与开源社区，由程序每小时自动收集、过滤和翻译，可能存在延迟、过期或错误。</p>
      <p>“未核实”表示本站尚未对照官网确认；任何领取、注册、绑卡、实名操作前，请以官方页面的最新规则为准。本站不收取费用、不代领、不索要账号密码或验证码，谨防冒充本站的诈骗。</p>
      <p>每条资源会显示来源站点、本站收录时间和核实状态。想用程序读取数据？见页脚的 <a href="m/api.html">CLI / API</a>（JSON 接口无需密钥）。已过期和超过 30 天的条目在 <a href="archives/index.html">归档</a>（{len(archived)} 条）。</p>
      <p>发现过期或错误？点击条目上的“报错 / 已过期”，或在 <a href="m/board.html">留言板</a> 告诉我们。</p>
      {render_known_issues(compact=True, prefix="./")}
    </div>
  </section>
  {arch_section}
  {faq_section}
  {site_footer("./", "生成于 " + now.strftime("%Y-%m-%d %H:%M") + " 北京时间")}
</main>
{page_scripts()}
</body></html>"""
    (SITE / "index.html").write_text(page, encoding="utf-8")

    board_path = _board_page(ym)
    url_entries = [("", date, "hourly", "1.0"), ("404.html", date, "yearly", "0.1"), ("m/api.html", date, "weekly", "0.8"),
                   ("m/status.html", date, "hourly", "0.5"), ("feed.xml", date, "hourly", "0.6"), ("api/index.json", date, "hourly", "0.5")]
    if board_path:
        url_entries.append((board_path, date, "daily", "0.7"))
    url_entries.append((octo_path, date, "monthly", "0.6"))
    for pth in deal_paths:
        url_entries.append((pth, date, "hourly" if "/x/" not in pth else "daily", "0.9" if "/x/" not in pth else "0.6"))
    for pth in cat_paths + mod_paths:
        url_entries.append((pth, date, "daily", "0.9"))
    for pth in item_paths:
        url_entries.append((pth, date, "weekly", "0.8"))
    for pth in arch_paths:
        url_entries.append((pth, date, "weekly", "0.5"))
    write_sitemaps(url_entries)
    print(f"wrote landing active={len(active)} archived={len(archived)} today_new={today_new} repos={len(repos)} "
          f"topics={len(topics)} items={len(item_paths)} modules={mod_counts}")


if __name__ == "__main__":
    build()
