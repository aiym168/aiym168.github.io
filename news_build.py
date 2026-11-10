"""AI 新闻 / AI 花边 / 科技新闻 + AI 工具箱 页面生成（由 build.py 调用，不联网）。

读 data/news/db.json（news_collect.py 产出）和 data/ai_tools.json（人工维护），写：
  news/index.html · news/ai.html · news/gossip.html · news/tech.html · news/a/<id>.html（每条一页，NewsArticle）
  news/feed.xml（RSS）· api/news.json · aitools/index.html
不要手改生成的页面；改这里、fx.css（.nw- / .at- 开头的样式）或数据文件。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "news" / "db.json"
TOOLS = ROOT / "data" / "ai_tools.json"
OUT = ROOT / "news"
ART = OUT / "a"
WAN = "https://wan.is-my.app/"
CH = [  # key, 名称, 文件, 一句话
    ("ai", "AI 新闻", "ai.html", "大模型、AI 产品与 AI 公司的最新动态"),
    ("gossip", "AI 花边", "gossip.html", "AI 圈的人事变动、网友热议、离职跳槽与趣闻"),
    ("tech", "科技新闻", "tech.html", "手机、电脑、游戏、开发者与互联网的最新科技新闻"),
]
CHN = {k: n for k, n, _f, _d in CH}
CHF = {k: f for k, _n, f, _d in CH}
NOTE = "本站程序每小时从公开 RSS / 官方博客自动收集，英文内容为机器翻译摘要，已自动过滤低俗、时政等敏感内容；细节以原文为准。"


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _ago(iso: str, now: datetime) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except Exception:
        return ""
    m = int((now - d).total_seconds() // 60)
    if m < 1:
        return "刚刚"
    if m < 60:
        return f"{m} 分钟前"
    if m < 24 * 60:
        return f"{m // 60} 小时前"
    return f"{m // 1440} 天前"


def build_pages(b, now: datetime) -> list[str]:
    esc = b.esc
    db = _load(DB, {"items": []})
    items = [x for x in db.get("items") or [] if x.get("channel") in CHN]
    items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    OUT.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    by = {k: [x for x in items if x["channel"] == k] for k in CHN}
    upd = (db.get("updated_at") or now.isoformat())[:16].replace("T", " ")

    def row(x, prefix):
        return (f'<li class="nw-row"><a href="{prefix}a/{x["id"]}.html"><span class="nw-meta"><b class="nw-ch nw-{x["channel"]}">{esc(CHN[x["channel"]])}</b>'
                f'<span>{esc(x["source"])}</span><time datetime="{esc(x["published_at"])}">{esc(_ago(x["published_at"], now))}</time></span>'
                f'<span class="nw-t">{esc(x["title"])}</span>'
                + (f'<span class="nw-s">{esc(x["summary"][:110])}{"…" if len(x["summary"]) > 110 else ""}</span>' if x.get("summary") else "")
                + '</a></li>')

    def chnav(prefix, active):
        return ('<nav class="nw-tabs" aria-label="新闻频道">' + f'<a href="{prefix}index.html" class="{"on" if active == "all" else ""}">全部<i>{len(items)}</i></a>'
                + "".join(f'<a href="{prefix}{f}" class="{"on" if k == active else ""}">{esc(n)}<i>{len(by[k])}</i></a>' for k, n, f, _d in CH)
                + f'<a href="../aitools/index.html">AI 工具箱</a><a href="{prefix}feed.xml">RSS</a></nav>')

    def stats():
        return (f'<div class="pill"><span>新闻</span><b>{len(items)}</b><span>条</span></div>'
                + "".join(f'<a class="pill" href="{f}"><span>{esc(n)}</span><b>{len(by[k])}</b></a>' for k, n, f, _d in CH)
                + f'<div class="pill"><span>更新于</span><b>{esc(upd[5:])}</b></div>')

    def page(rel, title, desc, body, prefix, crumbs, ld):
        html = f"""{b.head_block(f"{title} | {b.SITE_NAME}", desc, b.CANONICAL + rel, extra_ld=ld)}
{b.page_shell_start(prefix, "module news")}
{b.mod_hero("AI 新闻", title, desc, stats(), crumbs, prefix + "vendor/")}
<div class="wrap">
{body}
<p class="note nw-note">{esc(NOTE)}</p>
{b.site_footer(prefix, "AI 新闻 · 科技新闻")}
</div>
{b.page_scripts()}
</body></html>"""
        (ROOT / rel).write_text(html, encoding="utf-8")
        paths.append(rel)

    def item_list_ld(rel, name, xs):
        return [{"@context": "https://schema.org", "@type": "ItemList", "name": name, "url": b.CANONICAL + rel,
                 "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": f"{b.CANONICAL}news/a/{x['id']}.html", "name": x["title"]}
                                     for i, x in enumerate(xs[:30])]}]

    # ---- index: three channel columns + mixed latest stream
    cols = "".join(f"""<section class="panel-box nw-col"><h2><a href="{f}">{esc(n)}</a> <small>{esc(d)}</small></h2>
      <ol class="nw-list">{"".join(row(x, "") for x in by[k][:8]) or '<li class="note">暂时没有新内容</li>'}</ol>
      <a class="go" href="{f}">全部 {len(by[k])} 条 {esc(n)} →</a></section>""" for k, n, f, d in CH)
    body = f"""{chnav("", "all")}<div class="nw-cols">{cols}</div>
<section class="panel-box"><h2>最新 60 条</h2><ol class="nw-list">{"".join(row(x, "") for x in items[:60])}</ol></section>"""
    page("news/index.html", "AI 新闻 · AI 花边 · 科技新闻（每小时更新）",
         "每小时自动更新的 AI 新闻、AI 圈花边趣闻和科技新闻中文摘要：大模型、AI 产品、手机电脑、游戏与开发者资讯，来源可查。",
         body, "", '<a href="../">首页</a> › 新闻中心', item_list_ld("news/index.html", "AI 新闻与科技新闻", items))
    for k, n, f, d in CH:
        xs = by[k]
        body = f"""{chnav("", k)}<section class="panel-box"><h2>{esc(n)} <small>{len(xs)} 条 · 最近 10 天</small></h2>
<ol class="nw-list">{"".join(row(x, "") for x in xs) or '<li class="note">暂时没有新内容，下个整点再来看看。</li>'}</ol></section>"""
        page(f"news/{f}", f"{n}（每小时更新）", f"{d}。中文摘要、来源可查、每小时自动更新。", body, "",
             f'<a href="../">首页</a> › <a href="index.html">新闻中心</a> › {esc(n)}', item_list_ld(f"news/{f}", n, xs))

    # ---- one page per item
    keep = set()
    for x in items:
        rel = f"news/a/{x['id']}.html"
        canonical = b.CANONICAL + rel
        desc = (x.get("summary") or x["title"])[:150]
        same = [y for y in by[x["channel"]] if y is not x][:8]
        other = [y for y in items if y["channel"] != x["channel"]][:5]
        pub = x["published_at"]
        ld = [{"@context": "https://schema.org", "@type": "NewsArticle", "headline": x["title"][:110], "description": desc,
               "datePublished": pub, "dateModified": x.get("fetched_at") or pub, "inLanguage": "zh-CN", "mainEntityOfPage": canonical,
               "isBasedOn": x["url"], "articleSection": CHN[x["channel"]],
               "author": {"@type": "Organization", "name": x["source"], "url": x.get("source_home") or x["url"]},
               "publisher": {"@type": "Organization", "name": b.SITE_NAME, "url": b.CANONICAL,
                             "logo": {"@type": "ImageObject", "url": b.CANONICAL + "assets/og-card.jpg"}},
               "image": [b.CANONICAL + "assets/og-card.jpg"]},
              {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                  {"@type": "ListItem", "position": 1, "name": "首页", "item": b.CANONICAL},
                  {"@type": "ListItem", "position": 2, "name": CHN[x["channel"]], "item": f"{b.CANONICAL}news/{CHF[x['channel']]}"},
                  {"@type": "ListItem", "position": 3, "name": x["title"][:60], "item": canonical}]}]
        orig = (f'<details class="nw-orig"><summary>英文原文标题与摘要</summary><p lang="en"><b>{esc(x["title_orig"])}</b></p>'
                f'<p lang="en">{esc(x.get("summary_orig") or "")}</p></details>') if x.get("title_orig") else ""
        html = f"""{b.head_block(f"{x['title']} | {CHN[x['channel']]} · {b.SITE_NAME}", desc, canonical, x["title"], pubdate=pub, extra_ld=ld)}
{b.page_shell_start("../../", "detail news")}
<div class="wrap" data-share-url="{esc(canonical)}">
  <div class="crumbs"><a href="../../">首页</a> › <a href="../index.html">新闻中心</a> › <a href="../{CHF[x['channel']]}" data-s-mod>{esc(CHN[x['channel']])}</a> › 正文</div>
  <article class="hero nw-art">
    <div class="eyebrow"><i class="live-dot"></i> {esc(CHN[x['channel']])} · {esc(x['source'])}</div>
    <h1 data-s-title>{esc(x['title'])}</h1>
    <p class="nw-when">发布于 <time datetime="{esc(pub)}">{esc(b.fmt_dt(pub))} 北京时间</time> · 本站收录 {esc(b.fmt_dt(x.get('fetched_at') or pub))}</p>
    <p class="lead" data-s-sum>{esc(x.get('summary') or '原文没有提供摘要，请点下方按钮阅读原文。')}</p>
    {orig}
    <p class="actions"><a class="btn primary" href="{esc(x['url'])}" target="_blank" rel="noopener noreferrer nofollow">阅读原文（{esc(x['source'])}）↗</a>
    {f'<a class="btn" href="{esc(x["hn"])}" target="_blank" rel="noopener noreferrer nofollow">Hacker News 讨论 ↗</a>' if x.get('hn') else ''}
    <a class="btn" href="../{CHF[x['channel']]}">更多{esc(CHN[x['channel']])}</a></p>
    {b.SHARE_ROW}
    <p class="note">{esc(NOTE)}</p>
  </article>
  <section class="panel-box"><h2>{esc(CHN[x['channel']])} · 最新</h2><ol class="nw-list">{"".join(row(y, "../") for y in same)}</ol></section>
  <section class="panel-box"><h2>其他频道</h2><ol class="nw-list">{"".join(row(y, "../") for y in other)}</ol>
    <p class="actions"><a class="btn" href="../../aitools/index.html">AI 工具箱：免费 AI 工具</a><a class="btn" href="{WAN}">工具站大全：免费在线工具 ↗</a></p></section>
  {b.site_footer("../../")}
</div>
{b.page_scripts()}
</body></html>"""
        (ROOT / rel).write_text(html, encoding="utf-8")
        paths.append(rel)
        keep.add(f"{x['id']}.html")
    for f in ART.glob("*.html"):
        if f.name not in keep:
            f.unlink()

    # ---- RSS + JSON
    from email.utils import format_datetime
    def rfc(iso):
        try:
            return format_datetime(datetime.fromisoformat(iso))
        except Exception:
            return format_datetime(now)
    rss = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>',
           f"<title>{esc(b.SITE_NAME)} · AI 新闻与科技新闻</title><link>{b.CANONICAL}news/index.html</link>",
           f'<atom:link href="{b.CANONICAL}news/feed.xml" rel="self" type="application/rss+xml"/>',
           "<description>每小时更新的 AI 新闻、AI 花边和科技新闻中文摘要</description><language>zh-CN</language>",
           f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"]
    for x in items[:60]:
        u = f"{b.CANONICAL}news/a/{x['id']}.html"
        rss.append(f"<item><title>{esc(x['title'])}</title><link>{u}</link><guid isPermaLink=\"true\">{u}</guid>"
                   f"<category>{esc(CHN[x['channel']])}</category><pubDate>{rfc(x['published_at'])}</pubDate>"
                   f"<description>{esc((x.get('summary') or '') + ' 来源：' + x['source'])}</description></item>")
    rss.append("</channel></rss>")
    (OUT / "feed.xml").write_text("\n".join(rss) + "\n", encoding="utf-8")
    paths.append("news/feed.xml")
    api = {"updated_at": db.get("updated_at"), "counts": {k: len(v) for k, v in by.items()},
           "channels": [{"key": k, "name": n, "page": b.CANONICAL + "news/" + f} for k, n, f, _d in CH],
           "items": [{"id": x["id"], "channel": x["channel"], "title": x["title"], "summary": x.get("summary") or "", "source": x["source"],
                      "url": x["url"], "page": f"{b.CANONICAL}news/a/{x['id']}.html", "published_at": x["published_at"]} for x in items[:120]]}
    (ROOT / "api").mkdir(exist_ok=True)
    (ROOT / "api" / "news.json").write_text(json.dumps(api, ensure_ascii=False, indent=1), encoding="utf-8")

    paths += build_tools(b)
    return paths


def build_tools(b) -> list[str]:
    esc = b.esc
    d = _load(TOOLS, {"cats": [], "tools": []})
    cats, tools = d.get("cats") or [], d.get("tools") or []
    if not tools:
        return []
    (ROOT / "aitools").mkdir(exist_ok=True)

    def card(t):
        host = re.sub(r"^https?://(www\.)?", "", t["url"]).split("/")[0]
        return (f'<a class="at-card" href="{esc(t["url"])}" target="_blank" rel="noopener noreferrer nofollow">'
                f'<span class="at-h"><b>{esc(t["name"])}</b><i class="at-free">{esc(t["free"])}</i></span>'
                f'<span class="at-d">{esc(t["desc"])}</span>'
                f'<span class="at-f"><span>{esc(host)}</span><span class="at-cn {"y" if t.get("cn") else ""}">{"国内可直接用" if t.get("cn") else "海外服务"}</span></span></a>')
    nav = '<nav class="nw-tabs" aria-label="AI 工具分类">' + "".join(
        f'<a href="#{k}">{esc(n)}<i>{sum(1 for t in tools if t["cat"] == k)}</i></a>' for k, n in cats) + "</nav>"
    secs = "".join(f'<section class="panel-box" id="{k}"><h2>{esc(n)}</h2><div class="at-grid">{"".join(card(t) for t in tools if t["cat"] == k)}</div></section>'
                   for k, n in cats)
    more = f"""<a class="wan-banner" href="{WAN}" aria-label="工具站大全：别处要付费的在线工具，这里全部免费">
      <span class="wb-grid" aria-hidden="true"></span>
      <span class="wb-mark" aria-hidden="true"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0 5.4 5.4l-8.4 8.4a2.1 2.1 0 0 1-3-3l8.4-8.4a4 4 0 0 0-2.4-2.4z"/><path d="M14.7 6.3 17 4l3 3-2.3 2.3"/></svg></span>
      <span class="wb-body"><span class="wb-kicker">还要更多？· 工具站大全</span>
        <b class="wb-title">图片、PDF、二维码、计算器……<em>别处要付费的，这里全部免费</em></b>
        <span class="wb-chips"><span>图片压缩</span><span>PDF 合并</span><span>证件照换底色</span><span>房贷个税</span><span>开发者工具箱</span></span></span>
      <span class="wb-cta">去工具站大全 <i aria-hidden="true">→</i></span></a>"""
    ld = [{"@context": "https://schema.org", "@type": "ItemList", "name": "免费 AI 工具箱", "url": b.CANONICAL + "aitools/index.html",
           "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": t["name"], "url": t["url"]} for i, t in enumerate(tools)]}]
    stats = (f'<div class="pill"><span>免费 AI 工具</span><b>{len(tools)}</b><span>个</span></div>'
             f'<div class="pill"><span>国内可直接用</span><b>{sum(1 for t in tools if t.get("cn"))}</b><span>个</span></div>'
             f'<a class="pill" href="{WAN}"><span>更多免费工具</span><b>工具站大全</b></a>')
    title = "免费 AI 工具箱：对话、搜索、绘画、视频、写歌、编程、PPT"
    desc = f"人工整理的 {len(tools)} 个有免费版或免费额度的 AI 工具：DeepSeek、Kimi、豆包、ChatGPT、即梦、可灵、Suno 等，标明免费到什么程度、国内能不能直接用。"
    html = f"""{b.head_block(f"{title} | {b.SITE_NAME}", desc, b.CANONICAL + "aitools/index.html", extra_ld=ld)}
{b.page_shell_start("../", "module aitools")}
{b.mod_hero("AI 工具箱", "免费 AI 工具箱", desc, stats, '<a href="../">首页</a> › AI 工具箱', "../vendor/")}
<div class="wrap">
{nav}
<div class="showcase at-more">{more}</div>
{secs}
<p class="note nw-note">免费政策随时会变，以官网为准。本页链接均直达官网，非推广链接。想看 AI 圈每天发生了什么？<a href="../news/index.html">AI 新闻</a>。</p>
{b.site_footer("../", "AI 工具箱")}
</div>
{b.page_scripts()}
</body></html>"""
    (ROOT / "aitools" / "index.html").write_text(html, encoding="utf-8")
    return ["aitools/index.html"]


def home_section(b, prefix: str = "./") -> str:
    """首页：新闻三栏 + AI 工具箱一行。"""
    esc = b.esc
    db = _load(DB, {"items": []})
    items = sorted([x for x in db.get("items") or [] if x.get("channel") in CHN], key=lambda x: x.get("published_at") or "", reverse=True)
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    cols = ""
    for k, n, f, d in CH:
        xs = [x for x in items if x["channel"] == k][:5]
        li = "".join(f'<li><a href="{prefix}news/a/{x["id"]}.html"><span class="nw-t">{esc(x["title"])}</span>'
                     f'<span class="nw-meta"><span>{esc(x["source"])}</span><time datetime="{esc(x["published_at"])}">{esc(_ago(x["published_at"], now))}</time></span></a></li>' for x in xs)
        cols += (f'<div class="nw-hcol"><h3><a href="{prefix}news/{f}"><b class="nw-ch nw-{k}">{esc(n)}</b></a><small>{esc(d)}</small></h3>'
                 f'<ol class="nw-hlist">{li or "<li class=note>暂时没有新内容</li>"}</ol><a class="go" href="{prefix}news/{f}">更多{esc(n)} →</a></div>')
    tl = _load(TOOLS, {"tools": []}).get("tools") or []
    pick = [t for t in tl if t["name"] in ("DeepSeek", "Kimi", "豆包", "秘塔 AI 搜索", "即梦 AI", "可灵 AI", "Suno", "沉浸式翻译")]
    chips = "".join(f'<a class="at-chip" href="{esc(t["url"])}" target="_blank" rel="noopener noreferrer nofollow"><b>{esc(t["name"])}</b><span>{esc(t["free"])}</span></a>' for t in pick)
    if not items and not tl:
        return ""
    return f"""<section class="section nw-home" id="news">
    <div class="sec-head"><span class="sec-idx">AI 新闻 · 每小时更新</span><h2>AI 新闻 · AI 花边 · 科技新闻</h2>
      <p class="sec-desc">从 20 多个公开来源自动收集并整理成中文摘要，每条都有来源和原文链接，已过滤低俗、时政等敏感内容。 <a href="{prefix}news/index.html">进入 AI 新闻 →</a></p></div>
    <div class="nw-hcols">{cols}</div>
  </section>
  <section class="section at-home" id="aitools">
    <div class="sec-head"><span class="sec-idx">AI 工具箱 · 免费</span><h2>不花钱也能用的 AI 工具</h2>
      <p class="sec-desc">对话、搜索、绘画、视频、写歌、编程、PPT，{len(tl)} 个有免费版的 AI 工具，标明免费到什么程度。 <a href="{prefix}aitools/index.html">打开 AI 工具箱 →</a> · 图片、PDF、计算器等更多免费工具见 <a href="{WAN}">工具站大全</a></p></div>
    <div class="at-chips">{chips}<a class="at-chip more" href="{prefix}aitools/index.html"><b>全部 {len(tl)} 个 →</b><span>AI 工具箱</span></a><a class="at-chip wan" href="{WAN}"><b>工具站大全 ↗</b><span>别处要付费的，这里免费</span></a></div>
  </section>"""
