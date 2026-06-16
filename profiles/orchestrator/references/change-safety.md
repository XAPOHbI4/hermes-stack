# Change safety: risk levels, change plan, rollback

Грузится по триггеру «собираюсь что-то изменить/установить/удалить». Дополняет HARD RULE про destructive→BLOCK конкретной процедурой.

## Risk levels
| Уровень | Что | Approval |
|---|---|---|
| **L0** | только рассуждение, без инструментов | не нужен |
| **L1** | read-only инспекция в согласованном scope (чтение файлов, `mode=ro` БД, `systemctl status`, `--dry-run`) | обычно не нужен |
| **L2** | создание НОВЫХ файлов в рабочей папке | нужен, если scope неясен |
| **L3** | изменение существующих не-чувствительных файлов | нужен `CHANGE_PLAN` + явное «ок» |
| **L4** | config/profile/tool/gateway/cron changes | explicit approval |
| **L5** | delete/move данных, внешние сообщения, публикация, платежи, действия в аккаунтах, **gateway restart**, install/update | **всегда** explicit approval |

Default: L0–L1 — после понятного scope; L2 — только в рабочей папке; L3 — с `CHANGE_PLAN`; L4–L5 — explicit approval.

## Global stop rules → вернуть `BLOCKED`/`NEEDS_APPROVAL`
- нужен секрет/приватный экспорт;
- действие может удалить/перезаписать данные;
- нет источника правды или live state противоречит инструкции;
- влияет на внешний сервис/аккаунт/gateway;
- rollback невозможен или непонятен.

## CHANGE_PLAN (показать ДО изменения L3+)
```
CHANGE_PLAN
Scope:                 что и зачем
Files/configs:         что меняется (точные пути)
Old → New:             краткое до/после
Commands:              что будет запущено
Side effects:          что ещё затронется (L?)
Backup:                путь + timestamp (.bak/.disabled или архив)
Rollback:              как откатить одной командой
Approval needed:       yes/no
```
Без подтверждённого CHANGE_PLAN изменения L3+ не выполняются.

## ROLLBACK
```
ROLLBACK
Change ID / что меняли:
Backup location (+timestamp):
Restore steps (одна команда если можно):
Verify after restore:
What may be lost:
```
Backup валиден только если: точный путь + timestamp + проверено что читается + описан restore + секреты не в публичном месте.

## Наши инварианты (уже практикуем — закрепить)
- **Обратимость**: правки — через `.bak-<тег>-<дата>` или `.disabled`, не перезапись «в лоб».
- **Gateway restart — graceful**: `gw-restart <profile>` (SIGUSR1 drain), НЕ `systemctl restart` (убьёт in-flight воркер; см. proof о process-death).
- **Маленькими шагами**: не «10 профилей + все tools + все gateways» за раз. Один инкремент → проверка → следующий.
- **Перед публикацией/пушем**: `leak_scan.sh <path>` → PASS (см. `source-map.md`).
- **Install/update**: не `sudo`/`curl|bash`/удаление директорий/restart сервисов без отдельного approval; сначала версия/`--help`/dry-run.
