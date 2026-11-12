#!/usr/bin/env python3
"""Optional OpenAI-compatible model client with a daily budget, a result cache and silent fallback.

Reads LLM_API_KEY / LLM_BASE_URL / LLM_MODEL from the environment (GitHub secrets on Actions,
~/.llm_env on a server engine). Without a key, or on any error / rate limit / exhausted budget,
every call returns None and the caller keeps its rule-based path. The key is never logged or written.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Shanghai")
CACHE = ROOT / "data" / "auto" / "llm_cache.json"
CACHE_MAX = 4000
# daily caps per scope (calls, tokens); the budget file travels with the repo so all engines share it
CAPS = {"pipeline": (150, 450_000), "evolve": (6, 60_000), "board": (40, 60_000), "radio": (6, 30_000)}
BUDGET_FILES = {"board": ROOT / "data" / "board" / "llm_budget.json"}
DEFAULT_BUDGET = ROOT / "data" / "evolve" / "llm_budget.json"
MAX_FAILS_PER_RUN = 3

import threading
_lock = threading.Lock()
_fails = 0
_cache: dict | None = None
_cache_dirty = False


def _env_file() -> None:
    """Server engines keep the settings in ~/.llm_env (chmod 600, outside the repo)."""
    if os.environ.get("LLM_API_KEY"):
        return
    p = Path(os.path.expanduser("~/.llm_env"))
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                k = k.strip()
                if k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL") and not os.environ.get(k):
                    os.environ[k] = v.strip().strip('"').strip("'")
    except Exception:
        pass


def _cfg() -> tuple[str, str, str]:
    _env_file()
    return (os.environ.get("LLM_API_KEY", "").strip(), os.environ.get("LLM_BASE_URL", "").strip().rstrip("/"),
            os.environ.get("LLM_MODEL", "").strip())


def available() -> bool:
    k, b, m = _cfg()
    return bool(k and b and m) and os.environ.get("LLM_OFF", "") != "1"


def _today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _bpath(scope: str) -> Path:
    return BUDGET_FILES.get(scope, DEFAULT_BUDGET)


def _budget_load(scope: str) -> dict:
    try:
        d = json.loads(_bpath(scope).read_text(encoding="utf-8"))
    except Exception:
        d = {}
    if d.get("date") != _today():
        d = {"date": _today(), "scopes": {}}
    d.setdefault("scopes", {})
    return d


def budget_left(scope: str) -> tuple[int, int]:
    d = _budget_load(scope)
    s = d["scopes"].get(scope) or {}
    cap_c, cap_t = CAPS.get(scope, (10, 20_000))
    return cap_c - int(s.get("calls", 0)), cap_t - int(s.get("tokens", 0))


def _budget_add(scope: str, tokens: int, ok: bool) -> None:
    with _lock:
        _budget_add_locked(scope, tokens, ok)


def _budget_add_locked(scope: str, tokens: int, ok: bool) -> None:
    try:
        d = _budget_load(scope)
        s = d["scopes"].setdefault(scope, {"calls": 0, "tokens": 0, "fails": 0})
        s["calls"] = int(s.get("calls", 0)) + 1
        s["tokens"] = int(s.get("tokens", 0)) + int(tokens or 0)
        if not ok:
            s["fails"] = int(s.get("fails", 0)) + 1
        p = _bpath(scope)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except Exception:
        pass


def _cache_load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def save_cache() -> None:
    global _cache_dirty
    if not _cache_dirty or _cache is None:
        return
    try:
        with _lock:
            items = sorted(_cache.items(), key=lambda kv: kv[1].get("t", 0))[-CACHE_MAX:]
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(dict(items), ensure_ascii=False) + "\n", encoding="utf-8")
        _cache_dirty = False
    except Exception:
        pass


def chat(system: str, user: str, *, scope: str = "pipeline", max_tokens: int = 800, temperature: float = 0.3,
         cache: bool = True, timeout: int = 45) -> str | None:
    """One chat completion. Returns text or None (no key / budget / error). Never raises, never logs the key."""
    global _fails, _cache_dirty
    try:
        if not available() or _fails >= MAX_FAILS_PER_RUN:
            return None
        key, base, model = _cfg()
        ck = hashlib.sha256(f"{model}\n{system}\n{user}".encode("utf-8")).hexdigest()[:32]
        if cache:
            hit = _cache_load().get(ck)
            if hit and hit.get("v"):
                return hit["v"]
        calls, toks = budget_left(scope)
        if calls <= 0 or toks <= 0:
            print(f"[llm] {scope} daily budget used up — rule-based path")
            return None
        body = json.dumps({"model": model, "temperature": temperature, "max_tokens": max_tokens,
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                              "User-Agent": "aiym168-bot/1.0"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read(2_000_000))
        except Exception as e:
            _fails += 1
            _budget_add(scope, 0, False)
            code = getattr(e, "code", "")
            print(f"[llm] {scope} call failed ({type(e).__name__} {code}) — rule-based path")
            return None
        txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        txt = re.sub(r"(?s)<think>.*?</think>", "", txt).strip()
        used = int((d.get("usage") or {}).get("total_tokens") or 0)
        _budget_add(scope, used, bool(txt))
        print(f"[llm] {scope} ok {time.time() - t0:.1f}s tokens={used}")
        if not txt:
            _fails += 1
            return None
        if cache:
            with _lock:
                _cache_load()[ck] = {"v": txt, "t": int(time.time())}
                _cache_dirty = True
        return txt
    except Exception as e:
        print(f"[llm] unexpected {type(e).__name__} — rule-based path")
        return None


def chat_json(system: str, user: str, **kw):
    """chat() and parse the first JSON object/array in the answer; None on failure."""
    txt = chat(system, user, **kw)
    if not txt:
        return None
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    for pat in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pat, txt, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                continue
    return None


def translate_batch(rows: list[dict], scope: str = "pipeline", kind: str = "news", max_items: int = 60,
                    time_budget_s: int = 120) -> dict[str, dict]:
    """rows: [{"id","title","text"}] (English). Returns {id: {"title","summary"}} for the rows the model handled.
    Callers keep their free translators for anything missing."""
    out: dict[str, dict] = {}
    if not rows or not available():
        return out
    try:  # the same sensitive-word filter the news collector uses; no filter -> no model output
        from news_collect import blocked as _blocked
    except Exception:
        return out
    sys_p = ("你是中文科技编辑。把英文科技/AI 资讯翻成自然、准确、简洁的简体中文。标题不超过 40 字，不加感叹号、不夸张、不加评论；"
             "摘要 1-2 句、不超过 90 字，只根据原文，不编造；原文没有正文时 summary 留空字符串，不要写「原文未提供」之类的话。产品名、公司名、模型名保留英文原名。"
             + ("这些是免费资源/优惠条目，标题要说清是什么、免费在哪里。" if kind == "deal" else "")
             + "只输出 JSON 数组：[{\"id\":\"…\",\"title\":\"…\",\"summary\":\"…\"}]，id 原样返回。")
    def ikey(r):
        return "i:" + hashlib.sha256(f"{kind}\n{r.get('title')}\n{(r.get('text') or '')[:500]}".encode("utf-8")).hexdigest()[:28]
    cache_ = _cache_load()
    miss = []
    for r in rows:
        hit = cache_.get(ikey(r))
        if hit and isinstance(hit.get("v"), dict):
            out[r["id"]] = hit["v"]
        else:
            miss.append(r)
    rows = miss[:max_items]
    chunks = [rows[i:i + 12] for i in range(0, len(rows), 12)]

    def one(chunk):
        if time.time() > deadline:
            return chunk, None
        user = json.dumps([{"id": r["id"], "title": (r.get("title") or "")[:200], "text": (r.get("text") or "")[:500]} for r in chunk],
                          ensure_ascii=False)
        return chunk, chat_json(sys_p, user, scope=scope, max_tokens=1800, temperature=0.2, cache=False,
                                timeout=max(10, min(60, int(deadline - time.time()))))

    deadline = time.time() + time_budget_s
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(one, chunks))
    for chunk, got in results:
        if not isinstance(got, list):
            continue
        ids = {r["id"] for r in chunk}
        for g in got:
            if not isinstance(g, dict) or g.get("id") not in ids:
                continue
            t = re.sub(r"\s+", " ", str(g.get("title") or "")).strip()
            s = re.sub(r"\s+", " ", str(g.get("summary") or "")).strip()
            if t and re.search(r"[\u4e00-\u9fff]", t) and len(t) <= 80 and not _blocked(t, s):
                if re.search(r"原文(未|没有)|未提供|无正文", s):
                    s = ""
                out[g["id"]] = v = {"title": t, "summary": s[:200] if re.search(r"[\u4e00-\u9fff]", s) else ""}
                r0 = next(r for r in chunk if r["id"] == g["id"])
                with _lock:
                    cache_[ikey(r0)] = {"v": v, "t": int(time.time())}
                    global _cache_dirty
                    _cache_dirty = True
    save_cache()
    return out


if __name__ == "__main__":
    import sys
    print("available:", available(), "budget(pipeline):", budget_left("pipeline"))
    if len(sys.argv) > 1 and available():
        print(chat("用一句简体中文回答。", sys.argv[1], scope="evolve", cache=False, max_tokens=60))
