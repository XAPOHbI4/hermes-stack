#!/usr/bin/env bash
# leak_scan.sh <path> — READ-ONLY privacy/secret scan. Emits PRIVACY_RECEIPT.
# NEVER prints secret values: only type + masked prefix. Safe before any
# public-safe export (repo push, shared file, etc.).
#
# Status: BLOCKED (hard secrets) / NEEDS_REDACTION (instance/PII) / PASS.
set -uo pipefail
TARGET="${1:-.}"
[ -e "$TARGET" ] || { echo "leak_scan: path not found: $TARGET" >&2; exit 2; }

# grep over target, excluding VCS/venv/binaries noise
GREP=(grep -rInE --binary-files=without-match
      --exclude-dir=.git --exclude-dir=venv --exclude-dir=node_modules --exclude-dir=__pycache__)

mask() { sed -E 's/(.{4})[^[:space:]]*/\1…[REDACTED]/g'; }
hits() { "${GREP[@]}" "$1" "$TARGET" 2>/dev/null; }      # file:line:match
count() { hits "$1" | wc -l; }
samples() { "${GREP[@]}" -oh "$1" "$TARGET" 2>/dev/null | sort -u | head -3 | mask; }

# --- HARD secrets (=> BLOCKED) ---
declare -A HARD=(
  [openai_key]='sk-[A-Za-z0-9]{20,}'
  [telegram_bot_token]='[0-9]{6,}:[A-Za-z0-9_-]{30,}'
  [google_api_key]='AIza[0-9A-Za-z_-]{30,}'
  [google_oauth]='ya29\.[A-Za-z0-9_-]{20,}'
  [slack_token]='xox[baprs]-[A-Za-z0-9-]{10,}'
  [notion_token]='(ntn_|secret_)[A-Za-z0-9]{20,}'
  [private_key]='-----BEGIN [A-Z ]*PRIVATE KEY'
  [jwt]='eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'
  [aws_key]='AKIA[0-9A-Z]{16}'
)
# --- MEDIUM: instance-specific / PII (=> NEEDS_REDACTION) ---
declare -A MED=(
  [home_path]='(/root/|/home/[a-z]+/|C:\\\\Users\\\\)'
  [email]='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
  [ipv4]='\b([0-9]{1,3}\.){3}[0-9]{1,3}\b'
  [long_id]='[-]?[0-9]{9,}'
  [secret_file_ref]='(auth\.json|\.credentials|\.env\b|cookies|id_rsa|id_ed25519)'
)

BLOCK=0; REDACT=0
echo "PRIVACY_RECEIPT"
echo "Target: $TARGET"
echo "Time:   $(date -u +%FT%TZ)"
echo ""
echo "== HARD secrets (block publication) =="
for k in "${!HARD[@]}"; do
  c=$(count "${HARD[$k]}")
  if [ "$c" -gt 0 ]; then BLOCK=$((BLOCK+c)); echo "  [HIT] $k ×$c"; samples "${HARD[$k]}" | sed 's/^/        /'; fi
done
[ "$BLOCK" -eq 0 ] && echo "  none"
echo ""
echo "== MEDIUM: instance / PII (review before sharing) =="
for k in "${!MED[@]}"; do
  c=$(count "${MED[$k]}")
  if [ "$c" -gt 0 ]; then REDACT=$((REDACT+c)); echo "  [hit] $k ×$c"; fi
done
[ "$REDACT" -eq 0 ] && echo "  none"
echo ""
if   [ "$BLOCK"  -gt 0 ]; then STATUS="BLOCKED — hard secrets present, do NOT publish"
elif [ "$REDACT" -gt 0 ]; then STATUS="NEEDS_REDACTION — instance/PII present, review"
else                          STATUS="PASS — no secrets/PII patterns found"; fi
echo "Status: $STATUS"
echo "Note: only masked prefixes shown; values never printed."
[ "$BLOCK" -gt 0 ] && exit 1 || exit 0
