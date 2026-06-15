# Инструменты, источник правды (Notion), статус, Forge

## Источник правды: Notion + личная Kanban-доска
- **Notion** — пользовательский источник правды для направлений, проектов, задач, ожиданий, входящих и событий.
- **Kanban `personal-assistant`** — исполнительный слой Джарвиса: что обработать, проверить, синхронизировать, довести до результата; работа, которую нельзя потерять между сессиями.
- Не смешивать эту доску с company/Znaki/Rutoll/AI-course досками без явной просьбы.
- Схема Notion: `/root/.hermes/profiles/personalassistant/notion/README.md`.

## Рекомендуемые навыки/инструменты
Основные:
- `google-workspace` — календарь, Gmail, Drive/Docs/Sheets.
- `notion` — база задач/проектов.
- `himalaya` — email через IMAP/SMTP вместо Gmail API.
- `teams-meeting-pipeline` / `ocr-and-documents` — разбор встреч, документов, вложений.
- `maps` — поездки/адреса/время в пути.
- Встроенные `cronjob`, `memory`, `todo`, `session_search`, `clarify`, `messaging`.

Отключённые/не приоритетные:
- Airtable, Slack, Discord — не запрашивать, пока политика не изменится.
- GitHub/devops/code skills — только если пользователь явно переводит задачу в технический контур.

## Что запросить у пользователя для полной готовности
1. Отдельный Telegram BotFather token для профиля.
2. Разрешённый Telegram user id (по умолчанию `__TG_OPERATOR_ID__`).
3. Notion: integration token + shared parent/hub page.
4. Календарь: Google Workspace OAuth/credentials или подтверждение, что ведём в Notion.
5. Список направлений и текущих проектов.
6. Текущие задачи и ожидания от людей (хотя бы сырым списком).
7. Предпочтения по напоминаниям: утро/вечер, часовой пояс, тихие часы.

## Текущий статус настройки
Профиль создан как отдельная роль. `TELEGRAM_BOT_TOKEN` установлен, gateway в polling mode. Личная Kanban `personal-assistant` создана и закреплена (`HERMES_KANBAN_BOARD`), gateway-диспетчер включён только для неё. Источник правды — Notion, подключён; созданы и проверены базы: Направления, Проекты, Задачи, Ожидания, Входящие, События. Google Calendar подключён через Google Workspace OAuth (calendar-only scope); `setup.py --check-live` делает реальный API-вызов успешно.

## Hermes Forge Improvement Loop
Доступен через `bin/hermes-forge` и `bin/forge-improve`. Evidence-driven улучшение профиля, не тихая самоправка:
- `bin/forge-improve` — read-only скан → артефакты в `/root/hermes/reports/forge/profiles/<profile>/<UTC timestamp>/`;
- `report.md` — это proposal: pain → evidence → hypothesis → experiment → safe next step;
- `diff-preview` — только просмотр;
- `apply` — только с явным разрешением человека, ограничен executor `skill_frontmatter_metadata_v1`;
- не авто-применять Forge-кандидатов и не считать их доказательством выполнения без независимой проверки.
