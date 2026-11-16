"""Free community engagement. Game coins are never payment currency."""

from html import escape
import secrets
import time

from .ui import button

TRUTHS = [
    "آخرین چیزی که یاد گرفتی چه بود؟",
    "اگر یک روز اینترنت قطع باشد چه می‌کنی؟",
    "کدام کتاب یا فیلم را پیشنهاد می‌کنی؟",
    "چه مهارتی را دوست داری یاد بگیری؟",
    "یک خاطرهٔ خنده‌دار و مناسب جمع تعریف کن.",
    "بهترین عادت کوچکت چیست؟",
]
DARES = [
    "با سه ایموجی روزت را توصیف کن!",
    "از یک عضو گروه بابت کمکش تشکر کن 🌷",
    "یک جمله بدون حرف الف بنویس!",
    "با کلمهٔ تاکسی یک شعر دوخطی بگو!",
    "یک نکتهٔ مفید که بلدی به گروه یاد بده.",
    "برای یک وسیلهٔ ساده یک اسم خلاقانه بساز!",
]
FORTUNES = [
    "امروز یک کار نیمه‌تمام کوچک را تمام کن 🌱",
    "یک گفتگوی خوب ممکن است روزت را بهتر کند ☀️",
    "یک استراحت کوتاه هم بخشی از پیشرفت است 🌷",
    "کنجکاوی امروز می‌تواند مهارت فردا شود 📚",
]


class Growth:
    def __init__(self, bot):
        self.bot, self.db, self.tg = bot, bot.db, bot.tg

    async def invite(self, chat, user):
        if self.db.chat(chat)["settings"]["paid_gate"]:
            return await self.tg.send(
                user,
                "برای گروه اشتراکی از لینک فروشگاه استفاده کنید:",
                [[{"text": "فروشگاه گروه", "url": f"https://t.me/{self.bot.username}?start=buy_{chat}"}]],
            )
        existing = self.db.one("SELECT link FROM invite_links WHERE chat=? AND inviter=?", (chat, user))
        if existing:
            link = existing["link"]
        else:
            result = await self.tg.call("createChatInviteLink", chat_id=chat, name=f"ref-{user}"[:32])
            link = result["invite_link"]
            self.db.execute("INSERT INTO invite_links VALUES(?,?,?)", (chat, user, link))
        await self.tg.send(
            user,
            "🔗 لینک معرفی تو؛ هر ورود معتبرِ تازه ۱۰ امتیاز و ۵ سکهٔ بازی دارد. خروج و ورود تکراری جایزه ندارد.",
            [[{"text": "لینک دعوت من", "url": link}]],
        )

    def record_join(self, chat, user, invite, eligible=True):
        if not invite or not eligible:
            return False
        owner = self.db.one("SELECT inviter FROM invite_links WHERE chat=? AND link=?", (chat, invite))
        if not owner or owner["inviter"] == user:
            return False
        with self.db.transaction():
            new = self.db.execute(
                "INSERT OR IGNORE INTO referrals VALUES(?,?,?,?)",
                (chat, user, owner["inviter"], int(time.time())),
            ).rowcount
            if not new:
                return False
            self.db.member(chat, owner["inviter"])
            self.db.execute(
                "UPDATE members SET xp=xp+10,coins=coins+5 WHERE chat=? AND user=?", (chat, owner["inviter"])
            )
            self.db.bump(chat, "referrals")
        return True

    async def giveaway(self, chat, title, minutes, creator):
        if not 1 <= minutes <= 10080 or not 1 <= len(title) <= 200:
            raise ValueError("عنوان تا ۲۰۰ نویسه و زمان ۱ تا ۱۰۰۸۰ دقیقه باشد.")
        token = secrets.token_hex(5)
        self.db.execute(
            "INSERT INTO giveaways(token,chat,title,creator,ends) VALUES(?,?,?,?,?)",
            (token, chat, title, creator, int(time.time()) + minutes * 60),
        )
        await self.tg.send(
            chat,
            f"🎉 <b>قرعه‌کشی رایگان</b>\n{escape(title)}\nزمان: {minutes} دقیقه\nورود رایگان؛ ۱۰۰ سکهٔ بازی برای برنده. تحویل جایزهٔ ذکرشده بر عهدهٔ مدیر است.",
            [[button("🎟 شرکت می‌کنم", f"g:{token}")]],
        )

    async def enter(self, token, user):
        giveaway = self.db.one("SELECT * FROM giveaways WHERE token=? AND state='open'", (token,))
        if not giveaway or giveaway["ends"] <= time.time():
            raise ValueError("این قرعه‌کشی تمام شده است.")
        await self.bot.require_member(giveaway["chat"], user)
        if not self.db.chat(giveaway["chat"])["settings"]["fun"]:
            raise ValueError("تعامل این گروه غیرفعال است.")
        count = self.db.one("SELECT count(*) n FROM giveaway_entries WHERE token=?", (token,))["n"]
        exists = self.db.one("SELECT 1 FROM giveaway_entries WHERE token=? AND user=?", (token, user))
        if count >= 500 and not exists:
            raise ValueError("ظرفیت ۵۰۰نفرهٔ این قرعه‌کشی پر شده است.")
        new = self.db.execute("INSERT OR IGNORE INTO giveaway_entries VALUES(?,?)", (token, user)).rowcount
        return "🎟 ثبت شد؛ موفق باشی!" if new else "قبلاً ثبت‌نام کرده‌ای؛ هر نفر یک شانس دارد."

    async def draw(self, now):
        for giveaway in self.db.all(
            "SELECT * FROM giveaways WHERE state='open' AND ends<=? LIMIT 10", (now,)
        ):
            # Eligibility is rechecked at draw time. Cap entries to keep one draw bounded.
            entries = self.db.all(
                "SELECT user FROM giveaway_entries WHERE token=? LIMIT 500", (giveaway["token"],)
            )
            secrets.SystemRandom().shuffle(entries)
            winner = 0
            for entry in entries:
                try:
                    await self.bot.require_member(giveaway["chat"], entry["user"])
                    winner = entry["user"]
                    break
                except ValueError:
                    continue
            with self.db.transaction():
                self.db.execute(
                    "UPDATE giveaways SET state='drawn',winner=? WHERE token=?", (winner, giveaway["token"])
                )
                if winner:
                    self.db.member(giveaway["chat"], winner)
                    self.db.execute(
                        "UPDATE members SET coins=coins+100 WHERE chat=? AND user=?",
                        (giveaway["chat"], winner),
                    )
        for giveaway in self.db.all("SELECT * FROM giveaways WHERE state='drawn' AND notified=0 LIMIT 10"):
            winner = giveaway["winner"]
            await self.tg.send(
                giveaway["chat"],
                f"🎉 نتیجهٔ قرعه‌کشی {escape(giveaway['title'])}\n"
                + (
                    f'برنده: <a href="tg://user?id={winner}">عضو خوش‌شانس</a> — ۱۰۰ سکهٔ بازی!'
                    if winner
                    else "شرکت‌کنندهٔ واجد شرایطی نبود."
                ),
            )
            self.db.execute("UPDATE giveaways SET notified=1 WHERE token=?", (giveaway["token"],))
