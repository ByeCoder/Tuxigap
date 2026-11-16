import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest

import httpx

from tuxigap.config import Config
from tuxigap.dashboard import make_handler
from tuxigap.db import DB
from tuxigap.engines import SpamEngine
from test_core import BotFixture, CHAT, seed


class EngineCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB(":memory:")
        seed(self.db)

    async def asyncTearDown(self):
        self.db.close()

    async def test_real_engine_http_contract(self):
        seen = []

        def transport(request):
            self.assertTrue(request.headers["authorization"].startswith("Basic "))
            body = json.loads(request.content)
            seen.append(request.url.path)
            if request.url.path == "/check":
                self.assertEqual(body["user_id"], "2")
                return httpx.Response(200, json={"spam": True, "checks": []})
            self.assertEqual(body["msg"], "training text")
            return httpx.Response(200, json={"ok": True})

        config = Config(
            "123:fake", spam_engines=json.dumps({CHAT: "http://engine:8080"}), spam_engine_password="secret"
        )
        engine = SpamEngine(config, self.db, httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        self.assertTrue(await engine.check(CHAT, 2, "spam text"))
        engine.train(CHAT, "training text", "spam")
        await engine.flush()
        self.assertEqual(seen, ["/check", "/update/spam"])
        self.assertEqual(self.db.all("SELECT * FROM engine_outbox"), [])
        await engine.close()

    async def test_unavailable_engine_does_not_flag_user(self):
        config = Config(
            "123:fake", spam_engines=json.dumps({CHAT: "http://engine"}), spam_engine_password="secret"
        )
        engine = SpamEngine(
            config, self.db, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
        )
        self.assertFalse(await engine.check(CHAT, 2, "valid"))
        self.assertEqual(self.db.one("SELECT n FROM hours WHERE metric='engine_errors'")["n"], 1)
        await engine.close()

    async def test_groups_cannot_accidentally_share_training_backend(self):
        config = Config(
            "123:fake",
            spam_engines=json.dumps({CHAT: "http://engine", CHAT - 1: "http://engine"}),
            spam_engine_password="secret",
        )
        with self.assertRaises(ValueError):
            SpamEngine(config, self.db)


class GrowthCase(BotFixture, unittest.IsolatedAsyncioTestCase):
    async def test_referral_reward_once_and_no_self_referral(self):
        self.db.execute("INSERT INTO invite_links VALUES(?,?,?)", (CHAT, 2, "test-link"))
        self.assertFalse(self.bot.growth.record_join(CHAT, 2, "test-link"))
        self.assertFalse(self.bot.growth.record_join(CHAT, 3, "test-link", False))
        self.assertTrue(self.bot.growth.record_join(CHAT, 3, "test-link"))
        self.assertFalse(self.bot.growth.record_join(CHAT, 3, "test-link"))
        self.assertEqual(self.db.member(CHAT, 2)["coins"], 5)

    async def test_giveaway_entry_unique_and_nonmember_rejected(self):
        await self.bot.growth.giveaway(CHAT, "نشان", 1, 1)
        token = self.db.one("SELECT token FROM giveaways")["token"]
        await self.bot.callback(self.callback(2, f"g:{token}"))
        self.assertEqual(self.tg.calls[-1][0], "answerCallbackQuery")
        await self.bot.growth.enter(token, 2)
        self.assertEqual(len(self.db.all("SELECT * FROM giveaway_entries")), 1)
        self.tg.left.add(3)
        with self.assertRaises(ValueError):
            await self.bot.growth.enter(token, 3)

    async def test_giveaway_draw_rewards_only_once(self):
        await self.bot.growth.giveaway(CHAT, "نشان", 1, 1)
        token = self.db.one("SELECT token FROM giveaways")["token"]
        await self.bot.growth.enter(token, 2)
        self.db.execute("UPDATE giveaways SET ends=0")
        await self.bot.growth.draw(int(time.time()))
        await self.bot.growth.draw(int(time.time()))
        self.assertEqual(self.db.member(CHAT, 2)["coins"], 100)
        self.assertEqual(self.db.one("SELECT winner FROM giveaways")["winner"], 2)


class DashboardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = str(Path(self.tmp.name) / "test.sqlite3")
        db = DB(path)
        seed(db)
        db.close()
        self.config = Config("123:test", database=path)
        self.token = "test-token-" + "x" * 40
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.config, self.token))
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, data=None, authenticated=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        headers = {"Authorization": "Bearer " + self.token} if authenticated else {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        connection.request(
            "POST" if data is not None else "GET",
            path,
            json.dumps(data) if data is not None else None,
            headers,
        )
        response = connection.getresponse()
        content = response.read()
        result = response.status, content, dict(response.getheaders())
        connection.close()
        return result

    def test_api_requires_bearer_and_no_cors(self):
        self.assertEqual(self.request("/api/chats", authenticated=False)[0], 401)
        status, raw, headers = self.request("/api/chats")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)[0]["id"], CHAT)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_settings_are_allowlisted_and_typed(self):
        self.assertEqual(self.request("/api/settings", {"chat": CHAT, "key": "links", "value": True})[0], 200)
        self.assertEqual(
            self.request("/api/settings", {"chat": CHAT, "key": "paid_gate", "value": True})[0], 400
        )
        self.assertEqual(
            self.request("/api/settings", {"chat": CHAT, "key": "links", "value": "false"})[0], 400
        )
        db = DB(self.config.database)
        self.assertTrue(db.chat(CHAT)["settings"]["links"])
        db.close()

    def test_static_asset_and_path_traversal(self):
        status, raw, headers = self.request("/", authenticated=False)
        self.assertEqual(status, 200)
        self.assertIn("تاکسی گپ".encode(), raw)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotEqual(self.request("/../../.env", authenticated=False)[0], 200)

    def test_training_and_period_validation(self):
        self.assertEqual(
            self.request("/api/samples", {"chat": CHAT, "text": "training text", "label": "spam"})[0], 200
        )
        self.assertEqual(self.request(f"/api/stats?chat={CHAT}&period=day")[0], 200)
        self.assertEqual(self.request(f"/api/stats?chat={CHAT}&period=oops")[0], 400)


if __name__ == "__main__":
    unittest.main()
