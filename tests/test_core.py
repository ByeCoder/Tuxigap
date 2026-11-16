from datetime import datetime, timezone
import json
import time
import unittest

import httpx

from tuxigap.ai import AI, AIUnavailable
from tuxigap.billing import accept_payment, mark_refunded
from tuxigap.bot import Bot
from tuxigap.config import Config
from tuxigap.db import DB
from tuxigap import games, stats
from tuxigap.moderation import normalize, prohibited, local_check
from tuxigap.telegram import APIError, Telegram
from tuxigap.ui import admin_keyboard
from tuxigap.worker import drain_once, reports, scheduled_posts


CHAT = -100123


def seed(db):
    db.register({"id": CHAT, "title": "گروه آزمایش", "type": "supergroup"})
    db.set("bot_id", 99)
    db.set("bot_username", "TuxigapTestBot")


def payment(charge="charge-1", amount=100, payload="invoice", **extra):
    return {
        "invoice_payload": payload,
        "currency": "XTR",
        "total_amount": amount,
        "telegram_payment_charge_id": charge,
        **extra,
    }


def invoice(db, payload="invoice", user=2, days=30, recurring=0, now=None):
    db.execute(
        "INSERT OR REPLACE INTO invoices(payload,user,chat,plan,stars,days,recurring,created) VALUES(?,?,?,?,?,?,?,?)",
        (payload, user, CHAT, 1, 100, days, recurring, now or int(time.time())),
    )


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:")
        seed(self.db)

    def tearDown(self):
        self.db.close()

    def test_message_dedup(self):
        self.assertTrue(self.db.message(CHAT, 1, 2, "سلام", "text", 1000))
        self.assertFalse(self.db.message(CHAT, 1, 2, "سلام", "text", 1000))
        self.assertEqual(self.db.one("SELECT sum(n) n FROM hours WHERE metric='messages'")["n"], 1)

    def test_transaction_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                self.db.set("test", True)
                raise RuntimeError()
        self.assertIsNone(self.db.get("test"))

    def test_persian_normalization(self):
        self.assertEqual(normalize("كِتاب ي\u200bک"), "کتاب یک")
        self.assertTrue(prohibited("این پیام بد است", ["پیام بد"]))
        self.assertFalse(prohibited("کتابخانه", ["کتاب"]))
        self.assertTrue(prohibited("کتابخانه", ["*کتاب"]))
        self.assertTrue(prohibited("a+b", ["a+b"]))

    def test_training_isolated_and_ham_override(self):
        self.db.train(CHAT, "تبلیغات تکراری مزاحم در گروه ما", "spam", 1)
        m = {"message_id": 20, "text": "تبلیغات تکراری مزاحم در گروه ما"}
        verdict = local_check(self.db, CHAT, 2, m, self.db.chat(CHAT)["settings"])
        self.assertTrue(verdict.review)
        self.assertFalse(local_check(self.db, -100999, 2, m, self.db.chat(CHAT)["settings"]).flagged)
        self.db.train(CHAT, m["text"], "ham", 1)
        self.assertFalse(local_check(self.db, CHAT, 2, m, self.db.chat(CHAT)["settings"]).flagged)

    def test_flood(self):
        for mid in range(7):
            self.db.message(CHAT, mid, 2, str(mid), "text", 1000 + mid)
        self.assertEqual(
            local_check(
                self.db, CHAT, 2, {"message_id": 6, "text": "6"}, self.db.chat(CHAT)["settings"], 1006
            ).reason,
            "Too many messages too quickly",
        )

    def test_hidden_link_and_caption(self):
        conf = self.db.chat(CHAT)["settings"] | {"links": True}
        m = {
            "message_id": 10,
            "caption": "کلیک کن",
            "caption_entities": [{"type": "text_link", "url": "https://example.com"}],
        }
        self.assertTrue(local_check(self.db, CHAT, 2, m, conf).flagged)

    def test_retention_keeps_statistics(self):
        self.db.message(CHAT, 1, 2, "old text", "text", 100)
        self.db.audit(CHAT, 2, 1, 1, "test", "", "old text")
        self.db.prune(1, int(time.time()) + 2 * 86400)
        self.assertEqual(self.db.all("SELECT * FROM messages"), [])
        self.assertEqual(self.db.one("SELECT text FROM audit")["text"], "")
        self.assertEqual(self.db.one("SELECT n FROM hours WHERE metric='messages'")["n"], 1)

    def test_payment_duplicate_no_double_extension(self):
        invoice(self.db)
        self.assertIsNotNone(accept_payment(self.db, 2, payment(), 1000))
        self.assertIsNone(accept_payment(self.db, 2, payment(), 1000))
        self.assertEqual(self.db.one("SELECT expires FROM subscriptions")["expires"], 1000 + 30 * 86400)

    def test_payment_wrong_price_or_buyer_rejected(self):
        invoice(self.db)
        for user, p in [(3, payment()), (2, payment(amount=1)), (2, payment(currency="USD"))]:
            with self.assertRaises(ValueError):
                accept_payment(self.db, user, p)
        self.assertEqual(self.db.all("SELECT * FROM subscriptions"), [])

    def test_fixed_invoice_cannot_be_paid_twice(self):
        invoice(self.db)
        accept_payment(self.db, 2, payment(), 1000)
        with self.assertRaises(ValueError):
            accept_payment(self.db, 2, payment("charge-2"), 1001)

    def test_extension_and_refund_recompute(self):
        invoice(self.db)
        accept_payment(self.db, 2, payment(), 1000)
        invoice(self.db, "second")
        accept_payment(self.db, 2, payment("charge-2", payload="second"), 2000)
        self.assertEqual(self.db.one("SELECT expires FROM subscriptions")["expires"], 1000 + 60 * 86400)
        mark_refunded(self.db, "charge-1")
        self.assertEqual(self.db.one("SELECT expires FROM subscriptions")["expires"], 2000 + 30 * 86400)
        mark_refunded(self.db, "charge-1")
        self.assertEqual(self.db.one("SELECT expires FROM subscriptions")["expires"], 2000 + 30 * 86400)

    def test_recurring_uses_telegram_expiration(self):
        invoice(self.db, recurring=1)
        accept_payment(self.db, 2, payment(is_recurring=True, subscription_expiration_date=9000), 1000)
        accept_payment(
            self.db, 2, payment("charge-2", is_recurring=True, subscription_expiration_date=18000), 8000
        )
        self.assertEqual(self.db.one("SELECT expires FROM subscriptions")["expires"], 18000)

    def test_recurring_missing_expiration_rejected(self):
        invoice(self.db, recurring=1)
        with self.assertRaises(ValueError):
            accept_payment(self.db, 2, payment(is_recurring=True))

    def test_daily_reward_is_group_scoped_and_once(self):
        now = int(time.time())
        games.daily(self.db, CHAT, 2, now=now)
        balance = self.db.member(CHAT, 2)["coins"]
        games.daily(self.db, CHAT, 2, now=now)
        self.assertEqual(self.db.member(CHAT, 2)["coins"], balance)
        games.daily(self.db, CHAT - 1, 2, now=now)
        self.assertEqual(self.db.member(CHAT - 1, 2)["coins"], balance)

    def test_quiz_first_winner_and_one_attempt(self):
        self.db.execute(
            "INSERT INTO games VALUES('abc',?,'{\"answer\":1}',?,NULL)", (CHAT, int(time.time()) + 60)
        )
        self.assertIsNone(games.answer_quiz(self.db, "abc", 2, 0)[0])
        self.assertIsNone(games.answer_quiz(self.db, "abc", 2, 1)[0])
        self.assertEqual(games.answer_quiz(self.db, "abc", 3, 1)[0], CHAT)
        self.assertIsNone(games.answer_quiz(self.db, "abc", 4, 1)[0])
        self.assertEqual(self.db.member(CHAT, 3)["xp"], 25)

    def test_quota_atomic_and_separate_users(self):
        self.assertTrue(self.db.ai_quota(CHAT, 2, 2, 1, "2026-01-01"))
        self.assertFalse(self.db.ai_quota(CHAT, 2, 2, 1, "2026-01-01"))
        self.assertTrue(self.db.ai_quota(CHAT, 3, 2, 1, "2026-01-01"))
        self.assertFalse(self.db.ai_quota(CHAT, 4, 2, 1, "2026-01-01"))

    def test_tehran_midnight_not_utc_hour(self):
        before = int(datetime(2026, 11, 15, 20, 29, 59, tzinfo=timezone.utc).timestamp())
        after = before + 1
        self.db.message(CHAT, 1, 2, "before", "text", before)
        self.db.message(CHAT, 2, 3, "after", "text", after)
        text, totals = stats.report(self.db, CHAT, "day", datetime.fromtimestamp(after + 60, timezone.utc))
        self.assertEqual(totals["messages"], 1)
        self.assertIn("Active members: 1", text)

    def test_period_boundaries_leap_year_and_week(self):
        now = datetime(2024, 3, 1, 10, tzinfo=timezone.utc)
        _, _, start, end = stats.bounds("month", "Asia/Tehran", now, previous=True)
        self.assertEqual((start.month, start.day, end.month), (2, 1, 3))
        self.assertEqual((end - start).days, 29)
        _, _, start, _ = stats.bounds("week", "Asia/Tehran", now)
        self.assertEqual(start.weekday(), 5)
        _, _, start, end = stats.bounds("year", "Asia/Tehran", now, previous=True)
        self.assertEqual((start.year, end.year), (2023, 2024))

    def test_inline_data_within_64_bytes(self):
        conf = self.db.chat(CHAT)["settings"]
        for section in ("home", "mod", "learn", "content", "plans", "settings", "stats", "fun"):
            for row in admin_keyboard(-1009999999999, section, conf):
                for b in row:
                    self.assertLessEqual(len(b["callback_data"].encode()), 64)

    def test_completed_raw_updates_expire(self):
        self.db.execute("INSERT INTO inbox(id,payload,done,received) VALUES(1,'{}',1,100)")
        self.db.prune(14)
        self.assertEqual(self.db.all("SELECT * FROM inbox"), [])


class FakeTelegram:
    def __init__(self):
        self.calls = []
        self.sent = []
        self.admins = {1, 99}
        self.left = set()
        self.banned = set()
        self.fail_send = False
        self.fail_restrict = False
        self.permissions = {"can_send_messages": True, "can_send_photos": False}

    async def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
        if method == "getChatMember":
            user = kwargs["user_id"]
            status = (
                "administrator"
                if user in self.admins
                else "kicked"
                if user in self.banned
                else "left"
                if user in self.left
                else "member"
            )
            return {
                "status": status,
                "can_delete_messages": True,
                "can_restrict_members": True,
                "can_invite_users": True,
                "can_pin_messages": True,
                "can_post_messages": True,
            }
        if method == "getChat":
            return {
                "id": kwargs["chat_id"],
                "title": "test",
                "type": "supergroup",
                "permissions": self.permissions,
            }
        if method == "getChatMemberCount":
            return 12
        if method == "createChatInviteLink":
            return {"invite_link": "https://t.me/+test"}
        if method == "createInvoiceLink":
            return "https://t.me/$test"
        if method == "restrictChatMember" and self.fail_restrict:
            raise APIError(method, 503, "temporary")
        if method == "banChatMember":
            self.banned.add(kwargs["user_id"])
        if method == "unbanChatMember":
            self.banned.discard(kwargs["user_id"])
        return True

    async def send(self, chat, text, keyboard=None, **extra):
        if self.fail_send:
            raise APIError("sendMessage", 503, "temporary")
        self.sent.append((chat, text, keyboard))
        return {"message_id": len(self.sent), "chat": {"id": chat}}

    async def document(self, *args):
        self.calls.append(("document", args))


class BotFixture:
    async def asyncSetUp(self):
        self.db = DB(":memory:")
        seed(self.db)
        self.tg = FakeTelegram()
        self.config = Config(
            "123:test", owner_ids=(1,), support_username="Support", terms_url="https://example.org/terms"
        )
        self.bot = Bot(self.config, self.db, self.tg)

    async def asyncTearDown(self):
        await self.bot.close()
        self.db.close()

    def callback(self, user, data):
        return {
            "id": "query",
            "from": {"id": user},
            "data": data,
            "message": {"message_id": 1, "chat": {"id": CHAT}},
        }

    def message(self, user=2, text="سلام", mid=1):
        return {
            "message_id": mid,
            "chat": {"id": CHAT, "type": "supergroup", "title": "test"},
            "from": {"id": user, "first_name": "کاربر"},
            "text": text,
            "date": int(time.time()),
        }


class BotCase(BotFixture, unittest.IsolatedAsyncioTestCase):
    async def test_unmatched_confirmed_payment_preserved_for_review(self):
        update = {
            "update_id": 50,
            "message": {
                "message_id": 1,
                "date": int(time.time()),
                "chat": {"id": 2, "type": "private"},
                "from": {"id": 2},
                "successful_payment": payment(payload="missing-invoice"),
            },
        }
        self.db.execute("INSERT INTO inbox(id,payload) VALUES(50,?)", (json.dumps(update),))
        with self.assertLogs("tuxigap", level="ERROR"):
            await drain_once(self.bot, financial=True)
        stored = self.db.one("SELECT * FROM inbox WHERE id=50")
        self.assertEqual(stored["done"], 0)
        self.assertEqual(stored["attempts"], 1)
        self.assertIn("missing-invoice", stored["payload"])

    async def test_forged_admin_callback_rejected(self):
        with self.assertRaises(ValueError):
            await self.bot.callback(self.callback(2, f"a:{CHAT}:toggle:dry_run"))
        self.assertTrue(self.db.chat(CHAT)["settings"]["dry_run"])

    async def test_admin_demotion_rechecked(self):
        await self.bot.callback(self.callback(1, f"a:{CHAT}:toggle:links"))
        self.tg.admins.remove(1)
        with self.assertRaises(ValueError):
            await self.bot.callback(self.callback(1, f"a:{CHAT}:toggle:links"))
        self.assertTrue(self.db.chat(CHAT)["settings"]["links"])

    async def test_input_rights_rechecked(self):
        self.tg.admins.remove(1)
        with self.assertRaises(ValueError):
            await self.bot.save_input(1, CHAT, "words", "test")
        self.assertEqual(self.db.chat(CHAT)["settings"]["words"], [])

    async def test_dry_run_never_deletes_or_restricts(self):
        self.db.setting(CHAT, "words", ["تبلیغ"])
        await self.bot.message(self.message(text="تبلیغ"))
        self.assertFalse(
            any(
                method in ("deleteMessage", "restrictChatMember", "banChatMember")
                for method, _ in self.tg.calls
            )
        )
        self.assertEqual(self.db.member(CHAT, 2)["warns"], 0)

    async def test_auto_enforcement_and_warn_limit(self):
        self.db.setting(CHAT, "dry_run", False)
        self.db.setting(CHAT, "words", ["تبلیغ"])
        self.db.setting(CHAT, "warn_limit", 1)
        await self.bot.message(self.message(text="تبلیغ"))
        methods = [method for method, _ in self.tg.calls]
        self.assertIn("deleteMessage", methods)
        self.assertIn("restrictChatMember", methods)
        self.assertEqual(self.db.member(CHAT, 2)["warns"], 0)

    async def test_warn_retry_does_not_increment_twice(self):
        self.db.setting(CHAT, "warn_limit", 1)
        m = self.message(1, "/warn", 5)
        m["reply_to_message"] = self.message(2)
        self.tg.fail_restrict = True
        with self.assertRaises(APIError):
            await self.bot.command("warn", "", m)
        self.assertEqual(self.db.member(CHAT, 2)["warns"], 1)
        self.tg.fail_restrict = False
        await self.bot.command("warn", "", m)
        self.assertEqual(self.db.one("SELECT sum(n) n FROM hours WHERE metric='warns'")["n"], 1)
        await self.bot.command("warn", "", m)
        self.assertEqual(self.db.member(CHAT, 2)["warns"], 0)

    async def test_protected_admin_target(self):
        m = self.message(1, "/ban")
        m["reply_to_message"] = self.message(99)
        with self.assertRaises(ValueError):
            await self.bot.command("ban", "", m)
        self.assertNotIn("banChatMember", [method for method, _ in self.tg.calls])

    async def test_nonmember_cannot_read_group_profile(self):
        self.tg.left.add(2)
        with self.assertRaises(ValueError):
            await self.bot.fun(CHAT, 2, "top", CHAT)

    async def test_captcha_bound_to_user_and_default_permissions(self):
        self.db.execute("INSERT INTO captcha VALUES(?,?,?,?)", (CHAT, 2, "7", int(time.time()) + 100))
        with self.assertRaises(ValueError):
            await self.bot.solve_captcha(CHAT, 2, "7", 3, CHAT)
        await self.bot.solve_captcha(CHAT, 2, "7", 2, CHAT)
        restores = [data for method, data in self.tg.calls if method == "restrictChatMember"]
        self.assertEqual(restores[-1]["permissions"], self.tg.permissions)
        self.assertEqual(self.db.all("SELECT * FROM captcha"), [])

    async def test_badge_cannot_charge_twice(self):
        self.db.member(CHAT, 2)
        self.db.execute("UPDATE members SET coins=200 WHERE user=2")
        await self.bot.fun(CHAT, 2, "badge:100", CHAT)
        # Cooldown is separately enforced, then ownership prevents repeated debit.
        self.db.execute("DELETE FROM command_cooldown")
        await self.bot.fun(CHAT, 2, "badge:100", CHAT)
        self.assertEqual(self.db.member(CHAT, 2)["coins"], 100)

    async def test_precheckout_is_not_payment_and_forgery_rejected(self):
        invoice(self.db)
        self.db.execute("INSERT INTO plans(id,chat,name,stars,days) VALUES(1,?,'test',100,30)", (CHAT,))
        self.db.setting(CHAT, "paid_gate", True)
        query = {
            "id": "p",
            "from": {"id": 2},
            "invoice_payload": "invoice",
            "currency": "XTR",
            "total_amount": 100,
        }
        await self.bot.billing.precheckout(query)
        self.assertTrue(self.tg.calls[-1][1]["ok"])
        self.assertFalse(self.bot.billing.active(CHAT, 2))
        await self.bot.billing.precheckout(query | {"total_amount": 1})
        self.assertFalse(self.tg.calls[-1][1]["ok"])

    async def test_delivery_retry_preserves_entitlement(self):
        invoice(self.db)
        accept_payment(self.db, 2, payment())
        self.tg.fail_send = True
        await self.bot.billing.pending_deliveries()
        self.assertEqual(self.db.one("SELECT delivered FROM payments")["delivered"], 0)
        self.assertTrue(self.bot.billing.active(CHAT, 2))
        self.tg.fail_send = False
        await self.bot.billing.pending_deliveries()
        self.assertEqual(self.db.one("SELECT delivered FROM payments")["delivered"], 1)

    async def test_manual_ban_not_lifted_by_paid_renewal(self):
        self.db.setting(CHAT, "paid_gate", True)
        self.db.execute("INSERT INTO subscriptions VALUES(?,?,?,0)", (CHAT, 2, 100))
        self.tg.banned.add(2)
        await self.bot.billing.expire(self.bot.admin)
        self.assertEqual(self.db.one("SELECT expired_ban FROM subscriptions")["expired_ban"], 2)
        self.db.execute("UPDATE subscriptions SET expires=?", (int(time.time()) + 86400,))
        with self.assertRaises(ValueError):
            await self.bot.billing.access_link(CHAT, 2)
        self.assertNotIn("unbanChatMember", [method for method, _ in self.tg.calls])

    async def test_expiry_ban_and_renewal(self):
        self.db.setting(CHAT, "paid_gate", True)
        self.db.execute("INSERT INTO subscriptions VALUES(?,?,?,0)", (CHAT, 2, 100))
        await self.bot.billing.expire(self.bot.admin)
        self.assertIn(2, self.tg.banned)
        self.db.execute("UPDATE subscriptions SET expires=?", (int(time.time()) + 86400,))
        await self.bot.billing.access_link(CHAT, 2)
        self.assertNotIn(2, self.tg.banned)

    async def test_join_request_checks_purchaser(self):
        self.db.setting(CHAT, "paid_gate", True)
        self.db.execute("INSERT INTO subscriptions VALUES(?,?,?,0)", (CHAT, 2, int(time.time()) + 86400))
        for user in (2, 3):
            await self.bot.billing.join_request(
                {"chat": {"id": CHAT, "type": "supergroup", "title": "test"}, "from": {"id": user}}
            )
        methods = [method for method, _ in self.tg.calls]
        self.assertIn("approveChatJoinRequest", methods)
        self.assertIn("declineChatJoinRequest", methods)

    async def test_refund_retry_is_idempotent(self):
        invoice(self.db)
        accept_payment(self.db, 2, payment())
        await self.bot.billing.refund("charge-1")
        await self.bot.billing.refund("charge-1")
        self.assertEqual(len([m for m, _ in self.tg.calls if m == "refundStarPayment"]), 1)
        self.assertFalse(self.bot.billing.active(CHAT, 2))

    async def test_financial_lane_ignores_normal_backlog(self):
        query = {
            "update_id": 2,
            "pre_checkout_query": {
                "id": "p",
                "from": {"id": 2},
                "invoice_payload": "missing",
                "currency": "XTR",
                "total_amount": 1,
            },
        }
        self.db.execute(
            "INSERT INTO inbox(id,payload) VALUES(1,?)",
            (json.dumps({"update_id": 1, "message": self.message(text="/joke")}),),
        )
        self.db.execute("INSERT INTO inbox(id,payload) VALUES(2,?)", (json.dumps(query),))
        await drain_once(self.bot, financial=True)
        self.assertEqual(self.db.one("SELECT done FROM inbox WHERE id=1")["done"], 0)
        self.assertEqual(self.db.one("SELECT done FROM inbox WHERE id=2")["done"], 1)

    async def test_reports_deduplicate_completed_periods(self):
        self.db.setting(CHAT, "reports", True)
        now = int(datetime(2026, 11, 16, 12, tzinfo=timezone.utc).timestamp())
        await reports(self.bot, now)
        count = len(self.tg.sent)
        self.assertEqual(count, 4)
        await reports(self.bot, now)
        self.assertEqual(len(self.tg.sent), count)

    async def test_scheduled_post_cancelled_if_creator_demoted(self):
        self.db.execute("INSERT INTO jobs(chat,creator,due,text) VALUES(?,?,?,?)", (CHAT, 2, 100, "post"))
        await scheduled_posts(self.bot, 200)
        self.assertEqual(self.db.one("SELECT state FROM jobs")["state"], "cancelled")
        self.assertEqual(self.tg.sent, [])

    async def test_inline_member_action_authorized_and_idempotent(self):
        forged = self.callback(2, f"u:{CHAT}:3:warn:5")
        with self.assertRaises(ValueError):
            await self.bot.callback(forged)
        legitimate = self.callback(1, f"u:{CHAT}:2:warn:5")
        await self.bot.callback(legitimate)
        await self.bot.callback(legitimate)
        self.assertEqual(self.db.member(CHAT, 2)["warns"], 1)

    async def test_notes_and_normalized_autoresponder(self):
        await self.bot.save_input(1, CHAT, "note", "راهنما | متن راهنما")
        await self.bot.save_input(1, CHAT, "filter", "كتاب | پاسخ فارسی")
        await self.bot.message(self.message(text="کتاب"))
        self.assertEqual(self.tg.sent[-1][1], "پاسخ فارسی")
        await self.bot.command("get", "راهنما", self.message())
        self.assertEqual(self.tg.sent[-1][1], "متن راهنما")
        await self.bot.save_input(1, CHAT, "filter", "کتاب | -")
        self.assertEqual(self.db.all("SELECT * FROM filters"), [])

    async def test_forget_removes_subject_training_samples(self):
        self.db.train(CHAT, "نمونهٔ آموزش متعلق به کاربر", "spam", 1, subject=2)
        await self.bot.callback(self.callback(2, "forget:2"))
        self.assertEqual(self.db.all("SELECT * FROM samples"), [])

    async def test_gate_ban_is_recoverable_after_purchase(self):
        await self.bot.billing.gate_ban(CHAT, 2)
        self.assertIn(2, self.tg.banned)
        invoice(self.db)
        accept_payment(self.db, 2, payment())
        await self.bot.billing.access_link(CHAT, 2)
        self.assertNotIn(2, self.tg.banned)

    async def test_renewal_arriving_during_expiry_request(self):
        self.db.setting(CHAT, "paid_gate", True)
        self.db.execute("INSERT INTO subscriptions VALUES(?,?,0,0)", (CHAT, 2))
        invoice(self.db)
        original = self.tg.call

        async def renewal_during_ban(method, **data):
            result = await original(method, **data)
            if method == "banChatMember":
                accept_payment(self.db, 2, payment())
            return result

        self.tg.call = renewal_during_ban
        await self.bot.billing.expire(self.bot.admin)
        self.assertTrue(self.bot.billing.active(CHAT, 2))
        self.assertNotIn(2, self.tg.banned)

    async def test_recurring_refund_cancels_future_billing(self):
        invoice(self.db, recurring=1)
        accept_payment(
            self.db, 2, payment(is_recurring=True, subscription_expiration_date=int(time.time()) + 86400)
        )
        await self.bot.billing.refund("charge-1")
        methods = [m for m, _ in self.tg.calls]
        self.assertLess(methods.index("editUserStarSubscription"), methods.index("refundStarPayment"))
        self.assertEqual(self.db.one("SELECT cancelled FROM invoices")["cancelled"], 1)

    async def test_cancel_recurring_bound_to_purchaser(self):
        invoice(self.db, recurring=1)
        accept_payment(
            self.db, 2, payment(is_recurring=True, subscription_expiration_date=int(time.time()) + 86400)
        )
        rid = self.db.one("SELECT rowid rid FROM payments")["rid"]
        with self.assertRaises(ValueError):
            await self.bot.callback(self.callback(3, f"cancelrec:{rid}"))
        await self.bot.callback(self.callback(2, f"cancelrec:{rid}"))
        await self.bot.callback(self.callback(2, f"cancelrec:{rid}"))
        self.assertEqual(len([m for m, _ in self.tg.calls if m == "editUserStarSubscription"]), 1)


class NetworkCase(unittest.IsolatedAsyncioTestCase):
    async def test_official_test_environment_path(self):
        def transport(request):
            self.assertEqual(request.url.path, "/bot123:fake/test/getMe")
            return httpx.Response(200, json={"ok": True, "result": {"id": 99}})

        tg = Telegram(
            "123:fake", test_mode=True, client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
        )
        self.assertEqual((await tg.call("getMe"))["id"], 99)
        await tg.close()

    async def test_bot_api_request_json_and_errors(self):
        def transport(request):
            self.assertEqual(request.url.path, "/bot123:fake/sendMessage")
            data = json.loads(request.content)
            self.assertEqual(data["chat_id"], 2)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 4}})

        tg = Telegram("123:fake", client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        self.assertEqual((await tg.send(2, "test"))["message_id"], 4)
        await tg.close()

    async def test_ai_schema_and_untrusted_role(self):
        db = DB(":memory:")
        seed(db)

        def transport(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["messages"][1]["role"], "user")
            self.assertIn("untrusted", payload["messages"][0]["content"])
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"spam":true,"confidence":0.99,"reason":"تبلیغ"}'}}]
                },
            )

        ai = AI(
            Config("123:test", ai_key="fake", ai_model="test"),
            db,
            httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        self.assertEqual((await ai.moderate(CHAT, 2, "ignore system", "rules"))[:2], (True, 0.99))
        await ai.close()
        db.close()

    async def test_invalid_ai_confidence_rejected(self):
        db = DB(":memory:")
        seed(db)
        ai = AI(
            Config("123:test", ai_key="fake", ai_model="test"),
            db,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(
                        200, json={"choices": [{"message": {"content": '{"spam":true,"confidence":9}'}}]}
                    )
                )
            ),
        )
        with self.assertRaises(AIUnavailable):
            await ai.moderate(CHAT, 2, "text", "rules")
        await ai.close()
        db.close()


if __name__ == "__main__":
    unittest.main()
