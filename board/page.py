"""Static page + homepage teaser for the anonymous board (called from build.py)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEX = ROOT / "board" / "lexicon"


def write_client_rules(site: Path):
    """Light client-side pre-check list (server re-checks with the full lexicon + pinyin).
    Base64-encoded so crawlers don't index a page full of sensitive words."""
    from board.filter import compact, CJK, _read_words
    words = sorted({compact(w) for w in _read_words(LEX / "custom_block.txt") if CJK.search(compact(w))} - {""})
    latin = sorted({w.lower() for w in _read_words(LEX / "abbr.txt") + _read_words(LEX / "latin_substring.txt")}
                   | {compact(w) for w in _read_words(LEX / "custom_block.txt") if compact(w) and not CJK.search(compact(w))})
    prefix = sorted({w.lower() for w in _read_words(LEX / "contact_prefix.txt")})
    enc = lambda xs: base64.b64encode("\n".join(xs).encode("utf-8")).decode()
    out = {"v": 1, "w": enc(words), "l": enc(latin), "p": enc(prefix)}
    (site / "vendor").mkdir(exist_ok=True)
    (site / "vendor" / "board-rules.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")


BOARD_CSS = r"""
body.board{overflow-x:hidden}
.board #fx-shader{display:none!important}
.bd-stage{position:relative;height:100vh;min-height:640px;max-height:1100px;overflow:hidden;isolation:isolate;
  background:radial-gradient(1200px 700px at 50% 55%,rgba(120,90,255,.16),transparent 60%),radial-gradient(800px 500px at 20% 20%,rgba(92,225,255,.10),transparent 60%),#02040a}
.bd-stage::after{content:"";position:absolute;inset:0;pointer-events:none;z-index:2;background:radial-gradient(ellipse 75% 65% at 50% 50%,transparent 55%,rgba(2,4,10,.85));}
#bd-canvas{position:absolute;inset:0;z-index:1;cursor:grab}
.bd-stage.grab #bd-canvas{cursor:grabbing}
.bd-hud{position:absolute;z-index:5;pointer-events:none}
.bd-hud *{pointer-events:auto}
.bd-hud.tl{left:clamp(16px,4vw,56px);top:92px;max-width:520px}
.bd-kicker{font:500 12px/1 var(--mono);letter-spacing:.32em;color:var(--cyan);text-transform:uppercase;display:flex;gap:10px;align-items:center}
.bd-kicker i{width:8px;height:8px;border-radius:50%;background:var(--mint);box-shadow:0 0 12px var(--mint);animation:bdPulse 1.6s infinite}
@keyframes bdPulse{50%{opacity:.35;transform:scale(.7)}}
.bd-title{font:700 clamp(38px,6.2vw,84px)/1.02 var(--display);margin:14px 0 10px;letter-spacing:-.02em;
  background:linear-gradient(100deg,#fff 0%,#bfefff 30%,#a78bfa 60%,#ff7ad9 85%);-webkit-background-clip:text;background-clip:text;color:transparent;
  filter:drop-shadow(0 0 28px rgba(140,120,255,.35));background-size:200% 100%;animation:bdSheen 8s linear infinite}
@keyframes bdSheen{to{background-position:-200% 0}}
.bd-sub{color:#b9c4e6;font-size:15px;line-height:1.75;margin:0 0 18px;max-width:460px;text-shadow:0 2px 12px #000}
.bd-stats{display:flex;gap:10px;flex-wrap:wrap}
.bd-stat{border:1px solid var(--line2);background:rgba(8,12,28,.55);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-radius:14px;padding:8px 14px;min-width:96px}
.bd-stat small{display:block;font:500 10px/1.4 var(--mono);letter-spacing:.2em;color:var(--muted);text-transform:uppercase}
.bd-stat b{font:700 22px/1.2 var(--display);color:#fff}
.bd-stat b.sm{font-size:14px;line-height:1.9}
.bd-hint{margin-top:14px;font:500 11px/1.6 var(--mono);color:var(--dim);letter-spacing:.12em}
.bd-hud.tr{right:clamp(16px,3vw,40px);top:92px;width:300px}
#bd-mine{display:none;border:1px solid var(--line2);background:rgba(8,12,28,.62);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-radius:16px;padding:12px 14px}
#bd-mine.has{display:block}
#bd-mine h3{margin:0 0 8px;font:600 12px/1 var(--mono);letter-spacing:.22em;color:var(--cyan)}
.bd-mine-row{border-top:1px dashed rgba(140,200,255,.15);padding:8px 0}
.bd-mine-row p{margin:2px 0 0;font-size:13px;color:#dfe6ff;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.bd-mine-row small{color:#ffb3c7;font-size:12px}
.bd-mine-s{font:500 11px/1.4 var(--mono);color:var(--warn)}
.bd-mine-row.ok .bd-mine-s{color:var(--mint)} .bd-mine-row.rej .bd-mine-s{color:#ff8fa8}
.bd-viewbtn{position:absolute;z-index:6;right:clamp(16px,3vw,40px);bottom:28px;font:500 12px/1 var(--mono);letter-spacing:.14em;color:#cfe9ff;background:rgba(8,12,28,.6);border:1px solid var(--line2);padding:10px 14px;border-radius:999px;cursor:pointer;backdrop-filter:blur(10px)}
.bd-viewbtn:hover{border-color:var(--cyan);box-shadow:0 0 18px rgba(92,225,255,.35)}
#bd-labels{position:absolute;inset:0;z-index:4;pointer-events:none;overflow:hidden}
.bd-label{--h:190;position:absolute;left:0;top:0;font:500 11px/1 var(--mono);letter-spacing:.06em;color:hsl(var(--h),95%,80%);white-space:nowrap;padding:4px 8px;border-radius:999px;
  background:rgba(4,8,20,.55);border:1px solid hsla(var(--h),95%,70%,.35);transition:opacity .3s;will-change:transform;text-shadow:0 0 8px hsla(var(--h),95%,60%,.8)}
.bd-k-short{display:none}
/* portal composer */
.bd-portal{--fill:0;--pow:0;position:absolute;z-index:7;left:50%;bottom:26px;transform:translateX(-50%);width:min(680px,calc(100% - 28px));
  border-radius:26px;padding:2px;background:conic-gradient(from var(--a,0deg),rgba(92,225,255,.9),rgba(167,139,250,.2),rgba(255,122,217,.85),rgba(94,240,192,.2),rgba(92,225,255,.9));
  animation:bdSpin 6s linear infinite;box-shadow:0 0 40px rgba(110,120,255,.28),0 30px 80px rgba(0,0,0,.6)}
@property --a{syntax:"<angle>";inherits:false;initial-value:0deg}
@keyframes bdSpin{to{--a:360deg}}
.bd-portal.focus,.bd-portal.charging{animation-duration:1.4s;box-shadow:0 0 70px rgba(92,225,255,.45),0 30px 80px rgba(0,0,0,.6)}
.bd-portal.charging{animation-duration:.45s}
.bd-portal-in{position:relative;border-radius:24px;background:linear-gradient(180deg,rgba(6,10,24,.92),rgba(4,6,16,.95));padding:14px 14px 12px;overflow:hidden}
.bd-portal-in::before{content:"";position:absolute;left:0;top:0;height:2px;width:calc(var(--fill)*100%);background:var(--grad);box-shadow:0 0 12px var(--cyan);transition:width .25s}
.bd-portal-in::after{content:"";position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(255,255,255,.025) 0 1px,transparent 1px 3px);mix-blend-mode:overlay}
.bd-portal textarea{width:100%;min-height:64px;max-height:160px;resize:none;border:0;outline:0;background:transparent;color:#fff;font:400 16px/1.65 var(--sans);padding:2px 4px}
.bd-portal textarea::placeholder{color:#6f7da3}
.bd-row{display:flex;gap:10px;align-items:center;margin-top:8px;flex-wrap:wrap}
.bd-nickwrap{display:flex;align-items:center;gap:6px;flex:1;min-width:180px;border:1px solid var(--line);border-radius:999px;padding:4px 6px 4px 12px;background:rgba(255,255,255,.03)}
.bd-nickwrap span{font:500 10px/1 var(--mono);letter-spacing:.16em;color:var(--muted)}
.bd-nickwrap input{flex:1;min-width:60px;border:0;outline:0;background:transparent;color:#dff6ff;font:500 13px/1.6 var(--sans)}
.bd-nickwrap input::placeholder{color:#7f8fb8}
#bd-dice{border:0;background:rgba(92,225,255,.12);color:var(--cyan);width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:14px}
#bd-dice:hover{transform:rotate(180deg);transition:transform .4s}
#bd-count{font:500 11px/1 var(--mono);color:var(--dim)} #bd-count.over{color:#ff8fa8}
#bd-send{position:relative;border:0;cursor:pointer;border-radius:999px;padding:11px 22px 11px 18px;font:700 14px/1 var(--display);letter-spacing:.06em;color:#02040a;
  background:linear-gradient(100deg,#5ce1ff,#a78bfa 60%,#ff7ad9);box-shadow:0 0 24px rgba(92,225,255,.5);display:flex;align-items:center;gap:8px;overflow:hidden}
#bd-send::before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.7),transparent);transform:translateX(-100%);animation:bdShine 2.6s infinite}
@keyframes bdShine{60%,100%{transform:translateX(100%)}}
#bd-send svg{width:18px;height:18px}
#bd-send:disabled{filter:saturate(.6) brightness(.9);cursor:progress}
.bd-portal.charging #bd-send{background:linear-gradient(90deg,#5ef0c0 calc(var(--pow)*100%),#5ce1ff calc(var(--pow)*100%))}
.bd-portal.shake{animation:bdShake .5s,bdSpin 6s linear infinite}
@keyframes bdShake{20%,60%{transform:translateX(calc(-50% - 8px))}40%,80%{transform:translateX(calc(-50% + 8px))}}
.bd-portal.launch .bd-portal-in{animation:bdFlash 1.2s}
@keyframes bdFlash{0%{box-shadow:inset 0 0 0 rgba(92,225,255,0)}20%{box-shadow:inset 0 0 120px rgba(160,240,255,.9)}100%{box-shadow:inset 0 0 0 rgba(92,225,255,0)}}
.bd-hp{position:absolute!important;left:-9999px!important;width:1px;height:1px;opacity:0}
.bd-rules{font:400 11.5px/1.6 var(--sans);color:var(--dim);margin-top:6px}
/* hologram card */
#bd-holo{--h:190;position:absolute;z-index:8;width:min(360px,calc(100% - 28px));padding:16px 18px 18px;border-radius:18px;pointer-events:none;opacity:0;transform:scale(.96);transition:opacity .25s,transform .25s;
  background:linear-gradient(160deg,hsla(var(--h),90%,60%,.16),rgba(6,10,26,.82) 40%,rgba(6,10,26,.9));border:1px solid hsla(var(--h),95%,70%,.55);
  box-shadow:0 0 0 1px rgba(255,255,255,.04) inset,0 0 40px hsla(var(--h),95%,60%,.35),0 20px 60px rgba(0,0,0,.6);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);overflow:hidden}
#bd-holo.on{opacity:1;transform:none}
#bd-holo.pinned{pointer-events:auto}
#bd-holo::before{content:"";position:absolute;inset:0;background:repeating-linear-gradient(0deg,rgba(255,255,255,.05) 0 1px,transparent 1px 4px);pointer-events:none;animation:bdScan 6s linear infinite}
@keyframes bdScan{to{background-position:0 120px}}
#bd-holo::after{content:"";position:absolute;left:-40%;top:0;width:40%;height:100%;background:linear-gradient(90deg,transparent,hsla(var(--h),100%,80%,.18),transparent);animation:bdSweep 3.2s infinite}
@keyframes bdSweep{to{left:140%}}
#bd-holo.glitch{animation:bdGlitch .45s steps(2)}
@keyframes bdGlitch{0%{clip-path:inset(0 0 60% 0);transform:translateX(-6px)}30%{clip-path:inset(40% 0 20% 0);transform:translateX(5px)}60%{clip-path:inset(10% 0 50% 0);transform:translateX(-3px)}100%{clip-path:inset(0);transform:none}}
.bd-holo-foot{display:flex;justify-content:space-between;margin-top:12px;padding-top:8px;border-top:1px dashed hsla(var(--h),95%,70%,.25);font:500 10px/1.4 var(--mono);letter-spacing:.12em;color:var(--dim)}
.bd-holo-top{white-space:nowrap;padding-right:22px;display:flex;justify-content:space-between;gap:10px;font:500 10.5px/1.4 var(--mono);letter-spacing:.14em;color:hsl(var(--h),95%,75%)}
.bd-holo-nick{margin:10px 0 6px;font:700 17px/1.3 var(--display);color:#fff;display:flex;align-items:center;gap:8px}
.bd-holo-nick::before{content:"";width:10px;height:10px;border-radius:50%;background:hsl(var(--h),95%,65%);box-shadow:0 0 14px hsl(var(--h),95%,65%)}
#bd-holo-text{margin:0;color:#e8eeff;font-size:15px;line-height:1.8;white-space:pre-wrap;min-height:1.8em}
#bd-holo-text::after{content:"▍";color:hsl(var(--h),95%,70%);animation:bdPulse 1s infinite}
.bd-holo-c{position:absolute;width:14px;height:14px;border-color:hsl(var(--h),95%,70%);border-style:solid;opacity:.9}
.bd-holo-c.a{left:6px;top:6px;border-width:2px 0 0 2px}.bd-holo-c.b{right:6px;top:6px;border-width:2px 2px 0 0}.bd-holo-c.c{left:6px;bottom:6px;border-width:0 0 2px 2px}.bd-holo-c.d{right:6px;bottom:6px;border-width:0 2px 2px 0}
#bd-holo-x{position:absolute;right:10px;top:8px;border:0;background:transparent;color:#9fb0d8;font-size:18px;cursor:pointer;display:none}
#bd-holo.pinned #bd-holo-x{display:block}
.bd-toast{position:fixed;z-index:90;left:50%;top:84px;transform:translate(-50%,-20px);opacity:0;pointer-events:none;max-width:min(560px,92vw);padding:12px 18px;border-radius:14px;
  background:rgba(8,12,28,.92);border:1px solid var(--line2);color:#eaf4ff;font-size:14px;line-height:1.6;box-shadow:0 10px 40px rgba(0,0,0,.6);transition:.3s var(--ease)}
.bd-toast.show{opacity:1;transform:translate(-50%,0)}
.bd-toast.err{border-color:rgba(255,120,150,.6);box-shadow:0 0 30px rgba(255,90,140,.25)}
.bd-toast.ok{border-color:rgba(94,240,192,.6);box-shadow:0 0 30px rgba(94,240,192,.25)}
/* flow list */
.bd-flow{position:relative;z-index:3}
.bd-flow .sec-head{margin-top:56px}
.bd-tools{display:flex;gap:12px;align-items:center;margin:0 0 18px;flex-wrap:wrap}
.bd-tools input{flex:1;min-width:220px;border:1px solid var(--line2);background:rgba(8,12,28,.6);color:#fff;border-radius:999px;padding:11px 18px;font:400 14px var(--sans);outline:0}
.bd-tools input:focus{border-color:var(--cyan);box-shadow:0 0 0 3px rgba(92,225,255,.15)}
.bd-tools span{font:500 11px/1.4 var(--mono);color:var(--dim)}
#bd-list{columns:3 300px;column-gap:16px}
.bd-card{--h:190;break-inside:avoid;margin:0 0 16px;padding:16px 18px;border-radius:18px;cursor:pointer;position:relative;overflow:hidden;
  background:linear-gradient(160deg,hsla(var(--h),90%,60%,.10),rgba(10,16,34,.7) 45%);border:1px solid hsla(var(--h),90%,70%,.22);animation:bdIn .6s var(--ease) both;transition:transform .3s var(--ease),border-color .3s,box-shadow .3s}
.bd-card:hover{transform:translateY(-3px);border-color:hsla(var(--h),95%,70%,.6);box-shadow:0 0 30px hsla(var(--h),95%,60%,.22)}
@keyframes bdIn{from{opacity:0;transform:translateY(16px)}}
.bd-card-h{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px;font-size:13px}
.bd-card-h b{color:#fff;font-weight:600}
.bd-dot{width:8px;height:8px;border-radius:50%;background:hsl(var(--h),95%,65%);box-shadow:0 0 10px hsl(var(--h),95%,65%)}
.bd-id,.bd-card time{font:500 10.5px/1 var(--mono);color:var(--dim);letter-spacing:.06em}
.bd-card time{margin-left:auto}
.bd-card p{margin:0;color:#dfe6ff;line-height:1.8;white-space:pre-wrap}
.bd-card.pending{opacity:.6;border-style:dashed}
.bd-empty{padding:40px;text-align:center;color:var(--muted);border:1px dashed var(--line2);border-radius:18px}
.bd-rulebox{margin-top:28px}
.bd-rulebox ul{margin:6px 0 0;padding-left:18px;color:var(--muted);font-size:13.5px;line-height:1.9}
/* flat / reduced-motion fallback */
.bd-flat #bd-canvas{background:radial-gradient(2px 2px at 20% 30%,#fff,transparent),radial-gradient(1.5px 1.5px at 70% 60%,#bff,transparent),radial-gradient(2px 2px at 40% 80%,#caf,transparent),radial-gradient(1px 1px at 85% 25%,#fff,transparent),radial-gradient(600px 400px at 50% 55%,rgba(167,139,250,.25),transparent)}
.bd-flat .bd-hint{display:none}
@media (max-width:820px){
  .bd-stage{height:88vh;min-height:620px}
  .bd-hud.tl{top:74px;left:16px;right:16px}
  .bd-title{font-size:40px;margin:10px 0 6px}
  .bd-sub{font-size:13.5px;margin-bottom:12px}
  .bd-stat{min-width:0;padding:6px 10px}.bd-stat b{font-size:17px}
  .bd-hud.tr{display:none}
  .bd-viewbtn{bottom:auto;top:auto;right:16px;padding:8px 12px;font-size:11px;bottom:calc(12px + var(--portal-h,150px) + 10px)}
  .bd-k-long{display:none}.bd-k-short{display:inline}
  .bd-portal{bottom:12px;border-radius:22px}
  .bd-portal-in{padding:10px 10px 10px;border-radius:20px}
  .bd-portal textarea{min-height:48px;font-size:15px}
  .bd-hint{display:none}
  #bd-send{padding:10px 16px 10px 14px}
  .bd-rules{display:none}
  #bd-list{columns:1}
}
@media (prefers-reduced-motion:reduce){.bd-portal,#bd-send::before,.bd-title{animation:none!important}}
"""


SEND_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>'


def write_board_page(site: Path, *, head_block, topnav, site_footer, site_js, canonical: str, site_name: str, ym: str, esc):
    cfg = json.loads((ROOT / "board" / "config.json").read_text(encoding="utf-8"))
    pub = {k: cfg[k] for k in ("relay", "topic", "pubkey_spki", "pow_prefix", "max_len", "max_nick")}
    pub["base"] = "../"
    write_client_rules(site)
    title = f"匿名留言板 · 星际信号站 | {site_name} · {ym}"
    desc = f"{site_name}匿名留言板：无需登录，写下你想说的话，化作星空里的一颗发光信号。交流免费大模型、免费API与AI工具使用心得。"
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": "匿名留言板 · 星际信号站", "url": f"{canonical}m/board.html", "inLanguage": "zh-CN", "description": desc,
           "isPartOf": {"@type": "WebSite", "name": site_name, "url": canonical}},
          {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
              {"@type": "ListItem", "position": 1, "name": "首页", "item": canonical},
              {"@type": "ListItem", "position": 2, "name": "匿名留言板", "item": f"{canonical}m/board.html"}]}]
    head = head_block(title, desc, f"{canonical}m/board.html", extra_ld=ld)
    head = head.replace("</head>", f"<style>{BOARD_CSS}</style>\n</head>")
    page = f"""{head}
<body class="board">
<div class="fx-noise" aria-hidden="true"></div>
<div class="fx-scan" aria-hidden="true"></div>
{topnav("../")}
<main>
<section class="bd-stage" id="bd-stage" aria-label="星际信号星图">
  <div id="bd-canvas"></div>
  <div id="bd-labels" aria-hidden="true"></div>
  <div class="bd-hud tl">
    <div class="bd-kicker"><i></i> <span class="bd-k-long">匿名留言 · 星际信号站</span><span class="bd-k-short">星际信号站</span></div>
    <h1 class="bd-title" data-scramble>星际信号站</h1>
    <p class="bd-sub">匿名留言板 · 无需登录。写下想说的话，它会化作一束光，穿越审核星门，成为星空里的一颗信号星。</p>
    <div class="bd-stats">
      <div class="bd-stat"><small>信号总数</small><b id="bd-total">0</b></div>
      <div class="bd-stat"><small>今日新星</small><b id="bd-today">0</b></div>
      <div class="bd-stat"><small>最近信号</small><b class="sm" id="bd-latest">--</b></div>
    </div>
    <div class="bd-hint">拖动旋转星系 · 滚轮/双指缩放 · 点击星辰阅读信号</div>
  </div>
  <div class="bd-hud tr"><div id="bd-mine"><h3>我的信号</h3><div id="bd-mine-list"></div></div></div>
  <button class="bd-viewbtn" id="bd-view" type="button">≡ 列表视图</button>
  <div id="bd-holo" role="dialog" aria-live="polite">
    <i class="bd-holo-c a"></i><i class="bd-holo-c b"></i><i class="bd-holo-c c"></i><i class="bd-holo-c d"></i>
    <div class="bd-holo-top"><span id="bd-holo-id">信号</span><span id="bd-holo-ago"></span></div>
    <button id="bd-holo-x" type="button" aria-label="关闭">×</button>
    <div class="bd-holo-nick" id="bd-holo-nick"></div>
    <p id="bd-holo-text"></p>
    <div class="bd-holo-foot"><span id="bd-holo-time"></span><span>匿名 · 已审核</span></div>
  </div>
  <form class="bd-portal" id="bd-portal" onsubmit="return false" autocomplete="off">
    <div class="bd-portal-in">
      <label class="sr-only" for="bd-text" style="position:absolute;left:-9999px">留言内容</label>
      <textarea id="bd-text" maxlength="{int(cfg['max_len']) + 50}" rows="2" placeholder="写下你想对宇宙说的话……"></textarea>
      <input class="bd-hp" id="bd-hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true" />
      <div class="bd-row">
        <div class="bd-nickwrap"><span>代号</span><input id="bd-nick" maxlength="{int(cfg['max_nick'])}" placeholder="星际旅人" /><button type="button" id="bd-dice" title="随机代号">⟳</button></div>
        <span id="bd-count">0 / {int(cfg['max_len'])}</span>
        <button type="button" id="bd-send">{SEND_SVG}<span id="bd-send-t">发射信号</span></button>
      </div>
      <div class="bd-rules">文明留言 · 禁止涉政、辱骂、色情、赌博、诈骗、广告与联系方式 · 所有信号经服务器审核后点亮</div>
    </div>
  </form>
</section>
<div class="wrap bd-flow" id="bd-flow">
  <div class="sec-head"><span class="sec-idx">信号流</span>
    <h2>信号流</h2>
    <p class="sec-desc">所有已点亮的信号按时间倒序排列，点击卡片可在星图中定位。数据更新于 <span id="bd-updated">--</span>。</p></div>
  <div class="bd-tools"><input id="bd-q" type="search" placeholder="搜索信号 / 代号 / 编号…" /><span>API：<a href="../api/board.json">/api/board.json</a></span></div>
  <div id="bd-list"><div class="bd-empty">正在接收星际信号……</div></div>
  <div class="panel-box bd-rulebox"><h2>留言须知</h2>
    <ul>
      <li>完全匿名，无需注册或登录；代号可留空，系统会随机分配一个星际代号。</li>
      <li>每条最多 {int(cfg['max_len'])} 字；同一设备每 10 分钟最多 3 条、每天最多 12 条。</li>
      <li>信号先加密传输，经服务器自动审核后点亮，通常 10–30 分钟内出现在星空。</li>
      <li>请文明友善：涉政、辱骂、色情、赌博、毒品、诈骗、广告、网址和联系方式都会被自动拦截。</li>
      <li>发现不良信息？记下信号编号（如 M-7F3A2C），站长会将其移除。</li>
    </ul>
  </div>
  {site_footer("../")}
</div>
</main>
<div class="bd-toast" id="bd-toast" role="status"></div>
<script type="application/json" id="board-cfg">{json.dumps(pub, ensure_ascii=False)}</script>
<script>{site_js}</script>
<script type="module" src="../vendor/board.js"></script>
</body></html>"""
    (site / "m").mkdir(exist_ok=True)
    (site / "m" / "board.html").write_text(page, encoding="utf-8")
    return "m/board.html"


TEASER_CSS = r"""
.bd-teaser{position:relative;display:grid;grid-template-columns:1.1fr 1fr;gap:28px;align-items:center;padding:34px;border-radius:28px;overflow:hidden;isolation:isolate;
  border:1px solid rgba(167,139,250,.35);background:radial-gradient(600px 300px at 80% 50%,rgba(167,139,250,.22),transparent 70%),radial-gradient(500px 260px at 10% 0%,rgba(92,225,255,.14),transparent 70%),rgba(6,10,24,.7)}
.bd-teaser::before{content:"";position:absolute;inset:0;z-index:-1;opacity:.9;background-image:radial-gradient(1.5px 1.5px at 12% 22%,#fff,transparent),radial-gradient(1px 1px at 32% 72%,#bff,transparent),radial-gradient(1.5px 1.5px at 58% 18%,#caf,transparent),radial-gradient(1px 1px at 78% 62%,#fff,transparent),radial-gradient(1.5px 1.5px at 90% 30%,#9ff,transparent),radial-gradient(1px 1px at 46% 46%,#fff,transparent);background-size:240px 240px;animation:bdDrift 40s linear infinite}
@keyframes bdDrift{to{background-position:240px 120px}}
.bd-teaser h2{margin:8px 0 10px;font:700 clamp(28px,3.4vw,44px)/1.1 var(--display);background:linear-gradient(100deg,#fff,#bfefff 35%,#a78bfa 70%,#ff7ad9);-webkit-background-clip:text;background-clip:text;color:transparent}
.bd-teaser p{color:var(--muted);margin:0 0 18px}
.bd-orbit{position:relative;height:240px}
.bd-orbit .o{position:absolute;left:50%;top:50%;border:1px solid rgba(140,200,255,.18);border-radius:50%;transform:translate(-50%,-50%) rotateX(68deg);animation:bdRot 18s linear infinite}
.bd-orbit .o1{width:180px;height:180px}.bd-orbit .o2{width:300px;height:300px;animation-duration:30s;border-color:rgba(167,139,250,.2)}.bd-orbit .o3{width:420px;height:420px;animation-duration:46s}
@keyframes bdRot{to{transform:translate(-50%,-50%) rotateX(68deg) rotateZ(360deg)}}
.bd-orbit .core{position:absolute;left:50%;top:50%;width:46px;height:46px;margin:-23px;border-radius:50%;background:radial-gradient(circle,#fff,#a78bfa 45%,transparent 70%);box-shadow:0 0 60px 18px rgba(167,139,250,.45);animation:bdPulse 3s infinite}
.bd-chip{position:absolute;max-width:240px;padding:8px 12px;border-radius:12px;font-size:12.5px;line-height:1.5;color:#e6eeff;background:rgba(8,12,28,.72);border:1px solid rgba(140,200,255,.25);backdrop-filter:blur(8px);animation:bdFloat 6s ease-in-out infinite;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bd-chip b{color:var(--cyan);font-weight:600;margin-right:6px}
.bd-chip:nth-child(1){left:2%;top:12%}.bd-chip:nth-child(2){right:0;top:44%;animation-delay:-2s}.bd-chip:nth-child(3){left:12%;bottom:6%;animation-delay:-4s}
@keyframes bdFloat{50%{transform:translateY(-10px)}}
@media (max-width:820px){.bd-teaser{grid-template-columns:1fr;padding:24px}.bd-orbit{height:200px}.bd-chip{max-width:200px}}
"""


def home_teaser_html(prefix: str = "") -> str:
    return f"""<style>{TEASER_CSS}</style>
<section class="section" id="board">
  <div class="bd-teaser reveal">
    <div>
      <div class="bd-kicker" style="font:500 12px/1 var(--mono);letter-spacing:.3em;color:var(--cyan)">匿名留言 · 星际信号站</div>
      <h2>匿名留言板 · 星际信号站</h2>
      <p>无需登录，写下你想说的话，它会化作一束光飞入星空，成为一颗可以被所有人点亮阅读的信号星。</p>
      <a class="btn primary" href="{prefix}m/board.html">进入星际信号站 →</a>
    </div>
    <div class="bd-orbit" aria-hidden="true">
      <span class="o o3"></span><span class="o o2"></span><span class="o o1"></span><span class="core"></span>
      <div id="bd-chips"></div>
    </div>
  </div>
</section>
<script>
(function(){{var box=document.getElementById('bd-chips');if(!box)return;
fetch('{prefix}api/board.json?t='+Math.floor(Date.now()/600000)).then(function(r){{return r.json()}}).then(function(j){{
var ms=(j.messages||[]).slice(0,3);if(!ms.length){{ms=[{{nick:'星际旅人',text:'成为第一个发射信号的人吧 ✦'}}]}}
ms.forEach(function(m){{var c=document.createElement('div');c.className='bd-chip';var b=document.createElement('b');b.textContent=m.nick||'匿名旅人';c.appendChild(b);c.appendChild(document.createTextNode(m.text||''));box.appendChild(c)}});
}}).catch(function(){{}});}})();
</script>"""
