#!/usr/bin/env bash
# Hermes-stack provisioner — lays our customization layer over a STOCK Hermes install.
# Idempotent. Run as root on the target machine AFTER stock Hermes is installed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HHOME="${HERMES_PROFILES_HOME:-/root/.hermes}"
PROFILES="$HHOME/profiles"
RUNTIME="${HERMES_RUNTIME:-/root/hermes/runtime}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

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

# 1b. semantic memory (isolated fastembed venv — torch-free; powers mi_search + memory-ingest)
MI="$RUNTIME/memory-index"
mkdir -p "$MI" "$HHOME/scripts"
cp "$HERE/bin/memory_index.py" "$MI/memory_index.py"
cp "$HERE/bin/memory_hygiene.py" "$HHOME/scripts/memory_hygiene.py"
if command -v python3 >/dev/null 2>&1; then
  [ -x "$MI/.venv/bin/python" ] || python3 -m venv "$MI/.venv"
  "$MI/.venv/bin/python" -m pip install -q --upgrade pip
  # --only-binary avoids building tokenizers from source (puccinialin/Rust toolchain)
  "$MI/.venv/bin/pip" install -q --only-binary=:all: "fastembed<0.5" "numpy<3" \
    && echo "  [ok] memory venv -> $MI/.venv" \
    || echo "  [warn] fastembed install failed (network/wheels) — semantic search off until fixed"
  # build orchestrator references/wiki index (downloads MiniLM-multilingual once, then offline)
  "$MI/.venv/bin/python" "$MI/memory_index.py" rebuild-atomic >/dev/null 2>&1 \
    && echo "  [ok] orchestrator memory index built" \
    || echo "  [skip] build later: $MI/.venv/bin/python $MI/memory_index.py rebuild-atomic"
else
  echo "  [skip] no python3 — semantic memory not provisioned"
fi

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

# 4. systemd units (our timers) — auto-detect ALL shipped *.timer (no stale list)
if command -v systemctl >/dev/null 2>&1; then
  cp "$HERE"/systemd/* "$SYSTEMD_DIR/"
  systemctl daemon-reload
  for unit in "$HERE"/systemd/*.timer; do
    t=$(basename "$unit")
    systemctl enable --now "$t" >/dev/null 2>&1 && echo "  [ok] $t" || echo "  [skip] $t"
  done
else
  echo "  [skip] no systemd — copy $HERE/systemd/* and wire timers/cron manually for your init system"
fi

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
