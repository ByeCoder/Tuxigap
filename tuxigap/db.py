"""Single-process SQLite store. No awaits inside transactions; WAL + durable financial ledger."""

from .i18n import tr

from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time

from .config import DEFAULTS, ensure_parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY,title TEXT,kind TEXT,settings TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS members(chat INTEGER,user INTEGER,name TEXT,xp INTEGER DEFAULT 0,
 coins INTEGER DEFAULT 0,last_xp INTEGER DEFAULT 0,daily_day TEXT DEFAULT '',streak INTEGER DEFAULT 0,
 warns INTEGER DEFAULT 0,badge TEXT DEFAULT '',PRIMARY KEY(chat,user));
CREATE TABLE IF NOT EXISTS messages(chat INTEGER,mid INTEGER,user INTEGER,text TEXT,ts INTEGER,
 PRIMARY KEY(chat,mid));
CREATE INDEX IF NOT EXISTS messages_ts ON messages(ts);
CREATE TABLE IF NOT EXISTS hours(chat INTEGER,hour INTEGER,metric TEXT,n INTEGER NOT NULL,
 PRIMARY KEY(chat,hour,metric));
CREATE TABLE IF NOT EXISTS activity(chat INTEGER,day INTEGER,user INTEGER,n INTEGER DEFAULT 1,
 PRIMARY KEY(chat,day,user));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,chat INTEGER,user INTEGER,mid INTEGER,
 actor INTEGER,action TEXT,reason TEXT,text TEXT,ts INTEGER,status TEXT DEFAULT 'done');
CREATE INDEX IF NOT EXISTS audit_chat ON audit(chat,ts);
CREATE TABLE IF NOT EXISTS samples(chat INTEGER,hash TEXT,text TEXT,label TEXT,actor INTEGER,ts INTEGER,subject INTEGER DEFAULT 0,
 PRIMARY KEY(chat,hash));
CREATE TABLE IF NOT EXISTS sessions(user INTEGER PRIMARY KEY,chat INTEGER,field TEXT,expires INTEGER);
CREATE TABLE IF NOT EXISTS captcha(chat INTEGER,user INTEGER,answer TEXT,expires INTEGER,
 PRIMARY KEY(chat,user));
CREATE TABLE IF NOT EXISTS games(token TEXT PRIMARY KEY,chat INTEGER,data TEXT,expires INTEGER,winner INTEGER);
CREATE TABLE IF NOT EXISTS attempts(token TEXT,user INTEGER,PRIMARY KEY(token,user));
CREATE TABLE IF NOT EXISTS quota(scope TEXT,day TEXT,n INTEGER,PRIMARY KEY(scope,day));
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY,chat INTEGER,name TEXT,stars INTEGER,
 days INTEGER,recurring INTEGER DEFAULT 0,enabled INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS invoices(payload TEXT PRIMARY KEY,user INTEGER,chat INTEGER,plan INTEGER,
 stars INTEGER,days INTEGER,recurring INTEGER,created INTEGER,paid INTEGER DEFAULT 0,cancelled INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments(charge TEXT PRIMARY KEY,payload TEXT,user INTEGER,chat INTEGER,
 stars INTEGER,days INTEGER,paid_at INTEGER,period_end INTEGER DEFAULT 0,refunded INTEGER DEFAULT 0,
 delivered INTEGER DEFAULT 0,notice_sent INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS payments_chat ON payments(chat,paid_at);
CREATE TABLE IF NOT EXISTS subscriptions(chat INTEGER,user INTEGER,expires INTEGER,
 expired_ban INTEGER DEFAULT 0,PRIMARY KEY(chat,user));
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,chat INTEGER,creator INTEGER,due INTEGER,
 text TEXT,state TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS report_log(chat INTEGER,period TEXT,start INTEGER,PRIMARY KEY(chat,period,start));
CREATE TABLE IF NOT EXISTS inbox(id INTEGER PRIMARY KEY,payload TEXT,done INTEGER DEFAULT 0,
 attempts INTEGER DEFAULT 0,next_try INTEGER DEFAULT 0,received INTEGER DEFAULT (unixepoch()));
CREATE TABLE IF NOT EXISTS command_cooldown(chat INTEGER,user INTEGER,kind TEXT,ts INTEGER,
 PRIMARY KEY(chat,user,kind));
CREATE TABLE IF NOT EXISTS notes(chat INTEGER,name TEXT,body TEXT,PRIMARY KEY(chat,name));
CREATE TABLE IF NOT EXISTS filters(chat INTEGER,trigger TEXT,body TEXT,PRIMARY KEY(chat,trigger));
CREATE TABLE IF NOT EXISTS engine_outbox(id INTEGER PRIMARY KEY,chat INTEGER,text TEXT,label TEXT,due INTEGER);
CREATE TABLE IF NOT EXISTS invite_links(chat INTEGER,inviter INTEGER,link TEXT,PRIMARY KEY(chat,inviter));
CREATE TABLE IF NOT EXISTS referrals(chat INTEGER,user INTEGER,inviter INTEGER,ts INTEGER,PRIMARY KEY(chat,user));
CREATE TABLE IF NOT EXISTS giveaways(token TEXT PRIMARY KEY,chat INTEGER,title TEXT,creator INTEGER,ends INTEGER,
 state TEXT DEFAULT 'open',winner INTEGER DEFAULT 0,notified INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS giveaway_entries(token TEXT,user INTEGER,PRIMARY KEY(token,user));
CREATE TABLE IF NOT EXISTS approved(chat INTEGER,user INTEGER,actor INTEGER,PRIMARY KEY(chat,user));
CREATE TABLE IF NOT EXISTS afk(chat INTEGER,user INTEGER,text TEXT,since INTEGER,PRIMARY KEY(chat,user));
CREATE TABLE IF NOT EXISTS join_events(chat INTEGER,user INTEGER,ts INTEGER,PRIMARY KEY(chat,user,ts));
CREATE INDEX IF NOT EXISTS join_events_ts ON join_events(chat,ts);
CREATE TABLE IF NOT EXISTS federations(id TEXT PRIMARY KEY,owner INTEGER,name TEXT);
CREATE TABLE IF NOT EXISTS federation_chats(chat INTEGER PRIMARY KEY,fid TEXT,state TEXT);
CREATE TABLE IF NOT EXISTS federation_bans(fid TEXT,user INTEGER,reason TEXT,active INTEGER,actor INTEGER,version INTEGER,PRIMARY KEY(fid,user));
CREATE TABLE IF NOT EXISTS federation_jobs(id INTEGER PRIMARY KEY,fid TEXT,chat INTEGER,user INTEGER,action TEXT,
 version INTEGER,state TEXT DEFAULT 'pending',due INTEGER,attempts INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS federation_enforced(fid TEXT,chat INTEGER,user INTEGER,PRIMARY KEY(fid,chat,user));
"""


class DB:
    def __init__(self, path):
        ensure_parent(path)
        self.conn = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            self.conn.close()
            raise RuntimeError("Database is newer than this code. Upgrade Tuxigap first.")
        self.conn.executescript(SCHEMA)
        if version < 2:
            with self.transaction():
                self.execute("PRAGMA user_version=2")

    def close(self):
        self.conn.close()

    def execute(self, sql, args=()):
        return self.conn.execute(sql, args)

    def one(self, sql, args=()):
        row = self.execute(sql, args).fetchone()
        return dict(row) if row else None

    def all(self, sql, args=()):
        return [dict(row) for row in self.execute(sql, args).fetchall()]

    @contextmanager
    def transaction(self):
        self.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.execute("COMMIT")
        except BaseException:
            self.execute("ROLLBACK")
            raise

    def get(self, key, default=None):
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set(self, key, value):
        self.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (key, json.dumps(value)))

    def chat(self, chat_id):
        row = self.one("SELECT * FROM chats WHERE id=?", (chat_id,))
        if not row:
            raise ValueError(tr("m_0ac48bd91130"))
        row["settings"] = DEFAULTS | json.loads(row["settings"])
        from .i18n import catalog, lazy

        # Built-in defaults follow the UI language; custom admin text stays untouched.
        for name in ("rules", "welcome_text"):
            default = DEFAULTS[name]
            if row["settings"][name] in (str.__str__(default), catalog("fa").get(default.key)):
                row["settings"][name] = lazy(default.key)
        return row

    def register(self, chat):
        self.execute(
            "INSERT INTO chats VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,kind=excluded.kind",
            (chat["id"], chat.get("title", str(chat["id"])), chat["type"], json.dumps(DEFAULTS)),
        )

    def setting(self, chat, key, value):
        conf = self.chat(chat)["settings"]
        conf[key] = value
        self.execute("UPDATE chats SET settings=? WHERE id=?", (json.dumps(conf, ensure_ascii=False), chat))

    def member(self, chat, user, name=""):
        self.execute(
            "INSERT INTO members(chat,user,name) VALUES(?,?,?) ON CONFLICT(chat,user) DO UPDATE SET name=CASE WHEN excluded.name='' THEN members.name ELSE excluded.name END",
            (chat, user, name[:100]),
        )
        return self.one("SELECT * FROM members WHERE chat=? AND user=?", (chat, user))

    def bump(self, chat, metric, n=1, ts=None):
        hour = int(ts if ts is not None else time.time()) // 60 * 60
        self.execute(
            "INSERT INTO hours VALUES(?,?,?,?) ON CONFLICT(chat,hour,metric) DO UPDATE SET n=n+excluded.n",
            (chat, hour, metric, n),
        )

    def message(self, chat, mid, user, text, kind, ts):
        with self.transaction():
            inserted = self.execute(
                "INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?)", (chat, mid, user, text[:4000], ts)
            ).rowcount
            if not inserted:
                return False
            self.bump(chat, "messages", ts=ts)
            self.bump(chat, kind, ts=ts)
            self.execute(
                "INSERT INTO activity VALUES(?,?,?,1) ON CONFLICT(chat,day,user) DO UPDATE SET n=n+1",
                (chat, ts // 60 * 60, user),
            )
        return True

    def audit(self, chat, user, mid, actor, action, reason, text="", status="done"):
        return self.execute(
            "INSERT INTO audit(chat,user,mid,actor,action,reason,text,ts,status) VALUES(?,?,?,?,?,?,?,?,?)",
            (chat, user, mid, actor, action, reason[:300], text[:4000], int(time.time()), status),
        ).lastrowid

    def train(self, chat, text, label, actor, subject=0):
        from .moderation import normalize

        text = normalize(text)[:4000]
        if len(text) < 8 or label not in ("spam", "ham"):
            raise ValueError(tr("m_7ccd1b593823"))
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.execute(
            "INSERT OR REPLACE INTO samples VALUES(?,?,?,?,?,?,?)",
            (chat, digest, text, label, actor, int(time.time()), subject),
        )
        self.execute(
            "DELETE FROM samples WHERE chat=? AND hash NOT IN (SELECT hash FROM samples WHERE chat=? ORDER BY ts DESC LIMIT 500)",
            (chat, chat),
        )

    def cooldown(self, chat, user, kind, seconds, now=None):
        now = int(time.time()) if now is None else now
        with self.transaction():
            row = self.one(
                "SELECT ts FROM command_cooldown WHERE chat=? AND user=? AND kind=?", (chat, user, kind)
            )
            if row and now - row["ts"] < seconds:
                return False
            self.execute("INSERT OR REPLACE INTO command_cooldown VALUES(?,?,?,?)", (chat, user, kind, now))
        return True

    def ai_quota(self, chat, user, group_limit, user_limit, day):
        scopes = [(f"chat:{chat}", group_limit), (f"user:{chat}:{user}", user_limit)]
        with self.transaction():
            for scope, limit in scopes:
                row = self.one("SELECT n FROM quota WHERE scope=? AND day=?", (scope, day))
                if limit <= 0 or (row and row["n"] >= limit):
                    return False
            for scope, _ in scopes:
                self.execute(
                    "INSERT INTO quota VALUES(?,?,1) ON CONFLICT(scope,day) DO UPDATE SET n=n+1", (scope, day)
                )
        return True

    def prune(self, retention_days, now=None):
        now = int(time.time()) if now is None else now
        cutoff = now - retention_days * 86400
        with self.transaction():
            self.execute("DELETE FROM messages WHERE ts<?", (cutoff,))
            self.execute("DELETE FROM join_events WHERE ts<?", (now - 86400,))
            self.execute("UPDATE audit SET text='' WHERE ts<? AND text<>''", (cutoff,))
            self.execute("DELETE FROM samples WHERE ts<?", (now - 90 * 86400,))
            self.execute("DELETE FROM games WHERE expires<?", (now - 86400,))
            self.execute("DELETE FROM attempts WHERE token NOT IN (SELECT token FROM games)")
            self.execute("DELETE FROM sessions WHERE expires<?", (now,))
            self.execute(
                "DELETE FROM inbox WHERE done=1 AND (received<? OR id NOT IN (SELECT id FROM inbox ORDER BY id DESC LIMIT 1000))",
                (cutoff,),
            )
            self.execute("DELETE FROM command_cooldown WHERE ts<?", (now - 86400,))
            self.execute(
                "DELETE FROM quota WHERE day<?", (time.strftime("%Y-%m-%d", time.gmtime(now - 7 * 86400)),)
            )
