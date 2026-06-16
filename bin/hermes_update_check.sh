#!/usr/bin/env bash
# Hermes upstream update WATCHER (read-only). Fetches upstream, and if it moved,
# asks Claude to summarize "what changed / what helps US / risks" and sends to
# Telegram. NEVER updates — `hermes update` stays a manual, approved action.
set -uo pipefail
REPO=/root/.hermes/hermes-agent
STATE=/root/hermes/runtime/logs/update-check-state.txt
LOG=/root/hermes/runtime/logs/hermes-update-check.log
PY=/root/.hermes/hermes-agent/venv/bin/python
RSEND=/root/hermes/runtime/bin/rich_send.py
CRUN=/root/hermes/runtime/bin/claude_run.py

cd "$REPO" || { echo "$(date -u +%FT%TZ) repo missing" >> "$LOG"; exit 1; }
git fetch origin --quiet 2>/dev/null || { echo "$(date -u +%FT%TZ) fetch failed" >> "$LOG"; exit 0; }
UB=origin/main; git rev-parse --verify -q "$UB" >/dev/null || UB=origin/master
HEAD_SHA=$(git rev-parse --short HEAD)
UP_SHA=$(git rev-parse --short "$UB")
N=$(git rev-list --count "HEAD..$UB" 2>/dev/null || echo 0)
echo "$(date -u +%FT%TZ) head=$HEAD_SHA up=$UP_SHA new=$N" >> "$LOG"

[ "${N:-0}" -eq 0 ] && { echo "  up to date" >> "$LOG"; exit 0; }
LAST=$(cat "$STATE" 2>/dev/null || echo "")
[ "$UP_SHA" = "$LAST" ] && { echo "  no new upstream since last report ($UP_SHA)" >> "$LOG"; exit 0; }

AREAS=$(git diff --dirstat=files,0 "HEAD..$UB" 2>/dev/null | sort -rn | head -15)
SUBJECTS=$(git log "HEAD..$UB" --oneline --no-merges 2>/dev/null | grep -iE 'feat|fix|perf|security|breaking|refactor' | head -60)

CTX="Мы запускаем Hermes-agent с нашим слоем сверху: оркестрация (engine-first decompose), Kanban + proof policy, Telegram rich-доставка, мониторинг лимитов Claude/Codex, петля обучения (eval+lessons), watchdog, per-profile smoke.
Текущая версия отстаёт на $N коммитов (HEAD $HEAD_SHA → upstream $UP_SHA).

Изменённые области (dirstat):
$AREAS

Заметные коммиты:
$SUBJECTS"

PROMPT="По этим upstream-изменениям Hermes дай кратко по-русски, markdown с заголовками: (1) 5-8 самых заметных изменений, релевантных НАШЕЙ системе (оркестрация, kanban/proof, telegram rich, мониторинг/лимиты, память, skills, gateway, security); (2) что из этого реально улучшит нас и почему; (3) риски/возможный breaking при апдейте. НЕ рекомендуй авто-апдейт — решение за человеком. Уложись примерно в 3000 символов, без воды, но раздел про риски НЕ обрезай."

SUMMARY=$(printf '%s' "$CTX" | HERMES_HOME=/root/hermes/runtime timeout 230 "$PY" "$CRUN" --model sonnet --attempts 1 --timeout 200 "$PROMPT" 2>/dev/null)
if [ -z "$SUMMARY" ] || printf '%s' "$SUMMARY" | grep -q '^BLOCK'; then
  SUMMARY="_(AI-анализ недоступен — сырой список заметных коммитов)_"$'\n'"$(printf '%s' "$SUBJECTS" | head -30)"
fi

MSG="🛰 *Hermes update доступен* — мы на \`$HEAD_SHA\`, upstream \`$UP_SHA\` (+$N коммитов)"$'\n'"_Это уведомление, НЕ апдейт. Обновление — только вручную с approval._"$'\n\n'"$SUMMARY"
# no hard truncation — rich_send.py splits long content into (k/n) parts

ENV=/root/.hermes/profiles/orchestrator/.env
[ -f "$ENV" ] && . "$ENV"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT="${TELEGRAM_ALLOWED_USER_IDS:-${TELEGRAM_HOME_CHANNEL:-}}"; export CHAT_ID="${CHAT%%,*}"
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
  echo "  no token/chat to send" >> "$LOG"; exit 0
fi
RES=$(printf '%s' "$MSG" | "$PY" "$RSEND" 2>&1)
echo "$(date -u +%FT%TZ) send: $RES" >> "$LOG"
echo "$UP_SHA" > "$STATE"
exit 0
