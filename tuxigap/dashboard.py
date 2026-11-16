"""Optional owner dashboard. Run separately: python -m tuxigap.dashboard.

Bearer authentication, no cookies/CORS, fixed static paths, bounded JSON requests.
Bind to loopback by default; use a TLS reverse proxy for remote access.
"""

from .i18n import tr

import hmac
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from .bot import BOOL_FIELDS
from .config import Config
from .db import DB
from .stats import report
from .i18n import LANGUAGES, catalog, using_language

ASSETS = Path(__file__).with_name("assets")


def make_handler(config, token):
    if len(token) < 32:
        raise ValueError(tr("m_e1020c58772a"))

    class Handler(BaseHTTPRequestHandler):
        server_version = "Tuxigap"

        def log_message(self, *_args):
            # No headers, credential values, request bodies or URL query strings in logs.
            pass

        def respond(self, status, data, content_type="application/json; charset=utf-8"):
            if isinstance(data, (dict, list)):
                data = json.dumps(data, ensure_ascii=False).encode()
            if isinstance(data, str):
                data = data.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            expected = "Bearer " + token
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied.encode(), expected.encode())

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path.startswith("/locales/") and parsed.path.endswith(".json"):
                code = parsed.path[len("/locales/") : -len(".json")]
                if code in LANGUAGES:
                    return self.respond(200, catalog(code))
                return self.respond(404, {"error": "Language not found"})
            static = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            if parsed.path in static:
                name, kind = static[parsed.path]
                return self.respond(200, (ASSETS / name).read_bytes(), kind)
            return self.api(parsed.path, parse_qs(parsed.query))

        def do_POST(self):
            path = urlparse(self.path).path
            if not self.authorized():
                return self.respond(401, {"error": tr("m_af2664d8237d")})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384 or not self.headers.get("Content-Type", "").startswith(
                    "application/json"
                ):
                    return self.respond(400, {"error": tr("m_d90c1d2e9251")})
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError(tr("m_1955e5c06835"))
                return self.api(path, data)
            except (ValueError, TypeError):
                return self.respond(400, {"error": tr("m_bf40e15eafad")})

        def api(self, path, query):
            with using_language(self.headers.get("X-Tuxigap-Language", "en")):
                return self._api(path, query)

        def _api(self, path, query):
            if not self.authorized():
                return self.respond(401, {"error": tr("m_af2664d8237d")})
            db = DB(config.database)
            try:
                if self.command == "GET" and path == "/api/chats":
                    return self.respond(
                        200,
                        [db.chat(r["id"]) for r in db.all("SELECT id FROM chats ORDER BY title LIMIT 200")],
                    )
                if self.command == "GET" and path == "/api/stats":
                    chat, period = int(query["chat"][0]), query.get("period", ["day"])[0]
                    text = report(db, chat, period)[0]
                    plain = html.unescape(re.sub(r"<[^>]*>", "", text))
                    return self.respond(200, {"text": plain})
                if self.command == "GET" and path == "/api/audit":
                    chat = int(query["chat"][0])
                    return self.respond(
                        200,
                        db.all(
                            "SELECT ts,actor,user,action,reason,status FROM audit WHERE chat=? ORDER BY id DESC LIMIT 100",
                            (chat,),
                        ),
                    )
                if self.command == "POST" and path == "/api/settings":
                    chat, key, value = int(query["chat"]), query["key"], query["value"]
                    valid_language = key == "language" and isinstance(value, str) and value in LANGUAGES
                    if not valid_language and (key not in BOOL_FIELDS or type(value) is not bool):
                        raise ValueError(tr("m_e41fb51517ab"))
                    db.setting(chat, key, value)
                    db.audit(chat, 0, 0, 0, "web_setting", f"{key}={value}")
                    return self.respond(200, {"ok": True})
                if self.command == "POST" and path == "/api/samples":
                    chat, text, label = int(query["chat"]), query["text"], query["label"]
                    if not isinstance(text, str) or len(text) > 4000:
                        raise ValueError(tr("m_b3bea6b951bb"))
                    db.chat(chat)
                    db.train(chat, text, label, 0)
                    if str(chat) in json.loads(config.spam_engines):
                        db.execute(
                            "INSERT INTO engine_outbox(chat,text,label,due) VALUES(?,?,?,unixepoch())",
                            (chat, text, label),
                        )
                    db.audit(chat, 0, 0, 0, "web_training", label)
                    return self.respond(200, {"ok": True})
                return self.respond(404, {"error": tr("m_c9f5d2b95a85")})
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                return self.respond(400, {"error": str(exc)[:200]})
            finally:
                db.close()

    return Handler


def main():
    config = Config.load()
    token = os.getenv("WEB_TOKEN", "")
    host, port = os.getenv("WEB_HOST", "127.0.0.1"), int(os.getenv("WEB_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), make_handler(config, token))
    print(tr("m_ccfc307bcfd8", p0=host, p1=port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
