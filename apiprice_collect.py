#!/usr/bin/env python3
"""大模型 API 最低价榜：从公开价格接口采集各家报价，写入 data/apiprices/prices.json。

来源（都是无需密钥的公开接口，本地与 GitHub Actions 均可访问）：
  - OpenRouter 公开模型接口 /api/v1/models 与 /models/{id}/endpoints：每个模型在各上游（含官方直连）的列表价、上下文、量化与可用率
  - DeepInfra 公开模型列表 /models/list：DeepInfra 自己官网的直连价
  - Novita 公开模型列表 /v3/openai/models：Novita 自己官网的直连价
  - open.er-api.com：美元兑人民币参考汇率（记录汇率日期）
抓不到的来源保留上一次的数据并标注。只用标准库。
"""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
D = ROOT / "data" / "apiprices"
OUT = D / "prices.json"
HIST = D / "history.json"
TZ = ZoneInfo("Asia/Shanghai")
CTX = ssl.create_default_context()
UA = "Mozilla/5.0 (compatible; aiym168-price-bot/1.0; +https://aiym168.github.io/)"
T0 = time.monotonic()
BUDGET = float(os.environ.get("APIPRICE_BUDGET", "240"))
PER_FAMILY = int(os.environ.get("APIPRICE_PER_FAMILY", "4"))

# 家族：(显示名, OpenRouter 作者前缀, 官方直连在 OpenRouter 上的 provider 名, 官方定价页)
FAMILIES = [
    ("GPT", ("openai",), ("OpenAI",), "https://openai.com/api/pricing/"),
    ("Claude", ("anthropic",), ("Anthropic",), "https://claude.com/pricing"),
    ("Gemini", ("google",), ("Google AI Studio", "Google", "Google Vertex"), "https://ai.google.dev/gemini-api/docs/pricing"),
    ("DeepSeek", ("deepseek",), ("DeepSeek",), "https://api-docs.deepseek.com/quick_start/pricing"),
    ("Qwen", ("qwen",), ("Alibaba", "Alibaba Cloud Int."), "https://help.aliyun.com/zh/model-studio/models"),
    ("GLM", ("z-ai",), ("Z.AI", "Z.ai"), "https://open.bigmodel.cn/pricing"),
    ("Kimi", ("moonshotai",), ("Moonshot AI", "MoonshotAI"), "https://platform.moonshot.cn/docs/pricing/chat"),
    ("Llama / Meta", ("meta-llama", "meta"), ("Meta",), "https://www.llama.com/"),
    ("Mistral", ("mistralai",), ("Mistral",), "https://mistral.ai/pricing"),
    ("Grok", ("x-ai",), ("xAI",), "https://docs.x.ai/docs/models"),
    ("MiniMax", ("minimax",), ("MiniMax", "Minimax"), "https://www.minimax.io/"),
]
SKIP_RX = re.compile(r"image|audio|tts|transcri|embed|moderation|realtime|search-preview|guard|vision-preview|-deep-research|computer-use|codex-mini|o1-pro|o3-pro|gpt-.*-pro\b|-legal\b|-contributor\b", re.I)


def now():
    return datetime.now(TZ)


def iso(d):
    return d.astimezone(TZ).isoformat(timespec="seconds") if d else None


def get_json(url, timeout=25):
    if BUDGET - (time.monotonic() - T0) < 5:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"[apiprice] GET fail {url[:80]}: {type(e).__name__}")
        return None


def load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def per_m(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v * 1e6, 6) if v >= 0 else None


def key(s):
    s = (s or "").lower().split("/")[-1].split(":")[0]
    s = re.sub(r"-(instruct|chat|turbo|fp8|bf16|hf)$", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def blend(i, o):
    if i is None or o is None:
        return None
    return round((3 * i + o) / 4, 6)


def caveats_for(ep: dict) -> list[str]:
    out = []
    q = (ep.get("quantization") or "").lower()
    if q and q not in ("unknown", "bf16", "fp16", "fp32"):
        out.append(f"量化版本（{q}），输出质量可能略低于原版")
    tier = (ep.get("service_tier") or "").lower()
    if tier == "flex":
        out.append("flex 档：低价但可能排队、延迟较高")
    up = ep.get("uptime_last_30m")
    if isinstance(up, (int, float)) and up < 95:
        out.append(f"近 30 分钟可用率 {up:.0f}%")
    mx = ep.get("max_completion_tokens")
    if isinstance(mx, int) and 0 < mx < 8192:
        out.append(f"单次最多输出 {mx} tokens")
    return out


def main() -> int:
    nowdt = now()
    prev = load(OUT, {})
    stat = {"started_at": iso(nowdt)}
    fx = get_json("https://open.er-api.com/v6/latest/USD")
    if fx and fx.get("result") == "success" and (fx.get("rates") or {}).get("CNY"):
        rate = {"usd_cny": round(fx["rates"]["CNY"], 4), "date": fx.get("time_last_update_utc"), "source": "https://open.er-api.com/v6/latest/USD"}
    else:
        rate = prev.get("fx") or {"usd_cny": 7.1, "date": "参考值（汇率接口不可用）", "source": ""}
    models = (get_json("https://openrouter.ai/api/v1/models") or {}).get("data") or []
    stat["openrouter_models"] = len(models)
    if not models:
        print("[apiprice] OpenRouter unavailable — keep previous data")
        if prev:
            prev["stale_note"] = f"{iso(nowdt)} 本轮 OpenRouter 接口不可用，沿用上次数据"
            OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    free_ids = {m["id"].split(":")[0] for m in models if m["id"].endswith(":free")}
    di = get_json("https://api.deepinfra.com/models/list") or []
    di_map = {}
    for m in di if isinstance(di, list) else []:
        if m.get("type") != "text-generation" or m.get("deprecated") or m.get("private"):
            continue
        p = m.get("pricing") or {}
        if p.get("type") != "tokens" or p.get("cents_per_input_token") is None:
            continue
        di_map.setdefault(key(m["model_name"]), m)
    nv = (get_json("https://api.novita.ai/v3/openai/models") or {}).get("data") or []
    nv_map = {}
    for m in nv:
        pr = m.get("pricing") or {}
        try:
            i = float(pr["prompt"]["price_per_m_decimal"])
            o = float(pr["completion"]["price_per_m_decimal"])
        except (KeyError, TypeError, ValueError):
            continue
        nv_map.setdefault(key(m["id"]), (m, i, o))
    stat.update(deepinfra=len(di_map), novita=len(nv_map))

    hist = load(HIST, {})
    rows = []
    for fam, prefixes, official_names, official_page in FAMILIES:
        cand = []
        for m in models:
            mid = m["id"]
            if ":" in mid or mid.startswith("~") or mid.split("/")[0] not in prefixes:
                continue
            arch = m.get("architecture") or {}
            if "text" not in (arch.get("output_modalities") or ["text"]) or SKIP_RX.search(mid):
                continue
            pr = m.get("pricing") or {}
            if per_m(pr.get("prompt")) in (None, 0) and per_m(pr.get("completion")) in (None, 0):
                continue
            cand.append(m)
        cand.sort(key=lambda m: -(m.get("created") or 0))
        for m in cand[:PER_FAMILY]:
            mid = m["id"]
            epd = get_json(f"https://openrouter.ai/api/v1/models/{mid}/endpoints")
            eps = ((epd or {}).get("data") or {}).get("endpoints") or []
            offers = []
            for ep in eps:
                i, o = per_m((ep.get("pricing") or {}).get("prompt")), per_m((ep.get("pricing") or {}).get("completion"))
                if i is None or o is None or (i == 0 and o == 0):
                    continue
                prov = ep.get("provider_name") or "?"
                is_off = prov in official_names
                offers.append({"provider": prov, "channel": "official" if is_off else "openrouter", "in": i, "out": o,
                               "ctx": ep.get("context_length") or m.get("context_length"), "quant": ep.get("quantization"),
                               "tier": ep.get("service_tier"), "tag": ep.get("tag"), "caveats": caveats_for(ep),
                               "url": f"https://openrouter.ai/{mid}", "source": f"https://openrouter.ai/api/v1/models/{mid}/endpoints"})
            # 直连官网 API（DeepInfra / Novita）
            k = key(m.get("hugging_face_id") or "") or key(mid)
            for kk in {k, key(mid)}:
                dm = di_map.get(kk)
                if dm and not any(x["channel"] == "deepinfra" for x in offers):
                    p = dm["pricing"]
                    offers.append({"provider": "DeepInfra", "channel": "deepinfra", "in": round(p["cents_per_input_token"] * 1e4, 6),
                                   "out": round(p["cents_per_output_token"] * 1e4, 6), "ctx": dm.get("max_tokens"), "quant": dm.get("quantization"),
                                   "tier": None, "caveats": ([f"量化版本（{dm['quantization']}）"] if (dm.get("quantization") or "").lower() not in ("", "bf16", "fp16", "none") else []),
                                   "url": f"https://deepinfra.com/{dm['model_name']}", "source": "https://api.deepinfra.com/models/list"})
                nm = nv_map.get(kk)
                if nm and not any(x["channel"] == "novita" for x in offers):
                    nmod, i, o = nm
                    offers.append({"provider": "Novita", "channel": "novita", "in": i, "out": o, "ctx": nmod.get("context_size"),
                                   "quant": None, "tier": None, "caveats": [], "url": "https://novita.ai/pricing",
                                   "source": "https://api.novita.ai/v3/openai/models"})
            if not offers:
                continue
            for x in offers:
                x["blend"] = blend(x["in"], x["out"])
                hk = f"{mid}|{x['provider']}|{x['channel']}|{x.get('tier') or ''}|{x.get('quant') or ''}"
                h = hist.get(hk)
                if h and (abs(h["in"] - x["in"]) > 1e-9 or abs(h["out"] - x["out"]) > 1e-9):
                    x["change"] = {"prev_in": h["in"], "prev_out": h["out"], "since": h.get("at"), "dir": "down" if x["blend"] < blend(h["in"], h["out"]) else "up"}
                    hist[hk] = {"in": x["in"], "out": x["out"], "at": iso(nowdt), "prev_in": h["in"], "prev_out": h["out"]}
                elif h and h.get("prev_in") is not None and h.get("at"):
                    x["change"] = {"prev_in": h["prev_in"], "prev_out": h["prev_out"], "since": h["at"],
                                   "dir": "down" if x["blend"] < blend(h["prev_in"], h["prev_out"]) else "up"}
                elif not h:
                    hist[hk] = {"in": x["in"], "out": x["out"], "at": iso(nowdt)}
            offers.sort(key=lambda x: (x["blend"], x["channel"] != "official", x["in"]))
            off = [x for x in offers if x["channel"] == "official"]
            std = [x for x in off if (x.get("tier") or "").lower() not in ("flex", "batch")] or off
            offc = min(std, key=lambda x: x["blend"]) if std else None
            best = offers[0]
            save = None
            if offc and offc["blend"] and best["blend"] < offc["blend"]:
                save = round((offc["blend"] - best["blend"]) / offc["blend"] * 100, 1)
            rows.append({
                "id": mid, "name": m.get("name") or mid, "family": fam, "ctx": m.get("context_length"), "created": m.get("created"),
                "official_provider": offc["provider"] if offc else None, "official_in": offc["in"] if offc else None,
                "official_out": offc["out"] if offc else None, "official_page": official_page,
                "best": {k2: best.get(k2) for k2 in ("provider", "channel", "in", "out", "ctx", "url", "caveats", "tier")}, "save_pct": save,
                "free": mid in free_ids, "offers": offers, "verified_at": iso(nowdt),
            })
            time.sleep(0.15)
    stat["models"] = len(rows)
    stat["offers"] = sum(len(r["offers"]) for r in rows)
    out = {"updated_at": iso(nowdt), "fx": rate, "rows": rows, "stat": stat,
           "sources": {"openrouter": "https://openrouter.ai/api/v1/models", "deepinfra": "https://api.deepinfra.com/models/list",
                       "novita": "https://api.novita.ai/v3/openai/models", "fx": rate.get("source")}}
    if not rows and prev.get("rows"):
        print("[apiprice] 0 rows — keep previous data")
        return 0
    D.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    HIST.write_text(json.dumps(hist, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"[apiprice] models={len(rows)} offers={stat['offers']} deepinfra={len(di_map)} novita={len(nv_map)} fx={rate['usd_cny']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
