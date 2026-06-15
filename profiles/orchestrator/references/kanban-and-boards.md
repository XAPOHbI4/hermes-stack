# Kanban, proof contract, board routing

## Proof contract (HERMES_KANBAN_PROOF_CONTRACT_V1)
For every non-trivial task work through Hermes Kanban, not chat text. One card = one owner; multi-agent work = linked child cards with explicit dependencies.

Keep status durable: claim/heartbeat/comment; create/update a concrete artifact; close only with evidence. A task is not done because a worker replied in a session.

Close with structured completion data:
```bash
hermes kanban --board <board> complete <task_id> \
  --result "short user-facing result" \
  --summary "handoff/final summary for downstream tasks" \
  --metadata '{"artifact_path":"/absolute/path/or/n/a","proof_type":"test|smoke|review|document|config|n/a","verified_by":"<profile>","verdict":"PASS|BLOCK|REWORK","changed_files":[],"tests_run":[],"next_owner":"orchestrator|profile|none"}'
```
If it cannot be proven, do not fake proof. Block with a short human-readable reason and name the exact missing input/credential/approval/data/system. Human-required blockers → Approvals; auto-solvable → follow-up/rework cards.

### Proof policy: тип proof обязан соответствовать типу задачи
Слабое доказательство для сильной задачи = задача НЕ закрыта. Подбирай `proof_type` под характер работы:
- **Меняет поведение системы** (внедрить / настроить / добавить роль или skill / правка конфига, влияющего на работу агента) → минимум `proof_type: smoke` с **логом реального вызова** (артефакт выполнения: что запущено, ожидаемый vs фактический вывод). `document`/`config` сами по себе НЕ закрывают такую задачу — это лишь описание, а не подтверждение, что правило работает.
- **Инцидент / починка** → `proof_type: smoke` ПЛЮС подтверждение отсутствия повторного симптома (лог/снапшот мониторинга минимум через ~1ч после фикса). «Запустилось» ≠ «не повторяется».
- **Чистый research / текст / политика без изменения поведения** → `document` допустим (это и есть артефакт).
- **BLOCK обязан нести причину блокировки** — конкретное недостающее (доступ/данные/решение). Без причины в статус blocked не переводить.
Правило одной фразой: архитектура/внедрение → ≥smoke, инцидент → smoke+monitor, только pure-doc → document.

Kanban principle: **route, don't execute. Decompose, route, summarize.** Kanban = durable state machine (survives restart). `delegate_task` = quick synchronous subagent in one turn. Verify Kanban exists via `hermes kanban --help`; if absent, do not simulate it with prompts.

## Long-running tasks: goal mode (grind to result)
For a task that must keep working until a concrete result — not just one pass — create the card in **goal mode** with explicit acceptance criteria in the body:
```bash
hermes kanban --board <board> create "<title>" --assignee <profile> \
  --goal --goal-max-turns 8 --max-retries 2 \
  --body "Цель: ... Шаги: ... ACCEPTANCE (закрывать только при выполнении всех): <проверяемые условия: файл существует / тест зелёный / разделы присутствуют>. Работай в реальной системе, без выдумок. Закрой с proof."
```
- The worker iterates (up to `--goal-max-turns`), self-verifies against ACCEPTANCE, and closes only with proof. Failed runs retry up to `--max-retries`.
- ALWAYS put **verifiable** acceptance in the body (a file path, a passing check, required sections) — that is the stop condition. No acceptance = no goal mode.
- Durability: the in-gateway dispatcher runs cards every 60s; an external systemd watchdog (`kanban-watchdog.timer`) restarts the gateway if it dies, so a long grind resumes after a crash. You do not need a custom loop.
- Bound cost: keep `--goal-max-turns`/`--max-retries` modest; the acceptance criterion is the real guard against runaway.

Do not save temporary progress/noise into permanent memory. Save durable lessons, decisions, reusable artifacts, final handoff references only.

## Russian output & department boards (HERMES_RUSSIAN_KANBAN_OUTPUT_V1)
User-facing Telegram replies, Kanban summaries, blockers and final reports — **Russian**. Machine metadata keys stay English when tools require.

Choose BOTH department board and worker profile before creating a non-trivial task. Boards: `company-runtime`, `it-devops`, `engineering`, `product`, `smm-department`, `marketing`, `research`, `support`, `security`, `finance`, `qa-review`. Do not dump everything into `system-changes`/`company-runtime`.

Board routing defaults:
- IT/server/cron/MCP/n8n → `it-devops` with `itops`/`devops`
- code/API/frontend/backend/QA → `engineering` with `backend`/`frontend`/`qa`
- product/PRD/UX/roadmap → `product`
- SMM/content/posts/YouTube → `smm-department`
- marketing/funnel/offers → `marketing`
- research/sources/social intelligence → `research`
- support/tickets/helpdesk → `support`
- security/auth/approval/risk → `security`
- finance/payment/budget → `finance`
- review/proof/rework → `qa-review`

## AI agent course mode (AI_AGENT_COURSE_ORCHESTRATOR_MODE_V1)
For the AI-agents learning/course project use board `ai-agent-course-content`, separate from Znaki, Rutoll/Telematika support, and general company-runtime. Orchestrator acts as Content Producer:
- map request to existing profiles before proposing new ones; prefer extending ai-mentor, research, product, content, reviewer, ux, smm, marketing, analyst, qa;
- create Kanban fan-out only after owners, dependencies, acceptance criteria and proof path are identified;
- shared artifacts in `/root/hermes/runtime/projects/ai-agent-course-content`: `BOARD_CONTEXT.md`, `ROLE_MAPPING.md`, `LESSON_KANBAN_TEMPLATE.md`;
- close course tasks only with artifact path + proof metadata.
