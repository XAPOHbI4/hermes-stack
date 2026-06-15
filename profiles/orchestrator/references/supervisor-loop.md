# Supervisor loop — decomposition, routing by complexity, closure

Authoritative working loop for the orchestrator. **Claude thinks (plan/route); specialists/Codex execute.** No hardcoded if-else: for non-standard tasks pass them to Claude and follow its breakdown. The contract is only the process frame.

## When this loop applies
- Any non-trivial or cross-functional intake task (not a one-line question, not chit-chat).
- Trivial (greeting, status, short fact) → answer directly, skip decomposition.

## STEP 0 — reality check before doing anything
Do not act reflexively. First verify what already exists on the server:
- **Find the project locally first. Do NOT clone from GitHub by default.**
  - typical path: `/root/hermes/workspace/projects/<name>`
  - search: `find /root/hermes/workspace/projects -maxdepth 2 -iname '*<name>*'` and `find /root -maxdepth 4 -type d -iname '*<name>*'`
  - clone from GitHub ONLY if no local copy exists (and say so explicitly).
- If the project runs as a service (`systemctl list-units '<name>-*'`), audit/change it in its real directory and check the live services. **Do not build parallel copies or venvs in /tmp** when a working install exists.

## STEP 1 — decompose (engine-first, reliable)
**Primary path — native Kanban auto-decompose** (does not depend on the model remembering to call anything):
```bash
hermes kanban --board <board> create "<task>" --triage --body "<goal + context>"
```
A triaged task is automatically broken into specialist child-tasks (and routed to the right profile: research/smm/product/devops/…) by the engine decomposer, swept every ~10 min by `kanban-decompose.timer`. Root wakes when all children complete. To force it immediately: `hermes kanban --board <board> decompose <task_id>`.

**Optional — Claude architect** for genuinely complex/architectural/high-risk tasks where you want a stronger plan or model-tier guidance before decomposing:
```bash
HERMES_HOME=$HERMES_HOME python3 $HERMES_HOME/bin/claude_architect.py "Разбей задачу на подзадачи: [сложность] | [исполнитель] | [уровень модели] | [подзадача] | [критерии] | [зависит от #]. Задача: <текст>"
```
Use architect when the task needs design/risk reasoning; otherwise the native `--triage` decompose is enough and reliable.

## STEP 2 — executor field (Claude picks ONE)
- `specialist:<profile>` — domain work goes to a specialist profile via Kanban. Allowed: backend, frontend, qa, devops, itops, security, research, analyst, product, ux, content, smm, marketing, finance, support, ai-mentor, reviewer, curator.
- `claude:<tier>` — pure reasoning/analysis/text/architecture better done by Claude directly (no files/commands).
- `codex` — quick file/command work by the supervisor itself, no separate specialist.

## STEP 3 — model tier by complexity
- complexity 1-2 → `haiku` (fast/cheap) or specialist on its default model
- complexity 3 → `sonnet`
- complexity 4-5 → `opus`; on high risk/ambiguity — panel (several opinions) + separate judge

For `claude:<tier>` use the safe wrapper (no plan-mode loop, 429 backoff):
```bash
HERMES_HOME=$HERMES_HOME python3 $HERMES_HOME/bin/claude_run.py --model <haiku|sonnet|opus> "<подзадача с контекстом>"
# или с контекстом через stdin:
echo "<context>" | python3 $HERMES_HOME/bin/claude_run.py --model sonnet "<подзадача>"
```
Do NOT call raw `claude -p --permission-mode plan` for execution — it triggers an ExitPlanMode loop and times out.
For `specialist:<profile>` the tier = priority/depth in the Kanban card (specialist runs on its own provider).

## STEP 4 — dispatch via native Kanban
- One card per subtask with explicit handoff: source, current state, owner (profile), dependencies, acceptance criteria, proof path.
- Respect the `зависит от #` field: do not start a subtask until its dependencies are closed. Independent subtasks may run in parallel.
- See `references/kanban-and-boards.md` for board routing and the proof contract.

## STEP 5 — review and closure (never on trust)
- After a subtask — independent Claude review by evidence, not self-report.
- Final closure через `closure_gate` с PASS + proof. Codex не закрывает важное сам.
- Invocations: see `references/claude-architect-reviewer.md`.

## Execution discipline (state machine) — against "imitating work / silence / stuck"
States: `idle → working → checkpoint → {done | next_step | need_input | blocked} / stuck / handoff`.
- The most dangerous state is endless `working` (not blocked).
- No more than ~5 min in `working` without a checkpoint; each checkpoint names: current_state, progress_delta, next_action.
- 2 checkpoints without progress_delta → declare `stuck` (where stuck + what checked + 1 hypothesis + 1 minimal test).
- Before timeout/compaction → `handoff` (goal/done/not-done/blocker/next step).
- **Forbidden:** empty "продолжаю работать". Actions, not promises: plan → wait "ок" → execute → "Готово".
- Completion standard: a task is done when the work is finished OR a real blocker is named — never a plan/analysis alone.
