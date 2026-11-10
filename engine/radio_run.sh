#!/usr/bin/env bash
# AI 羊毛电台 — runs on the second server at 08:30 / 20:30 Asia/Shanghai (systemd radio.timer + cron).
# Makes one episode (engine/radio_make.py), renders radio/ pages, commits only the radio files, pushes with retry.
set -uo pipefail
E="$HOME/engine"; LOGDIR="$E/logs"; mkdir -p "$LOGDIR"
for f in /etc/profile.d/cocoonbox-proxy.sh /etc/profile.d/cocoonbox-mise.sh; do [ -r "$f" ] && . "$f" 2>/dev/null; done
if [ -z "${https_proxy:-}" ] && (exec 3<>/dev/tcp/127.0.0.1/3128) 2>/dev/null; then
  export http_proxy=http://127.0.0.1:3128 https_proxy=http://127.0.0.1:3128 HTTP_PROXY=http://127.0.0.1:3128 HTTPS_PROXY=http://127.0.0.1:3128
fi
export no_proxy="${no_proxy:-localhost,127.0.0.1,::1}" SSL_CERT_FILE="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}" TZ=Asia/Shanghai
LOG="$LOGDIR/radio-$(date +%F).log"
find "$LOGDIR" -name 'radio-*.log' -mtime +14 -delete 2>/dev/null || true
PY="$HOME/radio/venv/bin/python"; [ -x "$PY" ] || PY=python3
main() {
  exec 9>"$E/.lock"
  # share the engine lock (wait up to 40 min for an hourly run to finish)
  flock -w 2400 9 || { echo "[radio] lock busy — skip"; exit 0; }
  echo "===== [radio] start $(date '+%F %T %Z') ====="
  T="$(cat "$HOME/.gh_pages_token" 2>/dev/null)"; [ -z "$T" ] && { echo "[radio] no token"; exit 2; }
  export GH_TOKEN="$T"
  cd "$E" || exit 2
  git remote set-url origin "https://x-access-token:${T}@github.com/aiym168/aiym168.github.io.git"
  git config user.name "laohe-bot"; git config user.email "9499758-wq@users.noreply.github.com"
  sync(){ for i in 1 2 3; do git fetch -q origin main && git reset -q --hard origin/main && git clean -qfd -e logs -e .lock -e .tick && return 0; sleep $((i*10)); done; return 1; }
  sync || { echo "[radio] git sync failed"; exit 3; }
  ED="${RADIO_EDITION:-}"; [ -z "$ED" ] && { [ "$(date +%H)" -lt 14 ] && ED=am || ED=pm; }
  if [ "${FORCE:-0}" != "1" ] && python3 -c "import json,sys;d=json.load(open('data/radio/episodes.json'));sys.exit(0 if any(e['id']=='$(date +%Y%m%d)-$ED' for e in d.get('episodes',[])) else 1)" 2>/dev/null; then
    echo "[radio] episode $(date +%Y%m%d)-$ED already published — skip"; exit 0; fi
  ok=0
  for i in 1 2 3; do RADIO_EDITION=$ED timeout 1800 "$PY" engine/radio_make.py && { ok=1; break; }; echo "[radio] make failed (try $i)"; sleep $((i*30)); done
  [ $ok = 1 ] || exit 4
  cp -f data/radio/episodes.json /tmp/radio_eps.json
  python3 radio_build.py || { echo "[radio] page build failed"; exit 5; }
  git add data/radio radio api/radio.json
  git diff --cached --quiet && { echo "[radio] nothing to commit"; exit 0; }
  MSG="AI 羊毛电台 $(date '+%m-%d') $([ $ED = am ] && echo 早报 || echo 晚报)"
  git commit -q -m "$MSG"
  for i in 1 2 3 4 5; do
    if git push -q origin HEAD:main; then echo "[radio] pushed (try $i)"; echo "===== [radio] end ok ====="; return 0; fi
    echo "[radio] push rejected — resync (try $i)"
    sync || continue
    cp -f /tmp/radio_eps.json data/radio/episodes.json
    python3 radio_build.py && git add data/radio radio api/radio.json && git commit -q -m "$MSG" || true
    sleep $((i*5))
  done
  echo "[radio] push failed"; return 1
}
main "$@" 2>&1 | sed -u -E 's/(ghp_|github_pat_|gho_|ghs_)[A-Za-z0-9_]+/\1***/g' | tee -a "$LOG"
exit "${PIPESTATUS[0]}"
