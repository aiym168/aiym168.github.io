#!/usr/bin/env python3
"""AI 新闻 / AI 花边 / 科技新闻 采集（每小时由 engine/pipeline.sh 调用）。

只从下面 SOURCES 白名单里的公开 RSS / API 取数据；标题+摘要命中 BLOCK（中英文敏感词）就丢弃，
宁可错杀：色情低俗、时政/外交/军事/宗教、暴力犯罪、赌博毒品、金融荐股等一律不收。
英文条目用 fetch_auto.free_translate（免费翻译接口，带缓存）译成中文。
输出 data/news/db.json；任何异常都保留上一次的数据。不要手改 db.json，改这里。
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "news" / "db.json"
STATUS = ROOT / "data" / "news" / "collect_status.json"
TZ = ZoneInfo("Asia/Shanghai")
UA = "Mozilla/5.0 (compatible; aiym168-news/1.0; +https://aiym168.github.io/)"
KEEP_DAYS = 10
CAP_DEFAULT = 150
CAP = {"ai": 220, "gossip": 80, "huawei": 150}
MAX_NEW_TRANSLATE = 120  # 每次最多新翻译多少条英文（每条 2 次请求；免费接口有缓存，失败自动换下一个）
PER_SOURCE_NEW = 8       # 每个来源每次最多新收几条，保证各来源轮流上新

REG = ROOT / "data" / "news" / "sources.json"  # 来源白名单（数据文件）；disabled=true 的来源不抓


def load_sources() -> list[tuple]:
    try:
        L = json.loads(REG.read_text(encoding="utf-8")).get("sources") or []
    except Exception as e:
        print("[news] sources.json unreadable:", e)
        L = []
    try:  # self-evolution overlay: promoted sources join, paused / slow-cadence sources sit this run out
        import tuning
        have = {x.get("key") for x in L}
        L = L + [dict(x, need_ai=True) for x in tuning.promoted("news") if x["key"] not in have]
        L = [x for x in L if tuning.should_fetch("news", x.get("key", ""))]
        WEIGHT.update({x["key"]: tuning.weight("news", x["key"]) for x in L if x.get("key")})
    except Exception as e:
        print("[news] tuning overlay skipped:", e)
    KIND.update({x["key"]: x.get("kind", "") for x in L})
    return [(x["key"], x["name"], x["home"], x["feed"], x["channel"], x.get("lang", "en"), bool(x.get("need_ai")))
            for x in L if x.get("feed") and not x.get("disabled")]


WEIGHT: dict[str, float] = {}


def per_source_cap(key: str) -> int:
    return max(3, min(14, round(PER_SOURCE_NEW * WEIGHT.get(key, 1.0))))


KIND: dict[str, str] = {}
CIVITAI_BAD = re.compile(r"uncensor|abliterat|heretic|jailbreak|erotic|roleplay|\brp\b|gguf-nsfw|babe|mature|waifu|hentai|pony|bikini|lingerie|nsfw|nude|sexy|girl|woman|women|female|lady|body|breast|ass\b|thicc|milf|lewd|ecchi|feet|美女|少女|女|熟|性|裸|色", re.I)
HF_PIPE = {"text-to-video": "aivideo", "image-to-video": "aivideo", "video-to-video": "aivideo", "text-to-image": "comfyui", "image-to-image": "comfyui"}
HF_ZH = {"text-generation": "文本生成", "text-to-image": "文生图", "image-to-image": "图生图", "text-to-video": "文生视频", "image-to-video": "图生视频",
         "text-to-speech": "语音合成", "automatic-speech-recognition": "语音识别", "image-text-to-text": "多模态", "feature-extraction": "向量"}


def special_rows(kind: str, raw: bytes, ch0: str) -> list[dict]:
    """JSON sources → rows with ready-made Chinese titles (tpl=True: title not translated, summary may be)."""
    d = json.loads(raw)
    rows = []
    if kind == "civitai":
        for m in d.get("items") or []:
            lvl = m.get("nsfwLevel") or 0
            name = (m.get("name") or "").strip()
            tags = " ".join(m.get("tags") or [])
            if m.get("nsfw") or lvl > 1 or not name or CIVITAI_BAD.search(name + " " + tags) or blocked(name, tags):
                continue  # 严格：只要 PG 级（nsfwLevel ≤ 1）
            v = (m.get("modelVersions") or [{}])[0]
            st = m.get("stats") or {}
            typ = {"Workflows": "工作流", "Checkpoint": "大模型", "LORA": "LoRA", "TextualInversion": "Embedding", "Controlnet": "ControlNet"}.get(m.get("type"), m.get("type") or "模型")
            rows.append({"title": f"Civitai 本周热门{typ}：{name}", "link": f"https://civitai.com/models/{m.get('id')}",
                         "desc": f"本周下载 {st.get('downloadCount', 0)} 次，基础模型 {v.get('baseModel') or '未注明'}。适用于 ComfyUI / Stable Diffusion 工作流，下载前请看作者的使用许可。",
                         "date": v.get("publishedAt") or v.get("createdAt"), "tpl": True})
    elif kind == "hf":
        for m in d if isinstance(d, list) else []:
            mid = m.get("id") or m.get("modelId")
            if not mid or blocked(mid) or CIVITAI_BAD.search(mid):
                continue
            pt = m.get("pipeline_tag") or ""
            rows.append({"title": f"Hugging Face 热门{HF_ZH.get(pt, '')}模型：{mid}", "link": f"https://huggingface.co/{mid}",
                         "desc": f"Hugging Face 趋势榜上的{HF_ZH.get(pt, pt or '')}模型，{m.get('likes', 0)} 个点赞、{m.get('downloads', 0)} 次下载。",
                         "date": m.get("createdAt") or m.get("lastModified"), "tpl": True, "ch": HF_PIPE.get(pt, "ai")})
    elif kind == "ghsearch":
        lab = {"comfyui": "ComfyUI 节点/工作流", "aivideo": "AI 视频生成", "aigc": "AIGC"}.get(ch0, "开源")
        for r in d.get("items") or []:
            fn, desc = r.get("full_name") or "", r.get("description") or ""
            if not fn or blocked(fn, desc) or CIVITAI_BAD.search(fn):
                continue
            rows.append({"title": f"{lab}开源项目：{fn}（★{r.get('stargazers_count', 0)}）", "link": r.get("html_url") or "",
                         "desc": desc, "date": r.get("pushed_at") or r.get("created_at"), "tpl": True})
    return rows


SOURCES = load_sources()
SRC = {s[0]: s for s in SOURCES}

# ---- content filter (when unsure, drop) -------------------------------------------------------
BLOCK_ZH = """监管 网信办 广电总局 国家广电 色情 黄色 低俗 裸 露点 性感 性爱 性交 性侵 性骚扰 强奸 猥亵 嫖 卖淫 约炮 情色 成人片 成人内容 艳照 不雅 走光 床照 偷拍 乳房 胸部 臀 内衣 比基尼 OnlyFans 擦边
政治 政府 政党 党委 党员 共产党 中央 国务院 总书记 主席 总理 部长 人大 政协 外交 大使 领导人 官员 落马 纪委 反腐 双规 选举 大选 投票 公投 总统 议会 国会 议员 白宫 克里姆林
台湾 台独 两岸 香港 澳门 新疆 西藏 藏独 疆独 维吾尔 法轮 六四 天安门 民主 人权 抗议 示威 游行 罢工 暴乱 镇压 审查 翻墙 制裁 禁令 出口管制 实体清单 关税 贸易战
军方 军事 军队 解放军 国防 武器 导弹 核武 战争 战机 航母 空袭 冲突 袭击 恐怖 恐袭 爆炸 枪击 杀人 凶杀 命案 死亡 身亡 遇难 自杀 跳楼 尸体 血腥 斩首
以色列 巴勒斯坦 加沙 哈马斯 伊朗 乌克兰 俄罗斯 普京 泽连斯基 特朗普 拜登 哈里斯 朝鲜 金正恩 美军 北约
宗教 伊斯兰 基督 佛教 邪教 赌博 博彩 赌场 彩票 毒品 冰毒 吸毒 大麻 诈骗 传销 洗钱 荐股 内幕交易 币圈 割韭菜 维权 塌房 出轨 绯闻 离婚 小三 丑闻 疫情 疫苗
间谍 外遇 情妇 婚外 偷情 央视 新华社 人民日报 环球时报 外媒称中国 中美 美方 中方 国家安全 地缘 芯片禁令 出口限制 管制 习 毛泽东 领袖 主权 领土 南海 钓鱼岛 移民 难民"""
BLOCK_EN = r"""porn|porno|sex|sexual|sexy|nude|nudity|naked|nsfw|explicit|erotic|onlyfans|escort|prostitut|rape|molest|harass|grooming|csam|child abuse|
politic|government|congress|senate|senator|parliament|election|elect|vote|voting|ballot|democrat|republican|gop|white house|president|prime minister|minister|governor|
trump|biden|harris|vance|putin|zelensky|xi jinping|kim jong|netanyahu|doge|federal|immigration|deport|
taiwan|hong kong|tibet|xinjiang|uyghur|tiananmen|ccp|communist|
tariff|sanction|export control|entity list|trade war|war|wars|military|army|navy|pentagon|defense department|department of defense|weapon|missile|nuclear weapon|drone strike|airstrike|
israel|gaza|hamas|palestin|iran|ukrain|russia|kremlin|north korea|nato|terror|bomb|shooting|shooter|gun|guns|killed|murder|suicide|self-harm|death|dies|dead|
religio|church|islam|muslim|christian|jewish|gambl|casino|betting|lottery|drug|drugs|cocaine|meth|fentanyl|cannabis|marijuana|scam|fraud|launder|
protest|riot|abortion|lgbt|transgender|racis|nazi|extremis|police|arrest|prison|jail|covid|vaccine|pandemic|
stock tip|pump and dump|memecoin|sexual|erotic|nsfw|hentai|weapons|warfare|soldier|soldiers|troops|spy|spies|espionage|affair|mistress|cheating on|beijing|china|chinese|sovereign|national security|govcloud|geopolit|chip ban"""
BZH = [w for w in BLOCK_ZH.split() if w]
STEMS = {"politic", "prostitut", "palestin", "ukrain", "religio", "gambl", "racis", "extremis", "terror", "launder", "harass", "molest", "erotic", "porno", "nazi"}
BEN = re.compile(r"\b(?:" + "|".join((w + r"\w*") if w in STEMS else (w + r"\b") for w in BLOCK_EN.replace("\n", "").split("|") if w) + ")", re.I)
AI_KW = re.compile(r"\b(ai|a\.i\.|llm|llms|gpt|chatgpt|openai|claude|anthropic|gemini|deepmind|llama|mistral|deepseek|qwen|copilot|agent|agents|neural|machine learning|"
                   r"diffusion|transformer|hugging ?face|nvidia|cursor|midjourney|sora|perplexity|grok|xai)\b|(?<![A-Za-z])(?-i:AI)(?![A-Za-z])|人工智能|大模型|智能体|机器学习|生成式|AIGC|算力", re.I)
GOSSIP_KW = re.compile(r"\b(ceo|founder|co-founder|hire[sd]?|poach(es|ed)?|joins|leaves|quits|departs|resigns?|rumou?rs?|leak(ed|s)?|reportedly|drama|feud|beef|spat|"
                       r"viral|meme|prank|jokes?|funny|weird|bizarre|easter egg|secret|tweet(ed)?|salary|pay package|interview|podcast|admits|slams|mocks|roast)\b|"
                       r"离职|跳槽|挖角|加盟|出走|传闻|爆料|曝光|网友|整活|彩蛋|吐槽|回应|开撕|年薪|身价|内部信|八卦|花边|趣闻|名场面", re.I)


OFFTOPIC = re.compile(r"国补|降价|新低|史低|折扣|优惠券|京东|淘宝|天猫|拼多多|直降|到手价|好价|券后|元起|秒杀|补贴价|限时价|促销|电影|影片|上映|票房|金鸡|导演|演员|明星|综艺|电视剧|网剧|动画片|天气|气象|高温|暴雨|地震|台风|彩票|楼市|房价|A股|港股|美股|涨停|跌停|股价")


def blocked(*texts) -> str | None:
    t = " ".join(x for x in texts if x)
    for w in BZH:
        if w in t:
            return w
    m = BEN.search(t)
    return m.group(0) if m else None


# ---- fetch / parse ---------------------------------------------------------------------------
def get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml,application/atom+xml,application/xml,application/json;q=0.9,*/*;q=0.5"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(3_000_000)


def clean(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(The post .{0,200} appeared first on .{0,80}\.?|Continue reading.*|Read more.*|阅读全文.*|查看全文.*|点击查看原文.*|#欢迎关注.*)$", "", s).strip()
    return s


def pdate(s) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(TZ)


def _t(el, *names):
    for n in names:
        x = el.find(n)
        if x is not None:
            if x.text and x.text.strip():
                return x.text
            if x.get("href"):
                return x.get("href")
    return ""


def parse_feed(raw: bytes) -> list[dict]:
    raw = re.sub(rb"^\s+", b"", raw)
    raw = re.sub(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", b"", raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:  # sloppy feeds (bare & etc.): regex fallback for RSS <item>
        txt = raw.decode("utf-8", "replace")
        g = lambda b, t: (re.search(rf"<{t}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{t}>", b, re.S) or [None, ""])[1]
        return [{"title": g(b, "title"), "link": g(b, "link").strip(), "desc": g(b, "description"), "date": g(b, "pubDate")}
                for b in re.findall(r"<item>(.*?)</item>", txt, re.S)]
    A = "{http://www.w3.org/2005/Atom}"
    out = []
    items = root.findall(".//item")
    if items:
        for it in items:
            out.append({"title": _t(it, "title"), "link": _t(it, "link", "guid"),
                        "desc": _t(it, "description", "{http://purl.org/rss/1.0/modules/content/}encoded"),
                        "date": _t(it, "pubDate", "{http://purl.org/dc/elements/1.1/}date")})
    else:
        for e in root.findall(f".//{A}entry"):
            link = ""
            for l in e.findall(f"{A}link"):
                if l.get("rel", "alternate") == "alternate":
                    link = l.get("href", ""); break
            out.append({"title": _t(e, f"{A}title"), "link": link or _t(e, f"{A}id"),
                        "desc": _t(e, f"{A}summary", f"{A}content"), "date": _t(e, f"{A}published", f"{A}updated")})
    return out


def fetch_source(s):
    key, name, home, url, ch, lang, need_ai = s
    try:
        kind = KIND.get(key, "")
        if kind == "ghsearch":
            url = url.replace("{D7}", (datetime.now(TZ) - timedelta(days=7)).strftime("%Y-%m-%d"))
            import os
            tok = os.environ.get("GITHUB_TOKEN", "")
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json", **({"Authorization": "Bearer " + tok} if tok else {})})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read(3_000_000)
        else:
            raw = get(url)
        if kind and kind != "gnews":
            return key, special_rows(kind, raw, ch)[:30], ""
        if key == "hn":
            hits = json.loads(raw).get("hits") or []
            rows = [{"title": h.get("title") or "", "link": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                     "desc": "", "date": h.get("created_at"), "hn": f"https://news.ycombinator.com/item?id={h.get('objectID')}"}
                    for h in hits if (h.get("points") or 0) >= 80]
        elif "v2ex.com/api/" in url:
            rows = [{"title": t.get("title") or "", "link": t.get("url") or "", "desc": t.get("content") or "",
                     "date": datetime.fromtimestamp(t.get("created") or 0, timezone.utc).isoformat()} for t in json.loads(raw)]
        else:
            rows = parse_feed(raw)
        if kind == "gnews":  # 新闻聚合：标题末尾是 " - 媒体名"，拆出来当来源
            for r in rows:
                m = re.match(r"^(.*\S)\s+[-–]\s+([^-–]{1,40})$", r.get("title") or "")
                if m:
                    r["title"], r["src"] = m.group(1), m.group(2).strip()
                r["desc"] = ""
            rows = [r for r in rows if r.get("src") not in ("YouTube", "Bilibili", "哔哩哔哩", "抖音")]
        return key, rows[:30], ""
    except Exception as e:
        return key, [], f"{type(e).__name__}: {str(e)[:120]}"


def summary_of(desc: str, lang: str) -> str:
    d = clean(desc)
    if lang == "zh":
        d = re.sub(r"^(IT之家|快科技)?\s*\d+\s*月\s*\d+\s*日消息[，,]\s*", "", d)
        return (d[:150] + "…") if len(d) > 150 else d
    s = ""
    for p in re.split(r"(?<=[.!?])\s+", d):
        if len(s) + len(p) > 360:
            break
        s = (s + " " + p).strip()
    return s or d[:360]


def meta_desc(url: str) -> str:
    """Article page's own description (for feeds that give no summary)."""
    try:
        raw = get(url, timeout=10)[:400_000].decode("utf-8", "replace")
    except Exception:
        return ""
    for pat in (r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]+content=["\']([^"\']{20,600})',
                r'<meta[^>]+content=["\']([^"\']{20,600})["\'][^>]+(?:property|name)=["\'](?:og:description|description)'):
        m = re.search(pat, raw, re.I)
        if m:
            return clean(m.group(1))[:300]
    return ""


def norm_url(u: str) -> str:
    u = (u or "").strip()
    u = re.sub(r"[?&](utm_[^=&]+|ref|source)=[^&#]*", "", u)
    return u.rstrip("?&")


def nid(u: str) -> str:
    return hashlib.sha1(norm_url(u).encode()).hexdigest()[:12]


HUAWEI_KW = re.compile(r"华为|Huawei|鸿蒙|HarmonyOS|麒麟\s?\d|麒麟芯片|问界|鸿蒙智行|智界|享界|尊界|尚界|昇腾|Ascend\s?\d|华为云|余承东|盘古大模型|仓颉|Pura\s?\d+|Mate\s?\d+|Mate\s?X\d|nova\s?\d+", re.I)
COMFY_KW = re.compile(r"ComfyUI|\bcomfy\b", re.I)
VIDEO_KW = re.compile(r"\bSora\b|\bKling\b|可灵|即梦|Jimeng|\bRunway\b|\bVidu\b|Hailuo|海螺视频|海螺 ?AI|\bVeo ?\d|\bPika\b|Dream Machine|Seedance|\bWan ?2|万相|视频生成|文生视频|图生视频|video generat|text-to-video|image-to-video|AI 视频|AI视频", re.I)
DRAMA_KW = re.compile(r"漫剧|动态漫|AI ?短剧|AI ?漫画|AI ?动画|AI ?微短剧|AI ?comic|AI ?anime|AI-generated (short )?(drama|series|anime)", re.I)
TUTOR_KW = re.compile(r"教程|手把手|上手|入门|指南|实战|实操|保姆级|\btutorial|\bhow to\b|\bhow-to\b|\bguide\b|step-by-step|cookbook", re.I)


def route(ch: str, title: str, summ: str) -> str:
    """Topic channels win over the source's default channel (most specific first)."""
    t = title or ""
    if COMFY_KW.search(t):
        return "comfyui"
    if VIDEO_KW.search(t):
        return "aivideo"
    if DRAMA_KW.search(t):
        return "aidrama"
    if HUAWEI_KW.search(t):
        return "huawei"  # 华为相关一律进华为频道（制裁/地缘等已在过滤里丢掉）
    if TUTOR_KW.search(t) and AI_KW.search(t + " " + (summ or "")):
        return "aigc"
    return ch


def gn_ok(ch: str, title: str) -> bool:
    kw = {"aidrama": DRAMA_KW, "aivideo": VIDEO_KW, "comfyui": COMFY_KW, "huawei": HUAWEI_KW}.get(ch)
    return bool((kw and kw.search(title)) or (ch in ("aigc", "aidrama", "aivideo") and AI_KW.search(title) and (ch != "aidrama" or re.search(r"剧|漫|动画|动漫", title))))


CH_KEYS = ("comfyui", "aivideo", "aidrama", "aigc", "huawei", "ai", "gossip", "mobile", "chip", "internet", "software", "game", "auto", "space", "science", "dev", "launch")
AI_MOVE = {"internet", "software", "dev", "mobile", "launch"}  # 这些综合来源里明显是 AI 的条目归到 AI 新闻


def tkey(t: str) -> str:
    return re.sub(r"[\W_]+", "", (t or "").lower())[:40]


def heal():
    try:
        import selfheal
        selfheal.load().setdefault("news", {})
        return selfheal
    except Exception as e:
        print("[news] selfheal unavailable:", e)
        return None


def main() -> int:
    now = datetime.now(TZ)
    try:
        db = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        db = {"items": []}
    old = {x["id"]: x for x in db.get("items") or []}
    for x in old.values():  # 旧频道迁移：tech → internet
        if x.get("channel") not in CH_KEYS:
            x["channel"] = "internet"
    status = {"run_at": now.isoformat(timespec="seconds"), "sources": {}, "skipped": [], "dropped": {}, "new": 0}
    sh = heal()
    todo = []
    for src in SOURCES:
        if sh and sh.should_skip(src[0], "news"):
            status["skipped"].append(src[0])
        else:
            todo.append(src)
    with ThreadPoolExecutor(16) as ex:
        res = list(ex.map(fetch_source, todo))
    try:
        sys.path.insert(0, str(ROOT))
        import fetch_auto  # free_translate + cache
        tr = fetch_auto.free_translate
    except Exception as e:
        print("[news] translator unavailable:", e)
        fetch_auto, tr = None, None
    seen = set()
    for x in old.values():
        seen.add(tkey(x.get("title_orig") or x.get("title"))); seen.add(tkey(x.get("title")))
    # pass 1: filter + classify (no network); pass 2: translate round-robin across sources
    queue: dict[str, list] = {}
    for key, rows, err in res:
        _, name, home, _u, ch0, lang, need_ai = SRC[key]
        st = {"ok": not err and bool(rows), "error": err or ("" if rows else "empty feed"), "rows": len(rows), "new": 0, "blocked": 0}
        status["sources"][key] = st
        if sh:
            sh.record(key, st["ok"], len(rows), st["error"], kind="news")
        for r in rows:
            title = clean(r.get("title") or "")
            link = norm_url(r.get("link") or "")
            if not title or not link.startswith("http"):
                continue
            i, k = nid(link), tkey(title)
            if i in old or k in seen:
                continue
            pub = pdate(r.get("date")) or now
            if r.get("tpl") and pub < now - timedelta(days=KEEP_DAYS):
                pub = now  # 趋势榜条目：上榜时间即收录时间
            if pub < now - timedelta(days=KEEP_DAYS) or pub > now + timedelta(hours=2):
                continue
            summ = summary_of(r.get("desc") or "", lang)
            why = blocked(title, summ, link)
            if not why and lang == "zh" and OFFTOPIC.search(title):
                why = "(非科技)"
            if why:
                st["blocked"] += 1; status["dropped"][why] = status["dropped"].get(why, 0) + 1
                continue
            is_ai = bool(AI_KW.search(title + " " + summ))
            if KIND.get(key) == "gnews" and not gn_ok(ch0, title):
                continue  # 聚合来源：标题里必须有本频道关键词，否则不收
            if need_ai and not is_ai:
                continue
            ch = "ai" if (ch0 in AI_MOVE and AI_KW.search(title)) else ch0
            if ch == "ai" and GOSSIP_KW.search(title):
                ch = "gossip"
            if ch == "gossip" and not GOSSIP_KW.search(title):
                ch = "ai"
            ch = r.get("ch") or route(ch, title, summ)
            seen.add(k)
            queue.setdefault(key, []).append((i, ch, title, summ, link, pub, r, lang))
    n_tr = 0
    llm_zh: dict[str, dict] = {}
    try:  # optional model: better Chinese titles/summaries for the English items about to go up (free translators stay as fallback)
        import llm
        if llm.available():
            want = []
            for key, q in queue.items():
                for (i, ch, title, summ, link, pub, r, lang) in q[:(30 if KIND.get(key) else per_source_cap(key))]:
                    if lang == "en" and not r.get("tpl"):
                        want.append({"id": i, "title": title, "text": summ[:400], "_pub": pub.isoformat()})
            want.sort(key=lambda x: x["_pub"], reverse=True)  # freshest first: they are the ones going up now
            llm_zh = llm.translate_batch(want[:MAX_NEW_TRANSLATE], scope="pipeline", kind="news", max_items=60, time_budget_s=150)
            print(f"[news] model translated {len(llm_zh)}/{len(want[:MAX_NEW_TRANSLATE])} (up to 60 fresh items per run go to the model)")
    except Exception as e:
        print("[news] model translate skipped:", type(e).__name__)
    order = [k for k in queue]
    rnd = 0
    while order and rnd < 30:
        for key in list(order):
            q = queue[key]
            if rnd >= len(q) or rnd >= (30 if KIND.get(key) else per_source_cap(key)):
                order.remove(key); continue
            i, ch, title, summ, link, pub, r, lang = q[rnd]
            _, name, home, *_r = SRC[key]
            if r.get("tpl"):
                tz = title
                sz = summ if (not summ or re.search(r"[\u4e00-\u9fff]", summ)) else (tr(summ[:300]) if tr and n_tr < MAX_NEW_TRANSLATE else "")
                if summ and not re.search(r"[\u4e00-\u9fff]", summ):
                    n_tr += 1
            elif lang == "en" and i in llm_zh:
                tz, sz = llm_zh[i]["title"], (llm_zh[i]["summary"] or (tr(summ[:300]) if (tr and summ) else ""))
                n_tr += 1
            elif lang == "en":
                if not tr or n_tr >= MAX_NEW_TRANSLATE:
                    continue  # 留到下次，不发未翻译的英文
                tz = tr(title); sz = tr(summ[:300]) if summ else ""
                n_tr += 1
                if not tz or tz.strip() == title:
                    continue
            else:
                tz, sz = title, summ
            why = blocked(tz, sz)  # 译文再过一遍
            if why:
                status["sources"][key]["blocked"] += 1; status["dropped"][why] = status["dropped"].get(why, 0) + 1
                continue
            zk = tkey(tz)[:20]
            if any(tkey(y.get("title"))[:20] == zk for y in old.values()):
                continue  # 不同来源的同一条新闻（中文标题相同）
            old[i] = {"id": i, "channel": ch, "title": re.sub(r"\s+", " ", tz).strip()[:120], "title_orig": title if (lang == "en" and not r.get("tpl")) else "",
                      "summary": (sz or "").strip()[:400], "summary_orig": summ if (lang != "zh" and not re.search(r"[\u4e00-\u9fff]", summ or "")) else "", "url": link, "hn": r.get("hn") or "",
                      "source": r.get("src") or name, "source_key": key, "source_home": home, "lang": lang,
                      "published_at": pub.isoformat(timespec="seconds"), "fetched_at": now.isoformat(timespec="seconds")}
            status["sources"][key]["new"] += 1; status["new"] += 1
        rnd += 1
    if fetch_auto:
        try:
            fetch_auto.save_translate_cache()
        except Exception:
            pass
    need = [x for x in old.values() if x.get("lang") == "zh" and not x.get("summary") and not x.get("_md")][:25]
    if need:
        with ThreadPoolExecutor(6) as ex:
            got = list(ex.map(lambda x: meta_desc(x["url"]), need))
        for x, dsc in zip(need, got):
            x["_md"] = 1
            if dsc and not blocked(dsc) and dsc[:20] not in x["title"]:
                x["summary"] = dsc
    keep, cutoff = [], now - timedelta(days=KEEP_DAYS)
    for x in old.values():  # re-filter stored items too: the blocklist may have grown
        if blocked(x.get("title"), x.get("summary"), x.get("title_orig"), x.get("summary_orig")):
            continue
        if x.get("lang") == "zh" and OFFTOPIC.search(x.get("title") or ""):
            continue
        if x["channel"] == "gossip" and not GOSSIP_KW.search(x.get("title_orig") or x.get("title") or ""):
            x["channel"] = "ai"
        x["channel"] = route(x["channel"], (x.get("title_orig") or "") + " " + (x.get("title") or ""), "")
        if (pdate(x.get("published_at")) or now) < cutoff:
            continue
        keep.append(x)
    keep.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    out, cnt = [], {}
    for x in keep:
        c = x["channel"]
        if cnt.get(c, 0) >= CAP.get(c, CAP_DEFAULT):
            continue
        cnt[c] = cnt.get(c, 0) + 1
        out.append(x)
    if sh:
        try:
            sh.save()
        except Exception:
            pass
    ok = sum(1 for v in status["sources"].values() if v["ok"])
    status.update({"sources_total": len(SOURCES), "sources_ok": ok, "translated": n_tr, "counts": cnt})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    if not out and db.get("items"):
        print("[news] nothing collected — keeping previous data")
        return 0
    OUT.write_text(json.dumps({"updated_at": now.isoformat(timespec="seconds"), "counts": cnt, "items": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[news] sources ok {ok}/{len(todo)} (skipped {len(status['skipped'])}) new={status['new']} translated={n_tr} total={len(out)} counts={cnt} dropped={sum(status['dropped'].values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
