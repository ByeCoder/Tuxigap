from dataclasses import dataclass
import re
import time
import unicodedata


def normalize(text):
    text = unicodedata.normalize("NFKC", text).translate(
        str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی", "ـ": ""})
    )
    text = "".join(c for c in text if unicodedata.category(c) not in ("Mn", "Cf"))
    return " ".join(text.casefold().split())


def prohibited(text, words):
    text = normalize(text)
    for word in words:
        word = normalize(word)
        if not word:
            continue
        # Leading * opts into substring matching; default is whole phrase/word.
        if word.startswith("*") and len(word) > 1 and word[1:] in text:
            return True
        if not word.startswith("*") and re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text):
            return True
    return False


@dataclass
class Verdict:
    reason: str = ""
    review: bool = False

    @property
    def flagged(self):
        return bool(self.reason)


def local_check(db, chat, user, message, conf, now=None):
    now = int(time.time()) if now is None else now
    text = message.get("text", message.get("caption", ""))
    normalized = normalize(text)
    if conf["profanity"] and prohibited(text, conf["words"]):
        return Verdict("واژهٔ ممنوعه")
    entities = message.get("entities", []) + message.get("caption_entities", [])
    if conf["links"] and (
        any(e.get("type") in ("url", "text_link") for e in entities)
        or re.search(r"(?:https?://|www\.|t\.me/)", text, re.I)
    ):
        return Verdict("لینک ممنوع")
    if conf["forwards"] and message.get("forward_origin"):
        return Verdict("فوروارد ممنوع")
    if conf["media"] and any(
        k in message for k in ("photo", "video", "document", "audio", "voice", "animation", "video_note")
    ):
        return Verdict("رسانه ممنوع")
    if conf["stickers"] and "sticker" in message:
        return Verdict("استیکر ممنوع")
    if conf["bots"] and message.get("from", {}).get("is_bot"):
        return Verdict("ربات غیرمجاز")
    if conf["flood"]:
        count = db.one(
            "SELECT count(*) n FROM messages WHERE chat=? AND user=? AND ts>=?",
            (chat, user, now - conf["flood_seconds"]),
        )["n"]
        if count > conf["flood_count"]:
            return Verdict("فلود")
    if conf["duplicates"] and len(normalized) >= 8:
        recent = db.all(
            "SELECT text FROM messages WHERE chat=? AND user=? AND ts>=? AND mid<>? ORDER BY ts DESC LIMIT 15",
            (chat, user, now - 60, message["message_id"]),
        )
        if sum(normalize(row["text"]) == normalized for row in recent) >= 2:
            return Verdict("تکرار پیام")
    if conf["learning"] and len(normalized) >= 8:
        samples = db.all("SELECT text,label FROM samples WHERE chat=? ORDER BY ts DESC LIMIT 500", (chat,))
        # A legitimate label overrides learned text matches, never explicit moderation rules.
        if any(s["label"] == "ham" and s["text"] == normalized for s in samples):
            return Verdict()
        for sample in samples:
            if sample["label"] != "spam":
                continue
            a, b = set(normalized.split()), set(sample["text"].split())
            similar = len(a & b) / max(1, len(a | b))
            if sample["text"] == normalized or (min(len(a), len(b)) >= 5 and similar >= 0.90):
                return Verdict("شباهت به نمونهٔ تأییدشدهٔ مدیر", review=not conf["learned_enforce"])
    return Verdict()
