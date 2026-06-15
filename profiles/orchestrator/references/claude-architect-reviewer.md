# Claude as external architect & reviewer

Claude Code is wired as an external architecture/planning + review layer via CLI wrappers. Hermes/Codex runs the external CLI, gets text/JSON artifact, then executes/verifies itself.

Rules:
- Main executor — Hermes/Codex: changes files, runs checks, collects evidence.
- Claude as **architect** — for complex tasks: architecture, decomposition, technical plan, risk assessment.
- Claude as **reviewer** — independent acceptance by plan, acceptance criteria and evidence.
- Claude does not perform external actions, does not read files, does not run Bash.
- Codex must not self-accept important tasks: final closure requires Claude review or explicit smoke/proof.

## Architect
```bash
HERMES_HOME=$HERMES_HOME python3 $HERMES_HOME/bin/claude_architect.py "задача для архитектурного разбора"
```

## Reviewer
```bash
HERMES_HOME=$HERMES_HOME python3 $HERMES_HOME/bin/claude_reviewer.py "проверь результат" < /path/to/review_packet.md
```

## Closure gate (after reviewer)
```bash
HERMES_HOME=$HERMES_HOME python3 $HERMES_HOME/bin/closure_gate.py \
  --packet /path/to/review_packet.md \
  --review-artifact $HERMES_HOME/reviews/claude_review_....json \
  --evidence /path/to/test.log \
  --task-id "task-id" \
  --result "короткий результат"
```

Reviewer verdict:
- PASS — можно закрывать.
- REWORK — нужна доработка.
- BLOCK — нужен внешний ввод.

Review packet template: `/root/.hermes/profiles/personalassistant/templates/review_packet.md`
