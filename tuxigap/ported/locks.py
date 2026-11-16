# SPDX-License-Identifier: GPL-3.0-only
# Python adaptation of sametcn99/tg-bot-studio/src/server/modules/locks/lock-evaluator.ts.
# Original authors: sametcn99/tg-bot-studio contributors. See third_party/studio/LICENSE.
# Changes: Python types, UTF-16 entity slicing, strict domain allowlists scoped to lock families.
import re
from urllib.parse import urlparse

LOCK_TYPES = (
    "all album anonchannel audio bot botlink button cashtag checklist cjk command comment contact "
    "cyrillic document email emoji emojicustom emojigame emojionly externalreply forward forwardbot "
    "forwardchannel forwardstory forwarduser game gif guestbot inline invitelink location phone photo "
    "poll rtl spoiler sticker stickeranimated stickerpremium text url video videonote voice zalgo"
).split()
EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2190-\u21ff]")
RTL = re.compile("[\u0590-\u08ff\ufb50-\ufdff\ufe70-\ufeff]")
CJK = re.compile("[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def entity_text(text, entity):
    encoded = text.encode("utf-16-le")
    start = int(entity.get("offset", 0)) * 2
    end = start + int(entity.get("length", 0)) * 2
    return encoded[start:end].decode("utf-16-le", errors="replace")


def urls(message):
    text = message.get("text", message.get("caption", ""))
    values = []
    for entity in message.get("entities", message.get("caption_entities", [])):
        if entity.get("type") in ("url", "text_link"):
            values.append(entity.get("url") or entity_text(text, entity))
    values.extend(re.findall(r"(?:https?://|www\.|t\.me/)[^\s<>]+", text, re.I))
    return list(dict.fromkeys(v.lower().rstrip(".,!?؛،") for v in values))


def trusted_urls(message, allowlist):
    targets = urls(message)
    domains = [
        x.removeprefix("url:").strip().lower().rstrip(".")
        for x in allowlist
        if ":" not in x or x.startswith("url:")
    ]
    if not targets or not domains:
        return False
    for target in targets:
        host = urlparse(target if "://" in target else "https://" + target).hostname or ""
        host = host.lower().rstrip(".")
        if not any(host == domain or host.endswith("." + domain) for domain in domains):
            return False
    return True


def matches(kind, message, chat):
    text = message.get("text", message.get("caption", ""))
    entities = message.get("entities", message.get("caption_entities", []))

    def has(t):
        return any(e.get("type") == t for e in entities)

    sticker = message.get("sticker", {})
    forward = message.get("forward_origin", {})
    fields = {
        "photo": "photo",
        "video": "video",
        "voice": "voice",
        "videonote": "video_note",
        "audio": "audio",
        "document": "document",
        "gif": "animation",
        "sticker": "sticker",
        "poll": "poll",
        "game": "game",
        "contact": "contact",
        "externalreply": "external_reply",
        "checklist": "checklist",
        "album": "media_group_id",
        "emojigame": "dice",
    }
    if kind in fields:
        return fields[kind] in message
    if kind == "all":
        return any(matches(k, message, chat) for k in LOCK_TYPES if k != "all")
    if kind == "text":
        return bool(message.get("text", "").strip())
    if kind == "stickeranimated":
        return sticker.get("is_animated", False)
    if kind == "stickerpremium":
        return "premium_animation" in sticker
    if kind == "emoji":
        return bool(EMOJI.search(text))
    if kind == "emojicustom":
        return has("custom_emoji")
    if kind == "emojionly":
        return bool(EMOJI.search(text)) and not EMOJI.sub("", text).strip(" \n\t\u200d\ufe0f0123456789#*")
    if kind in ("inline", "guestbot"):
        return "via_bot" in message
    if kind == "url":
        return bool(urls(message))
    if kind == "email":
        return has("email") or bool(re.search(r"\S+@\S+\.\S+", text))
    if kind == "phone":
        return has("phone_number") or bool(re.search(r"\+?\d[\d -]{7,}\d", text))
    if kind == "command":
        return has("bot_command") or text.startswith("/")
    if kind == "location":
        return "location" in message or "venue" in message
    if kind == "invitelink":
        return any("t.me/" in u for u in urls(message))
    if kind == "botlink":
        return any(re.search(r"t\.me/[a-z0-9_]+bot(?:\?|$)", u, re.I) for u in urls(message))
    if kind == "bot":
        return message.get("from", {}).get("is_bot", False)
    if kind == "button":
        return any(
            "url" in b for row in message.get("reply_markup", {}).get("inline_keyboard", []) for b in row
        )
    if kind == "cashtag":
        return has("cashtag") or bool(re.search(r"\$[A-Z]{2,}", text))
    if kind == "forward":
        return bool(forward)
    if kind == "forwarduser":
        return forward.get("type") in ("user", "hidden_user")
    if kind == "forwardbot":
        return forward.get("sender_user", {}).get("is_bot", False)
    if kind == "forwardchannel":
        return forward.get("type") == "channel"
    if kind == "forwardstory":
        return "story" in forward
    if kind == "anonchannel":
        return (
            message.get("sender_chat", {}).get("type") == "channel" and message["sender_chat"]["id"] != chat
        )
    if kind == "comment":
        return message.get("is_automatic_forward", False)
    if kind == "spoiler":
        return has("spoiler")
    if kind == "rtl":
        return bool(RTL.search(text))
    if kind == "cjk":
        return bool(CJK.search(text))
    if kind == "cyrillic":
        return bool(re.search("[\u0400-\u04ff]", text))
    if kind == "zalgo":
        return bool(re.search("[\u0300-\u036f]{3,}", text))
    return False


def exempt(kind, message, allowlist):
    if kind in ("url", "botlink", "invitelink"):
        return trusted_urls(message, allowlist)
    if kind.startswith("sticker"):
        return "stickerpack:" + message.get("sticker", {}).get("set_name", "").lower() in allowlist
    if kind in ("inline", "guestbot"):
        bot = message.get("via_bot", {})
        return any(
            "inline:" + str(v).lower() in allowlist
            for v in (bot.get("id"), bot.get("username"))
            if v is not None
        )
    if kind.startswith("forward"):
        origin = message.get("forward_origin", {})
        sender = origin.get("chat", origin.get("sender_user", {}))
        return any(
            "forward:" + str(v).lower() in allowlist
            for v in (sender.get("id"), sender.get("username"))
            if v is not None
        )
    if kind == "command":
        text = message.get("text", "").split()
        return bool(text and "command:" + text[0].lower() in allowlist)
    return False


def evaluate(locked, message, chat, allowlist=()):
    normalized = [entry.strip().lower() for entry in allowlist]
    return [
        kind
        for kind in locked
        if kind in LOCK_TYPES and matches(kind, message, chat) and not exempt(kind, message, normalized)
    ]
