#!/usr/bin/env python3
# READ-ONLY audit: skill-name collisions + dead/unauthenticated model providers.
# Prints machine-parseable summary lines; never changes anything.
import os, glob, re, json

PROF_DIR = "/root/.hermes/profiles"

def skill_name(p):
    try:
        h = open(p, encoding="utf-8", errors="ignore").read(1500)
    except Exception:
        return None
    m = re.search(r"(?m)^name:\s*(.+)$", h)
    return m.group(1).strip().strip('"\'') if m else None

collisions = []          # (profile, name, count)
dead_providers = []      # (profile, default, provider)

for prof in sorted(os.listdir(PROF_DIR)):
    pdir = os.path.join(PROF_DIR, prof)
    if not os.path.isdir(pdir):
        continue
    # skills: count active SKILL.md per name (ignore .disabled)
    sroot = os.path.join(pdir, "skills")
    if os.path.isdir(sroot):
        names = {}
        for sk in glob.glob(sroot + "/**/SKILL.md", recursive=True):
            n = skill_name(sk)
            if n:
                names[n] = names.get(n, 0) + 1
        for n, c in names.items():
            if c > 1:
                collisions.append((prof, n, c))
    # model provider sanity (only for enabled gateways matters most, but check all)
    cfg = os.path.join(pdir, "config.yaml")
    if os.path.isfile(cfg):
        txt = open(cfg, encoding="utf-8", errors="ignore").read(800)
        dm = re.search(r"(?m)^\s*default:\s*(.+)$", txt)
        pv = re.search(r"(?m)^\s*provider:\s*(.+)$", txt)
        d = (dm.group(1).strip() if dm else "")
        p = (pv.group(1).strip() if pv else "")
        if "xai" in p.lower() or "grok" in d.lower():
            dead_providers.append((prof, d, p))

print("COLLISIONS:", len(collisions))
for prof, n, c in collisions[:20]:
    print(f"  - {prof}: {n} x{c}")
print("DEAD_PROVIDERS:", len(dead_providers))
for prof, d, p in dead_providers:
    print(f"  - {prof}: {d} via {p}")
