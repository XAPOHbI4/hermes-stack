#!/usr/bin/env python3
import argparse, hashlib, json, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {".txt", ".pdf", ".docx"}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def build(source, root=ROOT):
    source = Path(source).resolve()
    if not source.is_dir():
        raise ValueError("course source directory not found")
    root = Path(root).resolve()
    destination = (root / "references" / "source").resolve()
    if destination == source or source.is_relative_to(destination):
        raise ValueError("course source cannot be inside the generated copy")
    if not destination.is_relative_to(root):
        raise ValueError("generated copy must stay inside the module root")
    if destination.exists():
        shutil.rmtree(destination)
    files = []
    for src in sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED):
        relative = src.relative_to(source)
        dst = destination / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        files.append({"path":relative.as_posix(), "bytes":src.stat().st_size, "sha256":digest(src)})
    transcripts = [f for f in files if f["path"].endswith("Субтитры.txt") and f["bytes"]]
    manifest = {"course":"Продажи в новой реальности", "source_file_count":len(files),
                "subtitle_count":len(transcripts), "unique_subtitle_count":len({f["sha256"] for f in transcripts}),
                "files":files}
    target = root / "references" / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    result = build(args.source)
    print(json.dumps({k:result[k] for k in ("source_file_count","subtitle_count","unique_subtitle_count")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
