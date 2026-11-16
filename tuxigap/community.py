"""Community features: AFK, trusted members, join raids and federation jobs."""

from .i18n import tr

import secrets
import time

from .telegram import APIError


class Community:
    def __init__(self, bot):
        self.bot, self.db, self.tg = bot, bot.db, bot.tg

    def raid(self, chat, user, now=None):
        now = int(time.time()) if now is None else now
        self.db.execute("INSERT OR IGNORE INTO join_events VALUES(?,?,?)", (chat, user, now))
        c = self.db.chat(chat)["settings"]
        if not c["anti_raid"]:
            return False
        recent = self.db.one(
            "SELECT count(*) n FROM join_events WHERE chat=? AND ts>=?", (chat, now - c["raid_window"])
        )["n"]
        if recent >= c["raid_limit"]:
            self.db.set(f"raid_until:{chat}", now + 300)
        return (self.db.get(f"raid_until:{chat}", 0) or 0) > now

    def create_federation(self, owner, name):
        if not 1 <= len(name) <= 80:
            raise ValueError(tr("m_257e9fd27662"))
        fid = secrets.token_hex(6)
        self.db.execute("INSERT INTO federations VALUES(?,?,?)", (fid, owner, name))
        return fid

    async def request_join(self, chat, actor, fid):
        member = await self.tg.call("getChatMember", chat_id=chat, user_id=actor)
        if member["status"] != "creator":
            raise ValueError(tr("m_b17dd79a6ee9"))
        federation = self.db.one("SELECT * FROM federations WHERE id=?", (fid,))
        if not federation:
            raise ValueError(tr("m_b99099bdfb69"))
        existing = self.db.one("SELECT * FROM federation_chats WHERE chat=?", (chat,))
        if existing and existing["state"] == "active":
            raise ValueError(tr("m_2463b73c1435"))
        state = "active" if federation["owner"] == actor else "pending"
        self.db.execute("INSERT OR REPLACE INTO federation_chats VALUES(?,?,?)", (chat, fid, state))
        if state == "active":
            self.queue_existing(fid, chat)
        return federation, state

    def queue_existing(self, fid, chat):
        for ban in self.db.all("SELECT * FROM federation_bans WHERE fid=? AND active=1", (fid,)):
            self.db.execute(
                "INSERT INTO federation_jobs(fid,chat,user,action,version,due) VALUES(?,?,?,'ban',?,?)",
                (fid, chat, ban["user"], ban["version"], int(time.time())),
            )

    async def decide(self, fid, actor, chat, approve):
        federation = self.db.one("SELECT * FROM federations WHERE id=?", (fid,))
        if not federation or federation["owner"] != actor:
            raise ValueError(tr("m_9f749bb044e1"))
        member = self.db.one(
            "SELECT * FROM federation_chats WHERE chat=? AND fid=? AND state='pending'", (chat, fid)
        )
        if not member:
            raise ValueError(tr("m_64a4c233022b"))
        if approve:
            self.db.execute("UPDATE federation_chats SET state='active' WHERE chat=?", (chat,))
            self.queue_existing(fid, chat)
        else:
            self.db.execute("DELETE FROM federation_chats WHERE chat=?", (chat,))

    def federation_action(self, chat, actor, user, reason, active):
        joined = self.db.one(
            "SELECT f.* FROM federations f JOIN federation_chats c ON c.fid=f.id WHERE c.chat=? AND c.state='active'",
            (chat,),
        )
        if not joined or joined["owner"] != actor:
            raise ValueError(tr("m_274eeeb7b9a7"))
        fid = joined["id"]
        old = self.db.one("SELECT version FROM federation_bans WHERE fid=? AND user=?", (fid, user))
        version = old["version"] + 1 if old else 1
        with self.db.transaction():
            self.db.execute(
                "INSERT OR REPLACE INTO federation_bans VALUES(?,?,?,?,?,?)",
                (fid, user, reason[:300], int(active), actor, version),
            )
            for target in self.db.all(
                "SELECT chat FROM federation_chats WHERE fid=? AND state='active'", (fid,)
            ):
                self.db.execute(
                    "INSERT INTO federation_jobs(fid,chat,user,action,version,due) VALUES(?,?,?,?,?,?)",
                    (fid, target["chat"], user, "ban" if active else "unban", version, int(time.time())),
                )
        return fid

    async def enforce_federations(self, now):
        for job in self.db.all(
            "SELECT * FROM federation_jobs WHERE state='pending' AND due<=? ORDER BY id LIMIT 20", (now,)
        ):
            ban = self.db.one(
                "SELECT * FROM federation_bans WHERE fid=? AND user=?", (job["fid"], job["user"])
            )
            joined = self.db.one(
                "SELECT 1 FROM federation_chats WHERE chat=? AND fid=? AND state='active'",
                (job["chat"], job["fid"]),
            )
            if not joined or not ban or ban["version"] != job["version"]:
                self.db.execute("UPDATE federation_jobs SET state='stale' WHERE id=?", (job["id"],))
                continue
            try:
                if await self.bot.admin(job["chat"], job["user"]) or job["user"] == self.bot.bot_id:
                    self.db.execute("UPDATE federation_jobs SET state='protected' WHERE id=?", (job["id"],))
                    continue
                if job["action"] == "ban":
                    current = await self.tg.call("getChatMember", chat_id=job["chat"], user_id=job["user"])
                    if current["status"] != "kicked":
                        await self.tg.call("banChatMember", chat_id=job["chat"], user_id=job["user"])
                        self.db.execute(
                            "INSERT OR REPLACE INTO federation_enforced VALUES(?,?,?)",
                            (job["fid"], job["chat"], job["user"]),
                        )
                elif self.db.one(
                    "SELECT 1 FROM federation_enforced WHERE fid=? AND chat=? AND user=?",
                    (job["fid"], job["chat"], job["user"]),
                ):
                    if self.db.chat(job["chat"])["settings"]["paid_gate"] and not self.bot.billing.active(
                        job["chat"], job["user"]
                    ):
                        self.db.execute(
                            "INSERT INTO subscriptions VALUES(?,?,0,1) ON CONFLICT(chat,user) DO UPDATE SET expired_ban=1",
                            (job["chat"], job["user"]),
                        )
                    else:
                        await self.tg.call(
                            "unbanChatMember", chat_id=job["chat"], user_id=job["user"], only_if_banned=True
                        )
                    self.db.execute(
                        "DELETE FROM federation_enforced WHERE fid=? AND chat=? AND user=?",
                        (job["fid"], job["chat"], job["user"]),
                    )
                self.db.audit(
                    job["chat"], job["user"], 0, ban["actor"], "fed_" + job["action"], ban["reason"]
                )
                self.db.execute("UPDATE federation_jobs SET state='done' WHERE id=?", (job["id"],))
            except APIError:
                self.db.execute(
                    "UPDATE federation_jobs SET due=?,attempts=attempts+1 WHERE id=?", (now + 120, job["id"])
                )
