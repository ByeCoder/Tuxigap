from .i18n import tr
from dataclasses import dataclass
import re
import time
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from .ported.locks import evaluate, trusted_urls, urls


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
    if conf.get("night_mode"):
        hour = datetime.fromtimestamp(now, ZoneInfo(conf["timezone"])).hour
        start, end = conf["night_start"], conf["night_end"]
        quiet = (start <= hour < end) if start < end else (hour >= start or hour < end)
        if quiet:
            return Verdict(tr("m_f7eeb4d510a5"))
    locked = evaluate(conf.get("locks", []), message, chat, conf.get("allowlist", []))
    if locked:
        return Verdict(tr("m_de75ab0661e3") + ", ".join(locked))
    if conf.get("links_limit", -1) >= 0 and len(urls(message)) > conf["links_limit"]:
        return Verdict(tr("m_a84727803d64"))
    entities = message.get("entities", []) + message.get("caption_entities", [])
    if (
        conf.get("mentions_limit", -1) >= 0
        and sum(e.get("type") in ("mention", "text_mention") for e in entities) > conf["mentions_limit"]
    ):
        return Verdict(tr("m_0c648f609468"))
    if conf["profanity"] and prohibited(text, conf["words"]):
        return Verdict(tr("m_d220dd8cbcd7"))
    entities = message.get("entities", []) + message.get("caption_entities", [])
    if (
        conf["links"]
        and not trusted_urls(message, conf.get("allowlist", []))
        and (
            any(e.get("type") in ("url", "text_link") for e in entities)
            or re.search(r"(?:https?://|www\.|t\.me/)", text, re.I)
        )
    ):
        return Verdict(tr("m_2872ac6e771c"))
    if conf["forwards"] and message.get("forward_origin"):
        return Verdict(tr("m_e1eb9b831335"))
    if conf["media"] and any(
        k in message for k in ("photo", "video", "document", "audio", "voice", "animation", "video_note")
    ):
        return Verdict(tr("m_06a68c461f79"))
    if conf["stickers"] and "sticker" in message:
        return Verdict(tr("m_57fd2aa681c7"))
    if conf["bots"] and message.get("from", {}).get("is_bot"):
        return Verdict(tr("m_30c820f11eca"))
    if conf["flood"]:
        count = db.one(
            "SELECT count(*) n FROM messages WHERE chat=? AND user=? AND ts>=?",
            (chat, user, now - conf["flood_seconds"]),
        )["n"]
        if count > conf["flood_count"]:
            return Verdict(tr("m_05352cf4fd71"))
    if conf["duplicates"] and len(normalized) >= 8:
        recent = db.all(
            "SELECT text FROM messages WHERE chat=? AND user=? AND ts>=? AND mid<>? ORDER BY ts DESC LIMIT 15",
            (chat, user, now - 60, message["message_id"]),
        )
        if sum(normalize(row["text"]) == normalized for row in recent) >= 2:
            return Verdict(tr("m_3ff464b9eae4"))
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
                return Verdict(tr("m_134090645bb6"), review=not conf["learned_enforce"])
    return Verdict()
