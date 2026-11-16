# A clear, friendly membership flow

Tuxigap sells digital group/channel access using **Telegram Stars (`XTR`)**. It does not implement bank transfers, cryptocurrency, currency conversion or tax accounting.

## Before your first real sale

- Use a private group or channel and revoke uncontrolled invitation links.
- Give the bot invite and restrict-member rights.
- Add `SUPPORT_USERNAME` and a real `TERMS_URL` to `.env`.
- Explain price, duration, renewal and refund policy in terms your members can read.
- Run the official test-environment scenarios in [LIVE_TEST.md](LIVE_TEST.md).

## The purchase journey

1. A member chooses an available plan in private chat.
2. They see the snapshot price/duration, any automatic renewal, and the sales terms.
3. They agree, then the bot creates a Stars invoice.
4. Pre-checkout validates the purchaser, currency, server-side price, plan state and invoice age. **This is not payment confirmation.**
5. Telegram sends `successful_payment`.
6. A SQLite transaction records the unique charge and calculates access.
7. A persistent delivery queue sends a join-request link.
8. The bot approves a join request only for an account with active access.

A forwarded link doesn't grant access to someone else. A screenshot or claimed receipt doesn't grant access. A confirmed payment that cannot be reconciled stays in the inbox for human review; owners can receive a notification rather than silently losing the evidence.

## Plans and renewals

| Plan | Supported duration | Renewal |
|---|---|---|
| Fixed | 1–365 days | Member purchases another term manually |
| Recurring | 30 days | Telegram's supported 2592000-second recurring period |

Prices in this release are integers from 1 to 10000 Stars. A fixed purchase extends from the later of its payment time or the existing expiry. Recurring access follows Telegram's reported subscription expiration timestamp.

Invoices bind a random payload to a purchaser and a stored plan snapshot. Fixed invoices are single-payment. Duplicate charge updates do not extend access twice. Initial pre-checkout expires after 15 minutes; a valid late confirmed payment is still reconciled.

Members can cancel future renewal from `/subscriptions`; they keep the already-paid period. Turning off plan sales is **not** the same as cancelling an existing recurring subscription.

## Access and expiry

Join links last one day and create join requests. The identity of the requesting member is checked against current access. The bot also handles visible direct-join events while the gate is active.

Tracked expired memberships are checked by maintenance, normally every 30 seconds. Network/service failures can delay enforcement. Current admins are exempt. Previously existing untracked members are not enumerated or automatically removed—the Bot API doesn't expose a full historical member list.

The bot tracks bans it made for the access gate so a later purchase can restore that path. Known manual bans aren't lifted by a purchase. Federation reversals respect a tracked unpaid access gate. Concurrent native Telegram changes and a crash between a Telegram response and a database write can still require human review.

## Refunds and help

An authorized admin sends:

```text
/refund TELEGRAM_PAYMENT_CHARGE_ID
```

The bot shows the buyer and amount and asks for a confirmation button. For recurring plans it cancels that invoice's future renewal before refunding, then recalculates access from unrefunded ledger entries. Expired access is handled by maintenance.

Charge IDs are in the private SQLite `payments` table. Don't paste real ones into public GitHub issues. `/paysupport` shares your configured contact; Telegram support doesn't fulfill your bot's sales for you.

A failed access-link delivery doesn't create a new charge or discard the entitlement. Delivery retries, owners can be alerted, and a member can use `/subscriptions` after unblocking/starting the bot's private chat.

## Ledger boundaries

The native ledger is separate from Studio's commerce ledger. Restoring an old backup can omit newer payments; reconcile before accepting new purchases. Automatic reconstruction from `getStarTransactions`, a bookkeeping system and a guaranteed exactly-once boundary across Telegram/SQLite are not implemented.

References: [Telegram digital payments](https://core.telegram.org/bots/payments-stars), [Bot API](https://core.telegram.org/bots/api), [Star subscriptions](https://core.telegram.org/api/subscriptions).
