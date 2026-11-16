"""Run locally to authorize your own helper account. Never paste sessions into chat."""

import argparse
import asyncio
from getpass import getpass
import os
from pathlib import Path
import re


async def login(destination):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    if destination.exists():
        raise ValueError("That file already exists. Choose a new output filename.")
    api_id = int(input("Telegram API ID from my.telegram.org: ").strip())
    api_hash = getpass("Telegram API hash (hidden): ").strip()
    if api_id <= 0 or not re.fullmatch("[a-fA-F0-9]{32}", api_hash):
        raise ValueError("Please check your API ID and hash.")
    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.start(
            phone=lambda: getpass("Helper account phone number (hidden): "),
            code_callback=lambda: getpass("Telegram login code (hidden): "),
            password=lambda: getpass("Two-step verification password (hidden): "),
        )
        me = await client.get_me()
        if me.bot:
            raise ValueError("Please use your own helper user account, not a bot.")
        session = client.session.save()
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write("# Private helper credentials. Never commit or share this file.\n")
            stream.write(f"MUSIC_API_ID={api_id}\nMUSIC_API_HASH={api_hash}\nMUSIC_SESSION={session}\n")
        print("Your helper session is saved privately. Nothing was printed or added to Git.")
        print("Add that account to your music group, start its call, and follow docs/MUSIC.md.")
    finally:
        await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Authorize your own optional Tuxigap music helper locally.")
    parser.add_argument("--output", default=".env.music")
    args = parser.parse_args()
    try:
        asyncio.run(login(Path(args.output)))
    except (ValueError, ImportError) as exc:
        parser.exit(
            1, ("Install the music extra first." if isinstance(exc, ImportError) else str(exc)) + "\n"
        )


if __name__ == "__main__":
    main()
