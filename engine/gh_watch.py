#!/usr/bin/env python3
"""Mutual watchdog helpers (GitHub REST API, stdlib only).

Used by:
  * .github/workflows/watchdog.yml (Engine A side, every 30 min)
  * engine/engine_b.sh on the Simular servers (Engine B / C side, hourly)

Commands:
  check              print JSON: workflow states, last success age, live data age, engine B age
  heal [--who X]     enable disabled workflows, re-dispatch update.yml if failed/stale, log incident issue
Token: env GH_TOKEN / GITHUB_TOKEN, or file ~/.gh_pages_token. Never printed.
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = os.environ.get("GITHUB_REPOSITORY", "aiym168/aiym168.github.io")
API = "https://api.github.com"
SITE = "https://aiym168.github.io"
TZ = ZoneInfo("Asia/Shanghai")
MAIN_WF = "update.yml"
WATCHED = ["update.yml", "watchdog.yml"]
STALE_MIN = int(os.environ.get("STALE_MIN", "90"))
ISSUE_TITLE = "[看门狗] 自动更新故障记录"


def token() -> str:
    t = (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if not t:
        p = Path.home() / ".gh_pages_token"
        if p.exists():
            t = p.read_text().strip()
    return t


def tokens() -> list[str]:
    out = [token(), (os.environ.get("GH_TOKEN_ALT") or "").strip()]
    return [t for i, t in enumerate(out) if t and t not in out[:i]]


def req(method: str, path: str, body: dict | None = None, raw: bool = False):
    last = (-1, {"error": "no token"})
    for t in tokens():
        last = _req(method, path, body, raw, t)
        if last[0] not in (401, 403, 404):
            return last
    return last


def _req(method: str, path: str, body: dict | None, raw: bool, tok: str):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "aiym168-watchdog",
    })
    try:
        with urllib.request.urlopen(r, timeout=40) as resp:
            content = resp.read()
            if raw:
                return resp.status, content
            return resp.status, (json.loads(content) if content else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read()[:300].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        return -1, {"error": f"{type(e).__name__}: {e}"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def mins_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int((now() - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() // 60)
    except Exception:
        return None


def sh(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ).strftime("%Y-%m-%d %H:%M Asia/Shanghai")


def live_json(path: str) -> dict:
    try:
        r = urllib.request.Request(f"{SITE}/{path}?t={int(now().timestamp())}", headers={"User-Agent": "aiym168-watchdog", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(r, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


def raw_main(path: str) -> dict:
    st, body = req("GET", f"/repos/{REPO}/contents/{path}?ref=main", raw=False)
    if st == 200 and body.get("content"):
        import base64
        try:
            return json.loads(base64.b64decode(body["content"]))
        except Exception:
            return {}
    return {}


def check() -> dict:
    out: dict = {"checked_at": sh(now().isoformat()), "workflows": {}}
    for wf in WATCHED:
        st, body = req("GET", f"/repos/{REPO}/actions/workflows/{wf}")
        out["workflows"][wf] = body.get("state", f"http{st}") if st == 200 else f"http{st}"
    st, body = req("GET", f"/repos/{REPO}/actions/workflows/{MAIN_WF}/runs?per_page=15")
    runs = body.get("workflow_runs") or [] if st == 200 else []
    succ = next((r for r in runs if r.get("conclusion") == "success" and r.get("event") != "push"), None)
    latest_done = next((r for r in runs if r.get("status") == "completed"), None)
    active = [r for r in runs if r.get("status") in ("queued", "in_progress", "waiting", "pending", "requested")]
    out["last_success"] = {"at": sh(succ["updated_at"]) if succ else None, "age_min": mins_since(succ["updated_at"]) if succ else None,
                           "url": succ.get("html_url") if succ else None}
    out["latest_completed"] = {"conclusion": latest_done.get("conclusion") if latest_done else None,
                               "id": latest_done.get("id") if latest_done else None,
                               "url": latest_done.get("html_url") if latest_done else None,
                               "at": sh(latest_done.get("updated_at")) if latest_done else None}
    out["active_runs"] = len(active)
    meta = live_json("api/meta.json")
    gen = meta.get("generated_at_label") or ""
    try:
        gdt = datetime.strptime(gen[:16], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        out["live_age_min"] = int((now() - gdt).total_seconds() // 60)
    except Exception:
        out["live_age_min"] = None
    out["live_generated"] = gen
    b = raw_main("data/engine_b.json")
    seen = max(filter(None, [b.get("last_run_at"), b.get("standby_seen_at")]), default=None)
    out["engine_b"] = {"last_seen": seen, "age_min": mins_since(seen), "mode": b.get("mode"), "result": b.get("result")}
    c = raw_main("data/engine_c.json")
    seen_c = max(filter(None, [c.get("last_run_at"), c.get("standby_seen_at")]), default=None)
    out["engine_c"] = {"last_seen": seen_c, "age_min": mins_since(seen_c), "mode": c.get("mode"), "result": c.get("result")}
    return out


def failed_log_tail(run_id: int, lines: int = 60) -> str:
    st, body = req("GET", f"/repos/{REPO}/actions/runs/{run_id}/jobs")
    chunks = []
    for job in (body.get("jobs") or []) if st == 200 else []:
        if job.get("conclusion") not in ("failure", "timed_out", "cancelled"):
            continue
        bad = [s.get("name") for s in job.get("steps") or [] if s.get("conclusion") == "failure"]
        s2, content = req("GET", f"/repos/{REPO}/actions/jobs/{job['id']}/logs", raw=True)
        text = content.decode("utf-8", "replace") if isinstance(content, (bytes, bytearray)) else str(content)
        if text[:2] == "PK":
            try:
                z = zipfile.ZipFile(io.BytesIO(content)); text = "\n".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())
            except Exception:
                pass
        tail = "\n".join(text.splitlines()[-lines:])
        for pre in ("ghp_", "github_pat_", "gho_", "ghs_"):
            import re
            tail = re.sub(pre + r"[A-Za-z0-9_]+", pre + "***", tail)
        chunks.append(f"**Job:** {job.get('name')}  失败步骤: {', '.join(bad) or '-'}\n```\n{tail}\n```")
    return "\n\n".join(chunks) or "(无法获取日志)"


def incident(title_line: str, detail: str) -> None:
    st, body = req("GET", f"/repos/{REPO}/issues?state=open&labels=watchdog&per_page=10")
    issue = next((i for i in (body if isinstance(body, list) else []) if i.get("title") == ISSUE_TITLE), None)
    text = f"### {title_line}\n\n时间：{sh(now().isoformat())}\n\n{detail}"[:60000]
    if issue:
        st, _ = req("POST", f"/repos/{REPO}/issues/{issue['number']}/comments", {"body": text})
        print(f"[watchdog] incident comment -> issue #{issue['number']} http{st}", file=sys.stderr)
    else:
        st, b = req("POST", f"/repos/{REPO}/issues", {"title": ISSUE_TITLE, "body": "此 Issue 由看门狗自动维护，记录自动更新流程的故障与自愈动作，无需人工处理。\n\n" + text, "labels": ["watchdog"]})
        print(f"[watchdog] incident issue created http{st} #{b.get('number') if isinstance(b, dict) else '?'}", file=sys.stderr)


def heal(who: str) -> dict:
    s = check()
    actions = []
    for wf, state in s["workflows"].items():
        if state not in ("active",) and not state.startswith("http"):
            st, _ = req("PUT", f"/repos/{REPO}/actions/workflows/{wf}/enable")
            actions.append(f"enable {wf} (was {state}) -> http{st}")
    lc = s["latest_completed"]
    age = s["last_success"]["age_min"]
    failed = lc.get("conclusion") in ("failure", "timed_out", "startup_failure")
    stale = age is None or age > STALE_MIN
    disabled = any(v.startswith("disabled") for v in s["workflows"].values())
    if (failed or stale or disabled) and s["active_runs"] == 0:
        st, _ = req("POST", f"/repos/{REPO}/actions/workflows/{MAIN_WF}/dispatches", {"ref": "main"})
        actions.append(f"dispatch {MAIN_WF} -> http{st}")
    if actions:
        reason = []
        if disabled:
            reason.append("主流程被停用")
        if failed:
            reason.append(f"最近一次运行失败（{lc.get('url')}）")
        if stale:
            reason.append(f"距上次成功已 {age} 分钟（阈值 {STALE_MIN}）")
        detail = f"发现方：{who}\n\n原因：{'；'.join(reason) or '-'}\n\n自愈动作：\n" + "\n".join(f"- `{a}`" for a in actions)
        if failed and lc.get("id"):
            detail += "\n\n失败日志（末尾）：\n\n" + failed_log_tail(lc["id"])
        incident(f"{who} 自愈：{'；'.join(reason) or '状态异常'}", detail)
    s["actions"] = actions
    return s


def main(argv: list[str]) -> int:
    if not token():
        print("[watchdog] no token available"); return 2
    cmd = argv[1] if len(argv) > 1 else "check"
    who = "GitHub 看门狗"
    if "--who" in argv:
        who = argv[argv.index("--who") + 1]
    if cmd == "incident":
        incident(argv[2], argv[3] if len(argv) > 3 else "")
        return 0
    res = heal(who) if cmd == "heal" else check()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write("## 看门狗\n\n```json\n" + json.dumps(res, ensure_ascii=False, indent=1) + "\n```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
