#!/usr/bin/env python3
"""AI 羊毛电台 — turns the site's own data into a short spoken briefing.

Runs on the second server (engine/radio_run.sh, 08:30 + 20:30 Asia/Shanghai).
  1. writes a script ONLY from data the site already shows (api/deals.json, api/latest.json,
     api/api-prices.json); nothing is invented, unverified items are read out as 待核实
  2. synthesises it offline (sherpa-onnx + Kokoro multi-lang v1.1, Apache-2.0) — no cloud TTS
  3. encodes MP3 (lameenc), uploads it as a GitHub release asset (keeps audio out of git history)
  4. prepends the episode (script, per-segment timings, links) to data/radio/episodes.json
Pages are rendered by radio_build.py (called from build.py on every engine).
env: RADIO_MODEL_DIR (default ~/radio/kokoro-multi-lang-v1_1), RADIO_SID (default 3 = zf_001),
     GH_TOKEN, RADIO_DRY=1 (script only, no TTS/upload)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Asia/Shanghai")
REPO = "aiym168/aiym168.github.io"
EPS = ROOT / "data" / "radio" / "episodes.json"
KEEP = 60
SR = 24000
LIVE = ("active", "expiring", "upcoming")


def j(p: Path, d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {} if d is None else d


def md(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
        return f"{t.month}月{t.day}日"
    except Exception:
        return None


def say(s: str) -> str:
    """Make text friendlier for TTS without changing facts."""
    s = s or ""
    s = re.sub(r"(\d),(\d{3})", r"\1\2", s)
    s = re.sub(r"(\d),(\d{3})", r"\1\2", s)
    s = re.sub(r"(\d{1,2})/(\d{1,2})\s*[-–~]\s*(\d{1,2})/(\d{1,2})", r"\1月\2日到\3月\4日", s)
    s = re.sub(r"(?<![\d.])(\d{1,2})/(\d{1,2})(?![\d/])", r"\1月\2日", s)
    s = re.sub(r"(?<![\d.])(\d{5,})(?![\d.])", lambda m: wan(int(m.group(1))), s)
    s = s.replace("：", "，").replace(":", "，").replace("+", "加").replace("/", "或").replace("|", "，")
    s = s.replace("≈", "约").replace("~", "到").replace("＆", "和").replace("&", "和")
    s = re.sub(r"[「」『』【】《》\"“”]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ，")
    return s


def wan(n: int) -> str:
    if n >= 100000000 and n % 1000000 == 0:
        return f"{n / 100000000:g}亿"
    if n >= 10000 and n % 100 == 0:
        return f"{n / 10000:g}万"
    return str(n)


def short(s: str, n: int = 60) -> str:
    s = re.split(r"[。；;]", s or "")[0]
    if len(s) <= n:
        return s
    cut = s[:n]
    if re.match(r"[A-Za-z0-9]", s[n:n + 1] or "") and " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip("，、—- ") + "……"


def tg(r: dict) -> str:
    t = r.get("type_tags") or []
    if "free" in t and "trial" in t:
        return "试用额度加长期免费"
    if "free" in t:
        return "免费"
    if "trial" in t:
        return "试用"
    if "deposit" in t or "topup" in t:
        return "需要充值"
    if "volume" in t or "trade" in t:
        return "需要交易量"
    if "invite" in t:
        return "需要邀请"
    return ""


def build_script(now: datetime, edition: str) -> dict:
    deals = j(ROOT / "api" / "deals.json")
    items = [r for r in (deals.get("items") or []) if r.get("state") in LIVE]
    latest = j(ROOT / "api" / "latest.json").get("items") or []
    meta = j(ROOT / "api" / "meta.json")
    prices = j(ROOT / "api" / "api-prices.json").get("rows") or []
    segs: list[dict] = []
    ed = "早报" if edition == "am" else "晚报"

    def add(kind, text, links=None):
        segs.append({"kind": kind, "text": text.strip(), "links": links or []})

    add("intro", f"欢迎收听 AI 羊毛电台，{now.month}月{now.day}日{ed}。本节目由 AI大模型免费资源导航 的程序，"
                 f"根据网站已经收录的条目自动整理和朗读，大约三分钟。所有规则请以官方页面为准。")
    c = meta.get("counts") or {}
    add("stats", f"先看数字。情报中心进行中的优惠共 {deals.get('live', len(items))} 条，其中已核实 {deals.get('verified', 0)} 条，"
                 f"官方公告 {deals.get('official', 0)} 条，待核实 {deals.get('pending', 0)} 条。"
                 f"免费资源导航一共收录 {c.get('deals', len(latest))} 条，今天新增 {c.get('today_new', 0)} 条。")

    # 1) high-value, verified or official only
    top = sorted([r for r in items if r.get("verify_status") in ("verified", "official")], key=lambda r: -(r.get("score") or 0))
    seen_ids = set()
    picks = []
    for r in top:
        if r["id"] in seen_ids or len(picks) >= 4:
            continue
        if picks and sum(1 for p in picks if p.get("category") == r.get("category")) >= 2:
            continue
        picks.append(r); seen_ids.add(r["id"])
    if picks:
        add("head", "接下来是本期最值得看的几条。")
    nums = ["第一条", "第二条", "第三条", "第四条"]
    for i, r in enumerate(picks):
        val = (r.get("value") or {}).get("label") or ""
        cond = short((r.get("conditions") or [""])[0], 40)
        end = md(r.get("end_at"))
        when = f"截止时间 {end}" if end else short(r.get("deadline_note") or "截止时间未注明", 30)
        kind = tg(r)
        st = "已对照官网核实" if r.get("verify_status") == "verified" else "来自官方公告"
        txt = f"{nums[i]}，{say(r['title'])}。{('价值大约是 ' + say(val) + '。') if val else ''}{('类型，' + kind + '。') if kind else ''}"
        txt += f"{('条件，' + say(cond) + '。') if cond else ''}{say(when)}。{st}。"
        add("deal", txt, [{"title": r["title"], "url": r.get("official_url") or r.get("source_url"), "path": f"deals/x/{r['id']}.html"}])

    # 2) ending soon (within 7 days)
    soon = []
    for r in items:
        try:
            e = datetime.fromisoformat((r.get("end_at") or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if now <= e <= now + timedelta(days=7) and r["id"] not in seen_ids:
            soon.append((e, r))
    soon.sort(key=lambda x: x[0])
    if soon:
        names = "；".join(f"{say(short(r['title'], 36))}，{md(r['end_at'])}截止" + ("，这条还待核实" if r.get("verify_status") == "pending" else "")
                         for _e, r in soon[:3])
        add("soon", f"即将截止的有 {len(soon)} 条，最近的几条是：{names}。想参加的话别拖。",
            [{"title": r["title"], "url": r.get("official_url") or r.get("source_url"), "path": f"deals/x/{r['id']}.html"} for _e, r in soon[:3]])

    # 3) newest free AI resources
    new = sorted([x for x in latest if not x.get("pinned")], key=lambda x: x.get("fetched_at") or "", reverse=True)[:3]
    if new:
        add("new", "免费资源这边，最新收录的是：" + "；".join(say(short(x["title"], 40)) for x in new) + "。每条是否需要绑卡、实名，网页上都有标注。",
            [{"title": x["title"], "url": x.get("url"), "path": x.get("path")} for x in new])

    # 4) API price board: biggest saving
    pr = sorted([r for r in prices if r.get("save_pct") and r.get("best")], key=lambda r: -r["save_pct"])[:1]
    for r in pr:
        b = r["best"]
        name = re.sub(r"^[^:]+:\s*", "", r.get("name") or r["id"])
        add("price", f"再看大模型 API 最低价榜。目前降幅最大的是 {say(name)}，最低价来自 {say(b['provider'])}，"
                     f"每百万输入 token {b['in']:g} 美元，每百万输出 token {b['out']:g} 美元，比官方标价便宜 {r['save_pct']:g}%。"
                     + ("注意，" + say(short((b.get('caveats') or [''])[0], 30)) + "。" if b.get("caveats") else ""),
            [{"title": r.get("name") or r["id"], "url": b.get("url"), "path": "deals/api-prices.html"}])

    # 5) one pending item, clearly marked
    pend = sorted([r for r in items if r.get("verify_status") == "pending" and r["id"] not in seen_ids], key=lambda r: -(r.get("score") or 0))[:1]
    for r in pend:
        add("pending", f"最后是一条待核实线索：{say(short(r['title'], 40))}。这条还没有对照官网核实，信息可能不全，请自己确认后再操作。",
            [{"title": r["title"], "url": r.get("source_url") or r.get("official_url"), "path": f"deals/x/{r['id']}.html"}])

    add("outro", "以上就是本期 AI 羊毛电台。文字稿和每条的官方链接都在网站的电台页面。本站不收费、不代领，"
                 "不会索要账号密码和验证码。我们下期见。")
    return {"segments": segs}


def synth(segs: list[dict], out_mp3: Path) -> float:
    import numpy as np
    import sherpa_onnx
    d = Path(os.environ.get("RADIO_MODEL_DIR", str(Path.home() / "radio" / "kokoro-multi-lang-v1_1")))
    lex = ",".join(str(d / f) for f in ("lexicon-us-en.txt", "lexicon-zh.txt") if (d / f).exists())
    fsts = ",".join(str(d / f) for f in ("date-zh.fst", "phone-zh.fst", "number-zh.fst") if (d / f).exists())
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(d / "model.onnx"), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"),
                data_dir=str(d / "espeak-ng-data"), dict_dir=str(d / "dict") if (d / "dict").exists() else "", lexicon=lex),
            num_threads=int(os.environ.get("RADIO_THREADS", "2")), provider="cpu"),
        rule_fsts=fsts, max_num_sentences=1)
    tts = sherpa_onnx.OfflineTts(cfg)
    sid = int(os.environ.get("RADIO_SID", "3"))
    speed = float(os.environ.get("RADIO_SPEED", "1.05"))
    pcs, t = [], 0.0
    gap = np.zeros(int(SR * 0.45), dtype=np.float32)
    lead = np.zeros(int(SR * 0.3), dtype=np.float32)
    pcs.append(lead); t += len(lead) / SR
    for s in segs:
        a = tts.generate(s["text"], sid=sid, speed=speed)
        x = np.asarray(a.samples, dtype=np.float32)
        s["start"] = round(t, 2)
        pcs.append(x); t += len(x) / SR
        s["end"] = round(t, 2)
        pcs.append(gap); t += len(gap) / SR
    y = np.concatenate(pcs)
    # loudness: scale speech RMS to about -18 dBFS, then hard-limit peaks
    rms = float(np.sqrt(np.mean(y[np.abs(y) > 1e-4] ** 2))) if np.any(np.abs(y) > 1e-4) else 0.1
    y = np.clip(y * (0.126 / max(rms, 1e-3)), -0.97, 0.97)
    pcm = (y * 32767).astype("<i2").tobytes()
    try:
        import lameenc
        enc = lameenc.Encoder()
        enc.set_bit_rate(48); enc.set_in_sample_rate(SR); enc.set_channels(1); enc.set_quality(2)
        out_mp3.write_bytes(enc.encode(pcm) + enc.flush())
    except ImportError:
        with tempfile.TemporaryDirectory() as td:
            w = Path(td) / "a.wav"
            with wave.open(str(w), "wb") as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(SR); f.writeframes(pcm)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(w), "-ac", "1", "-c:a", "libmp3lame", "-b:a", "48k", str(out_mp3)], check=True)
    return round(t, 1)


def gh(method: str, url: str, body=None, data: bytes | None = None, ctype="application/json"):
    tok = (os.environ.get("GH_TOKEN") or "").strip() or (Path.home() / ".gh_pages_token").read_text().strip()
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": "aiym168-radio"}
    if body is not None:
        data = json.dumps(body).encode(); ctype = "application/json"
    if data is not None:
        h["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            t = r.read()
            return r.status, (json.loads(t) if t else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:300]}


def upload(mp3: Path, tag: str, name: str) -> str:
    api = f"https://api.github.com/repos/{REPO}"
    st, rel = gh("GET", f"{api}/releases/tags/{tag}")
    if st != 200:
        st, rel = gh("POST", f"{api}/releases", {"tag_name": tag, "name": f"AI 羊毛电台 {tag[6:]}", "target_commitish": "main",
                                                  "body": "AI 羊毛电台音频存档（程序自动生成）。收听：https://aiym168.github.io/radio/", "draft": False, "prerelease": False})
        if st not in (200, 201):
            raise RuntimeError(f"release create {st} {rel}")
    for a in rel.get("assets") or []:
        if a.get("name") == name:
            gh("DELETE", f"{api}/releases/assets/{a['id']}")
    up = rel["upload_url"].split("{")[0] + f"?name={name}"
    st, a = gh("POST", up, data=mp3.read_bytes(), ctype="audio/mpeg")
    if st not in (200, 201):
        raise RuntimeError(f"asset upload {st} {a}")
    return a["browser_download_url"]


def main() -> int:
    now = datetime.now(TZ)
    edition = os.environ.get("RADIO_EDITION") or ("am" if now.hour < 14 else "pm")
    ep_id = f"{now:%Y%m%d}-{edition}"
    sc = build_script(now, edition)
    ep = {"id": ep_id, "date": now.strftime("%Y-%m-%d"), "edition": edition,
          "title": f"{now.month}月{now.day}日 {'早报' if edition == 'am' else '晚报'}",
          "created_at": now.isoformat(timespec="seconds"), "segments": sc["segments"],
          "voice": "Kokoro v1.1 zf_001（离线合成）", "generator": "程序根据本站已收录数据自动生成，无人工撰稿"}
    if os.environ.get("RADIO_DRY") == "1":
        print(json.dumps(ep, ensure_ascii=False, indent=1)); return 0
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / f"radio-{ep_id}.mp3"
        ep["duration_s"] = synth(ep["segments"], mp3)
        ep["bytes"] = mp3.stat().st_size
        ep["audio_url"] = upload(mp3, f"radio-{now:%Y-%m}", mp3.name)
    db = j(EPS, {"episodes": []})
    eps = [e for e in db.get("episodes") or [] if e.get("id") != ep_id]
    eps.insert(0, ep)
    EPS.parent.mkdir(parents=True, exist_ok=True)
    EPS.write_text(json.dumps({"updated_at": now.isoformat(timespec="seconds"), "episodes": eps[:KEEP]}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[radio] {ep_id} {ep['duration_s']}s {ep['bytes']}B -> {ep['audio_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
