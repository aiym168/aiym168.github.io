"""Anonymous board ingest — runs in GitHub Actions (no server, no account).

Browser → (RSA-OAEP + AES-GCM encrypted envelope) → public relay ntfy.sh topic (12h cache)
→ this script polls the relay, decrypts with BOARD_PRIVATE_KEY (repo secret), verifies
honeypot / time / proof-of-work / rate limits, runs board.filter (strict, default reject),
and only then stores accepted messages in data/board/messages.json and publishes
api/board.json. Rejected text is never written anywhere; only a receipt code (by random cid).

Hide a message: add its id (e.g. M-7F3A2C) to data/board/hidden.txt, or run the
"Board ingest" workflow manually with input hide=M-7F3A2C.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from board.filter import check_post, REASONS, DEPS_OK  # noqa: E402

CFG = json.loads((ROOT / "board" / "config.json").read_text(encoding="utf-8"))
DATA = ROOT / "data" / "board"
API = ROOT / "api"
TZ = timezone(timedelta(hours=8))
STORE = DATA / "messages.json"
STATE = DATA / "state.json"
HIDDEN = DATA / "hidden.txt"
PUBLIC = API / "board.json"
RECEIPTS = API / "board_receipts.json"

FP_WINDOW = (600, 3)       # per fingerprint: max 3 accepted per 10 min
FP_DAY = 12                # per fingerprint: max 12 per 24h
GLOBAL_DAY = 300           # whole board: max 300 accepted per 24h
MIN_FILL_MS = 3000         # must spend ≥3s on the page before sending
PUBLISH_MAX = 400


def load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def dump(p: Path, obj, pretty=False):
    p.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, indent=1 if pretty else None, separators=None if pretty else (",", ":"))
    if p.exists() and p.read_text(encoding="utf-8") == txt + "\n":
        return False
    p.write_text(txt + "\n", encoding="utf-8")
    return True


def poll_relay(since: str):
    url = f"{CFG['relay']}/{CFG['topic']}/json?poll=1&since={since}"
    req = urllib.request.Request(url, headers={"User-Agent": "aiym168-board/1"})
    with urllib.request.urlopen(req, timeout=40) as r:
        body = r.read().decode("utf-8", "replace")
    out = []
    for line in body.splitlines():
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("event") == "message":
            out.append(m)
    return out


def _private_key():
    from cryptography.hazmat.primitives import serialization
    pem = os.environ.get("BOARD_PRIVATE_KEY", "").strip()
    if not pem:
        kf = os.environ.get("BOARD_PRIVATE_KEY_FILE")
        if kf and Path(kf).exists():
            pem = Path(kf).read_text()
    if not pem:
        return None
    return serialization.load_pem_private_key(pem.encode(), password=None)


def decrypt(envelope: str, key):
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    parts = envelope.strip().split(".")
    if len(parts) != 4 or parts[0] != "ab1":
        raise ValueError("bad envelope")
    ek, iv, ct = (base64.b64decode(x) for x in parts[1:])
    aes = key.decrypt(ek, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    pt = AESGCM(aes).decrypt(iv, ct, None)
    return json.loads(pt.decode("utf-8"))


def pow_ok(p: dict) -> bool:
    s = f"{p.get('cid')}|{p.get('t1')}|{p.get('text')}|{p.get('nick')}|{p.get('nonce')}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest().startswith(CFG.get("pow_prefix", "0000"))


def clean(s: str, n: int) -> str:
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", str(s or ""))
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s[:n]


def msg_id(cid: str, t: int) -> str:
    return "M-" + hashlib.sha256(f"{cid}{t}".encode()).hexdigest()[:6].upper()


def read_hidden():
    ids = set()
    if HIDDEN.exists():
        for line in HIDDEN.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                ids.add(line.split()[0].upper())
    return ids


def publish(store):
    hidden = read_hidden()
    vis = [m for m in store if m["id"] not in hidden and not m.get("hidden")]
    vis.sort(key=lambda m: m["t"], reverse=True)
    vis = vis[:PUBLISH_MAX]
    now = datetime.now(TZ)
    pub = {
        "updated": now.strftime("%Y-%m-%d %H:%M:%S Asia/Shanghai"),
        "count": len(vis),
        "messages": [
            {"id": m["id"], "nick": m["nick"], "text": m["text"], "t": m["t"],
             "time": datetime.fromtimestamp(m["t"], TZ).strftime("%Y-%m-%d %H:%M"), "hue": m.get("hue", 190)}
            for m in vis
        ],
    }
    return dump(PUBLIC, pub)


def main():
    hide_arg = (os.environ.get("BOARD_HIDE") or "").strip()
    if hide_arg:
        cur = HIDDEN.read_text(encoding="utf-8") if HIDDEN.exists() else ""
        for hid in re.split(r"[\s,，]+", hide_arg):
            if hid and hid.upper() not in read_hidden():
                cur += f"{hid.upper()}  # hidden via workflow {datetime.now(TZ):%Y-%m-%d %H:%M}\n"
        HIDDEN.write_text(cur, encoding="utf-8")

    store = load(STORE, [])
    state = load(STATE, {"last_id": "", "cids": [], "fp": {}, "texts": {}})
    receipts = load(RECEIPTS, {})
    now = int(time.time())
    key = _private_key()
    changed = False

    if key is None or not DEPS_OK:
        print("[board] missing private key or filter deps — skip ingest (fail closed)")
        msgs = []
    else:
        try:
            # always re-read the relay's whole 12h cache: ordering-safe, dedupe by cid below
            msgs = poll_relay("13h")
        except Exception as e:
            print("[board] relay poll failed:", e)
            msgs = []

    seen_list = list(state.get("cids", []))
    seen = set(seen_list)
    texts = state.get("texts", {})
    fplog = state.get("fp", {})
    day_count = sum(1 for m in store if now - m["t"] < 86400)
    stats = {"ok": 0}

    for m in msgs:
        state["last_id"] = m.get("id") or state.get("last_id")
        t = int(m.get("time") or now)
        try:
            p = decrypt(m.get("message", ""), key)
        except Exception:
            stats["bad"] = stats.get("bad", 0) + 1
            continue
        cid = str(p.get("cid") or "")[:32]
        if not re.fullmatch(r"[0-9a-f]{16,32}", cid) or cid in seen:
            continue
        seen.add(cid)
        seen_list.append(cid)

        def reject(code):
            receipts[cid] = {"s": "rej", "r": code, "msg": REASONS.get(code, "信号未通过审核。"), "t": t}
            stats[code] = stats.get(code, 0) + 1

        text = clean(p.get("text"), 400)
        nick = clean(p.get("nick"), 40)
        fp = re.sub(r"[^0-9a-f]", "", str(p.get("fp") or ""))[:32] or "anon"
        # --- anti-bot ---
        if str(p.get("hp") or ""):
            reject("bot"); continue
        try:
            t0, t1 = int(p.get("t0")), int(p.get("t1"))
        except Exception:
            reject("bot"); continue
        if t1 - t0 < MIN_FILL_MS or abs(t1 / 1000 - t) > 6 * 3600:
            reject("bot"); continue
        if not pow_ok(p):
            reject("bot"); continue
        # --- rate limits ---
        hist = [x for x in fplog.get(fp, []) if now - x < 86400]
        if len([x for x in hist if t - x < FP_WINDOW[0]]) >= FP_WINDOW[1] or len(hist) >= FP_DAY:
            reject("rate"); continue
        if day_count >= GLOBAL_DAY:
            reject("full"); continue
        # --- moderation (strict, server-side) ---
        v = check_post(text, nick)
        if not v.ok:
            reject(v.get("code") or "word"); continue
        th = hashlib.sha256(re.sub(r"\W+", "", text.lower()).encode()).hexdigest()[:16]
        if th in texts and now - texts[th] < 30 * 86400:
            reject("dup"); continue
        texts[th] = t
        hist.append(t)
        fplog[fp] = hist
        mid = msg_id(cid, t)
        hue = int(hashlib.md5(cid.encode()).hexdigest()[:4], 16) % 360
        store.append({"id": mid, "nick": nick or "匿名旅人", "text": text, "t": t, "hue": hue})
        receipts[cid] = {"s": "ok", "id": mid, "t": t}
        day_count += 1
        stats["ok"] += 1
        changed = True

    # housekeeping
    state["cids"] = seen_list[-3000:]
    state["texts"] = {k: v for k, v in texts.items() if now - v < 30 * 86400}
    state["fp"] = {k: [x for x in v if now - x < 86400] for k, v in fplog.items() if any(now - x < 86400 for x in v)}
    receipts = {k: v for k, v in receipts.items() if now - int(v.get("t", now)) < 3 * 86400}
    hidden = read_hidden()
    before = len(store)
    store = [m for m in store if m["id"] not in hidden]  # hidden = removed from the store too
    changed |= before != len(store)

    dump(STORE, store, pretty=True)
    dump(STATE, state)
    dump(RECEIPTS, receipts)
    publish(store)
    print("[board]", json.dumps({"polled": len(msgs), **stats, "stored": len(store)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
