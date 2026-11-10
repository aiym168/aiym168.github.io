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
CAP = {"ai": 160, "gossip": 80, "tech": 200}
MAX_NEW_TRANSLATE = 36  # 每次最多新翻译多少条英文（控制免费翻译接口的压力）

# (key, 名称, 首页, feed, 默认频道, 语言, 是否需要 AI 关键词才收)
SOURCES = [
    ("techcrunch-ai", "TechCrunch", "https://techcrunch.com/", "https://techcrunch.com/category/artificial-intelligence/feed/", "ai", "en", False),
    ("verge-ai", "The Verge", "https://www.theverge.com/", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "ai", "en", False),
    ("openai", "OpenAI", "https://openai.com/news/", "https://openai.com/news/rss.xml", "ai", "en", False),
    ("deepmind", "Google DeepMind", "https://deepmind.google/discover/blog/", "https://deepmind.google/blog/rss.xml", "ai", "en", False),
    ("google-ai", "Google AI", "https://blog.google/technology/ai/", "https://blog.google/technology/ai/rss/", "ai", "en", False),
    ("huggingface", "Hugging Face", "https://huggingface.co/blog", "https://huggingface.co/blog/feed.xml", "ai", "en", False),
    ("decoder", "The Decoder", "https://the-decoder.com/", "https://the-decoder.com/feed/", "ai", "en", False),
    ("mittr-ai", "MIT Technology Review", "https://www.technologyreview.com/", "https://www.technologyreview.com/topic/artificial-intelligence/feed", "ai", "en", False),
    ("wired-ai", "WIRED", "https://www.wired.com/tag/ai/", "https://www.wired.com/feed/tag/ai/latest/rss", "ai", "en", False),
    ("qbitai", "量子位", "https://www.qbitai.com/", "https://www.qbitai.com/feed", "ai", "zh", False),
    ("simonw", "Simon Willison", "https://simonwillison.net/", "https://simonwillison.net/atom/everything/", "gossip", "en", True),
    ("hn", "Hacker News", "https://news.ycombinator.com/", "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=60", "tech", "en", False),
    ("ithome", "IT之家", "https://www.ithome.com/", "https://www.ithome.com/rss/", "tech", "zh", False),
    ("sspai", "少数派", "https://sspai.com/", "https://sspai.com/feed", "tech", "zh", False),
    ("geekpark", "极客公园", "https://www.geekpark.net/", "https://www.geekpark.net/rss", "tech", "zh", False),
    ("ifanr", "爱范儿", "https://www.ifanr.com/", "https://www.ifanr.com/feed", "tech", "zh", False),
    ("infoq", "InfoQ 中文", "https://www.infoq.cn/", "https://www.infoq.cn/feed", "tech", "zh", False),
    ("oschina", "开源中国", "https://www.oschina.net/news", "https://www.oschina.net/news/rss", "tech", "zh", False),
    ("verge", "The Verge", "https://www.theverge.com/", "https://www.theverge.com/rss/index.xml", "tech", "en", False),
    ("ars", "Ars Technica", "https://arstechnica.com/", "https://feeds.arstechnica.com/arstechnica/technology-lab", "tech", "en", False),
    ("engadget", "Engadget", "https://www.engadget.com/", "https://www.engadget.com/rss.xml", "tech", "en", False),
]
SRC = {s[0]: s for s in SOURCES}

# ---- content filter (when unsure, drop) -------------------------------------------------------
BLOCK_ZH = """色情 黄色 低俗 裸 露点 性感 性爱 性交 性侵 性骚扰 强奸 猥亵 嫖 卖淫 约炮 情色 成人片 成人内容 艳照 不雅 走光 床照 偷拍 乳房 胸部 臀 内衣 比基尼 OnlyFans 擦边
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
stock tip|pump and dump|memecoin|spy|spies|espionage|affair|mistress|cheating on|beijing|china|chinese|sovereign|national security|govcloud|geopolit|chip ban"""
BZH = [w for w in BLOCK_ZH.split() if w]
BEN = re.compile(r"\b(?:" + BLOCK_EN.replace("\n", "") + r")", re.I)
AI_KW = re.compile(r"\b(ai|a\.i\.|llm|llms|gpt|chatgpt|openai|claude|anthropic|gemini|deepmind|llama|mistral|deepseek|qwen|copilot|agent|agents|neural|machine learning|"
                   r"diffusion|transformer|hugging ?face|nvidia|cursor|midjourney|sora|perplexity|grok|xai)\b|人工智能|大模型|智能体|机器学习|生成式|AIGC|算力", re.I)
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
def get(url: str, timeout: int = 20) -> bytes:
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
        raw = get(url)
        if key == "hn":
            hits = json.loads(raw).get("hits") or []
            rows = [{"title": h.get("title") or "", "link": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                     "desc": "", "date": h.get("created_at"), "hn": f"https://news.ycombinator.com/item?id={h.get('objectID')}"}
                    for h in hits if (h.get("points") or 0) >= 80]
        else:
            rows = parse_feed(raw)
        return key, rows[:40], ""
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


def main() -> int:
    now = datetime.now(TZ)
    try:
        db = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        db = {"items": []}
    old = {x["id"]: x for x in db.get("items") or []}
    status = {"run_at": now.isoformat(timespec="seconds"), "sources": {}, "dropped": {}, "new": 0}
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(fetch_source, SOURCES))
    try:
        sys.path.insert(0, str(ROOT))
        import fetch_auto  # free_translate + cache
        tr = fetch_auto.free_translate
    except Exception as e:
        print("[news] translator unavailable:", e)
        fetch_auto, tr = None, None
    n_tr = 0
    seen_titles = {re.sub(r"\W+", "", (x.get("title_orig") or x.get("title") or "").lower())[:60] for x in old.values()}
    for key, rows, err in res:
        _, name, home, _u, ch0, lang, need_ai = SRC[key]
        st = {"ok": not err, "error": err, "rows": len(rows), "new": 0, "blocked": 0}
        for r in rows:
            title = clean(r.get("title") or "")
            link = norm_url(r.get("link") or "")
            if not title or not link.startswith("http"):
                continue
            i = nid(link)
            tkey = re.sub(r"\W+", "", title.lower())[:60]
            if i in old or tkey in seen_titles:
                continue
            pub = pdate(r.get("date")) or now
            if pub < now - timedelta(days=KEEP_DAYS) or pub > now + timedelta(hours=2):
                continue
            summ = summary_of(r.get("desc") or "", lang)
            why = blocked(title, summ, link)
            if why:
                st["blocked"] += 1; status["dropped"][why] = status["dropped"].get(why, 0) + 1
                continue
            if lang == "zh" and OFFTOPIC.search(title):
                st["blocked"] += 1; status["dropped"]["(非科技)"] = status["dropped"].get("(非科技)", 0) + 1
                continue
            is_ai = bool(AI_KW.search(title + " " + summ))
            if need_ai and not is_ai:
                continue
            ch = "ai" if (ch0 == "tech" and is_ai) else ch0
            if ch == "ai" and GOSSIP_KW.search(title):
                ch = "gossip"
            if key == "simonw" and not GOSSIP_KW.search(title):
                ch = "ai"
            if lang == "en":
                if not tr or n_tr >= MAX_NEW_TRANSLATE:
                    continue  # 下次再译，不发未翻译的英文
                tz = tr(title); sz = tr(summ) if summ else ""
                n_tr += 1
                if not tz or tz.strip() == title:
                    continue
            else:
                tz, sz = title, summ
            why = blocked(tz, sz)  # 译文再过一遍
            if why:
                st["blocked"] += 1; status["dropped"][why] = status["dropped"].get(why, 0) + 1
                continue
            old[i] = {"id": i, "channel": ch, "title": re.sub(r"\s+", " ", tz).strip()[:120], "title_orig": title if lang == "en" else "",
                      "summary": (sz or "").strip()[:400], "summary_orig": summ if lang == "en" else "", "url": link, "hn": r.get("hn") or "",
                      "source": name, "source_key": key, "source_home": home, "lang": lang,
                      "published_at": pub.isoformat(timespec="seconds"), "fetched_at": now.isoformat(timespec="seconds")}
            seen_titles.add(tkey)
            st["new"] += 1; status["new"] += 1
        status["sources"][key] = st
    need = [x for x in old.values() if x.get("lang") == "zh" and not x.get("summary") and not x.get("_md")][:25]
    if need:
        with ThreadPoolExecutor(6) as ex:
            got = list(ex.map(lambda x: meta_desc(x["url"]), need))
        for x, dsc in zip(need, got):
            x["_md"] = 1
            if dsc and not blocked(dsc) and dsc[:20] not in x["title"]:
                x["summary"] = dsc
    if fetch_auto:
        try:
            fetch_auto.save_translate_cache()
        except Exception:
            pass
    keep, cutoff = [], now - timedelta(days=KEEP_DAYS)
    for x in old.values():  # re-filter old items too: the blocklist may have grown
        if blocked(x.get("title"), x.get("summary"), x.get("title_orig"), x.get("summary_orig")):
            continue
        if x.get("lang") == "zh" and OFFTOPIC.search(x.get("title") or ""):
            continue
        if x["channel"] == "gossip" and not GOSSIP_KW.search(x.get("title_orig") or x.get("title") or ""):
            x["channel"] = "ai"
        if (pdate(x.get("published_at")) or now) < cutoff:
            continue
        keep.append(x)
    keep.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    out, cnt = [], {}
    for x in keep:
        c = x["channel"]
        if cnt.get(c, 0) >= CAP.get(c, 100):
            continue
        cnt[c] = cnt.get(c, 0) + 1
        out.append(x)
    if not out and db.get("items"):
        print("[news] nothing collected — keeping previous data")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated_at": now.isoformat(timespec="seconds"), "counts": cnt, "items": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for v in status["sources"].values() if v["ok"])
    print(f"[news] sources ok {ok}/{len(SOURCES)} new={status['new']} translated={n_tr} counts={cnt} dropped={sum(status['dropped'].values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
