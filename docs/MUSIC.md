# Put a little music in the call

Tuxigap's optional music worker uses **PyTgCalls 3.0.1 + NTgCalls 3.0.7 + Telethon 1.45.0 + FFmpeg**. Telegram's Bot API still does not stream into calls: a **helper user account that you own and authorize** supplies the MTProto session. Your normal Tuxigap bot keeps its own token and polling process.

The worker plays audio in an already-started supergroup/channel call. It does not automatically join a community, start a new call, end everyone's call, record participants, or run arbitrary chat-supplied shell commands. `/mstop` stops playback and makes the helper leave; other participants' call continues.

## First setup on Linux

Use the same checkout/database as your core bot. The helper runtime is supported on Linux; the core bot remains independently installable.

```bash
pip install -e '.[music]'
# Install FFmpeg and ffprobe with your operating system's package manager.
python -m tuxigap.music_worker --check
python -m tuxigap.music_login
```

The check command imports the pinned dependencies and finds FFmpeg without connecting to Telegram. The login helper is an **interactive command you run on your own trusted terminal**:

1. Obtain your Telegram API ID/hash from [my.telegram.org](https://my.telegram.org).
2. Enter that ID/hash, your helper account's phone number, Telegram login code and two-step password when asked locally.
3. The script writes `.env.music` with private permissions and refuses to overwrite it. It does not print the exported session.
4. Keep `.env.music` private. A session grants account access, so never paste it into chat, issues, screenshots or Git. Use Telegram's **Settings → Devices** to revoke it if needed.
5. Add the helper account to your test community yourself and allow it to speak. Start the call in Telegram.

Set the following in the normal `.env`:

```dotenv
MUSIC_ENABLED=1
MUSIC_CHATS=-1001234567890
MUSIC_LIBRARY=data/music/library.json
MUSIC_MEDIA=data/music/media
```

`MUSIC_CHATS` is an explicit comma-separated allowlist. Restart the core after changing it. Then run the worker separately:

```bash
python -m tuxigap.music_worker
```

The worker loads `.env.music`, connects only an already-authorized helper session, and refuses an unauthorized session instead of opening an unattended login prompt. It never calls `getUpdates`. One worker owns the database through a process lock; don't run two workers against the same database or helper session.

## Docker

After creating `.env` and `.env.music`, and setting `MUSIC_ENABLED`/`MUSIC_CHATS` in `.env`:

```bash
python tools/manage.py up --music
python tools/manage.py logs --music
```

You can add `--all` to include the dashboard, spam engine and Studio too. Music is deliberately separate from `--all`, since it needs a personally authorized helper. Direct Compose also works:

```bash
docker compose -f docker-compose.yml -f docker-compose.music.yml up -d --build
```

The optional image installs FFmpeg and the pinned music extra. It runs as UID 10001 and shares only the existing Tuxigap data volume. No music HTTP port is exposed. The core and worker must use the same upgraded schema and database path.

## Play from Telegram

1. Send a Telegram **audio attachment** to the group, or use one you have permission to play.
2. Reply to that attachment with `/mplay`.
3. Open `/music` for playback buttons.

Attachments must be **5 seconds–30 minutes**, with a reported and downloaded size no greater than **20 MiB**. The worker downloads through the Bot API's returned file path, probes finite media and converts it into a local Opus file before playback. Paths are validated; arbitrary web, YouTube or playlist URLs are not accepted. Supported upload containers include MP3, WAV, Ogg, FLAC, M4A/MP4, AAC and WebM with an audio stream. MIME labels alone are not trusted.

This accepts Telegram's `audio` attachment field, not every arbitrary document, voice note or video message. An oversized/unsupported file can be converted locally and added to your library instead.

## Play from a local library

Create files under `MUSIC_MEDIA` and a `MUSIC_LIBRARY` JSON file:

```json
[
  {"id": "welcome", "title": "Our welcome track", "file": "welcome.ogg"},
  {"id": "piano", "title": "A quiet piano break", "file": "piano.mp3"}
]
```

IDs use lowercase letters, digits, `_` or `-`, at most 40 characters. Filenames resolve inside `MUSIC_MEDIA`; traversal and symlinks escaping that directory are rejected. Local files may be up to 100 MiB and 30 minutes, with a minimum duration of five seconds. Add your own audio; the project ships no commercial songs.

For Docker, copy your library and files into `/app/data/music/` in the persistent volume, keeping files readable by UID 10001. Paths in the JSON are relative to `/app/data/music/media`.

`/mlibrary` lists the first 30 entries and provides quick-play buttons for the first ten. All valid IDs are usable with `/mplay ID`, up to 500 library entries.

## Your controls

| Command | What happens |
|---|---|
| `/music` | Current track/state, worker heartbeat and inline controls |
| `/mplay TRACK_ID` | Queue a library track; replying to audio queues that attachment |
| `/mpause`, `/mresume` | Pause/resume; after restart, resume explicitly restarts the interrupted track from its beginning |
| `/mskip` | Leave the current stream, skip its entry and play the next queued item |
| `/mstop` | Stop, leave the call and cancel queued tracks |
| `/mvolume 1–100` | Set the helper's call volume, initially 70 |
| `/mqueue` | Current and queued entries, with numeric IDs |
| `/mremove ENTRY_ID` | Remove a pending item, scoped to this community |
| `/mclear` | Clear pending tracks while leaving the current one alone |
| `/mrepeat off`, `one`, `all` | Set end-of-track repeat behavior |
| `/mshuffle` | Shuffle pending entries |
| `/mjobs` | Ten latest control requests and their processing states |

Actual Telegram call managers, the community owner, and owner-appointed bot `host`/`manager` roles may control music. Live membership/role checks run both when accepting a command and when the worker acts, including after audio preparation. Bot moderator/editor roles alone don't grant music access. The allowlist is always enforced.

## Queues, restarts and limits

- Up to 30 current/queued tracks and 30 pending control requests per community.
- Control requests expire after five minutes. Completed jobs are retained under the normal retention policy; status `done` means the control was processed, not that the whole track finished.
- A job interrupted by a process crash becomes `uncertain`; it is not automatically replayed. Check `/music` and submit a fresh command.
- Normal queue entries survive restart. Playback becomes `interrupted` and waits for a fresh authorized `/mresume` or `/mplay`. Resume begins the interrupted item again rather than seeking to an old timestamp.
- Local database commits and Telegram calls are not one atomic transaction; a crash after an external action can need manual reconciliation.
- Finite track duration is probed with FFmpeg. A pause-aware duration watchdog advances the queue with a small end buffer; this is not gapless playback, crossfade, seek support or sample-accurate synchronization.
- Preparing/converting an attachment can take time. The panel's heartbeat can temporarily show busy/offline while preparation is in progress. A pending stop prevents that prepared track from starting. The main moderation/payment process remains separate.
- Cached uploads not used by a current/pending track are removed after seven days. Operator library files are not automatically removed.
- If a track fails, playback stops in an error state. The queue remains; `/mresume` tries the next queued item. Playback notices failing to send do not stop working audio.
- The core's moderation dry run does not disable explicitly requested music commands. Use `MUSIC_ENABLED=0` and stop the optional worker to disable music entirely.

PyTgCalls may check its upstream version at startup. Its dependency implementation and Telegram connectivity remain independent of the bot's offline joke/catalog features.

## What was verified

`tests/music_contract.py` checks the real pinned library interfaces, synthetic audio download, FFmpeg conversion/probing, audio-only stream configuration and `auto_start=False` without connecting an account. The ordinary tests use fake call engines to verify queue/control/role/restart behavior. CI also builds the optional Docker image and runs its offline check.

**No live Telegram account, active group call or audible playback was exercised here.** Finish the music section in [LIVE_TEST.md](LIVE_TEST.md) with your own helper before relying on it for an event.

Primary sources: [PyTgCalls](https://github.com/pytgcalls/pytgcalls/tree/8a4310a658af6426a09eb6cd33ef489550ed0d67), [Telethon](https://docs.telethon.dev/en/stable/), [FFmpeg](https://ffmpeg.org/documentation.html). Preserved licenses are listed in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
