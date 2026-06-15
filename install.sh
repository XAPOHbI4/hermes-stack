#!/usr/bin/env bash
# Hermes-stack provisioner — lays our customization layer over a STOCK Hermes install.
# Idempotent. Run as root on the target machine AFTER stock Hermes is installed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HHOME="${HERMES_PROFILES_HOME:-/root/.hermes}"
PROFILES="$HHOME/profiles"
RUNTIME="${HERMES_RUNTIME:-/root/hermes/runtime}"

echo "== Hermes-stack provisioner =="

# 0. preconditions ----------------------------------------------------------
command -v hermes >/dev/null 2>&1 || {
  echo "ERROR: stock Hermes not found on PATH."
  echo "  First install the base:"
  echo "    git clone https://github.com/NousResearch/hermes-agent /root/.hermes/hermes-agent"
  echo "    cd /root/.hermes/hermes-agent && ./setup-hermes.sh"
  exit 1; }
[ -f "$HERE/.env" ] || { echo "ERROR: copy .env.example -> .env and fill it, then re-run."; exit 1; }
set -a; . "$HERE/.env"; set +a
: "${TG_HOME_CHAT:?set TG_HOME_CHAT in .env}"; : "${TG_OPERATOR_ID:?set TG_OPERATOR_ID in .env}"
: "${TG_COMPANY_GROUP:=$TG_HOME_CHAT}"

# 1. our runtime scripts ----------------------------------------------------
mkdir -p "$RUNTIME/bin" "$RUNTIME/logs"
cp "$HERE"/bin/* "$RUNTIME/bin/"
chmod +x "$RUNTIME"/bin/*.sh "$RUNTIME"/bin/*.py 2>/dev/null || true
echo "  [ok] scripts -> $RUNTIME/bin"

# 2. profile contracts (merge over existing; never wipe live state) ---------
for p in "$HERE"/profiles/*/; do
  name=$(basename "$p"); dst="$PROFILES/$name"; mkdir -p "$dst"
  cp -r "$p". "$dst/"
done
echo "  [ok] profile contracts -> $PROFILES ($(ls "$HERE"/profiles | wc -l) profiles)"

# 3. substitute instance placeholders + drop per-profile .env ---------------
while IFS= read -r f; do
  sed -i "s|__TG_HOME_CHAT__|${TG_HOME_CHAT}|g; s|__TG_COMPANY_GROUP__|${TG_COMPANY_GROUP}|g; s|__TG_OPERATOR_ID__|${TG_OPERATOR_ID}|g" "$f"
done < <(grep -rIl '__TG_' "$PROFILES" 2>/dev/null || true)
for p in "$PROFILES"/*/; do [ -d "$p" ] && cp "$HERE/.env" "$p/.env"; done
echo "  [ok] placeholders substituted, per-profile .env written"

# 4. systemd units (our timers) ---------------------------------------------
cp "$HERE"/systemd/* /etc/systemd/system/
systemctl daemon-reload
for t in hermes-health hermes-eval hermes-lessons kanban-decompose kanban-watchdog; do
  systemctl enable --now "$t.timer" >/dev/null 2>&1 && echo "  [ok] $t.timer" || echo "  [skip] $t.timer"
done

# 5. manual follow-ups ------------------------------------------------------
cat <<EOF

== provisioning done. MANUAL steps left (instance-specific) ==
1) Auth (NOT in this bundle — provision per instance):
     /root/.codex/auth.json        (codex login)
     /root/.claude/.credentials.json (claude login)
2) Crons: review crons.manifest.txt and re-create:
     hermes --profile <p> cron add ...
3) Start gateways:
     hermes --profile orchestrator gateway install
     systemctl enable --now hermes-gateway@orchestrator
4) Verify: bash $RUNTIME/bin/hermes_healthcheck.sh
EOF
