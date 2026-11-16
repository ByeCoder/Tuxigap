# Keep things comfortable and dependable

## What lives where

| Item | Default location | Keep private? |
|---|---|---|
| Bot and provider credentials | `.env` | Yes |
| Native SQLite | `data/tuxigap.sqlite3`, or `tuxigap-data` in Docker | Yes |
| Spam-engine database/samples | `spam-data` | Yes |
| Studio database | `studio-data` | Yes |
| Translation catalogs | `tuxigap/locales/*.json` | Public source |
| Tests and synthetic demo | Repository / temporary directory | No real user data |

Each token has one polling owner. Native core and Studio use different tokens and different ledgers. Scale by thoughtful deployment, not by starting duplicate pollers on one token.

## Check, start and inspect

```bash
python -m tuxigap --check
docker compose up -d --build
docker compose ps
docker compose logs -f --tail=100
```

The native Docker image runs as a non-root user, with a read-only root filesystem, persistent data volume and writable temporary directory. Its health probe checks the maintenance heartbeat. Loopback-only web ports avoid publishing admin services by accident.

Changing environment values requires recreating containers so the process reads them again:

```bash
docker compose up -d --force-recreate
```

Panel/database settings are read live and don't need that restart.

## Consistent backups

```bash
python -m tuxigap --backup backups/tuxigap-2026-11-16.sqlite3
# Container backup, stored inside the data volume:
docker compose exec tuxigap python -m tuxigap --backup /app/data/backup-2026-11-16.sqlite3
# Copy that completed backup to a private host folder:
docker compose cp tuxigap:/app/data/backup-2026-11-16.sqlite3 ./backup-2026-11-16.sqlite3
```

The backup command uses SQLite's backup API and refuses to overwrite a destination. Plain copying of an active SQLite file can miss WAL data.

To restore, stop the service, replace the database with the backup, and remove obsolete WAL/SHM companions for the old database. Check permissions and restart. Keep the backup itself safe before doing any restoration. Back up the engine and Studio with their own supported procedures too.

## Upgrades

- Back up first and keep the old image/source revision available.
- Version 0.3 adds schema version 3. The additive migration retains earlier data and adds new community tables.
- An older binary must not run against a newer schema.
- Test your configuration with `--check`, then monitor queues, logs and membership behavior after restart.
- Pin tested external engine images and retain the Studio source commit.

## Data retention

Ordinary message cache and moderation evidence text are pruned after `RETENTION_DAYS` (default 14). Local labeled samples last up to 90 days and are capped at 500 per group. Aggregate counters, activity identity rows and financial records are retained for reporting.

`/forget` removes a member's game profile, cached text, local subject training examples and personal activity rows. It doesn't erase aggregate counters, a purchased entitlement or the financial ledger. Unresolved financial updates remain available for investigation. Provider, engine, Studio and backup retention are separate responsibilities.

## Queues and failure recovery

- `inbox`: durable Telegram updates. Confirmed payments/pre-checkout use a separate consumer lane.
- `payments`: idempotent charge ledger and access-delivery status.
- `engine_outbox`: labeled examples waiting for the optional engine.
- `jobs`: scheduled posts, with retries and creator-rights rechecks.
- `federation_jobs`: versioned shared decisions, with retries and protected admin handling.
- `report_log`: already delivered completed-period reports.

Avoid deleting unresolved financial rows to make an error disappear. Check the original payload, configured plan and Telegram transaction before deciding how to reconcile it. Don't expose queue payloads or real payment identifiers in public issues.

Telegram sends and SQLite commits are not atomic together. Notices/posts can repeat around a process crash; charge IDs prevent double application of confirmed payments.

## Connectivity and privacy

`ALL_PROXY` supports an outbound proxy, including SOCKS. Keep engine/local addresses in `NO_PROXY`. A local OpenAI-compatible provider can be used if you prefer; its API still needs the required contract.

The bot masks network failures in logs so token-bearing Telegram URLs aren't dumped. Protect the host and `.env` too: an operator can read the SQLite database. Rotate leaked keys and bot tokens with their issuing service.

No remote shell/eval command is exposed. The dashboard uses a separate random bearer key, bounded request bodies, fixed static routes and no permissive CORS. Its key grants broad owner access; share it only with people you trust to manage every group in that installation.


Version 0.4 stores bot staff roles, local tags, observed member presence, pending join requests, call events and group-game state in the same backed-up SQLite database. Event/request details follow message retention; aggregate counters and scoreboards remain. `/forget` removes the new personal tag/presence/staff/request/score records only after self-confirmation; payment records remain for reconciliation. Future activity can recreate membership records.
