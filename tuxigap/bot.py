from datetime import datetime
from html import escape
import json
import logging
import secrets
import time
from zoneinfo import ZoneInfo

from . import games, stats
from .ai import AI, AIUnavailable
from .billing import Billing, PaymentNeedsReview, accept_payment, mark_refunded
from .engines import SpamEngine
from .growth import Growth, TRUTHS, DARES, FORTUNES
from .moderation import Verdict, local_check
from .telegram import APIError
from .ui import admin_keyboard, button, fun_keyboard, panel_title

log = logging.getLogger("tuxigap")
MEMBER_STATUSES = {"member", "administrator", "creator"}
BOOL_FIELDS = {
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
HELP = """🤝 <b>تاکسی گپ — راهنمای سریع</b>
مدیر: /panel یا /connect شناسه برای کانال
اعضا: /play /profile /top /daily /rules /ask سؤال
پنل دکمه‌ای عضو با ریپلای: /manage
مدیریت با ریپلای: /warn /ban /unban /mute [دقیقه] /unmute /delete /pin
یادداشت‌ها: /notes و /get نام
آموزش با ریپلای: /spam یا /ham
/stats day|week|month|year (مدیر)
/report با ریپلای: گزارش پیام به مدیران
فروشگاه: /shop، دسترسی خریداری‌شده: /subscriptions
بازپرداخت: /refund شناسه‌تراکنش (مدیر؛ نیازمند تأیید دکمه)
/paysupport /terms /privacy /forget
برای ناشناس‌بودن مدیر، پنل را در گفتگوی خصوصی باز کنید.
"""


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
        self.bot_id = db.get("bot_id", 0)
        self.username = db.get("bot_username", "")

    async def admin(self, chat, user, right=None):
        member = await self.tg.call("getChatMember", chat_id=chat, user_id=user)
        if member["status"] == "creator":
            return True
        return member["status"] == "administrator" and (not right or member.get(right, False))

    async def require_admin(self, chat, user, right=None):
        if not await self.admin(chat, user, right):
            raise ValueError("فقط مدیر فعلی گروه با دسترسی لازم اجازهٔ این کار را دارد.")

    async def require_member(self, chat, user):
        member = await self.tg.call("getChatMember", chat_id=chat, user_id=user)
        if not present(member):
            raise ValueError("این بخش فقط برای اعضای فعلی گروه است.")

    async def protect_target(self, chat, user):
        if user == self.bot_id or await self.admin(chat, user):
            raise ValueError("این اقدام روی مدیر یا خود ربات انجام نمی‌شود.")

    async def panel(self, chat, user, destination, section="home", mid=None):
        await self.require_admin(chat, user)
        info = self.db.chat(chat)
        text = panel_title(info, section)
        markup = admin_keyboard(chat, section, info["settings"])
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
        text = stats.report(self.db, chat, period, now, previous)[0]
        try:
            count = await self.tg.call("getChatMemberCount", chat_id=chat)
            text += f"\nاعضای فعلی اکنون: {count:,}"
        except APIError:
            text += "\nتعداد فعلی اعضا در دسترس نیست."
        return await self.tg.send(destination, text)

    async def release(self, chat, user):
        await self.protect_target(chat, user)
        info = await self.tg.call("getChat", chat_id=chat)
        permissions = info.get("permissions")
        if not permissions:
            raise ValueError("مجوزهای پیش‌فرض گروه قابل دریافت نیست.")
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
            [button("✅ سالم / یاد بگیر", f"v:{aid}:ham"), button("🚫 اسپم / یاد بگیر", f"v:{aid}:spam")]
        ]
        if conf["dry_run"] or verdict.review:
            prefix = "🧪 آزمایشی" if conf["dry_run"] else "🔎 نیازمند بازبینی"
            await self.log_action(
                chat,
                f"{prefix}: {escape(verdict.reason)}\nکاربر <code>{user}</code>\n{escape(row['text'][:500])}",
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
        await self.log_action(
            chat, f"🛡 پیام کاربر <code>{user}</code> حذف شد: {escape(verdict.reason)}", review
        )

    async def feedback(self, aid, label, actor, destination):
        row = self.db.one("SELECT * FROM audit WHERE id=?", (aid,))
        if not row:
            raise ValueError("این مورد پیدا نشد.")
        await self.require_admin(row["chat"], actor, "can_delete_messages")
        if label not in ("ham", "spam"):
            raise ValueError("برچسب نامعتبر است.")
        self.db.train(row["chat"], row["text"], label, actor, row["user"])
        self.engine.train(row["chat"], row["text"], label)
        self.db.audit(row["chat"], row["user"], row["mid"], actor, "feedback", label)
        await self.tg.send(
            destination,
            "✅ بازخورد ذخیره شد. حذف گذشته قابل برگرداندن نیست؛ برای رفع سکوت، از /unmute با ریپلای یا شناسه استفاده کنید.",
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
                    "title": "😄 یک شوخی برای گفتگو",
                    "input_message_content": {"message_text": secrets.choice(games.JOKES)},
                },
                {
                    "type": "article",
                    "id": "play",
                    "title": "🎮 دعوت به بازی با تاکسی گپ",
                    "input_message_content": {
                        "message_text": "برای بازی و جدول امتیاز، در گروه /play را بفرستید."
                    },
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
                                f"⚠️ پرداخت قطعی نیاز به تطبیق دستی دارد: <code>{escape(charge)}</code>؛ کاربر {user}. آپدیت در صف حفظ شده است.",
                            )
                        except APIError:
                            pass
                    self.db.set(alert_key, True)
                raise PaymentNeedsReview() from None
            if result:
                await self.tg.send(
                    user, "✅ پرداخت ثبت شد؛ لینک دسترسی تا حداکثر یک دقیقه ارسال می‌شود. /subscriptions"
                )
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
                and user
                and not m.get("sender_chat")
                and m["chat"]["type"] in ("group", "supergroup")
                and is_content
            ):
                if not await self.admin(chat, user):
                    verdict = local_check(self.db, chat, user, m, conf)
                    if not verdict.flagged and conf["external_spam"] and text:
                        flagged = await self.engine.check(chat, user, text, m["from"].get("username", ""))
                        if flagged:
                            verdict = Verdict("موتور tg-spam", review=conf["external_review"])
                    if not verdict.flagged and conf["ai_moderation"] and text and not text.startswith("/"):
                        try:
                            flagged, confidence, reason = await self.ai.moderate(
                                chat, user, text, conf["rules"]
                            )
                            if flagged and confidence >= conf["ai_threshold"]:
                                verdict = Verdict("AI: " + reason, review=True)
                        except AIUnavailable:
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
        if cmd == "cancel":
            self.db.execute("DELETE FROM sessions WHERE user=?", (user,))
            return await self.tg.send(chat, "عملیات ورود متن لغو شد.")
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
                raise ValueError("گروه یا کانال را انتخاب کنید.")
            await self.require_admin(info["id"], user)
            if not await self.admin(info["id"], self.bot_id):
                raise ValueError("ابتدا ربات را ادمین کنید.")
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
                raise ValueError("روی پیام عضو ریپلای کرده و /manage را بفرستید.")
            uid, message_id = target["from"]["id"], target["message_id"]

            def member_button(label, action):
                return button(label, f"u:{chat}:{uid}:{action}:{message_id}")

            return await self.tg.send(
                chat,
                f"🛠 مدیریت عضو <code>{uid}</code>",
                [
                    [member_button("اخطار", "warn"), member_button("سکوت ۱۰ دقیقه", "mute")],
                    [member_button("رفع سکوت", "unmute"), member_button("حذف پیام", "delete")],
                    [member_button("مسدودکردن", "banconfirm"), member_button("رفع مسدودی", "unban")],
                    [member_button("آموزش: اسپم", "spam"), member_button("آموزش: سالم", "ham")],
                ],
            )
        if cmd in ("privacy", "terms", "paysupport"):
            messages = {
                "privacy": f"متن پیام‌ها و شواهد مدیریت تا {self.config.retention_days} روز نگهداری می‌شوند؛ نمونه‌های آموزشی تا ۹۰ روز. آمار فعالیت و دفتر پرداخت ماندگارند. AI به‌صورت پیش‌فرض خاموش است؛ با روشن‌شدن، متن به ارائه‌دهندهٔ تنظیم‌شده ارسال می‌شود. /forget برای حذف پروفایل سرگرمی و متن‌های خودتان؛ سوابق مالی و شمارنده‌های تجمیعی حفظ می‌شوند.",
                "terms": "شرایط فروش: "
                + escape(self.config.terms_url or "مدیر هنوز شرایط فروش را تنظیم نکرده است."),
                "paysupport": "پشتیبانی پرداخت: "
                + escape(
                    "@" + self.config.support_username
                    if self.config.support_username
                    else "هنوز تنظیم نشده است."
                ),
            }
            return await self.tg.send(chat, messages[cmd])
        if cmd == "forget":
            return await self.tg.send(
                chat,
                "پروفایل بازی، متن‌های ذخیره‌شده و ردیف‌های فعالیت شخصی شما در همهٔ گروه‌ها پاک شود؟ شمارنده‌های کلی و سوابق پرداخت باقی می‌مانند.",
                [[button("حذف داده‌های شخصی من", f"forget:{user}")]],
            )
        if cmd in ("shop", "subscriptions"):
            if not private:
                return await self.tg.send(
                    chat,
                    "فروشگاه و اشتراک‌ها در گفتگوی خصوصی ربات در دسترس‌اند.",
                    [[{"text": "بازکردن ربات", "url": f"https://t.me/{self.username}?start=shop"}]],
                )
            return await (self.store(user) if cmd == "shop" else self.subscriptions(user))
        if cmd == "ask":
            if private:
                raise ValueError(
                    "برای گفتگو با AI، در گروهی که مدیر این قابلیت را فعال کرده /ask سؤال را بفرستید."
                )
            conf = self.db.chat(chat)["settings"]
            if not conf["ai"]:
                raise ValueError("دستیار هوش مصنوعی در این گروه خاموش است.")
            if not args:
                raise ValueError("پس از /ask سؤال خود را بنویسید.")
            if not self.db.cooldown(chat, user, "ai", 15):
                return
            answer = await self.ai.answer(chat, user, args, conf["rules"])
            return await self.tg.send(chat, escape(answer))
        if private:
            if cmd == "refund":
                return await self.refund_prompt(user, args, user)
            raise ValueError("این دستور را در گروه استفاده کنید، یا /panel را باز کنید.")
        if cmd == "rules":
            return await self.tg.send(chat, escape(self.db.chat(chat)["settings"]["rules"]))
        if cmd == "notes":
            rows = self.db.all("SELECT name FROM notes WHERE chat=? ORDER BY name LIMIT 50", (chat,))
            return await self.tg.send(
                chat, "📝 یادداشت‌های عمومی:\n" + "\n".join(escape(r["name"]) for r in rows) + "\n/get نام"
            )
        if cmd == "get":
            row = self.db.one("SELECT body FROM notes WHERE chat=? AND name=?", (chat, args.strip()))
            return await self.tg.send(chat, escape(row["body"]) if row else "یادداشت پیدا نشد.")
        if cmd in ("play", "profile", "daily", "top", "joke", "quiz", "dice"):
            return await self.fun(
                chat, user, "menu" if cmd == "play" else cmd, chat, m["from"].get("first_name", "")
            )
        if cmd == "report":
            if not self.db.cooldown(chat, user, "report", 60):
                return
            target = m.get("reply_to_message")
            if not target or not target.get("from"):
                raise ValueError("روی پیام موردنظر ریپلای کنید.")
            aid = self.db.audit(
                chat,
                target["from"]["id"],
                target["message_id"],
                user,
                "report",
                "گزارش عضو",
                target.get("text", target.get("caption", "")),
            )
            return await self.log_action(
                chat,
                "🚩 گزارش عضو:\n" + escape(target.get("text", target.get("caption", ""))[:500]),
                [[button("سالم", f"v:{aid}:ham"), button("نمونهٔ اسپم", f"v:{aid}:spam")]],
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
                raise ValueError("روی پیام یک کاربر ریپلای کنید؛ /unban و /unmute شناسهٔ عددی هم می‌پذیرند.")
            if cmd in ("spam", "ham"):
                self.db.train(chat, target.get("text", target.get("caption", "")), cmd, user, target_user)
                self.engine.train(chat, target.get("text", target.get("caption", "")), cmd)
                return await self.tg.send(
                    chat,
                    "✅ نمونهٔ آموزشی ذخیره شد. این دستور فقط آموزش می‌دهد؛ برای حذف از /delete استفاده کنید.",
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
                    chat, target_user, m["message_id"], user, cmd, "دستور مدیر", status="pending"
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
                    raise ValueError("زمان سکوت باید ۱ تا ۵۲۵۶۰۰ دقیقه باشد.")
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
            return await self.tg.send(chat, "✅ انجام شد.")

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
            "گروه یا کانال را انتخاب کنید. برای اتصال، ربات را ادمین کرده و در گروه /panel بفرستید؛ برای کانال /connect شناسه را همین‌جا بفرستید.",
            rows,
        )

    async def fun(self, chat, user, action, destination, name=""):
        await self.require_member(chat, user)
        conf = self.db.chat(chat)["settings"]
        if not conf["fun"]:
            raise ValueError("سرگرمی این گروه خاموش است.")
        self.db.member(chat, user, name)
        if action not in ("menu", "profile", "rules", "top", "shop") and not self.db.cooldown(
            chat, user, "fun", 5
        ):
            raise ValueError("چند ثانیه صبر کنید 🙂")
        if action == "menu":
            return await self.tg.send(destination, "🎮 یک فعالیت انتخاب کن:", fun_keyboard(chat))
        if action == "quiz":
            if not self.db.cooldown(chat, 0, "quiz", 60):
                raise ValueError("تا مسابقهٔ بعدی یک دقیقه فاصله لازم است.")
            question, keyboard = games.quiz(self.db, chat)
            return await self.tg.send(
                chat,
                "🧩 " + question + "\nاولین پاسخ درست برنده است؛ هر نفر یک فرصت، زمان ۵ دقیقه.",
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
                "🏆 رتبه‌بندی امتیاز\n"
                + "\n".join(
                    f"{i}. {escape(r['name'])} {escape(r['badge'])} — {r['xp']}"
                    for i, r in enumerate(rows, 1)
                ),
            )
        if action == "profile":
            p = self.db.member(chat, user)
            return await self.tg.send(
                destination,
                f"👤 {escape(p['name'])} {escape(p['badge'])}\nسطح: {p['xp'] // 100 + 1}\nامتیاز: {p['xp']}\nسکهٔ بازی: {p['coins']}\nاخطار: {p['warns']}\nسکهٔ بازی ارزش مالی ندارد.",
            )
        if action == "rules":
            return await self.tg.send(destination, escape(conf["rules"]))
        if action == "invite":
            if not self.db.cooldown(chat, user, "invite", 60):
                raise ValueError("لینک قبلاً ارسال شد؛ یک دقیقه بعد دوباره تلاش کنید.")
            return await self.growth.invite(chat, user)
        if action in ("truth", "dare", "fortune"):
            items = {"truth": TRUTHS, "dare": DARES, "fortune": FORTUNES}[action]
            prefix = "🔮 صرفاً سرگرمی: " if action == "fortune" else "🎭 "
            return await self.tg.send(destination, prefix + secrets.choice(items))
        if action == "referrals":
            rows = self.db.all(
                "SELECT r.inviter,count(*) n,coalesce(m.name,cast(r.inviter as TEXT)) name FROM referrals r LEFT JOIN members m ON r.chat=m.chat AND r.inviter=m.user WHERE r.chat=? GROUP BY r.inviter ORDER BY n DESC LIMIT 10",
                (chat,),
            )
            return await self.tg.send(
                destination,
                "🏅 برترین معرف‌ها\n"
                + "\n".join(f"{i}. {escape(r['name'])}: {r['n']}" for i, r in enumerate(rows, 1)),
            )
        if action == "like":
            if self.db.cooldown(chat, user, "like", 86400):
                self.db.bump(chat, "likes")
            return await self.tg.send(destination, "🌷 بازخوردت ثبت شد.")
        if action == "shop":
            return await self.tg.send(
                destination,
                "نشان‌ها با سکهٔ بازی خریداری می‌شوند:",
                [
                    [
                        button("🌱 نشان جوانه — ۱۰۰", f"f:{chat}:badge:100"),
                        button("🌟 نشان ستاره — ۵۰۰", f"f:{chat}:badge:500"),
                    ]
                ],
            )
        if action.startswith("badge:"):
            price = int(action.split(":")[1])
            if price not in (100, 500):
                raise ValueError("نشان نامعتبر است.")
            badge = "🌱" if price == 100 else "🌟"
            changed = self.db.execute(
                "UPDATE members SET coins=coins-?,badge=? WHERE chat=? AND user=? AND coins>=? AND badge<>?",
                (price, badge, chat, user, price, badge),
            ).rowcount
            return await self.tg.send(
                destination, "✅ نشان فعال شد." if changed else "سکه کافی نیست یا همین نشان را دارید."
            )
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
                "سنگ، کاغذ یا قیچی؟",
                [[button(x, f"r:{token}:{i}") for i, x in enumerate(("سنگ", "کاغذ", "قیچی"))]],
            )

    async def callback(self, q):
        user = q["from"]["id"]
        m = q.get("message")
        if not m or "chat" not in m:
            return await self.tg.call(
                "answerCallbackQuery", callback_query_id=q["id"], text="این دکمه را در گفتگوی ربات باز کنید."
            )
        destination, mid = m["chat"]["id"], m["message_id"]
        parts = q.get("data", "").split(":")
        route = parts[0]
        if route == "g":
            text = await self.growth.enter(parts[1], user)
            return await self.tg.call("answerCallbackQuery", callback_query_id=q["id"], text=text)
        await self.tg.call("answerCallbackQuery", callback_query_id=q["id"])
        if route == "a":
            chat, action = int(parts[1]), parts[2]
            await self.require_admin(chat, user)
            conf = self.db.chat(chat)["settings"]
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
                lines = [f"اعضای فعلی: {count}", f"وضعیت ربات: {bot_member['status']}"]
                lines += [f"{key}: {'✅' if bot_member.get(key) else '❌'}" for key in required]
                lines += [
                    f"AI: {'✅' if self.config.ai_key and self.config.ai_model else '❌ کلید یا مدل تنظیم نشده'}",
                    "برای حالت @bot در BotFather گزینهٔ /setinline را فعال کنید.",
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
                    "نمونه‌های ۹۰ روز اخیر:\n"
                    + "\n".join(f"{r['label']}: {r['n']}" for r in rows)
                    + "\nبا ریپلای روی پیام از /spam و /ham استفاده کنید.",
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
                        [[button("سالم", f"v:{r['id']}:ham"), button("اسپم", f"v:{r['id']}:spam")]],
                    )
                if not rows:
                    await self.tg.send(destination, "موردی برای بازبینی نیست.")
                return
            if action == "resetconfirm":
                return await self.tg.send(
                    destination,
                    "همهٔ نمونه‌های آموزشی این گروه پاک شوند؟",
                    [[button("تأیید پاک‌کردن", f"a:{chat}:reset")]],
                )
            if action == "reset":
                self.db.execute("DELETE FROM samples WHERE chat=?", (chat,))
                return await self.tg.send(destination, "نمونه‌ها پاک شدند.")
            if action == "gateconfirm":
                return await self.tg.send(
                    destination,
                    "با فعال‌سازی، ورود اعضای جدید و ماندن مشترکان ثبت‌شده وابسته به پرداخت می‌شود. گروه باید خصوصی باشد و لینک‌های قدیمی را خودتان لغو کنید. اعضای قبلیِ بدون اشتراک خودکار اخراج نمی‌شوند.",
                    [
                        [
                            button("فعال‌سازی دروازه", f"a:{chat}:gateon"),
                            button("غیرفعال‌سازی", f"a:{chat}:gateoff"),
                        ]
                    ],
                )
            if action in ("gateon", "gateoff"):
                await self.require_admin(chat, user, "can_restrict_members")
                if action == "gateon":
                    info = await self.tg.call("getChat", chat_id=chat)
                    if info.get("username"):
                        raise ValueError("گروه یا کانال باید خصوصی باشد.")
                    if not self.config.support_username or not self.config.terms_url:
                        raise ValueError("ابتدا پشتیبانی و شرایط فروش را در .env تنظیم کنید.")
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
                    "طرح‌ها؛ دکمه برای فعال/غیرفعال‌کردن:\n"
                    + f"لینک فروشگاه: https://t.me/{self.username}?start=buy_{chat}",
                    keyboard,
                )
            if action == "plan":
                self.db.execute(
                    "UPDATE plans SET enabled=1-enabled WHERE id=? AND chat=?", (int(parts[3]), chat)
                )
                return await self.tg.send(destination, "وضعیت طرح عوض شد.")
            if action == "revenue":
                return await self.send_stats(chat, user, "month")
            if action == "jobs":
                rows = self.db.all(
                    "SELECT * FROM jobs WHERE chat=? AND state='pending' ORDER BY due LIMIT 20", (chat,)
                )
                return await self.tg.send(
                    destination,
                    "ارسال‌های در انتظار؛ دکمه برای لغو:",
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
                return await self.tg.send(destination, "ارسال زمان‌بندی‌شده لغو شد.")
            if action in ("lock", "unlock"):
                await self.require_admin(chat, user, "can_restrict_members")
                if self.db.chat(chat)["kind"] not in ("group", "supergroup"):
                    raise ValueError("قفل اضطراری فقط برای گروه است.")
                if action == "lock":
                    info = await self.tg.call("getChat", chat_id=chat)
                    if not self.db.get(f"lock:{chat}"):
                        self.db.set(f"lock:{chat}", info["permissions"])
                    permissions = {k: False for k in info["permissions"]}
                else:
                    permissions = self.db.get(f"lock:{chat}")
                    if not permissions:
                        raise ValueError("مجوز ذخیره‌شده‌ای برای بازگردانی نیست.")
                await self.tg.call(
                    "setChatPermissions",
                    chat_id=chat,
                    permissions=permissions,
                    use_independent_chat_permissions=True,
                )
                if action == "unlock":
                    self.db.set(f"lock:{chat}", None)
                self.db.audit(chat, 0, 0, user, action, "قفل اضطراری")
                return await self.tg.send(destination, "✅ مجوزهای گروه به‌روز شدند.")
        elif route == "u":
            chat, target, action, target_mid = int(parts[1]), int(parts[2]), parts[3], int(parts[4])
            await self.require_admin(chat, user)
            if action == "banconfirm":
                return await self.tg.send(
                    destination,
                    f"عضو {target} مسدود شود؟",
                    [[button("تأیید مسدودی", f"u:{chat}:{target}:ban:{target_mid}")]],
                )
            if action not in {"warn", "mute", "unmute", "ban", "unban", "delete", "spam", "ham"}:
                raise ValueError("اقدام نامعتبر است.")
            cached = self.db.one(
                "SELECT * FROM messages WHERE chat=? AND mid=? AND user=?", (chat, target_mid, target)
            )
            if action in {"delete", "spam", "ham"} and not cached:
                raise ValueError("پیام در حافظهٔ ربات نیست؛ روی پیام اصلی از دستور استفاده کنید.")
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
                raise ValueError("مسابقه منقضی است.")
            await self.require_member(game["chat"], user)
            if not self.db.chat(game["chat"])["settings"]["fun"]:
                raise ValueError("بازی غیرفعال است.")
            _, text = games.answer_quiz(self.db, parts[1], user, parts[2])
            return await self.tg.send(destination, text)
        elif route == "r":
            game = self.db.one("SELECT * FROM games WHERE token=?", (parts[1],))
            if not game or game["expires"] < time.time() or game["winner"] is not None:
                raise ValueError("بازی تمام شده است.")
            data = json.loads(game["data"])
            if data["user"] != user:
                raise ValueError("این نوبت بازی برای کاربر دیگری است.")
            await self.require_member(game["chat"], user)
            if not self.db.chat(game["chat"])["settings"]["fun"]:
                raise ValueError("بازی غیرفعال است.")
            choice = int(parts[2])
            if choice not in range(3):
                raise ValueError("انتخاب نامعتبر است.")
            result = (choice - data["bot"]) % 3
            self.db.execute("UPDATE games SET winner=? WHERE token=?", (user, parts[1]))
            self.db.bump(game["chat"], "games")
            return await self.tg.send(
                destination,
                f"انتخاب ربات: {('سنگ', 'کاغذ', 'قیچی')[data['bot']]}\n"
                + ("مساوی شد 🤝" if result == 0 else "بردی 🎉" if result == 1 else "این بار ربات برد 🙂"),
            )
        elif route == "v":
            return await self.feedback(int(parts[1]), parts[2], user, destination)
        elif route == "c":
            return await self.solve_captcha(int(parts[1]), int(parts[2]), parts[3], user, destination)
        elif route == "buy":
            if destination != user:
                raise ValueError("خرید را در گفتگوی خصوصی انجام دهید.")
            p = self.db.one("SELECT * FROM plans WHERE id=?", (int(parts[1]),))
            if not p:
                raise ValueError("طرح نامعتبر است.")
            # Require a second explicit click after terms; no charge on the first click.
            return await self.tg.send(
                user,
                f"{escape(p['name'])}: {p['stars']} ⭐ برای {p['days']} روز.\n"
                + ("تمدید خودکار هر ۳۰ روز.\n" if p["recurring"] else "تمدید دستی است.\n")
                + "با ادامه شرایط فروش را می‌پذیرید: "
                + escape(self.config.terms_url),
                [[button("می‌پذیرم؛ ساخت صورت‌حساب", f"pay:{p['id']}")]],
            )
        elif route == "pay":
            if destination != user:
                raise ValueError("خرید خصوصی است.")
            return await self.billing.invoice(user, int(parts[1]))
        elif route == "access":
            if destination != user:
                raise ValueError("لینک دسترسی فقط خصوصی ارسال می‌شود.")
            return await self.billing.access_link(int(parts[1]), user)
        elif route == "cancelrec":
            p = self.db.one("SELECT * FROM payments WHERE rowid=? AND user=?", (int(parts[1]), user))
            if not p:
                raise ValueError("اشتراک پیدا نشد.")
            inv = self.db.one("SELECT * FROM invoices WHERE payload=?", (p["payload"],))
            if not inv["recurring"]:
                raise ValueError("این طرح تمدید خودکار ندارد.")
            if not inv["cancelled"]:
                await self.tg.call(
                    "editUserStarSubscription",
                    user_id=user,
                    telegram_payment_charge_id=p["charge"],
                    is_canceled=True,
                )
                self.db.execute("UPDATE invoices SET cancelled=1 WHERE payload=?", (p["payload"],))
            return await self.tg.send(user, "تمدید خودکار لغو شد؛ دسترسی تا پایان دوره باقی می‌ماند.")
        elif route == "refund":
            p = self.db.one("SELECT * FROM payments WHERE rowid=?", (int(parts[1]),))
            if not p:
                raise ValueError("تراکنش پیدا نشد.")
            await self.require_admin(p["chat"], user, "can_restrict_members")
            await self.billing.refund(p["charge"])
            return await self.tg.send(destination, "✅ بازپرداخت ثبت و دسترسی دوباره محاسبه شد.")
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
                "✅ پروفایل سرگرمی، متن پیام‌ها و جزئیات فعالیت شخصی پاک شد. دفتر پرداخت و آمار کلی حفظ شدند.",
            )

    async def prompt(self, user, chat, field):
        prompts = {
            "giveaway": "عنوان جایزه | زمان به دقیقه\nمثال: نشان عضو برتر | 60\nشرکت رایگان است. برنده ۱۰۰ سکهٔ بازی هم می‌گیرد؛ تحویل جایزهٔ ذکرشده با مدیر است.",
            "poll": "سؤال | گزینهٔ اول | گزینهٔ دوم | ...\n۲ تا ۱۰ گزینه؛ نظرسنجی برای همهٔ اعضا ارسال می‌شود.",
            "note": "نام یادداشت | متن\nبرای حذف: نام | -\nیادداشت برای همهٔ اعضا با /get نام قابل مشاهده است.",
            "filter": "عبارت دقیق | پاسخ خودکار\nبرای حذف: عبارت | -",
            "log_chat": "شناسهٔ کانال یا گروه گزارش‌ها را بفرستید؛ باید شما و ربات هر دو ادمین مقصد باشید. برای گزارش در همین گروه عدد 0 را بفرستید.",
            "words": "واژه‌ها یا عبارت‌های ممنوعه را هرکدام در یک خط بفرستید؛ * در ابتدای واژه برای جستجوی بخشی از کلمه. برای پاک‌کردن: -",
            "flood": "تعداد و بازهٔ ثانیه را بفرستید؛ مثال: 6 10",
            "warn_limit": "حد اخطار را از ۱ تا ۲۰ بفرستید.",
            "mute_minutes": "زمان سکوت را از ۱ تا ۱۴۴۰ دقیقه بفرستید.",
            "timezone": "نام منطقهٔ زمانی؛ مثال Asia/Tehran",
            "report_hour": "ساعت گزارش را از ۰ تا ۲۳ بفرستید.",
            "welcome_text": "متن خوشامدگویی را بفرستید؛ {name} با نام عضو جایگزین می‌شود.",
            "rules": "متن قوانین گروه را بفرستید.",
            "schedule": "زمان محلی و متن را با | جدا کنید:\n2027-01-15 18:30 | متن پیام\nارسال در همین گروه یا کانال انجام می‌شود.",
            "plan": "نام | قیمت Stars | روز | دوره‌ای ۰ یا ۱\nمثال: ماهانه | 100 | 30 | 0\nدوره‌ای فقط برای ۳۰ روز و تا ۱۰۰۰۰ ستاره است.",
        }
        await self.tg.send(user, prompts[field] + "\nبرای انصراف: /cancel")
        self.db.execute(
            "INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)", (user, chat, field, int(time.time()) + 600)
        )

    async def save_input(self, user, chat, field, text):
        await self.require_admin(chat, user)
        if field not in INPUTS:
            raise ValueError("درخواست نامعتبر است.")
        if field == "giveaway":
            title, minutes = text.split("|", 1)
            await self.growth.giveaway(chat, title.strip(), int(minutes.strip()), user)
        elif field == "poll":
            pieces = [piece.strip() for piece in text.split("|")]
            if (
                not 3 <= len(pieces) <= 11
                or not 1 <= len(pieces[0]) <= 300
                or any(not 1 <= len(x) <= 100 for x in pieces[1:])
            ):
                raise ValueError("سؤال تا ۳۰۰ نویسه و ۲ تا ۱۰ گزینهٔ حداکثر ۱۰۰ نویسه‌ای لازم است.")
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
                raise ValueError("نام ۱ تا ۸۰ و متن ۱ تا ۲۰۰۰ نویسه باشد.")
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
                    raise ValueError("مقصد باید گروه یا کانال باشد.")
                await self.require_admin(destination, user)
                if not await self.admin(destination, self.bot_id):
                    raise ValueError("ربات در مقصد ادمین نیست.")
            self.db.setting(chat, field, destination)
        elif field == "words":
            value = [] if text.strip() == "-" else [w.strip() for w in text.splitlines() if w.strip()]
            if len(value) > 200 or any(len(w) > 100 for w in value):
                raise ValueError("حداکثر ۲۰۰ عبارت، هرکدام ۱۰۰ نویسه.")
            self.db.setting(chat, field, value)
        elif field == "flood":
            count, seconds = map(int, text.split())
            if not 2 <= count <= 100 or not 2 <= seconds <= 120:
                raise ValueError("تعداد ۲ تا ۱۰۰ و بازه ۲ تا ۱۲۰ ثانیه باشد.")
            self.db.setting(chat, "flood_count", count)
            self.db.setting(chat, "flood_seconds", seconds)
        elif field in ("warn_limit", "mute_minutes", "report_hour"):
            value = int(text)
            low, high = {"warn_limit": (1, 20), "mute_minutes": (1, 1440), "report_hour": (0, 23)}[field]
            if not low <= value <= high:
                raise ValueError(f"عدد باید بین {low} و {high} باشد.")
            self.db.setting(chat, field, value)
        elif field == "timezone":
            ZoneInfo(text.strip())
            self.db.setting(chat, field, text.strip())
        elif field in ("rules", "welcome_text"):
            if not 1 <= len(text) <= 2000:
                raise ValueError("متن باید ۱ تا ۲۰۰۰ نویسه باشد.")
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
                raise ValueError("زمان باید در آینده و حداکثر یک سال بعد باشد؛ متن حداکثر ۳۵۰۰ نویسه.")
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
                raise ValueError(
                    "طرح نامعتبر است؛ نام تا ۳۲ نویسه، قیمت ۱ تا ۱۰۰۰۰، مدت ۱ تا ۳۶۵ روز؛ دوره‌ای فقط ۳۰ روز."
                )
            self.db.execute(
                "INSERT INTO plans(chat,name,stars,days,recurring) VALUES(?,?,?,?,?)",
                (chat, name, stars, days, recurring),
            )
        self.db.execute("DELETE FROM sessions WHERE user=?", (user,))
        self.db.audit(chat, 0, 0, user, "setting", field)
        await self.tg.send(user, "✅ ذخیره شد.")
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
            "⭐ فروشگاه اشتراک\nبرای دیدن شرایط و قیمت، یک طرح را انتخاب کنید."
            if rows
            else "فعلاً طرح فعالی وجود ندارد.",
            keyboard,
        )

    async def subscriptions(self, user):
        subs = self.db.all(
            "SELECT s.*,c.title FROM subscriptions s JOIN chats c ON c.id=s.chat WHERE user=?", (user,)
        )
        keyboard = [
            [
                button(
                    s["title"][:30] + (" ✅" if s["expires"] > time.time() else " — منقضی"),
                    f"access:{s['chat']}",
                )
            ]
            for s in subs
        ]
        for p in self.db.all(
            "SELECT min(payments.rowid) rid,payments.chat FROM payments JOIN invoices ON payments.payload=invoices.payload WHERE payments.user=? AND invoices.recurring=1 AND invoices.cancelled=0 AND payments.refunded=0 GROUP BY payments.payload ORDER BY max(payments.paid_at) DESC LIMIT 20",
            (user,),
        ):
            keyboard.append([button(f"لغو تمدید خودکار {p['chat']}", f"cancelrec:{p['rid']}")])
        await self.tg.send(
            user,
            "اشتراک‌ها؛ برای دریافت دوبارهٔ لینک ورود انتخاب کنید. لغو تمدید، دورهٔ جاری را حذف نمی‌کند.",
            keyboard,
        )

    async def refund_prompt(self, user, charge, destination):
        p = self.db.one("SELECT rowid rid,* FROM payments WHERE charge=?", (charge,))
        if not p:
            raise ValueError("تراکنش پیدا نشد.")
        await self.require_admin(p["chat"], user, "can_restrict_members")
        await self.tg.send(
            destination,
            f"بازپرداخت {p['stars']} ⭐ به کاربر {p['user']} و محاسبهٔ مجدد دسترسی؟ تمدید خودکار همین طرح هم لغو می‌شود.",
            [[button("تأیید بازپرداخت", f"refund:{p['rid']}")]],
        )

    async def membership(self, event):
        chat, target = event["chat"]["id"], event["new_chat_member"]["user"]
        self.db.register(event["chat"])
        before, after = present(event["old_chat_member"]), present(event["new_chat_member"])
        if before == after:
            return
        user = target["id"]
        self.db.member(chat, user, target.get("first_name", ""))
        self.db.bump(chat, "joins" if after else "leaves", ts=event.get("date"))
        if not after:
            self.db.execute("DELETE FROM captcha WHERE chat=? AND user=?", (chat, user))
            return
        conf = self.db.chat(chat)["settings"]
        if not conf["enabled"] or user == self.bot_id or await self.admin(chat, user):
            return
        if conf["paid_gate"] and not self.billing.active(chat, user):
            await self.billing.gate_ban(chat, user)
            self.db.bump(chat, "bans")
            return
        if conf["bots"] and target.get("is_bot") and not conf["dry_run"]:
            await self.tg.call("banChatMember", chat_id=chat, user_id=user)
            self.db.bump(chat, "bans")
            return
        if conf["captcha"] and not conf["dry_run"] and event["chat"]["type"] == "supergroup":
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
                f"{escape(target.get('first_name', 'عضو جدید'))}، حاصل {a} + {b} را انتخاب کن؛ ۳ دقیقه زمان داری.",
                [[button(str(x), f"c:{chat}:{user}:{x}") for x in choices]],
            )
        self.growth.record_join(
            chat, user, event.get("invite_link", {}).get("invite_link", ""), not target.get("is_bot", False)
        )
        if conf["welcome"] and event["chat"]["type"] in ("group", "supergroup"):
            await self.tg.send(
                chat, escape(conf["welcome_text"].replace("{name}", target.get("first_name", "دوست")))
            )

    async def solve_captcha(self, chat, target, answer, actor, destination):
        if target != actor:
            raise ValueError("این سؤال برای عضو تازه‌وارد است.")
        c = self.db.one("SELECT * FROM captcha WHERE chat=? AND user=?", (chat, actor))
        if not c or c["expires"] < time.time():
            raise ValueError("کپچا تمام شده است.")
        if c["answer"] != answer:
            raise ValueError("پاسخ درست نیست؛ دوباره تلاش کنید.")
        await self.release(chat, actor)
        pending_key = f"ref_pending:{chat}:{actor}"
        self.growth.record_join(chat, actor, self.db.get(pending_key, ""))
        self.db.set(pending_key, None)
        self.db.execute("DELETE FROM captcha WHERE chat=? AND user=?", (chat, actor))
        await self.tg.send(destination, "✅ خوش آمدی؛ می‌توانی پیام بفرستی.")

    async def safe_handle(self, update):
        try:
            await self.handle(update)
        except (ValueError, KeyError, IndexError, AIUnavailable) as exc:
            # Input errors are terminal. Unexpected KeyError/IndexError are logged by type only.
            m = update.get("message") or update.get("callback_query", {}).get("message")
            if m and "chat" in m:
                error = (
                    str(exc) if isinstance(exc, (ValueError, AIUnavailable)) else "درخواست نامعتبر است؛ /help"
                )
                await self.tg.send(m["chat"]["id"], escape(error[:500]))
        except APIError as exc:
            if exc.code >= 500 or exc.code == 429:
                raise
            m = update.get("message") or update.get("callback_query", {}).get("message")
            if m and "chat" in m:
                try:
                    await self.tg.send(
                        m["chat"]["id"],
                        "تلگرام اجازهٔ انجام این کار را نداد. دسترسی ادمین و شروع گفتگوی خصوصی با ربات را بررسی کنید.",
                    )
                except APIError:
                    pass

    async def close(self):
        await self.ai.close()
        await self.engine.close()
