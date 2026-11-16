"""Optional single-owner MTProto music worker. Never polls the bot's updates."""

import argparse
import asyncio
from contextlib import suppress
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import time

from .config import Config
from .db import DB
from .i18n import using_language, tr
from .music import MusicSettings
from .telegram import Telegram

log = logging.getLogger("tuxigap.music")


async def authorized(db, tg, chat, user):
    member = await tg.call("getChatMember", chat_id=chat, user_id=user)
    if member["status"] == "creator":
        return True
    if member["status"] == "administrator":
        return bool(member.get("can_manage_video_chats"))
    if member["status"] != "member" and not (member["status"] == "restricted" and member.get("is_member")):
        return False
    role = db.one("SELECT role FROM staff_roles WHERE chat=? AND user=?", (chat, user))
    return bool(role and role["role"] in ("host", "manager"))


async def process(*arguments, timeout=60):
    child = await asyncio.create_subprocess_exec(
        *arguments, stdin=subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    try:
        stdout, _ = await asyncio.wait_for(child.communicate(), timeout)
    except BaseException:
        child.kill()
        await child.wait()
        raise
    if child.returncode:
        raise ValueError("Media conversion failed")
    return stdout


class MediaLibrary:
    def __init__(self, settings, tg):
        self.settings, self.tg = settings, tg
        self.root = Path(settings.media).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def probe(self, path):
        raw = await process(
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-show_entries",
            "format=duration,format_name",
            "-of",
            "json",
            str(path),
            timeout=15,
        )
        info = json.loads(raw)["format"]
        duration = float(info["duration"])
        allowed = {"mp3", "wav", "ogg", "flac", "mov,mp4,m4a,3gp,3g2,mj2", "matroska,webm", "aac"}
        if info["format_name"] not in allowed or not 5 <= duration <= 1800:
            raise ValueError("Please choose finite audio of 5 seconds to 30 minutes")
        return duration

    async def prepare(self, payload):
        if payload["kind"] == "library":
            track = self.settings.tracks().get(payload.get("track", ""))
            if not track:
                raise ValueError("Track is no longer in the library")
            source = Path(track["file"])
            if source.stat().st_size > 100 * 1024 * 1024:
                raise ValueError("Local audio exceeds 100 MiB")
            duration = await self.probe(source)
            return str(source), duration
        if payload["kind"] != "telegram":
            raise ValueError("Unsupported audio source")
        file_id = payload["file_id"]
        info = await self.tg.call("getFile", file_id=file_id)
        relative = info.get("file_path", "")
        if (
            not relative
            or relative.startswith("/")
            or ".." in relative
            or ":" in relative
            or info.get("file_size", 0) > 20 * 1024 * 1024
        ):
            raise ValueError("Audio download is unavailable or too large")
        identity = hashlib.sha256(file_id.encode()).hexdigest()
        output = self.root / (identity + ".ogg")
        if output.is_file():
            return str(output), await self.probe(output)
        temporary = self.root / (identity + "." + secrets.token_hex(6) + ".download")
        converted = temporary.with_suffix(".ogg")
        size = 0
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                async with self.tg.client.stream("GET", self.tg.file_url + relative) as response:
                    response.raise_for_status()
                    async for data in response.aiter_bytes():
                        size += len(data)
                        if size > 20 * 1024 * 1024:
                            raise ValueError("Audio exceeds 20 MiB")
                        stream.write(data)
            duration = await self.probe(temporary)
            await process(
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(temporary),
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                "-t",
                "1800",
                "-c:a",
                "libopus",
                "-b:a",
                "96k",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(converted),
                timeout=90,
            )
            os.chmod(converted, 0o600)
            converted.replace(output)
            return str(output), duration
        finally:
            temporary.unlink(missing_ok=True)
            converted.unlink(missing_ok=True)

    def prune(self, db, days=7):
        active = {
            hashlib.sha256(json.loads(r["payload"]).get("file_id", "").encode()).hexdigest() + ".ogg"
            for r in db.all("SELECT payload FROM music_queue WHERE state IN ('queued','playing')")
            if json.loads(r["payload"]).get("kind") == "telegram"
        }
        for path in self.root.glob("*.ogg"):
            if (
                len(path.stem) == 64
                and path.name not in active
                and path.stat().st_mtime < time.time() - days * 86400
            ):
                path.unlink()


class AudioEngine:
    """Adapter for the verified py-tgcalls 3.0.1 interface."""

    def __init__(self, client, calls):
        self.client, self.calls = client, calls
        self.joined = set()

    async def play(self, chat, path):
        from pytgcalls.types import GroupCallConfig, MediaStream
        from telethon import functions

        entity = await self.client.get_input_entity(chat)
        # Never join a group/channel automatically with the helper account.
        await self.client(functions.channels.GetParticipantRequest(entity, "me"))
        stream = MediaStream(
            path, video_flags=MediaStream.Flags.IGNORE, audio_flags=MediaStream.Flags.REQUIRED
        )
        await self.calls.play(chat, stream, config=GroupCallConfig(auto_start=False))
        self.joined.add(chat)

    async def pause(self, chat):
        await self.calls.pause(chat)

    async def resume(self, chat):
        await self.calls.resume(chat)

    async def volume(self, chat, value):
        await self.calls.change_volume_call(chat, value)

    async def leave(self, chat):
        if chat in self.joined:
            from pytgcalls.exceptions import NotInCallError, NoActiveGroupCall

            try:
                await self.calls.leave_call(chat)
            except (NotInCallError, NoActiveGroupCall):
                pass
            self.joined.discard(chat)

    async def close(self):
        for chat in list(self.joined):
            with suppress(Exception):
                await self.leave(chat)
        await self.client.disconnect()


class MusicWorker:
    def __init__(self, db, tg, settings, engine, media):
        self.db, self.tg, self.settings, self.engine, self.media = db, tg, settings, engine, media
        self.active = set()

    def recover(self):
        # No surprise autoplay after restart. A fresh authorized /mresume or /mplay is needed.
        self.db.execute("UPDATE music_state SET status='interrupted' WHERE status IN ('playing','paused')")
        self.db.execute(
            "UPDATE music_jobs SET state='uncertain',error='Worker restarted during action' WHERE state='running'"
        )

    def state(self, chat):
        self.db.execute("INSERT OR IGNORE INTO music_state(chat) VALUES(?)", (chat,))
        return self.db.one("SELECT * FROM music_state WHERE chat=?", (chat,))

    async def jobs(self, now=None):
        now = int(time.time()) if now is None else now
        rows = self.db.all("SELECT * FROM music_jobs WHERE state='pending' ORDER BY id LIMIT 10")
        for job in rows:
            chat = job["chat"]
            if not self.db.execute(
                "UPDATE music_jobs SET state='running' WHERE id=? AND state='pending'", (job["id"],)
            ).rowcount:
                continue
            try:
                if (
                    chat not in self.settings.chats
                    or now - job["created"] > 300
                    or not await authorized(self.db, self.tg, chat, job["actor"])
                ):
                    raise ValueError("Music request expired or permission was revoked")
                await self.action(job, json.loads(job["payload"]))
                self.db.execute("UPDATE music_jobs SET state='done',error='' WHERE id=?", (job["id"],))
                self.db.audit(chat, 0, 0, job["actor"], "music", job["action"])
            except Exception as exc:
                # Store a type, not account/session details or token-bearing request URLs.
                self.db.execute(
                    "UPDATE music_jobs SET state='failed',error=? WHERE id=?", (type(exc).__name__, job["id"])
                )
                with using_language(self.db.chat(chat)["settings"]["language"]):
                    with suppress(Exception):
                        await self.tg.send(chat, tr("music.failed", id=job["id"]))
                log.warning("Music job %s failed (%s)", job["id"], type(exc).__name__)

    async def action(self, job, payload):
        chat, action = job["chat"], job["action"]
        state = self.state(chat)
        if action == "enqueue":
            count = self.db.one(
                "SELECT count(*) n FROM music_queue WHERE chat=? AND state IN ('queued','playing')", (chat,)
            )["n"]
            if count >= self.settings.queue_limit:
                raise ValueError("Music queue is full")
            if payload.get("kind") == "library" and payload.get("track") not in self.settings.tracks():
                raise ValueError("Unknown library track")
            if payload.get("kind") not in ("library", "telegram") or not isinstance(
                payload.get("title"), str
            ):
                raise ValueError("Invalid audio source")
            self.db.execute(
                "INSERT OR IGNORE INTO music_queue(chat,actor,title,payload,position,source_job) VALUES(?,?,?,?,?,?)",
                (chat, job["actor"], payload["title"][:100], json.dumps(payload), time.time_ns(), job["id"]),
            )
            # An interrupted current item goes back to the front only on an explicit resume.
            self.active.add(chat)
            if state["status"] == "interrupted":
                self.db.execute("UPDATE music_queue SET state='queued' WHERE id=?", (state["current"],))
                self.db.execute("UPDATE music_state SET current=0,status='idle' WHERE chat=?", (chat,))
            if state["status"] in ("idle", "error"):
                self.db.execute("UPDATE music_state SET status='idle' WHERE chat=?", (chat,))
        elif action == "pause":
            if state["status"] != "playing":
                raise ValueError("No playing track")
            await self.engine.pause(chat)
            self.db.execute(
                "UPDATE music_state SET status='paused',paused_at=? WHERE chat=?", (time.time(), chat)
            )
        elif action == "resume":
            if state["status"] == "playing":
                return
            self.active.add(chat)
            if state["status"] == "paused":
                await self.engine.resume(chat)
                self.db.execute(
                    "UPDATE music_state SET status='playing',started=started+?-paused_at,paused_at=0 WHERE chat=?",
                    (time.time(), chat),
                )
            else:
                if state["current"]:
                    self.db.execute("UPDATE music_queue SET state='queued' WHERE id=?", (state["current"],))
                self.db.execute("UPDATE music_state SET status='idle',current=0 WHERE chat=?", (chat,))
        elif action in ("skip", "stop"):
            await self.engine.leave(chat)
            self.db.execute("UPDATE music_queue SET state='skipped' WHERE id=?", (state["current"],))
            self.db.execute("UPDATE music_state SET status='idle',current=0 WHERE chat=?", (chat,))
            if action == "stop":
                self.active.discard(chat)
                self.db.execute(
                    "UPDATE music_queue SET state='cancelled' WHERE chat=? AND state='queued'", (chat,)
                )
            else:
                self.active.add(chat)
        elif action == "volume":
            value = payload.get("value")
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
                raise ValueError("Invalid volume")
            if state["status"] in ("playing", "paused"):
                await self.engine.volume(chat, value)
            self.db.execute("UPDATE music_state SET volume=? WHERE chat=?", (value, chat))
        elif action == "repeat":
            mode = payload.get("mode")
            if mode not in ("off", "one", "all"):
                raise ValueError("Invalid repeat mode")
            self.db.execute("UPDATE music_state SET repeat_mode=? WHERE chat=?", (mode, chat))
        elif action == "clear":
            self.db.execute(
                "UPDATE music_queue SET state='cancelled' WHERE chat=? AND state='queued'", (chat,)
            )
        elif action == "remove":
            self.db.execute(
                "UPDATE music_queue SET state='cancelled' WHERE id=? AND chat=? AND state='queued'",
                (payload["id"], chat),
            )
        elif action == "shuffle":
            rows = self.db.all("SELECT id FROM music_queue WHERE chat=? AND state='queued'", (chat,))
            secrets.SystemRandom().shuffle(rows)
            with self.db.transaction():
                for index, row in enumerate(rows):
                    self.db.execute("UPDATE music_queue SET position=? WHERE id=?", (index, row["id"]))
        else:
            raise ValueError("Unknown music action")

    async def tick(self, now=None):
        now = time.time() if now is None else now
        for chat in list(self.active):
            state = self.state(chat)
            if state["status"] == "playing" and now - state["started"] >= state["duration"] + 2:
                self.db.execute("UPDATE music_queue SET state='done' WHERE id=?", (state["current"],))
                current = self.db.one("SELECT * FROM music_queue WHERE id=?", (state["current"],))
                if current and state["repeat_mode"] in ("one", "all"):
                    position = -time.time_ns() if state["repeat_mode"] == "one" else time.time_ns()
                    self.db.execute(
                        "UPDATE music_queue SET state='queued',position=? WHERE id=?",
                        (position, current["id"]),
                    )
                self.db.execute("UPDATE music_state SET status='idle',current=0 WHERE chat=?", (chat,))
                state = self.state(chat)
            if state["status"] != "idle":
                continue
            row = self.db.one(
                "SELECT * FROM music_queue WHERE chat=? AND state='queued' ORDER BY position,id LIMIT 1",
                (chat,),
            )
            if not row:
                await self.engine.leave(chat)
                self.active.discard(chat)
                continue
            try:
                if not await authorized(self.db, self.tg, chat, row["actor"]):
                    raise ValueError("Requesting staff member no longer authorized")
                path, duration = await self.media.prepare(json.loads(row["payload"]))
                if not await authorized(self.db, self.tg, chat, row["actor"]):
                    raise ValueError("Permission was revoked while preparing audio")
                if self.db.one(
                    "SELECT 1 FROM music_jobs WHERE chat=? AND action='stop' AND state='pending'", (chat,)
                ):
                    continue
                await self.engine.play(chat, path)
                await self.engine.volume(chat, state["volume"])
                self.db.execute("UPDATE music_queue SET state='playing' WHERE id=?", (row["id"],))
                self.db.execute(
                    "UPDATE music_state SET status='playing',current=?,duration=?,started=?,paused_at=0 WHERE chat=?",
                    (row["id"], duration, time.time(), chat),
                )
                with using_language(self.db.chat(chat)["settings"]["language"]):
                    from html import escape

                    with suppress(Exception):
                        await self.tg.send(chat, tr("music.playing", title=escape(row["title"])))
            except Exception as exc:
                with suppress(Exception):
                    await self.engine.leave(chat)
                self.db.execute("UPDATE music_queue SET state='failed' WHERE id=?", (row["id"],))
                self.db.execute("UPDATE music_state SET status='error',current=0 WHERE chat=?", (chat,))
                self.active.discard(chat)
                log.warning("Playback in %s failed (%s)", chat, type(exc).__name__)
                with using_language(self.db.chat(chat)["settings"]["language"]):
                    with suppress(Exception):
                        await self.tg.send(chat, tr("music.play_failed"))


async def run():
    from dotenv import load_dotenv

    load_dotenv(".env.music")
    config = Config.load()
    settings = MusicSettings.load()
    if not settings.enabled:
        raise ValueError("Please enable MUSIC_ENABLED and set MUSIC_CHATS first")
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from pytgcalls import PyTgCalls

    api_id = int(os.environ.get("MUSIC_API_ID", "0"))
    api_hash = os.environ.get("MUSIC_API_HASH", "")
    session = os.environ.get("MUSIC_SESSION", "")
    if not api_id or not api_hash or not session:
        raise ValueError("Run python -m tuxigap.music_login locally first")
    import fcntl

    lock_path = Path(config.database).resolve().with_suffix(".music.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("One music worker already owns this database") from None
        client = TelegramClient(StringSession(session), api_id, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise ValueError("The music session is not authorized; recreate it locally")
        me = await client.get_me()
        if me.bot:
            await client.disconnect()
            raise ValueError("Use a human helper account session, not a bot token")
        calls = PyTgCalls(client)
        await calls.start()
        engine = AudioEngine(client, calls)
        db = DB(config.database)
        tg = Telegram(config.token, config.api_base, test_mode=config.test_mode)
        worker = MusicWorker(db, tg, settings, engine, MediaLibrary(settings, tg))
        worker.recover()
        stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        last_prune = 0
        try:
            while not stop.is_set():
                db.set("music_heartbeat", int(time.time()))
                await worker.jobs()
                await worker.tick()
                if time.time() - last_prune > 3600:
                    worker.media.prune(db)
                    last_prune = time.time()
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), 1)
        finally:
            await engine.close()
            db.set("music_heartbeat", 0)
            await tg.close()
            db.close()


def check():
    import importlib.metadata
    from pytgcalls.types import MediaStream, GroupCallConfig
    from telethon.sessions import StringSession

    assert MediaStream.Flags.IGNORE and GroupCallConfig(auto_start=False) and StringSession
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise ValueError("Please install FFmpeg, including ffprobe")
    print(
        "Music dependencies ready: py-tgcalls "
        + importlib.metadata.version("py-tgcalls")
        + ", Telethon "
        + importlib.metadata.version("Telethon")
        + ". No Telegram connection made."
    )


def main():
    parser = argparse.ArgumentParser(description="Tuxigap optional voice-chat music worker")
    parser.add_argument(
        "--check", action="store_true", help="Check installed dependencies without account access"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.check:
        return check()
    try:
        asyncio.run(run())
    except (ValueError, ImportError) as exc:
        # Configuration errors are friendly; don't print arbitrary network exceptions or sessions.
        parser.exit(
            1, ("Please install the music extra first." if isinstance(exc, ImportError) else str(exc)) + "\n"
        )


if __name__ == "__main__":
    main()
