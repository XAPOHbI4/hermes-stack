#!/usr/bin/env python3
import argparse, json, os, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.environ.get("CONSTANTS_COURSE_ROOT", "/opt/constants-course-mentor"))
DB = Path(os.environ.get("CONSTANTS_COURSE_DB", "/var/lib/constants-course-mentor/state.sqlite3"))
MANIFEST = ROOT / "references" / "manifest.json"

def now(): return datetime.now(timezone.utc).replace(microsecond=0)
def emit(data): print(json.dumps(data, ensure_ascii=False))
def lessons(): return json.loads(MANIFEST.read_text(encoding="utf-8"))["lessons"]
def lesson_at(index):
    items = lessons()
    return items[index] if 0 <= index < len(items) else None

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB); db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS progress (id INTEGER PRIMARY KEY CHECK(id=1), lesson_index INTEGER NOT NULL DEFAULT 0, phase TEXT NOT NULL DEFAULT 'not_started', previous_phase TEXT, updated_at TEXT NOT NULL, reminded_at TEXT);
    CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, lesson_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    db.execute("INSERT OR IGNORE INTO progress(id,updated_at) VALUES(1,?)", (now().isoformat(),)); db.commit()
    columns={row[1] for row in db.execute("PRAGMA table_info(progress)")}
    if "watched_at" not in columns: db.execute("ALTER TABLE progress ADD COLUMN watched_at TEXT")
    if "next_available_at" not in columns: db.execute("ALTER TABLE progress ADD COLUMN next_available_at TEXT")
    db.commit()
    return db

def state(db): return dict(db.execute("SELECT * FROM progress WHERE id=1").fetchone())
def set_state(db, **values):
    values["updated_at"] = now().isoformat()
    db.execute("UPDATE progress SET " + ", ".join(f"{k}=?" for k in values) + " WHERE id=1", tuple(values.values())); db.commit()

def cmd_start(db, args):
    s = state(db)
    if s["phase"] == "not_started": set_state(db, phase="watching", lesson_index=0); s = state(db)
    if s["phase"] != "watching": return cmd_resume(db, args)
    item = lesson_at(s["lesson_index"])
    emit({"action":"watch","lesson_id":item["id"],"message":item["title"]} if item else {"action":"complete","message":"Курс «Константы 2.0» завершён."})

def cmd_resume(db, args):
    s = state(db)
    if s["phase"] == "paused": set_state(db, phase=s["previous_phase"] or "watching", previous_phase=None); s = state(db)
    if s["phase"] == "not_started": return cmd_start(db, args)
    item = lesson_at(s["lesson_index"])
    if not item: return emit({"action":"complete","message":"Курс «Константы 2.0» завершён."})
    if s["phase"] == "watching": return emit({"action":"watch","lesson_id":item["id"],"message":item["title"]})
    if s["phase"] == "waiting_next": return emit({"action":"waiting","message":"Сейчас идёт интервал на закрепление.","available_at":s["next_available_at"]})
    emit({"action":s["phase"],"lesson_id":item["id"],"message":f"Продолжаем урок: {item['title']}","card":str(ROOT/item["card"])})

def cmd_watched(db, args):
    s = state(db); item = lesson_at(s["lesson_index"])
    if not item: return emit({"error":"Курс уже завершён."})
    if s["phase"] == "waiting_next": return emit({"error":"Следующий урок пока закрыт.","available_at":s["next_available_at"]})
    if s["phase"] in {"not_started","watching","paused"}: set_state(db, phase="discussion", previous_phase=None, watched_at=now().isoformat())
    emit({"action":"discussion","lesson_id":item["id"],"title":item["title"],"card":str(ROOT/item["card"])})

def cmd_phase(db, args):
    if args.phase not in {"discussion","homework"}: raise SystemExit("phase must be discussion or homework")
    s=state(db); item=lesson_at(s["lesson_index"]); set_state(db,phase=args.phase); emit({"ok":True,"phase":args.phase,"lesson_id":item["id"]})

def cmd_record(db, args):
    value=args.text.strip()
    if not value: raise SystemExit("empty journal entry")
    s=state(db); item=lesson_at(s["lesson_index"])
    if not item: raise SystemExit("course complete")
    db.execute("INSERT INTO journal(lesson_id,kind,text,created_at) VALUES(?,?,?,?)",(item["id"],args.kind,value,now().isoformat())); set_state(db); emit({"ok":True,"lesson_id":item["id"],"kind":args.kind})

def cmd_complete(db, args):
    s=state(db); current=lesson_at(s["lesson_index"])
    if not current: return emit({"action":"complete","message":"Курс «Константы 2.0» завершён."})
    index=s["lesson_index"]+1; nxt=lesson_at(index)
    if not nxt:
        set_state(db,lesson_index=index,phase="complete",previous_phase=None,next_available_at=None)
        return emit({"action":"complete","completed_title":current["title"],"next_title":None,"message":"Курс «Константы 2.0» завершён."})
    days=float(os.environ.get("CONSTANTS_COURSE_INTERVAL_DAYS",current.get("interval_days",3)))
    base=datetime.fromisoformat(s["watched_at"]) if s.get("watched_at") else now()
    due=base+timedelta(days=days)
    if due<=now():
        set_state(db,lesson_index=index,phase="watching",previous_phase=None,watched_at=None,next_available_at=None)
        return emit({"action":"next","completed_title":current["title"],"next_title":nxt["title"],"message":nxt["title"]})
    set_state(db,lesson_index=index,phase="waiting_next",previous_phase=None,watched_at=None,next_available_at=due.isoformat())
    emit({"action":"waiting","completed_title":current["title"],"next_title":None,"available_at":due.isoformat(),"message":"Домашнее задание завершено. Следующий урок придёт после интервала на закрепление."})

def cmd_pause(db,args):
    s=state(db)
    if s["phase"]!="paused": set_state(db,previous_phase=s["phase"],phase="paused")
    emit({"ok":True,"message":"Курс поставлен на паузу."})

def cmd_status(db,args):
    s=state(db); item=lesson_at(s["lesson_index"]); emit({"phase":s["phase"],"completed":min(s["lesson_index"],len(lessons())),"total":len(lessons()),"current_title":item["title"] if item else None,"next_available_at":s.get("next_available_at"),"updated_at":s["updated_at"]})

def cmd_reminder(db,args):
    s=state(db)
    if s["phase"] in {"paused","complete"}: return print("NO_REPLY")
    if s["phase"]=="waiting_next":
        if not s["next_available_at"] or now()<datetime.fromisoformat(s["next_available_at"]): return print("NO_REPLY")
        item=lesson_at(s["lesson_index"]); set_state(db,phase="watching",next_available_at=None,reminded_at=now().isoformat())
        return emit({"action":"next","message":item["title"]})
    if now()-datetime.fromisoformat(s["updated_at"]) < timedelta(hours=args.after_hours): return print("NO_REPLY")
    if s["reminded_at"] and now()-datetime.fromisoformat(s["reminded_at"]) < timedelta(hours=args.cooldown_hours): return print("NO_REPLY")
    item=lesson_at(s["lesson_index"]); word="обсуждение" if s["phase"]=="discussion" else "задание"
    message=f"Василий, время для курса. Следующий урок: {item['title']}" if s["phase"]=="not_started" else f"Василий, продолжаем курс? Сейчас у тебя урок: {item['title']}" if s["phase"]=="watching" else f"Василий, вернёмся к уроку «{item['title']}» и закончим {word}?"
    db.execute("UPDATE progress SET reminded_at=? WHERE id=1",(now().isoformat(),)); db.commit(); emit({"action":"remind","message":message})

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="command",required=True)
    for name in ("start","resume","watched","complete","pause","status"): sub.add_parser(name)
    ph=sub.add_parser("phase"); ph.add_argument("phase")
    rec=sub.add_parser("record"); rec.add_argument("--kind",choices=("reflection","homework","note"),required=True); rec.add_argument("--text",required=True)
    rem=sub.add_parser("reminder"); rem.add_argument("--after-hours",type=float,default=48); rem.add_argument("--cooldown-hours",type=float,default=24)
    args=p.parse_args()
    with connect() as db: globals()[f"cmd_{args.command}"](db,args)

if __name__=="__main__": main()
