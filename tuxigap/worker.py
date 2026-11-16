"""Persistent update inbox and periodic jobs; one polling process per bot token."""

import asyncio
from datetime import datetime, timezone
import json
import logging
import time
from zoneinfo import ZoneInfo

import httpx

from . import stats
from .telegram import APIError

log = logging.getLogger("tuxigap")
ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "callback_query",
    "inline_query",
    "my_chat_member",
    "chat_member",
    "chat_join_request",
    "message_reaction",
    "pre_checkout_query",
]


async def poll(bot, stop):
    tg, db = bot.tg, bot.db
    offset = db.get("poll_offset", 0)
    while not stop.is_set():
        try:
            updates = await tg.call(
                "getUpdates", offset=offset, timeout=25, allowed_updates=ALLOWED_UPDATES, limit=100
            )
            with db.transaction():
                for update in updates:
                    db.execute(
                        "INSERT OR IGNORE INTO inbox(id,payload) VALUES(?,?)",
                        (update["update_id"], json.dumps(update)),
                    )
                    offset = max(offset, update["update_id"] + 1)
                db.set("poll_offset", offset)
        except (httpx.HTTPError, APIError) as exc:
            if isinstance(exc, APIError) and exc.code in (401, 409):
                log.error("Polling rejected (%s): check token, webhook and duplicate processes", exc.code)
                stop.set()
                raise RuntimeError("Polling cannot start; see log") from None
            log.warning("Polling network/API failure (%s)", type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=3)
            except TimeoutError:
                pass


async def drain_once(bot, financial=False):
    db = bot.db
    # Payments/precheckout have deadlines; do not leave them behind slow AI work.
    money = "(json_type(payload,'$.pre_checkout_query') IS NOT NULL OR json_type(payload,'$.message.successful_payment') IS NOT NULL OR json_type(payload,'$.message.refunded_payment') IS NOT NULL)"
    lane = money if financial else "NOT " + money
    rows = db.all(
        "SELECT * FROM inbox WHERE done=0 AND next_try<=? AND "
        + lane
        + " ORDER BY CASE WHEN json_type(payload,'$.pre_checkout_query') IS NOT NULL THEN 0 ELSE 1 END,id LIMIT 20",
        (int(time.time()),),
    )
    for row in rows:
        try:
            await bot.safe_handle(json.loads(row["payload"]))
            db.execute("UPDATE inbox SET done=1 WHERE id=?", (row["id"],))
        except (httpx.HTTPError, APIError):
            attempts = row["attempts"] + 1
            db.execute(
                "UPDATE inbox SET attempts=?,next_try=? WHERE id=?",
                (attempts, int(time.time()) + min(300, 2 ** min(attempts, 8)), row["id"]),
            )
            log.warning("Update %s failed; retry %s scheduled", row["id"], attempts)
        except Exception as exc:
            # Preserve poisoned updates for investigation instead of deleting payments.
            attempts = row["attempts"] + 1
            db.execute(
                "UPDATE inbox SET attempts=?,next_try=? WHERE id=?",
                (attempts, int(time.time()) + 300, row["id"]),
            )
            log.error("Update %s unexpected %s; preserved for retry", row["id"], type(exc).__name__)


async def consume(bot, stop, financial=False):
    while not stop.is_set():
        await drain_once(bot, financial)
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.2)
        except TimeoutError:
            pass


async def scheduled_posts(bot, now):
    for job in bot.db.all(
        "SELECT * FROM jobs WHERE state='pending' AND due<=? ORDER BY due LIMIT 10", (now,)
    ):
        try:
            right = "can_post_messages" if bot.db.chat(job["chat"])["kind"] == "channel" else None
            if not await bot.admin(job["chat"], job["creator"], right):
                bot.db.execute("UPDATE jobs SET state='cancelled' WHERE id=?", (job["id"],))
                continue
            from html import escape

            await bot.tg.send(job["chat"], escape(job["text"]))
            bot.db.execute("UPDATE jobs SET state='sent' WHERE id=?", (job["id"],))
        except (APIError, httpx.HTTPError):
            attempts = job["attempts"] + 1
            bot.db.execute(
                "UPDATE jobs SET attempts=?,due=?,state=? WHERE id=?",
                (
                    attempts,
                    now + min(3600, 30 * 2 ** min(attempts, 6)),
                    "failed" if attempts >= 10 else "pending",
                    job["id"],
                ),
            )


async def reports(bot, now):
    dt = datetime.fromtimestamp(now, timezone.utc)
    for row in bot.db.all("SELECT id FROM chats"):
        chat = bot.db.chat(row["id"])
        c = chat["settings"]
        if not c["enabled"] or not c["reports"]:
            continue
        local = dt.astimezone(ZoneInfo(c["timezone"]))
        if local.hour < c["report_hour"]:
            continue
        # Latest completed periods catch up after downtime; the durable log deduplicates them.
        periods = ["day", "week", "month", "year"]
        for period in periods:
            start, _, _, _ = stats.bounds(period, c["timezone"], dt, True, c["week_start"])
            if bot.db.one(
                "SELECT 1 FROM report_log WHERE chat=? AND period=? AND start=?", (chat["id"], period, start)
            ):
                continue
            try:
                await bot.send_stats(chat["id"], chat["id"], period, dt, True)
                bot.db.execute("INSERT OR IGNORE INTO report_log VALUES(?,?,?)", (chat["id"], period, start))
            except (APIError, httpx.HTTPError):
                continue


async def captcha_expiry(bot, now):
    for c in bot.db.all("SELECT * FROM captcha WHERE expires<? LIMIT 50", (now,)):
        try:
            if not await bot.admin(c["chat"], c["user"]):
                await bot.tg.call("banChatMember", chat_id=c["chat"], user_id=c["user"], until_date=now + 60)
                bot.db.bump(c["chat"], "bans")
            bot.db.execute("DELETE FROM captcha WHERE chat=? AND user=?", (c["chat"], c["user"]))
        except (APIError, httpx.HTTPError):
            continue


async def maintenance(bot, stop):
    last_prune = 0
    while not stop.is_set():
        now = int(time.time())
        bot.db.set("heartbeat", now)
        try:
            await bot.billing.pending_deliveries()
            await bot.engine.flush()
            await bot.community.enforce_federations(now)
            await bot.growth.draw(now)
            await bot.billing.expire(bot.admin)
            await captcha_expiry(bot, now)
            await scheduled_posts(bot, now)
            await reports(bot, now)
            if now - last_prune > 3600:
                bot.db.prune(bot.config.retention_days, now)
                last_prune = now
        except (APIError, httpx.HTTPError) as exc:
            log.warning("Maintenance network/API failure (%s)", type(exc).__name__)
        except Exception as exc:
            log.error("Maintenance failed (%s)", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            pass
