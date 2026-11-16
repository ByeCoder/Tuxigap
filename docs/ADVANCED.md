# Grow your Tuxigap setup

Start small if you like. Each companion is optional, and your normal Telegram panel keeps working without it.

## Owner dashboard

Set a random `WEB_TOKEN` with at least 32 characters. The setup helper generates one for you, or make your own:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run it next to the bot:

```bash
python -m tuxigap.dashboard
```

Or add the dashboard Compose file:

```bash
docker compose -f docker-compose.yml -f docker-compose.web.yml up -d --build
```

Visit `http://127.0.0.1:8080`. Use the owner key from your private `.env`. The bot needs to have connected at least one group before it appears here.

The key grants owner access to all communities in this installation. It isn't a Telegram token. The browser keeps it in page memory—not a URL, cookie, localStorage or sessionStorage. Signing out clears it.

You can inspect analytics, edit permitted on/off settings, change a group's language and label training examples. Paid-gate activation and member/payment actions remain in Telegram, with live admin checks.

## Real tg-spam engine

The engine runs from the upstream project's Docker image. It has no Telegram token; Tuxigap sends authenticated checks and keeps ownership of Telegram actions.

```dotenv
SPAM_ENGINES={"-1001234567890":"http://spam-engine:8080"}
SPAM_ENGINE_PASSWORD=YOUR_STRONG_RANDOM_PASSWORD
CAS_TOKEN=
```

Then:

```bash
docker compose -f docker-compose.yml -f docker-compose.engines.yml up -d --build
```

- Engine dashboard: `http://127.0.0.1:8081`.
- Username: `tg-spam`; password: `SPAM_ENGINE_PASSWORD`.
- Group-specific engine mappings use independent endpoints and volumes. Reusing an endpoint for two groups is rejected.
- `/check` returns the upstream verdict; feedback waits in `engine_outbox` for `/update/spam` or `/update/ham`.
- `PARANOID=true` checks each message and disables the upstream engine's own LLM path. Tuxigap's AI is separate.
- Engine flags start in review mode. Test your language/sample data before turning that review off.
- Configure CAS, word dictionaries, sample files and Lua in the engine's own supported configuration. A CAS credential is optional; empty means no CAS check.
- Engine downtime doesn't stop the native flood, word or content rules.

The provided image uses `latest` for discoverability. For production, pin a digest or version you have tested. The engine's own data retention and deletion behavior are independent; local `/forget` doesn't delete provider/companion records automatically.

## Full Telegram Bot Studio companion

This optional service builds **the complete upstream application**, pinned to the commit in `third_party/upstream-lock.json`. It preserves the upstream license and application boundaries.

Set:

```dotenv
STUDIO_URL=http://localhost:3000
STUDIO_ADMIN_KEY=A_LONG_RANDOM_ADMIN_KEY
STUDIO_JWT_SECRET=ANOTHER_LONG_RANDOM_SECRET
```

Run:

```bash
docker compose -f docker-compose.yml -f docker-compose.studio.yml up -d --build
```

Open `http://127.0.0.1:3000` and sign in with the Studio master key. Create a bot using a **different BotFather token**. Don't paste Tuxigap's `BOT_TOKEN` into its bot pool.

Studio supplies its own CRM, support desk, visual flows, broadcasts, knowledge features, Mini App templates, Stars commerce and automation modules. These aren't native Tuxigap commands, and we don't present them as a shared database or unified payment ledger. Its language coverage is upstream's own, not the native 15-language picker.

For a Mini App to work outside your computer, set an appropriate public HTTPS `STUDIO_URL`, configure BotFather as upstream requires, and use a reverse proxy. If both bots are in a group, choose one moderation authority and disable conflicting moderation modules in the other.

## Run everything together

```bash
python tools/manage.py up --all
```

The equivalent Compose command is in the main README. Stopping with `down` keeps named volumes. Avoid `down -v` unless you intentionally want to erase persistent databases.

## Reach a remote server safely

The provided dashboard ports are loopback-only. An SSH tunnel is a comfortable option:

```bash
ssh -L 8080:127.0.0.1:8080 -L 8081:127.0.0.1:8081 -L 3000:127.0.0.1:3000 user@your-server
```

For a public endpoint, use a TLS reverse proxy and strong independent credentials. Don't expose unauthenticated engine APIs. Keep proxy/CORS settings aligned with the upstream application you actually run.
