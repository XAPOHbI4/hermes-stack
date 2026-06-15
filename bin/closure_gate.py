#!/usr/bin/env python3
"""Closure gate — shared across all Hermes profiles.

Closure directory resolved from CLOSURE_DIR env var,
or defaults to $HERMES_HOME/closures (set automatically per profile by systemd).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

VALID_REVIEWERS = {"claude"}
VALID_VERDICTS = {"PASS", "REWORK", "BLOCK"}
REQUIRED_ARTIFACT_KEYS = {"created_at", "reviewer", "task", "verdict", "packet_sha256", "raw_output"}
REQUIRED_PACKET_SECTIONS = [
    "## Исходная задача",
    "## План / acceptance criteria",
    "## Отчёт Hermes/Codex о выполнении",
    "## Изменённые файлы / артефакты",
    "## Реально запущенные проверки",
    "## Evidence / readback",
    "## Известные ограничения / блокеры",
]


def _default_closure_dir() -> str:
    hermes_home = os.environ.get("HERMES_HOME", "/root/.hermes/profiles/personalassistant")
    return os.environ.get("CLOSURE_DIR", os.path.join(hermes_home, "closures"))


def _profile_name() -> str:
    hermes_home = os.environ.get("HERMES_HOME", "")
    if hermes_home:
        return Path(hermes_home).name
    return "hermes"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_review_packet(path: Path) -> str:
    packet = path.read_text(encoding="utf-8").strip()
    return hashlib.sha256(packet.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"cannot parse JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("artifact JSON root is not an object")
    return data


def non_comment_content(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        lines.append(line)
    return "\n".join(lines)


def validate_packet(packet_path: Path, min_packet_chars: int) -> tuple[list[str], str]:
    errors: list[str] = []
    if not packet_path.exists():
        return [f"packet missing: {packet_path}"], ""
    if not packet_path.is_file():
        return [f"packet is not a file: {packet_path}"], ""
    text = packet_path.read_text(encoding="utf-8")
    if len(text.strip()) < min_packet_chars:
        errors.append(f"packet too short: {len(text.strip())} < {min_packet_chars}")
    for section in REQUIRED_PACKET_SECTIONS:
        if section not in text:
            errors.append(f"packet missing section: {section}")
    effective = non_comment_content(text)
    if len(effective.strip()) < min_packet_chars:
        errors.append(f"packet lacks non-comment evidence content: {len(effective.strip())} < {min_packet_chars}")
    return errors, text


def validate_artifact(artifact_path: Path, packet_hash: str) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if not artifact_path.exists():
        return [f"review artifact missing: {artifact_path}"], {}
    if not artifact_path.is_file():
        return [f"review artifact is not a file: {artifact_path}"], {}
    try:
        data = load_json(artifact_path)
    except ValueError as exc:
        return [f"invalid review artifact: {exc}"], {}

    missing = sorted(REQUIRED_ARTIFACT_KEYS - set(data))
    if missing:
        errors.append(f"review artifact missing keys: {', '.join(missing)}")

    reviewer = str(data.get("reviewer", "")).lower()
    if reviewer not in VALID_REVIEWERS:
        errors.append(f"reviewer must be claude, got: {data.get('reviewer')!r}")

    verdict = str(data.get("verdict", "")).upper()
    if verdict not in VALID_VERDICTS:
        errors.append(f"invalid verdict: {data.get('verdict')!r}")
    elif verdict != "PASS":
        errors.append(f"closure requires PASS verdict, got: {verdict}")

    artifact_hash = str(data.get("packet_sha256", ""))
    if artifact_hash != packet_hash:
        errors.append(f"packet hash mismatch: artifact={artifact_hash} actual={packet_hash}")

    raw = str(data.get("raw_output", ""))
    first_nonempty = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    if first_nonempty != "Вердикт: PASS":
        errors.append(f"raw_output first nonempty line must be 'Вердикт: PASS', got: {first_nonempty!r}")
    for marker in ("Проверено", "Evidence", "Финальный статус"):
        if marker not in raw:
            errors.append(f"raw_output missing marker: {marker}")

    return errors, data


def validate_paths(paths: list[str], label: str, require_existing: bool) -> list[str]:
    errors: list[str] = []
    if require_existing and not paths:
        errors.append(f"at least one {label} path is required")
    for item in paths:
        p = Path(item).expanduser()
        if not p.exists():
            errors.append(f"{label} path missing: {p}")
    return errors


def default_manifest_path(task_id: str | None, packet_hash: str) -> Path:
    out_dir = Path(_default_closure_dir())
    safe_task = "task" if not task_id else "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in task_id)[:80]
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return out_dir / f"closure_{ts}_{safe_task}_{packet_hash[:12]}.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Claude review evidence before closing a task.")
    parser.add_argument("--packet", required=True)
    parser.add_argument("--review-artifact", required=True)
    parser.add_argument("--task-id", default="")
    parser.add_argument("--result", default="")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--manifest-out", default="")
    parser.add_argument("--min-packet-chars", type=int, default=500)
    parser.add_argument("--no-require-evidence-path", action="store_true")
    args = parser.parse_args()

    packet_path = Path(args.packet).expanduser()
    artifact_path = Path(args.review_artifact).expanduser()

    errors: list[str] = []
    packet_errors, _packet_text = validate_packet(packet_path, args.min_packet_chars)
    errors.extend(packet_errors)
    packet_hash = sha256_review_packet(packet_path) if packet_path.exists() and packet_path.is_file() else ""

    artifact_errors, artifact = validate_artifact(artifact_path, packet_hash) if packet_hash else (["cannot validate artifact without packet hash"], {})
    errors.extend(artifact_errors)
    errors.extend(validate_paths(args.evidence, "evidence", require_existing=not args.no_require_evidence_path))
    errors.extend(validate_paths(args.changed_file, "changed-file", require_existing=False))

    if errors:
        print("BLOCK: closure gate failed", file=sys.stderr)
        for err in errors:
            print(f"- {err}", file=sys.stderr)
        return 2

    profile = _profile_name()
    manifest = {
        "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gate": f"{profile}_claude_review_v1",
        "verdict": "PASS",
        "task_id": args.task_id,
        "result": args.result,
        "packet_path": str(packet_path),
        "packet_sha256": packet_hash,
        "review_artifact_path": str(artifact_path),
        "review_artifact_sha256": sha256_file(artifact_path),
        "reviewer": artifact.get("reviewer"),
        "review_task": artifact.get("task"),
        "evidence_paths": [str(Path(p).expanduser()) for p in args.evidence],
        "changed_files": [str(Path(p).expanduser()) for p in args.changed_file],
    }

    out_path = Path(args.manifest_out).expanduser() if args.manifest_out else default_manifest_path(args.task_id, packet_hash)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: closure gate passed")
    print(f"MANIFEST: {out_path}")
    print(f"PACKET_SHA256: {packet_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
