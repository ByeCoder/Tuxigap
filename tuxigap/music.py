"""Bot-facing music controls. The optional MTProto worker owns all audio playback."""

from dataclasses import dataclass
from html import escape
import json
import os
from pathlib import Path
import re
import time

from .i18n import tr
from .ui import button

COMMANDS = {
    "music",
    "mplay",
    "mpause",
    "mresume",
    "mskip",
    "mstop",
    "mvolume",
    "mqueue",
    "mlibrary",
    "mclear",
    "mremove",
    "mrepeat",
    "mshuffle",
    "mjobs",
}
ACTIONS = {"pause", "resume", "skip", "stop", "volume", "clear", "remove", "repeat", "shuffle", "enqueue"}


@dataclass(frozen=True)
class MusicSettings:
    enabled: bool = False
    chats: tuple[int, ...] = ()
    library: str = "data/music/library.json"
    media: str = "data/music/media"
    queue_limit: int = 30

    @classmethod
    def load(cls):
        enabled = os.getenv("MUSIC_ENABLED", "0").lower() in ("1", "true", "yes")
        chats = tuple(int(x.strip()) for x in os.getenv("MUSIC_CHATS", "").split(",") if x.strip())
        if any(c >= 0 for c in chats) or enabled and not chats:
            raise ValueError("Please set MUSIC_CHATS to the negative IDs of your authorized music groups.")
        return cls(
            enabled,
            chats,
            os.getenv("MUSIC_LIBRARY", "data/music/library.json"),
            os.getenv("MUSIC_MEDIA", "data/music/media"),
        )

    def tracks(self):
        path = Path(self.library)
        if not path.exists():
            return {}
        rows = json.loads(path.read_text())
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError(tr("music.library_invalid"))
        result = {}
        root = Path(self.media).resolve()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(tr("music.library_invalid"))
            identity = str(row.get("id", ""))
            if not re.fullmatch("[a-z0-9_-]{1,40}", identity) or identity in result:
                raise ValueError(tr("music.library_invalid"))
            relative = str(row.get("file", ""))
            target = (root / relative).resolve()
            if not relative or not target.is_relative_to(root) or target == root or not target.is_file():
                raise ValueError(tr("music.library_invalid"))
            result[identity] = {
                "id": identity,
                "title": str(row.get("title", identity))[:100],
                "file": str(target),
            }
        return result


class Music:
    def __init__(self, bot, settings=None):
        self.bot, self.db, self.tg = bot, bot.db, bot.tg
        self.settings = settings or MusicSettings.load()

    async def require(self, chat, user):
        if not self.settings.enabled or chat not in self.settings.chats:
            raise ValueError(tr("music.setup"))
        await self.bot.hub.require(chat, user, "events", "can_manage_video_chats")

    def enqueue_job(self, chat, actor, action, payload, request):
        if action not in ACTIONS:
            raise ValueError(tr("hub.unknown_action"))
        if len(request) > 200:
            raise ValueError(tr("music.invalid"))
        self.db.execute(
            "INSERT OR IGNORE INTO music_jobs(chat,actor,action,payload,request,created) VALUES(?,?,?,?,?,?)",
            (chat, actor, action, json.dumps(payload), request, int(time.time())),
        )
        return self.db.one("SELECT id FROM music_jobs WHERE request=?", (request,))["id"]

    def keyboard(self, chat):
        return [
            [button(tr("music.pause"), f"m:{chat}:pause"), button(tr("music.resume"), f"m:{chat}:resume")],
            [
                button(tr("music.skip"), f"m:{chat}:skip"),
                button(tr("music.stop"), f"m:{chat}:stop", style="danger"),
            ],
            [button(tr("music.queue"), f"m:{chat}:queue"), button(tr("music.library"), f"m:{chat}:library")],
            [button("🔉 50%", f"m:{chat}:volume:50"), button("🔊 100%", f"m:{chat}:volume:100")],
        ]

    async def panel(self, chat, user, destination):
        await self.require(chat, user)
        state = self.db.one("SELECT * FROM music_state WHERE chat=?", (chat,))
        status = state["status"] if state else "idle"
        row = (
            self.db.one("SELECT title FROM music_queue WHERE id=?", (state["current"],))
            if state and state["current"]
            else None
        )
        fresh = int(time.time()) - self.db.get("music_heartbeat", 0) < 30
        await self.tg.send(
            destination,
            tr(
                "music.panel",
                status=escape(status),
                title=escape(row["title"] if row else "—"),
                worker=tr("music.online") if fresh else tr("music.offline"),
            ),
            self.keyboard(chat),
        )

    async def queue(self, chat, user, destination):
        await self.require(chat, user)
        rows = self.db.all(
            "SELECT id,title,state FROM music_queue WHERE chat=? AND state IN ('queued','playing') ORDER BY CASE WHEN state='playing' THEN 0 ELSE 1 END,position,id LIMIT 30",
            (chat,),
        )
        text = "\n".join(
            f"<code>{r['id']}</code> · {escape(r['title'])} · {escape(r['state'])}" for r in rows
        )
        await self.tg.send(destination, tr("music.queue_title") + "\n" + (text or tr("music.empty")))

    async def library(self, chat, user, destination):
        await self.require(chat, user)
        tracks = self.settings.tracks()
        lines = [f"<code>{escape(r['id'])}</code> · {escape(r['title'])}" for r in list(tracks.values())[:30]]
        rows = [[button(r["title"][:40], f"m:{chat}:play:{r['id']}")] for r in list(tracks.values())[:10]]
        await self.tg.send(destination, tr("music.library_help") + "\n" + "\n".join(lines), rows)

    async def callback(self, q, parts):
        chat, user, action = int(parts[1]), q["from"]["id"], parts[2]
        await self.require(chat, user)
        await self.tg.call("answerCallbackQuery", callback_query_id=q["id"])
        destination = q["message"]["chat"]["id"]
        if action == "panel":
            return await self.panel(chat, user, destination)
        if action == "queue":
            return await self.queue(chat, user, destination)
        if action == "library":
            return await self.library(chat, user, destination)
        args = parts[3] if len(parts) > 3 else ""
        cmd = "mplay" if action == "play" else "m" + action
        if cmd not in COMMANDS:
            raise ValueError(tr("hub.unknown_action"))
        return await self.control(chat, user, cmd, args, q["message"], "callback:" + q["id"], destination)

    async def command(self, cmd, args, message):
        chat, user = message["chat"]["id"], message["from"]["id"]
        if chat > 0:
            raise ValueError(tr("hub.in_group"))
        if cmd == "music" and not self.settings.enabled:
            return await self.tg.send(chat, tr("music.setup"))
        await self.require(chat, user)
        if cmd == "music":
            return await self.panel(chat, user, chat)
        if cmd == "mjobs":
            rows = self.db.all(
                "SELECT id,action,state,error FROM music_jobs WHERE chat=? ORDER BY id DESC LIMIT 10", (chat,)
            )
            return await self.tg.send(
                chat,
                "\n".join(f"{r['id']} · {escape(r['action'])} · {escape(r['state'])}" for r in rows)
                or tr("music.empty"),
            )
        if cmd == "mqueue":
            return await self.queue(chat, user, chat)
        if cmd == "mlibrary":
            return await self.library(chat, user, chat)
        return await self.control(
            chat, user, cmd, args, message, f"message:{chat}:{message['message_id']}:{cmd}", chat
        )

    async def control(self, chat, user, cmd, args, message, request, destination):
        await self.require(chat, user)
        if not self.db.cooldown(chat, user, "music_control", 2):
            raise ValueError(tr("party.wait"))
        action = cmd[1:]
        payload = {}
        if cmd == "mplay":
            action = "enqueue"
            audio = message.get("reply_to_message", {}).get("audio")
            if audio:
                if (
                    not 1 <= audio.get("file_size", 0) <= 20 * 1024 * 1024
                    or not 5 <= audio.get("duration", 0) <= 1800
                ):
                    raise ValueError(tr("music.audio_limit"))
                payload = {
                    "kind": "telegram",
                    "file_id": audio["file_id"],
                    "title": str(audio.get("title") or audio.get("file_name") or "Telegram audio")[:100],
                }
            else:
                tracks = self.settings.tracks()
                if args not in tracks:
                    raise ValueError(tr("music.track_help"))
                payload = {"kind": "library", "track": args, "title": tracks[args]["title"]}
        elif cmd == "mvolume":
            if not args.isdigit() or not 1 <= int(args) <= 100:
                raise ValueError(tr("music.volume_help"))
            payload = {"value": int(args)}
        elif cmd == "mremove":
            if not args.isdigit():
                raise ValueError(tr("music.remove_help"))
            payload = {"id": int(args)}
        elif cmd == "mrepeat":
            if args not in ("off", "one", "all"):
                raise ValueError(tr("music.repeat_help"))
            payload = {"mode": args}
        elif action not in ACTIONS:
            raise ValueError(tr("music.invalid"))
        pending = self.db.one(
            "SELECT count(*) n FROM music_jobs WHERE chat=? AND state IN ('pending','running')", (chat,)
        )["n"]
        if pending >= 30:
            raise ValueError(tr("music.busy"))
        identity = self.enqueue_job(chat, user, action, payload, request)
        await self.tg.send(destination, tr("music.accepted", id=identity), self.keyboard(chat))
