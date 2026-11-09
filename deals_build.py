"""全球优惠情报中心页面生成（由 build.py 调用，只读 data/deals/db.json，不联网）。

页面：deals/index.html（总览）+ 9 个模块页 + deals/x/<id>.html 详情页 + api/deals.json。
不要手改生成的页面；改这里、fx.css（.dl- 开头的样式）或 vendor/deals.js。
"""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "deals"
DB = ROOT / "data" / "deals" / "db.json"
STATUS = ROOT / "data" / "deals" / "collect_status.json"

CAT_LABEL = {"ai": "AI 工具", "crypto": "Crypto", "card": "U卡 / 银行卡", "bank": "海外银行", "cloud": "VPS / 云服务",
             "software": "软件与数字服务", "other": "其他优惠"}
TYPE_LABEL = {"free": "真正免费", "trial": "免费试用", "deposit": "需要充值", "volume": "需要交易量", "invite": "需要邀请",
              "paid": "付费折扣", "lottery": "抽奖/随机"}
TYPE_HINT = {
    "free": "不用花钱、不用充值、不用交易就能拿到（可能仍需注册或身份认证）",
    "trial": "先免费用一段时间，到期可能自动扣费",
    "deposit": "需要存入、充值、持有或申购资产才能拿到",
    "volume": "需要完成一定交易量",
    "invite": "需要邀请他人或使用推荐码",
    "paid": "要花钱购买，只是比平时便宜",
    "lottery": "奖励随机，不保证拿到最高额",
}
VERIFY = {
    "verified": ("已核实", "ok", "本站已对照官方页面核实关键条款"),
    "official": ("官方公告", "info", "来自官方公告接口或官方博客，字段由程序自动提取"),
    "pending": ("待核实", "warn", "来自第三方信息源，尚未对照官方页面核实"),
    "changed": ("待核实", "warn", "官方页面内容已变化，需要重新核实"),
    "unreachable": ("待核实", "warn", "官方页面暂时无法访问"),
}
STATE = {"active": ("进行中", "ok"), "expiring": ("即将截止", "warn"), "upcoming": ("即将开始", "info"),
         "expired": ("已结束", "bad"), "archived": ("已归档", "muted")}

# (key, 字母, 标题, 一句话说明, 文件名)
MODULES = [
    ("today", "A", "今日最新优惠", "过去 24 小时首次收录的优惠", "today.html"),
    ("top", "B", "高价值优惠排行榜", "按估算价值、类型与核实程度综合排序", "top.html"),
    ("ai", "C", "AI 工具免费与折扣专区", "ChatGPT、Claude、Gemini、Suno 等 AI 工具的免费额度与折扣", "ai.html"),
    ("crypto", "D", "Crypto 空投与积分专区", "交易所活动、空投、积分与任务奖励（官方公告）", "crypto.html"),
    ("bank", "E", "海外银行与银行卡优惠", "开户奖励、推荐奖励、免手续费与 U卡 / 银行卡优惠", "bank.html"),
    ("cloud", "F", "VPS 及云服务专区", "免费服务器、云额度、开发者资源与 VPS 折扣", "cloud.html"),
    ("expiring", "G", "即将截止的活动", f"7 天内截止，按截止时间排序", "expiring.html"),
    ("archive", "H", "已结束活动档案", "已过期或长期未更新的活动，自动归档", "archive.html"),
    ("software", "I", "软件与其他全球优惠", "游戏限免、软件试用、教育福利与其他优惠", "software.html"),
]
MOD_INDEX = {m[0]: m for m in MODULES}
LIVE = ("active", "expiring", "upcoming")


def _d(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d
    except Exception:
        return None


def select(items: list[dict], key: str, now: datetime) -> list[dict]:
    live = [r for r in items if r.get("state") in LIVE]
    if key == "today":
        cut = now - timedelta(hours=24)
        return [r for r in live if (_d(r.get("first_seen")) or now) >= cut]
    if key == "top":
        ok = [r for r in live if r.get("verify_status") in ("verified", "official") and r.get("state") != "upcoming"
              and ((r.get("value") or {}).get("usd") or (r.get("value") or {}).get("kind") == "free_tier")]
        return ok[:30]
    if key == "ai":
        return [r for r in live if r["category"] == "ai"]
    if key == "crypto":
        return [r for r in live if r["category"] == "crypto"]
    if key == "bank":
        return [r for r in live if r["category"] in ("bank", "card")]
    if key == "cloud":
        return [r for r in live if r["category"] == "cloud"]
    if key == "software":
        return [r for r in live if r["category"] in ("software", "other")]
    if key == "expiring":
        xs = [r for r in live if r.get("state") == "expiring"]
        return sorted(xs, key=lambda r: r.get("end_at") or "")
    if key == "archive":
        xs = [r for r in items if r.get("state") in ("expired", "archived")]
        return sorted(xs, key=lambda r: r.get("end_at") or r.get("last_seen") or "", reverse=True)[:300]
    return []


def left_text(r: dict, now: datetime) -> str:
    end = _d(r.get("end_at"))
    st = _d(r.get("start_at"))
    if r.get("state") == "upcoming" and st:
        return f"{st.astimezone(now.tzinfo):%m-%d %H:%M} 开始"
    if not end:
        return "长期 / 未写截止"
    sec = (end - now).total_seconds()
    if sec < 0:
        return "已结束"
    if sec < 86400:
        return f"还剩 {max(1, int(sec // 3600))} 小时"
    return f"还剩 {int(sec // 86400)} 天"


def build_pages(b, now: datetime) -> list[str]:
    """b = build 模块（复用 head_block / topnav / footer 等）。返回写出的站内路径（供 sitemap）。"""
    esc = b.esc
    db = b.load_json(DB) if DB.exists() else None
    items = (db or {}).get("items") or []
    status = b.load_json(STATUS) if STATUS.exists() else {}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "x").mkdir(parents=True, exist_ok=True)
    tz = b.TZ
    now = now.astimezone(tz)
    upd = (db or {}).get("updated_at")
    sel = {m[0]: select(items, m[0], now) for m in MODULES}
    live = [r for r in items if r.get("state") in LIVE]
    n_ver = sum(1 for r in live if r.get("verify_status") == "verified")
    n_off = sum(1 for r in live if r.get("verify_status") == "official")
    n_pend = len(live) - n_ver - n_off

    def fmt(s, t=True):
        return b.fmt_dt(s, t) if s else "未注明"

    def tags_html(r):
        tg = r.get("type_tags") or []
        if not tg:
            return '<span class="dl-tag t-unk" title="程序没能判断参与类型">类型待核实</span>'
        return "".join(f'<span class="dl-tag t-{esc(t)}" title="{esc(TYPE_HINT.get(t, ""))}">{esc(TYPE_LABEL.get(t, t))}</span>' for t in tg)

    def badge(r):
        lab, cls, tip = VERIFY.get(r.get("verify_status"), VERIFY["pending"])
        return f'<span class="dl-ver v-{cls}" title="{esc(r.get("verify_note") or tip)}">{"✓ " if cls == "ok" else ""}{esc(lab)}</span>'

    def state_badge(r):
        lab, cls = STATE.get(r.get("state"), ("进行中", "ok"))
        return f'<span class="st st-{ {"ok": "ok", "warn": "warn", "bad": "bad", "muted": "muted", "info": "muted"}[cls]}">{esc(lab)}</span>'

    def link(u, text, cls=""):
        if not u:
            return f'<span class="dl-nolink">{esc(text)}：待核实</span>'
        return f'<a class="{cls}" href="{esc(u)}" target="_blank" rel="noopener noreferrer nofollow">{esc(text)} ↗</a>'

    def fields(r) -> list[tuple[str, str]]:
        v = r.get("value") or {}
        conds = r.get("conditions") or []
        steps = r.get("steps") or []
        risks = r.get("risks") or []
        period = f"{fmt(r.get('start_at'))} 至 {fmt(r.get('end_at'))}" if (r.get("start_at") or r.get("end_at")) else "未写明起止时间"
        if r.get("deadline_note"):
            period += f"<br><small>{esc(r['deadline_note'])}</small>"
        src = link(r.get("source_url"), r.get("source_name") or "来源")
        if r.get("also_seen"):
            src += "<br><small>同一活动也出现在：" + "、".join(link(u, urllib.parse.urlsplit(u).netloc) for u in r["also_seen"][:3]) + "</small>"
        ver = f"{fmt(r.get('verified_at'))}（{esc(VERIFY.get(r.get('verify_status'), VERIFY['pending'])[0])}）" if r.get("verified_at") else "尚未核实（待核实）"
        if r.get("verify_note"):
            ver += f"<br><small>{esc(r['verify_note'])}</small>"
        return [
            ("活动名称", esc(r.get("title"))),
            ("所属类别", esc(CAT_LABEL.get(r.get("category"), r.get("category"))) + " · " + tags_html(r)),
            ("优惠内容", esc(r.get("offer") or "见官方页面")),
            ("实际价值", esc(v.get("label") or "未注明（待核实）") + ('<br><small>金额按固定参考汇率估算，仅供排序参考</small>' if v.get("usd") and v.get("currency") not in ("USD", "USDT", "USDC") else "")),
            ("参与条件", ("<ul>" + "".join(f"<li>{esc(c)}</li>" for c in conds) + "</ul>") if conds else "原文未列出（待核实）"),
            ("适用国家或地区", esc(r.get("region") or "未注明（待核实）")),
            ("开始及截止时间", period),
            ("参与步骤", ("<ol>" + "".join(f"<li>{esc(s)}</li>" for s in steps) + "</ol>") if steps else "见官方页面"),
            ("官方活动链接", link(r.get("official_url"), "官方活动页")),
            ("信息来源", src),
            ("最后验证时间", ver),
            ("风险提示", ("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in risks) + "</ul>") if risks else "参与前请阅读官方条款"),
        ]

    def table(r):
        return '<table class="dl-table">' + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in fields(r)) + "</table>"

    def card(r, prefix, rank=None):
        v = r.get("value") or {}
        path = f"{prefix}x/{r['id']}.html"
        text = " ".join(str(x) for x in [r.get("title"), r.get("offer"), r.get("region"), r.get("source_name"), CAT_LABEL.get(r.get("category"))]
                        + [TYPE_LABEL.get(t, "") for t in r.get("type_tags") or []] + [r.get("lang_note") or ""])
        rk = f'<span class="dl-rank">#{rank}</span>' if rank else ""
        tags = " ".join(r.get("type_tags") or ["unk"])
        return f"""<article class="card dl-card" data-tags="{esc(tags)}" data-ver="{esc(r.get('verify_status'))}" data-cat="{esc(r.get('category'))}" data-end="{esc(r.get('end_at') or '')}" data-score="{r.get('score', 0)}" data-text="{esc(text)}">
  <div class="card-top">{rk}<span class="dl-cat c-{esc(r.get('category'))}">{esc(CAT_LABEL.get(r.get('category'), ''))}</span>{badge(r)}{state_badge(r)}</div>
  <h3 class="title"><a href="{esc(path)}">{esc(r.get('title'))}</a></h3>
  <p class="summary">{esc(r.get('offer') or '')}</p>
  <div class="dl-kv"><span><i>实际价值</i><b>{esc(v.get('label') or '未注明（待核实）')}</b></span><span><i>地区</i><b>{esc(r.get('region') or '未注明')}</b></span><span><i>截止</i><b class="{'dl-hot' if r.get('state') == 'expiring' else ''}">{esc(left_text(r, now))}{(' · ' + esc(fmt(r.get('end_at'), False))) if r.get('end_at') else ''}</b></span></div>
  <div class="dl-tags">{tags_html(r)}</div>
  <details class="dl-more"><summary>完整信息（12 项）</summary>{table(r)}</details>
  <div class="linkrow">{link(r.get('official_url'), '官方活动页', 'dl-go')}{link(r.get('source_url'), '信息来源') if r.get('source_url') != r.get('official_url') else ''}<a href="{esc(path)}">详情</a><a class="report" href="{esc(b.ISSUE_URL + '?' + urllib.parse.urlencode({'title': '[优惠报错] ' + (r.get('title') or '')[:60], 'body': '条目：' + (r.get('title') or '') + chr(10) + '页面：' + b.CANONICAL + 'deals/x/' + r['id'] + '.html' + chr(10) + '问题：已结束 / 信息有误 / 链接失效 / 其他' + chr(10), 'labels': '报错'}))}" target="_blank" rel="noopener">报错</a><span class="mod-tag">核实 {esc(fmt(r.get('verified_at'), True) if r.get('verified_at') else '待核实')}</span></div>
</article>"""

    def filters(rs):
        cnt_t = {}
        for r in rs:
            for t in r.get("type_tags") or ["unk"]:
                cnt_t[t] = cnt_t.get(t, 0) + 1
        cnt_v = {}
        for r in rs:
            k = r.get("verify_status") if r.get("verify_status") in ("verified", "official") else "pending"
            cnt_v[k] = cnt_v.get(k, 0) + 1
        tchips = "".join(f'<button type="button" class="chip" data-dl-f="tags" data-v="{k}" aria-pressed="false">{esc(TYPE_LABEL.get(k, "类型待核实"))} <i>{cnt_t[k]}</i></button>'
                         for k in list(TYPE_LABEL) + ["unk"] if cnt_t.get(k))
        vchips = "".join(f'<button type="button" class="chip" data-dl-f="ver" data-v="{k}" aria-pressed="false">{esc(VERIFY[k][0])} <i>{cnt_v[k]}</i></button>'
                         for k in ("verified", "official", "pending") if cnt_v.get(k))
        return f"""<div class="filters compact dl-filters" data-dl-root>
  <form class="searchbar" role="search" onsubmit="return false"><label class="sr-only" for="dlq">搜索</label>
    <input id="dlq" type="search" placeholder="搜索：Gemini、币安、香港银行、VPS、免绑卡…" autocomplete="off" /></form>
  <div class="fgroups"><div class="fgroup"><span class="flabel">参与类型</span><div class="chips">{tchips}</div></div>
  <div class="fgroup"><span class="flabel">核实程度</span><div class="chips">{vchips}</div></div></div>
  <div class="fbar"><span class="f-count" data-dl-count>共 {len(rs)} 条</span>
    <label class="sort">排序 <select data-dl-sort><option value="score">价值优先</option><option value="end">按截止时间</option></select></label>
    <button type="button" class="btn sm hidden" data-dl-clear>清除筛选</button></div>
</div>"""

    def mod_nav(prefix, active=None):
        return '<nav class="dl-modnav" aria-label="优惠情报模块">' + "".join(
            f'<a href="{prefix}{fn}" class="{"on" if k == active else ""}"><b>{L}</b>{esc(t)}<i>{len(sel[k])}</i></a>'
            for k, L, t, _d, fn in MODULES) + "</nav>"

    def page(rel, title, desc, body, prefix, crumbs, stats, ld=None):
        canonical = b.CANONICAL + rel
        html = f"""{b.head_block(f"{title} | 全球优惠情报中心 · {b.SITE_NAME}", desc, canonical, extra_ld=ld or [])}
{b.page_shell_start(prefix, "module deals")}
{b.mod_hero("全球优惠情报", title, desc, stats, crumbs, prefix + "vendor/")}
<div class="wrap">
{body}
{b.site_footer(prefix, "全球优惠情报中心")}
</div>
{b.page_scripts()}
<script src="{b.vurl(prefix, 'deals.js')}" defer></script>
</body></html>"""
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
        return rel

    def pills(extra=""):
        return (f'<div class="pill">进行中 <b>{len(live)}</b> 条</div><div class="pill">已核实 <b>{n_ver}</b></div>'
                f'<div class="pill">官方公告 <b>{n_off}</b></div><div class="pill">待核实 <b>{n_pend}</b></div>'
                f'<div class="pill">最后采集 <b>{esc(b.fmt_dt(upd)[5:] if upd else "未知")}</b></div>{extra}')

    paths = []
    legend = "".join(f'<li><span class="dl-tag t-{k}">{esc(v)}</span>{esc(TYPE_HINT[k])}</li>' for k, v in TYPE_LABEL.items())
    vlegend = "".join(f'<li><span class="dl-ver v-{c}">{esc(l)}</span>{esc(t)}</li>' for k, (l, c, t) in VERIFY.items() if k in ("verified", "official", "pending"))

    # ---------- 模块页
    for k, L, t, d, fn in MODULES:
        rs = sel[k]
        prefix = "../"
        if k == "top":
            cards = "\n".join(card(r, "", i + 1) for i, r in enumerate(rs))
        else:
            cards = "\n".join(card(r, "") for r in rs)
        note = ""
        if k == "today" and rs and all((_d(r.get("first_seen")) or now) >= now - timedelta(hours=24) for r in live):
            note = '<p class="note dl-note">情报中心刚上线：所有条目都是今天首次收录，所以今天的「今日最新」和总数相同。</p>'
        if k == "top":
            note = '<p class="note dl-note">排序依据：单人可得的估算价值（奖池总额不算个人价值）、是否真正免费、是否已核实、是否临近截止。只收「已核实」和「官方公告」条目，待核实的不进榜。</p>'
        if k == "crypto":
            note = '<p class="note dl-note">目前自动接入币安、KuCoin 官方公告。项目方自己发的空投、测试网和积分计划很难自动核实，暂未收录；交易所在中国大陆不提供服务，参与前请确认当地法规。</p>'
        if k == "bank":
            u = sum(1 for r in rs if r["category"] == "card")
            note = (f'<p class="note dl-note">本区 {len(rs)} 条，其中银行卡 / U卡相关 {u} 条。海外银行与 U卡官网多数禁止程序访问，第三方信息一律标「待核实」，'
                    '请点「官方活动页」或自行到银行官网核对后再参与。</p>')
        if k == "archive":
            note = '<p class="note dl-note">过了截止时间的活动会自动移到这里；没写截止时间、但超过 30 天或 21 天没在来源出现的，也会归档（不代表活动一定结束）。</p>'
        if k == "expiring":
            note = '<p class="note dl-note">只列出写明截止时间、且 7 天内截止的活动。</p>'
        empty = f'<div class="empty">本模块目前 0 条。我们不会为了凑数编造优惠——有新的核实条目时会自动出现。</div>'
        body = f"""{mod_nav("", k)}
  <section class="section" id="list">
    <div class="sec-head"><span class="sec-idx">{L} · {esc(t)}</span><h2>{esc(t)}（{len(rs)} 条）</h2><p class="sec-desc">{esc(d)}</p></div>
    {note}
    {filters(rs) if rs else ''}
    <div class="grid dl-grid" data-dl-list>{cards or empty}</div>
    <div class="empty hidden" data-dl-empty>没有符合条件的条目，试试清除筛选</div>
  </section>"""
        ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": t, "url": b.CANONICAL + "deals/" + fn, "description": d}]
        paths.append(page("deals/" + fn, t, d + "。每条标注实际价值、参与条件、地区、截止时间与核实状态。", body, prefix,
                          f'<a href="../">首页</a> › <a href="index.html">优惠情报</a> › {esc(t)}', pills(), ld))

    # ---------- 详情页
    for r in items:
        prefix = "../../"
        rel = f"deals/x/{r['id']}.html"
        body = f"""{mod_nav("../", None)}
  <section class="section"><div class="panel-box dl-detail">
    <div class="card-top"><span class="dl-cat c-{esc(r.get('category'))}">{esc(CAT_LABEL.get(r.get('category'), ''))}</span>{badge(r)}{state_badge(r)}</div>
    <h2>{esc(r.get('title'))}</h2>
    {(f'<p class="note">原文标题：{esc(r["lang_note"])}</p>' if r.get('lang_note') and r.get('lang_note') != r.get('title') else '')}
    {table(r)}
    <p class="note">{esc(r.get('archived_reason') or '')}</p>
    <p class="note">本站只做信息整理，不代领、不收费、不索要账号密码或验证码。参与前请以官方页面最新规则为准。</p>
  </div></section>"""
        lead = (r.get("offer") or r.get("title") or "")[:120]
        paths.append(page(rel, r.get("title") or "优惠详情", lead, body, prefix,
                          f'<a href="../../">首页</a> › <a href="../index.html">优惠情报</a> › 详情',
                          f'<div class="pill">状态 <b>{esc(STATE.get(r.get("state"), ("进行中",))[0])}</b></div><div class="pill">核实 <b>{esc(VERIFY.get(r.get("verify_status"), VERIFY["pending"])[0])}</b></div>'))

    # ---------- 总览页
    tiles = "".join(f"""<a class="dl-tile" href="{fn}"><span class="dl-L">{L}</span><span class="dl-tb"><b>{esc(t)}</b><span>{esc(d)}</span></span><span class="dl-n"><b>{len(sel[k])}</b>条</span></a>"""
                    for k, L, t, d, fn in MODULES)
    top6 = "\n".join(card(r, "", i + 1) for i, r in enumerate(sel["top"][:6]))
    exp6 = "\n".join(card(r, "") for r in sel["expiring"][:6])
    src_rows = [
        ("编辑核实条目（官方页面回访）", status.get("curated_ok"), status.get("curated"), "每 6 小时回访官方页面，关键条款还在才算「已核实」"),
        ("Epic 商店限免（官方接口）", status.get("epic_n"), None, "自动读取起止时间与原价"),
        ("币安活动 / 空投公告（官方接口）", status.get("binance_n"), None, "自动读取正文，提取活动期间、条件和地区"),
        ("KuCoin 活动公告（官方）", status.get("kucoin_n"), None, "自动读取公告页提取活动期间"),
        ("Doctor of Credit 银行/信用卡奖励（第三方 RSS）", status.get("doc_kept"), status.get("doc"), "一律标「待核实」"),
        ("LowEndBox VPS 优惠（第三方 RSS）", status.get("leb_kept"), status.get("leb"), "一律标「待核实」，只收带价格的促销"),
        ("GitHub Changelog / OpenAI 新闻（官方 RSS）", (status.get("ghcl_kept") or 0) + (status.get("openai_kept") or 0), None, "只收标题就是免费/折扣的文章"),
    ]
    src_html = "".join(f"<tr><th>{esc(a)}</th><td>{'' if n is None else n}{(' / ' + str(tot)) if tot is not None else ''}</td><td>{esc(c)}</td></tr>" for a, n, tot, c in src_rows)
    body = f"""
  <section class="section" id="modules">
    <div class="sec-head"><span class="sec-idx">模块</span><h2>八大情报模块</h2>
      <p class="sec-desc">程序每小时自动采集、去重、提取截止时间与条件、估算价值、过期归档。不确定的写「待核实」，不替你猜。</p></div>
    <div class="dl-tiles">{tiles}</div>
  </section>
  <section class="section" id="top"><div class="sec-head"><span class="sec-idx">B · 排行</span><h2>高价值优惠 TOP 6</h2><p class="sec-desc"><a href="top.html">查看完整排行榜 →</a></p></div>
    <div class="grid dl-grid">{top6 or '<div class="empty">暂无</div>'}</div></section>
  <section class="section" id="soon"><div class="sec-head"><span class="sec-idx">G · 截止</span><h2>7 天内截止</h2><p class="sec-desc"><a href="expiring.html">查看全部 {len(sel['expiring'])} 条 →</a></p></div>
    <div class="grid dl-grid">{exp6 or '<div class="empty">7 天内没有截止的活动</div>'}</div></section>
  <section class="section" id="legend"><div class="sec-head"><span class="sec-idx">说明</span><h2>标签怎么看</h2></div>
    <div class="panel-box dl-legend"><h3>参与类型</h3><ul>{legend}</ul><h3>核实程度</h3><ul>{vlegend}</ul>
    <p class="note">「实际价值」只算单人可拿到的部分；交易所的「奖池总额」是所有人一起分的，不代表个人所得。外币按固定参考汇率估算，仅用于排序。</p></div></section>
  <section class="section" id="sources"><div class="sec-head"><span class="sec-idx">来源</span><h2>本轮采集情况</h2>
    <p class="sec-desc">最后采集：{esc(b.fmt_dt(upd) if upd else '未知')} 北京时间 · 自动合并重复条目 {esc((db or {}).get('dedupe_merged', 0))} 条</p></div>
    <div class="panel-box"><table class="dl-table dl-src"><tr><th>来源</th><td><b>本轮条数</b></td><td><b>处理方式</b></td></tr>{src_html}</table>
    <p class="note">目前还做不到的：项目方空投 / 测试网（无统一官方源）、需要登录的交易所任务中心、多数海外银行与 U卡官网（禁止程序访问）、Telegram 群消息与手机推送。这些需要额外的接口或授权，接入前不会假装已经覆盖。</p>
    <p class="note">程序读取数据：<a href="../api/deals.json">api/deals.json</a>（无需密钥）。</p></div></section>"""
    paths.insert(0, page("deals/index.html", "全球优惠情报中心", "AI 订阅、Crypto 活动、海外银行与 U卡、VPS 云服务、软件限免的全球优惠，每小时自动采集、去重、核实与归档。", body, "../",
                         '<a href="../">首页</a> › 优惠情报', pills()))

    # ---------- API
    api = {"updated_at": upd, "counts": {m[0]: len(sel[m[0]]) for m in MODULES}, "live": len(live), "verified": n_ver, "official": n_off, "pending": n_pend,
           "fields": {"title": "活动名称", "category": "所属类别", "offer": "优惠内容", "value": "实际价值", "conditions": "参与条件", "region": "适用国家或地区",
                      "start_at/end_at": "开始及截止时间", "steps": "参与步骤", "official_url": "官方活动链接", "source_url": "信息来源", "verified_at": "最后验证时间", "risks": "风险提示",
                      "type_tags": "free 真正免费 / trial 免费试用 / deposit 需要充值 / volume 需要交易量 / invite 需要邀请 / paid 付费折扣 / lottery 抽奖",
                      "verify_status": "verified 已核实 / official 官方公告 / pending|changed|unreachable 待核实"},
           "items": [{k: v for k, v in r.items() if not k.startswith("_") and k not in ("fp",)} for r in items]}
    (ROOT / "api").mkdir(exist_ok=True)
    (ROOT / "api" / "deals.json").write_text(json.dumps(api, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # 清理已删除条目的旧详情页
    keep = {f"{r['id']}.html" for r in items}
    for p in (OUT / "x").glob("*.html"):
        if p.name not in keep:
            p.unlink()
    print(f"[deals] pages={len(paths)} live={len(live)} verified={n_ver} official={n_off} pending={n_pend} modules={ {m[0]: len(sel[m[0]]) for m in MODULES} }")
    return paths


def home_section(prefix: str = "./") -> str:
    """首页上的情报中心入口（读 api/deals.json 的计数）。"""
    p = ROOT / "api" / "deals.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    c = d.get("counts") or {}
    tiles = "".join(f'<a class="dl-tile sm" href="{prefix}deals/{fn}"><span class="dl-L">{L}</span><span class="dl-tb"><b>{t}</b></span><span class="dl-n"><b>{c.get(k, 0)}</b>条</span></a>'
                    for k, L, t, _d, fn in MODULES[:8])
    return f"""<section class="section dl-home" id="deals">
    <div class="sec-head"><span class="sec-idx">NEW · 全球优惠情报中心</span><h2>AI 订阅 · Crypto · 海外银行与 U卡 · 云服务优惠</h2>
      <p class="sec-desc">每小时自动采集、去重、提取截止时间和参与条件、估算价值、过期归档。进行中 {d.get('live', 0)} 条，其中已核实 {d.get('verified', 0)} 条、官方公告 {d.get('official', 0)} 条、待核实 {d.get('pending', 0)} 条。 <a href="{prefix}deals/index.html">进入情报中心 →</a></p></div>
    <div class="dl-tiles">{tiles}</div>
  </section>"""
