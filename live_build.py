#!/usr/bin/env python3
"""AI 羊毛信号站 entry page: live/index.html (fixed address that forwards to the station's current public URL)
and api/live.json. Reads data/live.json (written by the station when its public address changes).
Called from build.py on every build; can also run standalone (python3 live_build.py)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "data" / "live.json"
OUT = ROOT / "live"
REL = "live/index.html"


def load() -> dict:
    try:
        d = json.loads(SRC.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def urls(d: dict) -> list[str]:
    out = []
    for u in [d.get("primary")] + list(d.get("mirrors") or []):
        if isinstance(u, str) and u.startswith("https://") and u not in out:
            out.append(u.rstrip("/"))
    return out


def home_link(prefix: str = "./") -> str:
    return f'<a href="{prefix}live/">AI 羊毛信号站（直播）</a>'


def build_page(b, now: datetime) -> str | None:
    esc = b.esc
    d = load()
    U = urls(d)
    OUT.mkdir(parents=True, exist_ok=True)
    canonical = f"{b.CANONICAL}{REL}"
    (ROOT / "api").mkdir(exist_ok=True)
    (ROOT / "api" / "live.json").write_text(json.dumps({
        "page": f"{b.CANONICAL}live/", "domain": d.get("domain"), "front": d.get("domain") or "https://aiym168.github.io/signal/", "urls": U, "updated_at": d.get("updated_at"), "checked_at": d.get("checked_at"),
        "stream": [u + "/stream.mp3" for u in U], "radar": [u + "/api/radar.json" for u in U],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    stats = (f'<div class="pill live">状态 <b id="lv-state">检测中…</b></div>'
             f'<div class="pill">直播 <b>24 小时</b></div>'
             f'<div class="pill">网关雷达 <b>每 5 分钟</b></div>'
             f'<div class="pill">地址更新 <b>{esc((d.get("updated_at") or "—")[:16].replace("T", " "))}</b></div>'
             + (f'<div class="pill">好记域名 <b><a href="{esc(d["domain"])}">{esc(d["domain"].split("//")[-1].rstrip("/"))}</a></b></div>' if d.get("domain") else ""))
    html = f"""{b.head_block(f"AI 羊毛信号站 · 24 小时 AI 羊毛直播 + 大模型 API 网关雷达 | {b.SITE_NAME}", "AI 羊毛信号站：独立运行的直播站，24 小时滚动播报 AI 免费资源与全球优惠，整点快讯，并每 5 分钟实测十几家大模型 API 网关的连通性和延迟。这里是它的固定入口。", canonical)}
{b.page_shell_start("../", "module live")}
{b.mod_hero("SIGNAL STATION", "AI 羊毛信号站", "一个独立运行的直播站：24 小时不停播的 AI 羊毛电台、整点快讯，和实时的大模型 API 网关雷达。它跑在一台单独的服务器上，公网地址可能变化，这个页面永远指向它当前的地址。", stats, '<a href="../">首页</a> › AI 羊毛信号站', "../vendor/")}
<main class="wrap">
  <section class="section">
    <div class="panel-box lv-box">
      <p class="lv-msg" id="lv-msg">正在连接信号站…</p>
      <p><a class="btn primary" id="lv-go" href="{esc(U[0] + '/' if U else '#')}" rel="noopener">进入信号站 ↗</a>
         <a class="btn" href="../radio/index.html">收听往期电台</a>
         <a class="btn" href="{esc((d.get("domain") or "https://aiym168.github.io/signal/").rstrip("/") + "/daka/")}">🗺️ 打卡中国：点亮足迹地图 · 好友抢答 · 排行榜</a></p>
      {f'<p>好记的固定域名：<a href="{esc(d["domain"])}"><code>{esc(d["domain"])}</code></a>（页面常驻，自动连接直播后端）</p>' if d.get("domain") else ''}
      <ul class="lv-urls" id="lv-urls">{''.join(f'<li><code>{esc(u)}</code> <span data-u="{esc(u)}">检测中</span></li>' for u in U) or '<li>信号站地址还未登记。</li>'}</ul>
      <p class="lv-note">信号站上有什么：① 24 小时直播流（台呼 → 整点快讯 → 最新一期早报/晚报 → 往期），所有人听到的是同一路信号；② 实时字幕和本段提到的链接；③ 大模型 API 网关雷达：每 5 分钟请求一次各家公开接口地址，记录能否连通和响应时间，保留 24 小时。雷达只说明接口地址能连通，不代表模型推理一定正常。数据接口：<a href="../api/live.json">api/live.json</a></p>
    </div>
  </section>
  {b.site_footer("../", "AI 羊毛信号站")}
</main>
<script id="lv-data" type="application/json">{json.dumps(U).replace("</", "<\\/")}</script>
<script>
(function(){{
  var U=JSON.parse(document.getElementById('lv-data').textContent||'[]'), st=document.getElementById('lv-state'), msg=document.getElementById('lv-msg'), go=document.getElementById('lv-go');
  var stay=/[?&]stay/.test(location.search), done=false, left=U.length;
  function mark(u,t,ok){{var s=document.querySelector('[data-u="'+u+'"]'); if(s){{s.textContent=t; s.className=ok?'ok':'bad';}}}}
  if(!U.length){{st.textContent='未登记'; msg.textContent='信号站地址还未登记，请稍后再来，或先收听往期电台。'; return;}}
  U.forEach(function(u){{
    var c=new AbortController(); var tm=setTimeout(function(){{c.abort();}},8000);
    fetch(u+'/healthz',{{cache:'no-store',signal:c.signal}}).then(function(r){{return r.json();}}).then(function(j){{
      clearTimeout(tm); mark(u,'在线 · 在听 '+(j.listeners||0)+' 人',true);
      if(done) return; done=true; go.href=u+'/'; st.textContent='在线';
      msg.textContent=stay?'信号站在线。':'信号站在线，正在进入…';
      if(!stay) setTimeout(function(){{location.replace(u+'/');}},1200);
    }}).catch(function(){{
      clearTimeout(tm); mark(u,'连不上',false);
      if(--left===0&&!done){{st.textContent='离线'; msg.textContent='信号站暂时连不上（服务器可能在休眠或正在换地址，通常几分钟内恢复）。可以先收听往期电台。';}}
    }});
  }});
}})();
</script>
<style>
.lv-box{{padding:24px}} .lv-msg{{font-size:1.15rem}} .lv-urls{{list-style:none;padding:0;margin:14px 0;display:grid;gap:6px}}
.lv-urls code{{word-break:break-all}} .lv-urls .ok{{color:#5cffb0}} .lv-urls .bad{{color:#ff8a8a}} .lv-note{{color:var(--muted);font-size:.9rem;line-height:1.7}}
</style>
{b.page_scripts()}
</body></html>"""
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"[live] wrote {REL} urls={len(U)}")
    return REL


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    import build as B
    from datetime import datetime as _dt
    build_page(B, _dt.now(B.TZ))
