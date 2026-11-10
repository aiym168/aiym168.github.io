#!/usr/bin/env python3
"""AI 羊毛电台 pages: radio/index.html (player + synced transcript), radio/feed.xml (podcast RSS),
api/radio.json, and the homepage card. Reads data/radio/episodes.json (written by engine/radio_make.py).
Called from build.py on every engine; can also run standalone (python3 radio_build.py)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EPS = ROOT / "data" / "radio" / "episodes.json"
OUT = ROOT / "radio"
REL = "radio/index.html"


def load() -> list[dict]:
    try:
        return [e for e in (json.loads(EPS.read_text(encoding="utf-8")).get("episodes") or []) if e.get("audio_url")]
    except Exception:
        return []


def mmss(s) -> str:
    s = int(round(float(s or 0)))
    return f"{s // 60}:{s % 60:02d}"


def local(e: dict) -> str:
    """Same-origin copy (added to the Pages artifact by pages-deploy.yml); release URL is the fallback."""
    return "audio/" + e["audio_url"].rsplit("/", 1)[-1]


def ep_text(e: dict) -> str:
    return "\n".join(s.get("text", "") for s in e.get("segments") or [])


def home_section(prefix: str = "./") -> str:
    eps = load()
    if not eps:
        return ""
    e = eps[0]
    from build import esc
    bars = "".join(f'<i style="--d:{(k * 37) % 9 / 10 + .35:.2f}s"></i>' for k in range(14))
    return f"""<section class="section rd-home" id="radio">
    <a class="rd-card" href="{prefix}radio/index.html#{esc(e['id'])}">
      <span class="rd-eq" aria-hidden="true">{bars}</span>
      <span class="rd-cb"><span class="rd-kick"><i class="live-dot"></i> AI 羊毛电台 · 每天早晚各一期</span>
        <b>{esc(e.get('title'))} · {mmss(e.get('duration_s'))}</b>
        <span>程序把今天的高价值羊毛、即将截止的活动、API 最低价变化读给你听，离线 AI 语音合成，附逐句文字稿和官方链接。</span></span>
      <span class="rd-go">▶ 收听</span>
    </a>
  </section>
<style>
.rd-card{{display:flex;align-items:center;gap:18px;padding:18px 22px;border-radius:18px;text-decoration:none;color:inherit;
  background:linear-gradient(120deg,rgba(92,225,255,.10),rgba(155,110,255,.12));border:1px solid rgba(92,225,255,.28);
  box-shadow:0 0 0 1px rgba(255,255,255,.02) inset,0 10px 40px rgba(0,0,0,.25);transition:transform .2s,border-color .2s}}
.rd-card:hover{{transform:translateY(-2px);border-color:rgba(92,225,255,.6)}}
.rd-eq{{display:flex;align-items:flex-end;gap:3px;height:46px;flex:0 0 auto}}
.rd-eq i{{display:block;width:5px;height:30%;border-radius:3px;background:linear-gradient(180deg,var(--cyan),var(--violet));animation:rdq var(--d) ease-in-out infinite alternate}}
@keyframes rdq{{from{{height:18%}}to{{height:100%}}}}
.rd-cb{{display:flex;flex-direction:column;gap:4px;flex:1;min-width:0}} .rd-cb b{{font-size:1.1rem}} .rd-cb>span:last-child{{color:var(--muted);font-size:.9rem}}
.rd-kick{{font-family:var(--mono);font-size:.78rem;color:var(--cyan);letter-spacing:.04em}}
.rd-go{{flex:0 0 auto;padding:10px 16px;border-radius:999px;background:var(--cyan);color:#041018;font-weight:700}}
@media (max-width:640px){{.rd-card{{flex-wrap:wrap}} .rd-eq{{height:34px}} .rd-go{{width:100%;text-align:center}}}}
@media (prefers-reduced-motion:reduce){{.rd-eq i{{animation:none;height:60%}}}}
html.reduce-motion .rd-eq i{{animation:none;height:60%}}
</style>"""


def build_page(b, now: datetime) -> str | None:
    esc = b.esc
    eps = load()
    OUT.mkdir(parents=True, exist_ok=True)
    canonical = f"{b.CANONICAL}{REL}"
    write_feed(b, eps, now)
    (ROOT / "api").mkdir(exist_ok=True)
    (ROOT / "api" / "radio.json").write_text(json.dumps({
        "updated_at": now.isoformat(timespec="seconds"), "feed": f"{b.CANONICAL}radio/feed.xml", "page": canonical,
        "episodes": [{k: e.get(k) for k in ("id", "date", "edition", "title", "duration_s", "audio_url", "created_at")} | {"transcript": ep_text(e)} for e in eps[:30]],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    data = [{"id": e["id"], "title": e.get("title"), "date": e.get("date"), "dur": e.get("duration_s"), "url": local(e), "alt": e["audio_url"],
             "segs": [{"k": s.get("kind"), "t": s.get("text"), "a": s.get("start", 0), "b": s.get("end", 0),
                       "l": [{"t": x.get("title"), "u": x.get("url"), "p": x.get("path")} for x in (s.get("links") or [])]}
                      for s in e.get("segments") or []]} for e in eps[:30]]
    latest = eps[0] if eps else None
    stats = (f'<div class="pill live">最新一期 <b>{esc(latest.get("title") if latest else "即将上线")}</b></div>'
             f'<div class="pill">时长 <b>{esc(mmss(latest.get("duration_s")) if latest else "—")}</b></div>'
             f'<div class="pill">已播 <b>{len(eps)}</b> 期</div>'
             f'<div class="pill">更新 <b>每天 08:30 / 20:30</b></div>')
    eq = "".join(f'<i style="--d:{(k * 53) % 11 / 10 + .3:.2f}s"></i>' for k in range(32))
    empty = '<p class="rd-empty">第一期正在生成中，稍后刷新即可收听。</p>' if not eps else ""
    ld = {"@context": "https://schema.org", "@type": "PodcastSeries", "name": "AI 羊毛电台", "url": canonical,
          "webFeed": f"{b.CANONICAL}radio/feed.xml", "inLanguage": "zh-CN",
          "description": "每天早晚两期，程序把 AI 大模型免费资源与全球优惠情报整理成三分钟音频。"}
    html = f"""{b.head_block(f"AI 羊毛电台 · 每天三分钟听完 AI 免费资源与优惠 | {b.SITE_NAME}", "AI 羊毛电台：每天早晚两期，程序根据本站已收录的大模型免费 API、AI 会员试用、云服务与金融优惠，自动生成三分钟中文音频，附逐句文字稿与官方链接，可用播客 App 订阅。", canonical, extra_ld=[ld])}
{b.page_shell_start("../", "module radio")}
{b.mod_hero("AI RADIO", "AI 羊毛电台", "不想翻网页？每天早晚各一期，程序把今天最值得看的羊毛读给你听。全部内容来自本站已收录条目，待核实的会明确说出来。", stats, '<a href="../">首页</a> › AI 羊毛电台', "../vendor/")}
<main class="wrap">
  <section class="section">
    <div class="rd-player" id="rd-player" aria-label="电台播放器">
      <div class="rd-screen">
        <div class="rd-big-eq" aria-hidden="true">{eq}</div>
        <div class="rd-now"><span class="rd-kick">NOW PLAYING · 正在播放</span><b id="rd-title">{esc(latest.get("title") if latest else "第一期即将上线")}</b>
          <span id="rd-line" class="rd-line">点播放开始收听，文字稿会跟着声音逐段高亮。</span></div>
      </div>
      <div class="rd-ctrl">
        <button type="button" id="rd-play" class="rd-play" aria-label="播放" {'' if latest else 'disabled'}><svg viewBox="0 0 24 24" aria-hidden="true"><path id="rd-ico" d="M8 5v14l11-7z"/></svg></button>
        <button type="button" class="rd-skip" data-skip="-15" aria-label="后退 15 秒">−15s</button>
        <div class="rd-bar" id="rd-bar" role="slider" tabindex="0" aria-label="播放进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i id="rd-fill"></i><span id="rd-marks"></span></div>
        <span class="rd-time" id="rd-time">0:00 / {esc(mmss(latest.get("duration_s")) if latest else "0:00")}</span>
        <button type="button" class="rd-skip" data-skip="15" aria-label="前进 15 秒">+15s</button>
        <button type="button" class="rd-rate" id="rd-rate" aria-label="播放速度">1.0×</button>
      </div>
      <audio id="rd-audio" preload="none"></audio>
    </div>
    {empty}
  </section>
  <section class="section">
    <div class="sec-head"><span class="sec-idx">01 / TRANSCRIPT</span><h2>本期文字稿</h2>
      <p class="sec-desc">点任意一段跳到那里播放。每段下面是站内详情和官方链接，领取前请以官方页面为准。</p></div>
    <ol class="rd-tr panel-box" id="rd-tr"></ol>
  </section>
  <section class="section">
    <div class="sec-head"><span class="sec-idx">02 / EPISODES</span><h2>往期节目</h2></div>
    <div class="rd-eps" id="rd-eps"></div>
  </section>
  <section class="section">
    <div class="sec-head"><span class="sec-idx">03 / SUBSCRIBE</span><h2>订阅</h2></div>
    <div class="panel-box rd-sub">
      <p>把这个地址加到任意支持 RSS 的播客 App（小宇宙以外的大多数播客客户端、Apple 播客「通过 URL 关注」、Pocket Casts、AntennaPod 等）：</p>
      <p><code id="rd-feed">{esc(b.CANONICAL)}radio/feed.xml</code> <button type="button" class="btn" id="rd-copy">复制订阅地址</button></p>
      <p class="rd-note">怎么做的：程序每天 08:30 和 20:30 读取本站数据（优惠情报、免费资源、API 价格榜），按固定规则写稿，不编造任何活动；再用开源模型 Kokoro 在服务器上离线合成语音。机器朗读偶有读错，以文字稿为准。数据接口：<a href="../api/radio.json">api/radio.json</a></p>
    </div>
  </section>
  {b.site_footer("../", "AI 羊毛电台")}
</main>
<script id="rd-data" type="application/json">{json.dumps(data, ensure_ascii=False).replace("</", "<\\/")}</script>
<script>
(function(){{
  var D=JSON.parse(document.getElementById('rd-data').textContent||'[]'); if(!D.length) return;
  var A=document.getElementById('rd-audio'), P=document.getElementById('rd-player'), tr=document.getElementById('rd-tr');
  var fill=document.getElementById('rd-fill'), bar=document.getElementById('rd-bar'), tm=document.getElementById('rd-time');
  var line=document.getElementById('rd-line'), ttl=document.getElementById('rd-title'), ico=document.getElementById('rd-ico');
  var cur=null, curSeg=-1, rates=[1,1.25,1.5,0.8], ri=0;
  function f(s){{s=Math.max(0,Math.round(s||0));return Math.floor(s/60)+':'+('0'+s%60).slice(-2);}}
  function esc(s){{return String(s==null?'':s).replace(/[&<>"]/g,function(c){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c];}});}}
  function load(ep, play){{
    cur=ep; curSeg=-1; A.dataset.alt=ep.alt||''; A.src=ep.url; ttl.textContent=ep.title; tm.textContent='0:00 / '+f(ep.dur);
    tr.innerHTML=ep.segs.map(function(s,i){{
      var ls=(s.l||[]).map(function(x){{return (x.p?'<a href="../'+esc(x.p)+'">站内详情</a>':'')+(x.u?' <a href="'+esc(x.u)+'" target="_blank" rel="noopener nofollow">官方 / 来源 ↗</a>':'');}}).join(' · ');
      return '<li data-i="'+i+'" class="rd-seg k-'+esc(s.k)+'"><span class="rd-ts">'+f(s.a)+'</span><p>'+esc(s.t)+'</p>'+(ls?'<div class="rd-links">'+ls+'</div>':'')+'</li>';}}).join('');
    document.getElementById('rd-marks').innerHTML=ep.segs.map(function(s){{return '<b style="left:'+(100*s.a/(ep.dur||1)).toFixed(2)+'%"></b>';}}).join('');
    document.querySelectorAll('.rd-ep').forEach(function(x){{x.classList.toggle('on',x.dataset.id===ep.id);}});
    if('mediaSession' in navigator){{try{{navigator.mediaSession.metadata=new MediaMetadata({{title:'AI 羊毛电台 · '+ep.title,artist:'AI大模型免费资源导航',album:'AI 羊毛电台'}});}}catch(e){{}}}}
    if(play) A.play().catch(function(){{}});
  }}
  document.getElementById('rd-eps').innerHTML=D.map(function(ep){{return '<button type="button" class="rd-ep" data-id="'+esc(ep.id)+'"><b>'+esc(ep.title)+'</b><span>'+esc(ep.date)+' · '+f(ep.dur)+'</span></button>';}}).join('');
  document.getElementById('rd-eps').addEventListener('click',function(e){{var b=e.target.closest('.rd-ep'); if(!b) return; var ep=D.find(function(x){{return x.id===b.dataset.id;}}); if(ep){{history.replaceState(null,'','#'+ep.id); load(ep,true); P.scrollIntoView({{behavior:'smooth',block:'center'}});}}}});
  var start=D.find(function(x){{return '#'+x.id===location.hash;}})||D[0]; load(start,false);
  document.getElementById('rd-play').addEventListener('click',function(){{A.paused?A.play().catch(function(){{}}):A.pause();}});
  A.addEventListener('error',function(){{ if(A.dataset.alt&&A.src.indexOf(A.dataset.alt)<0){{ var t=A.currentTime; A.src=A.dataset.alt; A.dataset.alt=''; A.play().catch(function(){{}}); }} }});
  A.addEventListener('play',function(){{P.classList.add('playing');ico.setAttribute('d','M7 5h4v14H7zM13 5h4v14h-4z');}});
  A.addEventListener('pause',function(){{P.classList.remove('playing');ico.setAttribute('d','M8 5v14l11-7z');}});
  A.addEventListener('ended',function(){{var i=D.indexOf(cur); if(i>=0&&i+1<D.length){{}}}});
  A.addEventListener('timeupdate',function(){{
    var d=A.duration||cur.dur||1, t=A.currentTime; fill.style.width=(100*t/d)+'%'; bar.setAttribute('aria-valuenow',Math.round(100*t/d)); tm.textContent=f(t)+' / '+f(d);
    var k=-1; for(var i=0;i<cur.segs.length;i++){{ if(t>=cur.segs[i].a-0.15) k=i; }}
    if(k!==curSeg){{ curSeg=k; tr.querySelectorAll('.rd-seg').forEach(function(li,i){{li.classList.toggle('on',i===k);}});
      if(k>=0){{ line.textContent=cur.segs[k].t; var li=tr.children[k]; var r=li.getBoundingClientRect(); if(!A.paused&&(r.top<80||r.bottom>innerHeight-20)) li.scrollIntoView({{behavior:'smooth',block:'center'}}); }} }}
  }});
  tr.addEventListener('click',function(e){{ if(e.target.closest('a')) return; var li=e.target.closest('.rd-seg'); if(!li) return; A.currentTime=cur.segs[+li.dataset.i].a; A.play().catch(function(){{}}); }});
  function seek(e){{ var r=bar.getBoundingClientRect(); var x=(e.touches?e.touches[0].clientX:e.clientX); A.currentTime=Math.max(0,Math.min(1,(x-r.left)/r.width))*(A.duration||cur.dur); }}
  bar.addEventListener('click',seek);
  bar.addEventListener('keydown',function(e){{ if(e.key==='ArrowRight') A.currentTime+=5; if(e.key==='ArrowLeft') A.currentTime-=5; }});
  document.querySelectorAll('.rd-skip').forEach(function(b){{b.addEventListener('click',function(){{A.currentTime=Math.max(0,A.currentTime+(+b.dataset.skip));}});}});
  document.getElementById('rd-rate').addEventListener('click',function(){{ri=(ri+1)%rates.length; A.playbackRate=rates[ri]; this.textContent=rates[ri].toFixed(rates[ri]%1?2:1).replace(/0$/,'')+'×';}});
  document.getElementById('rd-copy').addEventListener('click',function(){{var t=document.getElementById('rd-feed').textContent; (navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){{document.getElementById('rd-copy').textContent='已复制';}},function(){{prompt('复制订阅地址',t);}});}});
  document.addEventListener('keydown',function(e){{ if(e.code==='Space'&&!/INPUT|TEXTAREA|BUTTON/.test((e.target.tagName||''))){{e.preventDefault(); A.paused?A.play():A.pause();}} }});
}})();
</script>
<style>
.rd-player{{border-radius:22px;padding:22px;background:linear-gradient(160deg,rgba(10,22,40,.85),rgba(28,16,52,.85));border:1px solid rgba(92,225,255,.25);box-shadow:0 20px 60px rgba(0,0,0,.35),0 0 40px rgba(92,225,255,.08) inset}}
.rd-screen{{display:flex;gap:22px;align-items:center;min-height:120px}}
.rd-big-eq{{display:flex;align-items:flex-end;gap:4px;height:110px;flex:0 0 auto;padding:8px 10px;border-radius:14px;background:rgba(0,0,0,.25)}}
.rd-big-eq i{{display:block;width:6px;height:12%;border-radius:3px;background:linear-gradient(180deg,var(--cyan),var(--violet));transition:height .3s}}
.rd-player.playing .rd-big-eq i{{animation:rdq var(--d) ease-in-out infinite alternate}}
@keyframes rdq{{from{{height:12%}}to{{height:100%}}}}
.rd-now{{display:flex;flex-direction:column;gap:6px;min-width:0}} .rd-now b{{font-size:1.35rem}}
.rd-kick{{font-family:var(--mono);font-size:.78rem;color:var(--cyan);letter-spacing:.06em}}
.rd-line{{color:var(--muted);line-height:1.6;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
.rd-ctrl{{display:flex;align-items:center;gap:12px;margin-top:18px;flex-wrap:wrap}}
.rd-play{{width:58px;height:58px;border-radius:50%;border:0;background:var(--cyan);color:#041018;display:grid;place-items:center;cursor:pointer;box-shadow:0 0 24px rgba(92,225,255,.5)}}
.rd-play svg{{width:28px;height:28px;fill:currentColor}} .rd-play[disabled]{{opacity:.4;cursor:not-allowed}}
.rd-skip,.rd-rate{{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.14);color:inherit;border-radius:999px;padding:7px 12px;font-family:var(--mono);cursor:pointer}}
.rd-bar{{position:relative;flex:1;min-width:160px;height:10px;border-radius:6px;background:rgba(255,255,255,.1);cursor:pointer}}
.rd-bar i{{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:6px;background:linear-gradient(90deg,var(--cyan),var(--violet))}}
.rd-bar #rd-marks b{{position:absolute;top:-3px;width:2px;height:16px;background:rgba(255,255,255,.35)}}
.rd-time{{font-family:var(--mono);font-size:.85rem;color:var(--muted);min-width:96px;text-align:center}}
.rd-tr{{list-style:none;margin:0;padding:8px}} .rd-seg{{display:grid;grid-template-columns:52px 1fr;gap:4px 12px;padding:12px;border-radius:12px;cursor:pointer;transition:background .2s}}
.rd-seg:hover{{background:rgba(255,255,255,.04)}} .rd-seg.on{{background:rgba(92,225,255,.12);box-shadow:inset 3px 0 0 var(--cyan)}}
.rd-seg p{{margin:0;line-height:1.75}} .rd-ts{{font-family:var(--mono);color:var(--cyan);font-size:.82rem;padding-top:4px}}
.rd-links{{grid-column:2;font-size:.85rem}} .rd-seg.k-pending p::before{{content:"待核实";font-size:.72rem;padding:2px 6px;margin-right:6px;border-radius:6px;background:rgba(255,190,80,.18);color:#ffc164}}
.rd-eps{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}}
.rd-ep{{text-align:left;padding:12px 14px;border-radius:14px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.04);color:inherit;cursor:pointer;display:flex;flex-direction:column;gap:4px}}
.rd-ep span{{font-family:var(--mono);font-size:.8rem;color:var(--muted)}} .rd-ep.on{{border-color:var(--cyan);background:rgba(92,225,255,.1)}}
.rd-sub code{{word-break:break-all}} .rd-note{{color:var(--muted);font-size:.88rem}} .rd-empty{{color:var(--muted)}}
@media (max-width:640px){{.rd-screen{{flex-direction:column;align-items:flex-start}} .rd-big-eq{{height:70px;width:100%;justify-content:space-between}} .rd-bar{{order:9;flex-basis:100%}}}}
@media (prefers-reduced-motion:reduce){{.rd-player.playing .rd-big-eq i{{animation:none;height:55%}}}}
html.reduce-motion .rd-player.playing .rd-big-eq i{{animation:none;height:55%}}
</style>
{b.page_scripts()}
</body></html>"""
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"[radio] wrote {REL} episodes={len(eps)}")
    return REL


def write_feed(b, eps: list[dict], now: datetime) -> None:
    from xml.sax.saxutils import escape as x
    site = b.CANONICAL
    items = []
    for e in eps[:30]:
        try:
            pub = format_datetime(datetime.fromisoformat(e["created_at"]))
        except Exception:
            pub = format_datetime(now)
        notes = "\n".join(s.get("text", "") for s in e.get("segments") or [])
        links = "".join(f'<li><a href="{x(l.get("url") or "")}">{x(l.get("title") or "")}</a></li>' for s in e.get("segments") or [] for l in (s.get("links") or []) if l.get("url"))
        items.append(f"""  <item>
    <title>{x("AI 羊毛电台 · " + (e.get("title") or ""))}</title>
    <link>{site}radio/index.html#{x(e["id"])}</link>
    <guid isPermaLink="false">aiym168-radio-{x(e["id"])}</guid>
    <pubDate>{pub}</pubDate>
    <description><![CDATA[<p>{notes.replace("]]>", "")}</p><ul>{links}</ul><p>领取前请以官方页面为准。</p>]]></description>
    <enclosure url="{x(site + "radio/" + local(e))}" length="{int(e.get("bytes") or 0)}" type="audio/mpeg"/>
    <itunes:duration>{int(round(float(e.get("duration_s") or 0)))}</itunes:duration>
    <itunes:explicit>false</itunes:explicit>
  </item>""")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>AI 羊毛电台</title>
  <link>{site}radio/index.html</link>
  <atom:link href="{site}radio/feed.xml" rel="self" type="application/rss+xml"/>
  <language>zh-cn</language>
  <description>每天早晚两期，程序把 AI 大模型免费资源与全球优惠情报整理成三分钟中文音频。全部来自 {x(b.SITE_NAME)} 已收录条目，领取前请以官方页面为准。</description>
  <itunes:author>{x(b.SITE_NAME)}</itunes:author>
  <itunes:summary>AI 免费资源与优惠情报，每天三分钟听完。</itunes:summary>
  <itunes:image href="{site}assets/og-card.jpg"/>
  <itunes:category text="Technology"/>
  <itunes:explicit>false</itunes:explicit>
  <lastBuildDate>{format_datetime(now)}</lastBuildDate>
{chr(10).join(items)}
</channel>
</rss>
"""
    (OUT / "feed.xml").write_text(feed, encoding="utf-8")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    import build as B
    from datetime import datetime as _dt
    build_page(B, _dt.now(B.TZ))
