import json
import os
from pathlib import Path
import sqlite3
import time


def main():
    path = Path(os.getenv("DATABASE", "data/tuxigap.sqlite3")).resolve()
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            row = db.execute("SELECT value FROM kv WHERE key='heartbeat'").fetchone()
        healthy = row is not None and 0 <= time.time() - json.loads(row[0]) < 180
    except (sqlite3.Error, OSError, ValueError):
        healthy = False
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()
