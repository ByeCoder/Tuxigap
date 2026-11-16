import json
from pathlib import Path
import tempfile
import time
import unittest

from tuxigap.db import DB
from tuxigap.humor import builtins, public_joke
from tuxigap.i18n import LANGUAGES, using_language, validate_catalogs
from tuxigap.music import Music, MusicSettings
from tuxigap.music_worker import MusicWorker, MediaLibrary
from test_core import BotFixture, CHAT


class HumorCase(BotFixture, unittest.IsolatedAsyncioTestCase):
    def test_all_packs_have_unique_ids_real_language_and_categories(self):
        rows = list(builtins().values())
        self.assertEqual(len(rows), 240)
        self.assertEqual(sum(r["language"] == "fa" for r in rows), 80)
        self.assertEqual({r["language"] for r in rows}, set(LANGUAGES))
        self.assertTrue(all(10 <= len(r["text"]) < 700 and len(r["id"]) == 16 for r in rows))
        self.assertEqual(validate_catalogs(), [])
        with using_language("fa"):
            self.assertTrue(any("\u0600" <= c <= "\u06ff" for c in public_joke()))

    def test_persian_deck_does_not_repeat_before_exhaustion(self):
        ids = [self.bot.humor.select(CHAT, "fa")["id"] for _ in range(80)]
        self.assertEqual(len(set(ids)), 80)
        self.assertNotEqual(self.bot.humor.select(CHAT, "fa")["id"], ids[-1])

    def test_category_rotation_does_not_clear_other_category_history(self):
        first = self.bot.humor.select(CHAT, "fa", "tech")
        for _ in range(17):
            self.bot.humor.select(CHAT, "fa", "animals")
        seen = self.db.one("SELECT 1 FROM joke_history WHERE chat=? AND joke=?", (CHAT, first["id"]))
        self.assertIsNotNone(seen)

    async def test_explicit_persian_and_private_jokes_do_not_require_group_membership(self):
        await self.bot.command("jokes", "fa student", self.message(2))
        text = self.tg.sent[-1][1]
        self.assertIn("فارسی", text)
        msg = self.message(3)
        msg["chat"] = {"id": 3, "type": "private"}
        await self.bot.command("jokes", "ru", msg)
        self.assertIn("Русский", self.tg.sent[-1][1])
        self.assertIsNone(self.db.one("SELECT 1 FROM chats WHERE id=3"))
        self.assertFalse(
            any(method == "getChatMember" and payload["chat_id"] == 3 for method, payload in self.tg.calls)
        )

    async def test_joke_default_can_be_persian_without_changing_english_ui(self):
        await self.bot.command("jokedefault", "fa", self.message(1))
        await self.bot.command("jokes", "", self.message(2))
        self.assertIn("فارسی", self.tg.sent[-1][1])
        self.assertEqual(self.db.chat(CHAT)["settings"]["language"], "en")
        with self.assertRaises(ValueError):
            await self.bot.command("jokedefault", "ru", self.message(2))

    async def test_votes_and_saves_are_deduplicated_and_cross_private_access_denied(self):
        joke = self.bot.humor.select(CHAT, "fa")
        for _ in range(2):
            await self.bot.humor.callback(
                self.callback(2, f"j:{CHAT}:like:{joke['id']}"), ["j", str(CHAT), "like", joke["id"]]
            )
        self.assertEqual(self.db.one("SELECT count(*) n FROM joke_reactions")["n"], 1)
        self.db.register({"id": 2, "title": "private", "type": "private"})
        with self.assertRaises(ValueError):
            await self.bot.humor.callback(
                self.callback(3, f"j:2:save:{joke['id']}"), ["j", "2", "save", joke["id"]]
            )
        self.tg.left.add(2)
        with self.assertRaises(ValueError):
            await self.bot.humor.send(CHAT, 2, CHAT, "fa")

    async def test_submission_needs_review_and_cannot_cross_groups(self):
        await self.bot.command(
            "jokesuggest",
            "fa | everyday | یه روز تصمیم گرفتم همه‌چیز رو عقب نندازم؛ از فردا شروع می‌کنم!",
            self.message(2),
        )
        row = self.db.one("SELECT * FROM community_jokes")
        self.assertIsNone(self.bot.humor.find(CHAT, row["id"]))
        with self.assertRaises(ValueError):
            await self.bot.humor.callback(self.callback(2, "j"), ["j", str(CHAT), "approve", row["id"]])
        await self.bot.humor.callback(self.callback(1, "j"), ["j", str(CHAT), "approve", row["id"]])
        self.assertIsNotNone(self.bot.humor.find(CHAT, row["id"]))
        self.assertIsNone(self.bot.humor.find(CHAT - 1, row["id"]))

    async def test_fun_switch_blocks_commands_and_old_vote_buttons(self):
        joke = self.bot.humor.select(CHAT, "fa")
        self.db.setting(CHAT, "fun", False)
        with self.assertRaises(ValueError):
            await self.bot.command("jokes", "fa", self.message(2))
        with self.assertRaises(ValueError):
            await self.bot.humor.callback(self.callback(2, "j"), ["j", str(CHAT), "like", joke["id"]])

    async def test_forget_erases_custom_jokes_and_personal_reactions(self):
        joke = self.bot.humor.select(CHAT, "fa")
        self.db.execute("INSERT INTO joke_reactions VALUES(?,?,?,?)", (CHAT, 2, joke["id"], "save"))
        await self.bot.callback(self.callback(2, "forget:2"))
        self.assertEqual(self.db.one("SELECT count(*) n FROM joke_reactions")["n"], 0)


class FakeEngine:
    def __init__(self):
        self.calls = []

    async def play(self, chat, path):
        self.calls.append(("play", chat, path))

    async def pause(self, chat):
        self.calls.append(("pause", chat))

    async def resume(self, chat):
        self.calls.append(("resume", chat))

    async def volume(self, chat, value):
        self.calls.append(("volume", chat, value))

    async def leave(self, chat):
        self.calls.append(("leave", chat))


class FakeMedia:
    async def prepare(self, payload):
        return "/safe/audio.ogg", 10


class MusicCase(BotFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        original = self.tg.call

        async def call(method, **kwargs):
            if method == "getChatMember" and kwargs["user_id"] == 1:
                return {"status": "creator"}
            return await original(method, **kwargs)

        self.tg.call = call
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        (root / "media").mkdir()
        (root / "media" / "demo.ogg").write_bytes(b"fake audio")
        library = root / "library.json"
        library.write_text(json.dumps([{"id": "demo", "title": "Demo", "file": "demo.ogg"}]))
        self.settings = MusicSettings(True, (CHAT,), str(library), str(root / "media"))
        self.bot.music = Music(self.bot, self.settings)
        self.engine = FakeEngine()
        self.worker = MusicWorker(self.db, self.tg, self.settings, self.engine, FakeMedia())

    async def asyncTearDown(self):
        self.directory.cleanup()
        await super().asyncTearDown()

    def job(self, action, payload=None, actor=1, key=None):
        return self.bot.music.enqueue_job(CHAT, actor, action, payload or {}, key or str(time.time_ns()))

    async def test_controls_queue_requests_not_audio_until_worker_runs(self):
        await self.bot.music.command("mplay", "demo", self.message(1, mid=10))
        self.assertEqual(self.engine.calls, [])
        await self.worker.jobs()
        self.assertEqual(self.db.one("SELECT state FROM music_jobs")["state"], "done")
        await self.worker.tick()
        self.assertEqual(self.engine.calls[0][0], "play")
        self.assertEqual(self.worker.state(CHAT)["status"], "playing")

    async def test_duplicate_request_does_not_duplicate_queue_entry(self):
        payload = {"kind": "library", "track": "demo", "title": "Demo"}
        self.job("enqueue", payload, key="same")
        self.job("enqueue", payload, key="same")
        await self.worker.jobs()
        await self.worker.jobs()
        self.assertEqual(self.db.one("SELECT count(*) n FROM music_queue")["n"], 1)

    async def test_permission_rechecked_in_worker_and_old_buttons(self):
        self.db.execute("INSERT INTO staff_roles VALUES(?,?,?,?)", (CHAT, 2, "host", 1))
        self.job("enqueue", {"kind": "library", "track": "demo", "title": "Demo"}, actor=2)
        self.db.execute("DELETE FROM staff_roles WHERE user=2")
        await self.worker.jobs()
        self.assertEqual(self.db.one("SELECT state FROM music_jobs")["state"], "failed")
        with self.assertRaises(ValueError):
            await self.bot.music.callback(self.callback(2, "m"), ["m", str(CHAT), "stop"])
        self.assertEqual(self.engine.calls, [])

    async def test_revocation_during_preparation_prevents_call_join(self):
        self.db.execute("INSERT INTO staff_roles VALUES(?,?,?,?)", (CHAT, 2, "host", 1))
        self.job("enqueue", {"kind": "library", "track": "demo", "title": "Demo"}, actor=2)
        await self.worker.jobs()
        db = self.db

        class RevokingMedia:
            async def prepare(self, payload):
                db.execute("DELETE FROM staff_roles WHERE user=2")
                return "/safe/audio.ogg", 10

        self.worker.media = RevokingMedia()
        await self.worker.tick()
        self.assertFalse(any(c[0] == "play" for c in self.engine.calls))

    async def test_pause_resume_volume_skip_and_stop(self):
        for i in range(2):
            self.job("enqueue", {"kind": "library", "track": "demo", "title": str(i)})
        await self.worker.jobs()
        await self.worker.tick()
        self.job("pause")
        await self.worker.jobs()
        self.assertEqual(self.worker.state(CHAT)["status"], "paused")
        started = self.worker.state(CHAT)["started"]
        self.job("resume")
        await self.worker.jobs()
        self.assertEqual(self.worker.state(CHAT)["status"], "playing")
        self.assertGreaterEqual(self.worker.state(CHAT)["started"], started)
        self.job("volume", {"value": 45})
        await self.worker.jobs()
        self.assertEqual(self.worker.state(CHAT)["volume"], 45)
        self.job("skip")
        await self.worker.jobs()
        await self.worker.tick()
        self.assertEqual(sum(c[0] == "play" for c in self.engine.calls), 2)
        self.job("stop")
        await self.worker.jobs()
        self.assertNotIn(CHAT, self.worker.active)
        self.assertEqual(self.worker.state(CHAT)["current"], 0)

    async def test_repeat_natural_completion_and_pending_removal(self):
        self.job("enqueue", {"kind": "library", "track": "demo", "title": "A"})
        self.job("enqueue", {"kind": "library", "track": "demo", "title": "B"})
        await self.worker.jobs()
        await self.worker.tick()
        row = self.db.one("SELECT id FROM music_queue WHERE state='queued'")
        self.job("remove", {"id": row["id"]})
        await self.worker.jobs()
        self.job("repeat", {"mode": "one"})
        await self.worker.jobs()
        started = self.worker.state(CHAT)["started"]
        await self.worker.tick(started + 13)
        self.assertEqual(sum(c[0] == "play" for c in self.engine.calls), 2)
        self.assertEqual(
            self.db.one("SELECT state FROM music_queue WHERE id=?", (row["id"],))["state"], "cancelled"
        )

    async def test_restart_preserves_queue_without_surprise_autoplay(self):
        self.job("enqueue", {"kind": "library", "track": "demo", "title": "Demo"})
        await self.worker.jobs()
        await self.worker.tick()
        new = MusicWorker(self.db, self.tg, self.settings, self.engine, FakeMedia())
        new.recover()
        self.assertEqual(new.state(CHAT)["status"], "interrupted")
        count = len(self.engine.calls)
        await new.tick()
        self.assertEqual(len(self.engine.calls), count)
        self.job("resume")
        await new.jobs()
        await new.tick()
        self.assertEqual(new.state(CHAT)["status"], "playing")

    async def test_expired_and_interrupted_jobs_not_replayed(self):
        identity = self.job("stop")
        self.db.execute("UPDATE music_jobs SET created=1 WHERE id=?", (identity,))
        await self.worker.jobs()
        self.assertEqual(self.db.one("SELECT state FROM music_jobs")["state"], "failed")
        self.db.execute("UPDATE music_jobs SET state='running'")
        self.worker.recover()
        self.assertEqual(self.db.one("SELECT state FROM music_jobs")["state"], "uncertain")

    async def test_file_sources_and_input_bounds(self):
        with self.assertRaises(ValueError):
            await self.bot.music.command("mplay", "https://example.com/audio.mp3", self.message(1))
        self.db.execute("DELETE FROM command_cooldown")
        with self.assertRaises(ValueError):
            await self.bot.music.command("mvolume", "101", self.message(1))
        self.db.execute("DELETE FROM command_cooldown")
        msg = self.message(1, mid=5)
        msg["reply_to_message"] = {
            "audio": {"file_id": "audio-file", "file_size": 100, "duration": 10, "title": "A friendly song"}
        }
        await self.bot.music.command("mplay", "", msg)
        payload = json.loads(self.db.one("SELECT payload FROM music_jobs")["payload"])
        self.assertEqual(payload["kind"], "telegram")
        self.assertEqual(payload["file_id"], "audio-file")

    def test_library_rejects_traversal_symlink_escape_and_duplicate_ids(self):
        root = Path(self.directory.name)
        outside = root / "outside.ogg"
        outside.write_bytes(b"not allowed")
        library = Path(self.settings.library)
        for rows in (
            [{"id": "x", "file": "../outside.ogg"}],
            [{"id": "x", "file": "demo.ogg"}, {"id": "x", "file": "demo.ogg"}],
            [42],
        ):
            library.write_text(json.dumps(rows))
            with self.assertRaises(ValueError):
                self.settings.tracks()
        (root / "media" / "escape.ogg").symlink_to(outside)
        library.write_text(json.dumps([{"id": "escape", "file": "escape.ogg"}]))
        with self.assertRaises(ValueError):
            self.settings.tracks()

    async def test_download_path_escape_is_rejected_before_fetch(self):
        original = self.tg.call

        async def call(method, **kwargs):
            if method == "getFile":
                return {"file_path": "../secret", "file_size": 100}
            return await original(method, **kwargs)

        self.tg.call = call
        media = MediaLibrary(self.settings, self.tg)
        with self.assertRaises(ValueError):
            await media.prepare({"kind": "telegram", "file_id": "file"})

    async def test_pending_stop_prevents_prepared_audio_from_starting(self):
        self.job("enqueue", {"kind": "library", "track": "demo", "title": "Demo"})
        await self.worker.jobs()
        self.job("stop")
        await self.worker.tick()
        self.assertFalse(any(c[0] == "play" for c in self.engine.calls))
        await self.worker.jobs()
        self.assertEqual(self.db.one("SELECT state FROM music_queue")["state"], "cancelled")

    async def test_notice_failure_does_not_stop_working_audio(self):
        self.job("enqueue", {"kind": "library", "track": "demo", "title": "Demo"})
        await self.worker.jobs()
        self.tg.fail_send = True
        await self.worker.tick()
        self.assertEqual(self.worker.state(CHAT)["status"], "playing")
        self.assertFalse(any(c[0] == "leave" for c in self.engine.calls))

    def test_pruned_jobs_never_reuse_queue_source_ids(self):
        old = self.job("enqueue", {"kind": "library", "track": "demo", "title": "Demo"})
        self.db.execute("DELETE FROM music_jobs")
        new = self.job("stop")
        self.assertGreater(new, old)

    def test_schema_three_upgrades_without_losing_existing_content(self):
        path = Path(self.directory.name) / "upgrade.sqlite3"
        db = DB(str(path))
        db.set("existing", "hello")
        db.execute("PRAGMA user_version=3")
        db.close()
        db = DB(str(path))
        self.assertEqual(db.get("existing"), "hello")
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
        self.assertIsNotNone(db.one("SELECT name FROM sqlite_master WHERE name='music_queue'"))
        db.close()
