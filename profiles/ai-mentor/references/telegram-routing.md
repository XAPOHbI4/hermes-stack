# Telegram routing

## ACTIVE — Friend Runtime (HERMES_FRIEND_TELEGRAM_ROUTING_V1)
This block overrides any older cloned routing from the source server.

- Main Telegram chat: `__TG_HOME_CHAT__`
- Allowed human operator: `__TG_OPERATOR_ID__`
- Primary entrypoint and Kanban dispatch owner: `orchestrator`
- Specialist bot tokens configured for devops, product, smm, research, ai-mentor; only always-on gateways load through the service manager.

Topic map:
- inbox → thread `24`, profile `orchestrator`, board `company-runtime`
- kanban → thread `26`, profile `orchestrator`, board `company-runtime`
- approvals → thread `28`, profile `orchestrator`, board `company-runtime`
- devops → thread `30`, profile `devops`, board `it-devops`
- product → thread `32`, profile `product`, board `product`
- research → thread `34`, profile `research`/`ai-mentor`, board `research`
- system_alerts → thread `37`, profile `devops`, board `it-devops`

User-facing summaries/blockers/finals — Russian. Inbox = intake only; Kanban lifecycle/finals → topic 26; human blockers/rework → topic 28; runtime failures → topic 37.

## LEGACY — Production company chat (archived, do NOT use unless reactivated)
Kept for reference only. Main chat `__TG_COMPANY_GROUP__`; active gateways `orchestrator`/`support`/`smm`; Rutoll support separate.
Topic map: inbox→2, kanban→4, approvals→6, IT&DevOps→8 (itops), product→10, engineering→25 (backend/frontend/qa), SMM→12 (smm), support→14 (support), research→16 (research), system alerts→18 (itops).
