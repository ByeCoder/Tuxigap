# Your everyday command guide

Welcome! The inline panel is the easiest place to explore. Most commands also work with `@YourBot` appended when several bots share a group.

## Everyone

| Command | What it does |
|---|---|
| `/start`, `/help` | A friendly tour and command list |
| `/language [CODE]` | Personal language in private; group language for group admins |
| `/play` | Games, daily rewards, profiles and referral buttons |
| `/rules` | Read the group's rules |
| `/notes`, `/get NAME` | Browse public notes |
| `/ask QUESTION` | Ask the enabled AI helper |
| `/summary` | Summarize recent messages when AI context is explicitly enabled |
| `/profile`, `/top`, `/daily` | See progress, community ranking and daily rewards |
| `/joke`, `/quiz`, `/dice` | A small activity for the group |
| `/toss`, `/decide`, `/8ball`, `/emote` | Ported fun utilities |
| `/shout TEXT` | Bounded text-art, or reply to text |
| `/afk [MESSAGE]` | Set an away notice; your next message clears it |
| `/report` | Reply to a message and ask admins to review it |
| `/shop`, `/subscriptions` | Private purchase options and access recovery |
| `/paysupport`, `/terms` | Payment contact and sales terms |
| `/privacy`, `/forget` | Data information and confirmed personal-data removal |

Use the giveaway's entry button to participate for free. Each person gets one entry; eligibility is checked again when drawing a winner.

## Current group admins

| Command | Permission / behavior |
|---|---|
| `/panel` | Open the group panel; private chat lists your managed groups |
| `/connect CHAT_ID` | Connect an accessible channel in private chat |
| `/manage` | Reply to a member's message for inline member buttons |
| `/warn` | Reply; requires restrict-member permission; warning limit can trigger a timed mute |
| `/resetwarn` | Clear a replied-to member's warning count |
| `/mute [MINUTES]`, `/unmute [USER_ID]` | Restrict/restore to the group's default permissions |
| `/ban`, `/unban [USER_ID]` | Reply; /unban also accepts a numeric ID |
| `/delete`, `/pin` | Reply; requires the corresponding Telegram admin right |
| `/approve`, `/unapprove` | Mark/revoke a trusted local-moderation exemption; doesn't grant paid access |
| `/spam`, `/ham` | Reply to teach a labeled example; no silent deletion |
| `/stats day|week|month|year` | Read a current-period report |
| `/aiquiz TOPIC` | Generate a four-option quiz when AI and games are enabled |
| `/refund CHARGE_ID` | Request a Stars refund, then confirm with a button |
| `/cancel` | Leave a pending text-entry flow |

The bot rechecks your current rights, including when a previously opened button is pressed. Anonymous admins should use the private panel so their real user identity can be verified.

## Panel entries

- **Moderation & safety:** dry run, flood, duplicate/word protection, content locks, scoped allowlists, quiet hours, CAPTCHA, anti-raid, link/mention limits and emergency permissions.
- **AI & learning:** assistant, text/image review, history size, samples and feedback.
- **Analytics:** four calendar periods, private CSV and scheduled reporting.
- **Content & scheduling:** notes, auto-replies, rules, welcome text, polls, giveaways and posts.
- **Membership sales:** plans, gate confirmation, availability and revenue.
- **Settings:** language, timezone, report time, week start and community activities.

## Federations

A federation is a shared ban policy **you explicitly choose to trust**. Its owner can propose shared bans across approved member groups.

1. In private chat, create it: `/fedcreate My Community Circle`.
2. A group's actual Telegram **owner** sends `/fedjoin FEDERATION_ID` in that group.
3. If someone else owns the federation, its owner must approve the request in private chat.
4. The federation owner, while also a current admin in a linked group, can use `/fban USER_ID REASON` or reply to the member.
5. `/funban USER_ID REASON` queues a reversal.
6. The group owner can leave with `/fedleave`. Existing bans remain for local review.

Jobs are persistent and versioned, so outdated queued decisions are skipped. The target's current admin role is protected in each group. Reversal only lifts a known federation-applied ban, and it respects a tracked manual ban or unpaid membership gate. Telegram and local storage aren't one atomic transaction; concurrent outside actions can still need human review.
