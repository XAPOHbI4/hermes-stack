# hermes-stack

Слой операций поверх [Hermes-agent](https://github.com/NousResearch/hermes-agent): превращает
«голую» установку Hermes в настроенную, самонаблюдающую и самообучающуюся команду AI-агентов,
которой можно доверить реальную операционку и **видеть, что она делает**.

Это **не форк и не движок** — тонкий версионируемый без-секретный слой (контракты + скрипты +
systemd-таймеры + кроны + провижинер), который накатывается на сток.

## Что даёт
Ставишь задачу в Telegram → система дробит её на подзадачи, раздаёт профильным агентам, проверяет
результат **с доказательством**, присылает готовое. Сама себя мониторит, чинит и раз в неделю
анализирует качество.

- **Делегирование словами** — Telegram единственная точка входа.
- **Качество с пруфом** — нельзя закрыть «отчётиком»: нужен вердикт ревьюера + evidence.
- **Автономность** — упавшее перезапускается, лимиты подписок под присмотром.
- **Самообучение** — недельный разбор слабых мест (Claude) в Telegram.
- **Воспроизводимость** — настройка в Git, клон за минуты.

## Архитектура (поток задачи)
`Telegram → оркестратор → decompose (Kanban --triage, нативный декомпозер gpt-5.4-mini роутит
специалистам) → исполнение специалистом (Codex gpt-5.5, grind-to-result) → независимое ревью
Claude (PASS/REWORK/BLOCK) + proof policy → closure_gate → результат в Telegram.`

Поверх — два внешних контура на systemd-таймерах (не зависят от шлюза):
- **Надёжность**: health ежечасно (+лимиты Claude/Codex), watchdog 10м, decompose-sweep 10м.
- **Обучение**: недельный eval-дайджест качества → рефлексия Claude → уроки в Telegram.

## Ключевые решения (нюансы)
- **Engine-first decompose**, а не «агент сам зовёт architect-тул» — soft-промпт провалился 3/3
  (модель забывала дёрнуть тул). Дробит платформа; модель решает роутинг/сложность.
- **Тонкое ядро AGENTS.md (≤12KB)** + `references/` по требованию — экономия контекста.
- **Адверсариальный proof-gate**: отдельный Claude-ревьюер, «self-report → REWORK по умолчанию».
- **Proof policy**: тип доказательства = тип задачи (behavior-changing → ≥smoke с логом запуска,
  не document). Правило в промпте ревьюера, не хардкод-гейт — чтобы остаться model-driven.
- **`pid not alive` ≠ провал**: воркер = дочерний процесс шлюза; рестарт шлюза его SIGKILL-ит,
  ретраи восстанавливают. Рестартить graceful (`gw-restart`, SIGUSR1 drain), не `systemctl restart`.
  Метрики отделяют process-death от task-failure.
- **Лимиты = окна, не деньги**: Claude — oauth usage (5h/7d); Codex — `rate_limits` в session-rollout.
- **`claude_run.py` без plan-mode** — сырой `--permission-mode plan` уходит в ExitPlanMode-петлю.
- **Доставка `sendRichMessage`** — нативные TG-таблицы; одиночный `\n` схлопывается, широкие
  таблицы скроллят на мобиле → эмодзи-заголовки колонок.

## Структура репо
```
profiles/   22 контракта (AGENTS.md, SOUL.md, config.yaml, references/)
bin/        операционные скрипты (см. ниже)
systemd/    10 unit-файлов (таймеры health/eval/lessons/decompose/watchdog)
crons.manifest.txt   определения кронов (Джарвис, здоровье, дайджесты)
.env.example  env-ключи (токены + TG-привязка)
install.sh    идемпотентный провижинер
```

### bin/
| Скрипт | Назначение |
|---|---|
| `hermes_eval_digest.py` | недельный дайджест качества по Kanban; отделяет рестарт-шум от провалов; `--md` → нативная таблица |
| `hermes_eval_alert.sh` | дайджест → Telegram (rich) |
| `hermes_lessons.py` / `_alert.sh` | рефлексия Claude над метриками → «уроки недели» → Telegram |
| `hermes_healthcheck.sh` | read-only health, 10 блоков (шлюзы, watchdog, kanban, auth, ресурсы, ошибки, гигиена скиллов, routing, лимиты Claude, лимиты Codex) |
| `hermes_health_alert.sh` | почасовой аудит, алерт в TG только при WARN |
| `kanban_watchdog.sh` | рестарт упавшего шлюза + recovery-dispatch |
| `kanban_decompose_sweep.sh` | свип triage → decompose |
| `claude_run.py` | безопасный вызов Claude на тире (no plan-mode, 429 backoff) |
| `claude_architect.py` | Claude-архитектор (план/разбиение сложного) |
| `claude_reviewer.py` | Claude-ревьюер (вердикт + proof policy) |
| `closure_gate.py` | гейт закрытия (вердикт + 7 секций + sha256) |
| `codex_usage.py` | лимиты Codex из свежего session-rollout |
| `rich_send.py` | нативный Telegram rich-message (Bot API 10.1) |
| `skill_audit.py` | счётчик коллизий имён скиллов + мёртвых провайдеров |
| `backup_drill.sh` | scoped-бэкап + restore-тест |
| `clean_disabled.sh` | архивация-затем-удаление `*.disabled`-скиллов (обратимо: полный tar-архив + filelist) |
| `hermes_ops.py` | control-plane врапперы над нативными Kanban/MCP/Profile-командами (для кронов и ручных серверных операций, без печати секретов) |
| `hermes_runtime.py` | рантайм-утилиты (Kanban/метрики/доставка), общий слой для скриптов выше |

## Развёртывание (3 яруса)
Накатывается на уже установленный сток снизу вверх. Всё, кроме яруса 2, идемпотентно.

**Ярус 0 — сток Hermes (предусловие, не входит в репо).** На таргете уже стоит базовый
Hermes-agent и `hermes` есть в `PATH`:
```bash
git clone https://github.com/NousResearch/hermes-agent /root/.hermes/hermes-agent
cd /root/.hermes/hermes-agent && ./setup-hermes.sh
```
`install.sh` падает с инструкцией, если стока нет.

**Ярус 1 — провижинер слоя (`install.sh`, идемпотентный, от root).** Копируешь
`.env.example → .env`, заполняешь, запускаешь `./install.sh`. Он:
1. проверяет предусловия (`hermes` на PATH, наличие `.env`, обязательные `TG_*`-ключи);
2. кладёт `bin/*` → `$HERMES_RUNTIME/bin`, делает исполняемыми;
3. мёржит `profiles/*` поверх `$HERMES_PROFILES_HOME/profiles` (никогда не затирает живое состояние) — 22 контракта;
4. подставляет инстанс-плейсхолдеры (`__TG_HOME_CHAT__`, `__TG_COMPANY_GROUP__`, `__TG_OPERATOR_ID__`) и раскладывает per-profile `.env`;
5. ставит и поднимает 5 systemd-таймеров (`hermes-health`, `hermes-eval`, `hermes-lessons`, `kanban-decompose`, `kanban-watchdog`).

**Ярус 2 — ручные per-instance шаги (не автоматизируются, печатаются в конце `install.sh`).**
1. **Auth** (намеренно вне бандла, провижинится на каждый инстанс): `/root/.codex/auth.json` (`codex login`), `/root/.claude/.credentials.json` (`claude login`);
2. **Кроны** — пересоздать из `crons.manifest.txt`: `hermes --profile <p> cron add …`;
3. **Шлюзы** — `hermes --profile orchestrator gateway install` + `systemctl enable --now hermes-gateway@orchestrator`;
4. **Верификация** — `bash $HERMES_RUNTIME/bin/hermes_healthcheck.sh`.

## Что НЕ входит
Репо — без-секретный слой; всё инстанс-специфичное и runtime-состояние держится вне Git (см. `.gitignore`):
- **Секреты и auth** — реальные значения `.env`, `auth.json`, `.credentials.json`, MCP-токены, Notion-ключи. В репо только `.env.example` с пустыми ключами.
- **Движок Hermes** — это не форк; сам `hermes-agent` ставится отдельно (ярус 0).
- **Runtime-состояние** — `state.db`/`*.sqlite`, `kanban/`, `memory*/`, `closures/`, `reviews/`, `reports/`, `sessions/`, `logs/`. Чистый клон стартует пустым.
- **Бэкапы и архивы** — `*.tar.gz`, `*.bak*`.
- **Живые кроны** — в Git лежат только определения (`crons.manifest.txt`), не сами зарегистрированные задачи; их пересоздаёшь вручную (ярус 2).

## Статус / оговорки
- **Заточен под конкретный инстанс.** Профили, кроны и TG-привязка отражают одну боевую установку (single-node, `root@…`, Linux + systemd). Это рабочий слой, а не дистрибутив общего назначения.
- **Таргет — Linux/systemd от root.** Пути захардкожены под `/root` (переопределяются через `HERMES_PROFILES_HOME` / `HERMES_RUNTIME`). На не-systemd / не-root окружениях ярус 1 не пройдёт.
- **Кроны портативны, но не слепо.** Расписания и тела переносятся как есть; в манифесте есть одноразовые/датированные задачи (`once at …`) — перед применением на новом инстансе ревьюь.
- **`install.sh` мёржит, не синхронизирует.** Обновлённые контракты накатываются поверх; удаление профиля из репо не удаляет его на таргете — это сознательно (никогда не трогаем живое состояние).
- **Внешние контуры независимы от шлюза.** Health/eval/lessons/decompose/watchdog работают на systemd-таймерах, поэтому переживают падение и рестарт шлюзов (см. `pid not alive` выше).