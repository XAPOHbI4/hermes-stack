#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "references" / "manifest.json").read_text(encoding="utf-8"))
source_root = Path(manifest["source_root"])

assert manifest["source_file_count"] == 22
assert manifest["subtitle_count"] == 10
assert len(manifest["lessons"]) == 10
assert len(manifest["files"]) == 22
assert len({item["source"] for item in manifest["files"]}) == 22
assert len({item["copy"] for item in manifest["files"]}) == 22

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

for item in manifest["files"]:
    copied = ROOT / item["copy"]
    assert copied.is_file(), copied
    assert copied.stat().st_size == item["bytes"], copied
    assert sha256(copied) == item["sha256"], copied
    original = source_root / item["source"]
    if source_root.exists():
        assert original.is_file(), original
        assert sha256(original) == item["sha256"], original

for index, lesson in enumerate(manifest["lessons"]):
    card = ROOT / lesson["card"]
    subtitles = ROOT / lesson["subtitles"]
    assert card.is_file() and subtitles.is_file()
    text = card.read_text(encoding="utf-8")
    if index < 4:
        assert "Авторское ДЗ" in text
        assert "assignment" in lesson
    else:
        assert "Практика Джарвиса по материалам урока" in text

print(json.dumps({
    "ok": True,
    "lessons": len(manifest["lessons"]),
    "subtitles": manifest["subtitle_count"],
    "files": len(manifest["files"]),
    "originals_checked": source_root.exists(),
}, ensure_ascii=False))
