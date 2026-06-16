#!/usr/bin/env bash
# Hermes stack health check — READ-ONLY. Prints PASS / WARN lines.
# Usage: bash hermes_healthcheck.sh
set -uo pipefail
PY=/root/.hermes/hermes-agent/venv/bin/python
HM(){ "$PY" -m hermes_cli.main "$@"; }
ok(){ printf '  ✅ %s\n' "$1"; }
warn(){ printf '  ⚠️  %s\n' "$1"; ISSUES=$((ISSUES+1)); }
ISSUES=0

echo "=== Hermes health $(date -u +%FT%TZ) ==="

echo "[1] Enabled gateways (auto-detected) must be active"
mapfile -t ENABLED < <(ls /etc/systemd/system/multi-user.target.wants/hermes-gateway@*.service 2>/dev/null | xargs -r -n1 basename)
if [ "${#ENABLED[@]}" -eq 0 ]; then warn "no enabled hermes gateways found"; fi
for u in "${ENABLED[@]}"; do
  if systemctl is-active --quiet "$u"; then ok "$u active"
  else warn "$u enabled but NOT active"; fi
done

echo "[2] Watchdog timer"
if systemctl is-active --quiet kanban-watchdog.timer; then
  nxt=$(systemctl show -p NextElapseUSecRealtime --value kanban-watchdog.timer 2>/dev/null)
  ok "kanban-watchdog.timer active (next set)"
else warn "kanban-watchdog.timer NOT active"; fi

echo "[3] Kanban dispatcher / stuck cards (global, read-only)"
disp=$(HM --profile orchestrator kanban dispatch --dry-run --max 1 2>/dev/null)
crashed=$(echo "$disp" | grep -iE 'Crashed:' | grep -oE '[0-9]+' | head -1)
timedout=$(echo "$disp" | grep -iE 'Timed out:' | grep -oE '[0-9]+' | head -1)
stale=$(echo "$disp" | grep -iE 'Stale:' | grep -oE '[0-9]+' | head -1)
echo "    reclaim/crashed=${crashed:-?} timedout=${timedout:-?} stale=${stale:-?}"
if [ "${crashed:-0}" = "0" ] && [ "${timedout:-0}" = "0" ]; then ok "no crashed/timed-out cards"
else warn "crashed/timed-out cards present"; fi

echo "[4] Auth (subscription, no LLM call)"
[ -f /root/.claude/.credentials.json ] && ok "claude credentials present" || warn "claude credentials missing"
exp=$(/usr/bin/python3 -c "import json;print(json.load(open('/root/.claude/.credentials.json'))['claudeAiOauth']['expiresAt'])" 2>/dev/null)
[ -n "${exp:-}" ] && ok "claude oauth token (expiresAt=$exp)" || warn "cannot read claude token"
[ -f /root/.codex/auth.json ] && ok "codex auth present" || warn "codex auth missing"

echo "[5] Resources"
duse=$(df -h / | awk 'NR==2{print $5}' | tr -d '%')
[ "${duse:-100}" -lt 85 ] && ok "disk ${duse}% used" || warn "disk ${duse}% used (>85)"
mem=$(free -m | awk '/Mem:/{printf "%d", $7}')
[ "${mem:-0}" -gt 300 ] && ok "RAM available ${mem}Mi" || warn "RAM available ${mem}Mi low"

echo "[6] Recent gateway errors (1h)"
ELOG=$(journalctl -u hermes-gateway@orchestrator --since '1 hour ago' --no-pager 2>/dev/null | grep -iE 'ERROR|Traceback|crash|fatal')
errs=$(printf '%s\n' "$ELOG" | grep -c .)
if [ "${errs:-0}" -lt 5 ]; then ok "errors last 1h: ${errs}"
else
  warn "errors last 1h: ${errs} (>5)"
  # breakdown: top error patterns (dedup, normalized) so the alert is actionable
  printf '%s\n' "$ELOG" \
    | sed -E 's/.*python\[[0-9]+\]: //; s/[0-9]{4,}/N/g' \
    | sed -E 's/(.{72}).*/\1…/' \
    | sort | uniq -c | sort -rn | head -4 \
    | while read -r n msg; do printf '      ↳ %sx %s\n' "$n" "$msg"; done
  if printf '%s\n' "$ELOG" | grep -qiE 'TimedOut|Bad Gateway|Network Retry|reconnect'; then
    printf '      ↳ hint: похоже на транзиентный сетевой блип Telegram (шлюз сам переподключается, не падает)\n'
  fi
fi

echo "[7] Skill hygiene & model providers"
AUD=$("$PY" /root/hermes/runtime/bin/skill_audit.py 2>/dev/null)
col=$(echo "$AUD" | awk -F': ' '/^COLLISIONS:/{print $2}')
dead=$(echo "$AUD" | awk -F': ' '/^DEAD_PROVIDERS:/{print $2}')
[ "${col:-0}" -eq 0 ] && ok "no skill name collisions" || warn "skill name collisions: ${col} (run sweep)"
[ "${dead:-0}" -eq 0 ] && ok "no dead/xai-unauth providers" || warn "profiles on dead provider (xai/grok): ${dead}"

echo "[8] Routing tooling present"
for t in claude_architect.py claude_reviewer.py claude_run.py closure_gate.py; do
  [ -f "/root/hermes/runtime/bin/$t" ] && ok "$t" || warn "$t missing"
done

echo "[9] Subscription limits (Claude oauth)"
TOK=$("$PY" -c "import json;print(json.load(open('/root/.claude/.credentials.json'))['claudeAiOauth']['accessToken'])" 2>/dev/null)
if [ -n "${TOK:-}" ]; then
  U=$(curl -s --max-time 12 'https://api.anthropic.com/api/oauth/usage' -H "Authorization: Bearer $TOK" -H 'anthropic-beta: oauth-2025-04-20' 2>/dev/null)
  h5=$(echo "$U" | "$PY" -c "import sys,json;print(int(json.load(sys.stdin).get('five_hour',{}).get('utilization') or 0))" 2>/dev/null)
  d7=$(echo "$U" | "$PY" -c "import sys,json;print(int(json.load(sys.stdin).get('seven_day',{}).get('utilization') or 0))" 2>/dev/null)
  if [ "${h5:-0}" -lt 80 ] && [ "${d7:-0}" -lt 80 ]; then ok "Claude limits ok (5h ${h5:-?}%, 7d ${d7:-?}%)"
  else warn "Claude limits HIGH (5h ${h5:-?}%, 7d ${d7:-?}%) — risk of 429"; fi
else warn "cannot read claude token for usage"; fi

echo "[10] Subscription limits (Codex / ChatGPT)"
CX=$("$PY" /root/hermes/runtime/bin/codex_usage.py 2>/dev/null)
if [ -n "${CX:-}" ] && [ "$CX" != "NA" ]; then
  cp5=$(echo "$CX" | awk '{print $1}'); cs7=$(echo "$CX" | awk '{print $2}'); cage=$(echo "$CX" | awk '{print $3}')
  if [ "${cp5:-0}" -lt 80 ] && [ "${cs7:-0}" -lt 80 ]; then ok "Codex limits ok (5h ${cp5}%, 7d ${cs7}%, snapshot ${cage}m ago)"
  else warn "Codex limits HIGH (5h ${cp5}%, 7d ${cs7}%) — risk of throttle"; fi
else warn "cannot read codex usage (no recent session rollout)"; fi

echo "[11] Per-profile smoke (cached, daily hermes-smoke — active≠healthy)"
SM=/root/hermes/runtime/logs/smoke-state.txt
if [ -f "$SM" ]; then
  sfail=$(grep -c ' FAIL' "$SM")
  sts=$(grep '^ts=' "$SM" | cut -d= -f2)
  if [ "${sfail:-0}" -eq 0 ]; then ok "all profiles answered smoke (as of ${sts:-?})"
  else warn "profiles FAILING smoke: $(grep ' FAIL' "$SM" | awk '{print $1}' | tr '\n' ' ')(as of ${sts:-?})"; fi
else warn "no smoke state yet (hermes-smoke not run)"; fi

echo "=== RESULT: $([ $ISSUES -eq 0 ] && echo 'PASS — всё в норме' || echo "WARN — проблем: $ISSUES") ==="
exit 0
