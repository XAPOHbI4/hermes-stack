#!/usr/bin/env bash
# Kanban grind watchdog — EXTERNAL (systemd timer), survives gateway restarts.
#
# Strategy:
#   - If the gateway is DOWN: restart it, then run ONE global recovery dispatch
#     (reclaims stale-lock cards + re-kicks ready ones across ALL boards).
#   - If the gateway is UP: do nothing. Its built-in dispatcher already runs
#     every 60s globally; a second dispatcher here would only risk double spawns.
set -uo pipefail

LOG=/root/hermes/runtime/logs/kanban-watchdog.log
PY=/root/.hermes/hermes-agent/venv/bin/python
PROFILE=orchestrator
MAX_SPAWN="${KANBAN_WATCHDOG_MAX:-5}"
ts() { date -u +%FT%TZ; }

if systemctl is-active --quiet "hermes-gateway@${PROFILE}"; then
  # healthy — native in-gateway dispatcher owns dispatch; nothing to do
  exit 0
fi

echo "$(ts) gateway@${PROFILE} DOWN -> restart" >> "$LOG"
systemctl restart "hermes-gateway@${PROFILE}" || echo "$(ts) restart FAILED" >> "$LOG"
sleep 8

# recovery: global reclaim + dispatch across all boards (idempotent: claimed cards skipped)
res=$("$PY" -m hermes_cli.main --profile "$PROFILE" kanban dispatch --max "$MAX_SPAWN" 2>>"$LOG" || true)
echo "$(ts) recovery dispatch: $(echo "$res" | tr '\n' ' ' | sed 's/  */ /g')" >> "$LOG"

exit 0
