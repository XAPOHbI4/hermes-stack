#!/usr/bin/env bash
# Weekly eval/quality digest -> Telegram as a NATIVE rich table (sendRichMessage,
# the same path the gateway uses). External systemd timer, gateway-independent.
set -uo pipefail
PY=/root/.hermes/hermes-agent/venv/bin/python
DIGEST=/root/hermes/runtime/bin/hermes_eval_digest.py
RSEND=/root/hermes/runtime/bin/rich_send.py
LOG=/root/hermes/runtime/logs/hermes-eval.log

# plain digest: for the log + threshold detection (machine SUMMARY line)
OUT=$("$PY" "$DIGEST" --days 7 2>&1)
echo "----- $(date -u +%FT%TZ) -----" >> "$LOG"
echo "$OUT" >> "$LOG"
gf=$(echo "$OUT" | grep '^SUMMARY' | grep -oE 'genuine_fail=[0-9]+' | cut -d= -f2)

ENV=/root/.hermes/profiles/orchestrator/.env
[ -f "$ENV" ] && . "$ENV"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT="${TELEGRAM_ALLOWED_USER_IDS:-${TELEGRAM_HOME_CHANNEL:-}}"
export CHAT_ID="${CHAT%%,*}"   # first id only
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
  echo "$(date -u +%FT%TZ) no token/chat to send" >> "$LOG"; exit 0
fi

# markdown digest (native table, no service line) -> rich sender
MD=$("$PY" "$DIGEST" --days 7 --md 2>/dev/null)
if [ "${gf:-0}" -gt 0 ]; then
  MD="⚠️ *Есть реальные провалы (${gf})*"$'\n\n'"$MD"
fi
RES=$(printf '%s' "$MD" | "$PY" "$RSEND" 2>&1)
echo "$(date -u +%FT%TZ) send: $RES" >> "$LOG"
exit 0
