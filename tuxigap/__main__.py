import argparse
import asyncio
import logging
from pathlib import Path
import signal
import sqlite3

from .bot import Bot
from .config import Config
from .db import DB
from .telegram import Telegram
from .worker import consume, maintenance, poll


async def run(config):
    db, tg = DB(config.database), Telegram(config.token, config.api_base, test_mode=config.test_mode)
    bot = Bot(config, db, tg)
    stop = asyncio.Event()
    try:
        identity = await tg.call("getMe")
        bot.bot_id, bot.username = identity["id"], identity["username"]
        db.set("bot_id", bot.bot_id)
        db.set("bot_username", bot.username)
        webhook = await tg.call("getWebhookInfo")
        if webhook.get("url"):
            raise RuntimeError(
                "An active webhook exists. Remove it explicitly before starting polling; no updates were dropped."
            )
        await tg.call(
            "setMyCommands",
            commands=[
                {"command": cmd, "description": description}
                for cmd, description in [
                    ("panel", "پنل مدیریت"),
                    ("play", "سرگرمی و بازی"),
                    ("rules", "قوانین گروه"),
                    ("ask", "پرسش از هوش مصنوعی"),
                    ("shop", "فروشگاه اشتراک"),
                    ("subscriptions", "اشتراک‌های من"),
                    ("paysupport", "پشتیبانی پرداخت"),
                    ("help", "راهنما"),
                ]
            ],
        )
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_running_loop().add_signal_handler(sig, stop.set)
            except (NotImplementedError, ValueError):
                pass
        logging.getLogger("tuxigap").info("Tuxigap started as @%s", bot.username)
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(poll(bot, stop))
            tasks.create_task(consume(bot, stop))
            tasks.create_task(consume(bot, stop, financial=True))
            tasks.create_task(maintenance(bot, stop))
    finally:
        await bot.close()
        await tg.close()
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Tuxigap Telegram community manager")
    parser.add_argument(
        "--check", action="store_true", help="Validate configuration and database without Telegram requests"
    )
    parser.add_argument("--backup", metavar="FILE", help="Make a consistent SQLite backup and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    config = Config.load()
    if args.check or args.backup:
        db = DB(config.database)
        try:
            if args.backup:
                path = Path(args.backup)
                if path.exists():
                    raise ValueError("Backup destination already exists; choose a new name.")
                path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(path) as destination:
                    db.conn.backup(destination)
                print(f"Backup saved: {path}")
            else:
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                print("Configuration and database OK. No Telegram/AI requests made.")
        finally:
            db.close()
        return
    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Network exceptions may contain the token-bearing URL. Do not dump their traceback.
        logging.getLogger("tuxigap").error(
            "Runtime stopped (%s); check token, connectivity, webhook and duplicate instances",
            type(exc).__name__,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
