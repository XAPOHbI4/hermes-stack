#!/usr/bin/env python3
"""Print Codex (ChatGPT) subscription usage from the newest codex session rollout.

Codex writes a `rate_limits` block into every session rollout JSONL after each
run: primary = 5h window, secondary = weekly window (window_minutes 300 / 10080).
This reads the most recent snapshot. Output: "primary_pct secondary_pct age_min"
or "NA" if no data.
"""
import glob, os, json, time, sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def newest_rate_limits():
    files = glob.glob('/root/.codex/sessions/*/*/*/rollout-*.jsonl')
    if not files:
        return None, None
    files.sort(key=os.path.getmtime, reverse=True)
    for path in files[:8]:                      # newest few; stop at first with data
        last = None
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                for line in fh:
                    if '"rate_limits"' not in line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    rl = o.get('rate_limits')
                    if not rl and isinstance(o.get('payload'), dict):
                        rl = o['payload'].get('rate_limits')
                    if not rl and isinstance(o.get('info'), dict):
                        rl = o['info'].get('rate_limits')
                    if rl:
                        last = rl
        except Exception:
            continue
        if last:
            return last, os.path.getmtime(path)
    return None, None


rl, mtime = newest_rate_limits()
if not rl:
    print("NA")
    raise SystemExit(0)
p = int((rl.get('primary') or {}).get('used_percent') or 0)
s = int((rl.get('secondary') or {}).get('used_percent') or 0)
age_min = int((time.time() - mtime) / 60) if mtime else -1
print(f"{p} {s} {age_min}")
