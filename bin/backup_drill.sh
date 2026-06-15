#!/usr/bin/env bash
# Scoped Hermes backup + restore DRILL. Backs up config/contracts/kanban/crons/
# auth/our-scripts/systemd-units (NOT skill bodies 7.2G, NOT venv). Then restores
# into an isolated /tmp dir and verifies integrity. Archive is meant to be pulled
# OFF-server and deleted here (zero server footprint).
set -uo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
ARCH=/root/hermes-backup-${TS}.tar.gz
LOG=/root/hermes/runtime/logs/backup-drill.log
TESTDIR=/tmp/restore-test-${TS}
PY=/root/.hermes/hermes-agent/venv/bin/python
{
echo "=== backup drill $TS ==="
tar czf "$ARCH" \
  --exclude='*/skills' --exclude='*/__pycache__' --exclude='*.pyc' --exclude='*.log' \
  /root/.hermes/profiles /root/.hermes/kanban \
  /root/hermes/runtime/bin /root/hermes/runtime/assets \
  /root/.codex/auth.json /root/.claude/.credentials.json \
  /etc/systemd/system/hermes-*.service /etc/systemd/system/hermes-*.timer \
  /etc/systemd/system/kanban-*.service /etc/systemd/system/kanban-*.timer 2>/dev/null
echo "archive: $(du -h "$ARCH" | cut -f1)  entries: $(tar tzf "$ARCH" | wc -l)"

mkdir -p "$TESTDIR"
tar xzf "$ARCH" -C "$TESTDIR" 2>/dev/null
echo "restored into $TESTDIR"

echo "-- kanban DBs open + integrity --"
ok=0; bad=0
for db in "$TESTDIR"/root/.hermes/kanban/boards/*/kanban.db; do
  [ -f "$db" ] || continue
  r=$("$PY" -c "import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute('PRAGMA integrity_check').fetchone()[0])" "$db" 2>/dev/null)
  if [ "$r" = "ok" ]; then ok=$((ok+1)); else bad=$((bad+1)); echo "  BAD: $db ($r)"; fi
done
echo "  kanban DBs ok=$ok bad=$bad"

echo "-- key files present + config parse --"
"$PY" - "$TESTDIR" <<'PYEOF'
import sys,glob,os
base=sys.argv[1]
need=['root/.hermes/profiles/orchestrator/AGENTS.md',
      'root/.hermes/profiles/orchestrator/config.yaml',
      'root/.codex/auth.json','root/.claude/.credentials.json']
miss=[p for p in need if not os.path.exists(os.path.join(base,p))]
print("  missing key files:", miss or "none")
try:
    import yaml
    bad=[]
    for f in glob.glob(os.path.join(base,'root/.hermes/profiles/*/config.yaml')):
        try: yaml.safe_load(open(f, encoding='utf-8'))
        except Exception: bad.append(os.path.basename(os.path.dirname(f)))
    print("  config.yaml parse failures:", bad or "none")
except ImportError:
    print("  (pyyaml unavailable — skipped parse check)")
units=len(glob.glob(os.path.join(base,'etc/systemd/system/*hermes*'))+glob.glob(os.path.join(base,'etc/systemd/system/*kanban*')))
print("  systemd units captured:", units)
PYEOF

rm -rf "$TESTDIR"
echo "RESTORE COMMAND: tar xzf <archive> -C /"
echo "ARCHPATH=$ARCH"
echo "=== drill done $TS ==="
} >> "$LOG" 2>&1
