"""Free community engagement. Game coins are never payment currency."""

from .i18n import tr, lazy

from html import escape
import secrets
import time

from .ui import button
from .i18n import localize_user, using_language

TRUTHS = [
    lazy("m_420a59a4fd4d"),
    lazy("m_670725c6ff44"),
    lazy("m_ff9b97f2a79e"),
    lazy("m_d5b17002c458"),
    lazy("m_a76b1e1f81ef"),
    lazy("m_0595872f8f9a"),
]
DARES = [
    lazy("m_6fb3dc8702c8"),
    lazy("m_9698d71d45c8"),
    lazy("m_48c1fe3fc21d"),
    lazy("m_d6872f9efb68"),
    lazy("m_9f67794230d4"),
    lazy("m_937c8141c04b"),
]
FORTUNES = [
    lazy("m_442b3b432919"),
    lazy("m_33eb50eb358f"),
    lazy("m_f561a76cf71b"),
    lazy("m_afe10553a837"),
]


class Growth:
    def __init__(self, bot):
        self.bot, self.db, self.tg = bot, bot.db, bot.tg

    @localize_user(1)
    async def invite(self, chat, user):
        if self.db.chat(chat)["settings"]["paid_gate"]:
            return await self.tg.send(
                user,
                tr("m_b11f5fe3b950"),
                [
                    [
                        {
                            "text": tr("m_ab123de686f9"),
                            "url": f"https://t.me/{self.bot.username}?start=buy_{chat}",
                        }
                    ]
                ],
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
            tr("m_d612241d389c"),
            [[{"text": tr("m_e759d1a6eaab"), "url": link}]],
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
            raise ValueError(tr("m_7ce92da2fe0a"))
        token = secrets.token_hex(5)
        self.db.execute(
            "INSERT INTO giveaways(token,chat,title,creator,ends) VALUES(?,?,?,?,?)",
            (token, chat, title, creator, int(time.time()) + minutes * 60),
        )
        await self.tg.send(
            chat,
            tr("m_b5788b61747a", p0=escape(title), p1=minutes),
            [[button(tr("m_fc00229636b1"), f"g:{token}")]],
        )

    async def enter(self, token, user):
        giveaway = self.db.one("SELECT * FROM giveaways WHERE token=? AND state='open'", (token,))
        if not giveaway or giveaway["ends"] <= time.time():
            raise ValueError(tr("m_73f1359a3374"))
        await self.bot.require_member(giveaway["chat"], user)
        if not self.db.chat(giveaway["chat"])["settings"]["fun"]:
            raise ValueError(tr("m_eef779cc4f1c"))
        count = self.db.one("SELECT count(*) n FROM giveaway_entries WHERE token=?", (token,))["n"]
        exists = self.db.one("SELECT 1 FROM giveaway_entries WHERE token=? AND user=?", (token, user))
        if count >= 500 and not exists:
            raise ValueError(tr("m_262629f66c83"))
        new = self.db.execute("INSERT OR IGNORE INTO giveaway_entries VALUES(?,?)", (token, user)).rowcount
        return tr("m_370bac8e37ff") if new else tr("m_be05b86ae1ae")

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
            with using_language(self.db.chat(giveaway["chat"])["settings"].get("language", "en")):
                await self.tg.send(
                    giveaway["chat"],
                    tr("m_e70e76a24d21", p0=escape(giveaway["title"]))
                    + (tr("m_01d9d5d50542", p0=winner) if winner else tr("m_a76cc116c626")),
                )
            self.db.execute("UPDATE giveaways SET notified=1 WHERE token=?", (giveaway["token"],))
