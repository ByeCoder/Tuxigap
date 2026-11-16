"""Telegram presentation with safe emoji markers and per-request styling."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from html import escape
import re

STYLE = ContextVar("tuxigap_presentation", default={})
STYLES = {"primary", "success", "danger", "default"}
MARKER = re.compile(r"\[emoji:(\d{1,30})\|([^\[\]<>\n]{1,16})\]")
EMOJI_TAG = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.S)


@contextmanager
def using_presentation(conf):
    token = STYLE.set(conf)
    try:
        yield
    finally:
        STYLE.reset(token)


def rich_text(text):
    """Only our explicit emoji marker creates HTML. All other input stays escaped."""
    result, start = [], 0
    for match in MARKER.finditer(str(text)):
        result.append(escape(str(text)[start : match.start()]))
        result.append(f'<tg-emoji emoji-id="{match[1]}">{escape(match[2])}</tg-emoji>')
        start = match.end()
    result.append(escape(str(text)[start:]))
    return "".join(result)


def decorate_keyboard(markup):
    markup = deepcopy(markup)
    conf = STYLE.get()
    for row in markup.get("inline_keyboard", []):
        for b in row:
            b["text"] = str(b["text"])
            style = conf.get("button_style", "primary")
            if style != "default":
                b.setdefault("style", style)
            icon = conf.get("button_icon", "")
            if icon:
                b.setdefault("icon_custom_emoji_id", icon)
    return markup


def plain_presentation(data):
    result = deepcopy(data)
    if "text" in result:
        result["text"] = EMOJI_TAG.sub(r"\1", result["text"])
    for row in result.get("reply_markup", {}).get("inline_keyboard", []):
        for b in row:
            b.pop("icon_custom_emoji_id", None)
            b.pop("style", None)
    return result
