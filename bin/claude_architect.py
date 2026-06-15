#!/usr/bin/env python3
"""Safe Claude Code architecture/planning helper — shared across all Hermes profiles.

Usage:
  python3 claude_architect.py "Сформируй архитектурный план ..."
  cat context.md | python3 claude_architect.py "Разбери вводные и дай план"

Profile is resolved from HERMES_HOME env var (set automatically by hermes-gateway@<profile>.service).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

DISALLOWED_TOOLS = ["Bash", "Read", "Edit", "Write", "Grep", "Glob", "WebSearch", "WebFetch", "Task", "TodoWrite", "NotebookEdit", "ExitPlanMode"]

SYSTEM = """Ты Claude Code в роли внешнего архитектора/планировщика для агента Hermes.
Пользователь: Василий, INTP / «Инноватор».
Твоя задача — не исполнять действия и не менять файлы, а дать ясный архитектурный/операционный план.
Пиши по-русски, подробно, структурно, без таблиц и воды.
Адаптация под INTP: сначала короткий вывод, затем логика и evidence; отделяй факты от гипотез; показывай причинно-следственные связи, trade-off вариантов и критерии выбора; избегай давления авторитетом, морализаторства и мотивационных лозунгов.
Фокус: варианты решения, риски, зависимости, порядок шагов, критерии готовности, что поручить Hermes/Codex.
План должен быть достаточно подробным, чтобы Hermes/Codex мог выполнять его без повторного уточнения: указывай этапы, порядок действий, проверки, артефакты, владельцев и условия остановки/блокировки.
Для больших задач обязательно дай ближайшее next action, чтобы анализ не зависал без исполнения.
Не проси секреты. Не выполняй платные, внешние, destructive или account-mutating действия.
Не используй инструменты Claude Code: не читай файлы, не запускай Bash, не редактируй. Работай только с контекстом, переданным в prompt/stdin.
Если вводных не хватает, перечисли точные вопросы/блокеры.
"""


def build_prompt(task: str, stdin_context: str) -> str:
    chunks = [SYSTEM.strip(), "", "Задача от Hermes-агента:", task.strip()]
    if stdin_context.strip():
        chunks += ["", "Контекст:", stdin_context.strip()]
    chunks += [
        "",
        "Верни результат в формате:",
        "- Короткий вывод",
        "- Архитектурное решение / подход",
        "- Подробный план выполнения для Hermes/Codex",
        "- Acceptance criteria / критерии приёмки",
        "- Proof path / какие проверки и артефакты должны подтвердить готовность",
        "- Риски/блокеры и условия остановки",
        "- Что должен сделать Hermes/Codex дальше",
    ]
    return "\n".join(chunks)


def claude_cmd(prompt: str, max_turns: int) -> list[str]:
    return [
        "claude",
        "-p",
        prompt,
        "--max-turns",
        str(max_turns),
        "--output-format",
        "json",
        "--disallowedTools",
        *DISALLOWED_TOOLS,
    ]


def run_claude(cmd: list[str], timeout: int, attempts: int) -> subprocess.CompletedProcess[str]:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, attempts + 1):
        last = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, env=os.environ.copy())
        if last.returncode == 0:
            return last
        if attempt < attempts:
            continue
    assert last is not None
    return last


def extract_result(stdout: str, stderr: str) -> str:
    try:
        data = json.loads(stdout)
    except Exception:
        return ((stdout or "") + (stderr or "")).strip()
    return (data.get("result") or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask Claude Code for planning/architecture advice.")
    parser.add_argument("task", nargs="+", help="Planning question/task for Claude")
    parser.add_argument("--timeout", type=int, default=240, help="Timeout seconds per attempt")
    parser.add_argument("--max-turns", type=int, default=4, help="Claude print-mode max turns")
    parser.add_argument("--attempts", type=int, default=2, help="Retry attempts for transient Claude CLI failures")
    args = parser.parse_args()

    task = " ".join(args.task)
    stdin_context = sys.stdin.read() if not sys.stdin.isatty() else ""
    prompt = build_prompt(task, stdin_context)
    cmd = claude_cmd(prompt, args.max_turns)

    try:
        proc = run_claude(cmd, timeout=args.timeout, attempts=max(1, args.attempts))
    except FileNotFoundError:
        print("BLOCK: claude CLI не найден в PATH", file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired:
        print("BLOCK: Claude architect не ответил до timeout", file=sys.stderr)
        return 124

    raw = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        print("BLOCK: claude CLI завершился с ошибкой", file=sys.stderr)
        print(raw[:4000], file=sys.stderr)
        return proc.returncode

    result = extract_result(proc.stdout, proc.stderr)
    if not result:
        print("BLOCK: Claude architect вернул пустой результат", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
