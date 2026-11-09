"""大模型 API 最低价榜页面（deals/api-prices.html），由 build.py 调用，只读 data/apiprices/prices.json。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "apiprices" / "prices.json"
SPONSORS = ROOT / "data" / "sponsors.json"
REL = "deals/api-prices.html"
CHANNEL = {"official": ("官方直连", "ok"), "openrouter": ("经 OpenRouter", "info"), "deepinfra": ("DeepInfra 官网", "info"), "novita": ("Novita 官网", "info")}


def sponsor_slot(slot: str, esc) -> str:
    """赞助位：data/sponsors.json 里有该位置的真实合作内容才显示，默认空、不占位。"""
    try:
        items = [x for x in (json.loads(SPONSORS.read_text(encoding="utf-8")).get("slots") or []) if x.get("slot") == slot and x.get("active")]
    except Exception:
        items = []
    if not items:
        return f'<aside class="sponsor-slot" data-slot="{esc(slot)}" hidden></aside>'
    x = items[0]
    return (f'<aside class="sponsor-slot on" data-slot="{esc(slot)}"><span class="sp-lab">赞助</span>'
            f'<a href="{esc(x.get("url"))}" target="_blank" rel="sponsored noopener">{esc(x.get("text"))}</a></aside>')


def money(v, fx):
    if v is None:
        return "—"
    s = f"{v:.4f}".rstrip("0").rstrip(".") if v < 1 else f"{v:.2f}".rstrip("0").rstrip(".")
    return f"${s}"


def cny(v, fx):
    return "" if v is None else f"≈¥{v * fx:.3f}".rstrip("0").rstrip(".")


def build_page(b, now) -> str | None:
    esc = b.esc
    try:
        d = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception as e:
        print("[apiprice] no data:", e)
        return None
    fx = (d.get("fx") or {}).get("usd_cny") or 7.1
    fxdate = (d.get("fx") or {}).get("date") or "未知"
    rows = d.get("rows") or []
    fams = []
    for r in rows:
        if r["family"] not in fams:
            fams.append(r["family"])
    provs = sorted({o["provider"] for r in rows for o in r["offers"]})
    upd = b.fmt_dt(d.get("updated_at"))

    def chg(o):
        c = o.get("change")
        if not c:
            return '<span class="ap-chg flat" title="自本站开始记录以来未变化">—</span>'
        arrow = "▼" if c["dir"] == "down" else "▲"
        return (f'<span class="ap-chg {c["dir"]}" title="上次 {money(c["prev_in"], fx)}/{money(c["prev_out"], fx)}，变化于 {esc(b.fmt_dt(c.get("since")))}">'
                f'{arrow}</span>')

    def cav(xs):
        return "".join(f'<span class="ap-cav">{esc(x)}</span>' for x in xs)

    bodies = []
    for r in rows:
        best = r["best"]
        offs = r["offers"]
        provtxt = " ".join(o["provider"] for o in offs)
        off_cell = (f'{money(r["official_in"], fx)} / {money(r["official_out"], fx)}<small>{esc(r["official_provider"])}</small>'
                    if r.get("official_in") is not None else '<span class="ap-na">OpenRouter 未收录官方直连（待核实）</span>')
        save = f'<b class="ap-save">-{r["save_pct"]:g}%</b>' if r.get("save_pct") else ('<span class="ap-na">官方即最低</span>' if r.get("official_in") is not None else "—")
        ch, chc = CHANNEL.get(best["channel"], ("", "info"))
        sub = "".join(f"""<tr class="{'ap-best' if i == 0 else ''}"><td>{esc(o['provider'])} <span class="ap-ch c-{CHANNEL.get(o['channel'], ('', 'info'))[1]}">{esc(CHANNEL.get(o['channel'], (o['channel'],))[0])}</span>{('<small>' + esc(o['tier']) + ' 档</small>') if o.get('tier') and o['tier'] not in ('standard', 'default') else ''}</td>
<td class="num">{money(o['in'], fx)}<small>{cny(o['in'], fx)}</small></td><td class="num">{money(o['out'], fx)}<small>{cny(o['out'], fx)}</small></td>
<td class="num">{(f"{o['ctx'] // 1000}K" if o.get('ctx') else '—')}</td><td>{chg(o)}</td><td>{cav(o.get('caveats') or []) or '<span class="ap-na">—</span>'}</td>
<td><a href="{esc(o['url'])}" target="_blank" rel="noopener noreferrer nofollow">打开 ↗</a> · <a href="{esc(o['source'])}" target="_blank" rel="noopener nofollow">数据源</a></td></tr>""" for i, o in enumerate(offs[:25]))
        more = f'<p class="ap-more-note">共 {len(offs)} 个报价，仅显示最便宜的 25 个。</p>' if len(offs) > 25 else ""
        bodies.append(f"""<tbody class="ap-model" data-fam="{esc(r['family'])}" data-prov="{esc(provtxt)}" data-text="{esc(r['name'] + ' ' + r['id'] + ' ' + r['family'] + ' ' + provtxt)}"
 data-s-model="{esc(r['name'])}" data-s-ctx="{r.get('ctx') or 0}" data-s-best="{best['in'] * 3 + best['out']:.6f}" data-s-off="{((r['official_in'] or 0) * 3 + (r['official_out'] or 0)) if r.get('official_in') is not None else 1e9:.6f}" data-s-save="{r.get('save_pct') or 0}">
<tr class="ap-row"><td><b>{esc(r['name'])}</b><small class="ap-id">{esc(r['id'])}</small>{'<span class="ap-free">有免费版（限速）</span>' if r.get('free') else ''}</td>
<td><span class="ap-fam">{esc(r['family'])}</span></td><td class="num">{(f"{r['ctx'] // 1000}K" if r.get('ctx') else '—')}</td>
<td class="num">{off_cell}</td>
<td class="num ap-bestcell">{money(best['in'], fx)} / {money(best['out'], fx)}<small>{esc(best['provider'])} · {esc(ch)}{(' · ' + esc(best['tier']) + ' 档') if best.get('tier') and best['tier'] not in ('standard', 'default') else ''}</small>{cav(best.get('caveats') or [])}</td>
<td class="num">{save}</td><td>{chg(offs[0])}</td>
<td><button type="button" class="btn sm ap-tog" aria-expanded="false">全部 {len(offs)} 家</button></td></tr>
<tr class="ap-sub" hidden><td colspan="8"><table class="ap-subt"><thead><tr><th>服务商</th><th>输入 /1M</th><th>输出 /1M</th><th>上下文</th><th>变化</th><th>注意</th><th>链接</th></tr></thead><tbody>{sub}</tbody></table>{more}
<p class="ap-more-note">官方定价页：<a href="{esc(r['official_page'])}" target="_blank" rel="noopener">{esc(r['official_page'])}</a> · 最后验证 {esc(b.fmt_dt(r.get('verified_at')))}</p></td></tr>
</tbody>""")
    famchips = "".join(f'<button type="button" class="chip" data-ap-fam="{esc(f)}" aria-pressed="false">{esc(f)} <i>{sum(1 for r in rows if r["family"] == f)}</i></button>' for f in fams)
    provopts = "".join(f'<option value="{esc(p)}">{esc(p)}</option>' for p in provs)
    n_off = sum(len(r["offers"]) for r in rows)
    saves = [r for r in rows if r.get("save_pct")]
    st = d.get("stat") or {}
    stats = (f'<div class="pill">模型 <b>{len(rows)}</b></div><div class="pill">报价 <b>{n_off}</b></div>'
             f'<div class="pill">比官方便宜 <b>{len(saves)}</b> 个模型</div><div class="pill">更新 <b>{esc(upd[5:])}</b></div>')
    body = f"""
  <nav class="dl-modnav"><a href="index.html"><b>←</b>全球优惠情报中心</a></nav>
  {sponsor_slot("apiprice-top", esc)}
  <section class="section" id="table">
    <div class="sec-head"><span class="sec-idx">API 价格</span><h2>各大模型 API 最低价对比</h2>
      <p class="sec-desc">价格单位：美元 / 每 100 万 tokens（源币种 USD）。人民币按 1 美元 ≈ {fx:g} 元换算（汇率日期 {esc(fxdate)}，仅供参考）。「最低价」按 输入×3 + 输出×1 的混合价比较。</p></div>
    <p class="note dl-note">低价不一定划算：量化版本（fp8/fp4/int4）质量可能下降，flex 档可能排队，部分小服务商可用率不稳定，表格里都标了出来。没有公开价格接口、无法核实的中转站 / 灰色转售渠道一律不收录、不推荐。</p>
    <div class="filters compact dl-filters js-ready" data-ap-root>
      <form class="searchbar" role="search" onsubmit="return false"><label class="sr-only" for="apq">搜索</label>
        <input id="apq" type="search" placeholder="搜索模型或服务商：DeepSeek、Claude、Groq、DeepInfra…" autocomplete="off" /></form>
      <div class="fgroups"><div class="fgroup"><span class="flabel">模型家族</span><div class="chips">{famchips}</div></div>
        <div class="fgroup"><span class="flabel">服务商</span><select data-ap-prov class="ap-sel"><option value="">全部服务商（{len(provs)}）</option>{provopts}</select></div></div>
      <div class="fbar"><span class="f-count" data-ap-count>共 {len(rows)} 个模型</span><span class="ap-hint">点表头可排序</span></div>
    </div>
    <div class="ap-wrap"><table class="ap-table" data-ap-table>
      <thead><tr><th data-sort="model">模型</th><th>家族</th><th data-sort="ctx" class="num">上下文</th><th data-sort="off" class="num">官方价 输入/输出</th>
      <th data-sort="best" class="num">全网最低 输入/输出</th><th data-sort="save" class="num">比官方省</th><th>变化</th><th></th></tr></thead>
      {''.join(bodies)}
    </table></div>
    <div class="empty hidden" data-ap-empty>没有符合条件的模型</div>
  </section>
  {sponsor_slot("apiprice-bottom", esc)}
  <section class="section" id="method"><div class="sec-head"><span class="sec-idx">说明</span><h2>数据来源与限制</h2></div>
    <div class="panel-box"><ul class="ap-list">
      <li>报价来自公开接口，每小时随站点更新自动刷新：OpenRouter 公开模型接口（含官方直连与 Together、Fireworks、Groq、DeepInfra、Novita 等上游在 OpenRouter 上的报价）、DeepInfra 官网公开模型列表、Novita 官网公开模型列表。</li>
      <li>「官方价」取 OpenRouter 收录的官方直连线路（如 OpenAI、Anthropic、DeepSeek、Z.AI、Moonshot AI）的标准档报价；本站没有直接抓取各家官方定价页，可点每个模型里的官方定价页链接自行核对。OpenRouter 没有官方直连线路的模型显示「待核实」。</li>
      <li>经 OpenRouter 调用时，充值手续费、限速等以 OpenRouter 官网为准；缓存折扣、批处理折扣、阶梯价没有计入。</li>
      <li>国内聚合平台（如硅基流动）的价格接口本站暂时访问不到，未收录；其他中转站因无法核实，一律不收录。</li>
      <li>价格变化（▲涨 ▼降）从本站开始记录（{esc(upd[:10])}）后才会出现。链接都是普通链接，没有推广返佣。</li>
    </ul><p class="note">机器可读数据：<a href="../api/api-prices.json">api/api-prices.json</a></p></div></section>"""
    canonical = b.CANONICAL + REL
    html = f"""{b.head_block(f"大模型 API 最低价榜 · GPT / Claude / Gemini / DeepSeek / Qwen / GLM / Kimi | {b.SITE_NAME}", "各大模型 API 每 100 万 tokens 的输入输出价格对比：官方价 vs OpenRouter、DeepInfra、Novita 等，每小时自动更新，标注量化与稳定性风险。", canonical)}
{b.page_shell_start("../", "module deals apiprice")}
{b.mod_hero("API 价格情报", "大模型 API 最低价榜", "全网各大模型 API 的输入 / 输出单价对比，官方 vs 第三方推理平台，每小时自动刷新。", stats, '<a href="../">首页</a> › <a href="index.html">优惠情报</a> › API 最低价榜', "../vendor/")}
<div class="wrap">
{body}
{b.site_footer("../", "大模型 API 最低价榜")}
</div>
{b.page_scripts()}
<script src="{b.vurl("../", "apiprice.js")}" defer></script>
</body></html>"""
    (ROOT / REL).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / REL).write_text(html, encoding="utf-8")
    (ROOT / "api").mkdir(exist_ok=True)
    (ROOT / "api" / "api-prices.json").write_text(json.dumps({k: v for k, v in d.items() if k != "stat"}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[apiprice] page models={len(rows)} offers={n_off}")
    return REL
