#!/usr/bin/env python3
"""全球优惠情报：采集 → 去重 → 核实 → 字段提取 → 估值 → 归档，写入 data/deals/db.json。

只用标准库（GitHub Actions 与备用服务器都能直接运行）。任何来源失败都不会让整个流程失败。
来源分三类：
  official_api  交易所 / 商店的官方公告接口（币安、KuCoin、Epic 等）——活动时间等从官方正文自动提取
  official_feed 官方博客 RSS（GitHub Changelog、OpenAI 新闻等）——按优惠关键词过滤
  third_party   第三方优惠聚合 RSS（Doctor of Credit、LowEndBox）——一律标「待核实」，等待官方链接复核
  curated       data/deals/curated.json 里编辑核实过的条目——每 6 小时回访官网复核关键文字
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DDIR = ROOT / "data" / "deals"
DB_PATH = DDIR / "db.json"
CURATED_PATH = DDIR / "curated.json"
STATUS_PATH = DDIR / "collect_status.json"
TZ = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CTX = ssl.create_default_context()
BUDGET = float(os.environ.get("DEALS_BUDGET", "600"))
T0 = time.monotonic()
REVERIFY_HOURS = 6
STALE_VERIFY_DAYS = 7
EXPIRING_DAYS = 7
MAX_TRANSLATE = int(os.environ.get("DEALS_MAX_TRANSLATE", "120"))
OFFLINE = os.environ.get("DEALS_OFFLINE") == "1"

CATS = {
    "ai": "AI 工具免费与折扣",
    "crypto": "Crypto 空投与积分",
    "card": "U卡 / 海外银行卡",
    "bank": "海外银行",
    "cloud": "VPS 及云服务",
    "software": "软件与数字服务",
    "other": "其他全球优惠",
}
TYPE_TAGS = {
    "free": "真正免费",
    "trial": "免费试用",
    "deposit": "需要充值",
    "volume": "需要交易量",
    "invite": "需要邀请",
    "paid": "付费折扣",
    "lottery": "抽奖/随机",
}
# 固定参考汇率（只用于排序与估值显示，页面注明「约」）
FX_USD = {"USD": 1.0, "USDT": 1.0, "USDC": 1.0, "FDUSD": 1.0, "USD1": 1.0, "HKD": 0.128, "CNY": 0.14, "RMB": 0.14,
          "EUR": 1.08, "GBP": 1.27, "JPY": 0.0066, "SGD": 0.74, "AUD": 0.65, "CAD": 0.72}


def now() -> datetime:
    return datetime.now(TZ)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(TZ).isoformat(timespec="seconds") if dt else None


def parse_iso(s) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=TZ)
    except Exception:
        return None


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def left() -> float:
    return BUDGET - (time.monotonic() - T0)


def http(url: str, headers: dict | None = None, timeout: int = 20) -> tuple[int | None, str]:
    if OFFLINE or left() < 5:
        return None, ""
    h = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Accept": "*/*"}
    h.update(headers or {})
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=min(timeout, max(5, left())), context=CTX) as r:
            raw = r.read(4_000_000)
            enc = r.headers.get_content_charset() or "utf-8"
            return r.status, raw.decode(enc, "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, f"{type(e).__name__}"


def http_json(url: str, headers: dict | None = None):
    code, body = http(url, headers)
    if code != 200:
        return None
    try:
        return json.loads(body)
    except Exception:
        return None


def page_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def fp_title(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[（(]\s*\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s*[)）]", "", s)
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)
    return s[:80]


def norm_url(u: str | None) -> str:
    if not u:
        return ""
    p = urllib.parse.urlsplit(u.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith(("utm_", "ref", "aff", "fbclid", "gclid"))]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), urllib.parse.urlencode(q), ""))


def sid(prefix: str, key: str) -> str:
    return f"{prefix}-{hashlib.sha1(key.encode()).hexdigest()[:10]}"


# ------------------------------------------------------------------ 翻译（复用站点已有的免费翻译与缓存）
_TR = {"n": 0, "fn": None}


def zh(text: str) -> str:
    text = norm_space(text)
    if not text or len(re.findall(r"[\u4e00-\u9fff]", text)) >= max(4, len(text) // 4):
        return text
    if _TR["fn"] is None:
        try:
            import fetch_auto  # type: ignore
            _TR["fn"] = fetch_auto.free_translate
            _TR["save"] = fetch_auto.save_translate_cache
        except Exception as e:
            print(f"[deals] translator unavailable: {type(e).__name__}")
            _TR["fn"] = False
    if not _TR["fn"] or _TR["n"] >= MAX_TRANSLATE or left() < 30:
        return text
    _TR["n"] += 1
    try:
        out = _TR["fn"](text) or text
    except Exception:
        return text
    for a, b in (("房源活动", "上币活动"), ("上市活动", "上币活动"), ("赠品", "奖励"), ("贸易和学习", "交易与学习"), ("贸易", "交易"), ("$ ", "$"), ("目标：", "Target："), ("乐天：", "Rakuten：")):
        out = out.replace(a, b)
    return out


def zh_trad_to_simp(s: str) -> str:
    """极简繁→简（只覆盖活动公告常见字），避免引入依赖。"""
    table = str.maketrans("獎勵與動參賽幣實際將於開戶歡迎贈送現優惠費額點擊領邀請種區屬傳體這個們會說時後問題賬號帳戶應用線點發佈爲為臺灣場價購買單筆額滿員內關資訊數據幫並經過還沒處", 
                          "奖励与动参赛币实际将于开户欢迎赠送现优惠费额点击领邀请种区属传体这个们会说时后问题账号帐户应用线点发布为为台湾场价购买单笔额满员内关资讯数据帮并经过还没处")
    return (s or "").translate(table)


# ------------------------------------------------------------------ 规则提取
RX_VOLUME = re.compile(r"交易量|交易额|吃单|挂单|交易赛|交易大赛|合约交易|现货交易|trading volume|\btrade\b|\btrading\b|tournament|trade to", re.I)
RX_DEPOSIT = re.compile(r"充值|存入|入金|净入金|持有|持仓|申购|锁仓|质押|存款|余额|deposit|\bhold\b|holding|subscribe|stake|staking|direct deposit|balance", re.I)
RX_INVITE = re.compile(r"邀请|推荐好友|推荐码|推荐人|referral|refer a friend|refer friends|invite", re.I)
RX_TRIAL = re.compile(r"免费试用|试用期|free trial|\btrial\b|first month|首月", re.I)
RX_LOTTERY = re.compile(r"抽奖|刮刮|盲盒|幸运|lucky draw|raffle|spin|红包|lottery", re.I)
RX_FREE = re.compile(r"免费|零成本|无需|free|giveaway|空投|airdrop|答题|quiz|word of the day", re.I)
RX_KYC = re.compile(r"实名|身份认证|KYC|identity verification|verified users", re.I)
RX_NEWUSER = re.compile(r"新用户|新客户|首次|new users?|new customers?|first[- ]time", re.I)
RX_LIMITED = re.compile(r"名额有限|先到先得|额满即止|first[- ]come|limited (?:slots|quota)|while supplies last", re.I)
RX_AUTORENEW = re.compile(r"自动续费|自动扣费|auto[- ]?renew|automatically charge", re.I)
RX_CARDREQ = re.compile(r"绑卡|信用卡|credit card required|valid form of payment|payment method", re.I)

REGION_RULES = [
    (r"South Asia|南亚", "南亚地区"), (r"\bCIS\b|独联体", "独联体（CIS）"), (r"\bCEE\b|中东欧", "中东欧"), (r"Kenya|肯尼亚", "肯尼亚"),
    (r"Nigeria|尼日利亚", "尼日利亚"), (r"LATAM|Latin America|拉美", "拉丁美洲"), (r"\bMENA\b|中东", "中东北非"),
    (r"Turkey|Türkiye|土耳其", "土耳其"), (r"Vietnam|越南", "越南"), (r"Indonesia|印尼|印度尼西亚", "印度尼西亚"),
    (r"Philippines|菲律宾", "菲律宾"), (r"\bIndia\b|印度", "印度"), (r"Pakistan|巴基斯坦", "巴基斯坦"), (r"Brazil|巴西", "巴西"),
    (r"Europe|EEA|欧洲|欧盟", "欧洲"), (r"\bUK\b|United Kingdom|英国", "英国"), (r"Japan|日本", "日本"), (r"Korea|韩国", "韩国"),
    (r"Hong Kong|香港|HKID", "中国香港"), (r"Singapore|新加坡", "新加坡"), (r"Australia|澳大利亚", "澳大利亚"),
    (r"\bU\.S\.|\bUS residents|United States|美国", "美国"), (r"Canada|加拿大", "加拿大"),
]
RX_REGION_EXCL = re.compile(r"Region[- ]Exclusive|区域专享|地区专享|Exclusive[: ]|专属地区", re.I)


RX_EXCL_CTX = re.compile(r"不适用|不包括|除外|不得参与|不符合资格|禁止|受限|限制地区|excluded|exclude|not eligible|not available|restricted|prohibited", re.I)


def detect_regions(text: str, split: bool = False):
    inc, exc = [], []
    for rx, name in REGION_RULES:
        for m in re.finditer(rx, text or ""):
            ctx = text[max(0, m.start() - 160): m.start()]
            (exc if RX_EXCL_CTX.search(ctx) else inc).append(name)
    inc = [x for x in dict.fromkeys(inc) if x not in exc]
    exc = list(dict.fromkeys(exc))
    return (inc, exc) if split else inc


AMT_RX = re.compile(
    r"(?P<pre>[$€£¥]|US\$|HK\$|HKD|USD|USDT|USDC|CNY|RMB|EUR|GBP)?\s?(?P<num>\d{1,3}(?:[,，]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<mult>[KkMm](?![a-z])|万|億|亿|千)?\s?(?P<post>USDT|USDC|FDUSD|USD1|USD|BNB|BTC|ETH|SOL|XRP|TRX|HKD|美元|美金|港币|港元|EUR|GBP|[A-Z][A-Z0-9]{1,9})?(?![A-Za-z])")
NOT_CUR = {"UTC", "GMT", "VIP", "APR", "APY", "API", "KYC", "AM", "PM", "TB", "GB", "MB", "CPU", "GPU", "VPS", "KVM", "RAM", "SSD", "NVME", "DDOS", "HTTP", "AI", "OK", "ID", "PDF", "FAQ", "USA", "EST", "PST", "CST", "HKT", "TH", "ST", "ND", "RD", "X", "BOGO"}
POOL_RX = re.compile(r"奖池|瓜分|share|prize pool|总值|总奖金|pool|giveaway|空投总量|to be won", re.I)
UPTO_RX = re.compile(r"最高|高达|up to", re.I)


def _cur(pre: str | None, post: str | None) -> str | None:
    p = (pre or "").upper()
    q = (post or "").upper()
    m = {"$": "USD", "US$": "USD", "HK$": "HKD", "€": "EUR", "£": "GBP", "¥": "CNY", "美元": "USD", "美金": "USD", "港币": "HKD", "港元": "HKD"}
    if q in ("美元", "美金"):
        return "USD"
    if q in ("港币", "港元"):
        return "HKD"
    if q and q not in ("元",):
        return q
    if p:
        return m.get(p, p)
    return None


def extract_value(text: str, title: str = "") -> dict:
    """优先从标题找金额，标题没有再看正文；区分「奖池总额」「个人最高」与「仅提到」。"""
    if title:
        v = extract_value(title)
        if v.get("kind") != "unknown":
            return v
    syms = set(re.findall(r"[（(]([A-Z][A-Z0-9]{1,9})[)）]", text or ""))
    best = None
    for m in AMT_RX.finditer(text or ""):
        cur = _cur(m.group("pre"), m.group("post"))
        if not cur or cur in NOT_CUR:
            continue
        if cur not in FX_USD and cur not in syms and cur not in ("BNB", "BTC", "ETH", "SOL", "XRP", "TRX"):
            continue
        try:
            n = float(m.group("num").replace(",", "").replace("，", ""))
        except ValueError:
            continue
        mult = (m.group("mult") or "")
        n *= {"k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "万": 1e4, "亿": 1e8, "億": 1e8, "千": 1e3}.get(mult, 1)
        if n <= 0 or (cur in ("USD", "HKD") and n in (2025, 2026, 2027)):
            continue
        usd = n * FX_USD[cur] if cur in FX_USD else None
        ctx = text[max(0, m.start() - 30): m.end() + 12]
        kind = "pool" if POOL_RX.search(ctx) else ("per_user_max" if UPTO_RX.search(ctx) else "mentioned")
        cand = {"amount": n, "currency": cur, "usd": usd, "kind": kind}
        pri = {"per_user_max": 2, "mentioned": 1, "pool": 0}[kind]
        if best is None or (pri, usd or 0) > ({"per_user_max": 2, "mentioned": 1, "pool": 0}[best["kind"]], best.get("usd") or 0):
            best = cand
    if not best:
        return {"amount": None, "currency": None, "usd": None, "kind": "unknown", "label": "未注明金额（待核实）"}
    amt = f"{best['amount']:,.0f}" if best["amount"] >= 100 else f"{best['amount']:g}"
    usd_s = f"（约 {best['usd']:,.0f} 美元）" if best.get("usd") and best["currency"] not in ("USD", "USDT", "USDC") else ""
    if best["currency"] not in FX_USD:
        usd_s = "（代币，未换算成美元）"
    lab = {"pool": f"奖池总额 {amt} {best['currency']}{usd_s}，个人所得远低于此",
           "per_user_max": f"个人最高 {amt} {best['currency']}{usd_s}",
           "mentioned": f"公告提到 {amt} {best['currency']}{usd_s}（具体个人所得见条款）"}[best["kind"]]
    best["label"] = lab
    return best


MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_PATTERNS = [
    # 2026年11月09日08:00 （东八区时间）
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(?:(\d{1,2})[:：](\d{2}))?"),
    # 2026-11-09 08:00 (UTC)
    re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?"),
]
EN_DATE = re.compile(r"(?:(\d{1,2}):(\d{2})\s*(?:on\s*)?)?(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2}),?\s+(\d{4})(?:,?\s*(\d{1,2}):(\d{2}))?", re.I)


def _tz_for(ctx: str):
    if re.search(r"东八区|UTC\+8|GMT\+8|北京时间|香港时间|HKT", ctx):
        return TZ
    if re.search(r"\bUTC\b|GMT|世界协调", ctx):
        return UTC
    return None


def find_dates(text: str) -> list[datetime]:
    out = []
    for rx in DATE_PATTERNS:
        for m in rx.finditer(text):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hh = int(m.group(4)) if m.group(4) else 23
            mm = int(m.group(5)) if m.group(5) else 59
            ctx = text[m.end(): m.end() + 40]
            tz = _tz_for(ctx) or TZ
            try:
                out.append((m.start(), datetime(y, mo, d, min(hh, 23), min(mm, 59), tzinfo=tz)))
            except ValueError:
                pass
    for m in EN_DATE.finditer(text):
        try:
            mo = MON[m.group(3)[:3].lower()]
            hh = m.group(1) or m.group(6)
            mi = m.group(2) or m.group(7)
            ctx = text[m.end(): m.end() + 40]
            tz = _tz_for(ctx) or UTC
            out.append((m.start(), datetime(int(m.group(5)), mo, int(m.group(4)), int(hh) if hh else 23, int(mi) if mi else 59, tzinfo=tz)))
        except (ValueError, KeyError):
            pass
    out.sort(key=lambda x: x[0])
    return [d for _p, d in out]


PERIOD_RX = re.compile(r"(活动(?:期间|时间|时段)|推广期|Promotion Period|Campaign Period|Activity Period|Event Period|Promotion period)[:：]?\s*(.{0,160})", re.I)


def extract_period(text: str) -> tuple[datetime | None, datetime | None, str]:
    """优先取「活动期间：A 至 B」；返回 (开始, 截止, 原文片段)。"""
    for m in PERIOD_RX.finditer(text or ""):
        seg = m.group(2)
        ds = find_dates(seg)
        if len(ds) >= 2 and ds[1] > ds[0]:
            return ds[0], ds[1], norm_space(m.group(0))[:120]
        if len(ds) == 1:
            if re.search(r"截止|until|ends?\b|before|前", seg, re.I):
                return None, ds[0], norm_space(m.group(0))[:120]
    m = re.search(r"(截止|截至|deadline|ends? on|until|valid until|redeem until)[:：]?\s*(.{0,60})", text or "", re.I)
    if m:
        ds = find_dates(m.group(2))
        if ds:
            return None, ds[0], norm_space(m.group(0))[:80]
    return None, None, ""


RX_PAID = re.compile(r"requires \$|per month|/mo\b|/month|/year|月费|年费|subscription fee|membership fee|purchase|buy \$|spend \$|消费", re.I)


def type_tags(text: str, base: list[str] | None = None, allow_free: bool = True) -> list[str]:
    tags = list(base or [])
    if RX_PAID.search(text) and "paid" not in tags and not allow_free:
        tags.append("paid")
    if RX_VOLUME.search(text) and "volume" not in tags:
        tags.append("volume")
    if RX_DEPOSIT.search(text) and "deposit" not in tags:
        tags.append("deposit")
    if RX_INVITE.search(text) and "invite" not in tags:
        tags.append("invite")
    if RX_TRIAL.search(text) and "trial" not in tags:
        tags.append("trial")
    if RX_LOTTERY.search(text) and "lottery" not in tags:
        tags.append("lottery")
    if allow_free and not (set(tags) & {"volume", "deposit", "invite", "trial", "paid"}) and RX_FREE.search(text) and "free" not in tags:
        tags.append("free")
    return tags


def hidden_conditions(text: str) -> list[str]:
    out = []
    if RX_KYC.search(text):
        out.append("需完成实名 / 身份认证（KYC）")
    if RX_NEWUSER.search(text):
        out.append("仅限新用户 / 首次参与")
    if RX_LIMITED.search(text):
        out.append("名额有限，先到先得")
    if RX_AUTORENEW.search(text):
        out.append("到期自动续费，需记得取消")
    if RX_CARDREQ.search(text):
        out.append("需绑定银行卡或付款方式")
    if RX_REGION_EXCL.search(text):
        out.append("仅限特定地区用户")
    return out


def score(rec: dict, nowdt: datetime) -> float:
    v = rec.get("value") or {}
    usd = v.get("usd") or 0
    kind = v.get("kind")
    s = 0.0
    w = {"per_user": 1.0, "credit": 0.9, "retail": 0.8, "per_user_max": 0.6, "fee_saving": 0.8, "lottery": 0.15}.get(kind)
    if usd and w:
        s += 18 * math.log10(1 + min(usd, 3000) * w)
    elif kind == "free_tier":
        s += 30
    elif kind in ("pool", "mentioned"):
        s += 6
    tags = set(rec.get("type_tags") or [])
    s += 12 if "free" in tags else 0
    s += 4 if "trial" in tags else 0
    s -= 6 if "volume" in tags else 0
    s -= 3 if "deposit" in tags else 0
    s -= 2 if "invite" in tags else 0
    vs = rec.get("verify_status")
    s += {"verified": 16, "official": 6}.get(vs, -12)
    end = parse_iso(rec.get("end_at"))
    if end and 0 <= (end - nowdt).total_seconds() <= EXPIRING_DAYS * 86400:
        s += 5
    if rec.get("regions") and "全球" not in (rec.get("region") or ""):
        s -= 2
    return round(s, 2)


DEFAULT_RISK = {
    "crypto": ["加密资产价格波动大，奖励可能是代币券或锁仓资产", "交易所服务在部分国家/地区（含中国大陆）受限，参与前确认当地法规", "谨防冒充官方的钓鱼链接，只从官方页面进入"],
    "bank": ["开户资格（身份、居住地、税务）以银行条款为准", "奖金可能需要保持存款或账户一段时间，提前销户可能被收回"],
    "card": ["卡片费用、汇率与地区限制以发卡方条款为准", "U卡涉及加密资产出入金，注意资金与合规风险"],
    "cloud": ["超出免费额度后可能自动计费，建议设置预算提醒"],
    "ai": ["免费额度与价格随时可能调整，以官网为准"],
    "software": ["限免结束后恢复原价，领取前看清是否永久入库"],
    "other": ["参与前请阅读官方条款"],
}


# ------------------------------------------------------------------ 记录构造
def make_rec(**kw) -> dict:
    rec = {
        "id": kw["id"], "title": kw["title"], "category": kw["category"], "offer": kw.get("offer") or "",
        "value": kw.get("value") or {"amount": None, "currency": None, "usd": None, "kind": "unknown", "label": "未注明金额（待核实）"},
        "conditions": kw.get("conditions") or [], "region": kw.get("region") or "未注明（待核实）", "regions": kw.get("regions") or [],
        "start_at": kw.get("start_at"), "end_at": kw.get("end_at"), "deadline_note": kw.get("deadline_note") or "",
        "steps": kw.get("steps") or [], "official_url": kw.get("official_url"), "source_url": kw.get("source_url"),
        "source_name": kw.get("source_name") or "", "source_kind": kw["source_kind"], "adapter": kw.get("adapter", ""),
        "type_tags": kw.get("type_tags") or [], "risks": kw.get("risks") or [], "verify_status": kw.get("verify_status", "pending"),
        "verify_note": kw.get("verify_note", ""), "verified_at": kw.get("verified_at"), "published_at": kw.get("published_at"),
        "fp": fp_title(kw["title"]), "lang_note": kw.get("lang_note", ""),
    }
    if rec["value"].get("usd") is None and rec["value"].get("amount") and rec["value"].get("currency") in FX_USD:
        rec["value"]["usd"] = round(rec["value"]["amount"] * FX_USD[rec["value"]["currency"]], 2)
    return rec


def enrich_auto(rec: dict, text: str, category: str) -> dict:
    """自动条目：从官方正文提取类型、隐藏条件、地区、金额、风险。"""
    rec["type_tags"] = type_tags(text, rec.get("type_tags"), allow_free=rec.get("source_kind") != "third_party")
    hc = hidden_conditions(text)
    rec["conditions"] = list(dict.fromkeys((rec.get("conditions") or []) + hc))
    if not rec.get("regions") and (rec.get("region") or "").startswith("未注明"):
        inc, exc = detect_regions(text, split=True)
        head = rec.get("lang_note") or rec.get("title") or ""
        only, _x = detect_regions(head, split=True)
        if only and RX_REGION_EXCL.search(head):
            rec["regions"] = only
            rec["region"] = "仅限：" + "、".join(only) + "（以原文为准）"
        elif exc:
            rec["regions"] = []
            rec["region"] = "不适用：" + "、".join(exc) + " 等地区用户（程序从原文提取，以原文为准）"
        elif inc:
            rec["regions"] = inc
            rec["region"] = "原文提及：" + "、".join(inc) + "（是否限定地区以原文为准）"
    if (rec.get("value") or {}).get("kind") in (None, "unknown"):
        rec["value"] = extract_value(text, rec.get("lang_note") or rec.get("title") or "")
    rec["risks"] = list(dict.fromkeys((rec.get("risks") or []) + DEFAULT_RISK.get(category, [])))
    return rec


# ------------------------------------------------------------------ 适配器
def ad_binance(db: dict, stat: dict) -> list[dict]:
    """币安官方公告接口：93 最新活动、128 空投；正文里自动提取活动期间。"""
    out = []
    hdr = {"lang": "zh-CN", "clienttype": "web"}
    risk_extra = []
    news = http_json("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=49&pageNo=1&pageSize=10", hdr)
    for c in ((news or {}).get("data") or {}).get("catalogs") or []:
        for a in c.get("articles") or []:
            if re.search(r"安全事件|暂停提现|恢复进展", a.get("title") or ""):
                risk_extra.append(f"币安近期官方公告：「{a['title']}」，参与前留意资金与提现状态")
                break
        break
    for cat_id, kind in ((93, "活动"), (128, "空投")):
        d = http_json(f"https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId={cat_id}&pageNo=1&pageSize=20", hdr)
        arts = [a for c in ((d or {}).get("data") or {}).get("catalogs") or [] for a in c.get("articles") or []]
        stat[f"binance_{cat_id}"] = len(arts)
        for a in arts:
            code = a.get("code")
            if not code or re.search(r"完成|已结束|現已結束|现已结束|計畫現已|分发|分發|结束|更新|延期", a.get("title") or ""):
                continue  # 已完成/已结束的分发公告不是可参与的优惠
            if a.get("releaseDate") and (time.time() - a["releaseDate"] / 1000) > 60 * 86400:
                continue
            rid = f"bn-{code[:12]}"
            url = f"https://www.binance.com/zh-CN/support/announcement/detail/{code}"
            pub = datetime.fromtimestamp((a.get("releaseDate") or 0) / 1000, TZ) if a.get("releaseDate") else None
            prev = db.get(rid)
            if prev and prev.get("_body_ok"):
                prev["_seen"] = True
                out.append(prev)
                continue
            body = ""
            det = http_json(f"https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode={code}", hdr)
            try:
                node = json.loads(((det or {}).get("data") or {}).get("body") or "null")
                parts = []

                def walk(n):
                    if isinstance(n, dict):
                        if n.get("node") == "text":
                            parts.append(n.get("text") or "")
                        for ch in n.get("child") or []:
                            walk(ch)
                    elif isinstance(n, list):
                        for ch in n:
                            walk(ch)
                walk(node)
                body = norm_space(" ".join(parts))
            except Exception:
                body = ""
            title = a.get("title") or ""
            text = title + " " + body
            st, en, seg = extract_period(body)
            m = re.search(r"(?:重点摘要|亲爱的用户)[:：]?\s*(.{20,260}?[。！])", body)
            offer = norm_space(m.group(1)) if m else title
            offer = re.sub(r"^为给用户提供[^，。]*[，,]\s*", "", offer)
            steps = ["打开币安官方公告阅读完整条款"]
            if re.search(r"无需(?:申请|报名)", body):
                steps.append("公告写明无需报名，符合条件自动参与")
            elif re.search(r"报名|立即参与|Join Now|注册", body):
                steps.append("在活动页点击报名/参与")
            steps.append("完成公告列出的任务，奖励按公告时间发放")
            cat = "crypto"
            rec = make_rec(id=rid, title=title, category=cat, offer=offer[:220], start_at=iso(st), end_at=iso(en),
                           deadline_note=seg or "公告未找到明确活动期间（待核实）", steps=steps, official_url=url, source_url=url,
                           source_name="币安官方公告" + ("（空投）" if cat_id == 128 else ""), source_kind="official_api", adapter="binance",
                           verify_status="official" if body else "pending", verify_note="程序从币安官方公告正文自动提取，以公告原文为准" if body else "仅取得标题，正文未能读取",
                           verified_at=iso(now()) if body else None, published_at=iso(pub),
                           conditions=(["需持有/申购 BNB 等指定资产"] if cat_id == 128 else []), risks=list(risk_extra))
            if "这是一般性公告" in body or "可能不适用于您所在的地区" in body:
                rec["conditions"].append("公告提示：活动可能不适用于你所在的地区")
            enrich_auto(rec, text, cat)
            rec["_body_ok"] = bool(body)
            rec["_seen"] = True
            out.append(rec)
            time.sleep(0.3)
    return out


def ad_kucoin(db: dict, stat: dict) -> list[dict]:
    d = http_json("https://www.kucoin.com/_api/cms/articles?page=1&pageSize=20&category=activities&lang=en_US")
    items = (d or {}).get("items") or []
    stat["kucoin"] = len(items)
    out = []
    for it in items:
        path = it.get("path") or ""
        if not path:
            continue
        rid = sid("kc", path)
        url = "https://www.kucoin.com/announcement" + path
        prev = db.get(rid)
        if prev and prev.get("_body_ok"):
            prev["_seen"] = True
            out.append(prev)
            continue
        code, raw = http(url)
        body = page_text(raw) if code == 200 else ""
        i = body.find(it.get("title", "")[:30])
        body = body[i:i + 6000] if i >= 0 else body[:6000]
        title_en = norm_space(it.get("title"))
        st, en, seg = extract_period(body)
        pub = datetime.fromtimestamp(it["publish_ts"], TZ) if it.get("publish_ts") else None
        rec = make_rec(id=rid, title=zh(title_en), category="crypto", offer=zh(title_en) + "（详见 KuCoin 官方公告）",
                       start_at=iso(st), end_at=iso(en), deadline_note=seg or "未找到明确活动期间（待核实）",
                       steps=["打开 KuCoin 官方公告阅读完整条款", "按公告点击 Join Now 报名（如需要）", "完成交易/任务后按公告发放奖励"],
                       official_url=url, source_url=url, source_name="KuCoin 官方公告", source_kind="official_api", adapter="kucoin",
                       verify_status="official" if body else "pending", verify_note="程序从 KuCoin 官方公告自动提取，以公告原文为准；标题为机器翻译",
                       verified_at=iso(now()) if body else None, published_at=iso(pub), lang_note=title_en)
        enrich_auto(rec, title_en + " " + body[:3000], "crypto")
        rec["_body_ok"] = bool(body)
        rec["_seen"] = True
        out.append(rec)
        time.sleep(0.3)
    return out


def ad_epic(db: dict, stat: dict) -> list[dict]:
    d = http_json("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=zh-CN&country=CN&allowCountries=CN")
    els = (((d or {}).get("data") or {}).get("Catalog") or {}).get("searchStore", {}).get("elements") or []
    stat["epic"] = len(els)
    out = []
    nowdt = now()
    for e in els:
        promos = e.get("promotions") or {}
        cur = [o for g in promos.get("promotionalOffers") or [] for o in g.get("promotionalOffers") or []]
        up = [o for g in promos.get("upcomingPromotionalOffers") or [] for o in g.get("promotionalOffers") or []]
        free_now = [o for o in cur if (o.get("discountSetting") or {}).get("discountPercentage") == 0]
        free_up = [o for o in up if (o.get("discountSetting") or {}).get("discountPercentage") == 0]
        o = (free_now or free_up or [None])[0]
        if not o:
            continue
        st, en = parse_iso(o.get("startDate")), parse_iso(o.get("endDate"))
        slug = e.get("productSlug") or next((m.get("pageSlug") for m in (e.get("catalogNs") or {}).get("mappings") or [] if m.get("pageSlug")), None) \
            or next((m.get("pageSlug") for m in e.get("offerMappings") or [] if m.get("pageSlug")), None)
        url = f"https://store.epicgames.com/zh-CN/p/{slug}" if slug else "https://store.epicgames.com/zh-CN/free-games"
        price = ((e.get("price") or {}).get("totalPrice") or {})
        orig = (price.get("originalPrice") or 0) / (10 ** ((price.get("currencyInfo") or {}).get("decimals", 2)))
        curc = price.get("currencyCode") or "CNY"
        fmt = ((price.get("fmtPrice") or {}).get("originalPrice")) or ""
        upcoming = bool(free_up and not free_now)
        title = norm_space(e.get("title")).strip("《》")
        rid = sid("epic", (e.get("id") or title) + (o.get("endDate") or ""))
        rec = make_rec(id=rid, title=f"Epic 喜加一：《{title}》限时免费领取" + ("（即将开始）" if upcoming else ""), category="software",
                       offer=f"Epic Games 商店限时免费领取《{title}》，领取后永久保留在账号库中。" + (f"原价 {fmt}。" if fmt and orig else ""),
                       value={"amount": orig or None, "currency": curc, "kind": "retail", "label": (f"原价 {fmt}（中国区标价）" if orig else "原价未注明")},
                       conditions=["需要 Epic Games 账号", "在活动时间内点击「获取」"], region="全球多数地区（以 Epic 商店显示为准）",
                       start_at=iso(st), end_at=iso(en), deadline_note="Epic 官方接口给出的活动起止时间",
                       steps=["打开 Epic 商店游戏页面", "登录账号点击「获取」并完成下单（0 元）", "领取后在游戏库中永久保留"],
                       official_url=url, source_url="https://store.epicgames.com/zh-CN/free-games", source_name="Epic Games 官方商店",
                       source_kind="official_api", adapter="epic", type_tags=["free"], verify_status="official",
                       verify_note="Epic 官方接口实时数据" + ("；尚未开始" if upcoming else ""), verified_at=iso(nowdt),
                       risks=["只在活动时间内点「获取」才算入库", "个别地区可能不参与"])
        rec["value"]["usd"] = round(orig * FX_USD.get(curc, 0), 2) if orig else None
        rec["upcoming"] = upcoming
        rec["_seen"] = True
        out.append(rec)
    return out


def _rss_items(url: str) -> list[dict]:
    code, body = http(url, timeout=25)
    if code != 200 or not body:
        return []
    try:
        root = ET.fromstring(body.encode("utf-8"))
    except ET.ParseError:
        return []
    out = []
    ns = {"atom": "http://www.w3.org/2005/Atom", "content": "http://purl.org/rss/1.0/modules/content/"}
    for it in root.iter("item"):
        out.append({"title": norm_space(it.findtext("title") or ""), "link": (it.findtext("link") or "").strip(),
                    "desc": page_text(it.findtext("description") or ""), "content": it.findtext("content:encoded", default="", namespaces=ns) or "",
                    "pub": it.findtext("pubDate") or ""})
    for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = it.find("atom:link", ns)
        out.append({"title": norm_space(it.findtext("atom:title", default="", namespaces=ns)), "link": link.get("href") if link is not None else "",
                    "desc": page_text(it.findtext("atom:summary", default="", namespaces=ns) or it.findtext("atom:content", default="", namespaces=ns) or ""),
                    "content": "", "pub": it.findtext("atom:updated", default="", namespaces=ns)})
    return out


def _pubdate(s: str) -> datetime | None:
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).astimezone(TZ)
    except Exception:
        return parse_iso(s)


RSS_SOURCES = [
    # (adapter, url, category, source_name, source_kind, include regex, exclude regex, max age days)
    ("doc", "https://www.doctorofcredit.com/feed/", "bank", "Doctor of Credit（第三方）", "third_party",
     r"\$\d|Bonus|Checking|Savings|Bank|Credit Union|Card", r"Expired|Dead|\[Expired\]|Reminder|Weekly|Recap|Question|Poll|Best Posts|Review|\[Update\]|Update\]", 10),
    ("leb", "https://lowendbox.com/feed/", "cloud", "LowEndBox（第三方）", "third_party",
     r"\$\d+(?:\.\d+)?\s*/\s*(?:year|yr|month|mo)\b|\d+% off|Black Friday|Cyber Monday|Starting at \$", r"Interview|Review of|Opinion|Question|Poll|Giveaway|Turns Out|Did You|About Those|Bonus Entries|Bonus Code|Email Hosting", 14),
    ("ghcl", "https://github.blog/changelog/feed/", "ai", "GitHub Changelog（官方）", "official_feed",
     r"\bfree\b|no additional cost|at no cost|Copilot Free|free tier", r"deprecat|retir|sunset|closing down", 30),
    ("openai", "https://openai.com/news/rss.xml", "ai", "OpenAI 官方新闻", "official_feed",
     r"\bfree\b|discount|\bcredits\b|\boffer\b|promotion|at no cost", r"safety|research|system card|policy|hiring|ROI|achieves|case study|customer", 30),
]


def ad_rss(db: dict, stat: dict) -> list[dict]:
    out = []
    nowdt = now()
    for adapter, url, cat, sname, skind, inc, exc, max_age in RSS_SOURCES:
        items = _rss_items(url)
        stat[adapter] = len(items)
        kept = 0
        for it in items:
            t = it["title"]
            if not t or not re.search(inc, t + " " + it["desc"][:300], re.I) or re.search(exc, t, re.I):
                continue
            pub = _pubdate(it["pub"])
            if pub and (nowdt - pub).days > max_age:
                continue
            link = it["link"]
            rid = sid(adapter, norm_url(link) or t)
            prev = db.get(rid)
            if prev:
                prev["_seen"] = True
                out.append(prev)
                continue
            text_en = t + " " + it["desc"][:1500]
            c = cat
            if adapter == "doc":
                if re.search(r"Checking|Savings|\bBank\b|Credit Union|\bCD\b|Brokerage|Money Market|Fintech", t, re.I):
                    c = "bank"
                elif re.search(r"Credit Card|Debit Card|Signup Bonus|Sign-?up Bonus|AmEx|Chase|Citi|Capital One|Discover|Mastercard|Visa", t, re.I) and not re.search(r"Gift Card", t, re.I):
                    c = "card"
                else:
                    c = "other"
            if adapter in ("ghcl", "openai") and not re.search(r"\bfree\b|discount|\bcredits\b|\boffer\b|no cost|promotion", t, re.I):
                continue  # 官方博客只收标题本身就是优惠的
            st, en, seg = extract_period(it["desc"])
            summary_en = it["desc"][:260]
            rec = make_rec(id=rid, title=zh(t), category=c, offer=zh(summary_en) if summary_en else zh(t), start_at=iso(st), end_at=iso(en),
                           deadline_note=seg or "来源未写明截止时间（待核实）",
                           steps=["阅读来源文章了解活动", "从银行/服务商官网核对最新条款（本站尚未核实）", "确认资格后按官网流程参与"],
                           official_url=None if skind == "third_party" else link, source_url=link, source_name=sname, source_kind=skind,
                           adapter=adapter, verify_status="pending" if skind == "third_party" else "official",
                           verify_note=("第三方聚合信息，尚未对照官方页面核实" if skind == "third_party" else "官方博客文章，优惠细节以原文为准"),
                           verified_at=None if skind == "third_party" else iso(nowdt), published_at=iso(pub), lang_note=t)
            if adapter == "leb":
                rec["type_tags"] = ["paid"]
                rec["risks"] = ["低价 VPS 商家跑路风险较高，建议月付或小额试用", "价格为第三方文章所写，下单前以商家页面为准"]
            if adapter == "doc":
                rec["region"] = "美国（来源主要覆盖美国，以官方条款为准）"
                rec["regions"] = ["美国"]
            enrich_auto(rec, text_en, c)
            if adapter == "leb":
                rec["type_tags"] = [x for x in rec["type_tags"] if x not in ("free", "deposit")] or ["paid"]
                if "paid" not in rec["type_tags"]:
                    rec["type_tags"].insert(0, "paid")
                v = rec["value"]
                if v.get("kind") != "unknown":
                    rec["value"] = {"amount": v["amount"], "currency": v["currency"], "usd": None, "kind": "price",
                                    "label": f"售价约 {v['amount']:g} {v['currency']}（付费套餐，不是赠送价值）"}
            rec["_seen"] = True
            out.append(rec)
            kept += 1
        stat[adapter + "_kept"] = kept
    return out


def ad_curated(db: dict, stat: dict) -> list[dict]:
    cur = load(CURATED_PATH, {}).get("items") or []
    out = []
    nowdt = now()
    checked = ok = 0
    for c in cur:
        rid = "ed-" + c["id"]
        prev = db.get(rid) or {}
        rec = make_rec(id=rid, title=c["title"], category=c["category"], offer=c["offer"], value=dict(c.get("value") or {}),
                       conditions=c.get("conditions"), region=c.get("region"), start_at=c.get("start_at"), end_at=c.get("end_at"),
                       deadline_note=c.get("deadline_note"), steps=c.get("steps"), official_url=c["official_url"], source_url=c.get("source_url"),
                       source_name=c.get("source_name"), source_kind="curated", adapter="curated", type_tags=c.get("type_tags"),
                       risks=c.get("risks"), verify_status=prev.get("verify_status", "pending"), verify_note=prev.get("verify_note", ""),
                       verified_at=prev.get("verified_at"))
        rec["regions"] = detect_regions(rec["region"])
        last_check = parse_iso(prev.get("checked_at"))
        need = (not last_check) or (nowdt - last_check).total_seconds() > REVERIFY_HOURS * 3600 or prev.get("verify_status") != "verified" \
            or prev.get("_verify_sig") != json.dumps(c.get("verify"))
        if need and left() > 20:
            checked += 1
            code, raw = http(c["official_url"], headers={"Accept-Language": c.get("accept_language") or "en-US,en;q=0.9"}, timeout=25)
            txt = page_text(raw).lower() if code == 200 else ""
            missing = [k for k in c.get("verify") or [] if norm_space(k).lower() not in txt]
            rec["checked_at"] = iso(nowdt)
            rec["_verify_sig"] = json.dumps(c.get("verify"))
            if code == 200 and not missing:
                ok += 1
                rec.update(verify_status="verified", verified_at=iso(nowdt), verify_note="已对照官方页面核实关键条款")
            elif code == 200:
                rec.update(verify_status="changed", verify_note="官方页面内容已变化，以下信息待核实（找不到：" + "、".join(missing)[:80] + "）")
            else:
                pv = parse_iso(prev.get("verified_at"))
                if pv and (nowdt - pv).days < STALE_VERIFY_DAYS:
                    rec.update(verify_status="verified", verified_at=prev.get("verified_at"), verify_note=f"本次官网访问失败（{code or '网络错误'}），沿用上次核实结果")
                else:
                    rec.update(verify_status="unreachable", verify_note=f"官网暂时无法访问（{code or '网络错误'}），待核实")
        else:
            rec["checked_at"] = prev.get("checked_at")
            rec["_verify_sig"] = prev.get("_verify_sig")
        rec["_seen"] = True
        out.append(rec)
    stat["curated"] = len(cur)
    stat["curated_checked"] = checked
    stat["curated_ok"] = ok
    return out


ADAPTERS = [("curated", ad_curated), ("epic", ad_epic), ("binance", ad_binance), ("kucoin", ad_kucoin), ("rss", ad_rss)]


# ------------------------------------------------------------------ 状态 / 去重 / 归档
def set_state(rec: dict, nowdt: datetime) -> None:
    end = parse_iso(rec.get("end_at"))
    st = parse_iso(rec.get("start_at"))
    first = parse_iso(rec.get("first_seen")) or nowdt
    last = parse_iso(rec.get("last_seen")) or nowdt
    if end and end < nowdt:
        rec["state"], rec["archived_reason"] = "expired", "已过截止时间，自动归档"
    elif not end and rec["source_kind"] not in ("curated",) and (nowdt - last).days >= 21:
        rec["state"], rec["archived_reason"] = "archived", "超过 21 天未在来源中出现，自动归档（不代表活动已结束）"
    elif not end and rec["source_kind"] in ("official_api", "third_party", "official_feed") and (nowdt - (parse_iso(rec.get("published_at")) or first)).days >= 30:
        rec["state"], rec["archived_reason"] = "archived", "发布超过 30 天且未找到截止时间，自动归档（不代表活动已结束）"
    elif st and st > nowdt:
        rec["state"], rec["archived_reason"] = "upcoming", ""
    elif end and (end - nowdt).total_seconds() <= EXPIRING_DAYS * 86400:
        rec["state"], rec["archived_reason"] = "expiring", ""
    else:
        rec["state"], rec["archived_reason"] = "active", ""
    if rec.get("upcoming") and rec["state"] in ("active", "expiring"):
        rec["state"] = "upcoming"


def dedupe(recs: list[dict]) -> tuple[list[dict], int]:
    """同一官方链接或同一标题指纹只保留一条（官方 > 编辑核实 > 第三方），记录合并来源。"""
    rank = {"curated": 0, "official_api": 1, "official_feed": 2, "third_party": 3}
    recs = sorted(recs, key=lambda r: rank.get(r["source_kind"], 9))
    seen_u, seen_f, out, dup = {}, {}, [], 0
    for r in recs:
        ku = norm_url(r.get("official_url")) if r.get("official_url") and r["source_kind"] != "curated" else ""
        kf = r.get("fp") or ""
        hit = (seen_u.get(ku) if ku else None) or (seen_f.get(kf) if len(kf) >= 8 else None)
        if hit is not None:
            dup += 1
            alts = hit.setdefault("also_seen", [])
            if r.get("source_url") and r["source_url"] not in alts and r["source_url"] != hit.get("source_url"):
                alts.append(r["source_url"])
            continue
        if ku:
            seen_u[ku] = r
        if len(kf) >= 8:
            seen_f[kf] = r
        out.append(r)
    return out, dup


def main() -> int:
    nowdt = now()
    old = load(DB_PATH, {})
    db = {r["id"]: r for r in old.get("items") or []}
    stat = {"started_at": iso(nowdt)}
    errors = {}
    fresh: list[dict] = []
    for name, fn in ADAPTERS:
        t = time.monotonic()
        try:
            got = fn(db, stat)
            fresh.extend(got)
            stat[f"{name}_n"] = len(got)
        except Exception as e:  # 单个来源失败不影响其他来源
            errors[name] = f"{type(e).__name__}: {e}"[:200]
            print(f"[deals] adapter {name} failed: {errors[name]}")
        stat[f"{name}_sec"] = round(time.monotonic() - t, 1)
    if _TR.get("save"):
        try:
            _TR["save"]()
        except Exception:
            pass
    fresh_ids = {r["id"] for r in fresh}
    merged = []
    for r in fresh:
        p = db.get(r["id"]) or {}
        r["first_seen"] = p.get("first_seen") or iso(nowdt)
        r["last_seen"] = iso(nowdt)
        merged.append(r)
    # 本次未抓到的旧条目保留（来源暂时失败时不丢数据），由归档规则处理
    curated_ids = {"ed-" + c["id"] for c in (load(CURATED_PATH, {}).get("items") or [])}
    for rid, p in db.items():
        if rid in fresh_ids:
            continue
        if p.get("source_kind") == "curated" and rid not in curated_ids:
            continue  # 编辑删除的条目直接移除
        p.pop("_seen", None)
        merged.append(p)
    for r in merged:
        r.pop("_seen", None)
        r["fp"] = fp_title(r.get("title"))
        set_state(r, nowdt)
        r["score"] = score(r, nowdt)
    items, dup = dedupe(merged)
    items.sort(key=lambda r: (-r["score"], r["id"]))
    counts = {}
    for r in items:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    out = {"updated_at": iso(nowdt), "counts": counts, "dedupe_merged": dup, "items": items}
    if not items and old.get("items"):
        print("[deals] produced 0 items — keep previous database")
        return 0
    save(DB_PATH, out)
    stat.update(finished_at=iso(now()), errors=errors, total=len(items), dedupe_merged=dup, translations=_TR["n"], states=counts)
    save(STATUS_PATH, stat)
    print(f"[deals] items={len(items)} states={counts} dup={dup} errors={list(errors)} stat={ {k: v for k, v in stat.items() if k.endswith('_n')} }")
    return 0


if __name__ == "__main__":
    sys.exit(main())
