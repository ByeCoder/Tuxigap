"""Optional authenticated integration with the real tg-spam HTTP detector.

One endpoint per group preserves isolation. Telegram polling remains owned by Tuxigap.
"""

from .i18n import tr

import json
import time

import httpx


class SpamEngine:
    def __init__(self, config, db, client=None):
        self.config, self.db, self.client = config, db, client
        raw = json.loads(config.spam_engines or "{}")
        if not isinstance(raw, dict):
            raise ValueError(tr("m_df862d7df4b7"))
        self.urls = {int(chat): str(url).rstrip("/") for chat, url in raw.items()}
        if len(set(self.urls.values())) != len(self.urls):
            raise ValueError(tr("m_539538334c1b"))
        for url in self.urls.values():
            if not url.startswith(("http://", "https://")):
                raise ValueError(tr("m_712673873b3e"))
        if self.urls and not config.spam_engine_password:
            raise ValueError(tr("m_55bc9ecfe8fe"))

    async def request(self, chat, path, data):
        if chat not in self.urls:
            return None
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=5)
        response = await self.client.post(
            self.urls[chat] + path,
            json=data,
            auth=httpx.BasicAuth("tg-spam", self.config.spam_engine_password),
        )
        response.raise_for_status()
        return response.json()

    async def check(self, chat, user, text, username=""):
        if chat not in self.urls:
            return False
        try:
            result = await self.request(
                chat, "/check", {"msg": text[:4000], "user_id": str(user), "user_name": username}
            )
            if not isinstance(result, dict) or not isinstance(result.get("spam"), bool):
                return False
            self.db.bump(chat, "engine_calls")
            return result["spam"]
        except (httpx.HTTPError, ValueError):
            self.db.bump(chat, "engine_errors")
            return False

    def train(self, chat, text, label):
        if chat not in self.urls or label not in ("spam", "ham"):
            return
        self.db.execute(
            "INSERT INTO engine_outbox(chat,text,label,due) VALUES(?,?,?,?)",
            (chat, text[:4000], label, int(time.time())),
        )

    async def flush(self):
        for row in self.db.all(
            "SELECT * FROM engine_outbox WHERE due<=? ORDER BY id LIMIT 20", (int(time.time()),)
        ):
            if row["chat"] not in self.urls:
                continue
            try:
                await self.request(row["chat"], "/update/" + row["label"], {"msg": row["text"]})
                self.db.execute("DELETE FROM engine_outbox WHERE id=?", (row["id"],))
            except (httpx.HTTPError, ValueError):
                self.db.execute(
                    "UPDATE engine_outbox SET due=? WHERE id=?", (int(time.time()) + 300, row["id"])
                )

    async def close(self):
        if self.client is not None:
            await self.client.aclose()
