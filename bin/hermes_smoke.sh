#!/usr/bin/env bash
# Per-profile smoke: verify each ENABLED profile actually RESPONDS (not merely
# "gateway active"). Catches "active but brain-dead" (bad model/provider/skill),
# which gateway-status and dead-provider audit can miss. Each smoke = 1 real LLM
# call, so this runs on a DAILY timer; result is cached for the LLM-free healthcheck.
set -uo pipefail
HA=/root/.hermes/hermes-agent
STATE=/root/hermes/runtime/logs/smoke-state.txt
TOK='SMOKE_OK'

mapfile -t PROFILES < <(ls /etc/systemd/system/multi-user.target.wants/hermes-gateway@*.service 2>/dev/null \
  | sed -E 's#.*hermes-gateway@(.+)\.service#\1#' | sort -u)
[ "${#PROFILES[@]}" -eq 0 ] && PROFILES=(orchestrator)

: > "$STATE.tmp"
for p in "${PROFILES[@]}"; do
  out=$(cd "$HA" && timeout 90 ./venv/bin/python -m hermes_cli.main --profile "$p" \
        chat -Q --source smoke -q "Ответь ровно одним словом: $TOK" 2>/dev/null | tr -d '\r')
  if printf '%s' "$out" | grep -q "$TOK"; then
    printf '%s OK\n' "$p" >> "$STATE.tmp"
  else
    printf '%s FAIL\n' "$p" >> "$STATE.tmp"
  fi
done
printf 'ts=%s\n' "$(date -u +%FT%TZ)" >> "$STATE.tmp"
mv "$STATE.tmp" "$STATE"
cat "$STATE"
