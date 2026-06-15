#!/usr/bin/env bash
# Archive-then-delete all .disabled skill files under /root/.hermes.
# Reversible: full archive kept; restore with  tar xzf <ARCH> -C /
set -uo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
ARCH=/root/hermes-disabled-skills-${TS}.tar.gz
LIST=/root/hermes-disabled-filelist-${TS}.txt
LOG=/root/hermes/runtime/logs/clean-disabled.log

{
echo "=== clean .disabled started $TS ==="
N=$(find /root/.hermes -name '*.disabled' -type f | tee "$LIST" | wc -l)
echo "found: $N files"
[ "$N" -eq 0 ] && { echo "nothing to do"; exit 0; }

# archive (null-safe), paths stored without leading slash -> restore with -C /
find /root/.hermes -name '*.disabled' -type f -print0 \
  | tar --null --no-recursion -czf "$ARCH" -T -
INARCH=$(tar tzf "$ARCH" | wc -l)
echo "archived: $INARCH  (size $(du -h "$ARCH" | cut -f1))"

if [ "$INARCH" -ne "$N" ]; then
  echo "MISMATCH ($INARCH != $N) — ABORT, nothing deleted. Archive at $ARCH"
  exit 1
fi

# safe to delete now (archive verified)
find /root/.hermes -name '*.disabled' -type f -delete
REM=$(find /root/.hermes -name '*.disabled' -type f | wc -l)
echo "deleted. remaining .disabled: $REM"
echo "ROLLBACK: tar xzf $ARCH -C /"
echo "=== done $TS ==="
} >> "$LOG" 2>&1
