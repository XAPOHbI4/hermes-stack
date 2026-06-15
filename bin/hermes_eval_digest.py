#!/usr/bin/env python3
"""Hermes eval/quality digest — READ-ONLY.

Reads every board's kanban.db and reports a quality picture per profile:
closed work, GENUINE failures vs restart/infra noise, retry pressure,
proof discipline and what is currently blocked.

Restart-noise rule (from the 2026-06-15 root-cause): a crashed run whose
task ultimately reached status='done' AND whose error is a process death
(pid not alive / exited with code / SIGINT / signal) is operational
restart churn, NOT a quality failure — counted separately.

Usage:
  python hermes_eval_digest.py            # last 7 days
  python hermes_eval_digest.py --days 30
  python hermes_eval_digest.py --all      # all history
Read-only: opens every DB with mode=ro, never writes.
"""
import sqlite3, glob, json, time, sys, collections, re

# Force UTF-8 stdout: under systemd / non-interactive ssh the locale is often
# C/POSIX, which makes Python emit Cyrillic as '?'. Reconfigure guarantees UTF-8
# regardless of LANG so the Telegram digest renders correctly.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BOARDS_GLOB = '/root/.hermes/kanban/boards/*/kanban.db'
DAY = 86400
NOW = int(time.time())

# --- args ---
days = 7
if '--all' in sys.argv:
    days = None
elif '--days' in sys.argv:
    try:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    except Exception:
        days = 7
cutoff = None if days is None else NOW - days * DAY

PROCESS_DEATH = re.compile(r'pid \d+ not alive|exited with code|sigint|sigterm|signal|killed', re.I)
STRONG_PROOF = re.compile(r'test|compile|security-scan|smoke\+test', re.I)


def fnum(x):
    try:
        return int(x)
    except Exception:
        return 0


def get_proof_type(meta_raw):
    if not meta_raw:
        return None
    try:
        m = json.loads(meta_raw)
    except Exception:
        return None
    pt = m.get('proof_type')
    if not pt and isinstance(m.get('metadata'), dict):
        pt = m['metadata'].get('proof_type')
    return pt


# accumulators
prof = collections.defaultdict(lambda: {
    'done': 0, 'genuine_fail': 0, 'restart_noise': 0, 'blocked': 0, 'runs': 0})
proof_tier = collections.Counter()        # strong / weak / none
proof_types = collections.Counter()
genuine_errors = collections.Counter()    # normalized real failure causes
blocked_tasks = []                         # (board, id, assignee, why)
retry_pressure = []                        # (board, id, assignee, consec, maxr)
bad_dbs = []
n_tasks = n_runs = 0
done_total = genuine_total = noise_total = 0

dbs = sorted(glob.glob(BOARDS_GLOB))
for db in dbs:
    board = db.split('/')[-2]
    try:
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        # task status map (id -> row) for join + window by completed/created
        tasks = {}
        for r in cur.execute(
                "SELECT id,title,assignee,status,consecutive_failures,max_retries,"
                "last_failure_error,created_at,completed_at FROM tasks"):
            tasks[r['id']] = r
        # window filter helper on a task
        def in_window(r):
            if cutoff is None:
                return True
            ts = fnum(r['completed_at']) or fnum(r['created_at'])
            return ts >= cutoff if ts else False

        for r in tasks.values():
            if not in_window(r):
                continue
            n_tasks += 1
            a = r['assignee'] or '?'
            st = r['status']
            if st == 'done':
                prof[a]['done'] += 1; done_total += 1
            elif st == 'blocked':
                prof[a]['blocked'] += 1
                # Real blocked reason lives in the latest 'blocked' task_event,
                # not last_failure_error (that field is empty for deliberate parks).
                reason = (r['last_failure_error'] or '')
                try:
                    ev = cur.execute(
                        "SELECT payload FROM task_events WHERE task_id=? AND kind='blocked' "
                        "ORDER BY created_at DESC LIMIT 1", (r['id'],)).fetchone()
                    if ev and ev['payload']:
                        reason = (json.loads(ev['payload']).get('reason') or reason)
                except Exception:
                    pass
                blocked_tasks.append((board, r['id'], a, reason[:110]))
            cf = fnum(r['consecutive_failures'])
            if cf >= 2:
                retry_pressure.append((board, r['id'], a, cf, r['max_retries']))

        # runs
        for r in cur.execute(
                "SELECT task_id,profile,status,outcome,error,metadata,started_at "
                "FROM task_runs"):
            ts = fnum(r['started_at'])
            if cutoff is not None and ts and ts < cutoff:
                continue
            n_runs += 1
            p = r['profile'] or '?'
            prof[p]['runs'] += 1
            oc = (r['outcome'] or '').lower()
            if oc == 'crashed':
                t = tasks.get(r['task_id'])
                task_done = t and t['status'] == 'done'
                err = r['error'] or ''
                if task_done and PROCESS_DEATH.search(err):
                    prof[p]['restart_noise'] += 1; noise_total += 1
                else:
                    prof[p]['genuine_fail'] += 1; genuine_total += 1
                    norm = PROCESS_DEATH.sub('<proc-death>', err).strip()[:80] or '(empty)'
                    genuine_errors[f'{p}: {norm}'] += 1
            # proof discipline on completed runs
            if oc in ('completed', 'done'):
                pt = get_proof_type(r['metadata'])
                if pt:
                    proof_types[pt] += 1
                    proof_tier['strong' if STRONG_PROOF.search(pt) else 'weak'] += 1
                else:
                    proof_tier['none'] += 1
        con.close()
    except Exception as e:
        bad_dbs.append((board, str(e)[:60]))

# --- render ---
win = 'вся история' if days is None else f'последние {days} дн.'

# --- markdown mode (--md): native Telegram table via sendRichMessage ---
if '--md' in sys.argv:
    ps = proof_tier
    md = []
    md.append(f"📊 *Hermes — итоги недели* ({time.strftime('%Y-%m-%d')})")
    md.append("")
    md.append(f"✅ Задачи: {done_total} · ⚠️ Реальных провалов: {genuine_total} · 🔁 Рестарт-шум: {noise_total}")
    md.append("")
    # Emoji column headers keep the data columns ~1 char wide so all of
    # done/fail/noise fit on a phone without horizontal scroll.
    md.append("| Профиль | ✅ | ⚠️ | 🔁 |")
    md.append("|---|--:|--:|--:|")
    for name, d in sorted(prof.items(), key=lambda kv: (-kv[1]['done'], kv[0])):
        if d['done'] == 0 and d['genuine_fail'] == 0 and d['restart_noise'] == 0:
            continue
        md.append(f"| {name} | {d['done']} | {d['genuine_fail']} | {d['restart_noise']} |")
    md.append("")
    md.append(f"*Proof-дисциплина:* strong (test/compile) {ps['strong']} · "
              f"weak (doc/smoke) {ps['weak']} · нет proof {ps['none']}")
    if genuine_errors:
        md.append("")
        md.append("*Реальные провалы:*")
        for cause, c in genuine_errors.most_common(5):
            md.append(f"- ×{c} {cause}")
    else:
        md.append("")
        md.append("✅ Реальных провалов нет — всё либо done, либо рестарт-шум.")
    if blocked_tasks:
        md.append("")
        md.append(f"⏳ *Заблокировано: {len(blocked_tasks)}*")
        for b, tid, a, why in blocked_tasks[:6]:
            md.append(f"- {a}: {why or 'причина не записана'}")
    print('\n'.join(md))
    raise SystemExit(0)

out = []
out.append(f"📊 Hermes eval-дайджест — {win}  ({time.strftime('%Y-%m-%d %H:%M')})")
out.append("")
fail_pct = (genuine_total / n_runs * 100) if n_runs else 0
out.append(f"Закрыто задач: {done_total} · в работе/прочее: {n_tasks - done_total} · прогонов: {n_runs}")
out.append(f"Реальных провалов: {genuine_total} ({fail_pct:.0f}%) · рестарт-шум (восстановлено): {noise_total}")
out.append("")

# per-profile table
out.append("По профилям  (done / провал / шум / runs):")
rows = sorted(prof.items(), key=lambda kv: (-kv[1]['done'], kv[0]))
for name, d in rows:
    flag = ' ⚠️' if d['genuine_fail'] > 0 else ''
    out.append(f"  {name:<18} {d['done']:>3} / {d['genuine_fail']:>2} / {d['restart_noise']:>2} / {d['runs']:>3}{flag}")
out.append("")

# proof discipline
ps = proof_tier
total_proof = sum(ps.values()) or 1
out.append(f"Proof-дисциплина (закрытые прогоны): "
           f"strong(test/compile) {ps['strong']} · weak(doc/smoke) {ps['weak']} · нет proof {ps['none']}")
if proof_types:
    top = ', '.join(f'{k}×{v}' for k, v in proof_types.most_common(6))
    out.append(f"  типы proof: {top}")
out.append("")

# genuine failure causes
if genuine_errors:
    out.append("Топ реальных причин провалов:")
    for cause, c in genuine_errors.most_common(8):
        out.append(f"  ×{c}  {cause}")
    out.append("")
else:
    out.append("Реальных провалов в окне нет — всё либо done, либо рестарт-шум. ✅")
    out.append("")

# retry pressure
if retry_pressure:
    out.append(f"Под давлением ретраев (consecutive_failures≥2): {len(retry_pressure)}")
    for b, tid, a, cf, mr in retry_pressure[:8]:
        out.append(f"  [{b}] {tid} {a} — fails={cf} max_retries={mr}")
    out.append("")

# blocked
if blocked_tasks:
    out.append(f"Заблокировано сейчас: {len(blocked_tasks)}")
    for b, tid, a, why in blocked_tasks[:8]:
        out.append(f"  [{b}] {tid} {a} — {why or 'причина не записана'}")
    out.append("")

if bad_dbs:
    out.append(f"⚠️ Нечитаемые/битые БД: {len(bad_dbs)} — {', '.join(b for b,_ in bad_dbs)}")

# machine-readable summary line (for cron alert thresholds)
out.append("")
out.append(f"SUMMARY genuine_fail={genuine_total} restart_noise={noise_total} "
           f"blocked={len(blocked_tasks)} proof_none={ps['none']} runs={n_runs}")
print('\n'.join(out))
