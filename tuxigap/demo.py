"""Try the owner dashboard with synthetic data. No Telegram/AI/payment requests."""

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import secrets
import tempfile
import time

from .config import Config
from .dashboard import make_handler
from .db import DB


def populate(path):
    db = DB(str(path))
    chat = -100100100
    db.register({"id": chat, "title": "Tuxigap Community · Demo", "type": "supergroup"})
    db.setting(chat, "dry_run", True)
    for user, name in [(1, "Alex"), (2, "Sam"), (3, "Noor"), (4, "Lin")]:
        db.member(chat, user, name)
        db.execute(
            "UPDATE members SET xp=?,coins=? WHERE chat=? AND user=?", (user * 130, user * 70, chat, user)
        )
    now = int(time.time())
    for days in range(365):
        ts = now - days * 86400
        db.bump(chat, "messages", 15 + (days % 17), ts)
        db.bump(chat, "text", 12 + (days % 13), ts)
        db.bump(chat, "media", 3, ts)
        if days % 7 == 0:
            db.bump(chat, "joins", 2, ts)
        for user in range(1, 5):
            db.execute(
                "INSERT OR REPLACE INTO activity VALUES(?,?,?,?)", (chat, ts // 60 * 60, user, 2 + user)
            )
    for metric, amount in [("flagged", 8), ("deleted", 5), ("warns", 3), ("games", 12), ("referrals", 7)]:
        db.bump(chat, metric, amount, now)
    db.execute(
        "INSERT INTO notes VALUES(?,?,?)",
        (chat, "welcome", "Be kind, share what you learn, and help each other grow. 🌷"),
    )
    db.audit(chat, 3, 100, 1, "feedback", "An admin marked a message safe.")
    db.audit(chat, 2, 101, 1, "setting", "Dry run is enabled while we settle in.")
    db.train(chat, "A friendly example that belongs in our community.", "ham", 1)
    db.close()


def main():
    parser = argparse.ArgumentParser(description="Take Tuxigap for a friendly, offline test drive.")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tuxigap-demo-") as directory:
        path = Path(directory) / "demo.sqlite3"
        populate(path)
        token = secrets.token_urlsafe(32)
        config = Config("0:demo", database=str(path))
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(config, token))
        print(f"Tuxigap demo: http://127.0.0.1:{server.server_port}", flush=True)
        print(f"Demo owner key: {token}", flush=True)
        print(
            "All data is synthetic. Nothing contacts Telegram, AI, or a payment service. Ctrl+C to finish.",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
