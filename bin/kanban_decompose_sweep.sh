#!/usr/bin/env bash
# Auto-decompose: sweep the triage column of every board and break triaged
# tasks into specialist child-tasks (engine-level, reliable). Cheap no-op when
# no triage tasks. EXTERNAL systemd timer (survives gateway restarts).
set -uo pipefail
LOG=/root/hermes/runtime/logs/kanban-decompose.log
PY=/root/.hermes/hermes-agent/venv/bin/python
HM(){ "$PY" -m hermes_cli.main --profile orchestrator "$@"; }
ts(){ date -u +%FT%TZ; }

boards=$(HM kanban boards list 2>/dev/null | awk '{print $1}' | grep -E '^[a-z]' | grep -v '^SLUG$')
for b in $boards; do
  out=$(HM kanban --board "$b" decompose --all 2>/dev/null || true)
  if echo "$out" | grep -qiE 'Decomposed|children'; then
    echo "$(ts) [$b] $(echo "$out" | tr '\n' ' ' | sed 's/  */ /g')" >> "$LOG"
  fi
done
exit 0
