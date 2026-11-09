#!/usr/bin/env python3
"""Fetch free AI/tech deals + GitHub hot repos + hot discussions from public APIs.
No paid keys. Optional GitHub Models via GITHUB_TOKEN; keyword fallback otherwise.
Writes:
  data/auto/YYYY-MM-DD.json   — freebie/deal items
  data/auto/github_hot.json   — 新热门 repos
  data/auto/hot_topics.json   — 最近热议
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
import sys as _sys
_sys.path.insert(0, str(ROOT))
import selfheal  # noqa: E402
DATA_AUTO = ROOT / "data" / "auto"
TZ = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
UA = "aiym168-bot/1.0 (+https://github.com/aiym168/aiym168.github.io)"
CTX = ssl.create_default_context()

CATEGORIES = [
    "大模型 API 免费额度",
    "AI 产品会员/试用",
    "AI 开发工具与编程助手",
    "云服务/GPU/开发者资源",
    "科技软件/App 限免",
    "其他科技",
]

DEAL_KEYWORDS = [
    "free api", "free credits", "free tier", "free gpu", "free trial",
    "open beta", "no credit card", "free llm", "free tokens", "hobby plan",
    "student free", "免费", "白嫖", "限免", "免费额度", "免费试用", "薅羊毛",
    "api 额度", "free credits", "zero cost",
]
AI_TECH_KEYWORDS = [
    "ai", "llm", "gpt", "claude", "gemini", "deepseek", "qwen", "grok",
    "openai", "model", "agent", "gpu", "cuda", "ml", "machine learning",
    "devtool", "developer", "api", "sdk", "cursor", "copilot", "coding",
    "开源", "大模型", "人工智能", "编程", "开发", "框架", "工具",
]
BLOCK = [
    "airdrop", "crypto giveaway", "send eth", "send sol", "nft mint",
    "credit card offer", "bank bonus", "gambling", "casino", "forex",
    "空投", "信用卡", "银行活动", "返现", "优惠券购物",
]


def now_sh() -> datetime:
    return datetime.now(TZ)


def today_str() -> str:
    return now_sh().strftime("%Y-%m-%d")


def http_json(url: str, method: str = "GET", payload: dict | None = None, headers: dict | None = None, timeout: int = 35):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
        raw = resp.read()
        if not raw:
            return resp.status, None
        text = raw.decode("utf-8", errors="replace")
        if text.strip() in {"OK", "ok"}:
            return resp.status, None
        return resp.status, json.loads(text)


def safe_get(url: str, **kwargs):
    try:
        return http_json(url, **kwargs)
    except Exception as e:
        print(f"[warn] GET fail {url[:90]} :: {type(e).__name__}: {e}")
        return None, None


def github_token() -> str:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()


def looks_blocked(text: str) -> bool:
    t = (text or "").lower()
    return any(b.lower() in t for b in BLOCK)


def looks_ai_tech(text: str) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in AI_TECH_KEYWORDS)


def looks_deal(text: str) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in DEAL_KEYWORDS)


def slug_id(prefix: str, url: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "-", (url or "")[-80:]).strip("-").lower()
    return f"{prefix}-{base[:60]}"


def keyword_classify(text: str) -> tuple[str, str, str]:
    """Return (category, title_zh, summary_zh) via rules — Chinese-first display."""
    t = text or ""
    low = t.lower()
    if any(k in low for k in ["api", "token", "credits", "neurons", "额度", "llm api", "free gpt", "claude", "deepseek"]):
        cat = "大模型 API 免费额度"
        hint = "大模型免费API / 额度相关"
    elif any(k in low for k in ["trial", "beta", "pro free", "会员", "试用", "限免会员"]):
        cat = "AI 产品会员/试用"
        hint = "AI产品免费试用或限免会员"
    elif any(k in low for k in ["cursor", "copilot", "coderabbit", "ide", "编程", "coding assistant", "agent coding"]):
        cat = "AI 开发工具与编程助手"
        hint = "AI开发工具与编程助手"
    elif any(k in low for k in ["gpu", "colab", "kaggle", "vps", "cloud", "compute", "算力", "服务器"]):
        cat = "云服务/GPU/开发者资源"
        hint = "云服务 / 免费GPU / 开发者资源"
    elif any(k in low for k in ["app", "限免", "steam", "software", "开源工具"]):
        cat = "科技软件/App 限免"
        hint = "科技软件或App限免"
    else:
        cat = "其他科技"
        hint = "AI / 科技资讯"
    raw_title = re.split(r"[\n\r]", t.strip())[0]
    raw_title = re.sub(r"\s+", " ", raw_title)[:100] or "未命名科技动态"
    body = re.sub(r"\s+", " ", t).strip()
    if len(body) > 260:
        body = body[:257] + "…"
    if re.search(r"[\u4e00-\u9fff]", raw_title):
        title = raw_title[:80]
    else:
        title = f"{hint}：{raw_title}"[:90]
    if re.search(r"[\u4e00-\u9fff]", body):
        summary = body
    else:
        summary = (
            f"【{cat}】公开来源摘要（自动整理，请以官网为准）：{body}。"
            f"可关注大模型免费API、AI工具免费、免费GPU与GitHub热门项目相关更新。"
        )
    return cat, title, summary


MODELS_OK = 0
MODELS_FAIL = 0
TRANSLATE_OK = 0
TRANSLATE_FAIL = 0
TRANSLATE_CACHE_PATH = DATA_AUTO / "translations.json"
_TRANSLATE_CACHE: dict[str, str] | None = None
_TRANSLATE_DIRTY = False


def has_cjk(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))


def _load_translate_cache() -> dict[str, str]:
    global _TRANSLATE_CACHE
    if _TRANSLATE_CACHE is not None:
        return _TRANSLATE_CACHE
    _TRANSLATE_CACHE = {}
    if TRANSLATE_CACHE_PATH.exists():
        try:
            data = json.loads(TRANSLATE_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _TRANSLATE_CACHE = {str(k): str(v) for k, v in data.items() if v}
        except Exception as e:
            print(f"[warn] translations cache read: {e}")
    return _TRANSLATE_CACHE


def save_translate_cache() -> None:
    global _TRANSLATE_DIRTY, _TRANSLATE_CACHE
    if not _TRANSLATE_DIRTY:
        return
    try:
        TRANSLATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache = _load_translate_cache()
        if len(cache) > 8000:
            keys = list(cache.keys())[-6000:]
            cache = {k: cache[k] for k in keys}
            _TRANSLATE_CACHE = cache
        TRANSLATE_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _TRANSLATE_DIRTY = False
        print(f"[translate] cache saved n={len(cache)}")
    except Exception as e:
        print(f"[warn] translations cache write: {e}")


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()


def _http_get_text(url: str, timeout: int = 20) -> tuple[int | None, str | None]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[warn] translate GET fail: {type(e).__name__}")
        return None, None


def _via_google(text: str) -> str | None:
    q = urllib.parse.quote(text[:4500])
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl=zh-CN&dt=t&q={q}"
    )
    st, body = _http_get_text(url, timeout=25)
    if not body:
        return None
    try:
        data = json.loads(body)
        parts = []
        for seg in data[0] or []:
            if seg and seg[0]:
                parts.append(seg[0])
        out = "".join(parts).strip()
        return out or None
    except Exception:
        return None


def _via_mymemory(text: str) -> str | None:
    q = urllib.parse.quote(text[:450])
    url = f"https://api.mymemory.translated.net/get?q={q}&langpair=en|zh-CN"
    st, body = _http_get_text(url, timeout=25)
    if not body:
        return None
    try:
        data = json.loads(body)
        out = ((data.get("responseData") or {}).get("translatedText") or "").strip()
        if not out or "MYMEMORY WARNING" in out.upper():
            return None
        if out.lower() == text.strip().lower() and not has_cjk(out):
            return None
        return out
    except Exception:
        return None


_LIBRE_ENDPOINTS = [
    "https://libretranslate.com/translate",
    "https://translate.argosopentech.com/translate",
    "https://libretranslate.de/translate",
]


def _via_libre(text: str) -> str | None:
    payload = {"q": text[:4500], "source": "auto", "target": "zh", "format": "text"}
    raw = json.dumps(payload).encode("utf-8")
    for ep in _LIBRE_ENDPOINTS:
        try:
            req = urllib.request.Request(
                ep,
                data=raw,
                method="POST",
                headers={
                    "User-Agent": UA,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=25, context=CTX) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            out = (data.get("translatedText") or "").strip()
            if out and (has_cjk(out) or out.lower() != text.strip().lower()):
                return out
        except Exception:
            continue
    return None


def _glossary_fix(text: str) -> str:
    """Fix known machine-translation errors (法学硕士→LLM, 克劳德→Claude …) via glossary.py."""
    try:
        import glossary  # type: ignore
        return glossary.fix(text)
    except Exception as e:  # never break the fetcher
        print(f"[warn] glossary: {type(e).__name__}")
        return text


def free_translate(text: str) -> str:
    """Translate to zh-CN via Google gtx → MyMemory → LibreTranslate. Cache hits. Never raises."""
    global TRANSLATE_OK, TRANSLATE_FAIL, _TRANSLATE_DIRTY
    text = (text or "").strip()
    if not text:
        return ""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk >= max(8, max(len(text), 1) // 3):
        return text

    cache = _load_translate_cache()
    key = _cache_key(text)
    if key in cache and cache[key]:
        fixed = _glossary_fix(cache[key])
        if fixed != cache[key]:
            cache[key] = fixed
            _TRANSLATE_DIRTY = True
        return fixed

    out = None
    providers = {"google": _via_google, "mymemory": _via_mymemory, "libre": _via_libre}
    for name in selfheal.translator_order(list(providers)):
        fn = providers[name]
        try:
            out = fn(text)
        except Exception as e:
            print(f"[warn] translate {name}: {type(e).__name__}")
            out = None
        if out and out.strip():
            selfheal.record(name, True, kind="translators")
            print(f"[translate] ok via {name} len={len(text)}")
            break
        selfheal.record(name, False, error="no result", kind="translators")
        time.sleep(0.35)

    if out and out.strip():
        TRANSLATE_OK += 1
        out = _glossary_fix(out.strip())
        cache[key] = out
        _TRANSLATE_DIRTY = True
        time.sleep(0.45)
        return out

    TRANSLATE_FAIL += 1
    print(f"[warn] translate failed, keep original len={len(text)}")
    return text


def translate_fields(title: str, body: str, *, keep_title_en: bool = False) -> dict:
    title = (title or "").strip()
    body = (body or "").strip()
    original_title = title
    original_summary = body or title
    zh_title = title
    zh_summary = body or title
    if title and not has_cjk(title):
        if keep_title_en:
            zh_title = title
        else:
            zh_title = free_translate(title)
    if body and not has_cjk(body):
        zh_summary = free_translate(body)
    elif body and has_cjk(body):
        zh_summary = body
    elif not body and title and not has_cjk(title) and not keep_title_en:
        zh_summary = zh_title
    elif not body and title and keep_title_en:
        zh_summary = free_translate(f"GitHub repository: {title}")
    return {
        "title": zh_title or title or "未命名",
        "summary": zh_summary or body or title or "",
        "original_title": original_title,
        "original_summary": original_summary,
        "translated_by": "free-translate",
    }


def models_zh(prompt: str, max_tokens: int = 1200) -> str | None:
    global MODELS_OK, MODELS_FAIL
    if not getattr(models_zh, "_noted", False):
        print("[info] GitHub Models retired; using free translate APIs")
        models_zh._noted = True  # type: ignore[attr-defined]
    MODELS_FAIL += 1
    return None


def _extract_json_array(text: str) -> list | None:
    return None


def batch_translate(rows: list[dict], kind: str, batch_size: int = 12) -> dict[str, dict]:
    """Translate items with free keyless APIs + cache. Never breaks the build."""
    out: dict[str, dict] = {}
    if not rows:
        return out
    print(f"[translate] batch kind={kind} n={len(rows)}")
    for i, r in enumerate(rows):
        try:
            title = (r.get("title") or "")[:180]
            text = (r.get("text") or r.get("title") or "")[:800]
            if kind == "deal":
                cat, _, _ = keyword_classify(f"{title} {text}")
                fields = translate_fields(title, text, keep_title_en=False)
                out[r["id"]] = {
                    "category": cat,
                    "title": fields["title"],
                    "summary": fields["summary"],
                    "how": "打开来源链接按页面说明领取/试用；参与前自行核实。",
                    "original_title": fields["original_title"],
                    "original_summary": fields["original_summary"],
                    "translated_by": fields["translated_by"],
                }
            elif kind == "repo":
                fields = translate_fields(title, text, keep_title_en=True)
                summary = fields["summary"]
                if summary and not has_cjk(summary):
                    summary = free_translate(text or title)
                zh_label = ""
                if has_cjk(summary):
                    zh_label = re.split(r"[。！？\n]", summary)[0][:40]
                disp_title = (
                    f"{zh_label}（{title}）" if zh_label and title else (title or zh_label or "GitHub 项目")
                )
                out[r["id"]] = {
                    "title": disp_title,
                    "summary": summary or f"GitHub 仓库 {title}",
                    "original_title": title,
                    "original_summary": text or title,
                    "translated_by": "free-translate",
                }
            else:
                fields = translate_fields(title, text, keep_title_en=False)
                out[r["id"]] = {
                    "title": fields["title"],
                    "summary": fields["summary"],
                    "original_title": fields["original_title"],
                    "original_summary": fields["original_summary"],
                    "translated_by": fields["translated_by"],
                }
        except Exception as e:
            print(f"[heal] translate item failed: {type(e).__name__}: {e}")
            title = (r.get("title") or "未命名")[:120]
            text = (r.get("text") or title)[:400]
            cat = keyword_classify(f"{title} {text}")[0] if kind == "deal" else None
            out[r["id"]] = {
                "category": cat,
                "title": title,
                "summary": text,
                "how": "打开来源链接按页面说明领取/试用；参与前自行核实。" if kind == "deal" else None,
                "original_title": title,
                "original_summary": text,
                "translated_by": "passthrough",
            }
        if (i + 1) % 5 == 0:
            save_translate_cache()
    save_translate_cache()
    return out


def enrich_deal(raw_title: str, raw_text: str, source: str) -> tuple[str, str, str, str]:
    cat, _, _ = keyword_classify(f"{raw_title}\n{raw_text}")
    fields = translate_fields(raw_title, raw_text)
    how = "打开来源链接按页面说明领取/试用；参与前自行核实。"
    return cat, fields["title"], fields["summary"], how


def enrich_one_liner(raw_title: str, raw_text: str, kind: str) -> tuple[str, str]:
    fields = translate_fields(raw_title, raw_text, keep_title_en=(kind == "repo"))
    return fields["title"], fields["summary"]


# ---------------- sources: deals ----------------

def fetch_hn_deals() -> list[dict]:
    items = []
    queries = [
        "free API AI",
        "free credits LLM",
        "free GPU",
        "free tier OpenAI OR Claude OR Gemini",
        "\"free trial\" AI developer",
        "Show HN free API",
    ]
    since = (datetime.now(UTC) - timedelta(days=5)).timestamp()
    for q in queries:
        url = "https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(
            {"query": q, "tags": "story", "hitsPerPage": 15, "numericFilters": f"created_at_i>{int(since)}"}
        )
        st, data = safe_get(url)
        time.sleep(0.4)
        if not data:
            continue
        for h in data.get("hits") or []:
            title = h.get("title") or ""
            url_s = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            text = f"{title} {h.get('story_text') or ''}"
            if looks_blocked(text) or not (looks_deal(text) or looks_ai_tech(text)):
                continue
            if not looks_ai_tech(text):
                continue
            created = datetime.fromtimestamp(h.get("created_at_i") or 0, tz=UTC).astimezone(TZ)
            items.append(
                {
                    "id": slug_id("hn", str(h.get("objectID"))),
                    "source": "Hacker News",
                    "category": "",
                    "title": title,
                    "summary": "",
                    "how": "",
                    "deadline": None,
                    "author": h.get("author") or "hn",
                    "url": url_s,
                    "posted_at": created.strftime("%Y-%m-%d %H:%M Asia/Shanghai"),
                    "engagement": {
                        "points": h.get("points") or 0,
                        "comments": h.get("num_comments") or 0,
                    },
                    "_raw": text,
                }
            )
    return items


def fetch_v2ex_deals() -> list[dict]:
    items = []
    endpoints = [
        "https://www.v2ex.com/api/topics/latest.json",
        "https://www.v2ex.com/api/topics/hot.json",
    ]
    for ep in endpoints:
        st, data = safe_get(ep)
        time.sleep(0.8)
        if not isinstance(data, list):
            continue
        for t in data:
            title = t.get("title") or ""
            content = t.get("content") or ""
            text = f"{title}\n{content}"
            if looks_blocked(text):
                continue
            if not (looks_deal(text) and looks_ai_tech(text)):
                # still allow strong deal keywords in tech nodes
                node = ((t.get("node") or {}).get("name") or "")
                if node not in {"create", "programmer", "cloud", "share", "apple", "macos"} or not looks_deal(text):
                    continue
            url_s = t.get("url") or f"https://www.v2ex.com/t/{t.get('id')}"
            created = datetime.fromtimestamp(t.get("created") or 0, tz=UTC).astimezone(TZ)
            items.append(
                {
                    "id": slug_id("v2ex", str(t.get("id"))),
                    "source": "V2EX",
                    "category": "",
                    "title": title,
                    "summary": "",
                    "how": "",
                    "deadline": None,
                    "author": (t.get("member") or {}).get("username") or "v2ex",
                    "url": url_s,
                    "posted_at": created.strftime("%Y-%m-%d %H:%M Asia/Shanghai"),
                    "engagement": {"replies": t.get("replies") or 0},
                    "_raw": text[:2000],
                }
            )
    return items


def fetch_github_deal_repos() -> list[dict]:
    tok = github_token()
    if not tok:
        print("[warn] no GITHUB_TOKEN for repo search")
        return []
    items = []
    queries = [
        "free llm api in:name,description pushed:>" + (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d"),
        "awesome free api llm in:name,description pushed:>" + (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%d"),
        "free credits AI API in:readme pushed:>" + (datetime.now(UTC) - timedelta(days=20)).strftime("%Y-%m-%d"),
    ]
    for q in queries:
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": q, "sort": "updated", "order": "desc", "per_page": 8}
        )
        st, data = safe_get(url, headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
        time.sleep(1.0)
        if not data:
            continue
        for r in data.get("items") or []:
            desc = r.get("description") or ""
            text = f"{r.get('full_name')} {desc}"
            if looks_blocked(text):
                continue
            if not looks_ai_tech(text):
                continue
            created = datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00")).astimezone(TZ)
            items.append(
                {
                    "id": slug_id("ghdeal", r.get("full_name", "")),
                    "source": "GitHub",
                    "category": "",
                    "title": r.get("full_name") or "",
                    "summary": "",
                    "how": "",
                    "deadline": None,
                    "author": (r.get("owner") or {}).get("login") or "github",
                    "url": r.get("html_url"),
                    "posted_at": created.strftime("%Y-%m-%d %H:%M Asia/Shanghai"),
                    "engagement": {"stars": r.get("stargazers_count") or 0},
                    "_raw": text,
                }
            )
    return items


def fetch_devto_deals() -> list[dict]:
    items = []
    for tag in ["ai", "opensource", "machinelearning"]:
        st, data = safe_get(f"https://dev.to/api/articles?tag={tag}&per_page=10&top=7")
        time.sleep(0.4)
        if not isinstance(data, list):
            continue
        for a in data:
            title = a.get("title") or ""
            text = f"{title} {a.get('description') or ''}"
            if looks_blocked(text) or not looks_deal(text) or not looks_ai_tech(text):
                continue
            items.append(
                {
                    "id": slug_id("devto", str(a.get("id"))),
                    "source": "DEV.to",
                    "category": "",
                    "title": title,
                    "summary": "",
                    "how": "",
                    "deadline": None,
                    "author": ((a.get("user") or {}).get("username")) or "devto",
                    "url": a.get("url"),
                    "posted_at": (a.get("published_at") or "")[:16].replace("T", " ") + " UTC",
                    "engagement": {"reactions": a.get("positive_reactions_count") or 0, "comments": a.get("comments_count") or 0},
                    "_raw": text,
                }
            )
    return items


def fetch_lobsters_deals() -> list[dict]:
    st, data = safe_get("https://lobste.rs/hottest.json")
    if not isinstance(data, list):
        return []
    items = []
    for a in data:
        title = a.get("title") or ""
        tags = " ".join(a.get("tags") or [])
        text = f"{title} {tags}"
        if looks_blocked(text):
            continue
        if not (looks_deal(text) and looks_ai_tech(text)):
            continue
        items.append(
            {
                "id": slug_id("lob", a.get("short_id") or title),
                "source": "Lobsters",
                "category": "",
                "title": title,
                "summary": "",
                "how": "",
                "deadline": None,
                "author": a.get("submitter_user") if isinstance(a.get("submitter_user"), str) else (a.get("submitter_user") or {}).get("username", "lobsters"),
                "url": a.get("url") or a.get("comments_url"),
                "posted_at": (a.get("created_at") or "")[:16].replace("T", " ") + " UTC",
                "engagement": {"score": a.get("score") or 0, "comments": a.get("comment_count") or 0},
                "_raw": text,
            }
        )
    return items


# ---------------- github hot + hot topics ----------------

def fetch_github_hot() -> list[dict]:
    tok = github_token()
    if not tok:
        return []
    since7 = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%d")
    since14 = (datetime.now(UTC) - timedelta(days=14)).strftime("%Y-%m-%d")
    queries = [
        f"topic:llm created:>{since14}",
        f"topic:ai created:>{since7}",
        f"topic:agents created:>{since14}",
        f"topic:devtools created:>{since14}",
        f"LLM OR \"AI agent\" in:name,description created:>{since7}",
    ]
    seen = set()
    raw = []
    for q in queries:
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": q, "sort": "stars", "order": "desc", "per_page": 10}
        )
        st, data = safe_get(url, headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
        time.sleep(1.0)
        if not data:
            continue
        for r in data.get("items") or []:
            full = r.get("full_name")
            if not full or full in seen:
                continue
            desc = r.get("description") or ""
            text = f"{full} {desc}"
            if looks_blocked(text) or not looks_ai_tech(text):
                continue
            seen.add(full)
            created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).astimezone(TZ)
            raw.append(
                {
                    "id": slug_id("ghot", full),
                    "source": "GitHub",
                    "name": full,
                    "title": full,
                    "summary": desc,
                    "summary_en": desc,
                    "stars": r.get("stargazers_count") or 0,
                    "language": r.get("language") or "未知",
                    "created_at": created.strftime("%Y-%m-%d Asia/Shanghai"),
                    "url": r.get("html_url"),
                    "_raw_title": full,
                    "_raw_text": desc or full,
                }
            )
    raw.sort(key=lambda x: x.get("stars", 0), reverse=True)
    raw = raw[:30]
    tr = batch_translate(
        [{"id": r["id"], "title": r["_raw_title"], "text": r["_raw_text"]} for r in raw],
        kind="repo",
        batch_size=10,
    )
    out = []
    for r in raw:
        t = tr.get(r["id"]) or {}
        r["original_title"] = t.get("original_title") or r.get("_raw_title") or r.get("name")
        r["original_summary"] = t.get("original_summary") or r.get("summary_en") or r.get("_raw_text") or ""
        r["title"] = t.get("title") or r["name"]
        r["summary"] = t.get("summary") or r.get("summary_en") or f"GitHub 仓库 {r['name']}"
        r["translated_by"] = t.get("translated_by") or "free-translate"
        r.pop("_raw_title", None)
        r.pop("_raw_text", None)
        out.append(r)
    return out


def fetch_hot_topics(x_items: list[dict] | None = None) -> list[dict]:
    raw = []
    st, data = safe_get("https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({"tags": "front_page", "hitsPerPage": 20}))
    if data:
        for h in data.get("hits") or []:
            title = h.get("title") or ""
            if looks_blocked(title) or not looks_ai_tech(title):
                continue
            url_s = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            raw.append(
                {
                    "id": slug_id("hnhot", str(h.get("objectID"))),
                    "source": "Hacker News",
                    "title": title,
                    "summary": title,
                    "heat": f"点数 {h.get('points') or 0} · 评论 {h.get('num_comments') or 0}",
                    "points": h.get("points") or 0,
                    "url": url_s,
                    "_raw_title": title,
                    "_raw_text": title,
                    "_need_tr": True,
                }
            )
    for ep in ["https://www.v2ex.com/api/topics/hot.json", "https://www.v2ex.com/api/topics/latest.json"]:
        st, data = safe_get(ep)
        time.sleep(0.8)
        if not isinstance(data, list):
            continue
        for t in data:
            title = t.get("title") or ""
            content = (t.get("content") or "")[:300]
            text = f"{title}\n{content}"
            if looks_blocked(text) or not looks_ai_tech(text):
                continue
            # V2EX often already Chinese
            already = has_cjk(title)
            raw.append(
                {
                    "id": slug_id("v2hot", str(t.get("id"))),
                    "source": "V2EX",
                    "title": title,
                    "summary": content or title,
                    "heat": f"回复 {t.get('replies') or 0}",
                    "points": t.get("replies") or 0,
                    "url": t.get("url") or f"https://www.v2ex.com/t/{t.get('id')}",
                    "_raw_title": title,
                    "_raw_text": content or title,
                    "_need_tr": not already,
                }
            )
    for it in (x_items or [])[:12]:
        eng = it.get("engagement") or {}
        heat_n = int(eng.get("likes") or 0) + int(eng.get("bookmarks") or 0) * 2 + int(eng.get("impressions") or 0) // 500
        title = it.get("title") or ""
        summary = it.get("summary") or ""
        raw.append(
            {
                "id": slug_id("xhot", it.get("id") or it.get("url") or ""),
                "source": "X",
                "title": title,
                "summary": summary,
                "heat": f"赞 {eng.get('likes', 0)} · 收藏 {eng.get('bookmarks', 0)}",
                "points": heat_n,
                "url": it.get("url"),
                "_need_tr": not (has_cjk(title) and has_cjk(summary)),
                "_raw_title": title,
                "_raw_text": summary or title,
            }
        )

    need = [r for r in raw if r.get("_need_tr")]
    tr = batch_translate(
        [{"id": r["id"], "title": r.get("_raw_title") or "", "text": r.get("_raw_text") or ""} for r in need],
        kind="hot",
        batch_size=12,
    )
    out = []
    seen = set()
    for r in raw:
        u = r.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        if r.get("_need_tr"):
            t = tr.get(r["id"]) or {}
            r["original_title"] = t.get("original_title") or r.get("_raw_title") or r.get("title")
            r["original_summary"] = t.get("original_summary") or r.get("_raw_text") or r.get("summary")
            r["title"] = t.get("title") or r["title"]
            r["summary"] = t.get("summary") or r["summary"]
            r["translated_by"] = t.get("translated_by") or "free-translate"
        else:
            r["original_title"] = r.get("title")
            r["original_summary"] = r.get("summary")
            r["translated_by"] = "native-zh"
        r.pop("_raw_title", None)
        r.pop("_raw_text", None)
        r.pop("_need_tr", None)
        out.append(r)
    out.sort(key=lambda x: x.get("points") or 0, reverse=True)
    return out[:40]


def load_latest_x_items() -> list[dict]:
    """Prefer Action-fetched X feed, then day JSON from Simular/fetch_x merge."""
    feed = DATA_AUTO / "x_feed.json"
    if feed.exists():
        try:
            d = json.loads(feed.read_text(encoding="utf-8"))
            items = d.get("items") or []
            if items:
                return items
        except Exception as e:
            print(f"[warn] x_feed: {e}")
    data_dir = ROOT / "data"
    files = sorted(data_dir.glob("????-??-??.json"), reverse=True)
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            return d.get("items") or []
        except Exception:
            continue
    return []


def load_prev_json(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[warn] cannot read previous {path}: {e}")
    return None


def finalize_deals(raw_items: list[dict]) -> list[dict]:
    seen = set()
    uniq = []
    for it in raw_items:
        url = it.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        uniq.append(it)
        if len(uniq) >= 40:
            break
    tr = batch_translate(
        [
            {
                "id": it["id"],
                "title": it.get("title") or "",
                "text": it.get("_raw") or it.get("title") or "",
            }
            for it in uniq
        ],
        kind="deal",
        batch_size=10,
    )
    out = []
    for it in uniq:
        t = tr.get(it["id"]) or {}
        if t:
            it["category"] = t.get("category") or it.get("category") or "其他科技"
            it["original_title"] = t.get("original_title") or it.get("title")
            it["original_summary"] = t.get("original_summary") or it.get("_raw") or it.get("summary")
            it["title"] = t.get("title") or it.get("title")
            it["summary"] = t.get("summary") or it.get("summary")
            it["how"] = t.get("how") or "打开来源链接按页面说明领取/试用；参与前自行核实。"
            it["translated_by"] = t.get("translated_by") or "free-translate"
        else:
            raw_t = it.get("title") or ""
            raw_b = it.get("_raw") or it.get("title") or ""
            cat, title, summary, how = enrich_deal(raw_t, raw_b, it.get("source") or "")
            it["category"] = cat
            it["original_title"] = raw_t
            it["original_summary"] = raw_b
            it["title"] = title
            it["summary"] = summary
            it["how"] = how
            it["translated_by"] = "free-translate"
        it.pop("_raw", None)
        out.append(it)
    return out


def write_json_safe(path: Path, payload: dict, keep_if_empty_key: str = "items") -> None:
    """Self-healing: never overwrite good previous file with empty items."""
    items = payload.get(keep_if_empty_key)
    prev = load_prev_json(path)
    if (not items) and prev and prev.get(keep_if_empty_key):
        print(f"[heal] keep previous {path.name}: new empty, old has {len(prev.get(keep_if_empty_key) or [])}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[write] {path} items={len(items or [])}")


def main():
    global MODELS_OK, MODELS_FAIL
    DATA_AUTO.mkdir(parents=True, exist_ok=True)
    print("[fetch] start", now_sh().isoformat())
    raw = []
    for name, fn in [
        ("HN", fetch_hn_deals),
        ("V2EX", fetch_v2ex_deals),
        ("GitHub", fetch_github_deal_repos),
        ("DEV.to", fetch_devto_deals),
        ("Lobsters", fetch_lobsters_deals),
    ]:
        if selfheal.should_skip(name):
            print(f"[heal] {name} auto-skipped (backoff until {selfheal.load()['sources'][name].get('skip_until_label')})")
            continue
        try:
            got = fn()
            print(f"[fetch] {name}: {len(got)}")
            raw.extend(got)
            selfheal.record(name, len(got) > 0, len(got), "" if got else "0 items")
        except Exception as e:
            print(f"[fetch] {name} ERROR {type(e).__name__}: {e} (keeping other sources)")
            selfheal.record(name, False, 0, f"{type(e).__name__}: {e}")
    # self-discovered items (discover.py) are merged as an extra source
    try:
        disc = load_prev_json(DATA_AUTO / "discovered.json") or {}
        known = {it.get("url") for it in raw}
        extra = [dict(it) for it in (disc.get("items") or []) if it.get("url") not in known]
        print(f"[fetch] Discovery: {len(extra)}")
    except Exception as e:
        print(f"[heal] discovery merge failed: {e}")
        extra = []

    day = today_str()
    deal_path = DATA_AUTO / f"{day}.json"
    try:
        deals = finalize_deals(raw)
        have = {it.get("url") for it in deals}
        deals.extend(it for it in extra if it.get("url") not in have)
    except Exception as e:
        print(f"[heal] finalize_deals failed: {e}; keeping previous deals")
        deals = []
    write_json_safe(
        deal_path,
        {
            "date": day,
            "updated_at": now_sh().isoformat(timespec="minutes"),
            "updated_at_label": now_sh().strftime("%Y-%m-%d %H:%M Asia/Shanghai"),
            "source": "auto-fetch public APIs",
            "items": deals,
            "models_ok": MODELS_OK,
            "models_fail": MODELS_FAIL,
        },
    )

    x_items = load_latest_x_items()
    hot_path = DATA_AUTO / "github_hot.json"
    hot_repos = []
    if selfheal.should_skip("GitHubHot"):
        print("[heal] GitHubHot auto-skipped")
    else:
        try:
            hot_repos = fetch_github_hot()
            selfheal.record("GitHubHot", bool(hot_repos), len(hot_repos))
        except Exception as e:
            print(f"[heal] github_hot failed: {e}")
            selfheal.record("GitHubHot", False, 0, str(e))
    write_json_safe(
        hot_path,
        {
            "updated_at_label": now_sh().strftime("%Y-%m-%d %H:%M Asia/Shanghai"),
            "items": hot_repos,
            "models_ok": MODELS_OK,
            "models_fail": MODELS_FAIL,
        },
    )

    topics_path = DATA_AUTO / "hot_topics.json"
    hot_topics = []
    if selfheal.should_skip("HotTopics"):
        print("[heal] HotTopics auto-skipped")
    else:
        try:
            hot_topics = fetch_hot_topics(x_items)
            selfheal.record("HotTopics", bool(hot_topics), len(hot_topics))
        except Exception as e:
            print(f"[heal] hot_topics failed: {e}")
            selfheal.record("HotTopics", False, 0, str(e))
    write_json_safe(
        topics_path,
        {
            "updated_at_label": now_sh().strftime("%Y-%m-%d %H:%M Asia/Shanghai"),
            "items": hot_topics,
            "models_ok": MODELS_OK,
            "models_fail": MODELS_FAIL,
        },
    )

    by_src = {}
    # reload deals file in case healed
    cur = load_prev_json(deal_path) or {"items": deals}
    for it in cur.get("items") or []:
        by_src[it.get("source")] = by_src.get(it.get("source"), 0) + 1
    print("[summary] deals by source", by_src)
    print(f"[summary] models_ok={MODELS_OK} models_fail={MODELS_FAIL} translate_ok={TRANSLATE_OK} translate_fail={TRANSLATE_FAIL}")
    save_translate_cache()
    selfheal.save()


if __name__ == "__main__":
    main()
