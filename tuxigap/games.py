from datetime import datetime, timedelta
import json
import secrets
import time
from zoneinfo import ZoneInfo

JOKES = [
    "برنامه‌نویس رفت نونوایی گفت: دو تا نون بده، اگه تخم‌مرغ داشتی دوازده تا! 🥚",
    "می‌خواستم امروز خیلی مفید باشم؛ اینترنت وصل شد و نقشه‌ام عوض شد 😄",
    "دانشجو: پایان‌نامه‌ام تقریباً تمومه؛ فقط مونده شروعش کنم! 📚",
    "ربات هم گاهی نیاز به استراحت داره؛ اسمش رو می‌ذاره maintenance 🤖",
    "من باگ ندارم، فقط چند تا قابلیت مستندنشده دارم 🐛",
]
TRIVIA = [
    ("پایتخت ایران کجاست؟", ["تهران", "شیراز", "تبریز", "اصفهان"], 0),
    ("کدام سیاره به سیارهٔ سرخ معروف است؟", ["زهره", "مریخ", "زحل", "عطارد"], 1),
    ("حاصل ۱۲ × ۸ چند است؟", ["۸۴", "۹۸", "۹۶", "۸۸"], 2),
    ("فرمول شیمیایی آب چیست؟", ["CO₂", "O₂", "NaCl", "H₂O"], 3),
    ("کدام زبان برنامه‌نویسی نام یک مار هم هست؟", ["Python", "Rust", "Java", "Go"], 0),
    ("واحد مقاومت الکتریکی چیست؟", ["آمپر", "اهم", "وات", "ولت"], 1),
    ("فتوسنتز بیشتر در کدام اندام گیاه انجام می‌شود؟", ["ریشه", "دانه", "برگ", "گل"], 2),
    ("بزرگ‌ترین اقیانوس کدام است؟", ["اطلس", "هند", "منجمد شمالی", "آرام"], 3),
    ("یک بایت چند بیت است؟", ["۸", "۱۶", "۴", "۳۲"], 0),
    ("خالق شاهنامه کیست؟", ["سعدی", "فردوسی", "حافظ", "نظامی"], 1),
    ("کدام جانور پستاندار است؟", ["کوسه", "اختاپوس", "دلفین", "پنگوئن"], 2),
    ("رنگ حاصل از ترکیب نور قرمز و سبز چیست؟", ["بنفش", "آبی", "فیروزه‌ای", "زرد"], 3),
]


def quiz(db, chat):
    question, options, correct = secrets.choice(TRIVIA)
    token = secrets.token_hex(5)
    db.execute(
        "INSERT INTO games VALUES(?,?,?,?,NULL)",
        (token, chat, json.dumps({"answer": correct}), int(time.time()) + 300),
    )
    return question, [[{"text": label, "callback_data": f"q:{token}:{i}"}] for i, label in enumerate(options)]


def answer_quiz(db, token, user, choice):
    with db.transaction():
        game = db.one("SELECT * FROM games WHERE token=?", (token,))
        if not game or game["expires"] < time.time() or game["winner"] is not None:
            return None, "این مسابقه تمام شده است."
        if not db.execute("INSERT OR IGNORE INTO attempts VALUES(?,?)", (token, user)).rowcount:
            return None, "هر نفر یک فرصت دارد."
        if int(choice) != json.loads(game["data"])["answer"]:
            return None, "این پاسخ درست نبود 🙂"
        db.execute("UPDATE games SET winner=? WHERE token=?", (user, token))
        db.member(game["chat"], user)
        db.execute("UPDATE members SET xp=xp+25,coins=coins+10 WHERE chat=? AND user=?", (game["chat"], user))
        db.bump(game["chat"], "games")
    return game["chat"], "درست بود! ۲۵ امتیاز و ۱۰ سکه گرفتی 🎉"


def daily(db, chat, user, tz="Asia/Tehran", now=None):
    today = datetime.fromtimestamp(now or time.time(), ZoneInfo(tz)).date()
    with db.transaction():
        member = db.member(chat, user)
        if member["daily_day"] == str(today):
            return "پاداش امروز را گرفته‌ای؛ فردا دوباره بیا 🌷"
        streak = member["streak"] + 1 if member["daily_day"] == str(today - timedelta(days=1)) else 1
        reward = 10 + min(streak, 7) * 2
        db.execute(
            "UPDATE members SET daily_day=?,streak=?,coins=coins+?,xp=xp+10 WHERE chat=? AND user=?",
            (str(today), streak, reward, chat, user),
        )
    return f"🎁 {reward} سکه و ۱۰ امتیاز گرفتی؛ زنجیرهٔ حضور: {streak} روز"
