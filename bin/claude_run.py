#!/usr/bin/env python3
"""claude_run — execute a Claude subtask at a chosen model tier.

Used by the orchestrator for `claude:<tier>` subtasks (routing by complexity).
Safe invocation: no plan mode (avoids the ExitPlanMode loop), agentic tools
disallowed, 429/transient backoff. Tier = haiku | sonnet | opus (or full id).

Usage:
  claude_run.py --model haiku "коротко: что такое MCP"
  echo "<context>" | claude_run.py --model sonnet "проанализируй и дай вывод"
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

DISALLOW = ["Bash", "Read", "Edit", "Write", "Grep", "Glob", "WebSearch",
            "WebFetch", "Task", "TodoWrite", "NotebookEdit", "ExitPlanMode"]
ALIASES = {"haiku": "haiku", "sonnet": "sonnet", "opus": "opus"}


def run(prompt: str, model: str, timeout: int, attempts: int) -> tuple[int, str]:
    cmd = ["claude", "-p", prompt, "--model", model,
           "--output-format", "json", "--max-turns", "3",
           "--disallowedTools"] + DISALLOW
    last = ""
    for attempt in range(1, attempts + 1):
        try:
            p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            last = "timeout %ss" % timeout
            time.sleep(3 * attempt)
            continue
        out = p.stdout or ""
        if p.returncode == 0:
            import json
            try:
                data = json.loads(out)
                if not data.get("is_error"):
                    return 0, (data.get("result") or "").strip()
                last = "is_error: " + out[:200]
            except Exception:
                return 0, out.strip()
        else:
            last = "rc=%d %s" % (p.returncode, (out or p.stderr or "")[:200])
        # 429 / rate-limit -> long backoff
        time.sleep(25 if ("429" in out or "rate" in out.lower() or "overloaded" in out.lower())
                   else 3 * attempt)
    return 1, "BLOCK: claude_run failed after %d attempts: %s" % (attempts, last)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a Claude subtask at a chosen tier.")
    ap.add_argument("task", nargs="+")
    ap.add_argument("--model", default="sonnet", help="haiku|sonnet|opus or full model id")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--attempts", type=int, default=3)
    args = ap.parse_args()

    task = " ".join(args.task)
    model = ALIASES.get(args.model, args.model)
    stdin_ctx = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    prompt = task if not stdin_ctx else (task + "\n\nКонтекст:\n" + stdin_ctx)

    rc, text = run(prompt, model, args.timeout, max(1, args.attempts))
    print(text)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
