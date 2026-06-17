#!/usr/bin/env python3
"""
closure-enforcer (Phase 2, REPORT-ONLY).
Сторож: сканирует done-задачи по доскам и ЛОГИРУЕТ (ничего не меняет):
  - WOULD_REVIEW          — behavior-changing задача без вердикта (нужно детерминированное ревью)
  - PHANTOM_REVIEW_CLAIM  — текст заявляет ревью/PASS, но артефакта нет (анти-самообман)
  - OK_SKIP               — read-only / уже с вердиктом / непоместительное
Дедуп по seen-файлу: каждая задача логируется один раз.
REPORT_ONLY=True -> только лог, нулевой риск. Включение enforcing — отдельным шагом.
"""
import subprocess, json, os, re, time

HERMES = "/root/.hermes/hermes-agent/venv/bin/python"
HARGS = ["-m", "hermes_cli.main"]
LOGDIR = "/root/hermes/runtime/logs"
LOG = os.path.join(LOGDIR, "closure-enforcer.log")
STATE = os.path.join(LOGDIR, "closure-enforcer.seen")
VERDICT_DIR = "/root/hermes/runtime/reviews"   # сюда сторож будет класть task-keyed вердикты (в enforcing-режиме)
REPORT_ONLY = True

FILE_CHANGE = re.compile(r'(созда|написа|измен|отредакт|chmod|\bскрипт|patch|внедр|настро|\bконфиг|\bфайл|created|edited|wrote|modif|install|configur|\bscript\b|\bfile\b)', re.I)
READONLY = re.compile(r'(только чтени|read-?only|без измен|не менял|systemic.{0,3}read|\bаудит|\bотчёт|\breport\b|research|\bанализ|answering|изменений.{0,3}нет|no.{0,3}chang)', re.I)
REVIEW_CLAIM = re.compile(r'(verdict\s*PASS|вердикт\s*PASS|проверено независимо|independent.{0,12}review|review.{0,6}PASS|закры\w+.{0,12}PASS|кросс-?ревью|verdict[:=]\s*PASS)', re.I)

def run_json(args):
    try:
        out = subprocess.run([HERMES]+HARGS+args, capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout)
    except Exception:
        return None

def get_boards():
    try:
        out = subprocess.run([HERMES]+HARGS+["kanban","boards","list"], capture_output=True, text=True, timeout=30).stdout
        slugs = re.findall(r'^\s*●?\s*([a-z][a-z0-9-]{2,})\b', out, re.M)
        bad = {"board","boards","other","add","one","with","the","via","run","use"}
        slugs = [s for s in slugs if s not in bad]
        return sorted(set(slugs)) or ["it-devops","company-runtime","research"]
    except Exception:
        return ["it-devops","company-runtime","research"]

def load_seen():
    try: return set(open(STATE).read().split())
    except Exception: return set()

def save_seen(s):
    with open(STATE,"w") as f: f.write("\n".join(sorted(s)))

def has_verdict(tid):
    return os.path.exists(os.path.join(VERDICT_DIR, tid+".json"))

def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with open(LOG,"a") as f: f.write(line+"\n")
    print(line)

def gather(show, t):
    task = (show or {}).get("task") or t
    parts = [str(task.get("result") or ""), str(task.get("title") or "")]
    evs = (show or {}).get("events") or task.get("events") or []
    if isinstance(evs, list):
        for e in evs:
            d = e.get("data") if isinstance(e, dict) else None
            if isinstance(d, dict) and d.get("summary"):
                parts.append(str(d["summary"]))
            elif isinstance(e, dict) and e.get("summary"):
                parts.append(str(e["summary"]))
    md = task.get("metadata") or {}
    changed = md.get("changed_files") if isinstance(md, dict) else None
    return " ".join(parts), changed, task.get("assignee")

def main():
    os.makedirs(VERDICT_DIR, exist_ok=True); os.makedirs(LOGDIR, exist_ok=True)
    seen = load_seen()
    boards = get_boards()
    log(f"=== sweep start (REPORT-ONLY) boards={boards} seen={len(seen)} ===")
    scanned=would=phantom=ok=0
    for b in boards:
        lst = run_json(["kanban","--board",b,"list","--json"])
        if not isinstance(lst, list): continue
        for t in lst:
            if not isinstance(t, dict) or t.get("status")!="done": continue
            tid = t.get("id")
            if not tid or tid in seen: continue
            seen.add(tid); scanned+=1
            show = run_json(["kanban","--board",b,"show",tid,"--json"])
            text, changed, assignee = gather(show, t)
            if changed:
                behavioral, basis = True, f"changed_files={changed}"
            elif FILE_CHANGE.search(text) and not READONLY.search(text):
                behavioral, basis = True, "text:file-change-verbs"
            else:
                behavioral, basis = False, ("readonly-signal" if READONLY.search(text) else "no-file-signal")
            verdict = has_verdict(tid)
            claims = bool(REVIEW_CLAIM.search(text))
            if claims and not verdict:
                phantom+=1
                log(f"PHANTOM_REVIEW_CLAIM  {b}/{tid} ({assignee}) — текст заявляет ревью/PASS, артефакта нет")
            if behavioral and not verdict:
                would+=1
                log(f"WOULD_REVIEW  {b}/{tid} ({assignee}) | {basis}")
            else:
                ok+=1
                log(f"OK_SKIP  {b}/{tid} ({assignee}) | {basis}{' | has_verdict' if verdict else ''}")
    save_seen(seen)
    log(f"=== sweep done: scanned={scanned} WOULD_REVIEW={would} PHANTOM_CLAIM={phantom} OK_SKIP={ok} | mode={'REPORT-ONLY' if REPORT_ONLY else 'ENFORCING'} ===")

if __name__ == "__main__":
    main()
