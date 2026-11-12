#!/usr/bin/env python3
"""Bounded self-evolution for the site (rules first, optional model on top). Only data/evolve/* changes.

  python3 evolve.py run       ledger update every pipeline run + the daily evolution step (gated, once a day)
  python3 evolve.py daily     daily step only (server engine standby); also upgrades a rule-written diary
                              with the model when one becomes available
  python3 evolve.py ledger    ledger only
  python3 evolve.py dry       daily step on a copy, prints what it would change, writes nothing

Files (data/evolve/): ledger.json (per-source daily stats), tuning.json (what the collectors read),
probation.json (candidate sources on trial), snapshots/<date>.json (tuning before each step),
diary.json (short first-person lines for the brain), state.json (last step + rollback verdicts).

Guardrails: at most MAX_CHANGES source changes a day, core sources are never paused, never fewer than
MIN_ACTIVE active news sources (and 2 per channel), weights stay in [0.5, 2.0] and move at most 0.25 a day,
safety filters are reused untouched, and the next step rolls back automatically if site health got worse.
Never raises out of main(): on any error the collectors keep the last good tuning.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import traceback
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"
EV = DATA / "evolve"
TZ = ZoneInfo("Asia/Shanghai")
P_LEDGER, P_TUNING, P_PROB, P_DIARY, P_STATE = (EV / "ledger.json", EV / "tuning.json", EV / "probation.json",
                                                 EV / "diary.json", EV / "state.json")
SNAPS = EV / "snapshots"

WINDOW_DAYS = 7
KEEP_DAYS = 21
MAX_CHANGES = 5            # source changes per day (pause / restore / weight / cadence / promote)
W_MIN, W_MAX, W_STEP = 0.5, 2.0, 0.25
MIN_ACTIVE_FRAC = 0.75     # never fewer than 75% of the news sources active
MIN_PER_CHANNEL = 2
PAUSE_RETEST_DAYS = 3
PROBATION_MAX = 6
NEW_CANDIDATES_PER_DAY = 2
PROMOTE_PER_DAY = 1
CORE_NEWS = {"techcrunch-ai", "verge-ai", "openai", "deepmind", "google-ai", "huggingface", "qbitai", "ithome"}
CORE_DEALS = {"HN", "V2EX", "GitHub"}
DEAL_SOURCES = ["HN", "V2EX", "GitHub", "DEV.to", "Lobsters"]
DEAL_NAMES = {"HN": "Hacker News", "V2EX": "V2EX", "GitHub": "GitHub", "DEV.to": "DEV 社区", "Lobsters": "Lobsters"}
# rollback thresholds (post-step day vs. 3-day baseline)
RB_KEPT_DROP = 0.35        # kept-per-run fell by more than 35%
RB_DEAD_RISE = 0.05        # dead-link rate rose by more than 5 points
RB_BUILD_RISE = 0.25       # failed/rolled-back builds rose by more than 25 points
# candidate feeds to try when mining finds nothing (AI / dev / science only; trial decides)
SEED_CANDIDATES = [
    ("interconnects", "Interconnects", "https://www.interconnects.ai/", "https://www.interconnects.ai/feed", "ai"),
    ("huyenchip", "Chip Huyen", "https://huyenchip.com/", "https://huyenchip.com/feed.xml", "ai"),
    ("eugeneyan", "Eugene Yan", "https://eugeneyan.com/", "https://eugeneyan.com/rss/", "ai"),
    ("raschka", "Ahead of AI", "https://magazine.sebastianraschka.com/", "https://magazine.sebastianraschka.com/feed", "ai"),
    ("oneusefulthing", "One Useful Thing", "https://www.oneusefulthing.org/", "https://www.oneusefulthing.org/feed", "ai"),
    ("langchain-blog", "LangChain Blog", "https://blog.langchain.com/", "https://blog.langchain.com/rss/", "dev"),
    ("vllm-blog", "vLLM Blog", "https://blog.vllm.ai/", "https://blog.vllm.ai/feed.xml", "dev"),
    ("pytorch-blog", "PyTorch Blog", "https://pytorch.org/", "https://pytorch.org/feed/", "dev"),
    ("google-research", "Google Research", "https://research.google/", "https://research.google/blog/rss/", "ai"),
    ("pragmatic-eng", "The Pragmatic Engineer", "https://newsletter.pragmaticengineer.com/", "https://newsletter.pragmaticengineer.com/feed", "dev"),
]


# ---- io ------------------------------------------------------------------------------------------
def now() -> datetime:
    return datetime.now(TZ)


def today() -> str:
    return now().strftime("%Y-%m-%d")


def jload(p: Path, default):
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
        return v if isinstance(v, type(default)) else default
    except Exception:
        return default


def jsave(p: Path, v) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(v, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)


def days_back(n: int, end: str | None = None) -> list[str]:
    e = datetime.strptime(end or today(), "%Y-%m-%d")
    return [(e - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def news_registry() -> list[dict]:
    return (jload(DATA / "news" / "sources.json", {}).get("sources") or [])


# ---- ledger --------------------------------------------------------------------------------------
def _add(d: dict, k: str, v) -> None:
    d[k] = d.get(k, 0) + (v or 0)


def update_ledger(over: dict | None = None, day: str | None = None, save: bool = True, L: dict | None = None) -> dict:
    """over: {relative path: parsed json} replaces files (used by backfill from git history)."""
    def src(rel: str, default):
        if over is not None:
            v = over.get(rel)
            return v if isinstance(v, type(default)) else default
        return jload(ROOT / rel, default)
    L = L if L is not None else jload(P_LEDGER, {})
    L.setdefault("days", {}); L.setdefault("seen", {})
    seen = L["seen"]
    day = day or today()
    D = L["days"].setdefault(day, {"news": {}, "deals": {}, "site": {}})
    for k in ("news", "deals", "site"):
        D.setdefault(k, {})
    # news collector: one status file per run
    st = src("data/news/collect_status.json", {})
    if st.get("run_at") and st.get("run_at") > seen.get("news_run", "") and st["run_at"][:10] == day:
        seen["news_run"] = st["run_at"]
        for key, s in (st.get("sources") or {}).items():
            e = D["news"].setdefault(key, {})
            _add(e, "runs", 1); _add(e, "ok_runs", 1 if s.get("ok") else 0)
            _add(e, "found", s.get("rows")); _add(e, "kept", s.get("new")); _add(e, "blocked", s.get("blocked"))
            _add(e, "dup_or_old", max(0, int(s.get("rows") or 0) - int(s.get("new") or 0) - int(s.get("blocked") or 0)))
            if not s.get("ok"):
                _add(e, "fails", 1)
        _add(D["site"], "news_kept", st.get("new"))
        _add(D["site"], "news_runs", 1)
    # deal sources: per-source health registry (one entry per run) + today's kept items by source
    sh = src("data/sources_health.json", {}).get("sources") or {}
    ds = seen.setdefault("deals", {})
    for name in DEAL_SOURCES:
        e0 = sh.get(name) or {}
        lr = e0.get("last_run")
        if lr and lr > ds.get(name, "") and lr[:10] == day:
            ds[name] = lr
            e = D["deals"].setdefault(name, {})
            ok = e0.get("last_ok") == lr
            _add(e, "runs", 1); _add(e, "ok_runs", 1 if ok else 0); _add(e, "found", e0.get("last_count"))
            if not ok:
                _add(e, "fails", 1)
    deals_today = src(f"data/auto/{day}.json", {}).get("items") or []
    by = {}
    for it in deals_today:
        by[it.get("source")] = by.get(it.get("source"), 0) + 1
    for name in DEAL_SOURCES:
        if name in D["deals"] or by.get(name):
            D["deals"].setdefault(name, {})["kept"] = by.get(name, 0)  # distinct items on today's list
    # update log: items added per run
    ul = (src("data/_update_log.json", {}).get("entries") or [])
    last = seen.get("update_at", "")
    for en in reversed(ul):
        at = en.get("at") or ""
        if at > last and at[:10] == day:
            _add(D["site"], "added", en.get("added")); _add(D["site"], "runs", 1)
            seen["update_at"] = at
    # link check: dead links overall + per deal source (joined by url)
    lc = src("data/auto/linkcheck.json", {})
    if lc.get("checked_at") and lc["checked_at"][:10] == day and lc["checked_at"] != seen.get("linkcheck") and not lc.get("unreliable_run"):
        seen["linkcheck"] = lc["checked_at"]
        items = lc.get("items") or {}
        dead_urls = {v.get("url") for v in items.values() if v.get("verdict") not in ("ok", None) or int(v.get("fails") or 0) >= 2}
        D["site"]["checked"] = len(items); D["site"]["dead"] = len(dead_urls)
        url_src = {}
        for dd in days_back(WINDOW_DAYS):
            for it in (jload(DATA / "auto" / f"{dd}.json", {}).get("items") or []):
                url_src.setdefault(it.get("url"), it.get("source"))
        dead_by = {}
        for u in dead_urls:
            s = url_src.get(u)
            if s:
                dead_by[s] = dead_by.get(s, 0) + 1
        for name in DEAL_SOURCES:
            if name in D["deals"]:
                D["deals"][name]["dead_links"] = dead_by.get(name, 0)
    # build result of the previous pipeline run (status page data)
    es = (src("data/_internal_status.json", {}).get("engines") or {})
    for eid, e in es.items():
        at = e.get("last_run_at") or ""
        k = "build_" + eid
        if at and at > seen.get(k, "") and at[:10] == day:
            seen[k] = at
            res = e.get("result") or "ok"
            _add(D["site"], "build_ok" if res == "ok" else "build_bad", 1)
    D["site"]["updated_at"] = now().isoformat(timespec="minutes")
    for k in sorted(L["days"])[:-KEEP_DAYS]:
        L["days"].pop(k, None)
    L["updated_at"] = now().isoformat(timespec="minutes")
    if save:
        jsave(P_LEDGER, L)
    return L


def backfill(days: int = 8) -> None:
    """Rebuild the ledger from the repo's own history (each automated commit = one run)."""
    import subprocess
    files = ["data/news/collect_status.json", "data/sources_health.json", "data/_internal_status.json", "data/auto/linkcheck.json"]
    log = subprocess.run(["git", "log", f"--since={days} days ago", "--reverse", "--format=%H %cI", "--", *files],
                         cwd=ROOT, capture_output=True, text=True, timeout=120).stdout.split("\n")
    L = {"days": {}, "seen": {}}
    for line in log:
        if not line.strip():
            continue
        sha, ci = line.split()
        day = datetime.fromisoformat(ci).astimezone(TZ).strftime("%Y-%m-%d")
        over = {}
        for f in files + ["data/_update_log.json", f"data/auto/{day}.json"]:
            r = subprocess.run(["git", "show", f"{sha}:{f}"], cwd=ROOT, capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                try:
                    over[f] = json.loads(r.stdout)
                except Exception:
                    pass
        update_ledger(over=over, day=day, save=False, L=L)
    jsave(P_LEDGER, L)
    update_ledger()
    print("[evolve] backfilled days:", sorted(L["days"]))


def window(L: dict, group: str, days: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in days:
        for k, e in ((L.get("days") or {}).get(d, {}).get(group) or {}).items():
            o = out.setdefault(k, {"days": 0})
            o["days"] += 1
            for f, v in e.items():
                if isinstance(v, (int, float)):
                    o[f] = o.get(f, 0) + v
    for o in out.values():
        r = max(1, o.get("runs", 0))
        o["fail_rate"] = round(o.get("fails", 0) / r, 3)
        o["kept_per_run"] = round(o.get("kept", 0) / r, 3)
        o["block_rate"] = round(o.get("blocked", 0) / max(1, o.get("found", 0)), 3)
    return out


def site_metrics(L: dict, days: list[str]) -> dict:
    s = {"kept": 0, "runs": 0, "dead": 0, "checked": 0, "build_ok": 0, "build_bad": 0}
    for d in days:
        x = (L.get("days") or {}).get(d, {}).get("site") or {}
        s["kept"] += int(x.get("news_kept", 0)) + int(x.get("added", 0))
        s["runs"] += max(int(x.get("news_runs", 0)), int(x.get("runs", 0)))
        s["dead"] += int(x.get("dead", 0)); s["checked"] += int(x.get("checked", 0))
        s["build_ok"] += int(x.get("build_ok", 0)); s["build_bad"] += int(x.get("build_bad", 0))
    s["kept_per_run"] = round(s["kept"] / s["runs"], 2) if s["runs"] else None
    s["dead_rate"] = round(s["dead"] / s["checked"], 4) if s["checked"] else None
    b = s["build_ok"] + s["build_bad"]
    s["bad_build_rate"] = round(s["build_bad"] / b, 3) if b else None
    return s


# ---- rollback ------------------------------------------------------------------------------------
def judge_last_step(L: dict, state: dict) -> tuple[str | None, str]:
    """'rolled_back' / 'kept' / None (not judged yet)."""
    step = state.get("last_step") or {}
    if not step or step.get("verdict") or not step.get("changes"):
        return None, ""
    d0 = step.get("date")
    post_days = [d for d in days_back(3) if d > d0 and d < today()] or ([today()] if today() > d0 else [])
    if not post_days:
        return None, ""
    post, base = site_metrics(L, post_days), step.get("baseline") or {}
    if post["runs"] < 3:
        return None, ""
    why = []
    if base.get("kept_per_run") and post["kept_per_run"] is not None and base["kept_per_run"] >= 1 \
            and post["kept_per_run"] < base["kept_per_run"] * (1 - RB_KEPT_DROP):
        why.append(f"kept/run {base['kept_per_run']}→{post['kept_per_run']}")
    if base.get("dead_rate") is not None and post["dead_rate"] is not None and post["dead_rate"] - base["dead_rate"] > RB_DEAD_RISE:
        why.append(f"dead {base['dead_rate']}→{post['dead_rate']}")
    if base.get("bad_build_rate") is not None and post["bad_build_rate"] is not None \
            and post["bad_build_rate"] - base["bad_build_rate"] > RB_BUILD_RISE:
        why.append(f"bad builds {base['bad_build_rate']}→{post['bad_build_rate']}")
    step["post"] = post
    if why:
        snap = None
        sp = Path(step.get("snapshot") or "")
        for cand in (sp if sp.is_absolute() else ROOT / sp,):
            try:
                snap = json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                snap = None
        if isinstance(snap, dict):
            jsave(P_TUNING, snap)
            step["verdict"] = "rolled_back"; step["why"] = why
            return "rolled_back", "; ".join(why)
    step["verdict"] = "kept"
    return "kept", ""


# ---- tuning rules --------------------------------------------------------------------------------
def plan_changes(L: dict, T: dict) -> list[dict]:
    """Rule-based proposals, highest priority first. Applied later under the caps."""
    days7 = days_back(WINDOW_DAYS)
    W = window(L, "news", days7)
    reg = {s["key"]: s for s in news_registry()} | {s["key"]: s for s in (T.get("promoted_news") or [])}
    tn = T.setdefault("news", {})
    props: list[dict] = []
    kprs = sorted(w["kept_per_run"] for k, w in W.items() if w.get("runs", 0) >= 6)
    median = kprs[len(kprs) // 2] if kprs else 0
    td = today()
    for key, s in reg.items():
        e = tn.get(key) or {}
        st, wgt = e.get("state", "active"), float(e.get("weight", 1.0))
        w = W.get(key) or {}
        name = s.get("name") or key
        if st == "paused":
            since = e.get("since") or td
            if (datetime.strptime(td, "%Y-%m-%d") - datetime.strptime(since, "%Y-%m-%d")).days >= PAUSE_RETEST_DAYS:
                props.append({"group": "news", "key": key, "name": name, "op": "retest", "prio": 1})
            continue
        if st == "retest":
            rw = window(L, "news", [d for d in days7 if d >= (e.get("since") or td)]).get(key) or {}
            if rw.get("ok_runs", 0) >= 2 and rw.get("found", 0) > 0:
                props.append({"group": "news", "key": key, "name": name, "op": "restore", "prio": 0})
            elif rw.get("runs", 0) >= 3 and rw.get("ok_runs", 0) == 0:
                props.append({"group": "news", "key": key, "name": name, "op": "pause", "prio": 2, "why": "复测还是打不开"})
            continue
        if w.get("runs", 0) >= 8 and w["fail_rate"] >= 0.9 and key not in CORE_NEWS:
            props.append({"group": "news", "key": key, "name": name, "op": "pause", "prio": 2, "why": "最近总是打不开"})
        elif w.get("runs", 0) >= 12 and w.get("days", 0) >= 3 and w.get("found", 0) > 0 and w.get("kept", 0) == 0:
            if wgt <= W_MIN and int(e.get("every", 1)) >= 2 and key not in CORE_NEWS:
                props.append({"group": "news", "key": key, "name": name, "op": "pause", "prio": 3, "why": "一周都没有新东西"})
            elif wgt > W_MIN or int(e.get("every", 1)) < 2:
                props.append({"group": "news", "key": key, "name": name, "op": "slower", "prio": 4, "why": "总是重复，没有新东西"})
        elif w.get("runs", 0) >= 8 and w.get("days", 0) >= 2 and w.get("found", 0) >= 40 and w["block_rate"] >= 0.5 and wgt > W_MIN:
            props.append({"group": "news", "key": key, "name": name, "op": "down", "prio": 5, "why": "被过滤掉的内容太多"})
        elif w.get("runs", 0) >= 6 and median > 0 and w["kept_per_run"] >= 2 * median and w["fail_rate"] < 0.2 and wgt < W_MAX:
            props.append({"group": "news", "key": key, "name": name, "op": "up", "prio": 6, "kept": w.get("kept", 0)})
    # deal sources: only pause / retest / restore on reachability (weight has no meaning there)
    WD = window(L, "deals", days7)
    tdl = T.setdefault("deals", {})
    for name in DEAL_SOURCES:
        e = tdl.get(name) or {}
        st = e.get("state", "active")
        w = WD.get(name) or {}
        nm = DEAL_NAMES.get(name, name)
        if st == "paused":
            since = e.get("since") or td
            if (datetime.strptime(td, "%Y-%m-%d") - datetime.strptime(since, "%Y-%m-%d")).days >= PAUSE_RETEST_DAYS:
                props.append({"group": "deals", "key": name, "name": nm, "op": "retest", "prio": 1})
        elif st == "retest":
            rw = window(L, "deals", [d for d in days7 if d >= (e.get("since") or td)]).get(name) or {}
            if rw.get("ok_runs", 0) >= 2:
                props.append({"group": "deals", "key": name, "name": nm, "op": "restore", "prio": 0})
            elif rw.get("runs", 0) >= 3 and rw.get("ok_runs", 0) == 0:
                props.append({"group": "deals", "key": name, "name": nm, "op": "pause", "prio": 2, "why": "复测还是没有内容"})
        elif name not in CORE_DEALS and w.get("runs", 0) >= 8 and w["fail_rate"] >= 0.9:
            props.append({"group": "deals", "key": name, "name": nm, "op": "pause", "prio": 2, "why": "最近总是没有内容"})
    props.sort(key=lambda p: p["prio"])
    return props


def active_ok_after_pause(T: dict, key: str) -> bool:
    reg = news_registry() + list(T.get("promoted_news") or [])
    tn = T.get("news") or {}
    act = [s for s in reg if (tn.get(s["key"]) or {}).get("state", "active") != "paused" and not s.get("disabled")]
    if len(act) - 1 < int(len(reg) * MIN_ACTIVE_FRAC):
        return False
    ch = next((s.get("channel") for s in reg if s["key"] == key), None)
    return sum(1 for s in act if s.get("channel") == ch) - 1 >= MIN_PER_CHANNEL


def apply_change(T: dict, p: dict) -> bool:
    g = T.setdefault(p["group"], {})
    e = g.setdefault(p["key"], {})
    td, op = today(), p["op"]
    wgt = float(e.get("weight", 1.0))
    if op == "pause":
        if p["group"] == "news" and not active_ok_after_pause(T, p["key"]):
            return False
        if p["group"] == "deals":
            act = [n for n in DEAL_SOURCES if (T["deals"].get(n) or {}).get("state", "active") != "paused"]
            if len(act) - 1 < 3:
                return False
        e.update(state="paused", since=td)
    elif op == "retest":
        e.update(state="retest", since=td)
    elif op == "restore":
        e.update(state="active", since=td, weight=0.75 if p["group"] == "news" else 1.0, every=1)
    elif op == "slower":
        e.update(weight=max(W_MIN, round(wgt - W_STEP, 2)), every=2, since=td)
    elif op == "down":
        e.update(weight=max(W_MIN, round(wgt - W_STEP, 2)), since=td)
    elif op == "up":
        e.update(weight=min(W_MAX, round(wgt + W_STEP, 2)), every=1, since=td)
    elif op == "set_weight":
        nw = max(W_MIN, min(W_MAX, float(p["weight"])))
        nw = max(wgt - W_STEP, min(wgt + W_STEP, nw))
        if abs(nw - wgt) < 0.01:
            return False
        e.update(weight=round(nw, 2), since=td)
    else:
        return False
    e["why"] = p.get("why", "")[:40]
    return True


# ---- probation -----------------------------------------------------------------------------------
def _domain(u: str) -> str:
    try:
        return urllib.parse.urlparse(u).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def known_domains(T: dict) -> set[str]:
    out = set()
    for s in news_registry() + list(T.get("promoted_news") or []):
        out.add(_domain(s.get("home", ""))); out.add(_domain(s.get("feed", "")))
    return out - {""}


def find_candidates(T: dict, P: dict) -> list[dict]:
    """Mine domains that keep showing up inside existing feeds (aggregators link out to them), then seed list."""
    have = known_domains(T) | {_domain(c["feed"]) for c in P.get("candidates", [])} | set(P.get("rejected_domains", []))
    out: list[dict] = []
    try:
        db = jload(DATA / "news" / "db.json", {}).get("items") or []
        cnt: dict[str, list] = {}
        for x in db:
            d = _domain(x.get("url", ""))
            if d and d not in have and d not in ("github.com", "news.google.com", "x.com", "twitter.com", "youtube.com",
                                                   "medium.com", "reddit.com", "arxiv.org", "news.ycombinator.com"):
                cnt.setdefault(d, []).append(x.get("channel") or "ai")
        for d, chs in sorted(cnt.items(), key=lambda kv: -len(kv[1]))[:6]:
            if len(chs) < 3:
                break
            feed = probe_feed("https://" + d + "/")
            if feed:
                ch = max(set(chs), key=chs.count)
                out.append({"key": "cand-" + re.sub(r"[^a-z0-9]+", "-", d)[:40], "name": d, "home": "https://" + d + "/",
                            "feed": feed, "channel": ch, "lang": "en", "origin": "mined"})
            if len(out) >= NEW_CANDIDATES_PER_DAY:
                return out
    except Exception as e:
        print("[evolve] mining skipped:", type(e).__name__)
    for key, name, home, feed, ch in SEED_CANDIDATES:
        if len(out) >= NEW_CANDIDATES_PER_DAY:
            break
        if _domain(feed) in have or any(c["key"] == key for c in P.get("candidates", [])) or key in P.get("rejected", []):
            continue
        out.append({"key": key, "name": name, "home": home, "feed": feed, "channel": ch, "lang": "en", "origin": "seed"})
    return out


def probe_feed(home: str) -> str | None:
    import news_collect as nc
    try:
        html = nc.get(home, timeout=10).decode("utf-8", "ignore")[:300000]
        m = re.search(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', html, re.I)
        if m:
            h = re.search(r'href=["\']([^"\']+)', m.group(0))
            if h:
                return urllib.parse.urljoin(home, h.group(1))
    except Exception:
        pass
    for path in ("feed", "rss", "feed.xml", "rss.xml", "atom.xml", "index.xml"):
        u = urllib.parse.urljoin(home, path)
        try:
            raw = nc.get(u, timeout=10)
            if nc.parse_feed(raw):
                return u
        except Exception:
            continue
    return None


def trial(c: dict) -> dict:
    """Fetch the candidate feed without publishing anything; score it with the site's own filters."""
    import news_collect as nc
    r = {"date": today(), "ok": False, "rows": 0, "recent": 0, "blocked": 0, "on_topic": 0, "offtopic": 0}
    try:
        rows = nc.parse_feed(nc.get(c["feed"], timeout=15))[:30]
        r["rows"] = len(rows)
        cut = now() - timedelta(days=7)
        for x in rows:
            t, d = nc.clean(x.get("title") or ""), nc.clean(x.get("desc") or "")[:400]
            pd = nc.pdate(x.get("date"))
            if pd and pd >= cut:
                r["recent"] += 1
            if nc.blocked(t, d, x.get("link") or ""):
                r["blocked"] += 1
            if nc.AI_KW.search(t + " " + d):
                r["on_topic"] += 1
            if nc.OFFTOPIC.search(t):
                r["offtopic"] += 1
        r["ok"] = r["rows"] > 0
        r["zh"] = sum(1 for x in rows if re.search(r"[\u4e00-\u9fff]", x.get("title") or "")) > len(rows) / 2 if rows else None
    except Exception as e:
        r["error"] = type(e).__name__
    return r


def run_probation(T: dict, P: dict, budget: list[int]) -> list[dict]:
    """Trial every candidate once a day, add new ones, promote at most one. Returns diary events."""
    ev: list[dict] = []
    P.setdefault("candidates", []); P.setdefault("rejected", []); P.setdefault("rejected_domains", [])
    if len(P["candidates"]) < PROBATION_MAX:
        for c in find_candidates(T, P)[:PROBATION_MAX - len(P["candidates"])]:
            c.update(added=today(), trials=[])
            P["candidates"].append(c)
            ev.append({"op": "probation", "name": c["name"]})
    promoted = 0
    keep = []
    for c in P["candidates"]:
        tr = c.setdefault("trials", [])
        if not tr or tr[-1].get("date") != today():
            tr.append(trial(c))
            del tr[:-7]
        days_ok = [t for t in tr if t.get("ok")]
        tot_rows = sum(t["rows"] for t in tr) or 1
        blocked = sum(t.get("blocked", 0) for t in tr)
        on_topic = sum(t.get("on_topic", 0) for t in tr) / tot_rows
        recent = sum(t.get("recent", 0) for t in days_ok) / max(1, len(days_ok))
        c["score"] = {"trials": len(tr), "ok": len(days_ok), "blocked": blocked, "on_topic": round(on_topic, 2), "recent": round(recent, 1)}
        block_rate = blocked / tot_rows
        c["score"]["block_rate"] = round(block_rate, 2)
        if block_rate > 0.3:  # mostly content the sensitive-word filter drops = never
            P["rejected"].append(c["key"]); P["rejected_domains"].append(_domain(c["feed"]))
            ev.append({"op": "reject", "name": c["name"], "why": "内容不合规"})
            continue
        if tr[-1].get("zh") is not None:
            c["lang"] = "zh" if tr[-1]["zh"] else "en"
        passed = (len(days_ok) >= 3 and len(days_ok) == len(tr) and recent >= 1.5 and on_topic >= 0.4
                  and block_rate <= 0.1)
        if passed and promoted < PROMOTE_PER_DAY and budget[0] > 0:
            entry = {k: c[k] for k in ("key", "name", "home", "feed", "channel", "lang")}
            entry.update(need_ai=c.get("channel") in ("ai", "aigc", "aivideo", "dev"), promoted_at=today())
            T.setdefault("promoted_news", []).append(entry)
            T.setdefault("news", {})[c["key"]] = {"state": "active", "weight": W_MIN, "every": 1, "since": today(), "why": "试用合格"}
            promoted += 1; budget[0] -= 1
            ev.append({"op": "promote", "name": c["name"]})
            continue
        if len(tr) >= 6 and not passed:
            P["rejected"].append(c["key"])
            ev.append({"op": "reject", "name": c["name"], "why": "试用不合格"})
            continue
        keep.append(c)
    P["candidates"] = keep
    P["rejected"] = P["rejected"][-200:]; P["rejected_domains"] = P["rejected_domains"][-200:]
    return ev


# ---- diary ---------------------------------------------------------------------------------------
def rule_diary(events: list[dict], facts: dict) -> list[str]:
    by = {}
    for e in events:
        by.setdefault(e["op"], []).append(e)
    lines = []

    def names(L, n=2):
        s = "、".join(e["name"] for e in L[:n])
        s = s + (f" 等 {len(L)} 个来源" if len(L) > n else "")
        return s + (" " if s and s[-1].isascii() else "")
    if by.get("rollback"):
        lines.append("我发现上次的调整让收获变少了，已经自动退回原来的设置。")
    if facts.get("best"):
        b = facts["best"]
        lines.append(f"今天我学会了：{b['name']} 最近 7 天给了我 {b['kept']} 条新内容，最靠谱。")
    if by.get("up"):
        lines.append(f"我调整了：{names(by['up'])}出货多，我会多看它几眼。")
    if by.get("slower"):
        lines.append(f"我调整了：{names(by['slower'])}总是重复，我放慢了去看它的频率。")
    if by.get("down"):
        lines.append(f"我调整了：{names(by['down'])}不对口的内容偏多，我调低了它的分量。")
    if by.get("pause"):
        lines.append(f"我淘汰了：{names(by['pause'])}最近不太行，先歇几天，之后我再去试。")
    if by.get("restore"):
        lines.append(f"{names(by['restore'])}重新能用了，我把它请了回来。")
    if by.get("promote"):
        lines.append(f"新来源 {names(by['promote'])}通过了试用，开始少量上架。")
    elif by.get("probation"):
        lines.append(f"我在试用新来源 {names(by['probation']).rstrip()}，合格了才会上架。")
    if not any(e["op"] in ("up", "slower", "down", "pause", "restore", "promote", "rollback") for e in events):
        lines.append("今天各个来源都挺稳，我没有改动设置。")
    return lines[:4]


def model_reflect(facts: dict, planned: list[dict]) -> dict | None:
    """The model may veto planned changes, nudge up to two weights, and write the diary. Everything is re-validated."""
    try:
        import llm
        if not llm.available():
            return None
        sys_p = ("你是一个自动运行的中文科技资讯网站的大脑，每天复盘一次各个内容来源的表现。你只能在给定范围内提建议："
                 "veto：你认为不该执行的计划改动（填计划里的 key）；nudge：最多 2 个来源的权重微调（0.5 到 2.0）；"
                 "diary：2 到 4 句第一人称的进化日记，每句不超过 36 个字，用「今天我学会了」「我调整了」「我淘汰了」这类开头，"
                 "每句都必须点名一个数据里出现的具体来源名称（原样照抄），只写「今天的改动」里真实发生的调整，没有就写学到了什么；"
                 "只能根据给定数据，不编造数字，不提文件名、代码、模型、密钥等内部细节，不谈政治。nudge 的 key 必须用 top5 里的 key。只输出 JSON："
                 "{\"veto\":[],\"nudge\":[{\"key\":\"\",\"weight\":1.0}],\"diary\":[]}")
        user = json.dumps({"数据": facts, "今天的改动": facts.get("changes_today"), "计划改动": [{k: p.get(k) for k in ("key", "name", "op", "why")} for p in planned]}, ensure_ascii=False)
        d = llm.chat_json(sys_p, user, scope="evolve", max_tokens=700, temperature=0.4, cache=False)
        llm.save_cache()
        return d if isinstance(d, dict) else None
    except Exception as e:
        print("[evolve] model reflection skipped:", type(e).__name__)
        return None


def fact_names(facts: dict) -> list[str]:
    out = [x["name"] for x in (facts.get("top5") or []) + (facts.get("bottom5") or []) + (facts.get("changes_today") or []) if x.get("name")]
    if facts.get("best"):
        out.append(facts["best"]["name"])
    return [n for n in out if n]


def valid_line(s: str, facts_text: str, names: list[str] | None = None) -> bool:
    try:
        import news_collect as nc
        if nc.blocked(s):
            return False
    except Exception:
        return False
    if not s or len(s) > 48 or not re.search(r"[\u4e00-\u9fff]", s) or not s.startswith(("今天我", "我", "新来源")):
        return False
    if re.search(r"https?://|\.json|\.py|tuning|ledger|token|密钥|LLM|AI 模型|大模型接口|GitHub Actions|引擎", s, re.I):
        return False
    if names is not None and not any(n and n in s for n in names):
        return False  # every line has to name a real source
    return all(n in facts_text for n in re.findall(r"\d+(?:\.\d+)?", s))  # no invented numbers


def write_diary(lines: list[str], by: str, events: list[dict]) -> None:
    D = jload(P_DIARY, {})
    days = [d for d in (D.get("days") or []) if d.get("date") != today()]
    days.insert(0, {"date": today(), "lines": lines[:4], "by": by, "events": events[:12],
                    "at": now().isoformat(timespec="minutes")})
    jsave(P_DIARY, {"updated_at": now().isoformat(timespec="minutes"), "days": days[:14]})


# ---- daily step ----------------------------------------------------------------------------------
def build_facts(L: dict, T: dict, events: list[dict]) -> dict:
    W = window(L, "news", days_back(WINDOW_DAYS))
    reg = {s["key"]: s.get("name") or s["key"] for s in news_registry() + list(T.get("promoted_news") or [])}
    ranked = sorted(((k, w) for k, w in W.items() if k in reg and w.get("runs", 0) >= 3), key=lambda kv: -kv[1].get("kept", 0))
    best = {"name": reg[ranked[0][0]], "kept": int(ranked[0][1].get("kept", 0))} if ranked and ranked[0][1].get("kept", 0) > 0 else None
    sm = site_metrics(L, days_back(WINDOW_DAYS))
    act = sum(1 for k in reg if (T.get("news", {}).get(k) or {}).get("state", "active") != "paused")
    return {"best": best, "top5": [{"key": k, "name": reg[k], "kept_7d": int(w.get("kept", 0)), "runs": w.get("runs", 0)} for k, w in ranked[:5]],
            "bottom5": [{"name": reg[k], "kept_7d": int(w.get("kept", 0)), "fail_rate": w["fail_rate"]} for k, w in ranked[-5:]],
            "sources_total": len(reg), "sources_active": act, "site_7d": {"kept": sm["kept"], "runs": sm["runs"],
            "dead_rate": sm["dead_rate"]}, "changes_today": [{"op": e["op"], "name": e["name"]} for e in events]}


def daily(dry: bool = False) -> dict:
    L = jload(P_LEDGER, {"days": {}})
    T0 = jload(P_TUNING, {})
    T = copy.deepcopy(T0)
    P = jload(P_PROB, {})
    state = jload(P_STATE, {})
    events: list[dict] = []
    # 1) judge yesterday's step; roll back if site health got worse
    verdict, why = judge_last_step(L, state) if not dry else (None, "")
    if verdict == "rolled_back":
        T = jload(P_TUNING, {})
        events.append({"op": "rollback", "name": "", "why": why})
        print("[evolve] rolled back:", why)
    budget = [MAX_CHANGES]
    applied: list[dict] = []
    if verdict != "rolled_back":  # cool down for a day after a rollback
        planned = plan_changes(L, T)
        facts0 = build_facts(L, T, [])
        model = model_reflect(facts0, planned) if not dry else None
        veto = set((model or {}).get("veto") or []) if model else set()
        for p in planned:
            if budget[0] <= 0:
                break
            if p["key"] in veto and p["op"] in ("pause", "slower", "down", "up"):
                continue  # the model may only hold back a change, never force one
            if apply_change(T, p):
                applied.append(p); budget[0] -= 1
        reg_keys = {s["key"] for s in news_registry()}
        done = {p["key"] for p in applied}
        for n in ((model or {}).get("nudge") or [])[:2]:
            if budget[0] <= 0 or not isinstance(n, dict) or n.get("key") not in reg_keys or n["key"] in done:
                continue
            if (T.get("news", {}).get(n["key"]) or {}).get("state", "active") != "active":
                continue
            try:
                p = {"group": "news", "key": n["key"], "name": next(s["name"] for s in news_registry() if s["key"] == n["key"]),
                     "op": "set_weight", "weight": float(n.get("weight")), "why": "复盘微调"}
            except Exception:
                continue
            old = float((T.get("news", {}).get(n["key"]) or {}).get("weight", 1.0))
            if apply_change(T, p):
                p["op"] = "up" if T["news"][n["key"]]["weight"] > old else "down"
                applied.append(p); budget[0] -= 1
        events += [{"op": p["op"], "name": p["name"], "key": p["key"], "why": p.get("why", "")} for p in applied]
        if not dry:
            try:
                events += run_probation(T, P, budget)
            except Exception as e:
                print("[evolve] probation skipped:", type(e).__name__)
    else:
        model = None
    facts = build_facts(L, T, events)
    lines = rule_diary(events, facts)
    by = "rules"
    if model is None and verdict == "rolled_back":
        model = model_reflect(facts, []) if not dry else None
    ml = [str(x).strip() for x in ((model or {}).get("diary") or [])][:4]
    ft = json.dumps(facts, ensure_ascii=False)
    nm = fact_names(facts)
    if ml and all(valid_line(x, ft, nm) for x in ml) and len(ml) >= 2:
        lines, by = ml, "model"
    if dry:
        print(json.dumps({"would_apply": events, "diary": lines, "by": by}, ensure_ascii=False, indent=1))
        return {"events": events, "lines": lines}
    # 2) snapshot the tuning that was live before today's step, then write the new one
    SNAPS.mkdir(parents=True, exist_ok=True)
    snap = SNAPS / f"{today()}.json"
    if not snap.exists():
        jsave(snap, T0)
    for old in sorted(SNAPS.glob("*.json"))[:-10]:
        old.unlink(missing_ok=True)
    T["updated_at"] = now().isoformat(timespec="minutes")
    T["note"] = "由 evolve.py 每天自动维护；采集脚本只读。删除此文件即恢复默认（全部来源、权重 1.0）。"
    jsave(P_TUNING, T); jsave(P_PROB, P)
    tuning_changes = [e for e in events if e["op"] not in ("probation", "reject")]
    state["last_step"] = {"date": today(), "changes": tuning_changes, "snapshot": str(snap.relative_to(ROOT)),
                          "baseline": site_metrics(L, days_back(3, (now() - timedelta(days=1)).strftime("%Y-%m-%d")) + [today()]),
                          **({"verdict": "rolled_back", "why": why} if verdict == "rolled_back" else {})}
    hist = state.setdefault("history", [])
    hist.insert(0, {"date": today(), "verdict_prev": verdict, "changes": len(tuning_changes), "diary_by": by})
    del hist[30:]
    state["last_evolve_date"] = today()
    jsave(P_STATE, state)
    write_diary(lines, by, events)
    print(f"[evolve] {today()} changes={len(tuning_changes)} events={len(events)} diary_by={by}")
    for x in lines:
        print("  ·", x)
    return {"events": events, "lines": lines}


def refresh_diary_with_model() -> bool:
    """A rule-written diary for today can be rewritten by the model later (same facts, same validation)."""
    D = jload(P_DIARY, {})
    d0 = (D.get("days") or [{}])[0]
    if d0.get("date") != today() or d0.get("by") != "rules" or d0.get("model_tried"):
        return False
    L, T = jload(P_LEDGER, {"days": {}}), jload(P_TUNING, {})
    events = d0.get("events") or []
    facts = build_facts(L, T, events)
    model = model_reflect(facts, [])
    d0["model_tried"] = True
    ml = [str(x).strip() for x in ((model or {}).get("diary") or [])][:4]
    ft = json.dumps(facts, ensure_ascii=False)
    if ml and len(ml) >= 2 and all(valid_line(x, ft, fact_names(facts)) for x in ml):
        d0.update(lines=ml, by="model", at=now().isoformat(timespec="minutes"))
        print("[evolve] diary rewritten by model")
    jsave(P_DIARY, D)
    return True


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "run"
    try:
        if cmd == "backfill":
            backfill()
            return 0
        if cmd in ("run", "ledger"):
            try:
                update_ledger()
            except Exception:
                print("[evolve] ledger failed:\n" + traceback.format_exc()[-800:])
        if cmd == "dry":
            daily(dry=True)
            return 0
        if cmd in ("run", "daily"):
            st = jload(P_STATE, {})
            if st.get("last_evolve_date") != today() or "--force" in argv:
                daily()
            else:
                try:
                    import llm
                    if llm.available():
                        refresh_diary_with_model()
                except Exception:
                    pass
    except Exception:
        print("[evolve] step failed — collectors keep the last good tuning:\n" + traceback.format_exc()[-1200:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
