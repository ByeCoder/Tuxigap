# Security

Do not publish bot tokens, provider keys, database files, backups or real payment IDs in issues.
Rotate leaked tokens with BotFather and leaked AI keys with your provider.
For a vulnerability report, contact the repository owner privately; configure GitHub private vulnerability
reporting after publishing this repository. Never test attacks against unrelated Telegram groups.

Live administrator rights are rechecked on privileged callbacks and text input. Target administrators are
protected from moderation. This is not an independently audited security product. Server operators can read
the SQLite database. Protect the host, backups and secrets. There is no remote shell/eval command.
The polling bot does not accept inbound Telegram webhooks. An optional owner dashboard is a separate
process, bound to loopback by default. Its random WEB_TOKEN grants access to every community in this
installation, including settings and training. Keep it private and use a TLS reverse proxy for remote access.
Dashboard credentials are not bot tokens and are never sent in URL query strings or stored by the frontend.
