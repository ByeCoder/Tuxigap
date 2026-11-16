# A welcoming community, with clear responsibilities

The **Staff hub** button in `/panel`, or `/staffpanel` in your group, brings member tools, request review, analytics, call invitations and channel tools together. Members see only the tools their current permissions allow. Old buttons are checked again when pressed.

## Staff roles and Telegram admins

These are two separate systems. A **bot staff role** delegates Tuxigap tools; a **Telegram admin role** changes actual Telegram privileges. Participation ranks never grant either one.

| Bot staff role | Delegated tools |
|---|---|
| `manager` | Member moderation, request review, tags, content, call invitations, events and analytics |
| `moderator` | Member moderation, request review and tags |
| `editor` | Group/channel content tools, including title/description changes through the bot |
| `host` | Call invitations and community events |
| `analyst` | Reports and observed membership overview |

Only the **current Telegram owner of that community** can assign bot staff:

```text
/role 123456789 moderator
/role 123456789 analyst
/role 123456789 none
```

Or reply to a member and send `/role moderator`. `/roles` lists assigned roles. Leaving the chat revokes a bot role; live membership is also checked before use. A bot moderator cannot act on a peer or a higher bot staff role. Current Telegram admins stay protected by the existing moderation target checks.

A delegated moderator can reply and use `/manage` for member buttons, or `/warn`, `/mute`, `/unmute`, `/ban`, `/unban`, `/delete`, `/spam` and `/ham`. Delegation does **not** unlock the full settings panel, federation ownership, refunds or membership-plan controls. Those continue to require actual Telegram admins with the appropriate rights. Telegram permissions are enforced separately from bot roles: the bot itself still needs permission to carry out an action.

To grant actual Telegram admin privileges, reply to a member:

```text
/promote host | Call host
/promote moderator | Community helper
/promote editor
/promote manager
/demote
/admintitle New title
```

`/promote` and `/demote` require your current **Add new admins** permission and the bot's equivalent permission. The bot refuses protected/uneditable admins and grants only a subset of the acting admin's and bot's rights. Presets never grant **Add new admins**. A `host` gets call-management and invite permissions; channel editor presets use channel posting/editing rights. A manager preset includes broader moderation/info/call rights. Custom admin titles are for editable supergroup admins, with 1–16 letters/numbers/spaces/hyphens/underscores; use `/admintitle -` to clear one.

## Celebrate participation

`/profile` keeps your XP, level, coins and badge. `/rank` shows your community title and progress to the next rank. `/ranks` lists the ladder; `/top` keeps the general XP leaderboard and `/scores` tracks the new group-game points.

The default XP thresholds are **0, 100, 300, 700, 1500, 3000, 6000**. The owner can make them their own:

```text
/rankset 0:New friend | 100:Regular | 500:Helper | 1500:Star
/rankset reset
```

Choose 2–12 increasing thresholds beginning at zero, with titles of at most 16 characters. Levels remain `XP // 100 + 1`; the title ladder is independent. Existing message cooldowns, quiz wins, daily rewards and new group-game turns award XP. No rank automatically promotes an administrator or exempts a member from paid access.

## Tags that help people find their team

Local tags can organize your volunteers without changing Telegram permissions:

```text
# Reply to a member, or add their numeric ID before the tag
/tag helper
/untag helper
/tags
/tagmembers helper Our next planning session is tomorrow!
```

A member can inspect their own tags. Authorized tag staff can reply to inspect someone else's. Each member can have ten local tags; they are matched case-insensitively within one chat. `/tagmembers` mentions up to 20 currently present tagged members, with a one-minute sender cooldown and a 1,000-character message limit. It does not enumerate or notify the whole group.

For a **visible Telegram member tag**, use `/membertag Helper`, replying to a regular member, or `/membertag USER_ID Helper`. `/membertag -` clears it. Telegram needs the bot's **Manage tags** permission. These tags and administrator titles do not accept custom emoji. For admins, use `/admintitle` instead.

## Handle arrivals and departures

Open **Staff hub → Arrivals & departures** for join-policy and notice buttons. Set friendly templates:

```text
/template welcome Welcome, {name}! Take a look at /rules and make yourself at home. 🌷
/template goodbye See you around, {name}. Thanks for spending time with us!
/template rules Please be kind, stay curious, and help each other learn.
```

`{name}` becomes the arriving/departing member's first name. Each template can have up to 2,000 characters. Setting a welcome/goodbye template enables that notice; the inline lifecycle panel can switch notices off again. Departure messages are off initially.

Membership events are deduplicated, keep an observed presence record, and feed daily/weekly/monthly/yearly join and leave counters. `/members` shows the observed totals. Telegram does not give a bot the complete historical member list; these records begin with updates the bot receives. A delayed older event cannot revoke a role assigned after a newer join.

### Join requests

| Command | Ordinary requests |
|---|---|
| `/joinmode manual` | Staff review, the default |
| `/joinmode auto` | Automatically approve |
| `/joinmode trusted` | Automatically approve locally trusted members from `/approve` |
| `/joinmode off` | Leave decisions to Telegram's own interface |

`/requests` shows the ten newest pending requests the bot has observed, with green accept/red decline buttons. Configure the **log chat** in the main panel to receive review buttons there too. New requests supersede older pending requests from the same account; an old button cannot approve a replacement request. Decisions and automatic approval attempts remain stored across restarts.

Dry run pauses ordinary automatic approvals. Paid communities still require an active subscription, and an active federation ban takes priority. An admin's manual approval button cannot bypass those checks. Disabling ordinary request processing does not turn off the paid gate. After an automatic approval, the normal membership path still applies paid checks, CAPTCHA, bot locks and raid handling.

Only future incoming requests are available to the bot; an old backlog created before installation may need review directly in Telegram. A network failure leaves the request pending for retry. Telegram actions and database commits are not one atomic transaction, so an outside decision or a crash after Telegram accepts the action can leave a local request needing manual reconciliation.

## Calls: help people join and give hosts the right tools

`/callpanel` shows the latest call event the bot actually received. Scheduled/start/end/invited events are recorded once, and call-start counters appear in reports. Notice buttons are in the lifecycle panel.

```text
/calllink https://t.me/YourCommunity?videochat
/callannounce
/calllink off
```

Copy the actual call link from Telegram. Only HTTPS `t.me` links are accepted; Tuxigap does not verify that the session is currently running. Invitations have a one-minute sender cooldown. A host bot role can share invitations; `/promote host` gives a human actual Telegram call-management rights when the bot and acting admin may grant them.

**The Bot API does not expose starting/ending group calls, muting individual call participants, or streaming music.** Use Telegram's own call controls for those actions. Music playback is available through the explicitly authorized [optional helper-account worker](MUSIC.md), with separate setup. There is no hidden account session. The panel calls its state “latest observed event”, since the bot cannot query a complete live call roster through the Bot API.

## Channels and linked discussion groups

Connect a channel in private chat with `/connect CHAT_ID`. Then use:

```text
/channel -1001234567890
/post -1001234567890 Hello, everyone!
/editpost -1001234567890 42 Here is our updated announcement.
/pinpost -1001234567890 42
/unpinpost -1001234567890 42
/deletepost -1001234567890 42
/title -1001234567890 Our friendly community
/description -1001234567890 A place to learn and share together.
```

In the target group, omit its numeric chat ID. Posting returns the new message ID. The tools recheck acting-admin permissions or the explicitly delegated `content` capability; Telegram still checks the bot's own rights. Post/edit bodies allow up to 3,000 characters. Telegram's normal editing/deletion and pinning limitations still apply.

`/channel` or `/chatinfo` displays current member count and linked chat ID. A connected linked community gets its own panel button only when the acting user is also its current admin. Linking a discussion group to a channel itself stays a Telegram configuration task. Settings, membership sales, reports and staff roles remain scoped to each destination.

See [APPEARANCE.md](APPEARANCE.md) for colored buttons and custom emoji, and [GAMES.md](GAMES.md) for group activities.
