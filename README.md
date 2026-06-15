# hermes-stack — deployable Hermes operations layer

A clean, secret-free provisioning bundle that turns a **stock Hermes install** into our
configured, self-monitoring, self-reflecting multi-agent system. Deploy anywhere in minutes.

## What's inside
```
profiles/        sanitized contracts per profile (AGENTS.md, SOUL.md, config.yaml, references/)
bin/             our runtime scripts (eval digest, lessons, healthcheck, watchdog,
                 rich_send, codex_usage, claude_run/architect/reviewer, closure_gate, backup_drill…)
systemd/         our timers (health hourly, eval weekly, lessons weekly, decompose, watchdog)
crons.manifest.txt   cron job definitions to re-create (Jarvis, health, digests)
.env.example     all required env keys (tokens, telegram wiring) — fill, never commit real values
install.sh       idempotent provisioner
```
**Not included (by design):** stock Hermes itself, venv, skill bodies (7.2 GB — re-synced),
secrets (auth.json / credentials / tokens), and all per-instance state (kanban, memory, DBs).
A fresh deploy starts with **empty state**.

## Deploy (on a fresh Linux box, as root)
```bash
# 1. base platform (stock Hermes)
git clone https://github.com/NousResearch/hermes-agent /root/.hermes/hermes-agent
cd /root/.hermes/hermes-agent && ./setup-hermes.sh

# 2. this layer
git clone <this-repo> /root/hermes-stack && cd /root/hermes-stack
cp .env.example .env && nano .env        # fill tokens + TG_* wiring
./install.sh

# 3. instance secrets (manual — never in the repo)
#    place /root/.codex/auth.json (codex login) and /root/.claude/.credentials.json (claude login)

# 4. crons + gateways
#    re-create crons from crons.manifest.txt, then:
hermes --profile orchestrator gateway install
systemctl enable --now hermes-gateway@orchestrator

# 5. verify
bash /root/hermes/runtime/bin/hermes_healthcheck.sh
```

## What you get after deploy
- Orchestrator + specialist profiles with thin-kernel contracts and engine-first decomposition
- Proof policy enforced at closure (reviewer REWORKs weak proof)
- Monitoring: hourly health (+ Claude & Codex subscription limits), watchdog, auto-decompose
- Learning loop: weekly eval digest + Claude reflection → Telegram (native rich tables)
- Tested backup drill (`bin/backup_drill.sh`)

## Notes
- `__SERVER_IP__` / `__TG_*__` placeholders are filled by `install.sh` from `.env`.
- Base Hermes is pinned to the upstream repo; for an exact rebuild pin a commit in step 1.
- Real "deploy anywhere" is only proven once you run it on a clean box — treat first deploy as the validation.
