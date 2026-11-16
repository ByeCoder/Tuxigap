"""Stars-only access ledger. Never trust callback prices or pre-checkout as payment."""

from datetime import datetime
from html import escape
import secrets
import time
from zoneinfo import ZoneInfo

import httpx

from .telegram import APIError


class PaymentNeedsReview(Exception):
    """A confirmed payment could not be reconciled; preserve its raw inbox update."""


def recompute(db, chat, user):
    expiry = 0
    for payment in db.all(
        "SELECT * FROM payments WHERE chat=? AND user=? AND refunded=0 ORDER BY paid_at,charge", (chat, user)
    ):
        if payment["period_end"]:
            expiry = max(expiry, payment["period_end"])
        else:
            expiry = max(expiry, payment["paid_at"]) + payment["days"] * 86400
    db.execute(
        "INSERT INTO subscriptions(chat,user,expires) VALUES(?,?,?) ON CONFLICT(chat,user) DO UPDATE SET expires=excluded.expires",
        (chat, user, expiry),
    )
    return expiry


def accept_payment(db, user, successful, paid_at=None):
    """Atomic deduplication + entitlement. Return None for duplicate delivery."""
    paid_at = int(time.time()) if paid_at is None else paid_at
    invoice = db.one("SELECT * FROM invoices WHERE payload=?", (successful["invoice_payload"],))
    if (
        not invoice
        or invoice["user"] != user
        or successful.get("currency") != "XTR"
        or successful["total_amount"] != invoice["stars"]
    ):
        raise ValueError("Payment does not match the server-side invoice")
    recurring = bool(invoice["recurring"])
    if recurring and (
        not successful.get("is_recurring")
        or not isinstance(successful.get("subscription_expiration_date"), int)
    ):
        raise ValueError("Missing recurring subscription expiration")
    charge = successful["telegram_payment_charge_id"]
    with db.transaction():
        if db.one("SELECT charge FROM payments WHERE charge=?", (charge,)):
            return None
        if invoice["paid"] and not recurring:
            raise ValueError("Fixed invoice was already paid")
        db.execute(
            "INSERT INTO payments(charge,payload,user,chat,stars,days,paid_at,period_end) VALUES(?,?,?,?,?,?,?,?)",
            (
                charge,
                invoice["payload"],
                user,
                invoice["chat"],
                invoice["stars"],
                invoice["days"],
                paid_at,
                successful.get("subscription_expiration_date", 0) if recurring else 0,
            ),
        )
        db.execute("UPDATE invoices SET paid=1 WHERE payload=?", (invoice["payload"],))
        expiry = recompute(db, invoice["chat"], user)
    return invoice["chat"], expiry, charge


def mark_refunded(db, charge):
    with db.transaction():
        payment = db.one("SELECT * FROM payments WHERE charge=?", (charge,))
        if not payment:
            raise ValueError("تراکنش پیدا نشد.")
        db.execute("UPDATE payments SET refunded=1 WHERE charge=?", (charge,))
        recompute(db, payment["chat"], payment["user"])


class Billing:
    def __init__(self, db, tg, config):
        self.db, self.tg, self.config = db, tg, config

    async def invoice(self, user, plan_id):
        p = self.db.one("SELECT * FROM plans WHERE id=? AND enabled=1", (plan_id,))
        if not p or not self.db.chat(p["chat"])["settings"]["paid_gate"]:
            raise ValueError("این طرح فعلاً قابل خرید نیست.")
        if not self.config.support_username or not self.config.terms_url:
            raise ValueError("مدیر باید SUPPORT_USERNAME و TERMS_URL را پیش از فروش تنظیم کند.")
        chat_info = await self.tg.call("getChat", chat_id=p["chat"])
        if chat_info.get("username"):
            raise ValueError("فروش دسترسی فقط برای گروه یا کانال خصوصی فعال است.")
        bot_member = await self.tg.call("getChatMember", chat_id=p["chat"], user_id=self.db.get("bot_id"))
        if bot_member.get("status") != "administrator" or not all(
            bot_member.get(r) for r in ("can_invite_users", "can_restrict_members")
        ):
            raise ValueError("ربات باید مجوز دعوت و محدودسازی عضو داشته باشد.")
        # Prevent accidentally starting multiple concurrent recurring memberships.
        active = self.db.one(
            "SELECT * FROM subscriptions WHERE chat=? AND user=? AND expires>?",
            (p["chat"], user, int(time.time())),
        )
        if p["recurring"] and active:
            raise ValueError("اشتراک فعال دارید؛ برای تغییر طرح با پشتیبانی تماس بگیرید.")
        payload = secrets.token_urlsafe(20)
        self.db.execute(
            "INSERT INTO invoices(payload,user,chat,plan,stars,days,recurring,created) VALUES(?,?,?,?,?,?,?,?)",
            (payload, user, p["chat"], p["id"], p["stars"], p["days"], p["recurring"], int(time.time())),
        )
        params = dict(
            title=p["name"][:32],
            description=f"دسترسی {p['days']} روزه به {self.db.chat(p['chat'])['title']}"[:255],
            payload=payload,
            currency="XTR",
            prices=[{"label": p["name"][:32], "amount": p["stars"]}],
        )
        if p["recurring"]:
            url = await self.tg.call("createInvoiceLink", **params, subscription_period=2592000)
            await self.tg.send(
                user,
                "اشتراک هر ۳۰ روز به‌صورت خودکار تمدید می‌شود؛ لغو تمدید از «اشتراک‌های من».",
                [[{"text": "پرداخت اشتراک دوره‌ای ⭐", "url": url}]],
            )
        else:
            await self.tg.call("sendInvoice", chat_id=user, **params, start_parameter="shop")

    async def precheckout(self, query):
        p = self.db.one("SELECT * FROM invoices WHERE payload=?", (query["invoice_payload"],))
        ok = bool(
            p
            and p["user"] == query["from"]["id"]
            and query["currency"] == "XTR"
            and query["total_amount"] == p["stars"]
            and not p["cancelled"]
            and (p["recurring"] or not p["paid"])
            and (p["recurring"] and p["paid"] or int(time.time()) - p["created"] < 900)
        )
        if ok:
            ok = bool(
                self.db.chat(p["chat"])["settings"]["paid_gate"]
                and self.db.one("SELECT id FROM plans WHERE id=? AND enabled=1", (p["plan"],))
            )
        if ok and p["recurring"] and not p["paid"] and self.active(p["chat"], p["user"]):
            ok = False
        await self.tg.call(
            "answerPreCheckoutQuery",
            pre_checkout_query_id=query["id"],
            ok=ok,
            **(
                {}
                if ok
                else {"error_message": "صورت‌حساب معتبر نیست یا منقضی شده؛ از فروشگاه دوباره اقدام کنید."}
            ),
        )

    def active(self, chat, user):
        sub = self.db.one("SELECT * FROM subscriptions WHERE chat=? AND user=?", (chat, user))
        return bool(sub and sub["expires"] > time.time())

    async def access_link(self, chat, user):
        if not self.active(chat, user):
            raise ValueError("اشتراک فعال ندارید.")
        sub = self.db.one("SELECT * FROM subscriptions WHERE chat=? AND user=?", (chat, user))
        if sub["expired_ban"] == 1:
            await self.tg.call("unbanChatMember", chat_id=chat, user_id=user, only_if_banned=True)
            self.db.execute("UPDATE subscriptions SET expired_ban=0 WHERE chat=? AND user=?", (chat, user))
        member = await self.tg.call("getChatMember", chat_id=chat, user_id=user)
        if member.get("status") == "kicked":
            raise ValueError(
                "مدیر شما را مسدود کرده است؛ پرداخت، مسدودی دستی را لغو نمی‌کند. با پشتیبانی تماس بگیرید."
            )
        invite = await self.tg.call(
            "createChatInviteLink",
            chat_id=chat,
            creates_join_request=True,
            expire_date=int(time.time()) + 86400,
            name=f"paid-{user}"[:32],
        )
        tz = self.db.chat(chat)["settings"]["timezone"]
        end = datetime.fromtimestamp(sub["expires"], ZoneInfo(tz))
        await self.tg.send(
            user,
            f"✅ دسترسی تا {end:%Y-%m-%d %H:%M} فعال است. لینک درخواست عضویت یک روز معتبر است؛ فقط خریدار تأیید می‌شود.",
            [[{"text": "درخواست ورود", "url": invite["invite_link"]}]],
        )

    async def pending_deliveries(self):
        for p in self.db.all("SELECT * FROM payments WHERE delivered=0 AND refunded=0 LIMIT 20"):
            try:
                if self.active(p["chat"], p["user"]):
                    await self.access_link(p["chat"], p["user"])
                self.db.execute("UPDATE payments SET delivered=1 WHERE charge=?", (p["charge"],))
            except (APIError, ValueError, httpx.HTTPError):
                # Keep the entitlement and retry link delivery; never charge again.
                if not p["notice_sent"]:
                    for owner in self.config.owner_ids:
                        try:
                            await self.tg.send(
                                owner,
                                f"⚠️ تحویل دسترسی پرداخت {escape(p['charge'])} نیاز به بررسی دارد؛ گروه {p['chat']}، کاربر {p['user']}.",
                            )
                        except (APIError, httpx.HTTPError):
                            pass
                    self.db.execute("UPDATE payments SET notice_sent=1 WHERE charge=?", (p["charge"],))

    async def expire(self, is_admin):
        for s in self.db.all(
            "SELECT * FROM subscriptions WHERE expires<=? AND expired_ban=0 LIMIT 50", (int(time.time()),)
        ):
            if not self.db.chat(s["chat"])["settings"]["paid_gate"]:
                continue
            try:
                if await is_admin(s["chat"], s["user"]):
                    continue
                member = await self.tg.call("getChatMember", chat_id=s["chat"], user_id=s["user"])
                # A renewal can arrive while either awaited permission request is in flight.
                if self.active(s["chat"], s["user"]):
                    continue
                if member["status"] == "kicked":
                    # A pre-existing manual ban must never be lifted by a later renewal.
                    self.db.execute(
                        "UPDATE subscriptions SET expired_ban=2 WHERE chat=? AND user=?",
                        (s["chat"], s["user"]),
                    )
                    continue
                if member["status"] != "kicked":
                    await self.tg.call("banChatMember", chat_id=s["chat"], user_id=s["user"])
                if self.active(s["chat"], s["user"]):
                    await self.tg.call(
                        "unbanChatMember", chat_id=s["chat"], user_id=s["user"], only_if_banned=True
                    )
                    continue
                self.db.execute(
                    "UPDATE subscriptions SET expired_ban=1 WHERE chat=? AND user=?", (s["chat"], s["user"])
                )
            except (APIError, httpx.HTTPError):
                continue

    async def gate_ban(self, chat, user):
        if self.active(chat, user):
            return
        await self.tg.call("banChatMember", chat_id=chat, user_id=user)
        if self.active(chat, user):
            await self.tg.call("unbanChatMember", chat_id=chat, user_id=user, only_if_banned=True)
            return
        self.db.execute(
            "INSERT INTO subscriptions VALUES(?,?,0,1) ON CONFLICT(chat,user) DO UPDATE SET expired_ban=1",
            (chat, user),
        )

    async def refund(self, charge):
        p = self.db.one("SELECT * FROM payments WHERE charge=?", (charge,))
        if not p:
            raise ValueError("تراکنش پیدا نشد.")
        if not p["refunded"]:
            inv = self.db.one("SELECT * FROM invoices WHERE payload=?", (p["payload"],))
            if inv["recurring"] and not inv["cancelled"]:
                await self.tg.call(
                    "editUserStarSubscription",
                    user_id=p["user"],
                    telegram_payment_charge_id=charge,
                    is_canceled=True,
                )
                self.db.execute("UPDATE invoices SET cancelled=1 WHERE payload=?", (p["payload"],))
            try:
                await self.tg.call("refundStarPayment", user_id=p["user"], telegram_payment_charge_id=charge)
            except APIError as exc:
                if "CHARGE_ALREADY_REFUNDED" not in exc.description.upper():
                    raise
            mark_refunded(self.db, charge)

    async def join_request(self, request):
        chat, user = request["chat"]["id"], request["from"]["id"]
        self.db.register(request["chat"])
        if not self.db.chat(chat)["settings"]["paid_gate"]:
            return
        await self.tg.call(
            "approveChatJoinRequest" if self.active(chat, user) else "declineChatJoinRequest",
            chat_id=chat,
            user_id=user,
        )
