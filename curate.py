#!/usr/bin/env python3
"""Content curation layer (runs inside build.py on every hourly rebuild).

Takes raw items from fetchers (data/YYYY-MM-DD.json, data/auto/*.json) plus editorial
items (data/curated.json, data/pinned.json) and produces clean, deduplicated, relevant,
categorised items with structured facts:

  relevance scoring (exclude when unsure) · dedupe · title/summary rewrite ·
  Google News redirect decode (drop if unresolvable) · t.co expansion · deadline → expires_at ·
  fetched_at / verified_at · how-to-claim extraction · recency archive · date normalisation ·
  glossary fixes · rule-based categorisation · facts (card / realname / china / free type) ·
  status (可领 / 即将过期 / 已过期 / 未核实) · data/item_facts.json overrides.

Network work (URL resolution, favicons) is cached in data/auto/*.json and bounded by a time
budget so a slow network can never break the build. Every decision is counted in a report.
"""
from __future__ import annotations

import email.utils
import hashlib
import html as _html
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import glossary

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
AUTO = DATA / "auto"
TZ = ZoneInfo("Asia/Shanghai")
CURATION_VERSION = "2026-11-09.c3"

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CTX = ssl.create_default_context()
NET_BUDGET = float(os.environ.get("CURATE_NET_BUDGET", "90"))
_NET_START = time.monotonic()
OFFLINE = os.environ.get("CURATE_OFFLINE") == "1"

ARCHIVE_DAYS = 30
MIN_YEAR = 2025
BOILER_HOW = ("打开来源链接按页面说明领取", "打开来源链接，按页面说明领取", "参与前自行核实", "参与前请自行核实")

# ---------------------------------------------------------------- categories / modules
CAT_API = "大模型 API 免费额度"
CAT_MEMBER = "AI 产品会员/试用"
CAT_DEV = "AI 开发工具与编程助手"
CAT_GPU = "云服务/GPU/开发者资源"
CAT_APP = "科技软件/App 限免"
CAT_COURSE = "AI 课程/活动"
CAT_OTHER = "其他科技"
CATEGORIES = [CAT_API, CAT_MEMBER, CAT_DEV, CAT_GPU, CAT_APP, CAT_COURSE, CAT_OTHER]

# ---------------------------------------------------------------- helpers

def now() -> datetime:
    return datetime.now(TZ)


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def budget_left() -> float:
    return NET_BUDGET - (time.monotonic() - _NET_START)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(TZ).isoformat(timespec="seconds") if dt else None


def label(dt: datetime | None) -> str:
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M") + " 北京时间" if dt else "未知"


def parse_dt(s) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    try:  # RFC 2822 (Google News / RSS)
        if re.match(r"^[A-Z][a-z]{2}, \d", s):
            d = email.utils.parsedate_to_datetime(s)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    m = re.match(r"^[A-Z][a-z]{2} ([A-Z][a-z]{2}) (\d{2}) (\d{2}):(\d{2}):(\d{2}) ([+-]\d{4}) (\d{4})$", s)
    if m:  # twitter legacy
        try:
            return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
        except Exception:
            return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=TZ)
    except Exception:
        pass
    m = re.match(r"^(20\d{2})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", s)
    if m:
        y, mo, d_, hh, mm = m.groups()
        try:
            return datetime(int(y), int(mo), int(d_), int(hh or 0), int(mm or 0), tzinfo=TZ)
        except Exception:
            return None
    return None


def norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    try:
        p = urllib.parse.urlsplit(u)
    except Exception:
        return u.rstrip("/")
    host = (p.netloc or "").lower().removeprefix("www.").removeprefix("mobile.")
    if host in ("twitter.com", "x.com"):
        host = "x.com"
    q = urllib.parse.parse_qsl(p.query)
    q = [(k, v) for k, v in q if not k.lower().startswith(("utm_", "ref", "s", "t")) or k.lower() in ("sid",)]
    if host == "x.com":
        q = []
    return urllib.parse.urlunsplit(("https", host, p.path.rstrip("/"), urllib.parse.urlencode(q), ""))


def domain(u: str) -> str:
    try:
        h = urllib.parse.urlsplit(u).netloc.lower()
    except Exception:
        return ""
    return h.removeprefix("www.")


# ---------------------------------------------------------------- URL resolution (cached)
URL_CACHE_PATH = AUTO / "url_cache.json"
_url_cache: dict | None = None
STATS = Counter()


def _ucache() -> dict:
    global _url_cache
    if _url_cache is None:
        _url_cache = load(URL_CACHE_PATH, {}) or {}
    return _url_cache


def _cache_get(u: str):
    e = _ucache().get(u)
    if not e:
        return None, False
    if e.get("to"):
        return e["to"], True
    # failed before: retry after 6h
    at = parse_dt(e.get("at"))
    if at and now() - at < timedelta(hours=6):
        return None, True
    return None, False


def _cache_put(u: str, to: str | None, err: str = "") -> None:
    _ucache()[u] = {"to": to, "at": iso(now()), **({"err": err} if err else {})}


def _http(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 12, method=None):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.status, r.geturl(), r.read().decode("utf-8", "replace")


def _gnews_decode(u: str) -> str | None:
    m = re.search(r"/(?:rss/)?articles/([A-Za-z0-9_\-]+)", u)
    if not m:
        return None
    aid = m.group(1)
    _, _, page = _http(f"https://news.google.com/rss/articles/{aid}?hl=en-US&gl=US&ceid=US:en")
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return None
    inner = (
        '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
        f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{aid}",{ts.group(1)},"{sg.group(1)}"]'
    )
    body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner, None, "generic"]]]))
    _, _, resp = _http(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        data=body.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
    )
    try:
        j = json.loads(resp.split("\n\n", 1)[1])
        out = json.loads(j[0][2])[1]
        return out if isinstance(out, str) and out.startswith("http") else None
    except Exception:
        return None


def resolve_gnews(u: str) -> str | None:
    hit, known = _cache_get(u)
    if known:
        STATS["gnews_cache_hit"] += 1
        return hit
    if OFFLINE or budget_left() <= 0:
        STATS["gnews_budget_skip"] += 1
        return None
    try:
        out = _gnews_decode(u)
        _cache_put(u, out, "" if out else "no-result")
        STATS["gnews_resolved_net" if out else "gnews_failed_net"] += 1
        time.sleep(0.25)
        return out
    except Exception as e:
        _cache_put(u, None, type(e).__name__)
        STATS["gnews_failed_net"] += 1
        return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_NR = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=CTX))


def expand_tco(u: str) -> str | None:
    hit, known = _cache_get(u)
    if known:
        return hit
    if OFFLINE or budget_left() <= 0:
        return None
    try:
        req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": "curl/8"})
        try:
            r = _NR.open(req, timeout=8)
            loc = r.headers.get("Location")
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location")
        out = loc if loc and loc.startswith("http") else None
        _cache_put(u, out, "" if out else "no-location")
        STATS["tco_expanded" if out else "tco_failed"] += 1
        return out
    except Exception as e:
        _cache_put(u, None, type(e).__name__)
        STATS["tco_failed"] += 1
        return None


# ---------------------------------------------------------------- text cleanup
URL_RX = re.compile(r"https?://\S+")
TCO_RX = re.compile(r"https?://t\.co/[A-Za-z0-9]{6,}")
EMOJI_RX = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2190-\u21FF\u2B00-\u2BFF\uFE0F\u200d\u20E3]+"
)


def strip_html(s: str) -> str:
    s = _html.unescape(s or "")
    s = re.sub(r"<\s*(p|br)\s*/?>", " ", s, flags=re.I)
    return re.sub(r"<[^>]+>", " ", s)


def clean_text(s: str) -> str:
    s = strip_html(s)
    s = URL_RX.sub(" ", s)
    s = EMOJI_RX.sub(" ", s)
    s = re.sub(r"(?:^|\s)RT @\w+[:：]?", " ", s)
    s = re.sub(r"\[\d+/\d+\]|（\d+/\d+）|\(\d+/\d+\)", " ", s)
    s = re.sub(r"#(\w+)", r"\1", s)
    s = re.sub(r"\s*[-–—]\s*X\s*$", "", s.strip())
    s = re.sub(r"\s+X\s*$", "", s)
    s = re.sub(r"(?m)\s*[-–—]\s*X\s*\n", "\n", s)
    s = re.sub(r"👇|👉|→\s*$", " ", s)
    s = re.sub(r"[ \t\u3000]+", " ", s)
    # collapse duplicated halves ("A -X\nA X")
    lines = [ln.strip(" -–—") for ln in s.split("\n") if ln.strip(" -–—")]
    uniq: list[str] = []
    for ln in lines:
        key = re.sub(r"\W", "", ln)[:40]
        if any(key and key in re.sub(r"\W", "", u) for u in uniq):
            continue
        uniq.append(ln)
    s = " ".join(uniq)
    s = re.sub(r"\s+", " ", s).strip(" -–—:：")
    return glossary.fix(s)


SENT_RX = re.compile(r"(?<=[。！？!?；])\s*|(?<=[.!?])\s+(?=[A-Z\u4e00-\u9fff])")


def sentences(s: str) -> list[str]:
    parts = [p.strip(" -–—•·") for p in SENT_RX.split(s or "")]
    return [p for p in parts if len(re.sub(r"\W", "", p)) >= 2]


def _fp(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower())


def trim(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    for sep in ("。", "；", "，", "、", " "):
        i = cut.rfind(sep)
        if i >= n * 0.55:
            return cut[:i].rstrip("，、 ") + "…"
    return cut.rstrip() + "…"


# ---------------------------------------------------------------- relevance
AI_RX = re.compile(
    r"(?<![A-Za-z])(?:AI|AGI|LLMs?|GPT[-\w.]*|NLP|RAG|MCP|TPU|NIM)(?![a-z])|人工智能|大模型|语言模型|模型|智能体|机器学习|深度学习|强化学习|神经网络|"
    r"(?i:claude|gemini|deepseek|qwen|llama|kimi|\bglm|mistral|grok|chatgpt|copilot|cursor|codex|hugging ?face|ollama|comfyui|"
    r"stable diffusion|openai|anthropic|openrouter|groq|\bagents?\b|embedding|tokens?\b)|"
    r"通义|智谱|百炼|文心|混元|豆包|方舟|千帆|硅基流动|NVIDIA|Colab|Kaggle|向量|推理|算力|GPU"
)
AI_STRICT = re.compile(
    r"(?<![A-Za-z])(?:AI|AGI|LLMs?|GPT[-\w.]*|NLP|RAG|MCP)(?![a-z])|人工智能|大模型|语言模型|模型|智能体|机器学习|深度学习|"
    r"(?i:claude|gemini|deepseek|qwen|llama|kimi|mistral|grok|chatgpt|copilot|codex|hugging ?face|ollama|comfyui|openai|anthropic|openrouter|\bagents?\b)"
)
TECH_RX = re.compile(r"API|SDK|开源|GitHub|编程|代码|开发者|云|服务器|Linux|CLI|IDE|数据库|部署|Python|JavaScript|Rust|Go\b", re.I)
POS_STRONG = re.compile(
    r"免费(?:额度|试用|使用|领取|调用|开放|提供|计划|套餐|层|版|档|GPU|API|Token|tokens?|积分|名额|访问|获得|赠送|测试|学习|算力|模型|体验)|"
    r"免费.{0,10}(?:课程|讲座|研讨会|工作坊|训练营|PDF|电子书|教科书|教程|认证|GPU|算力|Token|tokens?|额度|积分|credits?|API|试用)|"
    r"免费(?:向|对).{0,10}开放|限免|限时免费|白嫖|免费领|可领|赠送|免绑卡|无需信用卡|免信用卡|no credit card|free tier|free credits|学生免费|"
    r"新用户(?:赠送|免费|可领|送)|\d[\d,.]*\s*(?:万|亿|M|K)?\s*(?:tokens?|Tokens?|积分|credits?)\b|"
    r"(?:无需|不需要|免)\s*API\s*(?:Key|密钥)|完全免费|永久免费|长期免费|不限量",
    re.I,
)
POS_WEAK = re.compile(r"免费|开源|free|试用|trial|额度|报名|注册即", re.I)
NEG = re.compile(
    r"论文|研究发现|研究人员发现|随机试验|临床|患者|医学|医疗|放射科|胆固醇|筛查|融资|收购|B 轮|估值|裁员|诉讼|"
    r"股票|交易代理|交易员|金融|区块链|币安|加密|NFT|空投|Netflix|海贼王|盗版|争论|播客|时事通讯|newsletter|"
    r"我求求你|从我的 ?TL|我尝试|我将|我正在|我的教育主管|赠品|抽奖|giveaway|中转站|号池|转售|域名|广告|测试广告|"
    r"优惠券|折扣|打折|促销|SEC 数据|雇用谁|心脏|ZDNET|报道称|据报道|太阳出来|祝贺|感谢@|感谢 @|skool|SEO|营销团队|"
    r"反检测|绕过保护|指纹浏览器|2api\b|反代|逆向\s*API|取代你的|你的笔记本电脑可以|求职|招聘",
    re.I,
)


def _uniq(rx: re.Pattern, text: str) -> set[str]:
    return {m.group(0).lower() for m in rx.finditer(text)}


def relevance(text: str, kind: str, desc: str = "") -> tuple[int, str]:
    """Return (score, reason). kind: x | hn | v2ex | github. Exclude when unsure."""
    strong = _uniq(POS_STRONG, text)
    neg = _uniq(NEG, text)
    weak = _uniq(POS_WEAK, text)
    ai_ok = bool(AI_STRICT.search(desc if kind == "github" else text)) or (
        kind != "github" and re.search(r"免费.{0,6}(?:GPU|算力)|GPU.{0,6}(?:免费|额度)", text) and AI_RX.search(text))
    if not ai_ok:
        return -9, "not_ai"
    if neg:
        return -3 * len(neg), "negative_signal"
    if kind == "github":
        # open-source AI repos are free tools by definition; gray-area tooling is excluded via NEG
        return 2 + len(strong), "ok"
    if not strong:
        return len(weak), "no_clear_offer"
    score = 2 * len(strong) + min(len(weak), 2)
    return score, "ok" if score >= 3 else "no_clear_offer"


# ---------------------------------------------------------------- categorisation
CAT_RULES = [
    (CAT_COURSE, re.compile(r"课程|讲座|研讨会|工作坊|训练营|黑客松|hackathon|webinar|bootcamp|教科书|电子书|PDF|公开课|学院|认证|报名|大赛|比赛|活动|学习", re.I)),
    (CAT_GPU, re.compile(r"GPU|算力|云服务器|云桌面|云电脑|Colab|Kaggle|Notebook|显卡|H100|A100|T4|服务器|Workers|部署|托管|容器", re.I)),
    (CAT_API, re.compile(r"API|Token|tokens?|额度|调用|推理端点|endpoint|OpenRouter|模型服务|百炼|方舟|NIM|免费模型|模型选择|型号选择|积分", re.I)),
    (CAT_MEMBER, re.compile(r"会员|Pro\b|Plus\b|订阅|试用|通行证|Max\b|Premium|免费计划|免费版", re.I)),
    (CAT_DEV, re.compile(r"编程|代码|Copilot|Cursor|IDE|Agent|智能体|插件|扩展|CLI|SDK|开源|MCP|框架|技能|skill|GitHub|仓库", re.I)),
    (CAT_APP, re.compile(r"App|应用|限免|iOS|Android|Mac|Windows|软件|客户端", re.I)),
]


def categorize(text: str, kind: str, current: str | None) -> str:
    if kind == "curated" and current in CATEGORIES:
        return current
    if kind == "github":
        if re.search(r"awesome-free|free-?llm|免费\s*(?:的\s*)?(?:LLM|大模型|AI)?\s*API(?!\s*密钥)|LLM\s*API|API\s*(?:列表|清单|导航|目录)|推理端点|免费模型", text, re.I):
            return CAT_API
        if re.search(r"免费\s*GPU|GPU\s*额度|免费算力", text, re.I):
            return CAT_GPU
        return CAT_DEV
    for cat, rx in CAT_RULES:
        if rx.search(text):
            if cat == CAT_COURSE and not re.search(r"免费|free", text, re.I):
                continue
            return cat
    return CAT_OTHER


# ---------------------------------------------------------------- facts
def _has(rx: str, t: str) -> bool:
    return bool(re.search(rx, t, re.I))


def infer_facts(text: str) -> dict:
    t = text
    card = "unknown"
    if _has(r"部分.{0,8}(?:需)?绑卡|部分.{0,6}信用卡", t):
        card = "partial"
    elif _has(r"免绑卡|无需(?:绑定)?(?:信用)?卡|不(?:需要|用)(?:绑)?(?:信用)?卡|无须(?:绑)?卡|no credit card|without (?:a )?credit card|不需要付款", t):
        card = "no"
    elif _has(r"需(?:要)?绑(?:定)?(?:信用|银行)?卡|绑卡后|需(?:要)?信用卡|credit card required|验证信用卡", t):
        card = "yes"
    real = "unknown"
    if _has(r"实名后(?:可)?再领|实名可(?:额外|再)", t):
        real = "partial"
    elif _has(r"无需(?:实名|手机号|注册)|免注册|不需要注册|无需登录|no sign[- ]?up|没有注册", t):
        real = "no"
    elif _has(r"实名|手机(?:号)?验证|手机号|身份证|人脸", t):
        real = "yes"
    china = "unknown"
    if _has(r"需(?:要)?(?:海外|外网|翻墙|代理|科学上网)|国内(?:无法|不可|不能)|海外网络|仅限(?:美国|海外)", t):
        china = "no"
    elif _has(r"国内(?:可)?直连|国内可用|国区|国内可直接访问|无需翻墙|国内网络可", t):
        china = "yes"
    ftype = "unknown"
    if _has(r"试用|trial|首月|天免费|通行证|体验期|限时免费|一周|免费测试|前\s*\d+\s*天", t):
        ftype = "trial"
    elif _has(r"每(?:天|日|周|月)|额度|tokens?|积分|credits?|限额|次/|小时/|配额|免费层|free tier|限速|上限", t):
        ftype = "quota"
    elif _has(r"永久免费|长期免费|完全免费|开源|免费开放|MIT 许可|Apache", t):
        ftype = "permanent"
    return {"requires_card": card, "requires_realname": real, "china_accessible": china, "type": ftype}


EXPIRY_LABEL = {
    "deadline": "有截止日期", "daily": "按日重置", "periodic": "按周/月发放",
    "limited": "限期试用", "long": "长期有效", "unknown": "未注明",
}


def expiry_kind(text: str, expires_at: str | None) -> str:
    if expires_at:
        return "deadline"
    if _has(r"每(?:天|日)(?:.{0,10})(?:重置|刷新|恢复|赠送|免费)|daily|每日额度|次日恢复", text):
        return "daily"
    if _has(r"每(?:周|月)(?:.{0,10})(?:发放|获得|赠送|重置|刷新)|每月获得|monthly", text):
        return "periodic"
    if _has(r"\d+\s*天(?:内)?有效|有效期|试用期|一周|首月|\d+\s*天免费|限时", text):
        return "limited"
    if _has(r"永久|长期有效|长期免费|不过期", text):
        return "long"
    return "unknown"


MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


def extract_deadline(text: str, en: str, posted: datetime | None, existing=None) -> datetime | None:
    base = (posted or now()).astimezone(TZ)

    def mk(y, mo, d):
        try:
            return datetime(y, mo, d, 23, 59, 59, tzinfo=TZ)
        except Exception:
            return None

    if existing:
        d = parse_dt(existing)
        if d:
            return d.replace(hour=23, minute=59, second=59) if d.hour == 0 and d.minute == 0 else d
    m = re.search(r"(?:截止|截至|截止日期|到期|有效期至|deadline|until|before|ends?|by)[^0-9]{0,8}(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text + " " + en, re.I)
    if m:
        return mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(?:截止(?:日期)?(?:为|是)?|截至|到|至|于|deadline is|until|before|ends)\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = base.year
        dt = mk(y, mo, d)
        if dt and dt < base - timedelta(days=60):
            dt = mk(y + 1, mo, d)
        return dt
    m = re.search(r"(?:deadline(?: is)?|until|before|ends?|by|through)\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})", en or "", re.I)
    if m:
        mo, d = MONTHS[m.group(1).lower()], int(m.group(2))
        dt = mk(base.year, mo, d)
        if dt and dt < base - timedelta(days=60):
            dt = mk(base.year + 1, mo, d)
        return dt
    return None


HOW_RX = re.compile(r"^(?:先|直接|只需|即可|请)?(?:注册|报名|登录|申请|领取|访问|前往|打开|点击|填写|安装|sign up|register|apply|claim|visit)", re.I)


def extract_how(sents: list[str], used: set[str]) -> str:
    """Concrete claim steps only (imperative sentence naming an action); otherwise omit."""
    out = []
    for s in sents:
        f = _fp(s)
        if not f or any(f in u or u in f for u in used if u) or any(b in s for b in BOILER_HOW):
            continue
        if HOW_RX.search(s.strip()) and 8 <= len(s) <= 120 and not re.search(r"下面|如下|链接在|见评论|在\s*中[。.]?$", s):
            out.append(s)
        if len(out) >= 2:
            break
    return " ".join(out)


# ---------------------------------------------------------------- title / summary rewrite
FLUFF_RX = re.compile(r"^(?:重磅|突发|刚刚|太棒了|好消息|速看|注意|提醒|大消息|最新|快讯)[!！:：,，\s]*")


def prefer_cjk(text: str) -> str:
    """Bilingual descriptions: keep the Chinese part when one exists."""
    if not re.search(r"[\u4e00-\u9fff]", text or ""):
        return text
    parts = re.split(r"\s*[|｜]\s*|(?<=[.!?])\s+(?=[\u4e00-\u9fff])|(?<=[。！？])\s*(?=[A-Z][a-z])", text)
    zh = [p for p in parts if len(re.findall(r"[\u4e00-\u9fff]", p)) >= 4]
    return " ".join(zh) if zh else text


def rewrite(raw_title: str, raw_summary: str, kind: str, original_title: str = "", extra: dict | None = None) -> tuple[str, str, list[str]]:
    extra = extra or {}
    if kind == "github":
        name = (original_title or "").strip()
        if "/" not in name:
            name = extra.get("name") or name
        repo = name.split("/")[-1] if name else ""
        desc = clean_text(raw_summary or raw_title)
        if name:
            desc = re.sub(r"[（(]\s*" + re.escape(name) + r"\s*[)）]", "", desc, flags=re.I)
            desc = re.sub(re.escape(name), "", desc, flags=re.I)
        desc = re.sub(r"\s{2,}", " ", prefer_cjk(desc.strip(" ：:-—…")))
        ss = sentences(desc) or ([desc] if desc else [])
        if not ss:
            return repo, "", []
        first = ss[0].rstrip("。.!！…")
        clauses = [c for c in re.split(r"(?<=[，,；;：:—])\s*", first) if c.strip(" ，,；;：:—")]
        head = clauses[0].rstrip("，,；;：:— ")
        used = 1
        while len(head) < 14 and used < len(clauses) and len(head) + len(clauses[used]) <= 52:
            head = head + "，" + clauses[used].rstrip("，,；;：:— ")
            used += 1
        complete = True
        if len(head) > 52 or head.count("（") > head.count("）") or head.count("(") > head.count(")"):
            cut = trim(head, 52).rstrip("…")
            cut = re.sub(r"[（(][^）)]*$", "", cut).rstrip("，,、 ")
            head, complete = cut, False
        title = f"{repo}：{head}" if repo else head
        if complete:
            rest_txt = desc[desc.find(head) + len(head):] if head in desc else ""
            rest_txt = "，".join(clauses[used:]) + ("。" if clauses[used:] else "") + " " + " ".join(ss[1:]) if head not in desc else rest_txt
        else:
            rest_txt = desc
        rest_txt = re.sub(r"^[\s，,；;：:—。.…、]+", "", rest_txt)
        summ = ""
        for x in sentences(rest_txt):
            if summ and len(summ) + len(x) > 150:
                break
            summ += x if re.search(r"[。！？!?.…]$", x) else x + "。"
        if len(_fp(summ)) < 6:
            bits = [f"开源仓库 {name}"]
            if extra.get("language"):
                bits.append(f"主要语言 {extra['language']}")
            summ = "，".join(bits) + "。"
        return title, trim(summ, 160), ss
    body = clean_text(raw_summary)
    tl = clean_text(raw_title)
    hn_rx = r"^(?:Show HN|显示 ?HN|展示 ?HN|Ask HN|询问 ?HN|Tell HN|告诉 ?HN)\s*[:：]\s*"
    if kind == "hn":
        tl = re.sub(hn_rx, "", tl, flags=re.I)
        body = re.sub(hn_rx, "", body, flags=re.I)
        if tl and body.startswith(tl):
            body = body[len(tl):]
        tl = re.sub(r"\s+[–—-]\s+", "：", tl, count=1)
        body = re.sub(r"^\s*(?:Hi|Hey|Hello)\s*HN[，,!！]?\s*|^\s*大家好[，,]?\s*", "", body.strip(), flags=re.I)
    if kind == "v2ex":
        tl = re.sub(r"^\[([^\]]+)\]\s*", r"\1：", tl)
        if tl and body.startswith(tl):
            body = body[len(tl):]
    body = prefer_cjk(body)
    if kind == "x":
        # split rhetorical hooks glued to the headline ("… PDF（158 页） 想要了解…？") and keep questions out of the title
        body = re.sub(r"\s+(?=(?:想要|想学|如果你|你是否|有没有|是否想))", "。", body)
        ss = [FLUFF_RX.sub("", x) for x in sentences(body)]
        ss = [x for x in ss if not re.search(r"[？?]$", x)] or ss
    else:
        ss = [tl] + [FLUFF_RX.sub("", x) for x in sentences(body)] if tl else [FLUFF_RX.sub("", x) for x in sentences(body)]
    ss = [x for x in ss if x]
    if not ss:
        return tl, "", []
    title = ss[0].rstrip("。.!！;；")
    idx = 1
    while len(title) < 12 and idx < len(ss):
        title = title + "，" + ss[idx].rstrip("。.!！;；")
        idx += 1
    if len(title) > 64:
        title = trim(title, 64).rstrip("…")
    tfp = _fp(title)
    # name who is giving it: when the headline has no named product/brand up front, credit the poster
    if kind == "x" and extra.get("handle") and not re.search(r"^.{0,14}?[A-Za-z][A-Za-z0-9.\-]+(?<!AI)\b|：", title[:24]):
        title = f"@{extra['handle']} 分享：{title}"
    rest = [x for x in ss[idx:] if _fp(x) and _fp(x) not in tfp and tfp not in _fp(x)]
    summ = ""
    for x in rest:
        if summ and len(summ) + len(x) > 150:
            break
        summ += x if re.search(r"[。！？!?.…]$", x) else x + "。"
        if len(summ) >= 60:
            break
    return title, trim(summ, 160), ss


# ---------------------------------------------------------------- favicons (cached)
FAV_DIR = ROOT / "assets" / "favicons"


def favicon(dom: str) -> str | None:
    """Return site-relative favicon path for a domain, fetching once at build time."""
    if not dom:
        return None
    safe = re.sub(r"[^a-z0-9.\-]", "", dom.lower())
    p = FAV_DIR / f"{safe}.png"
    miss = FAV_DIR / f"{safe}.miss"
    if p.exists() and p.stat().st_size > 60:
        return f"assets/favicons/{safe}.png"
    if miss.exists() or OFFLINE or budget_left() <= 0:
        return None
    try:
        req = urllib.request.Request(f"https://www.google.com/s2/favicons?domain={safe}&sz=64", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8, context=CTX) as r:
            data = r.read()
        if len(data) > 60 and data[:4] == b"\x89PNG":
            FAV_DIR.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            STATS["favicon_fetched"] += 1
            return f"assets/favicons/{safe}.png"
    except Exception:
        pass
    FAV_DIR.mkdir(parents=True, exist_ok=True)
    miss.write_text("", encoding="utf-8")
    return None


SOURCE_LABEL = {
    "x.com": "X", "github.com": "GitHub", "news.ycombinator.com": "Hacker News", "v2ex.com": "V2EX",
}


# ---------------------------------------------------------------- main pipeline
def _kind(it: dict) -> str:
    s = (it.get("source") or "").lower()
    if it.get("_curated"):
        return "curated"
    if "github" in s:
        return "github"
    if "hacker" in s:
        return "hn"
    if "v2ex" in s:
        return "v2ex"
    return "x"


def _stable_id(it: dict, url: str) -> str:
    if it.get("id") and not str(it["id"]).startswith("xrss-"):
        return str(it["id"])
    return "r-" + hashlib.sha1(url.encode()).hexdigest()[:12]


def load_raw() -> tuple[list[dict], list[str]]:
    raw = []
    days = set()
    for base in (DATA, AUTO):
        for f in sorted(base.glob("????-??-??.json"), reverse=True):
            d = load(f, {}) or {}
            days.add(f.stem)
            for it in d.get("items") or []:
                it = dict(it)
                it.setdefault("source", "X" if base == DATA else "auto")
                it["_day"] = f.stem
                raw.append(it)
    cur = load(DATA / "curated.json", {}) or {}
    for it in cur.get("items") or []:
        it = dict(it, _curated=True)
        it["_day"] = (str(it.get("posted_at") or "")[:10]) or None
        raw.append(it)
    return raw, sorted(days, reverse=True)


def curate(pins: list[dict] | None = None) -> dict:
    t0 = time.monotonic()
    nowdt = now()
    raw, days = load_raw()
    overrides = (load(DATA / "item_facts.json", {}) or {}).get("items") or {}
    first_seen = load(AUTO / "first_seen.json", {}) or {}
    dead = {norm_url(u) for u in ((load(DATA / "link_health.json", {}) or {}).get("dead") or [])}
    report = Counter()
    drops: dict[str, list[str]] = {}
    gnews_total = 0

    def drop(reason, it, title=""):
        report[f"drop:{reason}"] += 1
        drops.setdefault(reason, [])
        if len(drops[reason]) < 12:
            drops[reason].append((title or it.get("title") or "")[:60])

    pin_urls = {norm_url(p.get("url")) for p in (pins or [])}
    out: list[dict] = []
    seen_url: dict[str, dict] = {}
    seen_fp: dict[str, dict] = {}
    report["raw_total"] = len(raw)
    # curated first so that they win dedupe
    raw.sort(key=lambda i: 0 if i.get("_curated") else 1)
    for it in raw:
        kind = _kind(it)
        url = (it.get("url") or "").strip()
        if not url:
            drop("no_url", it)
            continue
        if "news.google.com" in url:
            gnews_total += 1
            real = resolve_gnews(url)
            if not real:
                drop("google_news_unresolved", it)
                continue
            report["google_news_resolved"] += 1
            url = real
        if re.match(r"https?://t\.co/", url):
            url = expand_tco(url) or url
        nurl = norm_url(url)
        if nurl in dead:
            drop("dead_link", it)
            continue
        if nurl in pin_urls:
            drop("duplicate_of_pinned", it)
            continue
        posted = parse_dt(it.get("posted_at") or it.get("created_at"))
        if posted and posted.year < MIN_YEAR and kind != "curated":
            drop("too_old_pre2025", it)
            continue
        if not posted and kind == "x":
            m = re.search(r"/status/(\d{15,})", url)
            if m:  # snowflake → timestamp
                ms = (int(m.group(1)) >> 22) + 1288834974657
                posted = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        # links inside the text (t.co) → expanded outbound links
        links = []
        for t in TCO_RX.findall((it.get("original_summary") or "") + " " + (it.get("summary") or "")):
            e = expand_tco(t)
            if e and domain(e) not in ("x.com", "twitter.com") and e not in links:
                links.append(e)
        if kind == "curated":
            title = glossary.fix(it.get("title") or "")
            summary = glossary.fix(it.get("summary") or "")
            ss = sentences(summary)
        else:
            ot = it.get("original_title") or ""
            title, summary, ss = rewrite(it.get("title") or "", it.get("summary") or "", kind, ot,
                                         {"name": it.get("name"), "language": it.get("language"),
                                          "handle": (re.search(r"x\.com/([A-Za-z0-9_]{1,15})/status/", url) or [None, None])[1]})
        en = (it.get("original_title") or "") + " " + (it.get("original_summary") or "")
        text = f"{title} {summary} {' '.join(ss)} {' '.join(domain(x) for x in links)}"
        if kind != "curated":
            score, why = relevance(text + " " + en, kind, summary if kind == "github" else "")
            if why != "ok":
                drop(why, it, title)
                continue
        if not summary.strip():
            drop("empty_summary", it, title)
            continue
        fp = _fp(title)[:28]
        if nurl in seen_url or (fp and fp in seen_fp):
            drop("duplicate", it, title)
            continue
        expires = extract_deadline(text, en, posted, it.get("deadline") or it.get("expires_at"))
        cat = categorize(text, kind, it.get("category"))
        facts = infer_facts(" ".join([title, summary, it.get("how") or "" if not any(b in (it.get("how") or "") for b in BOILER_HOW) else ""]))
        how = it.get("how") or ""
        if any(b in how for b in BOILER_HOW):
            how = ""
        if not how and kind != "curated":
            how = extract_how(ss, {_fp(title), _fp(summary)})
        iid = _stable_id(it, nurl)
        fs = first_seen.get(iid)
        if not fs:
            fs = iso(nowdt)
            first_seen[iid] = fs
            report["new_this_run"] += 1
        rec = {
            "id": iid,
            "title": title,
            "summary": summary,
            "url": url,
            "source": SOURCE_LABEL.get(domain(url), domain(url) or "未知"),
            "source_domain": domain(url),
            "source_name": "编辑整理" if kind == "curated" else (it.get("source") or ""),
            "author": it.get("author") or "",
            "category": cat,
            "how": glossary.fix(how),
            "links": links[:3],
            "published_at": iso(posted),
            "published_label": label(posted) if posted else "未知",
            "fetched_at": fs,
            "verified_at": it.get("verified_at"),
            "expires_at": iso(expires),
            "time_limited": "yes" if expires or facts["type"] == "trial" else ("no" if facts["type"] == "permanent" else "unknown"),
            "_kind": kind,
            "_day": it.get("_day"),
            **facts,
        }
        if kind == "github":
            rec["type"] = "permanent"  # open-source software
            rec["time_limited"] = "no" if not expires else "yes"
        ov = overrides.get(iid) or overrides.get(nurl)
        if ov:
            rec.update({k: v for k, v in ov.items() if not k.startswith("_")})
            report["facts_overridden"] += 1
        rec["expiry_kind"] = expiry_kind(text, rec["expires_at"])
        if rec["expires_at"]:
            report["deadline_extracted"] += 1
        out.append(rec)
        seen_url[nurl] = rec
        if fp:
            seen_fp[fp] = rec
    # status + archive
    for rec in out:
        set_status(rec, nowdt)
    report["kept_total"] = len(out)
    report["archived"] = sum(1 for r in out if r["status"] in ("archived", "expired"))
    report["google_news_total"] = gnews_total
    report.update({f"net:{k}": v for k, v in STATS.items()})
    save(AUTO / "first_seen.json", {k: v for k, v in first_seen.items()})
    if _url_cache is not None:
        save(URL_CACHE_PATH, _url_cache)
    repair_translation_cache()
    rep = {
        "curation_version": CURATION_VERSION,
        "generated_at": iso(nowdt),
        "seconds": round(time.monotonic() - t0, 1),
        "counts": dict(sorted(report.items())),
        "drop_examples": drops,
    }
    save(AUTO / "curation_report.json", rep)
    return {"items": out, "days": days, "report": rep}


def set_status(rec: dict, nowdt: datetime) -> None:
    exp = parse_dt(rec.get("expires_at"))
    pub = parse_dt(rec.get("published_at")) or parse_dt(rec.get("fetched_at"))
    if exp and exp < nowdt:
        rec["status"] = "expired"
    elif exp and exp - nowdt <= timedelta(days=7):
        rec["status"] = "expiring"
    elif rec.get("_kind") != "curated" and not rec.get("pinned") and pub and nowdt - pub > timedelta(days=ARCHIVE_DAYS) and not exp:
        rec["status"] = "archived"
    elif rec.get("verified_at"):
        rec["status"] = "available"
    else:
        rec["status"] = "unverified"


STATUS_LABEL = {"available": "可领", "expiring": "即将过期", "expired": "已过期", "unverified": "未核实", "archived": "已归档"}


def curate_side(items: list[dict], kind: str) -> tuple[list[dict], Counter]:
    """GitHub hot / hot topics: AI/tech relevance, dedupe, glossary, no engagement fields."""
    rep = Counter()
    out, seen = [], set()
    for it in items:
        rep["raw"] += 1
        title = clean_text(it.get("title") or it.get("name") or "")
        summary = clean_text(it.get("summary") or it.get("description") or "")
        en = (it.get("original_title") or "") + " " + (it.get("original_summary") or it.get("summary_en") or "")
        text = f"{title} {summary} {en}"
        if not AI_RX.search(text):
            rep["drop:not_ai"] += 1
            continue
        if kind == "hot" and NEG.search(text) and not re.search(r"Claude|GPT|Gemini|DeepSeek|LLM|模型|Agent|AI", title):
            rep["drop:negative_signal"] += 1
            continue
        u = norm_url(it.get("url") or "")
        fp = _fp(title)[:28]
        if not u or u in seen or fp in seen:
            rep["drop:duplicate"] += 1
            continue
        seen.update({u, fp})
        if kind == "github":
            name = it.get("name") or it.get("original_title") or ""
            title = f"{name.split('/')[-1]}：{trim(re.sub(r'[（(][^）)]*[）)]$', '', title).strip(), 48)}" if name else title
            if _fp(summary) and _fp(summary) in _fp(title):
                summary = f"开源仓库 {name}" + (f"，主要语言 {it.get('language')}" if it.get("language") else "") + "。"
        elif _fp(summary) == _fp(title) or not summary:
            summary = ""
        rec = {
            "id": it.get("id") or "",
            "title": title,
            "summary": summary,
            "url": it.get("url") or "",
            "source": it.get("source") or ("GitHub" if kind == "github" else ""),
            "source_domain": domain(it.get("url") or ""),
        }
        if kind == "github":
            rec.update(name=it.get("name") or "", stars=it.get("stars"), language=it.get("language") or "",
                       created_at=iso(parse_dt(it.get("created_at"))))
        out.append(rec)
    rep["kept"] = len(out)
    return out, rep


def repair_translation_cache() -> int:
    """Apply glossary to cached translations; drop entries that are still bad so they re-translate."""
    p = AUTO / "translations.json"
    d = load(p, None)
    if not isinstance(d, dict):
        return 0
    changed = 0
    for k, v in list(d.items()):
        if not isinstance(v, str):
            continue
        f = glossary.fix(v)
        if glossary.is_bad(f):
            del d[k]
            changed += 1
        elif f != v:
            d[k] = f
            changed += 1
    if changed:
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    STATS["translation_cache_repaired"] = changed
    return changed


if __name__ == "__main__":
    res = curate()
    print(json.dumps(res["report"]["counts"], ensure_ascii=False, indent=1))
