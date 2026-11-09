#!/usr/bin/env python3
"""Build multi-page Baidu-SEO site: landing + module pages + items + archives."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SITE = Path(__file__).resolve().parent
DATA = SITE / "data"
AUTO = DATA / "auto"
ARCHIVES = SITE / "archives"
ITEMS = SITE / "item"
CATS = SITE / "c"
MODS = SITE / "m"
CFG_PATH = SITE / "seo_config.json"
TZ = ZoneInfo("Asia/Shanghai")

DEFAULT_CFG = {
    "site_name": "AI大模型免费资源导航",
    "canonical": "https://aiym168.github.io/",
    "baidu_site_verification": "",
    "baidu_push_site": "https://aiym168.github.io",
}

CATEGORIES = [
    "大模型 API 免费额度",
    "AI 产品会员/试用",
    "AI 开发工具与编程助手",
    "云服务/GPU/开发者资源",
    "科技软件/App 限免",
    "其他科技",
]

CAT_SLUG = {
    "大模型 API 免费额度": "damoxing-mianfei-api",
    "AI 产品会员/试用": "ai-huiyuan-shiyong",
    "AI 开发工具与编程助手": "ai-kaifa-gongju",
    "云服务/GPU/开发者资源": "mianfei-gpu-yunfuwu",
    "科技软件/App 限免": "keji-app-xianmian",
    "其他科技": "qita-keji",
}

CAT_INTRO = {
    "大模型 API 免费额度": "汇总大模型免费API、免费GPT、Claude免费、DeepSeek免费额度等公开试用与免费Token信息，方便对照领取入口与规则。",
    "AI 产品会员/试用": "精选 AI 工具免费试用与会员限免资讯，覆盖写作、绘画、语音与办公类产品，附完整说明与来源。",
    "AI 开发工具与编程助手": "面向开发者的 AI 编程助手、Agent 与代码工具导航，适合关注 AI开源项目推荐与效率提升。",
    "云服务/GPU/开发者资源": "免费GPU、云算力试用与开发者资源入口，便于训练、推理与实验前快速筛选。",
    "科技软件/App 限免": "科技软件与 App 限免、开源替代精选，强调 AI / 开发相关。",
    "其他科技": "其他与大模型、AI 工具相关的科技资讯与资源补充阅读。",
}

LONGTAIL = "大模型免费API、免费GPT、Claude免费、DeepSeek免费额度、AI工具免费、免费GPU、GitHub热门项目、最新AI新闻"
KEYWORDS = (
    "AI大模型免费资源,大模型免费API,免费GPT,Claude免费,DeepSeek免费额度,"
    "AI工具免费,免费GPU,GitHub热门项目,AI开源项目推荐,最新AI新闻"
)

MODULES = [
    ("damoxing-mianfei-api", "大模型 API 免费额度", "免费GPT / Claude / DeepSeek 等额度入口", "c/damoxing-mianfei-api.html", "cat", "大模型 API 免费额度"),
    ("ai-huiyuan-shiyong", "AI 产品会员/试用", "AI工具免费试用与会员限免", "c/ai-huiyuan-shiyong.html", "cat", "AI 产品会员/试用"),
    ("ai-kaifa-gongju", "AI 开发工具与编程助手", "编程助手、Agent、开发效率工具", "c/ai-kaifa-gongju.html", "cat", "AI 开发工具与编程助手"),
    ("mianfei-gpu-yunfuwu", "免费GPU / 云服务", "算力试用与开发者云资源", "c/mianfei-gpu-yunfuwu.html", "cat", "云服务/GPU/开发者资源"),
    ("keji-app-xianmian", "科技软件 / App 限免", "限免与开源替代精选", "c/keji-app-xianmian.html", "cat", "科技软件/App 限免"),
    ("github-hot", "GitHub 新热门", "AI / 大模型开源项目推荐", "m/github-hot.html", "github", None),
    ("hot-topics", "最近热议", "最新AI新闻与社区热议", "m/hot-topics.html", "hot", None),
]

def _load_asset(name: str) -> str:
    path = SITE / name
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


CSS = _load_asset("fx.css")
FX_JS = _load_asset("fx.js")
INTERACT_JS = _load_asset("vendor/interact.js")

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
    # migrate any legacy Netlify / project-Pages hosts to the org root site
    legacy = ("netlify.app", "aidamoxing-mianfei", "aiyangmao", "9499758-wq.github.io", "/x-yangmao")
    if any(h in cfg["canonical"] for h in legacy):
        cfg["canonical"] = "https://aiym168.github.io/"
        cfg["baidu_push_site"] = "https://aiym168.github.io"
    return cfg


CFG = load_cfg()
SITE_NAME = CFG["site_name"]
CANONICAL = CFG["canonical"]
META_DESC = (
    f"{SITE_NAME}汇总大模型免费API、免费GPT、Claude免费、DeepSeek免费额度、"
    f"AI工具免费、免费GPU与GitHub热门项目，每日更新。"
)


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def parse_deadline(s: str | None):
    if not s:
        return None
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", s)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=TZ)
    except Exception:
        return None


def is_expired(item: dict, now: datetime) -> bool:
    dl = parse_deadline(item.get("deadline"))
    return bool(dl and dl.date() < now.date())


def norm_url(u: str) -> str:
    return (u or "").strip().rstrip("/")


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"skip {path}: {e}")
        return None


def ym_label(date_str: str) -> str:
    m = re.match(r"(20\d{2})-(\d{2})", date_str or "")
    if m:
        return f"{m.group(1)}年{int(m.group(2))}月最新"
    now = datetime.now(TZ)
    return f"{now.year}年{now.month}月最新"


def item_slug(item: dict) -> str:
    url = item.get("url") or item.get("id") or item.get("title") or ""
    h = hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:10]
    title = item.get("title") or ""
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    ascii_part = re.sub(r"-{2,}", "-", ascii_part)[:36].strip("-")
    cat = CAT_SLUG.get(item.get("category") or "", "item")
    if ascii_part and len(ascii_part) >= 4:
        return f"{ascii_part}-{h}"
    return f"{cat}-{h}"


SCOPE_BLOCK = (
    "stock market", "stock price", "trading bot", "forex", "bitcoin", "cryptocurrency", "crypto token", "airdrop", "nft mint", "coupon", "cashback",
    "credit card", "loan", "金融", "股票", "炒股", "比特币", "加密货币", "空投", "优惠券", "信用卡", "贷款", "返现", "银行",
)


def out_of_scope(item: dict) -> bool:
    """Content scope guard: only LLM / AI / tech freebies."""
    text = " ".join(str(item.get(k) or "") for k in ("title", "original_title", "summary")).lower()
    return any(b in text for b in SCOPE_BLOCK)


def load_pinned() -> list[dict]:
    """Pinned items from data/pinned.json — always rendered first, never touched by fetchers."""
    d = load_json(DATA / "pinned.json") if (DATA / "pinned.json").exists() else None
    out = []
    for it in (d or {}).get("items") or []:
        if it.get("title") and it.get("url"):
            it = dict(it, pinned=True)
            it.setdefault("category", "其他科技")
            it["_slug"] = item_slug(it)
            it["_path"] = f"item/{it['_slug']}.html"
            out.append(it)
    return out


def pinned_block(pins: list[dict], prefix: str = "") -> str:
    if not pins:
        return ""
    cards = []
    for it in pins:
        feats = "".join(f"<li>{esc(f)}</li>" for f in it.get("features") or [])
        start = it.get("start_url") or it.get("url")
        cards.append(f"""<article class="pin-card">
  <div class="pin-main">
  <div class="pin-head"><span class="pin-badge">📌 {esc(it.get("badge") or "置顶")}</span><span class="badge">{esc(it.get("category") or "")}</span></div>
  <h2 class="pin-title"><a href="{esc(start)}" target="_blank" rel="noopener">{esc(it.get("title"))}</a></h2>
  <p class="pin-sum">{esc(it.get("summary") or "")}</p>
  {f'<div class="how"><strong>怎么开始：</strong>{esc(it.get("how"))}</div>' if it.get("how") else ''}
  <div class="pin-actions"><a class="btn primary pin-btn" href="{esc(start)}" target="_blank" rel="noopener">立即免费领取 →</a><a class="btn" href="{prefix}{esc(it.get("_path") or "")}">查看详情</a></div>
  </div>
  {f'<ul class="pin-feats">{feats}</ul>' if feats else ''}
</article>""")
    return f'<section class="pinned-sec" aria-label="置顶推荐">{"".join(cards)}</section>'


PIN_CSS = ""  # pinned styles now live in fx.css


def collect_deal_items():
    now = datetime.now(TZ)
    items = []
    latest_label = ""
    latest_date = ""
    for f in sorted(DATA.glob("????-??-??.json"), reverse=True):
        d = load_json(f)
        if not d:
            continue
        if not latest_date:
            latest_date = d.get("date") or f.stem
            latest_label = d.get("updated_at_label") or ""
        for it in d.get("items") or []:
            it = dict(it)
            it.setdefault("source", "X")
            items.append(it)
    for f in sorted(AUTO.glob("????-??-??.json"), reverse=True):
        d = load_json(f)
        if not d:
            continue
        if not latest_label:
            latest_label = d.get("updated_at_label") or ""
        if not latest_date:
            latest_date = d.get("date") or f.stem
        for it in d.get("items") or []:
            it = dict(it)
            it.setdefault("source", "auto")
            items.append(it)
    seen = set()
    uniq = []
    dead = {norm_url(u) for u in ((load_json(DATA / "link_health.json") or {}).get("dead") or [])} if (DATA / "link_health.json").exists() else set()
    for it in items:
        u = norm_url(it.get("url") or "")
        if not u or u in seen or is_expired(it, now) or u in dead or out_of_scope(it):
            continue
        if (it.get("category") or "其他科技") not in CATEGORIES:
            it["category"] = "其他科技"
        it["_slug"] = item_slug(it)
        it["_path"] = f"item/{it['_slug']}.html"
        seen.add(u)
        uniq.append(it)
    if not latest_date:
        latest_date = now.strftime("%Y-%m-%d")
    if not latest_label:
        latest_label = now.strftime("%Y-%m-%d %H:%M Asia/Shanghai")
    return uniq, latest_date, latest_label


def load_section(name: str):
    path = AUTO / name
    d = load_json(path) if path.exists() else None
    if not d:
        return [], ""
    return d.get("items") or [], d.get("updated_at_label") or ""


def list_archive_dates():
    dates = set(f.stem for f in DATA.glob("????-??-??.json"))
    dates |= set(f.stem for f in AUTO.glob("????-??-??.json"))
    return sorted(dates, reverse=True)


def items_for_date(day: str):
    now = datetime.now(TZ)
    items = []
    for base in (DATA, AUTO):
        p = base / f"{day}.json"
        if not p.exists():
            continue
        d = load_json(p) or {}
        for it in d.get("items") or []:
            it = dict(it)
            if is_expired(it, now):
                continue
            if (it.get("category") or "其他科技") not in CATEGORIES:
                it["category"] = "其他科技"
            it["_slug"] = item_slug(it)
            it["_path"] = f"item/{it['_slug']}.html"
            items.append(it)
    seen = set()
    uniq = []
    for it in items:
        u = norm_url(it.get("url") or "")
        if not u or u in seen:
            continue
        seen.add(u)
        uniq.append(it)
    return uniq


def json_ld(obj) -> str:
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "</script>"


def head_block(title, description, canonical, og_title=None, pubdate=None, extra_ld=None):
    og_title = og_title or title
    verify = (CFG.get("baidu_site_verification") or "").strip()
    verify_meta = (
        f'<meta name="baidu-site-verification" content="{esc(verify)}" />'
        if verify
        else "<!-- VERIFY_BAIDU / seo_config.baidu_site_verification -->"
    )
    pub_meta = ""
    if pubdate:
        pub_meta = (
            f'<meta property="og:article:published_time" content="{esc(pubdate)}" />\n'
            f'<meta name="pubdate" content="{esc(pubdate)}" />'
        )
    ld_html = "\n".join(json_ld(x) for x in (extra_ld or []))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5" />
<meta name="color-scheme" content="dark" />
<meta name="theme-color" content="#02040a" />
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
{pub_meta}
<style>
{CSS}
{PIN_CSS}
</style>
{ld_html}
</head>
"""



NAV_SHORT = {
    "damoxing-mianfei-api": "免费API", "ai-huiyuan-shiyong": "会员试用", "ai-kaifa-gongju": "开发工具",
    "mianfei-gpu-yunfuwu": "免费GPU", "keji-app-xianmian": "App限免", "github-hot": "GitHub热门", "hot-topics": "热议",
}

ICONS = {
    "damoxing-mianfei-api": '<path d="M12 2a4 4 0 0 1 4 4v1a3 3 0 0 1 3 3v1a3 3 0 0 1-1 5.2V17a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4v-.8A3 3 0 0 1 5 11v-1a3 3 0 0 1 3-3V6a4 4 0 0 1 4-4z"/><path d="M12 6v14M9 10h6M9 14h6"/>',
    "ai-huiyuan-shiyong": '<path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8L3.5 9.2l5.9-.9z"/>',
    "ai-kaifa-gongju": '<path d="M8 8l-5 4 5 4M16 8l5 4-5 4M14 4l-4 16"/>',
    "mianfei-gpu-yunfuwu": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "keji-app-xianmian": '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 18h4M9 9l2 2 4-4"/>',
    "github-hot": '<path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/>',
    "hot-topics": '<path d="M12 22c4.4 0 7-2.9 7-7 0-4-3-6-4-10-2 2-2.5 4-2.5 4S10 6 9 3C7 6 5 9 5 15c0 4.1 2.6 7 7 7z"/><path d="M12 22c-1.7 0-3-1.3-3-3.2 0-2 1.5-3 3-5 1.5 2 3 3 3 5 0 1.9-1.3 3.2-3 3.2z"/>',
}


def icon_svg(mid: str) -> str:
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS.get(mid, ICONS["ai-kaifa-gongju"])}</svg>'


def brain_block(vendor_prefix: str = "vendor/", tags=None, nodes: int = 4200) -> str:
    tags = tags or [("免费API", ""), ("GPU 算力", ""), ("Agent", ""), ("开源", "")]
    tag_html = "".join(
        f'<span class="hud-tag {c}">{esc(t)}{f"<b>{esc(n)}</b>" if n != "" else ""}</span>'
        for c, (t, n) in zip("abcd", tags)
    )
    return f"""
<div class="brain-stage" aria-hidden="true">
  <span class="ring r3"></span><span class="ring r1"></span><span class="ring r2"></span>
  <span class="hud-corner tl"></span><span class="hud-corner tr"></span><span class="hud-corner bl"></span><span class="hud-corner br"></span>
  {tag_html}
  <div id="brain-hero" data-vendor="{esc(vendor_prefix)}" data-nodes="{nodes}"></div>
  <span class="brain-caption">Neural Graph · WebGL · Live</span>
</div>
"""


def brain_loader_script(vendor_prefix: str = "vendor/") -> str:
    # classic script; resolves ES module from vendored path
    return f'<script src="{esc(vendor_prefix)}brain-loader.js" defer></script>'


def topnav(prefix="./"):
    links = "".join(
        f'<a href="{prefix}{esc(href)}" title="{esc(title)}">{esc(NAV_SHORT.get(mid, title))}</a>'
        for mid, title, _, href, _, _ in MODULES
    )
    links += f'<a href="{prefix}m/board.html" title="匿名留言板 · 星际信号站">留言板</a>'
    links += f'<a href="{prefix}m/status.html" title="更新动态">更新动态</a>'
    links += f'<a class="cta" href="{prefix}m/api.html" title="CLI / API">CLI / API</a>'
    return f"""
<header class="topnav">
  <a class="brand-mini" href="{prefix}"><span class="mark"></span><span class="txt">{esc(SITE_NAME)}</span></a>
  <nav class="navlinks" aria-label="模块导航">{links}</nav>
</header>"""


def site_footer(prefix="./", extra="") -> str:
    return f"""<footer>
  <div><span class="foot-brand">{esc(SITE_NAME)}</span>{(" · " + esc(extra)) if extra else ""}<br/>每小时自动更新</div>
  <div><a href="{prefix}m/api.html">CLI / API</a> · <a href="{prefix}m/status.html">更新动态</a> · <a href="{prefix}feed.xml">RSS</a> · <a href="{prefix}sitemap.xml">网站地图</a> · <kbd>Ctrl</kbd>+<kbd>K</kbd> 搜索</div>
</footer>"""


def mod_hero(eyebrow: str, title: str, lead: str, stats: str, crumbs: str, vendor_prefix: str, tags=None) -> str:
    return f"""<header class="hero-xl compact hero-brain">
  <div class="hero-xl-inner">
    <div class="hero-copy">
      <div class="crumbs">{crumbs}</div>
      <div class="eyebrow"><i class="live-dot"></i> {esc(eyebrow)} <span class="sep">/</span> <span data-clock>--:--:--</span></div>
      <h1 class="hero-title"><span class="kl">{esc(title)}</span></h1>
      <p class="lead">{esc(lead)}</p>
      <div class="stats">{stats}<div class="pill live">下次更新 <b data-next>--:--</b></div></div>
    </div>
    {brain_block(vendor_prefix, tags, 2800)}
  </div>
</header>
{brain_loader_script(vendor_prefix)}"""


def orig_html(main: str = "", original: str = "") -> str:
    return ""



def card_deal(item, prefix=""):
    deadline = item.get("deadline")
    deadline_html = f'<span class="dl-tag">截止 {esc(deadline)}</span>' if deadline else ""
    how = item.get("how") or ""
    how_html = f'<div class="how"><strong>怎么领：</strong>{esc(how)}</div>' if how else ""
    url = item.get("url") or ""
    title = item.get("title") or ""
    summary = item.get("summary") or ""
    cat = item.get("category") or ""
    source = item.get("source") or "未知"
    slug_path = prefix + (item.get("_path") or f"item/{item_slug(item)}.html")
    author = item.get("author") or ""
    posted = item.get("posted_at") or ""
    author_html = f'<div class="meta author">@{esc(author)} · {esc(posted)}</div>' if (author or posted) else ""
    blob = " ".join([title, summary, how, author, url, cat, source])
    return f"""
<article class="card" data-text="{esc(blob)}">
  <div class="badgerow"><span class="badge">{esc(cat)}</span><span class="src-tag">来源 {esc(source)}</span>{deadline_html}</div>
  <h3 class="title"><a href="{esc(slug_path)}">{esc(title)}</a></h3>
  {orig_html(title, item.get("original_title") or "")}
  <p class="summary">{esc(summary)}</p>
  {orig_html(summary, item.get("original_summary") or "")}
  {how_html}{author_html}
  <div class="linkrow"><a href="{esc(slug_path)}">详情与领取方法</a> · <a class="fulllink" href="{esc(url)}" target="_blank" rel="noopener noreferrer">来源链接</a> · <a href="#" class="copy-link" data-copy-link="{esc(CANONICAL + (item.get("_path") or slug_path.lstrip('./')))}">复制链接</a></div>
</article>"""


def card_repo(item):
    url = item.get("url") or ""
    title = item.get("title") or item.get("name") or ""
    summary = item.get("summary") or ""
    name = item.get("name") or ""
    return f"""
<article class="card" data-text="{esc(title + ' ' + summary + ' ' + name)}">
  <div class="badgerow"><span class="badge">GitHub 新热门</span><span class="src-tag">来源 GitHub</span></div>
  <h3 class="title">{esc(title)}</h3>
  {orig_html(title, item.get("original_title") or name)}
  <p class="summary">{esc(summary)}</p>
  {orig_html(summary, item.get("original_summary") or "")}
  <div class="meta">⭐ {esc(item.get("stars") or 0)} · {esc(item.get("language") or "")} · {esc(item.get("created_at") or "")}</div>
  <div class="meta author">仓库：{esc(name)}</div>
  <div class="linkrow"><a class="fulllink" href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(url)}</a></div>
</article>"""


def card_hot(item):
    url = item.get("url") or ""
    title = item.get("title") or ""
    summary = item.get("summary") or ""
    return f"""
<article class="card" data-text="{esc(title + ' ' + summary)}">
  <div class="badgerow"><span class="badge">最近热议</span><span class="src-tag">来源 {esc(item.get("source") or "")}</span></div>
  <h3 class="title">{esc(title)}</h3>
  {orig_html(title, item.get("original_title") or "")}
  <p class="summary">{esc(summary)}</p>
  {orig_html(summary, item.get("original_summary") or "")}
  <div class="meta">热度：{esc(item.get("heat") or "")}</div>
  <div class="linkrow"><a class="fulllink" href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(url)}</a></div>
</article>"""


SEARCH_JS = r"""
(function(){
  const q=document.getElementById('q'); if(!q) return;
  const cards=[...document.querySelectorAll('.card')];
  const empty=document.getElementById('empty');
  q.addEventListener('input',()=>{
    const t=(q.value||'').trim().toLowerCase();
    let n=0;
    cards.forEach(c=>{
      const ok=!t||(c.getAttribute('data-text')||'').toLowerCase().includes(t);
      c.classList.toggle('hidden',!ok); if(ok) n++;
    });
    if(empty) empty.classList.toggle('hidden', n>0 || !cards.length);
  });
})();
"""

SITE_JS = SEARCH_JS + "\n" + FX_JS + "\n" + INTERACT_JS



def write_sitemaps(urls):
    now = datetime.now(TZ).strftime("%Y-%m-%d")
    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    abs_urls = []
    for path, lastmod, freq, pri in urls:
        loc = CANONICAL if path in ("", "/") else f"{CANONICAL}{path.lstrip('/')}"
        abs_urls.append(loc)
        body.append(
            f"  <url><loc>{esc(loc)}</loc><lastmod>{esc(lastmod or now)}</lastmod>"
            f"<changefreq>{esc(freq)}</changefreq><priority>{esc(pri)}</priority></url>"
        )
    body.append("</urlset>")
    (SITE / "sitemap.xml").write_text("\n".join(body) + "\n", encoding="utf-8")
    (SITE / "sitemap.txt").write_text("\n".join(abs_urls) + "\n", encoding="utf-8")
    (SITE / "sitemap_index.xml").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>{CANONICAL}sitemap.xml</loc><lastmod>{now}</lastmod></sitemap>
  <sitemap><loc>{CANONICAL}sitemap.txt</loc><lastmod>{now}</lastmod></sitemap>
</sitemapindex>
""",
        encoding="utf-8",
    )
    (SITE / "robots.txt").write_text(
        f"""User-agent: *
Allow: /
Disallow: /data/
Disallow: /engine/
Disallow: /board/
User-agent: Baiduspider
Allow: /
Disallow: /data/
Disallow: /engine/
Disallow: /board/
User-agent: Baiduspider-render
Allow: /
Disallow: /data/
Disallow: /engine/
Disallow: /board/
Sitemap: {CANONICAL}sitemap_index.xml
Sitemap: {CANONICAL}sitemap.xml
Sitemap: {CANONICAL}sitemap.txt
""",
        encoding="utf-8",
    )


def related_items(item, all_items, n=6):
    cat = item.get("category")
    same = [x for x in all_items if x is not item and x.get("category") == cat]
    others = [x for x in all_items if x is not item and x.get("category") != cat]
    out = same[:n]
    if len(out) < n:
        out += others[: n - len(out)]
    return out


def write_item_pages(all_items, date):
    ITEMS.mkdir(parents=True, exist_ok=True)
    paths = []
    for it in all_items:
        slug = it["_slug"]
        title_zh = it.get("title") or "资源详情"
        page_title = f"{title_zh} - 免费领取方法 | {SITE_NAME}"
        desc = (it.get("summary") or title_zh)[:150]
        canonical = f"{CANONICAL}item/{slug}.html"
        cat = it.get("category") or "其他科技"
        cat_slug = CAT_SLUG.get(cat, "qita-keji")
        pub = it.get("posted_at") or date
        rel = related_items(it, all_items)
        rel_html = "".join(f'<a href="{esc(r["_slug"])}.html">{esc(r.get("title") or "")}</a><br/>' for r in rel)
        how = it.get("how") or "打开来源链接，按页面说明领取或试用；参与前请自行核实。"
        ld = [
            {"@context": "https://schema.org", "@type": "Article", "headline": title_zh, "description": desc,
             "datePublished": str(pub), "dateModified": date, "mainEntityOfPage": canonical,
             "author": {"@type": "Organization", "name": SITE_NAME}},
            {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "首页", "item": CANONICAL},
                {"@type": "ListItem", "position": 2, "name": cat, "item": f"{CANONICAL}c/{cat_slug}.html"},
                {"@type": "ListItem", "position": 3, "name": title_zh, "item": canonical},
            ]},
        ]
        page = f"""{head_block(page_title, desc, canonical, title_zh, pubdate=str(pub), extra_ld=ld)}
<body>
<div class="fx-aurora" aria-hidden="true"></div>
<div class="fx-grid" aria-hidden="true"></div>
<div class="fx-noise" aria-hidden="true"></div>
<div class="fx-scan" aria-hidden="true"></div>
<div class="fx-spot" aria-hidden="true"></div>
<canvas id="fx-particles" aria-hidden="true"></canvas>
<div class="wrap">
  {topnav("../")}
  <div class="crumbs"><a href="../">首页</a> › <a href="../c/{esc(cat_slug)}.html">{esc(cat)}</a> › {esc(title_zh)}</div>
  <header class="hero">
    <div class="eyebrow"><i class="live-dot"></i> DETAIL</div>
    <h1>{esc(title_zh)}</h1>
    <p class="lead">{esc(cat)} · 来源 {esc(it.get("source") or "公开网页")}</p>
  </header>
  <section class="panel-box intro">
    <h2>资源说明</h2>
    <p>{esc(it.get("summary") or title_zh)}</p>
    {orig_html(it.get("summary") or "", it.get("original_summary") or "")}
    <div class="how"><strong>免费领取方法：</strong>{esc(how)}</div>
    <p style="margin-top:14px"><a class="btn primary" href="{esc(it.get("url") or "#")}" target="_blank" rel="noopener noreferrer">打开原帖 / 官网 →</a>
    <a class="btn" href="../c/{esc(cat_slug)}.html">同分类更多</a></p>
  </section>
  <section class="panel-box"><h2>相关推荐</h2>{rel_html or "暂无"}</section>
  {site_footer("../")}
</div>
<script>{FX_JS}
{INTERACT_JS}</script>
</body></html>"""
        (ITEMS / f"{slug}.html").write_text(page, encoding="utf-8")
        paths.append(f"item/{slug}.html")
    return paths


def write_category_pages(all_items, date, ym):
    CATS.mkdir(parents=True, exist_ok=True)
    paths = []
    for cat in CATEGORIES:
        slug = CAT_SLUG[cat]
        cat_items = [it for it in all_items if it.get("category") == cat]
        page_title = f"{cat} | {SITE_NAME} · {ym}"
        intro = CAT_INTRO[cat]
        canonical = f"{CANONICAL}c/{slug}.html"
        cards = "\n".join(card_deal(it, prefix="../") for it in cat_items) or '<div class="empty">本分类暂无条目</div>'
        ld = [
            {"@context": "https://schema.org", "@type": "CollectionPage", "name": page_title, "url": canonical, "description": intro},
            {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "url": f"{CANONICAL}{it['_path']}", "name": it.get("title") or ""}
                for i, it in enumerate(cat_items[:50])
            ]},
        ]
        page = f"""{head_block(page_title, intro, canonical, extra_ld=ld)}
<body>
<div class="fx-aurora" aria-hidden="true"></div>
<div class="fx-grid" aria-hidden="true"></div>
<div class="fx-noise" aria-hidden="true"></div>
<div class="fx-scan" aria-hidden="true"></div>
<div class="fx-spot" aria-hidden="true"></div>
<canvas id="fx-particles" aria-hidden="true"></canvas>
{topnav("../")}
{mod_hero("MODULE", cat, intro, f'<div class="pill">条目 <b data-count="{len(cat_items)}">{len(cat_items)}</b></div><div class="pill">更新 <b>{esc(date)}</b></div>', f'<a href="../">首页</a> › {esc(cat)}', "../vendor/", [(cat.split(" ")[0], len(cat_items)), ("免费", ""), ("实时", ""), ("中文", "")])}
<div class="wrap">
  <div class="toolbar"><input id="q" type="search" placeholder="在本模块内搜索…" autocomplete="off" /></div>
  <div class="grid">{cards}</div>
  <div id="empty" class="empty hidden">没有匹配条目</div>
  {site_footer("../", cat)}
</div>
<script>{SITE_JS}</script>
</body></html>"""
        (CATS / f"{slug}.html").write_text(page, encoding="utf-8")
        paths.append(f"c/{slug}.html")
    return paths


def write_module_special(repos, topics, date, ym):
    MODS.mkdir(parents=True, exist_ok=True)
    paths = []
    # github
    cards = "\n".join(card_repo(r) for r in repos) or '<div class="empty">暂无</div>'
    page = f"""{head_block(f"GitHub 新热门 | {SITE_NAME} · {ym}", f"{SITE_NAME} GitHub热门项目与AI开源项目推荐", f"{CANONICAL}m/github-hot.html")}
<body>
<div class="fx-aurora" aria-hidden="true"></div>
<div class="fx-grid" aria-hidden="true"></div>
<div class="fx-noise" aria-hidden="true"></div>
<div class="fx-scan" aria-hidden="true"></div>
<div class="fx-spot" aria-hidden="true"></div>
<canvas id="fx-particles" aria-hidden="true"></canvas>
{topnav("../")}
{mod_hero("GITHUB", "GitHub 新热门", "近 7–14 天创建的 AI / 大模型 / Agent 开源项目，按星标整理，完整中文说明。", f'<div class="pill">项目 <b data-count="{len(repos)}">{len(repos)}</b></div><div class="pill">更新 <b>{esc(date)}</b></div>', '<a href="../">首页</a> › GitHub 新热门', "../vendor/", [("开源项目", len(repos)), ("Agent", ""), ("LLM", ""), ("Stars", "")])}
<div class="wrap">
  <div class="toolbar"><input id="q" type="search" placeholder="搜索仓库 / 简介…" autocomplete="off" /></div>
  <div class="grid">{cards}</div>
  <div id="empty" class="empty hidden">没有匹配条目</div>
  {site_footer("../")}
</div>
<script>{SITE_JS}</script>
</body></html>"""
    (MODS / "github-hot.html").write_text(page, encoding="utf-8")
    paths.append("m/github-hot.html")

    cards = "\n".join(card_hot(t) for t in topics) or '<div class="empty">暂无</div>'
    page = f"""{head_block(f"最近热议 / 最新AI新闻 | {SITE_NAME} · {ym}", f"{SITE_NAME}最新AI新闻与社区热议", f"{CANONICAL}m/hot-topics.html")}
<body>
<div class="fx-aurora" aria-hidden="true"></div>
<div class="fx-grid" aria-hidden="true"></div>
<div class="fx-noise" aria-hidden="true"></div>
<div class="fx-scan" aria-hidden="true"></div>
<div class="fx-spot" aria-hidden="true"></div>
<canvas id="fx-particles" aria-hidden="true"></canvas>
{topnav("../")}
{mod_hero("PULSE", "最近热议", "Hacker News / V2EX / X 等渠道的 AI 与科技热议，标题与摘要已译为中文。", f'<div class="pill">话题 <b data-count="{len(topics)}">{len(topics)}</b></div><div class="pill">更新 <b>{esc(date)}</b></div>', '<a href="../">首页</a> › 最近热议', "../vendor/", [("热议", len(topics)), ("HN", ""), ("V2EX", ""), ("X", "")])}
<div class="wrap">
  <div class="toolbar"><input id="q" type="search" placeholder="搜索热议…" autocomplete="off" /></div>
  <div class="grid">{cards}</div>
  <div id="empty" class="empty hidden">没有匹配条目</div>
  {site_footer("../")}
</div>
<script>{SITE_JS}</script>
</body></html>"""
    (MODS / "hot-topics.html").write_text(page, encoding="utf-8")
    paths.append("m/hot-topics.html")
    return paths


def write_archive_page(day, items, all_dates):
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    ym = ym_label(day)
    title = f"{SITE_NAME} · {day} 存档 · {ym}"
    desc = f"{SITE_NAME} {day} 日归档"
    canonical = f"{CANONICAL}archives/{day}.html"
    sections = []
    for c in CATEGORIES:
        cat_items = [it for it in items if it.get("category") == c]
        if not cat_items:
            continue
        cards = "\n".join(card_deal(it, prefix="../") for it in cat_items)
        sections.append(f'<section class="section"><h2>{esc(c)} <span>({len(cat_items)})</span></h2><div class="grid">{cards}</div></section>')
    arch = "".join(f'<a class="arch {"current" if d==day else ""}" href="{esc(d)}.html">{esc(d)}</a>' for d in all_dates[:60])
    page = f"""{head_block(title, desc, canonical)}
<body>
<div class="fx-aurora" aria-hidden="true"></div>
<div class="fx-grid" aria-hidden="true"></div>
<div class="fx-noise" aria-hidden="true"></div>
<div class="fx-scan" aria-hidden="true"></div>
<div class="fx-spot" aria-hidden="true"></div>
<canvas id="fx-particles" aria-hidden="true"></canvas>
<div class="wrap">
  {topnav("../")}
  <div class="crumbs"><a href="../">首页</a> › 日归档 › {esc(day)}</div>
  <header class="hero"><div class="eyebrow"><i class="live-dot"></i> ARCHIVE</div><h1>{esc(day)}</h1>
  <p class="lead">{esc(ym)} · {len(items)} 条</p></header>
  {''.join(sections) or '<div class="empty">暂无</div>'}
  <div class="panel-box"><h2>更多日期</h2>{arch}</div>
  {site_footer("../")}
</div>
<script>{FX_JS}
{INTERACT_JS}</script>
</body></html>"""
    (ARCHIVES / f"{day}.html").write_text(page, encoding="utf-8")


def _api_item(it: dict) -> dict:
    return {
        "id": it.get("id") or item_slug(it),
        "title": it.get("title") or "",
        "summary": it.get("summary") or "",
        "url": it.get("url") or "",
        "category": it.get("category") or "",
        "source": it.get("source") or "",
        "how": it.get("how") or "",
        "author": it.get("author") or "",
        "deadline": it.get("deadline"),
        "posted_at": it.get("posted_at") or "",
        "engagement": it.get("engagement") or {},
        "path": it.get("_path") or (f"item/{item_slug(it)}.html" if it.get("title") else ""),
    }


def _api_repo(it: dict) -> dict:
    return {
        "id": it.get("id") or "",
        "title": it.get("title") or it.get("name") or "",
        "summary": it.get("summary") or it.get("description") or "",
        "url": it.get("url") or "",
        "source": it.get("source") or "GitHub",
        "stars": it.get("stars") or (it.get("engagement") or {}).get("stars"),
        "language": it.get("language") or "",
        "heat": it.get("heat") or "",
    }


def _api_topic(it: dict) -> dict:
    return {
        "id": it.get("id") or "",
        "title": it.get("title") or "",
        "summary": it.get("summary") or "",
        "url": it.get("url") or "",
        "source": it.get("source") or "",
        "heat": it.get("heat") or "",
        "points": it.get("points") or 0,
    }


def write_api_and_feed(items, repos, topics, date, updated, pins=None):
    """Static JSON API + RSS for CLI / curl consumers."""
    api = SITE / "api"
    api.mkdir(parents=True, exist_ok=True)
    now_label = datetime.now(TZ).strftime("%Y-%m-%d %H:%M Asia/Shanghai")
    version = "1.0.0"

    deals = [_api_item(it) for it in items]
    repo_items = [_api_repo(it) for it in repos]
    hot_items = [_api_topic(it) for it in topics]

    modules_payload = {}
    for mid, title, desc, href, kind, cat in MODULES:
        if kind == "cat":
            subset = [_api_item(it) for it in items if it.get("category") == cat]
        elif kind == "github":
            subset = repo_items
        else:
            subset = hot_items
        modules_payload[mid] = {
            "id": mid,
            "title": title,
            "description": desc,
            "href": href,
            "count": len(subset),
            "items": subset,
        }
        (api / f"{mid}.json").write_text(
            json.dumps(modules_payload[mid], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    pinned_api = [dict(_api_item(p), pinned=True, features=p.get("features") or [], start_url=p.get("start_url") or p.get("url")) for p in (pins or [])]
    for d_ in deals:
        d_["pinned"] = False
    latest = {
        "updated_at_label": updated or now_label,
        "generated_at_label": now_label,
        "date": date,
        "count": len(pinned_api) + len(deals),
        "pinned_count": len(pinned_api),
        "items": pinned_api + deals,
    }
    (api / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (api / "github-hot.json").write_text(
        json.dumps({"updated_at_label": now_label, "count": len(repo_items), "items": repo_items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (api / "hot.json").write_text(
        json.dumps({"updated_at_label": now_label, "count": len(hot_items), "items": hot_items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    meta = {
        "name": SITE_NAME,
        "canonical": CANONICAL,
        "version": version,
        "updated_at_label": updated or now_label,
        "generated_at_label": now_label,
        "date": date,
        "counts": {
            "deals": len(deals),
            "github_hot": len(repo_items),
            "hot": len(hot_items),
            "modules": {mid: modules_payload[mid]["count"] for mid, *_rest in MODULES},
        },
        "cli": {
            "npx": "npx github:aiym168/aiym168.github.io",
            "curl": f"curl -fsSL {CANONICAL}cli.sh | bash -s -- list",
        },
    }
    (api / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    endpoints = {
        "canonical": CANONICAL,
        "endpoints": [
            {"path": "api/index.json", "desc": "本接口目录"},
            {"path": "api/meta.json", "desc": "站点元信息与计数"},
            {"path": "api/latest.json", "desc": "全部免费资源条目"},
            {"path": "api/github-hot.json", "desc": "GitHub 新热门"},
            {"path": "api/hot.json", "desc": "最近热议"},
            {"path": "feed.xml", "desc": "RSS 订阅"},
        ]
        + [{"path": f"api/{mid}.json", "desc": title} for mid, title, *_ in MODULES],
    }
    (api / "index.json").write_text(json.dumps(endpoints, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # RSS
    def xml_esc(s: str) -> str:
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    items_xml = []
    for it in (deals + hot_items)[:60]:
        link = it.get("url") or (CANONICAL + (it.get("path") or ""))
        items_xml.append(
            "  <item>\n"
            f"    <title>{xml_esc(it.get('title') or '')}</title>\n"
            f"    <link>{xml_esc(link)}</link>\n"
            f"    <guid isPermaLink=\"false\">{xml_esc(str(it.get('id') or link))}</guid>\n"
            f"    <description>{xml_esc(it.get('summary') or '')}</description>\n"
            f"    <category>{xml_esc(it.get('category') or it.get('source') or '')}</category>\n"
            "  </item>"
        )
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n<channel>\n'
        f"<title>{xml_esc(SITE_NAME)}</title>\n"
        f"<link>{xml_esc(CANONICAL)}</link>\n"
        f"<description>{xml_esc(META_DESC)}</description>\n"
        f"<language>zh-CN</language>\n"
        f"<lastBuildDate>{xml_esc(now_label)}</lastBuildDate>\n"
        + "\n".join(items_xml)
        + "\n</channel>\n</rss>\n"
    )
    (SITE / "feed.xml").write_text(feed, encoding="utf-8")
    print(f"[api] wrote api/*.json feed.xml deals={len(deals)} repos={len(repo_items)} hot={len(hot_items)}")


def write_api_docs_page(date, ym):
    """Stylish CLI / API docs page."""
    MODS.mkdir(parents=True, exist_ok=True)
    canonical = f"{CANONICAL}m/api.html"
    intro = (
        f"{SITE_NAME} 提供零依赖静态 JSON API 与命令行入口，方便开发者用 curl / npx 快速拉取大模型免费资源、"
        f"GitHub 热门与社区热议。数据每小时自动更新，无需密钥。"
    )
    code_npx = "npx github:aiym168/aiym168.github.io list\nnpx github:aiym168/aiym168.github.io search 免费GPU\nnpx github:aiym168/aiym168.github.io hot --limit 10"
    code_curl = f"curl -fsSL {CANONICAL}cli.sh | bash -s -- list\ncurl -fsSL {CANONICAL}api/latest.json | head\ncurl -fsSL {CANONICAL}api/meta.json"
    code_api = f"{CANONICAL}api/index.json\n{CANONICAL}api/latest.json\n{CANONICAL}api/github-hot.json\n{CANONICAL}api/hot.json\n{CANONICAL}api/meta.json\n{CANONICAL}feed.xml"
    endpoints_rows = "".join(
        f"<tr><td><code>api/{esc(mid)}.json</code></td><td>{esc(title)}</td></tr>"
        for mid, title, *_ in MODULES
    )
    page = f"""{head_block(f"CLI / API · {SITE_NAME}", intro, canonical)}
<body>
<div class="fx-aurora" aria-hidden="true"></div>
<div class="fx-grid" aria-hidden="true"></div>
<div class="fx-noise" aria-hidden="true"></div>
<div class="fx-scan" aria-hidden="true"></div>
<div class="fx-spot" aria-hidden="true"></div>
<canvas id="fx-particles" aria-hidden="true"></canvas>
<div class="wrap">
  {topnav("../")}
  <header class="hero">
    <div class="eyebrow"><i class="live-dot"></i> DEVELOPER ACCESS</div>
    <h1 class="hero-title">CLI / API</h1>
    <p class="lead">{esc(intro)}</p>
  </header>

  <section class="section">
    <h2>一分钟上手</h2>
    <p class="sec-desc">无需注册、无需 Token。推荐用 npx（需本机 Node）或 curl 管道脚本。</p>
    <div class="term-block">
      <div class="term-bar"><span></span><span></span><span></span><em>npx</em>
        <button type="button" class="copy-btn" data-copy="{esc(code_npx)}">复制</button></div>
      <pre><code>{esc(code_npx)}</code></pre>
    </div>
    <div class="term-block">
      <div class="term-bar"><span></span><span></span><span></span><em>curl | bash</em>
        <button type="button" class="copy-btn" data-copy="{esc(code_curl)}">复制</button></div>
      <pre><code>{esc(code_curl)}</code></pre>
    </div>
  </section>

  <section class="section">
    <h2>静态 JSON API</h2>
    <p class="sec-desc">GitHub Pages 默认允许跨域读取。每次站点构建都会重新生成。</p>
    <div class="term-block">
      <div class="term-bar"><span></span><span></span><span></span><em>endpoints</em>
        <button type="button" class="copy-btn" data-copy="{esc(code_api)}">复制</button></div>
      <pre><code>{esc(code_api)}</code></pre>
    </div>
    <div class="panel-box">
      <table class="api-table">
        <thead><tr><th>路径</th><th>说明</th></tr></thead>
        <tbody>
          <tr><td><code>api/index.json</code></td><td>接口目录</td></tr>
          <tr><td><code>api/meta.json</code></td><td>更新时间、计数、版本</td></tr>
          <tr><td><code>api/latest.json</code></td><td>全部免费资源</td></tr>
          <tr><td><code>api/github-hot.json</code></td><td>GitHub 新热门</td></tr>
          <tr><td><code>api/hot.json</code></td><td>最近热议</td></tr>
          <tr><td><code>feed.xml</code></td><td>RSS 2.0</td></tr>
          {endpoints_rows}
        </tbody>
      </table>
    </div>
  </section>

  <section class="section">
    <h2>CLI 命令</h2>
    <div class="panel-box">
      <ul class="api-cmds">
        <li><code>list [module]</code> — 列出模块或全部资源</li>
        <li><code>search &lt;kw&gt;</code> — 按关键词搜索</li>
        <li><code>hot</code> — 最近热议</li>
        <li><code>github</code> — GitHub 新热门</li>
        <li><code>open &lt;id&gt;</code> — 打开条目链接</li>
        <li><code>json</code> — 输出原始 JSON</li>
        <li><code>--limit N</code> — 限制条数</li>
      </ul>
    </div>
  </section>

  {site_footer("../", date)}
</div>
<script>
{FX_JS}
{INTERACT_JS}
document.querySelectorAll('.copy-btn').forEach(btn=>{{
  btn.addEventListener('click', async ()=>{{
    const t = btn.getAttribute('data-copy') || '';
    try {{ await navigator.clipboard.writeText(t); btn.textContent='已复制'; setTimeout(()=>btn.textContent='复制',1200); }}
    catch(e) {{ btn.textContent='失败'; }}
  }});
}});
</script>
</body></html>"""
    (MODS / "api.html").write_text(page, encoding="utf-8")
    return "m/api.html"


def write_404():
    (SITE / "404.html").write_text(
        f"""{head_block(f"页面未找到 | {SITE_NAME}", META_DESC, CANONICAL + "404.html")}
<body><div class="fx-aurora" aria-hidden="true"></div><div class="fx-grid" aria-hidden="true"></div><div class="fx-noise" aria-hidden="true"></div><div class="fx-scan" aria-hidden="true"></div><div class="fx-spot" aria-hidden="true"></div><canvas id="fx-particles" aria-hidden="true"></canvas><div class="wrap">{topnav("./")}<header class="hero"><h1>404</h1>
<p class="lead">页面不存在，返回首页继续浏览大模型免费资源。</p>
<p><a class="btn" href="./">返回首页</a></p></header></div>
<script>{FX_JS}
{INTERACT_JS}</script>
</body></html>""",
        encoding="utf-8",
    )


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


def build():
    global CFG, SITE_NAME, CANONICAL, META_DESC
    CFG = load_cfg()
    SITE_NAME = CFG["site_name"]
    CANONICAL = CFG["canonical"]
    META_DESC = (
        f"{SITE_NAME}汇总大模型免费API、免费GPT、Claude免费、DeepSeek免费额度、"
        f"AI工具免费、免费GPU与GitHub热门项目，每日更新。"
    )

    items, date, updated = collect_deal_items()
    pins = load_pinned()
    pin_urls = {norm_url(p.get("url")) for p in pins}
    items = [it for it in items if norm_url(it.get("url")) not in pin_urls]
    repos, repos_updated = load_section("github_hot.json")
    topics, topics_updated = load_section("hot_topics.json")
    dates = list_archive_dates()
    ym = ym_label(date)

    item_paths = write_item_pages(pins + items, date)
    cat_paths = write_category_pages(items, date, ym)
    mod_paths = write_module_special(repos, topics, date, ym)
    for d in dates:
        write_archive_page(d, items_for_date(d), dates)
    write_404()
    write_api_and_feed(items, repos, topics, date, updated, pins)
    api_doc = write_api_docs_page(date, ym)

    # landing tiles (bento)
    tiles = []
    counts = {}
    for n, (mid, title, desc, href, kind, cat) in enumerate(MODULES, 1):
        if kind == "cat":
            subset = [it for it in items if it.get("category") == cat]
        elif kind == "github":
            subset = repos
        else:
            subset = topics
        counts[mid] = len(subset)
        topn = subset[: (8 if n == 1 else 3)]
        lis = "".join(f"<li>{esc((it.get('title') or it.get('name') or '')[:60])}</li>" for it in topn) or "<li>暂无条目</li>"
        tiles.append(
            f"""<a class="module-tile t-{n}" href="{esc(href)}">
  <div class="tile-top"><span class="tile-ico">{icon_svg(mid)}</span><span class="tile-idx">{n:02d} / 07</span></div>
  <div class="tile-count"><b data-count="{len(subset)}">{len(subset)}</b><small>条</small></div>
  <h2>{esc(title)} <em>{len(subset)}</em></h2>
  <p class="desc">{esc(desc)}</p>
  <ol>{lis}</ol>
  <div class="go">进入模块 <span>→</span></div>
</a>"""
        )

    # ticker of latest items
    tick_src = (pins + items)[:18] + [dict(t, _path="m/hot-topics.html") for t in topics[:8]]
    tick_html = "".join(
        f'<a href="{esc(it.get("_path") or "")}"><i>{esc(NAV_SHORT.get(CAT_SLUG.get(it.get("category") or "", ""), "热议") if it.get("category") else "热议")}</i>{esc((it.get("title") or "")[:48])}</a>'
        for it in tick_src if it.get("title")
    )
    ticker = f'<div class="ticker" aria-label="最新条目"><div class="ticker-track">{tick_html}<span aria-hidden="true" style="display:contents">{tick_html}</span></div></div>' if tick_html else ""

    arch_links = "".join(
        f'<a class="arch {"current" if d==date else ""}" href="archives/{esc(d)}.html">{esc(d)}</a>' for d in dates[:30]
    )
    now_label = datetime.now(TZ).strftime("%Y-%m-%d %H:%M Asia/Shanghai")
    website_ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NAME,
        "url": CANONICAL,
        "description": META_DESC,
        "inLanguage": "zh-CN",
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{CANONICAL}?q={{search_term_string}}",
            "query-input": "required name=search_term_string",
        },
    }
    m = re.match(r"(.*?)(免费资源导航)$", SITE_NAME)
    h1_lines = (f'<span class="kl">{esc(m.group(1))}</span><span class="kl">{esc(m.group(2))}</span>' if m and m.group(1)
                else f'<span class="kl">{esc(SITE_NAME)}</span>')
    upd_short = (updated or "").replace(" Asia/Shanghai", "")
    page_title = f"{SITE_NAME} · {ym} · 大模型免费API / 免费GPT / Claude免费"
    page = f"""{head_block(page_title, META_DESC, CANONICAL, SITE_NAME + " · " + ym, extra_ld=[website_ld])}
<body class="home">
<div class="fx-noise" aria-hidden="true"></div>
<div class="fx-scan" aria-hidden="true"></div>
<div class="fx-spot" aria-hidden="true"></div>
{topnav("./")}
<header class="hero-xl hero-brain">
  <div class="hero-xl-inner">
    <div class="hero-copy" data-parallax="-0.06">
      <div class="eyebrow"><i class="live-dot"></i> LIVE FREE AI RESOURCES <span class="sep">/</span> <span class="eb-x">北京时间</span> <span data-clock>--:--:--</span></div>
      <h1 class="hero-title">{h1_lines}</h1>
      <p class="lead">帮你一站看清大模型免费API、免费GPT、Claude免费额度、DeepSeek免费额度、AI工具免费试用、免费GPU，以及值得关注的 GitHub 热门项目与最新AI新闻。每个模块独立成页，信息每日自动更新；参与前请以官网规则为准。</p>
      <div class="hero-cta"><a class="btn primary" href="#modules">浏览全部模块 →</a><a class="btn" href="m/api.html">CLI / API 接口</a><a class="btn" href="m/status.html"><i class="live-dot"></i> 更新动态</a></div>
      <div class="stats">
        <div class="pill">更新日期 <b>{esc(date)}</b></div>
        <div class="pill">免费资源 <b data-count="{len(items)}">{len(items)}</b></div>
        <div class="pill">GitHub热门 <b data-count="{len(repos)}">{len(repos)}</b></div>
        <div class="pill">热议 <b data-count="{len(topics)}">{len(topics)}</b></div>
        <div class="pill live" title="最近更新 {esc(upd_short)}">下次自动更新 <b data-next>--:--</b></div>
      </div>
    </div>
    {brain_block("vendor/", [("免费API", counts.get("damoxing-mianfei-api", "")), ("免费GPU", counts.get("mianfei-gpu-yunfuwu", "")), ("GitHub", len(repos)), ("热议", len(topics))])}
  </div>
  <div class="scroll-hint">SCROLL</div>
</header>
{brain_loader_script("vendor/")}
<div class="wrap pin-wrap">
  {pinned_block(pins, "")}
</div>
{ticker}
<div class="wrap">
  <section class="section" id="modules">
    <div class="sec-head"><span class="sec-idx">01 / MODULES</span>
    <h2>选择模块</h2>
    <p class="sec-desc">七大专题独立成页：点击进入，浏览完整列表与中文说明。悬停卡片，大脑对应区域会被点亮。</p></div>
    <div class="module-grid">{''.join(tiles)}</div>
  </section>

  {_board_teaser()}

  <section class="section" id="cli-api">
    <div class="sec-head"><span class="sec-idx">02 / DEVELOPER</span>
    <h2>CLI / API</h2>
    <p class="sec-desc">用一行命令拉取本站数据，零依赖、免密钥，静态 JSON 可直接跨域读取。</p></div>
    <div class="cli-split">
      <ul class="cli-feats">
        <li><code>api/latest.json</code> 全部免费资源（置顶条目排在最前）</li>
        <li><code>api/github-hot.json</code> GitHub 新热门项目</li>
        <li><code>api/hot.json</code> 最近热议 · <code>feed.xml</code> RSS 订阅</li>
        <li>每小时自动刷新，<a href="m/status.html">查看更新动态</a></li>
        <li><a class="btn" href="m/api.html" style="margin-top:8px">查看完整文档 →</a></li>
      </ul>
      <div class="term-block">
        <div class="term-bar"><span></span><span></span><span></span><em>quickstart — bash</em></div>
        <pre><code><span class="c"># 列出全部免费资源</span>
<span class="p">$</span> npx github:aiym168/aiym168.github.io list
<span class="c"># 或者不装 Node，直接用 curl</span>
<span class="p">$</span> curl -fsSL https://aiym168.github.io/cli.sh | bash -s -- list
<span class="p">$</span> curl -fsSL https://aiym168.github.io/api/latest.json<span class="caret"></span></code></pre>
      </div>
    </div>
  </section>

  <div class="panel-box" id="archives"><h2>每日存档</h2>{arch_links or "暂无"}</div>
  <div class="panel-box"><h2>免责声明</h2>
    <p class="sec-desc" style="margin:0">信息来自公开网页与社区，自动整理，可能过期或不准确。参与前请自行核实官网规则，谨防诈骗。</p>
  </div>
  {site_footer("./", "生成于 " + now_label)}
</div>
<script>{SITE_JS}</script>
</body></html>"""
    (SITE / "index.html").write_text(page, encoding="utf-8")

    board_path = _board_page(ym)
    url_entries = [("", date, "hourly", "1.0"), ("404.html", date, "yearly", "0.1"), ("m/api.html", date, "weekly", "0.8"), ("m/status.html", date, "hourly", "0.5"), ("feed.xml", date, "hourly", "0.6"), ("api/index.json", date, "hourly", "0.5")]
    if board_path:
        url_entries.append((board_path, date, "daily", "0.7"))  # page only; messages are never in the sitemap
    for pth in cat_paths + mod_paths:
        url_entries.append((pth, date, "daily", "0.9"))
    for pth in item_paths:
        url_entries.append((pth, date, "weekly", "0.8"))
    for d in dates:
        url_entries.append((f"archives/{d}.html", d, "weekly", "0.7"))
    write_sitemaps(url_entries)
    print(
        f"wrote landing modules={len(MODULES)} deals={len(items)} repos={len(repos)} "
        f"topics={len(topics)} items={len(item_paths)} canonical={CANONICAL}"
    )


if __name__ == "__main__":
    build()
