#!/usr/bin/env python3
"""Freshness & sharing outputs for the homepage build (called from build.py):
  * today_section()  - visible 「今日新增」 block for the homepage
  * write_atom()     - feed.atom (Atom 1.0, newest first, with updated dates)
  * write_digest()   - digest/today.txt + digest/<date>.txt + api/digest.json, ready-to-post text
                       (X single post, X thread, 微信群, 小红书). Nothing is posted anywhere.
  * write_linkcheck_report() - api/linkcheck.json with counts and auto-hidden items
"""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime


def _x_len(s: str) -> int:
    """X counts CJK/fullwidth characters as 2 and any URL as 23."""
    n = 0
    for w in s.split(" "):
        if w.startswith("http://") or w.startswith("https://"):
            n += 23
        else:
            n += sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in w)
        n += 1
    return n - 1


def _cut(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def today_items(B, active, now):
    today = now.date()
    t = [it for it in active if not it.get("pinned")
         and (B.curate.parse_dt(it.get("fetched_at")) or now).astimezone(B.TZ).date() == today]
    order = {"available": 0, "expiring": 1}
    t.sort(key=lambda i: (order.get(i.get("status"), 2), -(B.curate.parse_dt(i.get("fetched_at")) or now).timestamp()))
    return t


def pick_for_digest(B, active, now, k=5):
    """Today's best: verified/closing-soon first, then ones with clear steps; at most 2 per module, no near-duplicates."""
    t = today_items(B, active, now)
    rest = sorted([i for i in active if not i.get("pinned") and i not in t], key=lambda i: i.get("fetched_at") or "", reverse=True)
    pool = t + rest[:40]
    rank = {"available": 0, "expiring": 1}
    pool.sort(key=lambda i: (rank.get(i.get("status"), 2), 0 if i in t else 1, 0 if i.get("how") else 1,
                             1 if i.get("_kind") == "github" or (i.get("source_domain") or "").endswith("github.com") else 0))
    out, seen, per = [], set(), {}
    for it in pool:
        key = "".join(ch for ch in (it.get("summary") or it.get("title") or "")[:24] if ch.isalnum())
        m = it.get("module") or ""
        if key in seen or per.get(m, 0) >= 2:
            continue
        seen.add(key); per[m] = per.get(m, 0) + 1; out.append(it)
        if len(out) >= k:
            break
    return out


def today_section(B, active, now) -> str:
    esc = B.esc
    t = today_items(B, active, now)
    lc = B.LINKCHECK
    c = lc.get("counts") or {}
    chk = ""
    if lc.get("checked_at"):
        chk = (f'<p class="lc-sum">链接自动检查（{esc(B.fmt_dt(lc["checked_at"]))}）：<b>{c.get("ok", 0)}</b> 条能正常打开 · '
               f'<b>{c.get("recheck", 0)}</b> 条待复查 · <b>{len(lc.get("hidden") or [])}</b> 条失效已下架'
               f'{" · " + str(c.get("unsure", 0)) + " 条对方限制访问未能确认" if c.get("unsure") else ""}</p>')
    rows = "".join(
        f'<li><a href="{esc(it["_path"])}"><span class="td-time">{esc(B.fmt_dt(it.get("fetched_at"))[-5:])}</span>'
        f'<span class="td-t">{esc(it["title"])}</span></a>'
        f'<span class="td-m"><span class="st st-{B.STATUS_CLASS.get(it.get("status"), "muted")}">{esc(it.get("status_label") or "")}</span>'
        f'{esc(it.get("module_name") or "")}</span></li>' for it in t[:12])
    if not rows:
        rows = '<li class="td-empty">今天还没有新收录，程序每小时会再找一遍。</li>'
    more = f'<p class="td-more">今天共新增 {len(t)} 条，下面列表按“最新”排序可以看全部。</p>' if len(t) > 12 else ""
    return f"""<section class="section today-new" id="today">
    <div class="sec-head"><span class="sec-idx">今日新增 · {now.month} 月 {now.day} 日</span><h2>今天新收录 {len(t)} 条</h2>
      <p class="sec-desc">每条都写明收录时间、更新时间和链接检查结果；也可以用 <a href="feed.xml">RSS</a> / <a href="feed.atom">Atom</a> 订阅，或看 <a href="digest/today.txt">今日速递文字版</a>。</p></div>
    {chk}
    <ol class="today-list">{rows}</ol>{more}
  </section>"""


def write_atom(B, active, now) -> None:
    def x(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    items = sorted([i for i in active], key=lambda i: B.updated_at(i) or "", reverse=True)[:60]
    ents = []
    for it in items:
        up = B.curate.parse_dt(B.updated_at(it)) or now
        pub = B.curate.parse_dt(it.get("published_at") or it.get("fetched_at")) or up
        lcls, ltxt = B.link_state(it)
        body = f"{it.get('summary') or ''}\n状态：{it.get('status_label') or ''}；{ltxt}"
        ents.append(f"""  <entry>
    <title>{x(it['title'])}</title>
    <link href="{x(B.CANONICAL + it['_path'])}"/>
    <id>tag:aiym168.github.io,2026:{x(str(it['id']))}</id>
    <published>{pub.isoformat(timespec='seconds')}</published>
    <updated>{up.isoformat(timespec='seconds')}</updated>
    <category term="{x(it.get('module_name') or '')}"/>
    <summary>{x(body)}</summary>
  </entry>""")
    doc = (f'<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="zh-CN">\n'
           f'  <title>{x(B.SITE_NAME)}</title>\n  <subtitle>{x(B.META_DESC)}</subtitle>\n'
           f'  <link href="{x(B.CANONICAL)}"/>\n  <link rel="self" href="{x(B.CANONICAL)}feed.atom"/>\n'
           f'  <id>{x(B.CANONICAL)}</id>\n  <updated>{now.isoformat(timespec="seconds")}</updated>\n'
           f'  <author><name>{x(B.SITE_NAME)}</name></author>\n' + "\n".join(ents) + "\n</feed>\n")
    (B.SITE / "feed.atom").write_text(doc, encoding="utf-8")


def _flag(it) -> str:
    st = it.get("status")
    return "已核实" if st == "available" else "即将截止" if st == "expiring" else "未核实，以官网为准"


def digest_texts(B, active, now) -> dict:
    picks = pick_for_digest(B, active, now)
    tn = len(today_items(B, active, now))
    date = f"{now.month}月{now.day}日"
    home = B.CANONICAL + "#today"
    url = lambda it: B.CANONICAL + it["_path"]  # noqa: E731
    # X single post, trimmed to fit 280
    head = f"今日 AI 羊毛 {date}｜新增 {tn} 条，共 {len(active)} 条在列"
    lines, budget = [], 280 - _x_len(head + "\n\n全部 → " + home) - 2
    for n, it in enumerate(picks, 1):
        ln = f"{n}. {_cut(it['title'], 34)}"
        if _x_len("\n".join(lines + [ln])) > budget:
            break
        lines.append(ln)
    x_single = head + "\n" + "\n".join(lines) + "\n\n全部 → " + home
    x_thread = [head + "（逐条附链接，未核实的请以官网为准）👇"] + [
        f"{n}/ {_cut(it['title'], 60)}\n{_cut(it.get('summary') or '', 70)}\n{_flag(it)} · {url(it)}" for n, it in enumerate(picks, 1)]
    x_thread = [t if _x_len(t) <= 280 else _cut(t, 120) for t in x_thread]
    wx = [f"【AI 羊毛速递 · {date}】今天新收录 {tn} 条，挑 {len(picks)} 条给大家：", ""]
    for n, it in enumerate(picks, 1):
        wx += [f"{n}. {it['title']}（{_flag(it)}）", f"   {_cut(it.get('summary') or '', 90)}", f"   详情：{url(it)}"]
    wx += ["", f"全部 {len(active)} 条（标了要不要绑卡、实名、国内能否直连）：{home}"]
    xhs_title = _cut(f"{date} AI 免费羊毛 {len(picks)} 条", 20)
    xhs = [xhs_title, "", "每天帮你筛一遍 AI 免费额度、会员试用和免费 GPU，能不能领、要不要绑卡都写清楚了👇", ""]
    for n, it in enumerate(picks, 1):
        xhs += [f"{n}️⃣ {_cut(it['title'], 40)}", f"{_cut(it.get('summary') or '', 60)}（{_flag(it)}）", ""]
    xhs += ["完整清单和领取方法：搜「AI大模型免费资源导航」或看主页链接", "", "#AI羊毛 #免费AI #大模型 #AI工具 #薅羊毛"]
    return {"date": now.strftime("%Y-%m-%d"), "generated_at": now.isoformat(timespec="seconds"), "today_new": tn, "total": len(active),
            "items": [{"title": it["title"], "url": url(it), "status": it.get("status"), "status_label": it.get("status_label")} for it in picks],
            "x_single": x_single, "x_single_len": _x_len(x_single), "x_thread": x_thread, "wechat": "\n".join(wx), "xiaohongshu": "\n".join(xhs),
            "note": "草稿文案，仅供人工发布前修改；本站不会自动发帖。"}


def write_digest(B, active, now) -> dict:
    d = digest_texts(B, active, now)
    txt = "\n".join([
        f"AI 羊毛今日速递 · {d['date']}（生成于 {now.strftime('%H:%M')} 北京时间）",
        f"今日新增 {d['today_new']} 条 · 有效共 {d['total']} 条 · 草稿，发布前请人工看一遍", "",
        f"===== X 单条（{d['x_single_len']}/280） =====", d["x_single"], "",
        "===== X 串推 =====", "\n\n".join(d["x_thread"]), "",
        "===== 微信群 / 朋友圈 =====", d["wechat"], "",
        "===== 小红书 =====", d["xiaohongshu"], ""])
    dd = B.SITE / "digest"
    dd.mkdir(exist_ok=True)
    (dd / "today.txt").write_text(txt, encoding="utf-8")
    (dd / f"{d['date']}.txt").write_text(txt, encoding="utf-8")
    olds = sorted(dd.glob("20*.txt"))[:-14]  # keep two weeks
    for f in olds:
        f.unlink()
    (B.SITE / "api").mkdir(exist_ok=True)
    (B.SITE / "api" / "digest.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def write_linkcheck_report(B, now) -> None:
    lc = B.LINKCHECK
    (B.SITE / "api" / "linkcheck.json").write_text(json.dumps({
        "checked_at": lc.get("checked_at"), "total": lc.get("total"), "counts": lc.get("counts"),
        "hidden": lc.get("hidden"), "unreliable_run": lc.get("unreliable_run"),
        "rules": "ok=能打开；recheck=上次没打开，下次再查；gone=连续两次 404/410/域名不存在，自动下架；unsure=对方限制访问或超时，不下架",
        "built_at": now.isoformat(timespec="seconds")}, ensure_ascii=False, indent=1), encoding="utf-8")
