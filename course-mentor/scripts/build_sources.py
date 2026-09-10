#!/usr/bin/env python3
import argparse, hashlib, json, os, shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LESSONS=[
 ("01-programs","Урок 1. Программы",Path("1 урок «Программы»"),3),
 ("02-beliefs","Урок 2. Убеждения",Path("2 урок «Убеждения»"),3),
 ("03-creation","Урок 3. Творение",Path("3 урок «Творение»"),3),
 ("04-money","Урок 4. Деньги",Path("4 урок «Деньги»"),3),
 ("05-laws","Урок 5. Законы",Path("5 урок «Законы»"),3),
 ("06-traps","Урок 6. Ловушки",Path("6 урок «Ловушки»"),3),
 ("07-doing","Урок 7. Делание",Path("7 урок «Делание»"),3),
 ("08-nika-viardo","Гостевой эфир. Ника Виардо",Path("8 урок «Гостевые эфиры»")/"Ника Виардо",2),
 ("09-pavel-kochkin","Гостевой эфир. Павел Кочкин",Path("8 урок «Гостевые эфиры»")/"Павел Кочкин",2),
 ("10-ruslan-sukhiy","Гостевой эфир. Руслан Сухий",Path("8 урок «Гостевые эфиры»")/"Руслан Сухий",0)]

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',default=os.environ.get('CONSTANTS_COURSE_SOURCE'))
    args=parser.parse_args()
    if not args.source: raise SystemExit('Pass --source or CONSTANTS_COURSE_SOURCE')
    source=Path(args.source).resolve()
    if not source.is_dir(): raise SystemExit('Course source directory not found')
    out=ROOT/"references"/"source"
    if out.exists(): shutil.rmtree(out)
    files=[]; lessons=[]
    for ident,title,rel,interval_days in LESSONS:
        dst_dir=out/ident; dst_dir.mkdir(parents=True); mapping={}
        for src in sorted((source/rel).glob("*.txt")):
            name="subtitles.txt" if src.name=="Субтитры.txt" else "assignment.txt" if src.name.startswith("Задание") else "guest.txt" if src.name=="О госте.txt" else "methods.txt"
            dst=dst_dir/name; shutil.copy2(src,dst); key=name[:-4]; mapping[key]=str(dst.relative_to(ROOT)).replace("\\","/")
            files.append({"source":str(src.relative_to(source)),"copy":str(dst.relative_to(ROOT)).replace("\\","/"),"bytes":src.stat().st_size,"sha256":digest(src)})
        lessons.append({"id":ident,"title":title,"interval_days":interval_days,"card":f"references/lessons/{ident}.md",**mapping})
    src=source/"8 урок «Гостевые эфиры»"/"Задание.txt"; dst=out/"08-guests-assignment.txt"; shutil.copy2(src,dst)
    files.append({"source":str(src.relative_to(source)),"copy":str(dst.relative_to(ROOT)).replace("\\","/"),"bytes":src.stat().st_size,"sha256":digest(src)})
    originals=sorted(source.rglob("*.txt")); manifest={"course":"Константы 2.0","source_root":str(source),"source_file_count":len(originals),"subtitle_count":sum(p.name=="Субтитры.txt" for p in originals),"lessons":lessons,"files":files}
    (ROOT/"references"/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"source_files":len(originals),"copied_files":len(files),"lessons":len(lessons)},ensure_ascii=False))
if __name__=="__main__": main()
