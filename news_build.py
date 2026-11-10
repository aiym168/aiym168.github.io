"""AI 新闻 / AI 花边 / 科技新闻 + AI 工具箱 页面生成（由 build.py 调用，不联网）。

读 data/news/db.json（news_collect.py 产出）和 data/ai_tools.json（人工维护），写：
  news/index.html · news/<频道>.html（17 个频道 + tech.html 汇总）· news/a/<id>.html（每条一页，NewsArticle）
  news/tag/<标签>.html（长尾标签 + 自动热点）· news/feed.xml + news/feed/<频道>.xml · api/news.json · aitools/index.html
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
CH = [  # key, 名称, 文件, 一句话, 分组
    ("ai", "AI 新闻", "ai.html", "大模型、AI 产品与 AI 公司的最新动态", "aigc"),
    ("aivideo", "AI 视频生成", "aivideo.html", "Sora、可灵、即梦、Runway、Vidu、海螺、Veo 等 AI 视频模型的新版本与玩法", "aigc"),
    ("comfyui", "ComfyUI", "comfyui.html", "ComfyUI 新版本、新节点、热门工作流与模型（Civitai / Hugging Face / GitHub）", "aigc"),
    ("aidrama", "AI 漫剧", "aidrama.html", "AI 漫剧、AI 短剧、AI 动画与 AI 漫画的行业动态与作品", "aigc"),
    ("aigc", "AIGC 教程", "aigc.html", "AI 绘画、AI 视频、大模型应用的上手教程与实战指南", "aigc"),
    ("gossip", "AI 花边", "gossip.html", "AI 圈的人事变动、网友热议、离职跳槽与趣闻", "aigc"),
    ("huawei", "华为", "huawei.html", "鸿蒙 HarmonyOS、Mate / Pura / nova、麒麟、问界 / 鸿蒙智行、昇腾、华为云", "tech"),
    ("mobile", "手机数码", "mobile.html", "手机、平板、电脑、穿戴设备的新品与评测", "tech"),
    ("chip", "芯片半导体", "chip.html", "处理器、显卡、存储与半导体产业动态", "tech"),
    ("internet", "互联网", "internet.html", "互联网公司、平台与产品的最新动态", "tech"),
    ("software", "软件开源", "software.html", "软件更新、开源项目与 GitHub 热门", "tech"),
    ("dev", "开发者", "dev.html", "编程语言、框架、云服务与开发者工具", "tech"),
    ("game", "游戏科技", "game.html", "游戏硬件、引擎与游戏行业科技新闻", "tech"),
    ("auto", "汽车科技", "auto.html", "新能源车、智能驾驶与汽车科技", "tech"),
    ("space", "航天", "space.html", "火箭发射、卫星与深空探测", "tech"),
    ("science", "科学", "science.html", "前沿科学发现与科研进展", "tech"),
    ("launch", "产品发布", "launch.html", "每天新上线的科技产品与应用", "tech"),
]
CH = [c[:4] for c in CH]
GROUP = {"aigc": ["ai", "aivideo", "comfyui", "aidrama", "aigc", "gossip"],
         "tech": ["huawei", "mobile", "chip", "internet", "software", "dev", "game", "auto", "space", "science", "launch"]}
# 长尾标签：名称 → 正则（标题/摘要命中即打标签）
TAGS = {
    "华为": r"华为|Huawei", "鸿蒙": r"鸿蒙|HarmonyOS", "麒麟芯片": r"麒麟\s?\d|麒麟芯片|Kirin", "问界": r"问界|鸿蒙智行|AITO", "昇腾": r"昇腾|Ascend\s?\d", "华为云": r"华为云|Huawei Cloud",
    "Mate": r"\bMate\s?\d", "Pura": r"\bPura\s?\d", "小米": r"小米|Xiaomi|澎湃OS|HyperOS", "苹果": r"苹果|Apple\b|iPhone|iPad|Mac\b|macOS|iOS\s?\d", "iPhone": r"iPhone",
    "三星": r"三星|Samsung|Galaxy", "OPPO": r"OPPO", "vivo": r"\bvivo\b", "荣耀": r"荣耀|Honor\b", "一加": r"一加|OnePlus", "谷歌": r"谷歌|Google|Gemini|Pixel",
    "微软": r"微软|Microsoft|Windows|Copilot", "OpenAI": r"OpenAI|ChatGPT|GPT-?\d|\bo[1-9]\b|Sora", "ChatGPT": r"ChatGPT", "Claude": r"Claude|Anthropic", "Gemini": r"Gemini",
    "DeepSeek": r"DeepSeek|深度求索", "通义千问": r"通义|Qwen|千问", "Kimi": r"Kimi|月之暗面|Moonshot", "豆包": r"豆包|Doubao|字节跳动|ByteDance|火山引擎", "文心一言": r"文心|ERNIE|百度",
    "智谱": r"智谱|GLM-?\d|Zhipu", "MiniMax": r"MiniMax|海螺", "Llama": r"Llama\s?\d|\bLlama\b|Meta AI", "Grok": r"Grok\b|xAI", "Mistral": r"Mistral",
    "Sora": r"\bSora\b", "可灵": r"可灵|Kling", "即梦": r"即梦|Jimeng|Seedance", "Runway": r"Runway", "Vidu": r"Vidu", "海螺视频": r"海螺|Hailuo", "Veo": r"\bVeo\s?\d?\b", "Pika": r"\bPika\b",
    "万相": r"万相|\bWan\s?2", "ComfyUI": r"ComfyUI", "Stable Diffusion": r"Stable Diffusion|SDXL|\bSD\s?3", "Flux": r"\bFLUX\b|\bFlux\.?\d", "Midjourney": r"Midjourney", "LoRA": r"\bLoRA\b",
    "Civitai": r"Civitai", "Hugging Face": r"Hugging ?Face", "AI 绘画": r"AI ?绘画|AI ?画图|文生图|text-to-image|image generat", "AI 视频": r"AI ?视频|文生视频|图生视频|video generat",
    "AI 漫剧": r"漫剧|动态漫|AI ?短剧|AI ?漫画|AI ?动画", "AI 音乐": r"Suno|Udio|AI ?音乐|AI ?写歌", "AI 编程": r"Cursor|Copilot|AI ?编程|Claude Code|Codex|coding agent", "AI Agent": r"\bAgents?\b|智能体",
    "大模型": r"大模型|LLM|language model|基础模型", "开源模型": r"开源模型|open[- ]weight|open[- ]source model", "机器人": r"机器人|Robot|人形|humanoid|宇树|Unitree|Optimus",
    "英伟达": r"英伟达|NVIDIA|Nvidia|GeForce|RTX\s?\d", "AMD": r"\bAMD\b|Ryzen|Radeon", "英特尔": r"英特尔|Intel\b", "高通": r"高通|Qualcomm|Snapdragon|骁龙", "台积电": r"台积电|TSMC", "联发科": r"联发科|MediaTek|天玑",
    "显卡": r"显卡|GPU", "存储": r"内存|DRAM|HBM|SSD|闪存", "特斯拉": r"特斯拉|Tesla", "比亚迪": r"比亚迪|BYD", "小米汽车": r"小米汽车|小米 ?SU\d|YU\d", "理想汽车": r"理想汽车|理想 ?[LMi]\d", "蔚来": r"蔚来|NIO\b", "小鹏": r"小鹏|XPeng",
    "智能驾驶": r"智驾|自动驾驶|智能驾驶|Robotaxi|FSD|autonomous", "新能源": r"新能源|电动车|\bEV\b|电池|固态电池|充电",
    "SpaceX": r"SpaceX|星舰|Starship|Starlink|星链|Falcon", "火箭": r"火箭|rocket|发射", "NASA": r"NASA", "嫦娥": r"嫦娥|天问|神舟|天宫|空间站",
    "Steam": r"Steam", "任天堂": r"任天堂|Nintendo|Switch", "PlayStation": r"PlayStation|PS5|索尼|Sony", "Xbox": r"Xbox", "黑神话": r"黑神话",
    "GitHub": r"GitHub", "Linux": r"Linux|Ubuntu|Debian", "Rust": r"\bRust\b", "Python": r"Python", "JavaScript": r"JavaScript|TypeScript|Node\.?js|\bReact\b", "安卓": r"安卓|Android",
    "微信": r"微信|WeChat|腾讯|Tencent", "阿里巴巴": r"阿里|Alibaba|淘宝|支付宝", "抖音": r"抖音|TikTok", "京东": r"京东|JD\.com", "拼多多": r"拼多多|Temu", "美团": r"美团",
    "Product Hunt": r"Product Hunt", "亚马逊": r"亚马逊|Amazon|\bAWS\b", "Meta": r"\bMeta\b|Facebook|Instagram|WhatsApp", "GTA 6": r"GTA ?6|GTA ?VI", "量子计算": r"量子|quantum", "折叠屏": r"折叠屏|foldable", "AR/VR": r"Vision Pro|\bVR\b|\bAR\b|XR\b|头显|智能眼镜|smart glasses",
}
TAG_RE = {k: re.compile(v, re.I) for k, v in TAGS.items()}
HOT_STOP = set("""The A An And For With From New How Why What When This That Your Our You Its Are Was Will Can Now Just Into Over After Says More Than Not Has Have All One Two Day Week Year Show Ask Launch Tell Inc Ltd Update Beta Release Version Video Image Model Models App Apps AI Open Source Free Best Top First Live Pro Max Plus Mini Ultra Air Lite Edition HN PDF API CEO CTO GPU CPU USB OS UI""".split())
CHN = {k: n for k, n, _f, _d in CH}
CHF = {k: f for k, _n, f, _d in CH}
CHF["tech"] = "tech.html"
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


def _slug(t: str) -> str:
    return re.sub(r"[\s/\\?#%&:]+", "-", t).strip("-")


def tag_items(items, now: datetime):
    """curated tags + auto hot topics (terms seen across ≥3 sources in 72h)."""
    tagged: dict[str, list] = {}
    for x in items:
        txt = f'{x.get("title") or ""} {x.get("title_orig") or ""} {(x.get("summary") or "")[:160]}'
        tg = [k for k, r in TAG_RE.items() if r.search(txt)]
        x["_tags"] = tg[:8]
        for k in tg:
            tagged.setdefault(k, []).append(x)
    cut = (now - timedelta(hours=72)).isoformat()
    cnt: dict[str, set] = {}
    seen_items: dict[str, int] = {}
    for x in items:
        if (x.get("published_at") or "") < cut:
            continue
        t = f'{x.get("title_orig") or ""} {x.get("title") or ""}'
        terms = set(re.findall(r"\b[A-Z][A-Za-z0-9][A-Za-z0-9.\-]{1,18}(?: ?\d{1,3}[A-Za-z]?)?\b", t))
        terms |= set(m.strip() for m in re.findall(r"[「《“\"]([^」》”\"]{2,12})[」》”\"]", t))
        for w in terms:
            w = w.strip(" .-")
            if len(w) < 3 or w in HOT_STOP or w.split(" ")[0] in HOT_STOP or w.isdigit():
                continue
            if re.fullmatch(r"[A-Z][a-z]+", w):  # 普通英文单词（Black / Cloud / Watch）不当热点
                continue
            cnt.setdefault(w, set()).add(x.get("source_key") or x.get("source"))
            seen_items[w] = seen_items.get(w, 0) + 1
    hot_auto = sorted((w for w, s in cnt.items() if len(s) >= 3 and seen_items[w] >= 4), key=lambda w: -seen_items[w])[:30]
    hot = []
    for w in hot_auto:
        k = next((k for k, r in TAG_RE.items() if r.fullmatch(w) or r.search(w)), None)
        name = k or w
        if name not in hot:
            hot.append(name)
        if not k:
            rx = re.compile(re.escape(w), re.I)
            xs = [x for x in items if rx.search(f'{x.get("title") or ""} {x.get("title_orig") or ""}')]
            tagged[w] = xs
            for x in xs:
                if w not in x["_tags"]:
                    x["_tags"].append(w)
    # recent-volume hot: curated tags with most items in 72h
    rec = sorted(tagged, key=lambda k: -sum(1 for x in tagged[k] if (x.get("published_at") or "") >= cut))
    for k in rec[:12]:
        if k not in hot:
            hot.append(k)
    tagged = {k: v for k, v in tagged.items() if len(v) >= 3}
    hot = [k for k in hot if k in tagged][:24]
    return tagged, hot


def build_pages(b, now: datetime) -> list[str]:
    esc = b.esc
    db = _load(DB, {"items": []})
    items = [x for x in db.get("items") or [] if x.get("channel") in CHN]
    items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    OUT.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    TAGD = OUT / "tag"
    TAGD.mkdir(exist_ok=True)
    (OUT / "feed").mkdir(exist_ok=True)
    paths: list[str] = []
    by = {k: [x for x in items if x["channel"] == k] for k in CHN}
    by["tech"] = [x for x in items if x["channel"] in GROUP["tech"]]
    tagged, hot = tag_items(items, now)
    upd = (db.get("updated_at") or now.isoformat())[:16].replace("T", " ")
    nsrc = len({x.get("source_key") or x.get("source") for x in items})

    def row(x, prefix):
        return (f'<li class="nw-row"><a href="{prefix}a/{x["id"]}.html"><span class="nw-meta"><b class="nw-ch nw-{x["channel"]}">{esc(CHN[x["channel"]])}</b>'
                f'<span>{esc(x["source"])}</span><time datetime="{esc(x["published_at"])}">{esc(_ago(x["published_at"], now))}</time></span>'
                f'<span class="nw-t">{esc(x["title"])}</span>'
                + (f'<span class="nw-s">{esc(x["summary"][:90])}{"…" if len(x["summary"]) > 90 else ""}</span>' if x.get("summary") else "")
                + '</a></li>')

    def chnav(prefix, active):
        def a(k, n, f):
            return f'<a href="{prefix}{f}" class="{"on" if k == active else ""}">{esc(n)}<i>{len(by[k])}</i></a>'
        return ('<nav class="nw-tabs" aria-label="新闻频道">'
                + f'<a href="{prefix}index.html" class="{"on" if active == "all" else ""}">全部<i>{len(items)}</i></a>'
                + '<span class="nw-grp">AI · AIGC</span>' + "".join(a(k, n, f) for k, n, f, _d in CH if k in GROUP["aigc"])
                + '<span class="nw-grp">科技</span>' + a("tech", "科技全部", "tech.html") + "".join(a(k, n, f) for k, n, f, _d in CH if k in GROUP["tech"])
                + f'<a href="{prefix}tag/index.html" class="{"on" if active == "tag" else ""}">热点标签</a><a href="../aitools/index.html" class="nw-x">AI 工具箱</a></nav>')

    def hotrow(prefix):
        if not hot:
            return ""
        return ('<div class="nw-hot"><b>热点</b>' + "".join(f'<a href="{prefix}tag/{esc(_slug(k))}.html">{esc(k)}<i>{len(tagged[k])}</i></a>' for k in hot[:16])
                + f'<a class="more" href="{prefix}tag/index.html">全部标签 →</a></div>')

    def stats():
        return (f'<div class="pill"><span>新闻</span><b>{len(items)}</b><span>条</span></div>'
                f'<div class="pill"><span>来源</span><b>{nsrc}</b><span>个</span></div>'
                f'<div class="pill"><span>频道</span><b>{len(CH)}</b><span>个</span></div>'
                f'<div class="pill"><span>更新于</span><b>{esc(upd[5:])}</b></div>')

    def page(rel, title, desc, body, prefix, crumbs, ld, kicker="科技新闻"):
        html = f"""{b.head_block(f"{title} | {b.SITE_NAME}", desc, b.CANONICAL + rel, extra_ld=ld)}
{b.page_shell_start(prefix, "module news")}
{b.mod_hero(kicker, title, desc, stats(), crumbs, prefix + "vendor/")}
<div class="wrap">
{body}
<p class="note nw-note">{esc(NOTE)}</p>
{b.site_footer(prefix, "科技新闻 · AI 新闻")}
</div>
{b.page_scripts()}
</body></html>"""
        (ROOT / rel).write_text(html, encoding="utf-8")
        paths.append(rel)

    def item_list_ld(rel, name, xs):
        return [{"@context": "https://schema.org", "@type": "ItemList", "name": name, "url": b.CANONICAL + rel,
                 "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": f"{b.CANONICAL}news/a/{x['id']}.html", "name": x["title"]}
                                     for i, x in enumerate(xs[:30])]}]

    def col(k, n, f, d, prefix=""):
        return (f'<section class="panel-box nw-col"><h2><a href="{prefix}{f}">{esc(n)}</a> <small>{esc(d)}</small></h2>'
                f'<ol class="nw-list">{"".join(row(x, prefix) for x in by[k][:6]) or "<li class=note>暂时没有新内容</li>"}</ol>'
                f'<a class="go" href="{prefix}{f}">全部 {len(by[k])} 条 {esc(n)} →</a></section>')

    # ---- index
    aig = "".join(col(k, n, f, d) for k, n, f, d in CH if k in GROUP["aigc"])
    tec = "".join(col(k, n, f, d) for k, n, f, d in CH if k in GROUP["tech"])
    body = f"""{chnav("", "all")}{hotrow("")}
<section class="panel-box"><h2>最新 40 条</h2><ol class="nw-list">{"".join(row(x, "") for x in items[:40])}</ol></section>
<h2 class="nw-gh">AI · AIGC</h2><div class="nw-cols">{aig}</div>
<h2 class="nw-gh">科技</h2><div class="nw-cols">{tec}</div>"""
    page("news/index.html", "科技新闻 · AI 新闻 · AIGC（每小时更新）",
         f"每小时自动更新的科技新闻中文摘要：AI 大模型、AI 视频生成、ComfyUI、AI 漫剧、华为鸿蒙、手机数码、芯片、汽车科技、航天与开发者资讯，{nsrc} 个来源可查。",
         body, "../", '<a href="../">首页</a> › 新闻中心', item_list_ld("news/index.html", "科技新闻与 AI 新闻", items))
    for k, n, f, d in CH + [("tech", "科技新闻", "tech.html", "华为、手机数码、芯片、互联网、软件开源、开发者、游戏、汽车、航天、科学与产品发布")]:
        xs = by[k][:200]
        body = f"""{chnav("", k)}{hotrow("")}<section class="panel-box"><h2>{esc(n)} <small>{len(by[k])} 条 · 最近 10 天</small></h2>
<ol class="nw-list">{"".join(row(x, "") for x in xs) or '<li class="note">暂时没有新内容，下个整点再来看看。</li>'}</ol></section>"""
        page(f"news/{f}", f"{n}（每小时更新）", f"{d}。中文摘要、来源可查、每小时自动更新。", body, "../",
             f'<a href="../">首页</a> › <a href="index.html">新闻中心</a> › {esc(n)}', item_list_ld(f"news/{f}", n, xs),
             "AI · AIGC" if k in GROUP["aigc"] else "科技新闻")

    # ---- tag pages
    keept = {"index.html"}
    for k, xs in tagged.items():
        sl = _slug(k)
        rel = f"news/tag/{sl}.html"
        body = f"""{chnav("../", "tag")}{hotrow("../")}<section class="panel-box"><h2>{esc(k)} 相关新闻 <small>{len(xs)} 条</small></h2>
<ol class="nw-list">{"".join(row(x, "../") for x in xs[:150])}</ol></section>"""
        page(rel, f"{k} 最新消息（每小时更新）", f"{k} 最新消息、新品与动态：{'；'.join(x['title'] for x in xs[:3])[:120]}",
             body, "../../", f'<a href="../../">首页</a> › <a href="../index.html">新闻中心</a> › <a href="index.html">标签</a> › {esc(k)}',
             item_list_ld(rel, f"{k} 最新消息", xs), "热点标签")
        keept.add(f"{sl}.html")
    allt = sorted(tagged, key=lambda k: -len(tagged[k]))
    cloud = "".join(f'<a href="{esc(_slug(k))}.html">{esc(k)}<i>{len(tagged[k])}</i></a>' for k in allt)
    page("news/tag/index.html", "科技热点标签：华为、鸿蒙、可灵、ComfyUI、DeepSeek……", f"按话题浏览 {len(allt)} 个科技与 AI 热点标签，每小时自动更新。",
         f'{chnav("../", "tag")}{hotrow("../")}<section class="panel-box"><h2>全部标签 <small>{len(allt)} 个</small></h2><div class="nw-cloud">{cloud}</div></section>',
         "../../", '<a href="../../">首页</a> › <a href="../index.html">新闻中心</a> › 标签', [], "热点标签")
    for f in TAGD.glob("*.html"):
        if f.name not in keept:
            f.unlink()

    # ---- one page per item
    keep = set()
    for x in items:
        rel = f"news/a/{x['id']}.html"
        canonical = b.CANONICAL + rel
        desc = (x.get("summary") or x["title"])[:150]
        same = [y for y in by[x["channel"]] if y is not x][:8]
        other = [y for y in items if y["channel"] != x["channel"]][:5]
        pub = x["published_at"]
        tg = x.get("_tags") or []
        tchips = ("<p class=\"nw-tags\">" + "".join(f'<a href="../tag/{esc(_slug(t))}.html">#{esc(t)}</a>' for t in tg if t in tagged) + "</p>") if any(t in tagged for t in tg) else ""
        ld = [{"@context": "https://schema.org", "@type": "NewsArticle", "headline": x["title"][:110], "description": desc,
               "datePublished": pub, "dateModified": x.get("fetched_at") or pub, "inLanguage": "zh-CN", "mainEntityOfPage": canonical,
               "isBasedOn": x["url"], "articleSection": CHN[x["channel"]], "keywords": ", ".join([CHN[x["channel"]]] + tg),
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
        kw = "、".join(tg[:3])
        html = f"""{b.head_block(f"{x['title']} | {CHN[x['channel']]}{(' · ' + kw) if kw else ''} · {b.SITE_NAME}", desc, canonical, x["title"], pubdate=pub, extra_ld=ld)}
{b.page_shell_start("../../", "detail news")}
<div class="wrap" data-share-url="{esc(canonical)}">
  <div class="crumbs"><a href="../../">首页</a> › <a href="../index.html">新闻中心</a> › <a href="../{CHF[x['channel']]}" data-s-mod>{esc(CHN[x['channel']])}</a> › 正文</div>
  <article class="hero nw-art">
    <div class="eyebrow"><i class="live-dot"></i> {esc(CHN[x['channel']])} · {esc(x['source'])}</div>
    <h1 data-s-title>{esc(x['title'])}</h1>
    <p class="nw-when">发布于 <time datetime="{esc(pub)}">{esc(b.fmt_dt(pub))} 北京时间</time> · 本站收录 {esc(b.fmt_dt(x.get('fetched_at') or pub))}</p>
    <p class="lead" data-s-sum>{esc(x.get('summary') or '原文没有提供摘要，请点下方按钮阅读原文。')}</p>
    {tchips}
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

    # ---- RSS (all + per channel) + JSON
    from email.utils import format_datetime
    def rfc(iso):
        try:
            return format_datetime(datetime.fromisoformat(iso))
        except Exception:
            return format_datetime(now)

    def rss(rel, name, xs):
        out = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>',
               f"<title>{esc(b.SITE_NAME)} · {esc(name)}</title><link>{b.CANONICAL}news/index.html</link>",
               f'<atom:link href="{b.CANONICAL}{rel}" rel="self" type="application/rss+xml"/>',
               f"<description>每小时更新的{esc(name)}中文摘要</description><language>zh-CN</language>",
               f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"]
        for x in xs[:60]:
            u = f"{b.CANONICAL}news/a/{x['id']}.html"
            out.append(f"<item><title>{esc(x['title'])}</title><link>{u}</link><guid isPermaLink=\"true\">{u}</guid>"
                       f"<category>{esc(CHN[x['channel']])}</category><pubDate>{rfc(x['published_at'])}</pubDate>"
                       f"<description>{esc((x.get('summary') or '') + ' 来源：' + x['source'])}</description></item>")
        out.append("</channel></rss>")
        (ROOT / rel).write_text("\n".join(out) + "\n", encoding="utf-8")
        paths.append(rel)
    rss("news/feed.xml", "科技新闻与 AI 新闻", items)
    for k, n, f, _d in CH + [("tech", "科技新闻", "tech.html", "")]:
        rss(f"news/feed/{k}.xml", n, by[k])
    api = {"updated_at": db.get("updated_at"), "counts": {k: len(v) for k, v in by.items()}, "hot": hot,
           "channels": [{"key": k, "name": n, "page": b.CANONICAL + "news/" + f, "feed": f"{b.CANONICAL}news/feed/{k}.xml"} for k, n, f, _d in CH],
           "items": [{"id": x["id"], "channel": x["channel"], "title": x["title"], "summary": x.get("summary") or "", "source": x["source"], "tags": x.get("_tags") or [],
                      "url": x["url"], "page": f"{b.CANONICAL}news/a/{x['id']}.html", "published_at": x["published_at"]} for x in items[:200]]}
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
    HOME = [c for c in CH if c[0] in ("ai", "aivideo", "comfyui", "huawei", "mobile", "chip")]
    for k, n, f, d in HOME:
        xs = [x for x in items if x["channel"] == k][:5]
        li = "".join(f'<li><a href="{prefix}news/a/{x["id"]}.html"><span class="nw-t">{esc(x["title"])}</span>'
                     f'<span class="nw-meta"><span>{esc(x["source"])}</span><time datetime="{esc(x["published_at"])}">{esc(_ago(x["published_at"], now))}</time></span></a></li>' for x in xs)
        cols += (f'<div class="nw-hcol"><h3><a href="{prefix}news/{f}"><b class="nw-ch nw-{k}">{esc(n)}</b></a><small>{esc(d)}</small></h3>'
                 f'<ol class="nw-hlist">{li or "<li class=note>暂时没有新内容</li>"}</ol><a class="go" href="{prefix}news/{f}">更多{esc(n)} →</a></div>')
    nsrc = len({x.get("source_key") or x.get("source") for x in items})
    tl = _load(TOOLS, {"tools": []}).get("tools") or []
    pick = [t for t in tl if t["name"] in ("DeepSeek", "Kimi", "豆包", "秘塔 AI 搜索", "即梦 AI", "可灵 AI", "Suno", "沉浸式翻译")]
    chips = "".join(f'<a class="at-chip" href="{esc(t["url"])}" target="_blank" rel="noopener noreferrer nofollow"><b>{esc(t["name"])}</b><span>{esc(t["free"])}</span></a>' for t in pick)
    if not items and not tl:
        return ""
    return f"""<section class="section nw-home" id="news">
    <div class="sec-head"><span class="sec-idx">AI 新闻 · 每小时更新</span><h2>科技新闻 · AI 新闻 · AIGC</h2>
      <p class="sec-desc">从 {nsrc} 个公开来源自动收集 AI、AIGC、华为、手机、芯片、汽车、航天等 {len(CH)} 个频道的科技新闻，整理成中文摘要，每条都有来源和原文链接，已过滤低俗、时政等敏感内容。 <a href="{prefix}news/index.html">进入新闻中心 →</a> · <a href="{prefix}news/tag/index.html">热点标签</a></p></div>
    <div class="nw-hcols">{cols}</div>
  </section>
  <section class="section at-home" id="aitools">
    <div class="sec-head"><span class="sec-idx">AI 工具箱 · 免费</span><h2>不花钱也能用的 AI 工具</h2>
      <p class="sec-desc">对话、搜索、绘画、视频、写歌、编程、PPT，{len(tl)} 个有免费版的 AI 工具，标明免费到什么程度。 <a href="{prefix}aitools/index.html">打开 AI 工具箱 →</a> · 图片、PDF、计算器等更多免费工具见 <a href="{WAN}">工具站大全</a></p></div>
    <div class="at-chips">{chips}<a class="at-chip more" href="{prefix}aitools/index.html"><b>全部 {len(tl)} 个 →</b><span>AI 工具箱</span></a><a class="at-chip wan" href="{WAN}"><b>工具站大全 ↗</b><span>别处要付费的，这里免费</span></a></div>
  </section>"""
