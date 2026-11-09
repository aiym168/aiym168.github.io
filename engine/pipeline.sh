#!/usr/bin/env bash
# Shared self-healing pipeline used by BOTH engines:
#   Engine A = GitHub Actions (.github/workflows/update.yml)
#   Engine B = Simular cloud server (engine/engine_b.sh)
# env: ENGINE=A|B  ENGINE_MODE=scheduled|takeover|forced|dispatch|push
#      FETCH=1 (0 = build only)  FORCE_X=1  RUN_URL=...
set -uo pipefail
cd "$(dirname "$0")/.."
ENGINE="${ENGINE:-A}"; FETCH="${FETCH:-1}"
log(){ echo "[pipeline:$ENGINE] $*"; }

# 1) snapshot last good publish tree
rm -rf .last_good && mkdir -p .last_good
for p in index.html 404.html feed.xml cli.sh fx.css fx.js robots.txt sitemap.xml sitemap.txt sitemap_index.xml; do
  [ -e "$p" ] && cp -a "$p" .last_good/
done
for d in api m c item archives vendor deals data; do [ -d "$d" ] && cp -a "$d" .last_good/; done
log "snapshot ready"

if [ "$FETCH" = "1" ]; then
  # 2) X (every 3h UTC, or forced) with health registry
  H=$((10#$(date -u +%H)))
  if [ "${FORCE_X:-0}" = "1" ] || [ $((H % 3)) -eq 0 ]; then
    if python3 selfheal.py should-skip X; then
      log "X auto-skipped (backoff)"
    else
      if timeout 600 python3 fetch_x.py; then
        kept=$(python3 -c "import json;print(json.load(open('data/auto/x_fetch_status.json')).get('kept',0))" 2>/dev/null || echo 0)
        if [ "${kept:-0}" -gt 0 ]; then python3 selfheal.py record X ok "$kept"; else python3 selfheal.py record X fail 0 "0 kept"; fi
      else
        python3 selfheal.py record X fail 0 "fetch_x exit $?"; log "[heal] fetch_x failed — keep previous X data"
      fi
    fi
  else
    log "X skip this hour (3h cadence)"
  fi
  # 3) daily self-discovery + dead-link pruning (gated inside to ~once/20h)
  timeout 900 python3 discover.py || log "[heal] discover failed — continue"
  # 4) main sources (per-source health, translator rotation inside)
  timeout 1500 python3 fetch_auto.py || log "[heal] fetch_auto exit $? — continue with previous data"
  # 4b) global deals: official APIs/feeds + re-verify curated offers + dedupe/expire/archive (keeps previous data on failure)
  timeout 900 python3 deals_collect.py || log "[heal] deals_collect exit $? — keep previous deals data"
  # 4c) LLM API price board: public pricing APIs (keeps previous prices on failure)
  timeout 300 python3 apiprice_collect.py || log "[heal] apiprice_collect exit $? — keep previous prices"
  timeout 900 python3 prune.py || log "[heal] prune failed — continue"
fi

# 5) build
RESULT=ok
if ! python3 build.py; then log "[heal] build failed"; RESULT=failed; fi
# 6) health check, rollback to last good on failure (incl. abnormal shrink)
if [ "$RESULT" = "failed" ] || ! python3 health_check.py; then
  log "[alive] health check failed — restoring last good build"
  for p in index.html 404.html feed.xml cli.sh fx.css fx.js robots.txt sitemap.xml sitemap.txt sitemap_index.xml; do
    [ -e ".last_good/$p" ] && cp -a ".last_good/$p" ./
  done
  for d in api m c item archives vendor deals; do
    if [ -d ".last_good/$d" ]; then rm -rf "$d"; cp -a ".last_good/$d" ./; fi
  done
  # keep source-health/discovery knowledge, restore content data
  cp -a data/sources_health.json /tmp/_sh.json 2>/dev/null || true
  [ -d .last_good/data ] && cp -a .last_good/data/. data/
  cp -a /tmp/_sh.json data/sources_health.json 2>/dev/null || true
  if python3 health_check.py; then RESULT=rolled_back; else log "[alive] restored tree still bad"; RESULT=failed; fi
fi
# 7) status page + engine marker, heartbeat, optional Baidu push
RUN_RESULT="$RESULT" python3 status.py || log "status page failed"
python3 heartbeat.py || true
[ "$ENGINE" = "A" ] && { python3 baidu_push.py || true; }
python3 indexnow_push.py || true
rm -rf .last_good __pycache__
log "result=$RESULT"
echo "$RESULT" > /tmp/pipeline_result_$ENGINE
[ "$RESULT" = "failed" ] && exit 1
exit 0
