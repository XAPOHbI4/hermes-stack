#!/usr/bin/env bash
# Hourly health auditor: run healthcheck, alert to Telegram ONLY on WARN.
# Silent on PASS (just logs). External systemd timer — independent of gateway.
set -uo pipefail

LOG=/root/hermes/runtime/logs/hermes-health.log
OUT=$(bash /root/hermes/runtime/bin/hermes_healthcheck.sh 2>&1)
echo "----- $(date -u +%FT%TZ) -----" >> "$LOG"
echo "$OUT" >> "$LOG"

# PASS -> stay silent
echo "$OUT" | grep -q 'RESULT: PASS' && exit 0

# WARN -> notify operator via orchestrator bot DM
ENV=/root/.hermes/profiles/orchestrator/.env
[ -f "$ENV" ] && . "$ENV"
TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT="${TELEGRAM_ALLOWED_USER_IDS:-${TELEGRAM_HOME_CHANNEL:-}}"
CHAT="${CHAT%%,*}"   # first id only
if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
  echo "$(date -u +%FT%TZ) WARN but no token/chat to alert" >> "$LOG"; exit 0
fi

# Include WARN lines, RESULT, and the indented "↳" breakdown lines so the
# alert says WHAT the problem is, not just a count.
MSG="⚠️ Hermes health: обнаружены проблемы"$'\n'"$(echo "$OUT" | grep -E 'RESULT:|⚠️|↳')"
curl -s --max-time 15 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${CHAT}" \
  --data-urlencode "text=${MSG}" \
  --data-urlencode "disable_web_page_preview=true" >/dev/null \
  && echo "$(date -u +%FT%TZ) alert sent" >> "$LOG" \
  || echo "$(date -u +%FT%TZ) alert send failed" >> "$LOG"
exit 0
