# A little color, a little personality

English remains the default. The **Staff hub → Buttons & emoji** panel offers blue, green and red style buttons, plus Telegram's default. Actual rendering depends on the Telegram app and Bot API version.

```text
/theme primary
/theme success
/theme danger
/theme default
```

The setting is per community. Native request-review buttons keep semantic green/red styles so an acceptance is easy to distinguish from a rejection. Telegram allows these named styles; arbitrary hex colors are not supported by this keyboard API.

## Custom emoji on a button

1. Send a custom emoji in a message and reply with `/emojiid`.
2. Copy its numeric custom emoji ID.
3. As a current Telegram admin, use `/buttonemoji EMOJI_ID` in the community.
4. Use `/buttonemoji off` to remove the custom icon.

Tuxigap uses Telegram's `icon_custom_emoji_id`, placing one custom icon before the label. Inline button labels do not parse HTML; arbitrary animated emoji embedded between words in the label are not supported by this interface.

## Custom emoji inside text

Use this safe marker:

```text
[emoji:5368324170671202286|👍]
```

The number must identify a real available custom emoji. Keep a real ordinary emoji after the vertical bar as a fallback. Preview one with:

```text
/emojitext [emoji:YOUR_ID|🚕] Welcome aboard!
/template welcome [emoji:YOUR_ID|🌷] Welcome, {name}!
```

Markers work in welcome/goodbye messages, rules, public notes, auto-replies, scheduled posts and the new post/edit tools. Other text—including raw HTML—is escaped. A member name cannot inject HTML through a template. Built-in bot messages remain friendly translated strings; your own text is not automatically translated.

## Telegram eligibility and fallback

The Telegram documentation permits custom emoji for bots with additional usernames purchased on Fragment, or for eligible messages directly sent to private/group/supergroup chats when the bot's owner has Telegram Premium. Do not assume the owner's Premium subscription alone permits every inline/channel context. Emoji IDs and app support also matter.

If Telegram rejects presentation with a custom-emoji/button/style-related `400` error, the transport retries once with ordinary fallback emoji and default button styling. Permission errors, unknown chats and unrelated failures are not retried as a different message. No Premium subscription or Fragment purchase is performed by this script.

Primary reference: [Telegram Bot API](https://core.telegram.org/bots/api#inlinekeyboardbutton), [HTML formatting](https://core.telegram.org/bots/api#html-style), and [Bot API changelog](https://core.telegram.org/bots/api-changelog).
