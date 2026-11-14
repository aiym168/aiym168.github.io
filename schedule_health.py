#!/usr/bin/env python3
"""Schedule gap, takeover decision, and backup-server wake window.

GitHub's scheduler can drop a cron run without recording a failure. This module
is the shared decision for that case:

  * status data lists the scheduled slots that nothing covered
  * the backup server and the external keepalive both publish when public
    content is older than publish_after_min, unless a publish is already running
  * the wake window in engine/wake.json is checked so hibernate cannot land on
    the next wake

No network in selftest. `decide` (used by the keepalive workflow) does fetch
the public site and, when a token is present, the Actions run list. Tokens are
never printed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
WAKE_PATH = ROOT / "engine" / "wake.json"
WATCHDOG_PATH = ROOT / "data" / "watchdog.json"
TZ = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")
SITE = "https://aiym168.github.io"
REPO = os.environ.get("GITHUB_REPOSITORY", "aiym168/aiym168.github.io")
ACTIVE_STATES = {"queued", "in_progress", "waiting", "pending", "requested"}
# A run this long before a slot already covered that slot.
ENGINE_COVER = timedelta(minutes=50)
WATCHDOG_COVER = timedelta(minutes=25)
MISS_LOOKBACK = timedelta(hours=72)
MISS_CAP = 36


def load_wake() -> dict:
    try:
        data = json.loads(WAKE_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("cron", "20,50 * * * *")
    data.setdefault("tz", "Asia/Shanghai")
    data.setdefault("awake_for_s", 1200)
    data.setdefault("engine_minutes", [20, 50])
    data.setdefault("publish_after_min", 75)
    return data


WAKE = load_wake()
PUBLISH_AFTER_MIN = int(WAKE["publish_after_min"])
ENGINE_MINUTES = tuple(int(m) for m in WAKE["engine_minutes"])
AWAKE_FOR_S = int(WAKE["awake_for_s"])
WAKE_CRON = str(WAKE["cron"])


def parse_time(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # epoch milliseconds (box state) or seconds
        sec = float(value) / 1000.0 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(sec, TZ)
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(TZ)
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M Asia/Shanghai", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt).replace(tzinfo=TZ)
        except Exception:
            continue
    try:
        return datetime.strptime(text[:16], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except Exception:
        return None


def label(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M Asia/Shanghai")


def should_publish(content_age_min, active_runs=0, threshold: int | None = None, force: bool = False) -> bool:
    """True only for a real publish. Standby / heartbeat never reaches this."""
    try:
        if int(active_runs or 0) > 0:
            return False
    except (TypeError, ValueError):
        return False
    if force:
        return True
    if content_age_min is None:
        return False
    try:
        age = float(content_age_min)
    except (TypeError, ValueError):
        return False
    return age >= (PUBLISH_AFTER_MIN if threshold is None else threshold)


def count_active(runs, ignore_id=None) -> int:
    n = 0
    for run in runs or []:
        if ignore_id is not None and str(run.get("id")) == str(ignore_id):
            continue
        if run.get("status") in ACTIVE_STATES:
            n += 1
    return n


def _slots(start: datetime, end: datetime, minute: int, hour_ok) -> list[datetime]:
    if end <= start:
        return []
    cursor = (start.astimezone(TZ) - timedelta(hours=1)).replace(minute=minute, second=0, microsecond=0)
    out = []
    while cursor <= end.astimezone(TZ):
        if start < cursor <= end and hour_ok(cursor):
            out.append(cursor)
        cursor += timedelta(hours=1)
    return out


def missed_slots(last_success: datetime | None, now: datetime, minute: int, cover: timedelta, hour_ok=None) -> list[datetime]:
    """Scheduled times after the last success that this run did not cover."""
    hour_ok = hour_ok or (lambda _t: True)
    window_start = now - MISS_LOOKBACK
    if last_success is not None and last_success > window_start:
        window_start = last_success
    found = []
    for slot in _slots(window_start, now, minute, hour_ok):
        if last_success is not None and last_success >= slot - cover and last_success <= slot:
            continue
        if last_success is not None and slot <= last_success:
            continue
        found.append(slot)
    return found


def engine_a_misses(last_success: datetime | None, now: datetime) -> list[datetime]:
    hourly = missed_slots(last_success, now, 7, ENGINE_COVER)
    backup = missed_slots(
        last_success, now, 37, ENGINE_COVER,
        hour_ok=lambda t: t.astimezone(UTC).hour % 2 == 0,
    )
    return sorted(hourly + backup)


def watchdog_misses(last_success: datetime | None, now: datetime) -> list[datetime]:
    found = []
    for minute in (23, 53):
        found.extend(missed_slots(last_success, now, minute, WATCHDOG_COVER))
    return sorted(found)


def consecutive_hourly_misses(slots: list[datetime]) -> int:
    hourly = sorted(s for s in slots if s.astimezone(TZ).minute == 7)
    n = 0
    expect = None
    for slot in reversed(hourly):
        slot = slot.astimezone(TZ).replace(second=0, microsecond=0)
        if expect is None:
            n = 1
            expect = slot - timedelta(hours=1)
        elif slot == expect:
            n += 1
            expect = slot - timedelta(hours=1)
        else:
            break
    return n


def wake_windows(cron_minutes=None, awake_min: int | None = None, prewake: int = 1):
    """(gaps before the next wake, whether each engine minute sits inside a window, pipeline budget)."""
    minutes = list(cron_minutes if cron_minutes is not None else ENGINE_MINUTES)
    awake = AWAKE_FOR_S // 60 if awake_min is None else awake_min
    spans = []
    for hour in range(0, 4):
        for minute in minutes:
            wake = hour * 60 + minute - prewake
            spans.append((wake, wake + awake))
    spans.sort()
    gaps = [spans[i + 1][0] - spans[i][1] for i in range(len(spans) - 1)]
    inside = []
    for minute in minutes:
        point = 60 + minute  # engine starts on the cron minute of the second hour
        inside.append(any(start <= point < end for start, end in spans))
    # minutes of headroom after the engine minute before hibernate
    budgets = []
    for minute in minutes:
        point = 60 + minute
        for start, end in spans:
            if start <= point < end:
                budgets.append(end - point)
                break
    return gaps, inside, budgets


def first_check_age(content_at: datetime, minutes: tuple[int, ...], threshold: int, hours: int = 6):
    """Content age at the first minute-of-hour check that is old enough to publish."""
    cursor = content_at.astimezone(TZ).replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = content_at + timedelta(hours=hours)
    while cursor <= end:
        if cursor.minute in minutes:
            age = (cursor - content_at).total_seconds() / 60
            if age >= threshold:
                return age
        cursor += timedelta(minutes=1)
    return None


def _cap(slots: list[datetime]) -> list[str]:
    shown = slots[-MISS_CAP:]
    return [label(s) for s in shown]


def summarize_from(now: datetime, content_at: datetime | None, engine_a_at: datetime | None,
                   watchdog_at: datetime | None, external_at: datetime | None,
                   watchdog_source: str) -> dict:
    content_age = None if content_at is None else int((now - content_at).total_seconds() // 60)
    a_slots = engine_a_misses(engine_a_at, now)
    w_slots = watchdog_misses(watchdog_at, now)
    stale = content_age is not None and content_age >= PUBLISH_AFTER_MIN
    return {
        "content_at": content_at.isoformat(timespec="seconds") if content_at else None,
        "content_age_min": content_age,
        "publish_after_min": PUBLISH_AFTER_MIN,
        "stale": stale,
        "takeover_due": bool(stale),
        "engine_a": {
            "last_run_at": engine_a_at.isoformat(timespec="seconds") if engine_a_at else None,
            "gap_min": None if engine_a_at is None else int((now - engine_a_at).total_seconds() // 60),
            "missed_slots": _cap(a_slots),
            "missed_count": len(a_slots),
            "consecutive_hourly_misses": consecutive_hourly_misses(a_slots),
        },
        "watchdog": {
            "last_run_at": watchdog_at.isoformat(timespec="seconds") if watchdog_at else None,
            "gap_min": None if watchdog_at is None else int((now - watchdog_at).total_seconds() // 60),
            "missed_slots": _cap(w_slots),
            "missed_count": len(w_slots),
            "source": watchdog_source,
        },
        "external_ping": {
            "last_run_at": external_at.isoformat(timespec="seconds") if external_at else None,
            "interval_min": 15,
        },
        "backup_wake": {
            "cron": WAKE_CRON,
            "tz": WAKE["tz"],
            "awake_for_s": AWAKE_FOR_S,
            "engine_minutes": list(ENGINE_MINUTES),
        },
    }


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def summarize(now: datetime | None = None, root: Path | None = None) -> dict:
    root = root or ROOT
    now = now or datetime.now(TZ)
    meta = _read(root / "api" / "meta.json")
    engine_a = _read(root / "data" / "engine_a.json")
    mark = _read(root / "data" / "watchdog.json")
    box = _read(root / "data" / "box_state.json")
    content_at = parse_time(meta.get("generated_at") or meta.get("generated_at_label"))
    engine_a_at = parse_time(engine_a.get("last_run_at"))
    watchdog_at = parse_time(mark.get("watchdog_last_run_at"))
    source = "marker" if watchdog_at else "unknown"
    if watchdog_at is None:
        watchdog_at = parse_time(box.get("checked_at_ms") or box.get("checked_at_label"))
        if watchdog_at is not None:
            source = "box-state"
    external_at = parse_time(mark.get("external_last_run_at"))
    result = summarize_from(now, content_at, engine_a_at, watchdog_at, external_at, source)
    gap = mark.get("last_watchdog_gap")
    if isinstance(gap, dict) and gap.get("missed_count"):
        result["watchdog"]["last_gap"] = gap
    return result


def mark(source: str, root: Path | None = None) -> dict:
    root = root or ROOT
    path = root / "data" / "watchdog.json"
    prev = _read(path)
    now = datetime.now(TZ)
    iso = now.isoformat(timespec="seconds")
    text = label(now)
    if source == "external-ping":
        prev["external_last_run_at"] = iso
        prev["external_last_run_label"] = text
    else:
        # Record the hole before this run overwrites the timestamp, otherwise
        # a watchdog that was gone for hours looks like it never missed.
        previous = parse_time(prev.get("watchdog_last_run_at"))
        if previous is not None:
            missed = watchdog_misses(previous, now)
            if missed:
                prev["last_watchdog_gap"] = {
                    "detected_at": iso,
                    "previous_run_at": previous.isoformat(timespec="seconds"),
                    "gap_min": int((now - previous).total_seconds() // 60),
                    "missed_slots": _cap(missed),
                    "missed_count": len(missed),
                }
        prev["watchdog_last_run_at"] = iso
        prev["watchdog_last_run_label"] = text
        prev["watchdog_source"] = source
    prev["updated_at"] = iso
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[schedule] marked {source} {text}")
    return prev


def _tokens() -> list[str]:
    found = []
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_TOKEN_ALT"):
        value = (os.environ.get(name) or "").strip()
        if value and value not in found:
            found.append(value)
    path = Path.home() / ".gh_pages_token"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value and value not in found:
            found.append(value)
    return found


def _github_runs(workflow: str) -> list[dict]:
    last_error = "no token"
    for token in _tokens():
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/runs?per_page=10",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "aiym168-keepalive",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode() or "{}")
            return body.get("workflow_runs") or []
        except Exception as exc:  # noqa: BLE001
            last_error = type(exc).__name__
    if last_error != "no token":
        print(f"[schedule] could not list {workflow} runs ({last_error})")
    return []


def active_publishers() -> int:
    me = os.environ.get("GITHUB_RUN_ID")
    runs = []
    for workflow in ("update.yml", "keepalive.yml"):
        runs.extend(_github_runs(workflow))
    return count_active(runs, ignore_id=me)


def live_content_age(now: datetime) -> tuple[datetime | None, int | None]:
    url = f"{SITE}/api/meta.json?t={int(now.timestamp())}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aiym168-keepalive", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            meta = json.loads(resp.read().decode() or "{}")
        when = parse_time(meta.get("generated_at") or meta.get("generated_at_label"))
        if when is not None:
            return when, int((now - when).total_seconds() // 60)
    except Exception as exc:  # noqa: BLE001
        print(f"[schedule] live meta unavailable ({type(exc).__name__})")
    local = parse_time(_read(ROOT / "api" / "meta.json").get("generated_at"))
    if local is None:
        return None, None
    return local, int((now - local).total_seconds() // 60)


def maybe_sync_box_timer() -> None:
    """Install the repo's timer on the backup server.

    The shell engine copies itself to /tmp before git sync, so the first run
    after a pull still executes the old script. status.py is imported after the
    sync, which makes this the hook that sees the new schedule on that run.
    GitHub Actions has no ~/.gh_pages_token and sets GITHUB_ACTIONS.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("SKIP_TIMER_SYNC") == "1":
        return
    if not (Path.home() / ".gh_pages_token").exists():
        return
    script = ROOT / "engine" / "install_box.sh"
    if not script.exists():
        return
    try:
        subprocess.run(["bash", str(script)], check=False, timeout=180)
    except Exception as exc:  # noqa: BLE001
        print(f"[schedule] timer sync skipped ({type(exc).__name__})")


def _write_output(publish: bool, age) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"publish={'1' if publish else '0'}\n")
        fh.write("content_age_min=\n" if age is None else f"content_age_min={int(age)}\n")


def refresh_internal(root: Path | None = None) -> None:
    """Update schedule_health inside the internal status file. Does not touch public pages."""
    root = root or ROOT
    path = root / "data" / "_internal_status.json"
    data = _read(path)
    now = datetime.now(TZ)
    # Drop a recorded hole once content is current again and nothing is still missed.
    marker = root / "data" / "watchdog.json"
    stored = _read(marker)
    preview = summarize(now, root)
    if stored.get("last_watchdog_gap") and not preview["stale"] and not preview["engine_a"]["missed_count"]:
        stored.pop("last_watchdog_gap", None)
        marker.write_text(json.dumps(stored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data["schedule_health"] = summarize(now, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    health = data["schedule_health"]
    print(
        f"[schedule] age={health.get('content_age_min')} stale={health.get('stale')} "
        f"engine_misses={health.get('engine_a', {}).get('missed_count')} "
        f"watchdog_misses={health.get('watchdog', {}).get('missed_count')}"
    )


def decide() -> int:
    now = datetime.now(TZ)
    mark("external-ping")
    _content_at, age = live_content_age(now)
    active = active_publishers()
    force = os.environ.get("KEEPALIVE_FORCE", "").strip() in ("1", "true", "True")
    publish = should_publish(age if age is not None else 99999, active, force=force)
    # Unknown age (site and local meta both missing) still publishes: a silent
    # scheduler gap plus a failed read should not wait another hour. An active
    # run suppresses it.
    if age is None and active:
        publish = False
    _write_output(publish, age)
    print(f"[keepalive] content_age={age if age is not None else 'unknown'} active={active} publish={int(publish)}")
    return 0


def publish_needed(argv: list[str]) -> int:
    age = None
    active = 0
    force = False
    if "--content-age" in argv:
        raw = argv[argv.index("--content-age") + 1]
        age = None if raw in ("", "none", "None") else float(raw)
    if "--active-runs" in argv:
        active = int(argv[argv.index("--active-runs") + 1])
    if "--force" in argv:
        force = True
    return 0 if should_publish(age, active, force=force) else 1


def selftest() -> int:
    content = datetime(2026, 11, 14, 18, 4, tzinfo=TZ)
    now = datetime(2026, 11, 14, 20, 30, tzinfo=TZ)
    last_engine = datetime(2026, 11, 14, 18, 4, tzinfo=TZ)
    last_watch = datetime(2026, 11, 14, 16, 19, tzinfo=TZ)
    errors = []

    def check(name, cond):
        if not cond:
            errors.append(name)

    check("fresh does not publish", not should_publish(10, 0))
    check("threshold publishes", should_publish(PUBLISH_AFTER_MIN, 0))
    check("just under threshold waits", not should_publish(PUBLISH_AFTER_MIN - 1, 0))
    check("active run blocks publish", not should_publish(200, 1))
    check("force publishes when idle", should_publish(1, 0, force=True))
    check("force still waits for a running publish", not should_publish(1, 3, force=True))
    check("ignore own run", count_active(
        [{"id": 5, "status": "in_progress"}, {"id": 9, "status": "in_progress"}], ignore_id=5) == 1)
    check("completed is not active", count_active([{"id": 1, "status": "completed"}]) == 0)

    box_age = first_check_age(content, ENGINE_MINUTES, PUBLISH_AFTER_MIN)
    old_age = first_check_age(content, (25,), 90)
    one_wake = first_check_age(content, (50,), PUBLISH_AFTER_MIN)
    check("box recovers within 120 min", box_age is not None and box_age <= 120)
    check("old :25 / 90 min policy misses 120", old_age is not None and old_age > 120)
    check("one surviving wake still within 120", one_wake is not None and one_wake <= 120)
    check("external worst case within 120", PUBLISH_AFTER_MIN + 15 + 15 <= 120)

    gaps, inside, budgets = wake_windows()
    check("wake gaps at least 8 min", bool(gaps) and min(gaps) >= 8)
    check("engine minutes inside awake window", all(inside))
    check("15 min pipeline fits before hibernate", bool(budgets) and min(budgets) >= 15)

    slots = engine_a_misses(last_engine, now)
    hourly = [label(s) for s in slots if s.minute == 7]
    check("two hourly misses visible", "2026-11-14 19:07 Asia/Shanghai" in hourly and "2026-11-14 20:07 Asia/Shanghai" in hourly)
    check("nearby slot after a success is not a miss", "2026-11-14 18:07 Asia/Shanghai" not in hourly)
    check("consecutive hourly misses", consecutive_hourly_misses(slots) >= 2)
    wslots = [label(s) for s in watchdog_misses(last_watch, now)]
    check("watchdog gap is visible", len(wslots) >= 4 and wslots[0].startswith("2026-11-14 16:53"))

    spec = json.loads(WAKE_PATH.read_text(encoding="utf-8"))
    guard = (ROOT / "engine" / "simular" / "box_guard.mjs").read_text(encoding="utf-8")
    check("guard reads wake.json", "wake.json" in guard)
    check("wake cron is two offsets", spec["cron"] == "20,50 * * * *" and spec["awake_for_s"] == 1200)
    install = (ROOT / "engine" / "install_box.sh").read_text(encoding="utf-8")
    check("installer asks schedule_health for minutes", "timer-minutes" in install)
    check("resume timer runs on boot", "OnBootSec=45s" in install and install.count("Persistent=true") >= 2)

    summary = summarize_from(now, content, last_engine, last_watch, None, "box-state")
    check("summary stale", summary["stale"] is True and summary["content_age_min"] == 146)
    check("summary lists misses", summary["engine_a"]["consecutive_hourly_misses"] >= 2)
    check("standby is not this decision", should_publish(0, 0) is False)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "data").mkdir()
        (root / "api").mkdir()
        old = datetime.now(TZ) - timedelta(hours=4)
        (root / "data" / "watchdog.json").write_text(
            json.dumps({"watchdog_last_run_at": old.isoformat(timespec="seconds")}), encoding="utf-8")
        mark("github-watchdog", root)
        saved = json.loads((root / "data" / "watchdog.json").read_text(encoding="utf-8"))
        check("gap survives the run that ends it", saved.get("last_watchdog_gap", {}).get("missed_count", 0) >= 4)
        check("first run does not invent a gap", "last_watchdog_gap" not in mark("github-watchdog", Path(tempfile.mkdtemp())))

    if errors:
        print("[selftest] FAIL")
        for name in errors:
            print(" -", name)
        return 1
    print(
        "[selftest] ok"
        f" box_age={box_age:.0f}min"
        f" one_wake={one_wake:.0f}min"
        f" old_policy={old_age:.0f}min"
        f" wake_gap={min(gaps)}min"
        f" hourly_misses={consecutive_hourly_misses(slots)}"
        f" watchdog_misses={len(wslots)}"
    )
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "selftest"
    if cmd == "selftest":
        return selftest()
    if cmd == "timer-minutes":
        print(",".join(str(m) for m in ENGINE_MINUTES))
        return 0
    if cmd == "wake-cron":
        print(WAKE_CRON)
        return 0
    if cmd == "awake-for":
        print(AWAKE_FOR_S)
        return 0
    if cmd == "publish-needed":
        return publish_needed(argv)
    if cmd == "mark":
        who = "github-watchdog"
        if "--who" in argv:
            who = argv[argv.index("--who") + 1]
        mark(who)
        return 0
    if cmd == "refresh":
        refresh_internal()
        return 0
    if cmd == "decide":
        return decide()
    if cmd == "show":
        print(json.dumps(summarize(), ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
