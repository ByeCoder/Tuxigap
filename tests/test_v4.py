import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest

import httpx

from tuxigap.db import DB
from tuxigap.hub import rank_for, ROLE_RIGHTS
from tuxigap.i18n import catalog, validate_catalogs
from tuxigap.presentation import rich_text, using_presentation, decorate_keyboard
from tuxigap.telegram import Telegram, APIError
from tuxigap.ui import button
from test_core import BotFixture, CHAT


class PresentationCase(unittest.IsolatedAsyncioTestCase):
    def test_safe_emoji_markup_and_explicit_button_fields(self):
        text = rich_text("<b>Hello</b> [emoji:123456|🚕] & welcome")
        self.assertIn("&lt;b&gt;Hello&lt;/b&gt;", text)
        self.assertIn('<tg-emoji emoji-id="123456">🚕</tg-emoji>', text)
        self.assertTrue(text.endswith("&amp; welcome"))
        self.assertEqual(rich_text("[emoji:x|<script>]"), "[emoji:x|&lt;script&gt;]")
        self.assertEqual(button("Yes", "x", style="success", icon="123")["icon_custom_emoji_id"], "123")
        with self.assertRaises(ValueError):
            button("Oops", "x", style="orange")

    async def test_context_isolation(self):
        async def render(style):
            with using_presentation({"button_style": style}):
                await asyncio.sleep(0)
                return decorate_keyboard({"inline_keyboard": [[button("Hello", "x")]]})

        blue, green = await asyncio.gather(render("primary"), render("success"))
        self.assertEqual(blue["inline_keyboard"][0][0]["style"], "primary")
        self.assertEqual(green["inline_keyboard"][0][0]["style"], "success")

    async def test_transport_falls_back_when_emoji_not_eligible(self):
        payloads = []

        def respond(request):
            payloads.append(json.loads(request.content))
            if len(payloads) == 1:
                return httpx.Response(
                    400, json={"ok": False, "error_code": 400, "description": "CUSTOM_EMOJI_NOT_ALLOWED"}
                )
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        tg = Telegram("0:test", client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        try:
            with using_presentation({"button_style": "success", "button_icon": "123"}):
                await tg.send(CHAT, rich_text("[emoji:123|🚕] Hello"), [[button("Play", "x")]])
            self.assertIn("tg-emoji", payloads[0]["text"])
            self.assertEqual(payloads[0]["reply_markup"]["inline_keyboard"][0][0]["style"], "success")
            self.assertEqual(payloads[1]["text"], "🚕 Hello")
            self.assertNotIn("icon_custom_emoji_id", payloads[1]["reply_markup"]["inline_keyboard"][0][0])
        finally:
            await tg.close()

    async def test_unrelated_api_failure_is_not_retried_as_plain(self):
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "chat not found"})

        tg = Telegram("0:test", client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        try:
            with self.assertRaises(APIError):
                await tg.send(CHAT, "Hello", [[button("Play", "x")]])
            self.assertEqual(len(seen), 1)
        finally:
            await tg.close()

    def test_catalog_keys_and_placeholders(self):
        self.assertEqual(validate_catalogs(), [])
        self.assertIn("hub.appearance_help", catalog("en"))
        self.assertIn("party.started", catalog("fa"))


class HubCase(BotFixture, unittest.IsolatedAsyncioTestCase):
    def request(self, user=2, date=100):
        return {
            "chat": {"id": CHAT, "title": "test", "type": "supergroup"},
            "from": {"id": user, "first_name": "Alex"},
            "date": date,
        }

    def member_event(self, after=True, date=100):
        return {
            "chat": {"id": CHAT, "title": "test", "type": "supergroup"},
            "date": date,
            "from": {"id": 1},
            "old_chat_member": {"status": "left" if after else "member"},
            "new_chat_member": {
                "status": "member" if after else "left",
                "user": {"id": 2, "first_name": "Alex"},
            },
        }

    async def set_owner(self):
        original = self.tg.call

        async def call(method, **kwargs):
            if method == "getChatMember" and kwargs["user_id"] == 1:
                return {"status": "creator"}
            return await original(method, **kwargs)

        self.tg.call = call

    async def test_only_actual_owner_assigns_staff_and_live_membership_gates_role(self):
        await self.set_owner()
        await self.bot.hub.command("role", "2 analyst", self.message(1))
        self.assertTrue(await self.bot.hub.allowed(CHAT, 2, "analytics"))
        self.assertFalse(await self.bot.hub.allowed(CHAT, 2, "content"))
        self.tg.left.add(2)
        self.assertFalse(await self.bot.hub.allowed(CHAT, 2, "analytics"))
        with self.assertRaises(ValueError):
            await self.bot.hub.command("role", "3 manager", self.message(2))

    async def test_role_revoked_on_leave_and_lifecycle_deduplicated(self):
        self.db.execute("INSERT INTO staff_roles VALUES(?,?,?,?)", (CHAT, 2, "manager", 1))
        self.db.setting(CHAT, "goodbye", True)
        self.db.setting(CHAT, "goodbye_text", "Bye {name} [emoji:123|🌷]")
        event = self.member_event(False)
        await self.bot.membership(event)
        sent = len(self.tg.sent)
        await self.bot.membership(event)
        self.assertEqual(len(self.tg.sent), sent)
        self.assertIn("tg-emoji", self.tg.sent[-1][1])
        self.assertIsNone(self.db.one("SELECT * FROM staff_roles WHERE chat=? AND user=2", (CHAT,)))
        self.assertEqual(
            self.db.one("SELECT n FROM hours WHERE chat=? AND metric=?", (CHAT, "leaves"))["n"], 1
        )

    async def test_stale_leave_does_not_remove_a_newer_role(self):
        await self.bot.membership(self.member_event(True, 200))
        self.db.execute("INSERT INTO staff_roles VALUES(?,?,?,?)", (CHAT, 2, "analyst", 1))
        await self.bot.membership(self.member_event(False, 100))
        self.assertIsNotNone(self.db.one("SELECT * FROM staff_roles WHERE chat=? AND user=2", (CHAT,)))

    async def test_auto_approval_respects_dry_run_and_trusted_policy(self):
        self.db.setting(CHAT, "join_mode", "auto")
        await self.bot.hub.join_request(self.request())
        self.assertFalse(any(m == "approveChatJoinRequest" for m, _ in self.tg.calls))
        self.db.setting(CHAT, "dry_run", False)
        await self.bot.hub.join_request(self.request())
        self.assertEqual(sum(m == "approveChatJoinRequest" for m, _ in self.tg.calls), 1)
        await self.bot.hub.join_request(self.request())
        self.assertEqual(sum(m == "approveChatJoinRequest" for m, _ in self.tg.calls), 1)
        self.db.setting(CHAT, "join_mode", "trusted")
        await self.bot.hub.join_request(self.request(3, 200))
        self.assertEqual(sum(m == "approveChatJoinRequest" for m, _ in self.tg.calls), 1)
        self.db.execute("INSERT INTO approved VALUES(?,?,?)", (CHAT, 3, 1))
        await self.bot.hub.join_request(self.request(3, 200))
        self.assertEqual(sum(m == "approveChatJoinRequest" for m, _ in self.tg.calls), 2)

    async def test_failed_auto_approval_retries_existing_pending_request(self):
        self.db.setting(CHAT, "join_mode", "auto")
        self.db.setting(CHAT, "dry_run", False)
        original = self.tg.call
        failed = False

        async def call(method, **kwargs):
            nonlocal failed
            if method == "approveChatJoinRequest" and not failed:
                failed = True
                raise APIError(method, 503, "temporary")
            return await original(method, **kwargs)

        self.tg.call = call
        with self.assertRaises(APIError):
            await self.bot.hub.join_request(self.request())
        await self.bot.hub.join_request(self.request())
        rows = self.db.all("SELECT * FROM admission_requests")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "approved")

    async def test_paid_gate_cannot_be_overridden_by_auto_or_manual(self):
        self.db.setting(CHAT, "paid_gate", True)
        self.db.setting(CHAT, "join_mode", "auto")
        await self.bot.hub.join_request(self.request())
        self.assertTrue(any(m == "declineChatJoinRequest" for m, _ in self.tg.calls))
        self.db.execute(
            "INSERT INTO admission_requests(chat,user,name,requested) VALUES(?,?,?,?)", (CHAT, 2, "Alex", 200)
        )
        rid = self.db.one("SELECT max(id) id FROM admission_requests")["id"]
        with self.assertRaisesRegex(ValueError, "paid membership"):
            await self.bot.hub.decide_request(rid, 1, True)
        self.db.execute(
            "INSERT INTO subscriptions(chat,user,expires) VALUES(?,?,?)", (CHAT, 2, int(time.time()) + 1000)
        )
        await self.bot.hub.decide_request(rid, 1, True)

    async def test_superseded_request_and_cross_chat_buttons_rejected(self):
        await self.bot.hub.join_request(self.request(date=100))
        old = self.db.one("SELECT id FROM admission_requests")["id"]
        await self.bot.hub.join_request(self.request(date=200))
        with self.assertRaises(ValueError):
            await self.bot.hub.decide_request(old, 1, True)
        with self.assertRaises(ValueError):
            await self.bot.hub.callback(
                self.callback(1, f"h:{CHAT}:request:{old}:yes"),
                ["h", str(CHAT - 1), "request", str(old), "yes"],
            )
        with self.assertRaises(ValueError):
            await self.bot.hub.decide_request(old + 1, 2, True)

    async def test_federation_ban_blocks_request_approval(self):
        self.db.setting(CHAT, "dry_run", False)
        self.db.execute("INSERT INTO federations VALUES('f',1,'test')")
        self.db.execute("INSERT INTO federation_chats VALUES(?,'f','active')", (CHAT,))
        self.db.execute("INSERT INTO federation_bans VALUES('f',2,'policy',1,1,1)")
        await self.bot.hub.join_request(self.request())
        self.assertTrue(any(m == "declineChatJoinRequest" for m, _ in self.tg.calls))

    async def test_native_promotion_never_grants_missing_right_or_promote_privilege(self):
        await self.set_owner()
        original = self.tg.call

        async def grant(method, **kwargs):
            if method == "getChatMember" and kwargs["user_id"] == 99:
                return {
                    "status": "administrator",
                    "can_promote_members": True,
                    **{r: True for r in ROLE_RIGHTS["host"]},
                }
            return await original(method, **kwargs)

        self.tg.call = grant
        await self.bot.hub.native_role(CHAT, 1, 2, "host")
        payload = next(v for m, v in self.tg.calls if m == "promoteChatMember")
        self.assertTrue(payload["can_manage_video_chats"])
        self.assertFalse(payload["can_promote_members"])
        with self.assertRaises(ValueError):
            await self.bot.hub.native_role(CHAT, 1, 3, "manager")

    async def test_delegated_moderation_is_scoped_and_higher_staff_protected(self):
        self.db.execute("INSERT INTO staff_roles VALUES(?,?,?,?)", (CHAT, 2, "moderator", 1))
        msg = self.message(2, "/warn", 10)
        msg["reply_to_message"] = {"message_id": 9, "from": {"id": 3}, "text": "hello"}
        await self.bot.command("warn", "", msg)
        self.assertEqual(self.db.member(CHAT, 3)["warns"], 1)
        with self.assertRaises(ValueError):
            await self.bot.panel(CHAT, 2, CHAT)
        self.db.execute("INSERT INTO staff_roles VALUES(?,?,?,?)", (CHAT, 3, "manager", 1))
        with self.assertRaises(ValueError):
            await self.bot.command("ban", "", msg)
        self.assertFalse(any(m == "banChatMember" for m, _ in self.tg.calls))

    async def test_staff_panel_and_inline_settings_recheck_current_permissions(self):
        await self.bot.hub.panel(CHAT, 1, CHAT)
        self.assertTrue(
            any("Staff hub" in str(text) or "staff hub" in str(text) for _, text, _ in self.tg.sent)
        )
        with self.assertRaises(ValueError):
            await self.bot.hub.callback(
                self.callback(2, f"h:{CHAT}:theme:danger"), ["h", str(CHAT), "theme", "danger"]
            )
        await self.bot.hub.callback(
            self.callback(1, f"h:{CHAT}:theme:success"), ["h", str(CHAT), "theme", "success"]
        )
        self.assertEqual(self.db.chat(CHAT)["settings"]["button_style"], "success")

    async def test_tags_scoped_and_visible_tag_payload(self):
        original = self.tg.call

        async def tag_right(method, **kwargs):
            result = await original(method, **kwargs)
            if method == "getChatMember" and kwargs["user_id"] == 1:
                result["can_manage_tags"] = True
            return result

        self.tg.call = tag_right
        await self.bot.hub.command("tag", "2 helper", self.message(1))
        with self.assertRaises(ValueError):
            await self.bot.hub.command("tag", "3 helper", self.message(2))
        await self.bot.hub.command("membertag", "2 Helper", self.message(1))
        self.assertTrue(any(m == "setChatMemberTag" and v["tag"] == "Helper" for m, v in self.tg.calls))
        self.tg.left.add(2)
        await self.bot.hub.command("tagmembers", "helper Hi there", self.message(1))
        self.assertNotIn("tg://user?id=2", self.tg.sent[-1][1])

    async def test_rank_ladder_owner_validation_and_no_authority_from_xp(self):
        await self.set_owner()
        with self.assertRaises(ValueError):
            await self.bot.hub.command("rankset", "0:New | 0:Star", self.message(1))
        await self.bot.hub.command("rankset", "0:New | 20:Star", self.message(1))
        self.assertEqual(rank_for(self.db.chat(CHAT)["settings"], 25)[0], "Star")
        self.db.member(CHAT, 2)
        self.db.execute("UPDATE members SET xp=999999 WHERE chat=? AND user=2", (CHAT,))
        self.assertFalse(await self.bot.hub.allowed(CHAT, 2, "content"))

    async def test_call_events_are_deduplicated_and_link_checks_reject_lookalikes(self):
        m = self.message(1, mid=10)
        m["video_chat_started"] = {}
        await self.bot.hub.call_event(m)
        await self.bot.hub.call_event(m)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(self.db.get(f"call:{CHAT}")["kind"], "started")
        self.db.execute("INSERT INTO staff_roles VALUES(?,?,?,?)", (CHAT, 2, "host", 1))
        with self.assertRaises(ValueError):
            await self.bot.hub.command("calllink", "https://t.me.evil.example/call", self.message(2))
        await self.bot.hub.command("calllink", "https://t.me/demo?videochat", self.message(2))
        await self.bot.hub.command("callannounce", "", self.message(2))
        self.assertEqual(self.tg.sent[-1][2][0][0]["url"], "https://t.me/demo?videochat")

    async def test_channel_private_posts_validate_destination_and_actor(self):
        msg = self.message(1)
        msg["chat"] = {"id": 1, "type": "private"}
        await self.bot.hub.command("post", str(CHAT) + " Welcome [emoji:123|🚕]", msg)
        self.assertEqual(self.tg.sent[-2][0], CHAT)
        self.assertIn("tg-emoji", self.tg.sent[-2][1])
        msg["from"]["id"] = 2
        with self.assertRaises(ValueError):
            await self.bot.hub.command("post", str(CHAT) + " Oops", msg)

    async def test_group_posts_do_not_require_channel_only_admin_flags(self):
        original = self.tg.call

        async def group_rights(method, **kwargs):
            result = await original(method, **kwargs)
            if method == "getChatMember":
                result.pop("can_post_messages", None)
                result.pop("can_edit_messages", None)
            return result

        self.tg.call = group_rights
        await self.bot.hub.command("post", "Hello, group!", self.message(1))
        self.assertEqual(self.tg.sent[-2][1], "Hello, group!")

    async def test_forget_keeps_new_records_until_self_confirmation(self):
        self.db.execute("INSERT INTO member_tags VALUES(?,?,?)", (CHAT, 2, "helper"))
        await self.bot.command("forget", "", self.message(2))
        self.assertIsNotNone(self.db.one("SELECT * FROM member_tags WHERE user=2"))
        await self.bot.callback(self.callback(3, "forget:2"))
        self.assertIsNotNone(self.db.one("SELECT * FROM member_tags WHERE user=2"))
        await self.bot.callback(self.callback(2, "forget:2"))
        self.assertIsNone(self.db.one("SELECT * FROM member_tags WHERE user=2"))

    async def test_group_game_single_winner_persistence_and_five_attempts(self):
        await self.bot.hub.party.start(CHAT, 2, "number")
        game = self.db.one("SELECT * FROM party_games")
        answer = json.loads(game["data"])["answer"]
        for _ in range(5):
            self.bot.hub.party.solve(CHAT, 3, "not a number")
        with self.assertRaises(ValueError):
            self.bot.hub.party.solve(CHAT, 3, answer)
        self.assertIn("winner", self.bot.hub.party.solve(CHAT, 2, answer))
        with self.assertRaises(ValueError):
            self.bot.hub.party.solve(CHAT, 4, answer)
        self.assertEqual(self.db.member(CHAT, 2)["xp"], 20)
        self.assertEqual(self.db.one("SELECT points FROM party_scores WHERE user=2")["points"], 20)

    async def test_word_chain_requires_turns_no_repeats_and_expires(self):
        await self.bot.hub.party.start(CHAT, 2, "wordchain")
        row = self.db.one("SELECT * FROM party_games")
        self.db.execute(
            "UPDATE party_games SET data=? WHERE id=?",
            (json.dumps({"words": ["garden"], "last_user": 0}), row["id"]),
        )
        self.bot.hub.party.solve(CHAT, 2, "night")
        with self.assertRaises(ValueError):
            self.bot.hub.party.solve(CHAT, 2, "table")
        self.bot.hub.party.solve(CHAT, 3, "table")
        with self.assertRaises(ValueError):
            self.bot.hub.party.solve(CHAT, 4, "night")
        self.db.execute("UPDATE party_games SET expires=1")
        await self.bot.hub.expire(2)
        self.assertEqual(self.db.one("SELECT state FROM party_games")["state"], "expired")

    async def test_all_group_game_modes_create_valid_persistent_rounds(self):
        for i, mode in enumerate(("math", "riddle", "scramble")):
            self.db.execute("DELETE FROM party_games")
            self.db.execute("DELETE FROM command_cooldown WHERE kind='party_start'")
            await self.bot.hub.party.start(CHAT, 2, mode)
            game = self.db.one("SELECT * FROM party_games")
            self.assertEqual(game["mode"], mode)
            self.assertTrue(json.loads(game["data"])["answer"])

    def test_v2_database_upgrade_retains_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite3"
            db = DB(str(path))
            db.set("existing", "hello")
            db.execute("PRAGMA user_version=2")
            db.close()
            db = DB(str(path))
            self.assertEqual(db.get("existing"), "hello")
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertIsNotNone(db.one("SELECT name FROM sqlite_master WHERE name='admission_requests'"))
            db.close()
