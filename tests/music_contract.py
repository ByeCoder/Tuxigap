"""Real optional dependency/media checks; no account, Telegram request or call."""

import asyncio
import inspect
import io
from pathlib import Path
import tempfile
import wave

import httpx
from pytgcalls import PyTgCalls
from pytgcalls.types import GroupCallConfig, MediaStream
from telethon.tl.types import InputPeerChannel

from tuxigap.music import MusicSettings
from tuxigap.music_worker import AudioEngine, MediaLibrary, check
from tuxigap.telegram import Telegram


async def main():
    check()
    for name in ("play", "pause", "resume", "leave_call", "change_volume_call"):
        assert callable(getattr(PyTgCalls, name)), name
    assert "config" in inspect.signature(PyTgCalls.play).parameters
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        audio = io.BytesIO()
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\0\0" * 8000 * 6)
        wav_bytes = audio.getvalue()

        def transport(request):
            if request.url.path.endswith("/getFile"):
                return httpx.Response(
                    200,
                    json={"ok": True, "result": {"file_path": "music/test.wav", "file_size": len(wav_bytes)}},
                )
            if request.url.path.endswith("/music/test.wav"):
                return httpx.Response(200, content=wav_bytes)
            raise AssertionError("Unexpected HTTP request")

        tg = Telegram("0:offline", client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        try:
            media = MediaLibrary(MusicSettings(media=str(root)), tg)
            path, duration = await media.prepare({"kind": "telegram", "file_id": "synthetic-wave"})
            assert 5 <= duration <= 7
            assert Path(path).suffix == ".ogg" and Path(path).is_file()
            stream = MediaStream(
                path, video_flags=MediaStream.Flags.IGNORE, audio_flags=MediaStream.Flags.REQUIRED
            )
            await stream.check_stream()
            assert stream.camera is None and stream.microphone is not None
            captured = []

            class Client:
                async def get_input_entity(self, chat):
                    return InputPeerChannel(123, 456)

                async def __call__(self, request):
                    captured.append(request)
                    return True

            class Calls:
                async def play(self, chat, media, config):
                    assert isinstance(media, MediaStream)
                    assert isinstance(config, GroupCallConfig) and config.auto_start is False
                    captured.append(chat)

            engine = AudioEngine(Client(), Calls())
            await engine.play(-100123, path)
            assert -100123 in captured
        finally:
            await tg.close()
    print(
        "Music contracts passed: pinned API, real audio download/transcode/probe, audio-only stream and no-auto-start call configuration. No Telegram or account connection made."
    )


if __name__ == "__main__":
    asyncio.run(main())
