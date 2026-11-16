# Take a careful first drive

Local tests are a useful start, but they don't prove a live Telegram/payment setup. Please use a private test community before enabling real moderation or selling access.

## Choose the right environment

For official Stars testing, create a user account and bot in Telegram's **separate test environment**, following [Telegram's guide](https://core.telegram.org/bots/features#dedicated-test-environment). Put that test bot's token in `.env` and set:

```dotenv
TELEGRAM_TEST_MODE=1
```

The adapter uses `https://api.telegram.org/bot<TOKEN>/test/METHOD`. Don't send a production token to the test path. Use a fresh database when returning to production and set `TELEGRAM_TEST_MODE=0`.

## Walk through the native bot

1. Add the bot to a private supergroup as admin; start its private chat. Open `/panel`.
2. Let a regular member try an admin button. It should refuse. Remove an admin's role and try their old panel/input flow again.
3. Set a test blocked phrase. Dry run should flag without deleting. Turn dry run off and verify deletion, warning escalation and timed mute.
4. Check a hidden text link, media caption, duplicate messages, content locks and a scoped domain allowlist. A trusted domain must not exempt unrelated media.
5. Use `/manage` against a regular member and against an admin. Admin protection should hold.
6. Test CAPTCHA with the new member's own account; another account can't solve it for them. Check restored permissions match group defaults.
7. Set a low anti-raid threshold in a test database and confirm new arrivals are challenged. Test quiet hours across midnight in your timezone.
8. Teach `/spam` and `/ham`. Confirm examples stay within their group and a learned pattern starts in review mode.
9. Try the quiz, repeated answers, daily rewards, game badges, a referral rejoin and a free giveaway. No one should pay to enter the giveaway.
10. Switch private and group languages independently. Test Hebrew/Persian/Arabic RTL in the dashboard. Check a missing translation falls back to readable English.
11. Review all four report periods, CSV access, a half-hour timezone boundary and deduplicated automatic reports.
12. Connect a test channel, schedule a post, revoke the creator's rights and verify the scheduled action is cancelled.

## Federations and the optional engine

1. Create a federation, request membership as a group owner and approve it as the federation owner.
2. Try a request as a regular admin or a decision as someone else; it should refuse.
3. Share a ban across two test groups; a target who is an admin in one must remain protected there.
4. Reverse a decision, test stale queued work and check a known manual ban/unpaid membership gate isn't lifted.
5. Bring the real spam engine online, confirm an authenticated check, label a sample, stop/restart the engine and verify feedback waits safely.

## AI

Enable a low quota on a test provider. Try `/ask`, public-note lookup, opt-in context, `/summary` and an admin `/aiquiz`. Try an invalid JSON verdict, unavailable provider and exhausted quota; local protection should continue.

If using vision, select a vision-capable model, tell your members what is shared, and test a small sample photo. An AI image flag should require human review.

## Paid access

1. Create a private test access plan and verify purchaser, price, duration, terms and renewal information.
2. Pay in the official test environment. Access must start only after successful payment.
3. Try forwarding an access link to a second account; only an actively entitled purchaser can join.
4. Replay a confirmed payment in a local test harness; charge deduplication must prevent double extension.
5. Block the bot's private chat after payment, then unblock it; entitlement must remain, and delivery should recover.
6. Test expiry, renewal arriving during expiry, manual-ban preservation and `/subscriptions` link recovery.
7. Confirm an authorized refund and inspect the recalculated ledger. A recurring refund should cancel future renewal.
8. Preserve an unmatched confirmed payment for human reconciliation rather than discarding it.

## Full-suite deployment

Studio needs its own different bot token, credentials, public HTTPS configuration for Mini Apps and its own upstream testing. Its ledger and languages are separate. Avoid enabling two competing moderators in the same group.

Finally, rehearse backup/restore and a clean restart. Record the component versions you actually tested. Thanks for giving your community a thoughtful launch. 🌷


## New community tools

- Grant/revoke bot staff roles as the real owner; confirm a departed staff member cannot use an old button.
- Verify actual `/promote host` grants only expected human call rights and `/demote` removes them on a bot-editable test admin.
- Check button colors in updated Telegram apps. Try a real custom emoji with an eligible bot owner, then verify ordinary fallback with an unavailable emoji.
- Test visible member tags with Manage tags rights; Telegram does not allow emoji in tags/admin titles.
- Review manual, auto and trusted join requests; test dry run, a paid subscriber, an unpaid account, a banned federation member and superseded buttons.
- Check welcome/goodbye messages, duplicate membership updates and observed counts.
- Post/edit/pin/unpin/delete in a private test channel; verify linked-group settings stay separate.
- Start/end/schedule a group call manually in Telegram and observe events; test the invitation link and human host privileges.
- Play all five `/party` modes with two accounts; check five-attempt limits, one winner, persisted scores and disabled activities.
