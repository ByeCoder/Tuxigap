#!/usr/bin/env python3
"""One entry point for the Tuxigap Compose suite."""

import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def command(action, all_services=False, music=False):
    files = ["docker-compose.yml"]
    if all_services:
        files += ["docker-compose.web.yml", "docker-compose.engines.yml", "docker-compose.studio.yml"]
    if music:
        files.append("docker-compose.music.yml")
    arguments = ["docker", "compose"]
    for file in files:
        arguments.extend(["-f", str(ROOT / file)])
    arguments += {
        "up": ["up", "-d", "--build"],
        "down": ["down"],
        "logs": ["logs", "-f", "--tail=100"],
        "status": ["ps"],
    }[action]
    return arguments


def main():
    parser = argparse.ArgumentParser(description="Your Tuxigap suite, one friendly command away.")
    parser.add_argument("action", choices=["up", "down", "logs", "status"])
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_services",
        help="Include the dashboard, spam engine and pinned Studio companion.",
    )
    parser.add_argument(
        "--music", action="store_true", help="Include the optional authorized helper-account music worker."
    )
    args = parser.parse_args()
    if not shutil.which("docker"):
        parser.exit(1, "Please install Docker with the Compose plugin, then come back. 🌷\n")
    if not (ROOT / ".env").is_file():
        parser.exit(1, "Let's create your private settings first: python tools/configure.py\n")
    if args.music and not (ROOT / ".env.music").is_file():
        parser.exit(1, "Create your helper session locally first: python -m tuxigap.music_login\n")
    raise SystemExit(subprocess.run(command(args.action, args.all_services, args.music), cwd=ROOT).returncode)


if __name__ == "__main__":
    main()
