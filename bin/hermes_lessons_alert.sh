#!/usr/bin/env bash
# Weekly graduation-lessons -> Telegram (operator DM). External systemd timer.
# Runs the model-driven reflection (hermes_lessons.py), then sends the report.
set -uo pipefail
PY=/root/.hermes/hermes-agent/venv/bin/python
export HERMES_HOME=/root/hermes/runtime
LOG=/root/hermes/runtime/logs/hermes-lessons.log
REP=/root/hermes/runtime/reports/lessons-msg.md

echo "----- $(date -u +%FT%TZ) -----" >> "$LOG"
"$PY" /root/hermes/runtime/bin/hermes_lessons.py --days 7 >>"$LOG" 2>&1

[ -f "$REP" ] || { echo "no report produced" >> "$LOG"; exit 0; }

ENV=/root/.hermes/profiles/orchestrator/.env
[ -f "$ENV" ] && . "$ENV"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT="${TELEGRAM_ALLOWED_USER_IDS:-${TELEGRAM_HOME_CHANNEL:-}}"
export CHAT_ID="${CHAT%%,*}"   # first id only
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
  echo "no token/chat to send" >> "$LOG"; exit 0
fi

# Send as a native rich message so the model's markdown (## headers, **bold**,
# lists) renders properly instead of raw syntax. Telegram hard limit 4096.
RES=$(head -c 3900 "$REP" | "$PY" /root/hermes/runtime/bin/rich_send.py 2>&1)
echo "lessons send: $RES" >> "$LOG"
exit 0
