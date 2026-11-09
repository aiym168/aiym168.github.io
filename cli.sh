#!/usr/bin/env bash
# AI大模型免费资源导航 — curl-friendly CLI (no Node required)
# Usage (download → inspect → run):
#   curl -fsSLo ai168.sh https://aiym168.github.io/cli.sh && less ai168.sh && bash ai168.sh list
set -euo pipefail
BASE="${AI168_API:-https://aiym168.github.io}"
BASE="${BASE%/}"
LIMIT=20
MODULE=""
KW=""
ID=""
JSON_EP="api/meta.json"
CMD=""
POS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="${2:-20}"; shift 2 ;;
    --limit=*) LIMIT="${1#*=}"; shift ;;
    --api) BASE="${2%/}"; shift 2 ;;
    --api=*) BASE="${1#*=}"; BASE="${BASE%/}"; shift ;;
    -h|--help|help) CMD=help; shift ;;
    *) POS+=("$1"); shift ;;
  esac
done

if [[ -z "$CMD" ]]; then
  CMD="${POS[0]:-list}"
  POS=("${POS[@]:1}")
fi

get() { curl -fsSL -A "ai168-cli.sh/1.0" "$1"; }
hdr() { printf '\n\033[1;36m%s\033[0m \033[2m(%s)\033[0m\n' "$1" "$2"; }

case "$CMD" in
  help)
    cat << H
ai168 curl CLI — ${BASE}
  list [module] [--limit N]
  search <kw> [--limit N]
  hot | github [--limit N]
  open <id>
  json [api/meta.json]
  meta
H
    ;;
  meta)
    get "$BASE/api/meta.json" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("name"), d.get("updated_at_label"));print(d.get("counts"))'
    ;;
  json)
    ep="${POS[0]:-$JSON_EP}"
    [[ "$ep" == */* ]] || ep="api/${ep}.json"
    get "$BASE/$ep"
    ;;
  list)
    MODULE="${POS[0]:-}"
    if [[ -n "$MODULE" ]]; then
      data=$(get "$BASE/api/${MODULE}.json")
      title=$(printf '%s' "$data" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("title") or "")')
    else
      data=$(get "$BASE/api/latest.json")
      title="latest"
    fi
    hdr "$title" "limit $LIMIT"
    printf '%s' "$data" | LIMIT="$LIMIT" python3 -c 'import json,os,sys
d=json.load(sys.stdin)
items=(d.get("items") or [])[:int(os.environ.get("LIMIT","20"))]
print(f"{chr(35):<3} {"ID":<18} TITLE")
print("-"*70)
for i,it in enumerate(items,1):
    print(f"{i:<3} {str(it.get("id") or "")[:18]:<18} {str(it.get("title") or it.get("name") or "")[:60]}")
'
    ;;
  search)
    KW="${POS[*]:-}"
    [[ -n "$KW" ]] || { echo "search requires keyword"; exit 1; }
    hdr "search $KW" "limit $LIMIT"
    get "$BASE/api/latest.json" | KW="$KW" LIMIT="$LIMIT" python3 -c 'import json,os,sys
kw=os.environ["KW"].lower()
items=json.load(sys.stdin).get("items") or []
hit=[it for it in items if kw in f"{it.get("title","")} {it.get("summary","")} {it.get("category","")}".lower()]
hit=hit[:int(os.environ.get("LIMIT","20"))]
print(f"{chr(35):<3} {"ID":<18} TITLE")
for i,it in enumerate(hit,1):
    print(f"{i:<3} {str(it.get("id") or "")[:18]:<18} {str(it.get("title") or "")[:60]}")
'
    ;;
  hot|github)
    path=$([[ "$CMD" == hot ]] && echo api/hot.json || echo api/github-hot.json)
    hdr "$CMD" "limit $LIMIT"
    get "$BASE/$path" | LIMIT="$LIMIT" python3 -c 'import json,os,sys
items=(json.load(sys.stdin).get("items") or [])[:int(os.environ.get("LIMIT","20"))]
print(f"{chr(35):<3} {"ID":<18} TITLE")
for i,it in enumerate(items,1):
    print(f"{i:<3} {str(it.get("id") or "")[:18]:<18} {str(it.get("title") or it.get("name") or "")[:60]}")
'
    ;;
  open)
    ID="${POS[0]:-}"
    [[ -n "$ID" ]] || { echo "open requires id"; exit 1; }
    url=$(get "$BASE/api/latest.json" | ID="$ID" python3 -c 'import json,os,sys
items=json.load(sys.stdin).get("items") or []
i=os.environ["ID"]
hit=next((x for x in items if str(x.get("id"))==i or i in str(x.get("id"))),None)
print((hit or {}).get("url") or "")')
    [[ -n "$url" ]] || { echo "not found"; exit 1; }
    echo "$url"
    if command -v xdg-open >/dev/null; then xdg-open "$url" >/dev/null 2>&1 || true
    elif command -v open >/dev/null; then open "$url" >/dev/null 2>&1 || true
    fi
    ;;
  *)
    echo "Unknown command: $CMD (try help)"; exit 1 ;;
esac
