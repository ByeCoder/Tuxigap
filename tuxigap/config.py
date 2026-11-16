from dataclasses import dataclass
import os
from pathlib import Path

DEFAULTS = {
    "enabled": True,
    "dry_run": True,
    "flood": True,
    "flood_count": 6,
    "flood_seconds": 10,
    "duplicates": True,
    "profanity": True,
    "words": [],
    "links": False,
    "forwards": False,
    "media": False,
    "stickers": False,
    "bots": False,
    "captcha": False,
    "welcome": True,
    "welcome_text": "سلام {name} 🌷 به گروه خوش آمدی!",
    "rules": "قوانین هنوز تنظیم نشده‌اند.",
    "warn_limit": 3,
    "mute_minutes": 10,
    "action": "warn",
    "fun": True,
    "ai": False,
    "ai_moderation": False,
    "ai_threshold": 0.95,
    "learning": True,
    "learned_enforce": False,
    "reports": False,
    "report_hour": 9,
    "timezone": "Asia/Tehran",
    "week_start": 5,
    "log_chat": 0,
    "paid_gate": False,
    "external_spam": True,
    "external_review": True,
}


@dataclass(frozen=True)
class Config:
    token: str
    database: str = "data/tuxigap.sqlite3"
    owner_ids: tuple[int, ...] = ()
    api_base: str = "https://api.telegram.org"
    test_mode: bool = False
    ai_key: str = ""
    ai_base: str = "https://api.openai.com/v1"
    ai_model: str = ""
    ai_daily_limit: int = 100
    ai_user_limit: int = 10
    retention_days: int = 14
    support_username: str = ""
    terms_url: str = ""
    spam_engines: str = "{}"
    spam_engine_password: str = ""

    @classmethod
    def load(cls):
        from dotenv import load_dotenv

        load_dotenv()
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token or ":" not in token:
            raise ValueError("Set BOT_TOKEN in .env; never commit .env")
        return cls(
            token=token,
            database=os.getenv("DATABASE", "data/tuxigap.sqlite3"),
            owner_ids=tuple(int(x.strip()) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip()),
            api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
            test_mode=os.getenv("TELEGRAM_TEST_MODE", "0").lower() in ("1", "true", "yes"),
            ai_key=os.getenv("AI_API_KEY", ""),
            ai_base=os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            ai_model=os.getenv("AI_MODEL", ""),
            ai_daily_limit=int(os.getenv("AI_DAILY_LIMIT", "100")),
            ai_user_limit=int(os.getenv("AI_USER_DAILY_LIMIT", "10")),
            retention_days=max(1, int(os.getenv("RETENTION_DAYS", "14"))),
            support_username=os.getenv("SUPPORT_USERNAME", "").lstrip("@"),
            terms_url=os.getenv("TERMS_URL", ""),
            spam_engines=os.getenv("SPAM_ENGINES", "{}"),
            spam_engine_password=os.getenv("SPAM_ENGINE_PASSWORD", ""),
        )


def ensure_parent(path):
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
