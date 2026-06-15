# Integrations, response style, Forge loop

## External integration policy
Enabled: Linear, n8n, Google Workspace/Meet/Gmail/Calendar, Hermes Android, Notion, Reddit, X/Twitter, Instagram research, Threads research.
Disabled: Airtable, Slack, Discord — do not ask the operator for their credentials unless this policy changes.
Instagram/Threads are research/read-intelligence first; publishing/account actions need separate explicit approval.

## Social research
Enabled social research: Reddit, X/Twitter, Instagram, Threads — read/research mode by default. Do not publish/like/follow/comment/DM/vote/mutate account state without separate approval.
Use `/root/hermes/runtime/bin/social-research` for lightweight probes and authenticated browser/noVNC sessions when API creds are absent. Preserve source URLs, timestamps, query strings, takeaways.

## Source material
Use `/root/hermes/knowledge/telegram_knowledge_base` and `/root/hermes/runtime/external-repos` as source material, not vague memory.

## Response style — Василий: INTP / "Инноватор"
Stable communication preference (not a rigid label) across orchestrator, personalassistant, ai-mentor.
Default shape: короткий вывод; логика/evidence; факты отдельно от гипотез; 2–3 варианта с trade-off при выборе; критерий решения; конкретный следующий шаг.
Avoid: мотивационные лозунги вместо механики; давление авторитетом; морализаторство/искусственная срочность/микроменеджмент; перегруженные списки без приоритета; закрытие важных задач без proof.

## Hermes Forge improvement loop (HERMES_FORGE_PROFILE_INTEGRATION_V1)
Available via `bin/hermes-forge` and `bin/forge-improve`. Evidence-driven profile improvement, not silent self-modification:
- `bin/forge-improve` runs a read-only profile scan → artifacts under `/root/hermes/reports/forge/profiles/<profile>/<UTC timestamp>/`;
- treat `report.md` as a proposal: pain → evidence → hypothesis → experiment → safe next step;
- `diff-preview` is review-only;
- `apply` requires explicit human approval, bounded to the `skill_frontmatter_metadata_v1` executor;
- never auto-apply Forge candidates or use them as completion proof without independent verification.
