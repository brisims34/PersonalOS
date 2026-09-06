#!/usr/bin/env bash
# Shared JSON field extraction for hooks.
#
# Hook payloads arrive as JSON on stdin. jq is preferred, but a protection hook
# that is disabled (or that blocks every tool call) because one binary is absent
# is worse than one that reaches for node or python instead. Callers that get a
# non-zero json_parser_ready should fail SAFE by asking the human, not by
# silently allowing and not by hard-denying with no way back.

_JSON_PARSER=""

_JSON_NODE_SCRIPT='let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{let v=JSON.parse(s);for(const k of process.argv[1].split("."))v=(v==null?undefined:v[k]);if(v!==undefined&&v!==null)process.stdout.write(String(v));}catch(e){process.exit(1);}});'

_JSON_PY_SCRIPT='import json,sys
try:
    v = json.load(sys.stdin)
    for k in sys.argv[1].split("."):
        v = v.get(k) if isinstance(v, dict) else None
    if v is not None:
        sys.stdout.write(v if isinstance(v, str) else str(v))
except Exception:
    sys.exit(1)'

# Probe candidates with a real parse; command -v alone would accept the
# Windows Store python3 stub, which exits non-zero on first use.
json_parser_ready() {
  [ -n "$_JSON_PARSER" ] && return 0
  if command -v jq >/dev/null 2>&1 && printf '{"a":"b"}' | jq -re '.a' >/dev/null 2>&1; then
    _JSON_PARSER="jq"; return 0
  fi
  if command -v node >/dev/null 2>&1 && printf '{"a":"b"}' | node -e "$_JSON_NODE_SCRIPT" a >/dev/null 2>&1; then
    _JSON_PARSER="node"; return 0
  fi
  local py
  for py in python python3; do
    if command -v "$py" >/dev/null 2>&1 && printf '{"a":"b"}' | "$py" -c "$_JSON_PY_SCRIPT" a >/dev/null 2>&1; then
      _JSON_PARSER="$py"; return 0
    fi
  done
  return 1
}

# json_field <json> <dotted.path> -> value on stdout, empty if absent.
json_field() {
  local json="$1" path="$2"
  json_parser_ready || return 1
  case "$_JSON_PARSER" in
    jq)   printf '%s' "$json" | jq -r --arg p "$path" 'getpath($p | split(".")) // empty' 2>/dev/null ;;
    node) printf '%s' "$json" | node -e "$_JSON_NODE_SCRIPT" "$path" 2>/dev/null ;;
    *)    printf '%s' "$json" | "$_JSON_PARSER" -c "$_JSON_PY_SCRIPT" "$path" 2>/dev/null ;;
  esac
}
