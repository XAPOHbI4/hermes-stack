#!/usr/bin/env python3
"""Hermes graduation-lessons — model-driven weekly reflection (REPORT ONLY).

Gathers quality facts from Kanban (proof discipline, weak-proof closed tasks,
blocked tasks, genuine failures), hands them to Claude (the methodologist) for
reasoning, and writes a lessons report. Claude THINKS, code only gathers/routes.

SAFETY: this never edits any profile contract or skill. It only writes a report
under reports/ and (optionally) sends it to Telegram. Applying lessons to
contracts is a separate, explicitly-approved step.

Usage:
  python hermes_lessons.py            # 7-day window, writes report, prints it
  python hermes_lessons.py --days 30
Requires claude_run.py (model-driven) reachable; falls back to a facts-only
report if the model call fails.
"""
import sqlite3, glob, json, time, sys, subprocess, collections, re, os

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BOARDS_GLOB = '/root/.hermes/kanban/boards/*/kanban.db'
HERMES_HOME = os.environ.get('HERMES_HOME', '/root/hermes/runtime')
CLAUDE_RUN = HERMES_HOME + '/bin/claude_run.py'
REPORTS = HERMES_HOME + '/reports'
DAY = 86400
NOW = int(time.time())

days = 7
if '--days' in sys.argv:
    try:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    except Exception:
        days = 7
cutoff = NOW - days * DAY

STRONG_PROOF = re.compile(r'test|compile|security-scan', re.I)
PROCESS_DEATH = re.compile(r'pid \d+ not alive|exited with code|sigint|sigterm|signal|killed', re.I)


def fnum(x):
    try:
        return int(x)
    except Exception:
        return 0


def proof_of(meta_raw):
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


weak_cases = []      # (profile, title, proof_type-or-none)
blocked_cases = []   # (profile, title, why)
genuine = []         # (profile, err)
tier = collections.Counter()
prof_done = collections.Counter()

for db in sorted(glob.glob(BOARDS_GLOB)):
    board = db.split('/')[-2]
    try:
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        tasks = {r['id']: r for r in cur.execute(
            "SELECT id,title,assignee,status,last_failure_error,created_at,completed_at FROM tasks")}
        # map task -> best proof_type from its completed runs
        proof_by_task = {}
        gen_by_task = collections.defaultdict(list)
        for r in cur.execute("SELECT task_id,profile,outcome,error,metadata FROM task_runs"):
            oc = (r['outcome'] or '').lower()
            if oc in ('completed', 'done'):
                pt = proof_of(r['metadata'])
                if pt and (r['task_id'] not in proof_by_task or STRONG_PROOF.search(pt)):
                    proof_by_task[r['task_id']] = pt
            elif oc == 'crashed':
                t = tasks.get(r['task_id'])
                err = r['error'] or ''
                if not (t and t['status'] == 'done' and PROCESS_DEATH.search(err)):
                    gen_by_task[r['task_id']].append((r['profile'] or '?', err[:80]))
        for tid, t in tasks.items():
            ts = fnum(t['completed_at']) or fnum(t['created_at'])
            if ts and ts < cutoff:
                continue
            a = t['assignee'] or '?'
            title = (t['title'] or '')[:70]
            if t['status'] == 'done':
                prof_done[a] += 1
                pt = proof_by_task.get(tid)
                if pt and STRONG_PROOF.search(pt):
                    tier['strong'] += 1
                elif pt:
                    tier['weak'] += 1
                    weak_cases.append((a, title, pt))
                else:
                    tier['none'] += 1
                    weak_cases.append((a, title, '(нет proof)'))
            elif t['status'] == 'blocked':
                blocked_cases.append((a, title, (t['last_failure_error'] or 'причина не записана')[:80]))
            for p, e in gen_by_task.get(tid, []):
                genuine.append((p, e))
        con.close()
    except Exception:
        pass

# ---- build the facts block for the model ----
facts = []
facts.append(f"Окно: последние {days} дн. Закрыто задач по профилям: " +
             ', '.join(f'{k}={v}' for k, v in prof_done.most_common()))
facts.append(f"Proof-дисциплина: strong(test/compile)={tier['strong']}, "
             f"weak(doc/smoke/config/review)={tier['weak']}, без proof={tier['none']}")
facts.append("")
facts.append("СЛАБО ЗАКРЫТЫЕ ЗАДАЧИ (закрыты без сильного доказательства):")
for a, title, pt in weak_cases[:18]:
    facts.append(f"  - [{a}] {title} — proof: {pt}")
if not weak_cases:
    facts.append("  (нет)")
facts.append("")
facts.append("ЗАБЛОКИРОВАННЫЕ:")
for a, title, why in blocked_cases[:10]:
    facts.append(f"  - [{a}] {title} — {why}")
if not blocked_cases:
    facts.append("  (нет)")
if genuine:
    facts.append("")
    facts.append("РЕАЛЬНЫЕ ПРОВАЛЫ (не рестарт-шум):")
    for p, e in genuine[:10]:
        facts.append(f"  - [{p}] {e}")
facts_block = '\n'.join(facts)

PROMPT = (
    "Ты — методолог автономной мульти-агентной системы Hermes. Ниже факты о работе "
    "агентов за неделю (из Kanban). Сделай КОРОТКИЙ разбор по-русски:\n"
    "1) 2-3 системные слабости (главное — почему задачи закрываются без сильного "
    "доказательства: test/compile, а не просто document/smoke).\n"
    "2) Для каждого проблемного профиля — 1 конкретная, проверяемая рекомендация "
    "(что именно требовать в proof при закрытии).\n"
    "3) 1 совет по процессу в целом.\n"
    "Будь конкретным и кратким (до ~250 слов), без воды. Это РЕКОМЕНДАЦИИ для оператора, "
    "не команды. Не выдумывай данных сверх фактов."
)


def call_model(facts_text):
    try:
        p = subprocess.run(
            ['python3', CLAUDE_RUN, '--model', 'sonnet', '--attempts', '2', '--timeout', '160', PROMPT],
            input=facts_text, text=True, capture_output=True, timeout=360,
            env={**os.environ, 'HERMES_HOME': HERMES_HOME})
        out = (p.stdout or '').strip()
        if out and not out.startswith('BLOCK:'):
            return out
        return None
    except Exception as e:
        return None


lessons = call_model(facts_block)
ts_name = time.strftime('%Y%m%dT%H%M', time.gmtime(NOW))
header = f"🎓 Hermes — уроки недели ({time.strftime('%Y-%m-%d', time.gmtime(NOW))})"
if lessons:
    body = f"{header}\n\n{lessons}\n\n— — —\nФакты, на которых основан разбор:\n{facts_block}"
    msg = f"{header}\n\n{lessons}"   # clean message for chat (no raw facts dump)
else:
    body = (f"{header}\n\n⚠️ Модель-рефлексия недоступна — привожу только факты:\n\n{facts_block}")
    msg = body

try:
    os.makedirs(REPORTS, exist_ok=True)
    open(f"{REPORTS}/lessons-{ts_name}.md", 'w', encoding='utf-8').write(body)
    open(f"{REPORTS}/lessons-latest.md", 'w', encoding='utf-8').write(body)
    open(f"{REPORTS}/lessons-msg.md", 'w', encoding='utf-8').write(msg)
except Exception:
    pass

print(body)
print(f"\nLESSONS_MODEL={'ok' if lessons else 'fallback'} weak={len(weak_cases)} blocked={len(blocked_cases)}")
