import asyncio
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx

from tuxigap.ai import AI, AIUnavailable
from tuxigap.config import Config
from tuxigap.db import DB
from tuxigap.demo import populate
from tuxigap.i18n import (
    LANGUAGES,
    catalog,
    current_language,
    placeholders,
    tr,
    using_language,
    validate_catalogs,
)
from tuxigap.moderation import local_check
from tuxigap.ported.fun import shout, emoticon
from tuxigap.ported.locks import LOCK_TYPES, entity_text, evaluate, trusted_urls
from tuxigap.stats import report
from test_core import BotFixture, CHAT, seed


class LanguageCase(unittest.IsolatedAsyncioTestCase):
    def test_catalogs_and_english_default(self):
        self.assertEqual(current_language(), "en")
        self.assertEqual(validate_catalogs(), [])
        self.assertGreaterEqual(len(catalog("en")), 500)
        for code in LANGUAGES:
            self.assertIn("language.changed", catalog(code))
            with using_language(code):
                self.assertNotIn("{language}", tr("language.changed", language="Tuxigap"))
        with using_language("unsupported"):
            self.assertEqual(current_language(), "en")

    async def test_languages_stay_separate_between_tasks(self):
        async def render(code):
            with using_language(code):
                await asyncio.sleep(0)
                return tr("language.choose")

        chinese, russian = await asyncio.gather(render("zh"), render("ru"))
        self.assertIn("欢迎", chinese)
        self.assertIn("Располагайтесь", russian)
        self.assertEqual(current_language(), "en")

    def test_english_fallback_is_safe_and_placeholders_match(self):
        key = next(k for k in catalog("en") if k not in catalog("zh"))
        with using_language("zh"):
            self.assertEqual(tr(key), catalog("en")[key])
        self.assertEqual(placeholders("Hello {name}: {count:,}"), {"name", "count"})


class PortsCase(unittest.TestCase):
    def test_utf16_entities_and_safe_domains(self):
        text = "😀 https://safe.example/a"
        entity = {"type": "url", "offset": 3, "length": 22}
        self.assertEqual(entity_text(text, entity), "https://safe.example/a")
        self.assertTrue(trusted_urls({"text": text}, ["url:safe.example"]))
        self.assertFalse(trusted_urls({"text": "https://safe.example.evil/a"}, ["safe.example"]))
        self.assertFalse(trusted_urls({"text": text + " https://evil.example"}, ["safe.example"]))

    def test_allowlist_is_scoped_to_its_lock(self):
        m = {"photo": [{}], "caption": "https://safe.example"}
        self.assertEqual(evaluate(["url", "photo"], m, CHAT, ["url:safe.example"]), ["photo"])
        self.assertEqual(evaluate(["unknown"], m, CHAT), [])
        self.assertGreaterEqual(len(LOCK_TYPES), 40)

    def test_sticker_forward_and_emoji_locks(self):
        self.assertEqual(
            evaluate(["stickerpremium"], {"sticker": {"premium_animation": {}}}, CHAT), ["stickerpremium"]
        )
        self.assertEqual(
            evaluate(["forwardchannel"], {"forward_origin": {"type": "channel"}}, CHAT), ["forwardchannel"]
        )
        self.assertEqual(evaluate(["emojionly"], {"text": "🌷 🎉"}, CHAT), ["emojionly"])
        self.assertEqual(evaluate(["emojionly"], {"text": "Hi 🌷"}, CHAT), [])

    def test_fun_ports_are_bounded_and_have_no_moderation_effects(self):
        self.assertLess(len(shout("hello" * 100)), 1000)
        self.assertEqual(shout(""), "")
        self.assertTrue(emoticon())


class CommunityCase(BotFixture, unittest.IsolatedAsyncioTestCase):
    async def test_language_changes_require_the_right_actor(self):
        with self.assertRaises(ValueError):
            await self.bot.change_language(CHAT, 2, "zh", CHAT)
        with self.assertRaises(ValueError):
            await self.bot.change_language(3, 2, "he", 2)
        await self.bot.change_language(CHAT, 1, "ru", CHAT)
        self.assertEqual(self.db.chat(CHAT)["settings"]["language"], "ru")
        await self.bot.change_language(2, 2, "he", 2)
        self.assertEqual(self.db.get("user_language:2"), "he")

    async def test_welcome_uses_group_language_and_custom_text_survives(self):
        self.db.setting(CHAT, "language", "ru")
        event = {
            "chat": {"id": CHAT, "title": "test", "type": "supergroup"},
            "date": int(time.time()),
            "from": {"id": 2},
            "old_chat_member": {"status": "left"},
            "new_chat_member": {"status": "member", "user": {"id": 2, "first_name": "Sam"}},
        }
        await self.bot.safe_handle({"update_id": 1, "chat_member": event})
        self.assertIn("Добро пожаловать", str(self.tg.sent[-1][1]))
        self.db.setting(CHAT, "welcome_text", "A custom greeting: {name}")
        event["date"] += 1
        await self.bot.safe_handle({"update_id": 2, "chat_member": event})
        self.assertEqual(self.tg.sent[-1][1], "A custom greeting: Sam")

    async def test_raid_threshold_and_expiry(self):
        self.db.setting(CHAT, "raid_limit", 3)
        self.assertFalse(self.bot.community.raid(CHAT, 2, 100))
        self.assertFalse(self.bot.community.raid(CHAT, 3, 101))
        self.assertTrue(self.bot.community.raid(CHAT, 4, 102))
        self.assertTrue(self.bot.community.raid(CHAT, 5, 103))
        self.assertFalse(self.bot.community.raid(CHAT, 6, 500))

    async def test_trusted_member_exemption(self):
        self.db.setting(CHAT, "words", ["blocked"])
        self.db.setting(CHAT, "dry_run", False)
        self.db.execute("INSERT INTO approved VALUES(?,?,?)", (CHAT, 2, 1))
        await self.bot.message(self.message(text="blocked"))
        self.assertNotIn("deleteMessage", [name for name, _ in self.tg.calls])

    async def test_quiet_hours_across_midnight(self):
        conf = self.db.chat(CHAT)["settings"] | {
            "night_mode": True,
            "timezone": "UTC",
            "night_start": 23,
            "night_end": 7,
        }
        ts = int(datetime(2026, 11, 16, 2, tzinfo=timezone.utc).timestamp())
        self.assertEqual(
            local_check(self.db, CHAT, 2, self.message(), conf, ts).reason, "Quiet hours are active"
        )
        self.assertFalse(local_check(self.db, CHAT, 2, self.message(), conf, ts + 12 * 3600).flagged)

    async def test_sender_channel_locks_do_not_target_anonymous_group_admin(self):
        self.db.setting(CHAT, "locks", ["anonchannel"])
        self.db.setting(CHAT, "dry_run", False)
        m = self.message(text="post")
        m["sender_chat"] = {"id": -100999, "type": "channel"}
        await self.bot.message(m)
        self.assertIn("deleteMessage", [name for name, _ in self.tg.calls])
        self.tg.calls.clear()
        m["message_id"] = 2
        m["sender_chat"]["id"] = CHAT
        await self.bot.message(m)
        self.assertNotIn("deleteMessage", [name for name, _ in self.tg.calls])

    async def make_federation(self):
        fid = self.bot.community.create_federation(1, "Friends")
        self.db.execute("INSERT INTO federation_chats VALUES(?,?,'active')", (CHAT, fid))
        return fid

    async def test_federation_requests_need_group_owner_and_fed_owner(self):
        fid = self.bot.community.create_federation(1, "Friends")
        with self.assertRaises(ValueError):
            await self.bot.community.request_join(CHAT, 2, fid)
        original = self.tg.call

        async def group_owner(method, **data):
            value = await original(method, **data)
            if method == "getChatMember" and data["user_id"] == 2:
                value["status"] = "creator"
            return value

        self.tg.call = group_owner
        _, state = await self.bot.community.request_join(CHAT, 2, fid)
        self.assertEqual(state, "pending")
        with self.assertRaises(ValueError):
            await self.bot.community.decide(fid, 3, CHAT, True)
        await self.bot.community.decide(fid, 1, CHAT, True)
        self.assertEqual(self.db.one("SELECT state FROM federation_chats")["state"], "active")

    async def test_federation_protects_admin_and_skips_stale_work(self):
        await self.make_federation()
        self.bot.community.federation_action(CHAT, 1, 99, "policy", True)
        self.bot.community.federation_action(CHAT, 1, 2, "policy", True)
        self.bot.community.federation_action(CHAT, 1, 2, "reviewed", False)
        await self.bot.community.enforce_federations(int(time.time()))
        self.assertNotIn("banChatMember", [name for name, _ in self.tg.calls])
        self.assertIn("protected", {r["state"] for r in self.db.all("SELECT state FROM federation_jobs")})

    async def test_federation_unban_does_not_lift_manual_ban(self):
        await self.make_federation()
        self.bot.community.federation_action(CHAT, 1, 2, "policy", True)
        await self.bot.community.enforce_federations(int(time.time()))
        self.assertIn(2, self.tg.banned)
        message = self.message(1, "/ban", 5)
        message["reply_to_message"] = self.message(2)
        await self.bot.command("ban", "", message)
        self.bot.community.federation_action(CHAT, 1, 2, "reviewed", False)
        await self.bot.community.enforce_federations(int(time.time()))
        self.assertIn(2, self.tg.banned)

    async def test_federation_unban_respects_paid_gate(self):
        await self.make_federation()
        self.bot.community.federation_action(CHAT, 1, 2, "policy", True)
        await self.bot.community.enforce_federations(int(time.time()))
        self.db.setting(CHAT, "paid_gate", True)
        self.bot.community.federation_action(CHAT, 1, 2, "reviewed", False)
        await self.bot.community.enforce_federations(int(time.time()))
        self.assertIn(2, self.tg.banned)
        self.assertEqual(self.db.one("SELECT expired_ban FROM subscriptions WHERE user=2")["expired_ban"], 1)


class AIAdditionsCase(unittest.IsolatedAsyncioTestCase):
    async def test_context_and_public_notes_are_data(self):
        db = DB(":memory:")
        seed(db)
        db.setting(CHAT, "ai_history", 2)
        db.setting(CHAT, "language", "es")
        db.message(CHAT, 1, 2, "A recent discussion", "text", int(time.time()))
        db.execute("INSERT INTO notes VALUES(?,?,?)", (CHAT, "meeting", "Our meeting is on Tuesday."))

        def transport(request):
            payload = json.loads(request.content)
            context = json.loads(payload["messages"][1]["content"])
            self.assertEqual(len(context["recent_messages"]), 1)
            self.assertEqual(context["public_notes"][0]["name"], "meeting")
            self.assertIn("es", payload["messages"][0]["content"])
            return httpx.Response(200, json={"choices": [{"message": {"content": "¡Nos vemos el martes!"}}]})

        ai = AI(
            Config("123:fake", ai_key="fake", ai_model="test"),
            db,
            httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        self.assertIn("martes", await ai.answer(CHAT, 2, "meeting?", "Be kind"))
        await ai.close()
        db.close()

    async def test_vision_payload_and_invalid_quiz(self):
        db = DB(":memory:")
        seed(db)

        def transport(request):
            payload = json.loads(request.content)
            content = payload["messages"][1]["content"]
            if isinstance(content, list):
                self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
                answer = '{"spam":false,"confidence":0.9,"reason":"safe"}'
            else:
                answer = '{"question":"Q","options":["A","B","C","D"],"answer":true}'
            return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

        ai = AI(
            Config("123:fake", ai_key="fake", ai_model="test"),
            db,
            httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        self.assertFalse((await ai.vision(CHAT, 2, b"jpeg", "caption", "rules"))[0])
        with self.assertRaises(AIUnavailable):
            await ai.quiz(CHAT, 2, "science")
        await ai.close()
        db.close()


class OperationsCase(unittest.TestCase):
    def test_v1_upgrade_keeps_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            with sqlite3.connect(path) as old:
                old.executescript(
                    "CREATE TABLE kv(key TEXT PRIMARY KEY,value TEXT); INSERT INTO kv VALUES('legacy','42'); PRAGMA user_version=1;"
                )
            db = DB(str(path))
            self.assertEqual(db.get("legacy"), 42)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(db.all("SELECT * FROM federations"), [])
            db.close()

    def test_setup_keeps_existing_secrets_safe(self):
        spec = importlib.util.spec_from_file_location(
            "configure", Path(__file__).parents[1] / "tools/configure.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            module.write_config(path, "123:fake", "1")
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                module.write_config(path, "123:other", "1")
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn("WEB_TOKEN=\n", before.decode())

    def test_demo_uses_synthetic_data_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.sqlite3"
            with patch("httpx.AsyncClient", side_effect=AssertionError("Demo must stay offline")):
                populate(path)
            db = DB(str(path))
            text, totals = report(db, -100100100, "year")
            self.assertGreater(totals["messages"], 0)
            self.assertIn("Demo", text)
            db.close()


if __name__ == "__main__":
    unittest.main()
