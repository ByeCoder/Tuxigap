"""Staff hub, community lifecycle, ranks, channel tools and call event tracking."""

from html import escape
import json
import re
import time
from urllib.parse import urlparse

from .i18n import tr, using_language
from .party import Party
from .presentation import STYLES, rich_text
from .ui import button

ROLES = {
    "manager": {"admission", "tags", "content", "events", "analytics", "moderation"},
    "moderator": {"admission", "tags", "moderation"},
    "editor": {"content"},
    "host": {"events"},
    "analyst": {"analytics"},
}
ROLE_RIGHTS = {
    "moderator": {"can_delete_messages", "can_restrict_members", "can_invite_users", "can_manage_tags"},
    "host": {"can_manage_video_chats", "can_invite_users"},
    "editor": {"can_post_messages", "can_edit_messages", "can_pin_messages"},
    "manager": {
        "can_delete_messages",
        "can_restrict_members",
        "can_invite_users",
        "can_change_info",
        "can_manage_video_chats",
        "can_manage_tags",
        "can_post_messages",
        "can_edit_messages",
        "can_pin_messages",
    },
}
ALL_RIGHTS = set.union(*ROLE_RIGHTS.values()) | {
    "can_promote_members",
    "can_manage_topics",
    "can_post_stories",
    "can_edit_stories",
    "can_delete_stories",
    "can_manage_direct_messages",
    "is_anonymous",
    "can_manage_chat",
    "can_send_welcome_messages",
}
RANKS = [
    (0, "New friend"),
    (100, "Regular"),
    (300, "Explorer"),
    (700, "Helper"),
    (1500, "Community star"),
    (3000, "Champion"),
    (6000, "Legend"),
]
COMMANDS = {
    "staffpanel",
    "staff",
    "roles",
    "role",
    "promote",
    "demote",
    "admintitle",
    "rank",
    "ranks",
    "rankset",
    "tag",
    "untag",
    "tags",
    "tagmembers",
    "membertag",
    "members",
    "joinmode",
    "requests",
    "template",
    "theme",
    "buttonemoji",
    "emojiid",
    "emojitext",
    "channel",
    "chatinfo",
    "title",
    "description",
    "post",
    "editpost",
    "deletepost",
    "pinpost",
    "unpinpost",
    "callpanel",
    "calllink",
    "callannounce",
    "party",
    "guess",
    "answer",
    "stopgame",
    "scores",
}


def target_and_text(message, args):
    replied = message.get("reply_to_message", {})
    user = replied.get("from", {}).get("id") if not replied.get("sender_chat") else None
    if user:
        return user, args.strip()
    first, _, rest = args.partition(" ")
    if not first.isdigit() or int(first) <= 0:
        raise ValueError(tr("hub.target"))
    return int(first), rest.strip()


def valid_label(text):
    return 1 <= len(text) <= 16 and all(c.isalnum() or c in " _-" for c in text)


def rank_for(conf, xp):
    ladder = conf.get("rank_ladder", RANKS)
    eligible = [(n, label) for n, label in ladder if xp >= n]
    threshold, label = eligible[-1] if eligible else ladder[0]
    next_item = next(((n, name) for n, name in ladder if n > xp), None)
    return label, threshold, next_item


class Hub:
    def __init__(self, bot):
        self.bot, self.db, self.tg = bot, bot.db, bot.tg
        self.party = Party(bot)

    async def allowed(self, chat, user, capability, right=None):
        member = await self.tg.call("getChatMember", chat_id=chat, user_id=user)
        if member["status"] == "creator":
            return True
        if member["status"] == "administrator":
            return not right or bool(member.get(right))
        if member["status"] not in ("member", "restricted") or (
            member["status"] == "restricted" and not member.get("is_member")
        ):
            return False
        role = self.db.one("SELECT role FROM staff_roles WHERE chat=? AND user=?", (chat, user))
        return bool(role and capability in ROLES.get(role["role"], set()))

    async def require(self, chat, user, capability, right=None):
        if not await self.allowed(chat, user, capability, right):
            raise ValueError(tr("hub.denied"))

    async def owner(self, chat, user):
        member = await self.tg.call("getChatMember", chat_id=chat, user_id=user)
        if member["status"] != "creator":
            raise ValueError(tr("hub.owner_only"))

    async def protect_staff(self, chat, actor, target):
        if await self.bot.admin(chat, actor):
            return
        actor_role = self.db.one("SELECT role FROM staff_roles WHERE chat=? AND user=?", (chat, actor))
        target_role = self.db.one("SELECT role FROM staff_roles WHERE chat=? AND user=?", (chat, target))
        order = {"manager": 50, "moderator": 40, "editor": 30, "host": 20, "analyst": 10}
        if target_role and order.get(target_role["role"], 0) >= order.get(
            (actor_role or {}).get("role", ""), 0
        ):
            raise ValueError(tr("hub.staff_protected"))

    async def panel(self, chat, user, destination):
        await self.bot.require_member(chat, user)
        native = await self.bot.admin(chat, user)
        role = self.db.one("SELECT role FROM staff_roles WHERE chat=? AND user=?", (chat, user))
        if not native and not role:
            raise ValueError(tr("hub.denied"))
        rows = []
        for capability, routes in [
            ("analytics", [("hub.analytics", "stats"), ("hub.members", "members")]),
            ("moderation", [("hub.moderation", "moderation")]),
            ("admission", [("hub.requests", "requests")]),
            ("tags", [("hub.tags", "tags")]),
            ("events", [("hub.calls", "calls"), ("hub.games", "games")]),
            ("content", [("hub.channel", "channel")]),
        ]:
            if await self.allowed(chat, user, capability):
                rows.append([button(tr(label), f"h:{chat}:{route}") for label, route in routes])
        if await self.allowed(chat, user, "events", "can_manage_video_chats"):
            rows.append([button(tr("music.title"), f"m:{chat}:panel")])
        if native:
            rows += [
                [button(tr("hub.native_panel"), f"a:{chat}:home")],
                [
                    button(tr("hub.roles"), "h:" + str(chat) + ":roles"),
                    button(tr("hub.appearance"), f"h:{chat}:appearance"),
                ],
                [button(tr("hub.lifecycle"), f"h:{chat}:lifecycle")],
            ]
        await self.tg.send(
            destination, tr("hub.panel", role=escape(role["role"] if role else "Telegram admin")), rows
        )

    def membership(self, event, after):
        chat, user = event["chat"]["id"], event["new_chat_member"]["user"]["id"]
        old, new = event["old_chat_member"]["status"], event["new_chat_member"]["status"]
        ts = int(event.get("date", time.time()))
        fresh = self.db.execute(
            "INSERT OR IGNORE INTO member_events VALUES(?,?,?,?,?,?,?)",
            (chat, user, ts, old, new, event.get("from", {}).get("id", 0), int(after)),
        ).rowcount
        if not fresh:
            return False
        current = self.db.one("SELECT ts FROM member_presence WHERE chat=? AND user=?", (chat, user))
        if current and ts < current["ts"]:
            return False
        if not current or ts >= current["ts"]:
            self.db.execute(
                "INSERT OR REPLACE INTO member_presence VALUES(?,?,?,?)", (chat, user, int(after), ts)
            )
        if not after:
            self.db.execute("DELETE FROM staff_roles WHERE chat=? AND user=?", (chat, user))
        return True

    async def goodbye(self, event):
        chat = event["chat"]["id"]
        conf = self.db.chat(chat)["settings"]
        if not conf["goodbye"] or event["chat"]["type"] not in ("group", "supergroup"):
            return
        target = event["new_chat_member"]["user"]
        if target["id"] != self.bot.bot_id:
            text = str(conf["goodbye_text"]).replace("{name}", target.get("first_name", "friend"))
            await self.tg.send(chat, rich_text(text))

    async def join_request(self, request):
        chat, user = request["chat"]["id"], request["from"]["id"]
        self.db.register(request["chat"])
        conf = self.db.chat(chat)["settings"]
        date = int(request.get("date", time.time()))
        previous = self.db.one(
            "SELECT * FROM admission_requests WHERE chat=? AND user=? ORDER BY id DESC LIMIT 1", (chat, user)
        )
        if previous and (
            previous["requested"] > date or (previous["requested"] == date and previous["state"] != "pending")
        ):
            return
        if previous and previous["requested"] == date:
            rid = previous["id"]
        else:
            self.db.execute(
                "UPDATE admission_requests SET state='superseded' WHERE chat=? AND user=? AND state='pending'",
                (chat, user),
            )
            rid = self.db.execute(
                "INSERT INTO admission_requests(chat,user,name,requested) VALUES(?,?,?,?)",
                (chat, user, request["from"].get("first_name", "friend")[:100], date),
            ).lastrowid
            self.db.bump(chat, "join_requests")
        federated = self.db.one(
            "SELECT 1 FROM federation_bans b JOIN federation_chats c ON b.fid=c.fid WHERE c.chat=? AND c.state='active' AND b.user=? AND b.active=1",
            (chat, user),
        )
        if federated or (conf["bots"] and request["from"].get("is_bot")):
            if not conf["dry_run"]:
                await self.decide_request(rid, 0, False, automatic=True)
            return
        if conf["paid_gate"]:
            return await self.decide_request(rid, 0, self.bot.billing.active(chat, user), automatic=True)
        trusted = bool(self.db.one("SELECT 1 FROM approved WHERE chat=? AND user=?", (chat, user)))
        approve = conf["join_mode"] == "auto" or conf["join_mode"] == "trusted" and trusted
        if approve and conf["enabled"] and not conf["dry_run"]:
            return await self.decide_request(rid, 0, True, automatic=True)
        if conf["join_mode"] != "off" and conf["log_chat"]:
            await self.bot.log_action(
                chat,
                tr("hub.request_notice", user=user, name=escape(request["from"].get("first_name", "friend"))),
                [
                    [
                        button(tr("hub.accept"), f"h:{chat}:request:{rid}:yes", style="success"),
                        button(tr("hub.decline"), f"h:{chat}:request:{rid}:no", style="danger"),
                    ]
                ],
            )

    async def decide_request(self, rid, actor, approve, automatic=False):
        row = self.db.one("SELECT * FROM admission_requests WHERE id=?", (rid,))
        if not row or row["state"] != "pending":
            raise ValueError(tr("hub.request_stale"))
        chat, user = row["chat"], row["user"]
        if not automatic:
            await self.require(chat, actor, "admission", "can_invite_users")
        conf = self.db.chat(chat)["settings"]
        if approve:
            if conf["paid_gate"] and not self.bot.billing.active(chat, user):
                raise ValueError(tr("hub.paid_required"))
            if self.db.one(
                "SELECT 1 FROM federation_bans b JOIN federation_chats c ON b.fid=c.fid WHERE c.chat=? AND c.state='active' AND b.user=? AND b.active=1",
                (chat, user),
            ):
                raise ValueError(tr("hub.federation_block"))
        await self.tg.call(
            "approveChatJoinRequest" if approve else "declineChatJoinRequest", chat_id=chat, user_id=user
        )
        self.db.execute(
            "UPDATE admission_requests SET state=? WHERE id=?", ("approved" if approve else "declined", rid)
        )
        self.db.bump(chat, "requests_approved" if approve else "requests_declined")
        self.db.audit(chat, user, 0, actor, "join_request", "approved" if approve else "declined")

    async def requests(self, chat, user, destination):
        await self.require(chat, user, "admission", "can_invite_users")
        rows = self.db.all(
            "SELECT * FROM admission_requests WHERE chat=? AND state='pending' ORDER BY id DESC LIMIT 10",
            (chat,),
        )
        keyboard = [
            [
                button(
                    tr("hub.accept") + " " + r["name"][:25],
                    f"h:{chat}:request:{r['id']}:yes",
                    style="success",
                ),
                button(tr("hub.decline"), f"h:{chat}:request:{r['id']}:no", style="danger"),
            ]
            for r in rows
        ]
        await self.tg.send(destination, tr("hub.requests_help") if rows else tr("hub.no_requests"), keyboard)

    async def native_role(self, chat, actor, user, role, title=""):
        await self.bot.require_admin(chat, actor, "can_promote_members")
        if role not in ROLE_RIGHTS and role != "none":
            raise ValueError(tr("hub.promote_usage"))
        if user in (actor, self.bot.bot_id):
            raise ValueError(tr("hub.protected"))
        target = await self.tg.call("getChatMember", chat_id=chat, user_id=user)
        if target["status"] == "creator" or (
            target["status"] == "administrator" and not target.get("can_be_edited")
        ):
            raise ValueError(tr("hub.protected"))
        if target["status"] not in ("member", "administrator"):
            raise ValueError(tr("hub.target_member"))
        bot_member = await self.tg.call("getChatMember", chat_id=chat, user_id=self.bot.bot_id)
        actor_member = await self.tg.call("getChatMember", chat_id=chat, user_id=actor)
        if bot_member["status"] != "creator" and not bot_member.get("can_promote_members"):
            raise ValueError(tr("hub.bot_promote"))
        kind = self.db.chat(chat)["kind"]
        grants = set(ROLE_RIGHTS.get(role, set()))
        grants -= (
            {"can_post_messages", "can_edit_messages"}
            if kind != "channel"
            else {"can_pin_messages", "can_manage_tags"}
        )
        if any(
            (actor_member["status"] != "creator" and not actor_member.get(r))
            or (bot_member["status"] != "creator" and not bot_member.get(r))
            for r in grants
        ):
            raise ValueError(tr("hub.subset"))
        if title and not valid_label(title):
            raise ValueError(tr("hub.label_invalid"))
        await self.tg.call(
            "promoteChatMember", chat_id=chat, user_id=user, **{r: r in grants for r in ALL_RIGHTS}
        )
        if title and role != "none" and kind == "supergroup":
            await self.tg.call(
                "setChatAdministratorCustomTitle", chat_id=chat, user_id=user, custom_title=title
            )
        self.db.audit(chat, user, 0, actor, "native_role", role)

    async def call_event(self, message):
        for kind in ("scheduled", "started", "ended", "participants_invited"):
            key = "video_chat_" + kind
            if key not in message:
                continue
            chat, mid = message["chat"]["id"], message["message_id"]
            payload = message[key]
            fresh = self.db.execute(
                "INSERT OR IGNORE INTO call_events VALUES(?,?,?,?,?)",
                (chat, mid, kind, int(message.get("date", time.time())), json.dumps(payload)),
            ).rowcount
            if not fresh:
                return True
            self.db.set(
                f"call:{chat}", {"kind": kind, "date": int(message.get("date", time.time())), **payload}
            )
            self.db.bump(chat, "calls_" + kind)
            if self.db.chat(chat)["settings"]["call_notices"]:
                await self.tg.send(chat, tr("hub.call_event", event=tr("hub.call_" + kind)))
            return True
        return False

    async def call_panel(self, chat, actor, destination):
        await self.require(chat, actor, "events", "can_manage_video_chats")
        state = self.db.get(f"call:{chat}", {})
        status = tr("hub.call_" + state["kind"]) if state else tr("hub.unknown")
        link = self.db.chat(chat)["settings"]["call_link"]
        rows = [[{"text": tr("hub.join_call"), "url": link}]] if link else []
        rows.append([button(tr("hub.call_announce"), f"h:{chat}:announce")])
        await self.tg.send(destination, tr("hub.call_help", status=status), rows)

    async def chat_info(self, chat, actor, destination):
        await self.require(chat, actor, "content")
        info = await self.tg.call("getChat", chat_id=chat)
        count = await self.tg.call("getChatMemberCount", chat_id=chat)
        linked = info.get("linked_chat_id", 0)
        text = tr(
            "hub.chat_info",
            title=escape(info.get("title", "")),
            kind=escape(info["type"]),
            count=count,
            linked=linked or "—",
        )
        text += "\n" + tr("hub.channel_help")
        rows = []
        if (
            linked
            and self.db.one("SELECT 1 FROM chats WHERE id=?", (linked,))
            and await self.bot.admin(linked, actor)
        ):
            rows.append([button(tr("hub.linked_panel"), f"a:{linked}:home")])
        await self.tg.send(destination, text, rows)

    async def member_report(self, chat, actor, destination):
        await self.require(chat, actor, "analytics")
        counts = self.db.one(
            "SELECT count(*) observed,coalesce(sum(active),0) active FROM member_presence WHERE chat=?",
            (chat,),
        )
        roles = self.db.one("SELECT count(*) n FROM staff_roles WHERE chat=?", (chat,))["n"]
        await self.tg.send(
            destination,
            tr("hub.member_report", observed=counts["observed"], active=counts["active"], staff=roles),
        )

    def role_report(self, chat):
        rows = self.db.all("SELECT * FROM staff_roles WHERE chat=? ORDER BY role,user LIMIT 40", (chat,))
        return (
            tr("hub.role_help")
            + "\n"
            + "\n".join(f"<code>{r['user']}</code> · {escape(r['role'])}" for r in rows)
        )

    async def callback(self, q, parts):
        chat, action, user = int(parts[1]), parts[2], q["from"]["id"]
        destination = q["message"]["chat"]["id"]
        await self.bot.require_member(chat, user)
        await self.tg.call("answerCallbackQuery", callback_query_id=q["id"])
        if action == "staff":
            return await self.panel(chat, user, destination)
        if action == "request":
            row = self.db.one("SELECT chat FROM admission_requests WHERE id=?", (int(parts[3]),))
            if not row or row["chat"] != chat:
                raise ValueError(tr("hub.request_stale"))
            await self.decide_request(int(parts[3]), user, parts[4] == "yes")
            return await self.tg.send(destination, tr("hub.saved"))
        if action == "requests":
            return await self.requests(chat, user, destination)
        if action == "stats":
            await self.require(chat, user, "analytics")
            return await self.bot.send_stats(chat, destination, "day")
        if action == "members":
            return await self.member_report(chat, user, destination)
        if action == "calls":
            return await self.call_panel(chat, user, destination)
        if action == "channel":
            return await self.chat_info(chat, user, destination)
        if action == "game":
            if destination != chat:
                raise ValueError(tr("party.in_group"))
            return await self.party.start(chat, user, parts[3])
        if action == "games":
            return await self.tg.send(destination, tr("party.menu"), self.party.menu(chat))
        if action == "scores":
            return await self.tg.send(destination, self.party.scores(chat))
        if action == "announce":
            return await self.announce_call(chat, user, destination)
        if action == "moderation":
            await self.require(chat, user, "moderation")
            return await self.tg.send(destination, tr("hub.moderation_help"))
        if action == "theme":
            await self.bot.require_admin(chat, user)
            if parts[3] not in STYLES:
                raise ValueError(tr("hub.unknown_action"))
            self.db.setting(chat, "button_style", parts[3])
            return await self.tg.send(destination, tr("hub.saved"))
        if action == "joinmode":
            await self.bot.require_admin(chat, user, "can_invite_users")
            if parts[3] not in ("manual", "auto", "trusted", "off"):
                raise ValueError(tr("hub.unknown_action"))
            self.db.setting(chat, "join_mode", parts[3])
            return await self.tg.send(destination, tr("hub.saved"))
        if action == "toggle":
            await self.bot.require_admin(chat, user)
            if parts[3] not in ("goodbye", "welcome", "call_notices"):
                raise ValueError(tr("hub.unknown_action"))
            conf = self.db.chat(chat)["settings"]
            self.db.setting(chat, parts[3], not conf[parts[3]])
            return await self.tg.send(destination, tr("hub.saved"))
        if action in ("roles", "appearance", "lifecycle", "tags"):
            if action == "tags":
                await self.require(chat, user, "tags")
                text = tr("hub.tag_help")
            else:
                await self.bot.require_admin(chat, user)
                text = self.role_report(chat) if action == "roles" else tr("hub." + action + "_help")
            rows = []
            if action == "appearance":
                rows = [
                    [
                        button(tr("hub.blue"), f"h:{chat}:theme:primary", style="primary"),
                        button(tr("hub.green"), f"h:{chat}:theme:success", style="success"),
                        button(tr("hub.red"), f"h:{chat}:theme:danger", style="danger"),
                    ],
                    [button(tr("hub.default_style"), f"h:{chat}:theme:default")],
                ]
            if action == "lifecycle":
                conf = self.db.chat(chat)["settings"]
                rows = [
                    [
                        button(
                            tr("hub.mode_" + mode) + (" ✓" if conf["join_mode"] == mode else ""),
                            f"h:{chat}:joinmode:{mode}",
                        )
                        for mode in ("manual", "auto")
                    ],
                    [
                        button(
                            tr("hub.mode_" + mode) + (" ✓" if conf["join_mode"] == mode else ""),
                            f"h:{chat}:joinmode:{mode}",
                        )
                        for mode in ("trusted", "off")
                    ],
                ]
                for key, label in [
                    ("welcome", "Welcome"),
                    ("goodbye", "Goodbye"),
                    ("call_notices", "Call notices"),
                ]:
                    rows.append(
                        [
                            button(
                                tr("hub.toggle_" + key) + (" ✅" if conf[key] else " ❌"),
                                f"h:{chat}:toggle:{key}",
                            )
                        ]
                    )
            return await self.tg.send(destination, text, rows)
        raise ValueError(tr("hub.unknown_action"))

    async def announce_call(self, chat, actor, destination):
        await self.require(chat, actor, "events", "can_manage_video_chats")
        link = self.db.chat(chat)["settings"]["call_link"]
        if not link:
            raise ValueError(tr("hub.call_link_needed"))
        if not self.db.cooldown(chat, actor, "call_notice", 60):
            raise ValueError(tr("party.wait"))
        await self.tg.send(chat, tr("hub.call_invite"), [[{"text": tr("hub.join_call"), "url": link}]])

    async def command(self, cmd, args, message):
        chat, actor = message["chat"]["id"], message["from"]["id"]
        private = message["chat"]["type"] == "private"
        if cmd == "emojiid":
            replied = message.get("reply_to_message", message)
            ids = [
                e["custom_emoji_id"]
                for e in replied.get("entities", []) + replied.get("caption_entities", [])
                if e.get("custom_emoji_id")
            ]
            if replied.get("sticker", {}).get("custom_emoji_id"):
                ids.append(replied["sticker"]["custom_emoji_id"])
            return await self.tg.send(
                chat,
                "\n".join("<code>" + escape(i) + "</code>" for i in dict.fromkeys(ids))
                or tr("hub.emoji_help"),
            )
        if private:
            # Explicit destination keeps channel control out of unauthenticated channel posts.
            if cmd not in (
                "channel",
                "chatinfo",
                "post",
                "editpost",
                "deletepost",
                "pinpost",
                "unpinpost",
                "title",
                "description",
                "callpanel",
                "staffpanel",
            ):
                raise ValueError(tr("hub.in_group"))
            first, _, args = args.partition(" ")
            if not re.fullmatch(r"-\d+", first):
                raise ValueError(tr("hub.private_target"))
            chat = int(first)
            self.db.chat(chat)
        conf = self.db.chat(chat)["settings"]
        destination = message["chat"]["id"]
        if cmd in ("staffpanel", "staff"):
            return await self.panel(chat, actor, destination)
        if cmd in ("roles", "role"):
            await self.owner(chat, actor)
            if cmd == "roles":
                return await self.tg.send(destination, self.role_report(chat))
            target, role = target_and_text(message, args)
            if role not in {*ROLES, "none"}:
                raise ValueError(tr("hub.role_usage"))
            if target == self.bot.bot_id or await self.bot.admin(chat, target):
                raise ValueError(tr("hub.protected"))
            await self.bot.require_member(chat, target)
            if role == "none":
                self.db.execute("DELETE FROM staff_roles WHERE chat=? AND user=?", (chat, target))
            else:
                self.db.execute(
                    "INSERT OR REPLACE INTO staff_roles VALUES(?,?,?,?)", (chat, target, role, actor)
                )
            self.db.audit(chat, target, 0, actor, "staff_role", role)
        elif cmd in ("promote", "demote"):
            target, value = target_and_text(message, args)
            role, _, title = value.partition("|")
            await self.native_role(
                chat, actor, target, "none" if cmd == "demote" else role.strip(), title.strip()
            )
        elif cmd == "admintitle":
            await self.bot.require_admin(chat, actor, "can_promote_members")
            target, title = target_and_text(message, args)
            info = await self.tg.call("getChatMember", chat_id=chat, user_id=target)
            if info["status"] != "administrator" or not info.get("can_be_edited"):
                raise ValueError(tr("hub.protected"))
            if title != "-" and not valid_label(title):
                raise ValueError(tr("hub.label_invalid"))
            await self.tg.call(
                "setChatAdministratorCustomTitle",
                chat_id=chat,
                user_id=target,
                custom_title="" if title == "-" else title,
            )
        elif cmd in ("rank", "ranks", "rankset"):
            if cmd == "rankset":
                await self.owner(chat, actor)
                if args == "reset":
                    ladder = RANKS
                else:
                    ladder = []
                    for piece in args.split("|"):
                        number, _, label = piece.strip().partition(":")
                        if not number.isdigit() or not valid_label(label.strip()):
                            raise ValueError(tr("hub.rankset_help"))
                        ladder.append((int(number), label.strip()))
                    if (
                        not 2 <= len(ladder) <= 12
                        or ladder[0][0] != 0
                        or any(a[0] >= b[0] for a, b in zip(ladder, ladder[1:]))
                        or ladder[-1][0] > 10**7
                    ):
                        raise ValueError(tr("hub.rankset_help"))
                self.db.setting(chat, "rank_ladder", ladder)
            elif cmd == "ranks":
                return await self.tg.send(
                    destination,
                    tr("hub.rank_help")
                    + "\n"
                    + "\n".join(f"{xp:,} XP · {escape(label)}" for xp, label in conf["rank_ladder"]),
                )
            else:
                member = self.db.member(chat, actor, message["from"].get("first_name", ""))
                label, threshold, nxt = rank_for(conf, member["xp"])
                goal = (
                    tr("hub.rank_next", remaining=max(0, nxt[0] - member["xp"]), name=escape(nxt[1]))
                    if nxt
                    else tr("hub.rank_max")
                )
                return await self.tg.send(
                    destination,
                    tr(
                        "hub.rank_status",
                        name=escape(label),
                        xp=member["xp"],
                        level=member["xp"] // 100 + 1,
                        goal=goal,
                    ),
                )
        elif cmd in ("tag", "untag", "membertag"):
            await self.require(chat, actor, "tags", "can_manage_tags" if cmd == "membertag" else None)
            target, label = target_and_text(message, args)
            await self.bot.require_member(chat, target)
            if not valid_label(label) and not (cmd == "membertag" and label == "-"):
                raise ValueError(tr("hub.label_invalid"))
            if cmd == "membertag":
                if await self.bot.admin(chat, target):
                    raise ValueError(tr("hub.membertag_admin"))
                await self.tg.call(
                    "setChatMemberTag", chat_id=chat, user_id=target, tag="" if label == "-" else label
                )
            elif cmd == "untag":
                self.db.execute(
                    "DELETE FROM member_tags WHERE chat=? AND user=? AND label=?",
                    (chat, target, label.casefold()),
                )
            else:
                count = self.db.one(
                    "SELECT count(*) n FROM member_tags WHERE chat=? AND user=?", (chat, target)
                )["n"]
                if count >= 10:
                    raise ValueError(tr("hub.too_many_tags"))
                self.db.execute(
                    "INSERT OR IGNORE INTO member_tags VALUES(?,?,?)", (chat, target, label.casefold())
                )
            self.db.audit(chat, target, 0, actor, cmd, label)
        elif cmd == "tags":
            target = message.get("reply_to_message", {}).get("from", {}).get("id", actor)
            if target != actor:
                await self.require(chat, actor, "tags")
            rows = self.db.all(
                "SELECT label FROM member_tags WHERE chat=? AND user=? ORDER BY label", (chat, target)
            )
            return await self.tg.send(
                destination,
                tr("hub.tags_for", user=target) + escape(", ".join(r["label"] for r in rows) or "—"),
            )
        elif cmd == "tagmembers":
            await self.require(chat, actor, "tags")
            label, _, body = args.partition(" ")
            if not valid_label(label) or not body or len(body) > 1000:
                raise ValueError(tr("hub.tagmembers_help"))
            if not self.db.cooldown(chat, actor, "tag_members", 60):
                raise ValueError(tr("party.wait"))
            mentions = []
            for row in self.db.all(
                "SELECT user FROM member_tags WHERE chat=? AND label=? ORDER BY user LIMIT 20",
                (chat, label.casefold()),
            ):
                info = await self.tg.call("getChatMember", chat_id=chat, user_id=row["user"])
                if info["status"] in ("member", "administrator", "creator"):
                    mentions.append(f'<a href="tg://user?id={row["user"]}">{row["user"]}</a>')
            return await self.tg.send(chat, rich_text(body) + "\n" + " ".join(mentions))
        elif cmd == "members":
            return await self.member_report(chat, actor, destination)
        elif cmd == "requests":
            return await self.requests(chat, actor, destination)
        elif cmd == "joinmode":
            await self.bot.require_admin(chat, actor, "can_invite_users")
            if args not in ("off", "manual", "auto", "trusted"):
                raise ValueError(tr("hub.joinmode_help"))
            self.db.setting(chat, "join_mode", args)
        elif cmd == "template":
            await self.bot.require_admin(chat, actor)
            kind, _, body = args.partition(" ")
            if kind not in ("welcome", "goodbye", "rules") or not 1 <= len(body) <= 2000:
                raise ValueError(tr("hub.template_help"))
            self.db.setting(chat, kind + "_text" if kind != "rules" else kind, body)
            if kind in ("welcome", "goodbye"):
                self.db.setting(chat, kind, True)
        elif cmd in ("theme", "buttonemoji", "emojitext"):
            await self.bot.require_admin(chat, actor)
            if cmd == "theme":
                if args not in STYLES:
                    raise ValueError(tr("hub.appearance_help"))
                self.db.setting(chat, "button_style", args)
            elif cmd == "buttonemoji":
                if args != "off" and not re.fullmatch(r"\d{1,30}", args):
                    raise ValueError(tr("hub.emoji_help"))
                self.db.setting(chat, "button_icon", "" if args == "off" else args)
            else:
                if not re.search(r"\[emoji:\d+\|", args):
                    raise ValueError(tr("hub.emoji_help"))
                return await self.tg.send(destination, rich_text(args))
        elif cmd in ("channel", "chatinfo"):
            return await self.chat_info(chat, actor, destination)
        elif cmd in ("title", "description", "post", "editpost", "deletepost", "pinpost", "unpinpost"):
            return await self.content_command(chat, actor, cmd, args, destination)
        elif cmd == "callpanel":
            return await self.call_panel(chat, actor, destination)
        elif cmd == "calllink":
            await self.require(chat, actor, "events", "can_manage_video_chats")
            parsed = urlparse(args)
            if args != "off" and (
                parsed.scheme != "https" or parsed.hostname != "t.me" or not parsed.path or len(args) > 500
            ):
                raise ValueError(tr("hub.calllink_help"))
            self.db.setting(chat, "call_link", "" if args == "off" else args)
        elif cmd == "callannounce":
            return await self.announce_call(chat, actor, destination)
        elif cmd == "party":
            if not args:
                return await self.tg.send(chat, tr("party.menu"), self.party.menu(chat))
            return await self.party.start(chat, actor, args)
        elif cmd in ("guess", "answer"):
            await self.bot.require_member(chat, actor)
            if not conf["fun"]:
                raise ValueError(tr("m_150682b0ae9a"))
            if not self.db.cooldown(chat, actor, "party_guess", 2):
                return
            return await self.tg.send(chat, self.party.solve(chat, actor, args))
        elif cmd == "stopgame":
            game = self.db.one(
                "SELECT * FROM party_games WHERE chat=? AND state='open' ORDER BY id DESC LIMIT 1", (chat,)
            )
            if not game:
                raise ValueError(tr("party.none"))
            if game["creator"] != actor:
                await self.require(chat, actor, "events")
            self.db.execute("UPDATE party_games SET state='cancelled' WHERE id=?", (game["id"],))
        elif cmd == "scores":
            return await self.tg.send(destination, self.party.scores(chat))
        self.db.audit(chat, 0, 0, actor, "hub_command", cmd)
        await self.tg.send(destination, tr("hub.saved"))

    async def content_command(self, chat, actor, cmd, args, destination):
        right = (
            "can_change_info"
            if cmd in ("title", "description")
            else "can_post_messages"
            if cmd == "post"
            else "can_delete_messages"
            if cmd == "deletepost"
            else "can_edit_messages"
        )
        if self.db.chat(chat)["kind"] != "channel" and cmd in ("post", "editpost"):
            right = None
        if self.db.chat(chat)["kind"] != "channel" and cmd in ("pinpost", "unpinpost"):
            right = "can_pin_messages"
        await self.require(chat, actor, "content", right)
        if cmd in ("title", "description", "post"):
            limit = {"title": 128, "description": 255, "post": 3000}[cmd]
            if not 1 <= len(args) <= limit:
                raise ValueError(tr("hub.content_length", limit=limit))
            if cmd == "post":
                result = await self.tg.send(chat, rich_text(args))
                self.db.audit(chat, 0, result["message_id"], actor, "post", "Staff post")
                return await self.tg.send(destination, tr("hub.posted", mid=result["message_id"]))
            await self.tg.call(
                "setChatTitle" if cmd == "title" else "setChatDescription",
                chat_id=chat,
                **{"title" if cmd == "title" else "description": args},
            )
        else:
            mid, _, text = args.partition(" ")
            if not mid.isdigit() or int(mid) <= 0:
                raise ValueError(tr("hub.post_id"))
            if cmd == "editpost":
                if not 1 <= len(text) <= 3000:
                    raise ValueError(tr("hub.content_length", limit=3000))
                await self.tg.call(
                    "editMessageText",
                    chat_id=chat,
                    message_id=int(mid),
                    text=rich_text(text),
                    parse_mode="HTML",
                )
            else:
                method = {
                    "deletepost": "deleteMessage",
                    "pinpost": "pinChatMessage",
                    "unpinpost": "unpinChatMessage",
                }[cmd]
                await self.tg.call(method, chat_id=chat, message_id=int(mid))
        self.db.audit(chat, 0, 0, actor, cmd, "Staff content action")
        await self.tg.send(destination, tr("hub.saved"))

    async def expire(self, now):
        for game in self.db.all(
            "SELECT * FROM party_games WHERE state='open' AND expires<=? LIMIT 20", (now,)
        ):
            self.db.execute("UPDATE party_games SET state='expired' WHERE id=?", (game["id"],))
            data = json.loads(game["data"])
            with using_language(self.db.chat(game["chat"])["settings"]["language"]):
                await self.tg.send(
                    game["chat"],
                    tr("party.expired", answer=escape(data.get("answer", data.get("words", ["—"])[-1]))),
                )
