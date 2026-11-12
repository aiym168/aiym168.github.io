#!/usr/bin/env bash
# Server engine — runs on a Simular cloud server (cron/systemd, hourly).
# Same script on every server; ~/.engine.conf (outside the repo) picks the identity:
#   ENGINE_ID=B  ENGINE_MINUTE=25   (first server, default)
#   ENGINE_ID=C  ENGINE_MINUTE=55   (second server: third line of defence, only takes over
#                                    when neither GitHub nor the first server has updated the site)
# 1. mutual watchdog: re-enable / re-dispatch GitHub engine A if needed
# 2. if the live site is stale (> STALE_MIN) or FORCE=1: run the full pipeline and push
#    otherwise: standby, refresh its "seen" marker every few hours
# Never prints tokens. Logs: ~/engine/logs (7-day rotation).
set -uo pipefail
# run from a private copy: the repo checkout (and this file) is reset during the run
if [ -z "${ENGINE_B_COPY:-}" ]; then cp -f "$0" /tmp/engine_b_run.sh; ENGINE_B_COPY=1 exec bash /tmp/engine_b_run.sh "$@"; fi
E="$HOME/engine"
[ -r "$HOME/.engine.conf" ] && . "$HOME/.engine.conf"
EID="${ENGINE_ID:-B}"; eid="$(printf '%s' "$EID" | tr 'A-Z' 'a-z')"
# cron/systemd start with a bare env: load the box's network proxy + CA settings
for f in /etc/profile.d/cocoonbox-proxy.sh /etc/profile.d/cocoonbox-mise.sh; do [ -r "$f" ] && . "$f" 2>/dev/null; done
if [ -z "${https_proxy:-}" ] && (exec 3<>/dev/tcp/127.0.0.1/3128) 2>/dev/null; then
  export http_proxy=http://127.0.0.1:3128 https_proxy=http://127.0.0.1:3128 HTTP_PROXY=http://127.0.0.1:3128 HTTPS_PROXY=http://127.0.0.1:3128
fi
export no_proxy="${no_proxy:-localhost,127.0.0.1,::1}" SSL_CERT_FILE="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}"
LOGDIR="$E/logs"; mkdir -p "$LOGDIR"
STALE_MIN="${STALE_MIN:-90}"
# second server: take over only if the live site is older than this (both others missed a slot)
C_LIVE_STALE_MIN="${C_LIVE_STALE_MIN:-75}"
C_PEER_STALE_MIN="${C_PEER_STALE_MIN:-150}"
SEEN_EVERY_MIN="${SEEN_EVERY_MIN:-55}"
REPO="aiym168/aiym168.github.io"
LOG="$LOGDIR/engine_${eid}-$(TZ=Asia/Shanghai date +%F).log"
find "$LOGDIR" -name 'engine_*-*.log' -mtime +7 -delete 2>/dev/null || true
[ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 5000000 ] && mv -f "$LOG" "$LOG.1"
exec 9>"$E/.lock"
if ! flock -n 9; then echo "[engine-$eid] another run holds the lock — exit"; exit 0; fi
main() {
export TZ=Asia/Shanghai
echo "===== [engine-$eid] start $(date '+%F %T %Z') force=${FORCE:-0} ====="

T="$(cat "$HOME/.gh_pages_token" 2>/dev/null)"
[ -z "$T" ] && { echo "[engine-$eid] no token file"; exit 2; }
export GH_TOKEN="$T" GITHUB_TOKEN="$T"
cd "$E" || exit 2
git remote set-url origin "https://x-access-token:${T}@github.com/${REPO}.git"
git config user.name "laohe-bot"; git config user.email "9499758-wq@users.noreply.github.com"

sync_main(){
  for i in 1 2 3; do
    git fetch -q origin main && git reset -q --hard origin/main && git clean -qfd -e logs -e .lock && return 0
    sleep $((i*10))
  done; return 1
}
push_retry(){ # $1 = commit message ; $2 = rerun cmd on conflict
  for i in 1 2 3 4 5; do
    if git push -q origin HEAD:main; then echo "[engine-$eid] pushed (try $i)"; return 0; fi
    echo "[engine-$eid] push rejected — pull --rebase (try $i)"
    git fetch -q origin main
    if ! git pull -q --rebase -X ours origin main; then
      git rebase --abort 2>/dev/null || true
      sync_main || return 1
      eval "$2"
      git add -A; git reset -q HEAD -- .last_good __pycache__ 2>/dev/null || true
      git diff --cached --quiet && { echo "[engine-$eid] nothing left after resync"; return 0; }
      git commit -q -m "$1 (resynced)"
    fi
    sleep $((i*5))
  done; return 1
}

sync_main || { echo "[engine-$eid] git sync failed"; exit 3; }

# --- mutual watchdog (also re-enables / re-dispatches engine A) ---
W="$(python3 engine/gh_watch.py heal --who "服务器引擎 $EID" 2>>"$LOG")"
read -r LIVE_AGE A_AGE ACTIONS B_AGE <<<"$(printf '%s' "$W" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: d={}
la=d.get("live_age_min"); aa=(d.get("last_success") or {}).get("age_min"); ba=(d.get("engine_b") or {}).get("age_min")
print(la if la is not None else 99999, aa if aa is not None else 99999, len(d.get("actions") or []), ba if ba is not None else 99999)')"
echo "[engine-$eid] live_age=${LIVE_AGE}min engineA_last_success=${A_AGE}min peerB_seen=${B_AGE}min watchdog_actions=${ACTIONS}"

MODE=standby
if [ "${FORCE:-0}" = "1" ]; then MODE=forced
elif [ "$EID" = "B" ]; then
  if [ "$LIVE_AGE" -gt "$STALE_MIN" ] || [ "$A_AGE" -gt "$STALE_MIN" ]; then MODE=takeover; fi
else
  # third line: only when the live site itself is stale, or both other engines look dead
  if [ "$LIVE_AGE" -gt "$C_LIVE_STALE_MIN" ]; then MODE=takeover
  elif [ "$A_AGE" -gt "$STALE_MIN" ] && [ "$B_AGE" -gt "$C_PEER_STALE_MIN" ]; then MODE=takeover; fi
fi
echo "[engine-$eid] mode=$MODE"

if [ "$MODE" = "standby" ]; then
  # daily self-evolution step if no engine did it yet today (only data/evolve/* changes; model diary when ~/.llm_env exists)
  timeout 600 python3 evolve.py daily || echo "[engine-$eid] evolve failed — skipped"
  git add data/evolve 2>/dev/null; git add data/auto/llm_cache.json 2>/dev/null || true
  if ! git diff --cached --quiet; then
    git commit -q -m "evolve $(date "+%F %H:%M")"
    push_retry "evolve" "timeout 600 python3 evolve.py daily" || echo "[engine-$eid] evolve push failed"
  fi
  SEEN_AGE=$(EIDL=$eid python3 -c '
import json,datetime
try:
  import os; d=json.load(open("data/engine_"+os.environ["EIDL"]+".json")); s=max(filter(None,[d.get("last_run_at"),d.get("standby_seen_at")]))
  print(int((datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(s)).total_seconds()//60))
except Exception: print(99999)')
  if [ "$SEEN_AGE" -lt "$SEEN_EVERY_MIN" ]; then echo "[engine-$eid] standby, marker fresh (${SEEN_AGE}min) — no commit"; exit 0; fi
  ENGINE=$EID ENGINE_SEEN_ONLY=1 python3 status.py
  git add data/engine_$eid.json api/status.json m/status.html
  git diff --cached --quiet && exit 0
  git commit -q -m "update $(date "+%F %H:%M")"
  push_retry "update" "ENGINE=$EID ENGINE_SEEN_ONLY=1 python3 status.py"
  exit $?
fi

RUN_CMD="ENGINE=$EID ENGINE_MODE=$MODE RUN_URL='https://github.com/${REPO}/commits/main' FORCE_X=\${FORCE_X:-0} timeout 2700 bash engine/pipeline.sh"
eval "$RUN_CMD"; rc=$?
echo "[engine-$eid] pipeline rc=$rc"
rm -rf .last_good __pycache__
git add -A; git reset -q HEAD -- .last_good __pycache__ logs .lock 2>/dev/null || true
if git diff --cached --quiet; then echo "[engine-$eid] no changes"; exit 0; fi
MSG="auto update $(date "+%F %H:%M")"
git commit -q -m "$MSG"
push_retry "$MSG" "ENGINE=$EID ENGINE_MODE=$MODE FETCH=0 bash engine/pipeline.sh"
rc=$?
echo "===== [engine-$eid] end $(date '+%F %T %Z') rc=$rc ====="
exit $rc
}

# pipe through the masker + log inside the same process group so nothing is lost when systemd ends the unit
main "$@" 2>&1 | sed -u -E 's/(ghp_|github_pat_|gho_|ghs_)[A-Za-z0-9_]+/\1***/g' | tee -a "$LOG"
exit "${PIPESTATUS[0]}"
