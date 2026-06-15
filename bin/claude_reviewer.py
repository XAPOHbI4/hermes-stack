#!/usr/bin/env python3
"""Safe Claude Code review/acceptance helper — shared across all Hermes profiles.

Artifact directory resolved from REVIEW_ARTIFACT_DIR env var,
or defaults to $HERMES_HOME/reviews (set automatically per profile by systemd).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

VALID_VERDICTS = {"PASS", "REWORK", "BLOCK"}
DISALLOWED_TOOLS = ["Bash", "Read", "Edit", "Write", "Grep", "Glob", "WebSearch", "WebFetch", "Task", "TodoWrite", "NotebookEdit", "ExitPlanMode"]
DEFAULT_MIN_PACKET_CHARS = 500


def _default_artifact_dir() -> str:
    hermes_home = os.environ.get("HERMES_HOME", "/root/.hermes/profiles/personalassistant")
    return os.environ.get("REVIEW_ARTIFACT_DIR", os.path.join(hermes_home, "reviews"))


SYSTEM = """Ты Claude Code в роли внешнего reviewer/приёмщика для агента Hermes.
Пользователь: Василий, INTP / «Инноватор».
Основной исполнитель — Hermes/Codex. Твоя задача — не делать работу и не менять файлы, а независимо проверить результат по плану, acceptance criteria и evidence.
Пиши по-русски, структурно, без таблиц и без воды.
Адаптация под INTP: сначала логически обоснуй verdict через evidence; отделяй факты от предположений; явно показывай, какие критерии закрыты, а какие нет; избегай общих похвал без доказательств.
Не проси секреты. Не выполняй платные, внешние, destructive или account-mutating действия.
Не используй инструменты Claude Code: не читай файлы, не запускай Bash, не редактируй. Работай только с review packet, переданным в stdin.
Не принимай работу на доверии: если evidence недостаточно, ставь REWORK или BLOCK.
Перед PASS обязательно перечисли причины, почему это могло бы быть REWORK/BLOCK. Только если таких причин нет или они явно закрыты evidence, ставь PASS.
Если evidence неоднозначно, неполно, противоречиво или основано только на self-report исполнителя — по умолчанию REWORK.
Сверяй ТИП доказательства с ТИПОМ задачи (proof policy):
- Задача меняет поведение системы (внедрение/настройка/роль/skill/конфиг, влияющий на работу агента), а proof_type = document/config БЕЗ артефакта реального запуска (лог вызова, ожидаемый vs фактический вывод) → REWORK: описание не доказывает, что правило работает.
- Задача — инцидент/починка, но нет подтверждения отсутствия повторного симптома (лог/снапшот мониторинга спустя время после фикса) → REWORK.
- proof_type=document допустим только для чистого research/текста/политики без изменения поведения.
Вердикт должен быть одним из:
- PASS — можно закрывать: критерии выполнены и evidence достаточно.
- REWORK — нужна доработка исполнителем: работа возможна, но есть конкретные несоответствия/недостающие проверки.
- BLOCK — нельзя продолжить без внешнего входа: нужен доступ, подтверждение, данные, решение человека или недоступная система.
"""


def build_prompt(task: str, stdin_context: str) -> str:
    chunks = [SYSTEM.strip(), "", "Задача на ревью от Hermes-агента:", task.strip()]
    chunks += ["", "Пакет на ревью:", stdin_context.strip()]
    chunks += [
        "",
        "Верни результат строго в таком формате. Первая непустая строка должна быть ровно одной из трёх:",
        "Вердикт: PASS",
        "Вердикт: REWORK",
        "Вердикт: BLOCK",
        "",
        "Проверено:",
        "- что именно сверено с планом/критериями",
        "",
        "Почему это могло бы быть REWORK/BLOCK:",
        "- перечисли сомнения перед PASS; если verdict не PASS, перечисли причины verdict",
        "",
        "Несоответствия:",
        "- если нет, напиши: нет подтверждённых несоответствий",
        "",
        "Что доработать:",
        "- конкретные действия для Hermes/Codex; если PASS, напиши: не требуется",
        "",
        "Evidence:",
        "- какие файлы, команды, тесты, логи или артефакты подтверждают вывод",
        "",
        "Финальный статус:",
        "- можно закрывать / нельзя закрывать / ждать внешний ввод",
    ]
    return "\n".join(chunks)


def claude_cmd(prompt: str, max_turns: int) -> list[str]:
    return [
        "claude", "-p", prompt,
        "--max-turns", str(max_turns),
        "--output-format", "json",
        "--disallowedTools", *DISALLOWED_TOOLS,
    ]


def run_claude(cmd: list[str], timeout: int, attempts: int) -> subprocess.CompletedProcess[str]:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, attempts + 1):
        last = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, env=os.environ.copy())
        if last.returncode == 0:
            return last
    assert last is not None
    return last


def extract_result(stdout: str, stderr: str) -> str:
    try:
        data = json.loads(stdout)
    except Exception:
        return ((stdout or "") + (stderr or "")).strip()
    return (data.get("result") or "").strip()


def extract_verdict(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.fullmatch(r"Вердикт:\s*(PASS|REWORK|BLOCK)", stripped, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return None
    return None


def write_artifact(artifact_dir: str, task: str, packet: str, result: str, verdict: str) -> Path:
    out_dir = Path(artifact_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    packet_hash = hashlib.sha256(packet.encode("utf-8")).hexdigest()
    path = out_dir / f"claude_review_{ts}_{packet_hash[:12]}.json"
    artifact = {
        "created_at": ts,
        "reviewer": "claude",
        "task": task,
        "verdict": verdict,
        "packet_sha256": packet_hash,
        "raw_output": result,
    }
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask Claude Code to review Codex/Hermes work.")
    parser.add_argument("task", nargs="+")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--min-packet-chars", type=int, default=DEFAULT_MIN_PACKET_CHARS)
    parser.add_argument("--artifact-dir", default=_default_artifact_dir())
    args = parser.parse_args()

    task = " ".join(args.task)
    stdin_context = sys.stdin.read() if not sys.stdin.isatty() else ""
    packet = stdin_context.strip()
    if len(packet) < args.min_packet_chars:
        print(f"BLOCK: review packet слишком короткий ({len(packet)} < {args.min_packet_chars})", file=sys.stderr)
        return 1

    prompt = build_prompt(task, packet)
    cmd = claude_cmd(prompt, args.max_turns)

    try:
        proc = run_claude(cmd, timeout=args.timeout, attempts=max(1, args.attempts))
    except FileNotFoundError:
        print("BLOCK: claude CLI не найден в PATH", file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired:
        print("BLOCK: Claude reviewer не ответил до timeout", file=sys.stderr)
        return 124

    if proc.returncode != 0:
        print("BLOCK: claude CLI завершился с ошибкой", file=sys.stderr)
        print(((proc.stdout or "") + (proc.stderr or ""))[:4000], file=sys.stderr)
        return proc.returncode

    result = extract_result(proc.stdout, proc.stderr)
    if not result:
        print("BLOCK: Claude reviewer вернул пустой результат", file=sys.stderr)
        return 1

    verdict = extract_verdict(result)
    if verdict not in VALID_VERDICTS:
        print("BLOCK: Claude reviewer не вернул валидный verdict первой строкой", file=sys.stderr)
        print(result[:4000], file=sys.stderr)
        return 2

    artifact_path = write_artifact(args.artifact_dir, task, packet, result, verdict)
    print(result)
    print(f"\nARTIFACT: {artifact_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
