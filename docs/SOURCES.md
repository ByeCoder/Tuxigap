# Sources and provenance

Thank you to these projects and their contributors. Exact revisions are pinned in [upstream-lock.json](../third_party/upstream-lock.json).

| Source | Upstream license | Used in this release |
|---|---|---|
| [umputun/tg-spam](https://github.com/umputun/tg-spam) | MIT | Optional real Docker engine, authenticated API adapter and queued feedback |
| [sametcn99/tg-bot-studio](https://github.com/sametcn99/tg-bot-studio) | GPL v3 | Ported lock evaluator and optional full pinned companion deployment |
| [Black-Bulls-Bots/zerotwobot](https://github.com/Black-Bulls-Bots/zerotwobot) | GPL v3 | Selected fun data and helper behavior adapted into native commands |
| [Astrako/AstrakoBot](https://github.com/Astrako/AstrakoBot) | GPL v3 | Bounded shout/text-art adaptation |
| [redstone-md/shield](https://github.com/redstone-md/shield) | MIT | Architecture reference; no full source import or service deployment claimed |

The original SaitamaRobot and PaulSonOfLars/tgbot are archived. They remain historical references, not runtime dependencies in this repository.

## Primary technical references

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Digital goods and Telegram Stars](https://core.telegram.org/bots/payments-stars)
- [Star subscriptions](https://core.telegram.org/api/subscriptions)
- [Official test environment](https://core.telegram.org/bots/features#dedicated-test-environment)
- [HTTPX async support](https://www.python-httpx.org/async/)

Group access is built with bot invoices, a local entitlement ledger and identity-checked join requests. It doesn't misuse the channel-only `createChatSubscriptionInviteLink` API for groups.

See [integration notes](INTEGRATION.md) and [third-party notices](../THIRD_PARTY_NOTICES.md) for what was adapted, what remains separate and the preserved licenses.
