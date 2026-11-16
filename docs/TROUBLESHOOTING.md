# A little help when something gets stuck

## The bot starts, then exits

Check `BOT_TOKEN`, connectivity and whether a webhook or second poller already owns the token. Tuxigap refuses an active webhook rather than dropping queued updates. Use BotFather/the Bot API to manage that webhook intentionally.

Start with `python -m tuxigap --check`. Then inspect logs without publishing credentials.

## Buttons say I don't have permission

The bot checks your current Telegram role, not the role you had when opening the panel. Ask a group owner to grant the required right. Anonymous admins should open the private panel with their real user identity.

## I can't receive a private prompt, CSV or access link

Start the bot's private chat with `/start` and make sure it isn't blocked. Telegram doesn't let bots start a private conversation with an account that hasn't opened one.

## Messages aren't deleted

Dry run is on by default. After testing your rules, disable it from Moderation & safety. Check the bot's Delete messages permission. AI and external-engine results may intentionally be in human-review mode.

An explicit trusted-member exemption bypasses native content checks; it doesn't grant a paid membership.

## I see English after choosing another language

English is the default and fallback. Core menus are translated, while some advanced messages and newer modules still need community translations. See `docs/LANGUAGES.md` and `python tools/check_translations.py` for actual coverage. Custom admin text and old audit reasons aren't automatically translated.

## The owner panel doesn't show my group

Run the bot, make it an admin, and send `/panel` in the group. Confirm the dashboard points at the same SQLite path/volume. The header language and group-language settings are separate.

## The spam engine is up but not checking this group

Check `SPAM_ENGINES` has the actual numeric group ID and the correct independent endpoint. Confirm `SPAM_ENGINE_PASSWORD` matches the engine's Basic auth password. Keep internal engine addresses in `NO_PROXY`. Engine errors appear as counters; native rules remain active.

## Studio reports a token conflict

Use a different BotFather token in Studio. The same token cannot be polled concurrently by Tuxigap, Studio or an old bot. If both bots moderate a group, disable duplicate moderation in one to avoid conflicting actions.

## A member paid but hasn't received access

Look for the charge in `payments`, check the private chat is open, verify the bot's invite/restrict rights, and try `/subscriptions`. A failed delivery remains queued. A payment that doesn't match a local invoice remains in the financial inbox for manual reconciliation; restoring an old database can create this situation.

## A refund didn't remove access instantly

Access is recalculated from the unrefunded payment ledger. Another paid term may still cover the member. Maintenance applies expired access, subject to connectivity and current admin exemptions.

## Reports don't match Telegram's full history

The Bot API doesn't provide complete old message history or a historical member list. Tuxigap counts events it receives after setup, in calendar periods and the configured timezone. It can't retroactively observe every manual deletion or another bot's messages.

## Can I use this for a huge network?

Please load-test first. The native core uses a single polling process, SQLite and live permission checks. Federations queue actions across groups, but they aren't a substitute for capacity planning or an independent security review.

If you open an issue, please include the version, your component, a safe error summary and reproduction steps using sample data. Leave out tokens, database dumps, real messages and payment IDs. Thank you! 🌷
