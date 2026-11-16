from .i18n import tr, lazy
from datetime import datetime
from html import escape
import json
import logging
import secrets
import time
import httpx
from zoneinfo import ZoneInfo

from . import games, stats
from .ai import AI, AIUnavailable
from .billing import Billing, PaymentNeedsReview, accept_payment, mark_refunded
from .engines import SpamEngine
from .growth import Growth, TRUTHS, DARES, FORTUNES
from .community import Community
from .ported import fun as ported_fun
from .ported.locks import LOCK_TYPES
from .i18n import LANGUAGES, DEFAULT_LANGUAGE, using_language
from .moderation import Verdict, local_check
from .telegram import APIError
from .ui import admin_keyboard, button, fun_keyboard, panel_title

log = logging.getLogger("tuxigap")
MEMBER_STATUSES = {"member", "administrator", "creator"}
BOOL_FIELDS = {
    "anti_raid",
    "night_mode",
    "ai_vision",
    "external_spam",
    "external_review",
    "enabled",
    "dry_run",
    "flood",
    "duplicates",
    "profanity",
    "links",
    "forwards",
    "media",
    "stickers",
    "bots",
    "captcha",
    "welcome",
    "fun",
    "ai",
    "ai_moderation",
    "learning",
    "learned_enforce",
    "reports",
}
SECTIONS = {"home", "mod", "learn", "content", "plans", "settings", "stats", "fun"}
INPUTS = {
    "locks",
    "allowlist",
    "night",
    "limits",
    "ai_history",
    "giveaway",
    "poll",
    "note",
    "filter",
    "log_chat",
    "words",
    "flood",
    "warn_limit",
    "mute_minutes",
    "timezone",
    "report_hour",
    "welcome_text",
    "rules",
    "schedule",
    "plan",
}
HELP = lazy("m_371a590d0cf3")


def present(member):
    return member.get("status") in MEMBER_STATUSES or (
        member.get("status") == "restricted" and member.get("is_member", False)
    )


class Bot:
    def __init__(self, config, db, tg):
        self.config, self.db, self.tg = config, db, tg
        self.ai = AI(config, db)
        self.billing = Billing(db, tg, config)
        self.engine = SpamEngine(config, db)
        self.growth = Growth(self)
        self.community = Community(self)
        self.bot_id = db.get("bot_id", 0)
        self.username = db.get("bot_username", "")

    async def admin(self, chat, user, right=None):
        member = await self.tg.call("getChatMember", chat_id=chat, user_id=user)
        if member["status"] == "creator":
            return True
        return member["status"] == "administrator" and (not right or member.get(right, False))

    async def require_admin(self, chat, user, right=None):
        if not await self.admin(chat, user, right):
            raise ValueError(tr("m_3dc694ddff8f"))

    async def require_member(self, chat, user):
        member = await self.tg.call("getChatMember", chat_id=chat, user_id=user)
        if not present(member):
            raise ValueError(tr("m_b5012798f936"))

    async def protect_target(self, chat, user):
        if user == self.bot_id or await self.admin(chat, user):
            raise ValueError(tr("m_897d4fc9c35e"))

    async def panel(self, chat, user, destination, section="home", mid=None):
        await self.require_admin(chat, user)
        info = self.db.chat(chat)
        text = panel_title(info, section)
        markup = admin_keyboard(chat, section, info["settings"])
        if section == "home" and self.config.studio_url:
            markup.append([{"text": "Studio companion ↗", "url": self.config.studio_url}])
        if mid:
            try:
                return await self.tg.call(
                    "editMessageText",
                    chat_id=destination,
                    message_id=mid,
                    text=text,
                    parse_mode="HTML",
                    reply_markup={"inline_keyboard": markup},
                )
            except APIError as exc:
                if "message is not modified" in exc.description.lower():
                    return
                if exc.code != 400:
                    raise
        return await self.tg.send(destination, text, markup)

    async def log_action(self, chat, text, keyboard=None):
        conf = self.db.chat(chat)["settings"]
        destination = conf["log_chat"] or chat
        await self.tg.send(destination, text, keyboard)

    async def send_stats(self, chat, destination, period, now=None, previous=False):
        with using_language(self.db.chat(chat)["settings"].get("language", DEFAULT_LANGUAGE)):
            return await self._send_stats(chat, destination, period, now, previous)

    async def _send_stats(self, chat, destination, period, now=None, previous=False):
        text = stats.report(self.db, chat, period, now, previous)[0]
        try:
            count = await self.tg.call("getChatMemberCount", chat_id=chat)
            text += tr("m_c460dcd5605c", p0=count)
        except APIError:
            text += tr("m_a3068da818e2")
        return await self.tg.send(destination, text)

    async def release(self, chat, user):
        await self.protect_target(chat, user)
        info = await self.tg.call("getChat", chat_id=chat)
        permissions = info.get("permissions")
        if not permissions:
            raise ValueError(tr("m_5b99d02a987a"))
        await self.tg.call(
            "restrictChatMember",
            chat_id=chat,
            user_id=user,
            permissions=permissions,
            use_independent_chat_permissions=True,
        )

    async def moderate(self, chat, message, verdict):
        user, mid = message["from"]["id"], message["message_id"]
        conf = self.db.chat(chat)["settings"]
        row = self.db.one(
            "SELECT * FROM audit WHERE chat=? AND mid=? AND actor=0 AND action='moderation' ORDER BY id DESC LIMIT 1",
            (chat, mid),
        )
        if row and row["status"] == "done":
            return
        if not row:
            aid = self.db.audit(
                chat,
                user,
                mid,
                0,
                "moderation",
                verdict.reason,
                message.get("text", message.get("caption", "")),
                "pending",
            )
            self.db.bump(chat, "flagged")
            row = self.db.one("SELECT * FROM audit WHERE id=?", (aid,))
        aid = row["id"]
        review = [
            [button(tr("m_9d8d730942a8"), f"v:{aid}:ham"), button(tr("m_dec737db3880"), f"v:{aid}:spam")]
        ]
        if conf["dry_run"] or verdict.review:
            prefix = tr("m_1e1d633b8335") if conf["dry_run"] else tr("m_e10cc1d2fdd1")
            await self.log_action(
                chat,
                tr(
                    "m_c8b04e059db5",
                    p0=prefix,
                    p1=escape(verdict.reason),
                    p2=user,
                    p3=escape(row["text"][:500]),
                ),
                review,
            )
            self.db.execute("UPDATE audit SET status='done' WHERE id=?", (aid,))
            return
        await self.protect_target(chat, user)
        if row["status"] == "pending":
            try:
                await self.tg.call("deleteMessage", chat_id=chat, message_id=mid)
            except APIError as exc:
                if "message to delete not found" not in exc.description.lower():
                    raise
            with self.db.transaction():
                self.db.bump(chat, "deleted")
                self.db.member(chat, user)
                if conf["action"] == "warn":
                    self.db.execute("UPDATE members SET warns=warns+1 WHERE chat=? AND user=?", (chat, user))
                    self.db.bump(chat, "warns")
                self.db.execute("UPDATE audit SET status='counted' WHERE id=?", (aid,))
        warns = self.db.member(chat, user)["warns"]
        if conf["action"] == "mute" or (conf["action"] == "warn" and warns >= conf["warn_limit"]):
            await self.tg.call(
                "restrictChatMember",
                chat_id=chat,
                user_id=user,
                permissions={"can_send_messages": False},
                use_independent_chat_permissions=True,
                until_date=int(time.time()) + conf["mute_minutes"] * 60,
            )
            self.db.bump(chat, "mutes")
            self.db.execute("UPDATE members SET warns=0 WHERE chat=? AND user=?", (chat, user))
        self.db.execute("UPDATE audit SET status='done' WHERE id=?", (aid,))
        await self.log_action(chat, tr("m_eaa45c0b255f", p0=user, p1=escape(verdict.reason)), review)

    async def feedback(self, aid, label, actor, destination):
        row = self.db.one("SELECT * FROM audit WHERE id=?", (aid,))
        if not row:
            raise ValueError(tr("m_c7f82ec5ad5e"))
        await self.require_admin(row["chat"], actor, "can_delete_messages")
        if label not in ("ham", "spam"):
            raise ValueError(tr("m_dba412cb74f2"))
        self.db.train(row["chat"], row["text"], label, actor, row["user"])
        self.engine.train(row["chat"], row["text"], label)
        self.db.audit(row["chat"], row["user"], row["mid"], actor, "feedback", label)
        await self.tg.send(
            destination,
            tr("m_fe01da3c03f2"),
        )

    async def handle(self, update):
        if "pre_checkout_query" in update:
            return await self.billing.precheckout(update["pre_checkout_query"])
        if "inline_query" in update:
            q = update["inline_query"]
            items = [
                {
                    "type": "article",
                    "id": secrets.token_hex(4),
                    "title": tr("m_2704d1c5035a"),
                    "input_message_content": {"message_text": str(secrets.choice(games.JOKES))},
                },
                {
                    "type": "article",
                    "id": "play",
                    "title": tr("m_52f422528e3e"),
                    "input_message_content": {"message_text": tr("m_fa994b2b5796")},
                },
            ]
            return await self.tg.call(
                "answerInlineQuery", inline_query_id=q["id"], results=items, cache_time=0, is_personal=True
            )
        if "callback_query" in update:
            return await self.callback(update["callback_query"])
        if "my_chat_member" in update:
            m = update["my_chat_member"]
            if m["chat"]["type"] != "private":
                self.db.register(m["chat"])
                self.db.setting(
                    m["chat"]["id"], "enabled", m["new_chat_member"]["status"] not in ("left", "kicked")
                )
            return
        if "chat_join_request" in update:
            return await self.billing.join_request(update["chat_join_request"])
        if "chat_member" in update:
            return await self.membership(update["chat_member"])
        if "message_reaction" in update:
            m = update["message_reaction"]
            if self.db.one("SELECT id FROM chats WHERE id=?", (m["chat"]["id"],)):
                self.db.bump(m["chat"]["id"], "reaction_events")
            return
        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
            or update.get("edited_channel_post")
        )
        if message:
            return await self.message(
                message, edited="edited_message" in update or "edited_channel_post" in update
            )

    async def message(self, m, edited=False):
        chat, user = m["chat"]["id"], m.get("from", {}).get("id", 0)
        text = m.get("text", m.get("caption", ""))
        private = m["chat"]["type"] == "private"
        if "successful_payment" in m:
            try:
                result = accept_payment(self.db, user, m["successful_payment"], m.get("date"))
            except ValueError:
                charge = m["successful_payment"].get("telegram_payment_charge_id", "unknown")
                alert_key = "payment_review:" + charge
                if not self.db.get(alert_key):
                    for owner in self.config.owner_ids:
                        try:
                            await self.tg.send(
                                owner,
                                tr("m_8c5f80a1b761", p0=escape(charge), p1=user),
                            )
                        except APIError:
                            pass
                    self.db.set(alert_key, True)
                raise PaymentNeedsReview() from None
            if result:
                await self.tg.send(user, tr("m_82f668ef3d59"))
            return
        if "refunded_payment" in m:
            mark_refunded(self.db, m["refunded_payment"]["telegram_payment_charge_id"])
            return
        if not private:
            self.db.register(m["chat"])
            if user:
                self.db.member(chat, user, m.get("from", {}).get("first_name", ""))
            kind = "text" if "text" in m else "media"
            is_content = text or any(
                k in m
                for k in (
                    "photo",
                    "sticker",
                    "animation",
                    "document",
                    "audio",
                    "video",
                    "voice",
                    "poll",
                    "video_note",
                )
            )
            fresh = (
                self.db.message(chat, m["message_id"], user, text, kind, m.get("date", int(time.time())))
                if is_content
                else False
            )
            if edited:
                self.db.execute(
                    "UPDATE messages SET text=? WHERE chat=? AND mid=?", (text[:4000], chat, m["message_id"])
                )
            conf = self.db.chat(chat)["settings"]
            if (
                conf["enabled"]
                and is_content
                and m.get("sender_chat")
                and m["chat"]["type"] in ("group", "supergroup")
            ):
                from .ported.locks import evaluate

                if m["sender_chat"]["id"] != chat:
                    violations = evaluate(conf["locks"], m, chat, conf["allowlist"])
                    if violations:
                        self.db.bump(chat, "flagged")
                        if not conf["dry_run"]:
                            await self.tg.call("deleteMessage", chat_id=chat, message_id=m["message_id"])
                            self.db.bump(chat, "deleted")
                        self.db.audit(
                            chat, 0, m["message_id"], 0, "sender_chat_lock", ", ".join(violations), text
                        )
                        return
            if (
                conf["enabled"]
                and user
                and not m.get("sender_chat")
                and m["chat"]["type"] in ("group", "supergroup")
                and is_content
            ):
                if not await self.admin(chat, user) and not self.db.one(
                    "SELECT 1 FROM approved WHERE chat=? AND user=?", (chat, user)
                ):
                    verdict = local_check(self.db, chat, user, m, conf)
                    if not verdict.flagged and conf["external_spam"] and text:
                        flagged = await self.engine.check(chat, user, text, m["from"].get("username", ""))
                        if flagged:
                            verdict = Verdict(tr("m_bb56814f818a"), review=conf["external_review"])
                    if not verdict.flagged and conf["ai_moderation"] and text and not text.startswith("/"):
                        try:
                            flagged, confidence, reason = await self.ai.moderate(
                                chat, user, text, conf["rules"]
                            )
                            if flagged and confidence >= conf["ai_threshold"]:
                                verdict = Verdict(tr("m_dd54be8da4eb") + reason, review=True)
                        except AIUnavailable:
                            pass
                    if not verdict.flagged and conf["ai_vision"] and m.get("photo"):
                        try:
                            photo = next(
                                (p for p in reversed(m["photo"]) if p.get("file_size", 0) <= 2 * 1024 * 1024),
                                m["photo"][0],
                            )
                            image = await self.tg.photo_bytes(photo["file_id"])
                            flagged, confidence, reason = await self.ai.vision(
                                chat, user, image, text, conf["rules"]
                            )
                            if flagged and confidence >= conf["ai_threshold"]:
                                verdict = Verdict(tr("m_de52a54ecd20") + reason, review=True)
                        except (AIUnavailable, APIError, ValueError, httpx.HTTPError):
                            pass
                    if verdict.flagged:
                        await self.moderate(chat, m, verdict)
                        return
                    if fresh and not text.startswith("/") and self.db.cooldown(chat, user, "xp", 60):
                        self.db.execute(
                            "UPDATE members SET xp=xp+2,coins=coins+1 WHERE chat=? AND user=?", (chat, user)
                        )
            if not is_content:
                return
            if fresh and not edited and text and not text.startswith("/afk"):
                status = self.db.one("SELECT * FROM afk WHERE chat=? AND user=?", (chat, user))
                if status:
                    self.db.execute("DELETE FROM afk WHERE chat=? AND user=?", (chat, user))
                    await self.tg.send(chat, tr("m_e2c52728e020"))
                reply_user = m.get("reply_to_message", {}).get("from", {}).get("id")
                if reply_user:
                    away = self.db.one("SELECT * FROM afk WHERE chat=? AND user=?", (chat, reply_user))
                    if away and self.db.cooldown(chat, reply_user, "afk_notice", 60):
                        await self.tg.send(chat, tr("m_56f91cb17f86") + escape(away["text"]))
        if text.startswith("/"):
            first, _, args = text.partition(" ")
            base, _, mention = first[1:].partition("@")
            if mention and mention.lower() != self.username.lower():
                return
            await self.command(base.lower(), args.strip(), m)
        elif private:
            session = self.db.one(
                "SELECT * FROM sessions WHERE user=? AND expires>?", (user, int(time.time()))
            )
            if session:
                await self.save_input(user, session["chat"], session["field"], text)
        elif text and user:
            from .moderation import normalize

            matched = self.db.one(
                "SELECT body FROM filters WHERE chat=? AND trigger=?", (chat, normalize(text))
            )
            if matched and self.db.cooldown(chat, user, "autoresponder", 15):
                await self.tg.send(chat, escape(matched["body"]))

    async def command(self, cmd, args, m):
        chat, user = m["chat"]["id"], m.get("from", {}).get("id", 0)
        private = m["chat"]["type"] == "private"
        if not user:
            return
        if cmd in ("language", "lang"):
            if not private:
                await self.require_admin(chat, user)
            if args:
                return await self.change_language(chat, user, args.strip(), chat)
            return await self.choose_language(chat, chat)
        if cmd == "fedcreate":
            if not private:
                raise ValueError(tr("m_f9d7aad93ea8"))
            fid = self.community.create_federation(user, args)
            return await self.tg.send(
                user,
                tr("m_6fbc52a08d89", p0=fid, p1=fid),
            )
        if not private and cmd == "fedjoin":
            federation, state = await self.community.request_join(chat, user, args.strip())
            if state == "pending":
                await self.tg.send(
                    federation["owner"],
                    tr("m_d117625f74c1", p0=escape(federation["name"]), p1=chat),
                    [
                        [
                            button(tr("m_474962bcd5f5"), f"fed:yes:{federation['id']}:{chat}"),
                            button(tr("m_a2d285b35287"), f"fed:no:{federation['id']}:{chat}"),
                        ]
                    ],
                )
            return await self.tg.send(
                chat,
                tr("m_bee1b5013403") if state == "active" else tr("m_dea1f2465667"),
            )
        if not private and cmd == "fedleave":
            member = await self.tg.call("getChatMember", chat_id=chat, user_id=user)
            if member["status"] != "creator":
                raise ValueError(tr("m_144602abe4f9"))
            self.db.execute("DELETE FROM federation_chats WHERE chat=?", (chat,))
            return await self.tg.send(
                chat,
                tr("m_1f29c00d9efe"),
            )
        if not private and cmd in ("fban", "funban"):
            await self.require_admin(chat, user, "can_restrict_members")
            replied = m.get("reply_to_message", {}).get("from", {})
            target = replied.get("id") or int(args.split()[0])
            await self.protect_target(chat, target)
            fid = self.community.federation_action(
                chat, user, target, args or "Federation policy", cmd == "fban"
            )
            return await self.tg.send(
                chat,
                tr("m_45b52b2b7ebc", p0=fid),
            )
        if cmd == "cancel":
            self.db.execute("DELETE FROM sessions WHERE user=?", (user,))
            return await self.tg.send(chat, tr("m_ff62862fd7a9"))
        if cmd in ("help", "start"):
            if cmd == "start" and args.startswith("buy_"):
                return await self.store(user, int(args[4:]))
            if cmd == "start" and args.startswith("manage_"):
                return await self.panel(int(args[7:]), user, user)
            await self.tg.send(chat, HELP)
            if private:
                return await self.my_chats(user)
            return
        if cmd == "connect" and private:
            info = await self.tg.call("getChat", chat_id=int(args))
            if info["type"] == "private":
                raise ValueError(tr("m_5caf32d76d75"))
            await self.require_admin(info["id"], user)
            if not await self.admin(info["id"], self.bot_id):
                raise ValueError(tr("m_a39c39637359"))
            self.db.register(info)
            return await self.panel(info["id"], user, user)
        if cmd == "panel":
            if private:
                return await self.my_chats(user)
            return await self.panel(chat, user, chat)
        if cmd == "manage" and not private:
            await self.require_admin(chat, user)
            target = m.get("reply_to_message")
            if not target or not target.get("from") or target.get("sender_chat"):
                raise ValueError(tr("m_b660a64fadb6"))
            uid, message_id = target["from"]["id"], target["message_id"]

            def member_button(label, action):
                return button(label, f"u:{chat}:{uid}:{action}:{message_id}")

            return await self.tg.send(
                chat,
                tr("m_444e0f2563cf", p0=uid),
                [
                    [
                        member_button(tr("m_4f2f5bdb5ecb"), "warn"),
                        member_button(tr("m_9ec664cb2161"), "mute"),
                    ],
                    [
                        member_button(tr("m_7c29e9c23e38"), "unmute"),
                        member_button(tr("m_7c58bdadcb3a"), "delete"),
                    ],
                    [
                        member_button(tr("m_24417444e3d1"), "banconfirm"),
                        member_button(tr("m_304587745c01"), "unban"),
                    ],
                    [member_button(tr("m_a0d45a431f7e"), "spam"), member_button(tr("m_f9cfa75eb024"), "ham")],
                ],
            )
        if cmd in ("privacy", "terms", "paysupport"):
            messages = {
                "privacy": tr("m_6d9979f1c703", p0=self.config.retention_days),
                "terms": tr("m_4ebeeb3f233f") + escape(self.config.terms_url or tr("m_da75df8a9346")),
                "paysupport": tr("m_8b426c290bd4")
                + escape(
                    "@" + self.config.support_username
                    if self.config.support_username
                    else tr("m_1247ca0da4e7")
                ),
            }
            return await self.tg.send(chat, messages[cmd])
        if cmd == "forget":
            return await self.tg.send(
                chat,
                tr("m_5ea4b5388013"),
                [[button(tr("m_9ff8a9a664ed"), f"forget:{user}")]],
            )
        if cmd in ("shop", "subscriptions"):
            if not private:
                return await self.tg.send(
                    chat,
                    tr("m_a342f9fc6d81"),
                    [[{"text": tr("m_0db020946caa"), "url": f"https://t.me/{self.username}?start=shop"}]],
                )
            return await (self.store(user) if cmd == "shop" else self.subscriptions(user))
        if cmd == "ask":
            if private:
                raise ValueError(tr("m_c3c1d5a5671f"))
            conf = self.db.chat(chat)["settings"]
            if not conf["ai"]:
                raise ValueError(tr("m_d0e5ee03ac00"))
            if not args:
                raise ValueError(tr("m_613daa971b1c"))
            if not self.db.cooldown(chat, user, "ai", 15):
                return
            answer = await self.ai.answer(chat, user, args, conf["rules"])
            return await self.tg.send(chat, escape(answer))
        if private:
            if cmd == "refund":
                return await self.refund_prompt(user, args, user)
            raise ValueError(tr("m_9377cba058b9"))
        if cmd == "afk":
            self.db.execute(
                "INSERT OR REPLACE INTO afk VALUES(?,?,?,?)",
                (chat, user, (args or "Back soon!")[:300], int(time.time())),
            )
            return await self.tg.send(chat, tr("m_3d9f09cae223"))
        if cmd in ("aiquiz", "summary"):
            conf = self.db.chat(chat)["settings"]
            if not conf["ai"]:
                raise ValueError(tr("m_a2258cb33a63"))
            if cmd == "aiquiz":
                await self.require_admin(chat, user)
                if not conf["fun"] or not args:
                    raise ValueError(tr("m_b77d9dcc920a"))
                data = await self.ai.quiz(chat, user, args)
                token = secrets.token_hex(5)
                self.db.execute(
                    "INSERT INTO games VALUES(?,?,?,?,NULL)",
                    (token, chat, json.dumps({"answer": data["answer"]}), int(time.time()) + 300),
                )
                return await self.tg.send(
                    chat,
                    escape(data["question"]) + tr("m_51d3d173320e"),
                    [[button(option, f"q:{token}:{i}")] for i, option in enumerate(data["options"])],
                )
            if conf["ai_history"] == 0:
                raise ValueError(tr("m_d350daf483cf"))
            answer = await self.ai.answer(
                chat,
                user,
                "Please summarize the recent conversation and any useful next steps.",
                conf["rules"],
            )
            return await self.tg.send(chat, escape(answer))
        if cmd in ("approve", "unapprove", "resetwarn"):
            await self.require_admin(chat, user, "can_restrict_members")
            target = m.get("reply_to_message", {}).get("from", {}).get("id")
            if not target:
                raise ValueError(tr("m_d6202486d02d"))
            if cmd == "approve":
                self.db.execute("INSERT OR REPLACE INTO approved VALUES(?,?,?)", (chat, target, user))
            elif cmd == "unapprove":
                self.db.execute("DELETE FROM approved WHERE chat=? AND user=?", (chat, target))
            else:
                self.db.member(chat, target)
                self.db.execute("UPDATE members SET warns=0 WHERE chat=? AND user=?", (chat, target))
            self.db.audit(chat, target, m["message_id"], user, cmd, "Admin decision")
            return await self.tg.send(chat, tr("m_9ff3823ecc1e"))
        if cmd in ("toss", "decide", "8ball", "emote", "shout"):
            if not self.db.chat(chat)["settings"]["fun"]:
                raise ValueError(tr("m_150682b0ae9a"))
            if not self.db.cooldown(chat, user, "fun", 5):
                return
            if cmd == "shout":
                text = args or m.get("reply_to_message", {}).get("text", "")
                if not text:
                    raise ValueError(tr("m_ee3937339fcb"))
                return await self.tg.send(chat, "<pre>" + escape(ported_fun.shout(text)) + "</pre>")
            if cmd == "emote":
                return await self.tg.send(chat, escape(ported_fun.emoticon()))
            choices = {"toss": ported_fun.TOSS, "decide": ported_fun.DECIDE, "8ball": ported_fun.EIGHTBALL}
            return await self.tg.send(chat, secrets.choice(choices[cmd]))
        if cmd == "rules":
            return await self.tg.send(chat, escape(self.db.chat(chat)["settings"]["rules"]))
        if cmd == "notes":
            rows = self.db.all("SELECT name FROM notes WHERE chat=? ORDER BY name LIMIT 50", (chat,))
            return await self.tg.send(
                chat, tr("m_9cd2c9f9737d") + "\n".join(escape(r["name"]) for r in rows) + tr("m_9829fa339f0b")
            )
        if cmd == "get":
            row = self.db.one("SELECT body FROM notes WHERE chat=? AND name=?", (chat, args.strip()))
            return await self.tg.send(chat, escape(row["body"]) if row else tr("m_87e2239d1927"))
        if cmd in ("play", "profile", "daily", "top", "joke", "quiz", "dice"):
            return await self.fun(
                chat, user, "menu" if cmd == "play" else cmd, chat, m["from"].get("first_name", "")
            )
        if cmd == "report":
            if not self.db.cooldown(chat, user, "report", 60):
                return
            target = m.get("reply_to_message")
            if not target or not target.get("from"):
                raise ValueError(tr("m_4571cd9b5246"))
            aid = self.db.audit(
                chat,
                target["from"]["id"],
                target["message_id"],
                user,
                "report",
                tr("m_0105a4231bb4"),
                target.get("text", target.get("caption", "")),
            )
            return await self.log_action(
                chat,
                tr("m_187282e286cf") + escape(target.get("text", target.get("caption", ""))[:500]),
                [
                    [
                        button(tr("m_4e2b1fba2883"), f"v:{aid}:ham"),
                        button(tr("m_22dd2af221b0"), f"v:{aid}:spam"),
                    ]
                ],
            )
        if cmd == "stats":
            await self.require_admin(chat, user)
            return await self.send_stats(chat, chat, args or "day")
        if cmd == "refund":
            return await self.refund_prompt(user, args, chat)
        rights = {
            "delete": "can_delete_messages",
            "pin": "can_pin_messages",
            "spam": "can_delete_messages",
            "ham": "can_delete_messages",
            "warn": "can_restrict_members",
            "ban": "can_restrict_members",
            "unban": "can_restrict_members",
            "mute": "can_restrict_members",
            "unmute": "can_restrict_members",
        }
        if cmd in rights:
            await self.require_admin(chat, user, rights[cmd])
            target = m.get("reply_to_message")
            if target and target.get("from") and not target.get("sender_chat"):
                target_user = target["from"]["id"]
            elif cmd in ("unban", "unmute") and args:
                target_user = int(args.split()[0])
            else:
                raise ValueError(tr("m_be534e3173aa"))
            if cmd in ("spam", "ham"):
                self.db.train(chat, target.get("text", target.get("caption", "")), cmd, user, target_user)
                self.engine.train(chat, target.get("text", target.get("caption", "")), cmd)
                return await self.tg.send(
                    chat,
                    tr("m_f7a04ee84454"),
                )
            await self.protect_target(chat, target_user)
            existing = self.db.one(
                "SELECT * FROM audit WHERE chat=? AND mid=? AND actor=? AND action=?",
                (chat, m["message_id"], user, cmd),
            )
            if existing and existing["status"] == "done":
                return
            aid = (
                existing["id"]
                if existing
                else self.db.audit(
                    chat, target_user, m["message_id"], user, cmd, tr("m_3cf8b320f124"), status="pending"
                )
            )
            if cmd == "delete":
                try:
                    await self.tg.call("deleteMessage", chat_id=chat, message_id=target["message_id"])
                except APIError as exc:
                    if "message to delete not found" not in exc.description.lower():
                        raise
                self.db.bump(chat, "deleted")
            elif cmd == "pin":
                await self.tg.call(
                    "pinChatMessage", chat_id=chat, message_id=target["message_id"], disable_notification=True
                )
            elif cmd in ("ban", "unban"):
                if cmd == "ban":
                    self.db.execute(
                        "DELETE FROM federation_enforced WHERE chat=? AND user=?", (chat, target_user)
                    )
                    self.db.execute(
                        "UPDATE subscriptions SET expired_ban=2 WHERE chat=? AND user=? AND expired_ban=1",
                        (chat, target_user),
                    )
                await self.tg.call(
                    "banChatMember" if cmd == "ban" else "unbanChatMember",
                    chat_id=chat,
                    user_id=target_user,
                    **({"only_if_banned": True} if cmd == "unban" else {}),
                )
                if cmd == "ban":
                    self.db.bump(chat, "bans")
            elif cmd == "unmute":
                await self.release(chat, target_user)
                self.db.member(chat, target_user)
                self.db.execute("UPDATE members SET warns=0 WHERE chat=? AND user=?", (chat, target_user))
            elif cmd == "mute":
                minutes = int(args or "10")
                if not 1 <= minutes <= 525600:
                    raise ValueError(tr("m_896daa4172d1"))
                await self.tg.call(
                    "restrictChatMember",
                    chat_id=chat,
                    user_id=target_user,
                    permissions={"can_send_messages": False},
                    use_independent_chat_permissions=True,
                    until_date=int(time.time()) + minutes * 60,
                )
                self.db.bump(chat, "mutes")
            elif cmd == "warn":
                self.db.member(chat, target_user)
                if not existing or existing["status"] == "pending":
                    with self.db.transaction():
                        self.db.execute(
                            "UPDATE members SET warns=warns+1 WHERE chat=? AND user=?", (chat, target_user)
                        )
                        self.db.bump(chat, "warns")
                        self.db.execute("UPDATE audit SET status='counted' WHERE id=?", (aid,))
                conf = self.db.chat(chat)["settings"]
                if self.db.member(chat, target_user)["warns"] >= conf["warn_limit"]:
                    await self.tg.call(
                        "restrictChatMember",
                        chat_id=chat,
                        user_id=target_user,
                        permissions={"can_send_messages": False},
                        use_independent_chat_permissions=True,
                        until_date=int(time.time()) + conf["mute_minutes"] * 60,
                    )
                    self.db.execute("UPDATE members SET warns=0 WHERE chat=? AND user=?", (chat, target_user))
                    self.db.bump(chat, "mutes")
            self.db.execute("UPDATE audit SET status='done' WHERE id=?", (aid,))
            return await self.tg.send(chat, tr("m_1d1d60dda9ee"))

    async def my_chats(self, user):
        rows = []
        for chat in self.db.all("SELECT id,title FROM chats ORDER BY title LIMIT 100"):
            try:
                if await self.admin(chat["id"], user):
                    rows.append([button(chat["title"][:40], f"a:{chat['id']}:home")])
            except APIError:
                continue
            if len(rows) >= 20:
                break
        await self.tg.send(
            user,
            tr("m_827883caceca"),
            rows,
        )

    async def fun(self, chat, user, action, destination, name=""):
        await self.require_member(chat, user)
        conf = self.db.chat(chat)["settings"]
        if not conf["fun"]:
            raise ValueError(tr("m_4deaaf37caac"))
        self.db.member(chat, user, name)
        if action not in ("menu", "profile", "rules", "top", "shop") and not self.db.cooldown(
            chat, user, "fun", 5
        ):
            raise ValueError(tr("m_bc89c41068bf"))
        if action == "menu":
            return await self.tg.send(destination, tr("m_55bb218032dd"), fun_keyboard(chat))
        if action == "quiz":
            if not self.db.cooldown(chat, 0, "quiz", 60):
                raise ValueError(tr("m_d67459411e3b"))
            question, keyboard = games.quiz(self.db, chat)
            return await self.tg.send(
                chat,
                "🧩 " + question + tr("m_c5d494cc2cc2"),
                keyboard,
            )
        if action == "dice":
            self.db.bump(chat, "games")
            return await self.tg.call("sendDice", chat_id=destination, emoji="🎲")
        if action == "joke":
            return await self.tg.send(destination, secrets.choice(games.JOKES))
        if action == "daily":
            return await self.tg.send(destination, games.daily(self.db, chat, user, conf["timezone"]))
        if action == "top":
            rows = self.db.all(
                "SELECT name,xp,badge FROM members WHERE chat=? ORDER BY xp DESC LIMIT 10", (chat,)
            )
            return await self.tg.send(
                destination,
                tr("m_6208fb4744d5")
                + "\n".join(
                    f"{i}. {escape(r['name'])} {escape(r['badge'])} — {r['xp']}"
                    for i, r in enumerate(rows, 1)
                ),
            )
        if action == "profile":
            p = self.db.member(chat, user)
            return await self.tg.send(
                destination,
                tr(
                    "m_0ca598f41624",
                    p0=escape(p["name"]),
                    p1=escape(p["badge"]),
                    p2=p["xp"] // 100 + 1,
                    p3=p["xp"],
                    p4=p["coins"],
                    p5=p["warns"],
                ),
            )
        if action == "rules":
            return await self.tg.send(destination, escape(conf["rules"]))
        if action == "invite":
            if not self.db.cooldown(chat, user, "invite", 60):
                raise ValueError(tr("m_564aa5b79432"))
            return await self.growth.invite(chat, user)
        if action in ("truth", "dare", "fortune"):
            items = {"truth": TRUTHS, "dare": DARES, "fortune": FORTUNES}[action]
            prefix = tr("m_426c87f0f36b") if action == "fortune" else "🎭 "
            return await self.tg.send(destination, prefix + secrets.choice(items))
        if action == "referrals":
            rows = self.db.all(
                "SELECT r.inviter,count(*) n,coalesce(m.name,cast(r.inviter as TEXT)) name FROM referrals r LEFT JOIN members m ON r.chat=m.chat AND r.inviter=m.user WHERE r.chat=? GROUP BY r.inviter ORDER BY n DESC LIMIT 10",
                (chat,),
            )
            return await self.tg.send(
                destination,
                tr("m_3e4c32bab592")
                + "\n".join(f"{i}. {escape(r['name'])}: {r['n']}" for i, r in enumerate(rows, 1)),
            )
        if action == "like":
            if self.db.cooldown(chat, user, "like", 86400):
                self.db.bump(chat, "likes")
            return await self.tg.send(destination, tr("m_91cc105c12d5"))
        if action == "shop":
            return await self.tg.send(
                destination,
                tr("m_ee7e4aca367f"),
                [
                    [
                        button(tr("m_61d4f99aaaff"), f"f:{chat}:badge:100"),
                        button(tr("m_4b545cb3ffa6"), f"f:{chat}:badge:500"),
                    ]
                ],
            )
        if action.startswith("badge:"):
            price = int(action.split(":")[1])
            if price not in (100, 500):
                raise ValueError(tr("m_34990984aad1"))
            badge = "🌱" if price == 100 else "🌟"
            changed = self.db.execute(
                "UPDATE members SET coins=coins-?,badge=? WHERE chat=? AND user=? AND coins>=? AND badge<>?",
                (price, badge, chat, user, price, badge),
            ).rowcount
            return await self.tg.send(destination, tr("m_68a670d6df4d") if changed else tr("m_046a2a2de404"))
        if action == "rps":
            token = secrets.token_hex(5)
            self.db.execute(
                "INSERT INTO games VALUES(?,?,?,?,NULL)",
                (
                    token,
                    chat,
                    json.dumps({"kind": "rps", "user": user, "bot": secrets.randbelow(3)}),
                    int(time.time()) + 120,
                ),
            )
            return await self.tg.send(
                destination,
                tr("m_5c874d8e31b5"),
                [
                    [
                        button(x, f"r:{token}:{i}")
                        for i, x in enumerate(
                            (tr("m_c9c95e69e1ed"), tr("m_0ed2e56e379b"), tr("m_2def9be73498"))
                        )
                    ]
                ],
            )

    async def callback(self, q):
        user = q["from"]["id"]
        m = q.get("message")
        if not m or "chat" not in m:
            return await self.tg.call(
                "answerCallbackQuery", callback_query_id=q["id"], text=tr("m_e47cb396f755")
            )
        destination, mid = m["chat"]["id"], m["message_id"]
        parts = q.get("data", "").split(":")
        route = parts[0]
        if route == "l":
            await self.change_language(int(parts[1]), user, parts[2], destination)
            return await self.tg.call("answerCallbackQuery", callback_query_id=q["id"])
        if route == "fed":
            await self.community.decide(parts[2], user, int(parts[3]), parts[1] == "yes")
            return await self.tg.call(
                "answerCallbackQuery",
                callback_query_id=q["id"],
                text=tr("m_641586f8b33c"),
            )
        if route == "g":
            text = await self.growth.enter(parts[1], user)
            return await self.tg.call("answerCallbackQuery", callback_query_id=q["id"], text=text)
        await self.tg.call("answerCallbackQuery", callback_query_id=q["id"])
        if route == "a":
            chat, action = int(parts[1]), parts[2]
            await self.require_admin(chat, user)
            conf = self.db.chat(chat)["settings"]
            if action == "language":
                return await self.choose_language(chat, destination)
            if action in SECTIONS:
                return await self.panel(chat, user, destination, action, mid)
            if action == "toggle" and parts[3] in BOOL_FIELDS:
                key = parts[3]
                self.db.setting(chat, key, not conf[key])
                self.db.audit(chat, 0, 0, user, "setting", f"{key}={not conf[key]}")
                section = (
                    "learn"
                    if key in ("ai", "ai_moderation", "learning", "learned_enforce")
                    else "stats"
                    if key == "reports"
                    else "settings"
                    if key in ("welcome", "fun")
                    else "mod"
                )
                return await self.panel(chat, user, destination, section, mid)
            if action == "cycle":
                key = parts[3]
                if key == "action":
                    options = ["delete", "warn", "mute"]
                    self.db.setting(chat, key, options[(options.index(conf[key]) + 1) % 3])
                    return await self.panel(chat, user, destination, "mod", mid)
                if key == "week_start":
                    self.db.setting(chat, key, (conf[key] + 1) % 7)
                    return await self.panel(chat, user, destination, "settings", mid)
            if action == "stat":
                return await self.send_stats(chat, destination, parts[3])
            if action == "csv":
                await self.tg.document(
                    user, f"tuxigap-{parts[3]}.csv", stats.csv_report(self.db, chat, parts[3])
                )
                return
            if action == "diagnose":
                bot_member = await self.tg.call("getChatMember", chat_id=chat, user_id=self.bot_id)
                count = await self.tg.call("getChatMemberCount", chat_id=chat)
                required = [
                    "can_delete_messages",
                    "can_restrict_members",
                    "can_invite_users",
                    "can_pin_messages",
                ]
                lines = [tr("m_f45f3a9bab68", p0=count), tr("m_ca39658cdcc0", p0=bot_member["status"])]
                lines += [f"{key}: {'✅' if bot_member.get(key) else '❌'}" for key in required]
                lines += [
                    f"AI: {'✅' if self.config.ai_key and self.config.ai_model else '❌ کلید یا مدل تنظیم نشده'}",
                    tr("m_97eb655b1d37"),
                ]
                return await self.tg.send(destination, "\n".join(lines))
            if action == "input" and parts[3] in INPUTS:
                return await self.prompt(user, chat, parts[3])
            if action == "samples":
                rows = self.db.all(
                    "SELECT label,count(*) n FROM samples WHERE chat=? GROUP BY label", (chat,)
                )
                return await self.tg.send(
                    destination,
                    tr("m_357a9fef0bdb")
                    + "\n".join(f"{r['label']}: {r['n']}" for r in rows)
                    + tr("m_ddf061c5e9ab"),
                )
            if action == "review":
                rows = self.db.all(
                    "SELECT * FROM audit WHERE chat=? AND action IN ('moderation','report') AND text<>'' ORDER BY id DESC LIMIT 5",
                    (chat,),
                )
                for r in rows:
                    await self.tg.send(
                        user,
                        escape(r["text"][:900]),
                        [
                            [
                                button(tr("m_4e2b1fba2883"), f"v:{r['id']}:ham"),
                                button(tr("m_aeebe6941be1"), f"v:{r['id']}:spam"),
                            ]
                        ],
                    )
                if not rows:
                    await self.tg.send(destination, tr("m_8c8bcc038df9"))
                return
            if action == "resetconfirm":
                return await self.tg.send(
                    destination,
                    tr("m_e474819b7a22"),
                    [[button(tr("m_9b452dd21ea2"), f"a:{chat}:reset")]],
                )
            if action == "reset":
                self.db.execute("DELETE FROM samples WHERE chat=?", (chat,))
                return await self.tg.send(destination, tr("m_9bd04098f6e4"))
            if action == "gateconfirm":
                return await self.tg.send(
                    destination,
                    tr("m_2ef5d4c63806"),
                    [
                        [
                            button(tr("m_3034a52a658e"), f"a:{chat}:gateon"),
                            button(tr("m_70874456b266"), f"a:{chat}:gateoff"),
                        ]
                    ],
                )
            if action in ("gateon", "gateoff"):
                await self.require_admin(chat, user, "can_restrict_members")
                if action == "gateon":
                    info = await self.tg.call("getChat", chat_id=chat)
                    if info.get("username"):
                        raise ValueError(tr("m_099da36f48e1"))
                    if not self.config.support_username or not self.config.terms_url:
                        raise ValueError(tr("m_9a905edf7b45"))
                self.db.setting(chat, "paid_gate", action == "gateon")
                return await self.panel(chat, user, destination, "plans", mid)
            if action == "planlist":
                rows = self.db.all("SELECT * FROM plans WHERE chat=? ORDER BY id DESC LIMIT 20", (chat,))
                keyboard = [
                    [
                        button(
                            f"{'✅' if p['enabled'] else '❌'} {p['name']} | {p['stars']}⭐",
                            f"a:{chat}:plan:{p['id']}",
                        )
                    ]
                    for p in rows
                ]
                return await self.tg.send(
                    destination,
                    tr("m_ab6dcfa27b62") + tr("m_23409013329d", p0=self.username, p1=chat),
                    keyboard,
                )
            if action == "plan":
                self.db.execute(
                    "UPDATE plans SET enabled=1-enabled WHERE id=? AND chat=?", (int(parts[3]), chat)
                )
                return await self.tg.send(destination, tr("m_a5d9d179e6e7"))
            if action == "revenue":
                return await self.send_stats(chat, user, "month")
            if action == "jobs":
                rows = self.db.all(
                    "SELECT * FROM jobs WHERE chat=? AND state='pending' ORDER BY due LIMIT 20", (chat,)
                )
                return await self.tg.send(
                    destination,
                    tr("m_6201eb07ed4f"),
                    [
                        [
                            button(
                                f"{datetime.fromtimestamp(j['due'], ZoneInfo(conf['timezone'])):%m-%d %H:%M} | {j['text'][:25]}",
                                f"a:{chat}:canceljob:{j['id']}",
                            )
                        ]
                        for j in rows
                    ],
                )
            if action == "canceljob":
                self.db.execute(
                    "UPDATE jobs SET state='cancelled' WHERE id=? AND chat=? AND state='pending'",
                    (int(parts[3]), chat),
                )
                return await self.tg.send(destination, tr("m_144cd1b4f253"))
            if action in ("lock", "unlock"):
                await self.require_admin(chat, user, "can_restrict_members")
                if self.db.chat(chat)["kind"] not in ("group", "supergroup"):
                    raise ValueError(tr("m_2380215b349c"))
                if action == "lock":
                    info = await self.tg.call("getChat", chat_id=chat)
                    if not self.db.get(f"lock:{chat}"):
                        self.db.set(f"lock:{chat}", info["permissions"])
                    permissions = {k: False for k in info["permissions"]}
                else:
                    permissions = self.db.get(f"lock:{chat}")
                    if not permissions:
                        raise ValueError(tr("m_fd73a1f12108"))
                await self.tg.call(
                    "setChatPermissions",
                    chat_id=chat,
                    permissions=permissions,
                    use_independent_chat_permissions=True,
                )
                if action == "unlock":
                    self.db.set(f"lock:{chat}", None)
                self.db.audit(chat, 0, 0, user, action, tr("m_d24eaf2bee92"))
                return await self.tg.send(destination, tr("m_fe37e18aba3a"))
        elif route == "u":
            chat, target, action, target_mid = int(parts[1]), int(parts[2]), parts[3], int(parts[4])
            await self.require_admin(chat, user)
            if action == "banconfirm":
                return await self.tg.send(
                    destination,
                    tr("m_ea76fa031db2", p0=target),
                    [[button(tr("m_7cc00a08e908"), f"u:{chat}:{target}:ban:{target_mid}")]],
                )
            if action not in {"warn", "mute", "unmute", "ban", "unban", "delete", "spam", "ham"}:
                raise ValueError(tr("m_49fd80e90354"))
            cached = self.db.one(
                "SELECT * FROM messages WHERE chat=? AND mid=? AND user=?", (chat, target_mid, target)
            )
            if action in {"delete", "spam", "ham"} and not cached:
                raise ValueError(tr("m_dd7a55591eb5"))
            synthetic = {
                "message_id": -mid,
                "chat": {"id": chat, "type": "supergroup"},
                "from": {"id": user},
                "reply_to_message": {
                    "message_id": target_mid,
                    "from": {"id": target},
                    "text": cached["text"] if cached else "",
                },
            }
            return await self.command(action, "10" if action == "mute" else "", synthetic)
        elif route == "f":
            return await self.fun(
                int(parts[1]), user, ":".join(parts[2:]), destination, q["from"].get("first_name", "")
            )
        elif route == "q":
            game = self.db.one("SELECT * FROM games WHERE token=?", (parts[1],))
            if not game:
                raise ValueError(tr("m_f361ff6989f6"))
            await self.require_member(game["chat"], user)
            if not self.db.chat(game["chat"])["settings"]["fun"]:
                raise ValueError(tr("m_400ca77e7f0f"))
            _, text = games.answer_quiz(self.db, parts[1], user, parts[2])
            return await self.tg.send(destination, text)
        elif route == "r":
            game = self.db.one("SELECT * FROM games WHERE token=?", (parts[1],))
            if not game or game["expires"] < time.time() or game["winner"] is not None:
                raise ValueError(tr("m_1aa853e90844"))
            data = json.loads(game["data"])
            if data["user"] != user:
                raise ValueError(tr("m_adb5914ae965"))
            await self.require_member(game["chat"], user)
            if not self.db.chat(game["chat"])["settings"]["fun"]:
                raise ValueError(tr("m_400ca77e7f0f"))
            choice = int(parts[2])
            if choice not in range(3):
                raise ValueError(tr("m_2b7a88308de0"))
            result = (choice - data["bot"]) % 3
            self.db.execute("UPDATE games SET winner=? WHERE token=?", (user, parts[1]))
            self.db.bump(game["chat"], "games")
            return await self.tg.send(
                destination,
                tr("m_b3df839b5557", p0=("سنگ", "کاغذ", "قیچی")[data["bot"]])
                + (
                    tr("m_d9e155ed036f")
                    if result == 0
                    else tr("m_b8e45fc85b97")
                    if result == 1
                    else tr("m_f4ac62ed1294")
                ),
            )
        elif route == "v":
            return await self.feedback(int(parts[1]), parts[2], user, destination)
        elif route == "c":
            return await self.solve_captcha(int(parts[1]), int(parts[2]), parts[3], user, destination)
        elif route == "buy":
            if destination != user:
                raise ValueError(tr("m_976fa878ab93"))
            p = self.db.one("SELECT * FROM plans WHERE id=?", (int(parts[1]),))
            if not p:
                raise ValueError(tr("m_e24bfc589823"))
            # Require a second explicit click after terms; no charge on the first click.
            return await self.tg.send(
                user,
                tr("m_e4f38679da24", p0=escape(p["name"]), p1=p["stars"], p2=p["days"])
                + (tr("m_0b768a7f8930") if p["recurring"] else tr("m_3e77993f41b2"))
                + tr("m_4e972589c0a4")
                + escape(self.config.terms_url),
                [[button(tr("m_66ba2ed6253c"), f"pay:{p['id']}")]],
            )
        elif route == "pay":
            if destination != user:
                raise ValueError(tr("m_3a3dc378c71b"))
            return await self.billing.invoice(user, int(parts[1]))
        elif route == "access":
            if destination != user:
                raise ValueError(tr("m_a6dbbea5d391"))
            return await self.billing.access_link(int(parts[1]), user)
        elif route == "cancelrec":
            p = self.db.one("SELECT * FROM payments WHERE rowid=? AND user=?", (int(parts[1]), user))
            if not p:
                raise ValueError(tr("m_d95c56069940"))
            inv = self.db.one("SELECT * FROM invoices WHERE payload=?", (p["payload"],))
            if not inv["recurring"]:
                raise ValueError(tr("m_985affe4df85"))
            if not inv["cancelled"]:
                await self.tg.call(
                    "editUserStarSubscription",
                    user_id=user,
                    telegram_payment_charge_id=p["charge"],
                    is_canceled=True,
                )
                self.db.execute("UPDATE invoices SET cancelled=1 WHERE payload=?", (p["payload"],))
            return await self.tg.send(user, tr("m_e2ae258a70c2"))
        elif route == "refund":
            p = self.db.one("SELECT * FROM payments WHERE rowid=?", (int(parts[1]),))
            if not p:
                raise ValueError(tr("m_1fcbd3898d58"))
            await self.require_admin(p["chat"], user, "can_restrict_members")
            await self.billing.refund(p["charge"])
            return await self.tg.send(destination, tr("m_ea3ad3b8f7a8"))
        elif route == "forget" and int(parts[1]) == user:
            with self.db.transaction():
                self.db.execute("DELETE FROM members WHERE user=?", (user,))
                self.db.execute("UPDATE messages SET text='' WHERE user=?", (user,))
                self.db.execute("UPDATE audit SET text='' WHERE user=?", (user,))
                self.db.execute("DELETE FROM activity WHERE user=?", (user,))
                self.db.execute("DELETE FROM samples WHERE subject=?", (user,))
                self.db.execute(
                    "DELETE FROM inbox WHERE done=1 AND json_extract(payload,'$.message.from.id')=? AND json_type(payload,'$.message.successful_payment') IS NULL AND json_type(payload,'$.message.refunded_payment') IS NULL",
                    (user,),
                )
            return await self.tg.send(
                destination,
                tr("m_d003f1f976e5"),
            )

    async def prompt(self, user, chat, field):
        prompts = {
            "locks": tr("m_c919d2d2cd65") + " ".join(LOCK_TYPES),
            "allowlist": tr("m_5c0665d6fcc2"),
            "night": tr("m_7945d3a98e67"),
            "limits": tr("m_7baaf2c3a158"),
            "ai_history": tr("m_c1a8ea402844"),
            "giveaway": tr("m_385a51e12d55"),
            "poll": tr("m_806c9cb95be9"),
            "note": tr("m_7b75ca7af142"),
            "filter": tr("m_1b7536531805"),
            "log_chat": tr("m_7205bf2af047"),
            "words": tr("m_f6686edf694c"),
            "flood": tr("m_5963bdb4ccf3"),
            "warn_limit": tr("m_d10ff15ddf2f"),
            "mute_minutes": tr("m_f9c280f5f193"),
            "timezone": tr("m_7a22e8a2a653"),
            "report_hour": tr("m_6f9c113eaa3e"),
            "welcome_text": tr("m_ae1bb8d4f985"),
            "rules": tr("m_8053e8856b38"),
            "schedule": tr("m_cd4848e0165d"),
            "plan": tr("m_b156188a3721"),
        }
        await self.tg.send(user, prompts[field] + tr("m_a8648f782256"))
        self.db.execute(
            "INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)", (user, chat, field, int(time.time()) + 600)
        )

    async def save_input(self, user, chat, field, text):
        await self.require_admin(chat, user)
        if field not in INPUTS:
            raise ValueError(tr("m_1955e5c06835"))
        if field == "locks":
            values = [] if text.strip() == "-" else text.lower().split()
            if any(v not in LOCK_TYPES for v in values):
                raise ValueError(tr("m_5fd75c424231"))
            self.db.setting(chat, field, sorted(set(values)))
        elif field == "allowlist":
            values = (
                [] if text.strip() == "-" else [v.strip().lower() for v in text.splitlines() if v.strip()]
            )
            if len(values) > 100 or any(len(v) > 120 for v in values):
                raise ValueError(tr("m_7f55b5d285bf"))
            self.db.setting(chat, field, values)
        elif field in ("night", "limits"):
            left, right = map(int, text.split())
            if field == "night":
                if not 0 <= left <= 23 or not 0 <= right <= 23 or left == right:
                    raise ValueError(tr("m_21d5c74fe635"))
                self.db.setting(chat, "night_start", left)
                self.db.setting(chat, "night_end", right)
            else:
                if not -1 <= left <= 100 or not -1 <= right <= 100:
                    raise ValueError(tr("m_4ca9d9049150"))
                self.db.setting(chat, "links_limit", left)
                self.db.setting(chat, "mentions_limit", right)
        elif field == "ai_history":
            value = int(text)
            if not 0 <= value <= 20:
                raise ValueError(tr("m_270b56201029"))
            self.db.setting(chat, field, value)
        elif field == "giveaway":
            title, minutes = text.split("|", 1)
            await self.growth.giveaway(chat, title.strip(), int(minutes.strip()), user)
        elif field == "poll":
            pieces = [piece.strip() for piece in text.split("|")]
            if (
                not 3 <= len(pieces) <= 11
                or not 1 <= len(pieces[0]) <= 300
                or any(not 1 <= len(x) <= 100 for x in pieces[1:])
            ):
                raise ValueError(tr("m_46972eb9ae74"))
            await self.tg.call(
                "sendPoll",
                chat_id=chat,
                question=pieces[0],
                options=[{"text": x} for x in pieces[1:]],
                is_anonymous=False,
            )
        elif field in ("note", "filter"):
            from .moderation import normalize

            name, body = [part.strip() for part in text.split("|", 1)]
            if not 1 <= len(name) <= 80 or not 1 <= len(body) <= 2000:
                raise ValueError(tr("m_27ace98f9731"))
            if field == "filter":
                name = normalize(name)
                if body == "-":
                    self.db.execute("DELETE FROM filters WHERE chat=? AND trigger=?", (chat, name))
                else:
                    self.db.execute("INSERT OR REPLACE INTO filters VALUES(?,?,?)", (chat, name, body))
            elif body == "-":
                self.db.execute("DELETE FROM notes WHERE chat=? AND name=?", (chat, name))
            else:
                self.db.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?)", (chat, name, body))
        elif field == "log_chat":
            destination = int(text.strip())
            if destination:
                info = await self.tg.call("getChat", chat_id=destination)
                if info["type"] == "private":
                    raise ValueError(tr("m_6a913ff9628a"))
                await self.require_admin(destination, user)
                if not await self.admin(destination, self.bot_id):
                    raise ValueError(tr("m_04cb9d2adfcc"))
            self.db.setting(chat, field, destination)
        elif field == "words":
            value = [] if text.strip() == "-" else [w.strip() for w in text.splitlines() if w.strip()]
            if len(value) > 200 or any(len(w) > 100 for w in value):
                raise ValueError(tr("m_7ac11a398745"))
            self.db.setting(chat, field, value)
        elif field == "flood":
            count, seconds = map(int, text.split())
            if not 2 <= count <= 100 or not 2 <= seconds <= 120:
                raise ValueError(tr("m_d1f2bea23745"))
            self.db.setting(chat, "flood_count", count)
            self.db.setting(chat, "flood_seconds", seconds)
        elif field in ("warn_limit", "mute_minutes", "report_hour"):
            value = int(text)
            low, high = {"warn_limit": (1, 20), "mute_minutes": (1, 1440), "report_hour": (0, 23)}[field]
            if not low <= value <= high:
                raise ValueError(tr("m_64214f91e60e", p0=low, p1=high))
            self.db.setting(chat, field, value)
        elif field == "timezone":
            ZoneInfo(text.strip())
            self.db.setting(chat, field, text.strip())
        elif field in ("rules", "welcome_text"):
            if not 1 <= len(text) <= 2000:
                raise ValueError(tr("m_45713251090c"))
            self.db.setting(chat, field, text)
        elif field == "schedule":
            date, body = text.split("|", 1)
            due = datetime.strptime(date.strip(), "%Y-%m-%d %H:%M").replace(
                tzinfo=ZoneInfo(self.db.chat(chat)["settings"]["timezone"])
            )
            if (
                not time.time() + 30 <= due.timestamp() <= time.time() + 366 * 86400
                or not body.strip()
                or len(body) > 3500
            ):
                raise ValueError(tr("m_f836e33080e4"))
            self.db.execute(
                "INSERT INTO jobs(chat,creator,due,text) VALUES(?,?,?,?)",
                (chat, user, int(due.timestamp()), body.strip()),
            )
        elif field == "plan":
            name, stars_text, days_text, recurring_text = [p.strip() for p in text.split("|")]
            stars, days, recurring = int(stars_text), int(days_text), int(recurring_text)
            if (
                not name
                or len(name) > 32
                or not 1 <= stars <= 10000
                or not 1 <= days <= 365
                or recurring not in (0, 1)
                or (recurring and days != 30)
            ):
                raise ValueError(tr("m_95ddb333865e"))
            self.db.execute(
                "INSERT INTO plans(chat,name,stars,days,recurring) VALUES(?,?,?,?,?)",
                (chat, name, stars, days, recurring),
            )
        self.db.execute("DELETE FROM sessions WHERE user=?", (user,))
        self.db.audit(chat, 0, 0, user, "setting", field)
        await self.tg.send(user, tr("m_85d69c1d1145"))
        await self.panel(chat, user, user)

    async def store(self, user, chat=None):
        query = "SELECT p.*,c.title FROM plans p JOIN chats c ON c.id=p.chat WHERE p.enabled=1"
        rows = self.db.all(
            query + (" AND p.chat=?" if chat is not None else "") + " ORDER BY p.id DESC LIMIT 30",
            (chat,) if chat is not None else (),
        )
        rows = [p for p in rows if self.db.chat(p["chat"])["settings"]["paid_gate"]]
        keyboard = [
            [button(f"{p['title'][:20]} | {p['name']} | {p['stars']}⭐", f"buy:{p['id']}")] for p in rows
        ]
        return await self.tg.send(
            user,
            tr("m_f772f570dcce") if rows else tr("m_76e3303c7ba7"),
            keyboard,
        )

    async def subscriptions(self, user):
        subs = self.db.all(
            "SELECT s.*,c.title FROM subscriptions s JOIN chats c ON c.id=s.chat WHERE user=?", (user,)
        )
        keyboard = [
            [
                button(
                    s["title"][:30] + (" ✅" if s["expires"] > time.time() else tr("m_e7e5babad86d")),
                    f"access:{s['chat']}",
                )
            ]
            for s in subs
        ]
        for p in self.db.all(
            "SELECT min(payments.rowid) rid,payments.chat FROM payments JOIN invoices ON payments.payload=invoices.payload WHERE payments.user=? AND invoices.recurring=1 AND invoices.cancelled=0 AND payments.refunded=0 GROUP BY payments.payload ORDER BY max(payments.paid_at) DESC LIMIT 20",
            (user,),
        ):
            keyboard.append([button(tr("m_76ddcdaeb0ee", p0=p["chat"]), f"cancelrec:{p['rid']}")])
        await self.tg.send(
            user,
            tr("m_5607854f6a6b"),
            keyboard,
        )

    async def refund_prompt(self, user, charge, destination):
        p = self.db.one("SELECT rowid rid,* FROM payments WHERE charge=?", (charge,))
        if not p:
            raise ValueError(tr("m_1fcbd3898d58"))
        await self.require_admin(p["chat"], user, "can_restrict_members")
        await self.tg.send(
            destination,
            tr("m_81d67828a515", p0=p["stars"], p1=p["user"]),
            [[button(tr("m_fbe3fd6ee9f5"), f"refund:{p['rid']}")]],
        )

    async def membership(self, event):
        chat, target = event["chat"]["id"], event["new_chat_member"]["user"]
        self.db.register(event["chat"])
        before, after = present(event["old_chat_member"]), present(event["new_chat_member"])
        if before == after:
            return
        user = target["id"]
        if event["new_chat_member"]["status"] == "kicked" and event.get("from", {}).get("id") != self.bot_id:
            self.db.execute("DELETE FROM federation_enforced WHERE chat=? AND user=?", (chat, user))
            self.db.execute(
                "UPDATE subscriptions SET expired_ban=2 WHERE chat=? AND user=? AND expired_ban=1",
                (chat, user),
            )
        self.db.member(chat, user, target.get("first_name", ""))
        self.db.bump(chat, "joins" if after else "leaves", ts=event.get("date"))
        if not after:
            self.db.execute("DELETE FROM captcha WHERE chat=? AND user=?", (chat, user))
            return
        conf = self.db.chat(chat)["settings"]
        if not conf["enabled"] or user == self.bot_id or await self.admin(chat, user):
            return
        for ban in self.db.all(
            "SELECT b.* FROM federation_bans b JOIN federation_chats c ON b.fid=c.fid WHERE c.chat=? AND c.state='active' AND b.user=? AND b.active=1",
            (chat, user),
        ):
            self.db.execute(
                "INSERT INTO federation_jobs(fid,chat,user,action,version,due) VALUES(?,?,?,'ban',?,?)",
                (ban["fid"], chat, user, ban["version"], int(time.time())),
            )
            await self.community.enforce_federations(int(time.time()))
            return
        if conf["paid_gate"] and not self.billing.active(chat, user):
            await self.billing.gate_ban(chat, user)
            self.db.bump(chat, "bans")
            return
        if conf["bots"] and target.get("is_bot") and not conf["dry_run"]:
            await self.tg.call("banChatMember", chat_id=chat, user_id=user)
            self.db.bump(chat, "bans")
            return
        raid = self.community.raid(chat, user)
        if (conf["captcha"] or raid) and not conf["dry_run"] and event["chat"]["type"] == "supergroup":
            self.db.set(f"ref_pending:{chat}:{user}", event.get("invite_link", {}).get("invite_link", ""))
            a, b = secrets.randbelow(8) + 1, secrets.randbelow(8) + 1
            answer = a + b
            await self.tg.call(
                "restrictChatMember",
                chat_id=chat,
                user_id=user,
                permissions={"can_send_messages": False},
                use_independent_chat_permissions=True,
            )
            self.db.execute(
                "INSERT OR REPLACE INTO captcha VALUES(?,?,?,?)",
                (chat, user, str(answer), int(time.time()) + 180),
            )
            choices = list({answer, answer + 1, answer + 2})
            secrets.SystemRandom().shuffle(choices)
            return await self.tg.send(
                chat,
                tr("m_1df21f3e8d86", p0=escape(target.get("first_name", "عضو جدید")), p1=a, p2=b),
                [[button(str(x), f"c:{chat}:{user}:{x}") for x in choices]],
            )
        self.growth.record_join(
            chat, user, event.get("invite_link", {}).get("invite_link", ""), not target.get("is_bot", False)
        )
        if conf["welcome"] and event["chat"]["type"] in ("group", "supergroup"):
            await self.tg.send(
                chat,
                escape(
                    str(conf["welcome_text"]).replace(
                        "{name}", target.get("first_name", tr("m_030f1b33c18d"))
                    )
                ),
            )

    async def solve_captcha(self, chat, target, answer, actor, destination):
        if target != actor:
            raise ValueError(tr("m_a5b09117be89"))
        c = self.db.one("SELECT * FROM captcha WHERE chat=? AND user=?", (chat, actor))
        if not c or c["expires"] < time.time():
            raise ValueError(tr("m_ee2e6b6d932d"))
        if c["answer"] != answer:
            raise ValueError(tr("m_6a09178d179f"))
        await self.release(chat, actor)
        pending_key = f"ref_pending:{chat}:{actor}"
        self.growth.record_join(chat, actor, self.db.get(pending_key, ""))
        self.db.set(pending_key, None)
        self.db.execute("DELETE FROM captcha WHERE chat=? AND user=?", (chat, actor))
        await self.tg.send(destination, tr("m_ca060088832d"))

    async def safe_handle(self, update):
        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
            or update.get("callback_query", {}).get("message")
            or update.get("chat_member")
            or update.get("my_chat_member")
            or {}
        )
        chat = message.get("chat", {}).get("id", 0)
        sender = (
            update.get("callback_query", {}).get("from")
            or update.get("inline_query", {}).get("from")
            or message.get("from", {})
        )
        code = self.db.get(f"user_language:{sender.get('id', chat)}", DEFAULT_LANGUAGE)
        if chat < 0 and self.db.one("SELECT 1 FROM chats WHERE id=?", (chat,)):
            code = self.db.chat(chat)["settings"].get("language", DEFAULT_LANGUAGE)
        with using_language(code):
            return await self._safe_handle(update)

    async def choose_language(self, chat, destination):
        rows = [[button(name, f"l:{chat}:{code}")] for code, name in LANGUAGES.items()]
        return await self.tg.send(destination, tr("language.choose"), rows)

    async def change_language(self, chat, actor, code, destination):
        if code not in LANGUAGES:
            raise ValueError(tr("language.invalid"))
        if chat > 0:
            if chat != actor:
                raise ValueError(tr("language.personal_only"))
            self.db.set(f"user_language:{actor}", code)
        else:
            await self.require_admin(chat, actor)
            self.db.setting(chat, "language", code)
        with using_language(code):
            return await self.tg.send(destination, tr("language.changed", language=LANGUAGES[code]))

    async def _safe_handle(self, update):
        try:
            await self.handle(update)
        except (ValueError, KeyError, IndexError, AIUnavailable) as exc:
            # Input errors are terminal. Unexpected KeyError/IndexError are logged by type only.
            m = update.get("message") or update.get("callback_query", {}).get("message")
            if m and "chat" in m:
                error = str(exc) if isinstance(exc, (ValueError, AIUnavailable)) else tr("m_9b73b3dd0162")
                await self.tg.send(m["chat"]["id"], escape(error[:500]))
        except APIError as exc:
            if exc.code >= 500 or exc.code == 429:
                raise
            m = update.get("message") or update.get("callback_query", {}).get("message")
            if m and "chat" in m:
                try:
                    await self.tg.send(
                        m["chat"]["id"],
                        tr("m_ecb9b7c7ba9f"),
                    )
                except APIError:
                    pass

    async def close(self):
        await self.ai.close()
        await self.engine.close()
