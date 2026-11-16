#!/usr/bin/env python3
"""Friendly local setup. Secrets are written to .env, never to Git or logs."""

import argparse
from getpass import getpass
import os
from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parents[1]


def write_config(destination, token, owners="", chat="", studio_url="http://localhost:3000"):
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise ValueError("That token doesn't look quite right. Please copy it from BotFather.")
    if owners and not all(part.strip().isdigit() for part in owners.split(",")):
        raise ValueError("Please use comma-separated numeric owner IDs.")
    if chat and not re.fullmatch(r"-\d+", chat):
        raise ValueError("Please use a numeric group ID, such as -1001234567890.")
    import json

    values = {
        "BOT_TOKEN": token,
        "OWNER_IDS": owners,
        "WEB_TOKEN": secrets.token_urlsafe(32),
        "SPAM_ENGINE_PASSWORD": secrets.token_urlsafe(32),
        "STUDIO_ADMIN_KEY": secrets.token_urlsafe(32),
        "STUDIO_JWT_SECRET": secrets.token_urlsafe(48),
        "STUDIO_URL": studio_url,
        "SPAM_ENGINES": json.dumps({chat: "http://spam-engine:8080"}) if chat else "{}",
    }
    lines = []
    for line in (ROOT / ".env.example").read_text().splitlines():
        key = line.partition("=")[0]
        lines.append(key + "=" + values[key] if key in values else line)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Let's get your Tuxigap community ready.")
    parser.add_argument(
        "--non-interactive", action="store_true", help="Read BOT_TOKEN and OWNER_IDS from the environment."
    )
    args = parser.parse_args()
    destination = ROOT / ".env"
    if destination.exists():
        parser.exit(1, "Your .env already exists, so we left it safe. Edit that file to make changes.\n")
    if args.non_interactive:
        token = os.getenv("BOT_TOKEN", "")
        owners = os.getenv("OWNER_IDS", "")
        chat = os.getenv("GROUP_ID", "")
    else:
        print("Welcome aboard! This stays on your computer; nothing is sent to Telegram yet.")
        token = getpass("BotFather token: ").strip()
        owners = input("Your numeric Telegram ID (optional): ").strip()
        chat = input("Group ID for the spam engine (optional): ").strip()
    try:
        write_config(destination, token, owners, chat)
    except (ValueError, FileExistsError) as exc:
        parser.exit(1, str(exc) + "\n")
    print("All set! Your private keys are in .env. Next: python tools/manage.py up --all")
    print("Use a separate bot token in Studio. You can find every step in README.md.")


if __name__ == "__main__":
    main()
