"""Offline, context-local UI translation. User content is never auto-translated."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import json
from pathlib import Path
import string
from functools import wraps

DEFAULT_LANGUAGE = "en"
LANGUAGES = {
    "en": "English",
    "fa": "فارسی",
    "zh": "中文",
    "ru": "Русский",
    "he": "עברית",
    "es": "Español",
    "fr": "Français",
    "ar": "العربية",
    "de": "Deutsch",
    "tr": "Türkçe",
    "pt": "Português",
    "hi": "हिन्दी",
    "ja": "日本語",
    "ko": "한국어",
    "it": "Italiano",
}
RTL_LANGUAGES = {"fa", "ar", "he"}
_language = ContextVar("tuxigap_language", default=DEFAULT_LANGUAGE)
CATALOGS = Path(__file__).with_name("locales")


def normalize_language(code):
    code = str(code).lower().replace("_", "-").split("-")[0]
    code = {"iw": "he"}.get(code, code)
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def current_language():
    return _language.get()


@contextmanager
def using_language(code):
    token = _language.set(normalize_language(code))
    try:
        yield
    finally:
        _language.reset(token)


@lru_cache(maxsize=32)
def catalog(code):
    path = CATALOGS / (normalize_language(code) + ".json")
    return json.loads(path.read_text()) if path.is_file() else {}


def tr(key, **values):
    base = catalog(DEFAULT_LANGUAGE)
    template = catalog(current_language()).get(key, base.get(key, key))
    try:
        return template.format(**values) if values else template
    except (KeyError, ValueError, IndexError, TypeError):
        fallback = base.get(key, key)
        return fallback.format(**values) if values else fallback


class LazyText(str):
    """Module-level UI labels resolve when displayed, rather than when imported."""

    def __new__(cls, key):
        obj = str.__new__(cls, catalog(DEFAULT_LANGUAGE).get(key, key))
        obj.key = key
        return obj

    def __str__(self):
        return tr(self.key)

    def __format__(self, spec):
        return format(str(self), spec)

    def __add__(self, other):
        return str(self) + str(other)

    def __radd__(self, other):
        return str(other) + str(self)


def lazy(key):
    return LazyText(key)


def localize_user(index=0):
    def decorate(function):
        from inspect import signature

        parameter = list(signature(function).parameters)[index + 1]

        @wraps(function)
        async def wrapped(self, *args, **kwargs):
            user = args[index] if len(args) > index else kwargs[parameter]
            with using_language(self.db.get(f"user_language:{user}", DEFAULT_LANGUAGE)):
                return await function(self, *args, **kwargs)

        return wrapped

    return decorate


def placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def validate_catalogs():
    base = catalog(DEFAULT_LANGUAGE)
    errors = []
    for code in LANGUAGES:
        for key, text in catalog(code).items():
            if key not in base:
                errors.append(f"{code}: unknown key {key}")
            elif placeholders(text) != placeholders(base[key]):
                errors.append(f"{code}: placeholder mismatch for {key}")
    return errors
