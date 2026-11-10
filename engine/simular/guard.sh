#!/usr/bin/env bash
# Keeps both Simular servers awake (runs inside the GitHub watchdog every 30 min).
#   server 1: secret SIMULAR_BOX_KEY  box cb-6ad4209d8372  heartbeat data/engine_b.json  state data/box_state.json
#   server 2: secret SIMULAR_KEY_2    box cb-e24d45c9724d  heartbeat data/engine_c.json  state data/box_state_2.json
# Each: wake if not running / heartbeat > 2h / forced, re-assert hourly wake schedule, log incidents.
set -uo pipefail
(cd engine/simular && npm i --silent --no-audit --no-fund)
COMMIT=0; ADD=""; SUMMARY=""
one() { # label key boxid statefile agekey
  local label="$1" key="$2" box="$3" st="$4" agek="$5"
  if [ -z "$key" ]; then echo "[$label] no key secret — skip"; return 0; fi
  echo "::add-mask::$key"
  cp -f "$st" /tmp/box_prev.json 2>/dev/null || echo '{}' > /tmp/box_prev.json
  local age; age=$(python3 -c "import json;d=json.load(open('/tmp/watch.json'));a=(d.get('$agek') or {}).get('age_min');print('' if a is None else a)" 2>/dev/null)
  if [ -n "$age" ]; then export ENGINE_B_AGE_MIN="$age"; else unset ENGINE_B_AGE_MIN; fi
  SIMULAR_BOX_KEY="$key" BOX_ID="$box" OUT="$st" node engine/simular/box_guard.mjs | tee /tmp/box.json
  LABEL="$label" python3 - <<'PY'
import json, subprocess, os
cur = json.load(open("/tmp/box.json"))
prev = json.load(open("/tmp/box_prev.json"))
woke = bool(cur.get("actions")) or bool(cur.get("wake_reasons"))
changed = cur.get("state_after") != prev.get("state_after") or cur.get("error") != prev.get("error")
old = (cur.get("checked_at_ms", 0) - int(prev.get("checked_at_ms") or 0)) > 3 * 3600 * 1000
lab = os.environ["LABEL"]
if woke or cur.get("error"):
    why = "；".join(cur.get("wake_reasons") or []) or (cur.get("error") or "调度修复")
    detail = (f"服务器：{lab}\n\n唤醒前状态：{cur.get('state_before')}\n\n唤醒后状态：{cur.get('state_after')}（{cur.get('state_after_zh')}）\n\n"
              f"引擎心跳：{cur.get('engine_b_age_min')} 分钟前\n\n动作：{', '.join(cur.get('actions') or []) or '-'}\n\n"
              f"定时唤醒：{json.dumps(cur.get('wake_schedule'), ensure_ascii=False)}\n\n"
              f"运行记录：{os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}")
    subprocess.run(["python3", "engine/gh_watch.py", "incident", f"GitHub 看门狗唤醒{lab}：{why}", detail])
open("/tmp/box_commit", "w").write("1" if (woke or changed or old) else "0")
print(f"[{lab}] commit state:", woke or changed or old)
PY
  [ "$(cat /tmp/box_commit)" = "1" ] && { COMMIT=1; ADD="$ADD $st"; }
  SUMMARY="$SUMMARY\n### $label\n\`\`\`json\n$(cat /tmp/box.json)\n\`\`\`"
}
one "服务器 1" "${SIMULAR_BOX_KEY:-}" "cb-6ad4209d8372" data/box_state.json engine_b
one "服务器 2" "${SIMULAR_KEY_2:-}" "cb-e24d45c9724d" data/box_state_2.json engine_c
if [ "$COMMIT" = "1" ]; then
  git config user.name "laohe-bot"; git config user.email "9499758-wq@users.noreply.github.com"
  STATUS_MARK=0 python3 status.py || true
  git add $ADD api/status.json m/status.html data/_internal_status.json 2>/dev/null
  if ! git diff --cached --quiet; then
    git commit -q -m "status check $(TZ=Asia/Shanghai date '+%F %H:%M')"
    for i in 1 2 3 4 5; do
      git push -q origin HEAD:main && break
      git fetch -q origin main && git rebase -q origin/main || { git rebase --abort; git reset -q --soft origin/main; git commit -q -m "status check (merged)"; }
      sleep $((i*4))
    done
  fi
fi
[ -n "${GITHUB_STEP_SUMMARY:-}" ] && printf "## 服务器守护%b\n" "$SUMMARY" >> "$GITHUB_STEP_SUMMARY"
exit 0
