# Архитектура (текущая)

## Поток задачи
```
Telegram → orchestrator (тонкое ядро AGENTS.md + references/)
  → decompose (Kanban --triage, нативный декомпозер роутит специалистам)
  → исполнение специалистом (grind-to-result)
  → независимое ревью Claude (PASS/REWORK/BLOCK) + proof policy
  → closure_gate (proof) → результат в Telegram
```

## Слои знаний (separation of concerns)
- **AGENTS.md** — тонкое ядро: роль + hard rules + таблица триггеров → грузит нужный `references/*`.
- **references/** — операционные контракты: supervisor-loop, kanban-and-boards (proof policy), telegram-routing/ux, claude-architect-reviewer, source-map (trust pyramid), change-safety (risk levels), memory-policy, main-agent-unpacking, integrations-style-forge.
- **wiki/** — этот слой: текущие решения/архитектура.
- **profile memory** — стабильные предпочтения (правила в memory-policy).
- **reports/closures/reviews + Kanban** — доказательства и состояние задач.
- **USER.md** — owner-context (стиль/предпочтения/проекты владельца).

## Контуры (внешние systemd-таймеры, не зависят от шлюза)
- **Надёжность:** health ежечасно (+лимиты Claude/Codex), watchdog 10м, decompose-sweep 10м, per-profile smoke daily.
- **Обучение:** eval-дайджест недельно → рефлексия Claude → уроки в Telegram.
- **Апстрим:** update-watcher недельно (что нового в Hermes / чем полезно нам / риски), read-only.

## Провайдеры
- Исполнение/специалисты: Codex (gpt-5.5/5.4/5.4-mini) — подписка.
- Архитектор/ревьюер/claude_run: Claude (подписка, OAuth) — независимый судья proof-гейта.
- Лимиты = окна (5h/7d), не деньги; мониторятся.
- *(Эксперимент, отдельно: локальный Qwen на ПК как мозг оркестратора — НЕ в этом серверном контуре.)*

## Доставка
`sendRichMessage` (нативные Telegram-таблицы); длинное режется на части `(k/n)` в `rich_send.py`.

## Безопасность
Reversible (.bak/.disabled); destructive/config/publish/restart → approval (change-safety L0–L5); секреты не в md/memory/chat/git; leak_scan перед публикацией; gateway restart — graceful (`gw-restart`).
