"""Offline multilingual humor, nonrepeating decks, member favorites and reviewed submissions."""

from functools import lru_cache
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import secrets
import time

from .i18n import LANGUAGES, current_language, tr
from .config import DEFAULTS
from .ui import button

CATEGORIES = {"everyday", "tech", "student", "work", "animals"}
COMMANDS = {
    "joke",
    "jokes",
    "jokelanguages",
    "joketop",
    "jokefavorites",
    "jokesuggest",
    "jokereview",
    "jokedefault",
}


@lru_cache(maxsize=1)
def builtins():
    result = {}
    for path in sorted(Path(__file__).with_name("jokes").glob("*.json")):
        for row in json.loads(path.read_text()):
            identity = sha256((path.stem + "\0" + row["text"]).encode()).hexdigest()[:16]
            result[identity] = {"id": identity, "language": path.stem, **row}
    return result


def public_joke(language=None):
    if language == "any":
        language = secrets.choice(list(LANGUAGES))
    if language == "auto":
        language = current_language()
    rows = [r for r in builtins().values() if r["language"] == (language or current_language())]
    return secrets.choice(rows or [r for r in builtins().values() if r["language"] == "en"])["text"]


class Humor:
    def __init__(self, bot):
        self.bot, self.db, self.tg = bot, bot.db, bot.tg

    def conf(self, chat):
        if chat > 0:
            return DEFAULTS | {
                "language": self.db.get(f"user_language:{chat}", "en"),
                "joke_language": self.db.get(f"joke_language:{chat}", "auto"),
            }
        return self.db.chat(chat)["settings"]

    async def member(self, chat, user):
        if chat > 0:
            if chat != user:
                raise ValueError(tr("hub.denied"))
        else:
            await self.bot.require_member(chat, user)

    def find(self, chat, identity):
        if identity in builtins():
            return builtins()[identity]
        row = self.db.one(
            "SELECT * FROM community_jokes WHERE id=? AND chat=? AND state='approved'", (identity, chat)
        )
        return row

    def select(self, chat, language, category="all"):
        if language == "any":
            language = secrets.choice(list(LANGUAGES))
        if language not in LANGUAGES or category not in CATEGORIES | {"all"}:
            raise ValueError(tr("humor.usage"))
        rows = [
            r
            for r in builtins().values()
            if r["language"] == language and (category == "all" or r["category"] == category)
        ]
        rows += self.db.all(
            "SELECT * FROM community_jokes WHERE chat=? AND language=? AND state='approved'"
            + (" AND category=?" if category != "all" else ""),
            (chat, language, category) if category != "all" else (chat, language),
        )
        if not rows:
            raise ValueError(tr("humor.empty"))
        seen = {
            r["joke"]
            for r in self.db.all(
                "SELECT joke FROM joke_history WHERE chat=? AND language=?", (chat, language)
            )
        }
        available = [r for r in rows if r["id"] not in seen]
        if not available:
            # Start a new deck, keeping the last card out when there is a choice.
            last = self.db.one(
                "SELECT joke FROM joke_history WHERE chat=? AND language=? ORDER BY ts DESC,rowid DESC LIMIT 1",
                (chat, language),
            )
            self.db.execute(
                "DELETE FROM joke_history WHERE chat=? AND language=? AND joke IN ("
                + ",".join("?" for _ in rows)
                + ")",
                (chat, language, *[r["id"] for r in rows]),
            )
            available = [r for r in rows if len(rows) == 1 or not last or r["id"] != last["joke"]]
        row = secrets.choice(available)
        self.db.execute(
            "INSERT OR REPLACE INTO joke_history VALUES(?,?,?,?)", (chat, language, row["id"], time.time_ns())
        )
        return row

    async def send(self, chat, user, destination, language=None, category="all"):
        await self.member(chat, user)
        if not self.conf(chat)["fun"]:
            raise ValueError(tr("m_150682b0ae9a"))
        if not self.db.cooldown(chat, user, "humor", 5):
            raise ValueError(tr("party.wait"))
        preferred = self.conf(chat)["joke_language"]
        selected = language or (self.conf(chat)["language"] if preferred == "auto" else preferred)
        row = self.select(chat, selected, category)
        keyboard = [
            [
                button(tr("humor.like"), f"j:{chat}:like:{row['id']}"),
                button(tr("humor.save"), f"j:{chat}:save:{row['id']}"),
            ],
            [
                button(tr("humor.next"), f"j:{chat}:next:{language or row['language']}:{category}"),
                button(tr("humor.languages"), f"j:{chat}:languages"),
            ],
        ]
        await self.tg.send(
            destination,
            escape(row["text"])
            + "\n\n"
            + tr(
                "humor.signature",
                language=LANGUAGES[row["language"]],
                category=tr("humor.category_" + row["category"]),
            ),
            keyboard,
        )

    async def languages(self, chat, destination):
        rows = [[button(name, f"j:{chat}:next:{code}:all")] for code, name in LANGUAGES.items()]
        await self.tg.send(destination, tr("humor.language_help"), rows)

    async def callback(self, q, parts):
        chat, user, action = int(parts[1]), q["from"]["id"], parts[2]
        await self.member(chat, user)
        if not self.conf(chat)["fun"]:
            raise ValueError(tr("m_150682b0ae9a"))
        destination = q["message"]["chat"]["id"]
        if action in ("like", "save"):
            row = self.find(chat, parts[3])
            if not row:
                raise ValueError(tr("humor.unavailable"))
            self.db.execute(
                "INSERT OR IGNORE INTO joke_reactions VALUES(?,?,?,?)", (chat, user, row["id"], action)
            )
            return await self.tg.call(
                "answerCallbackQuery",
                callback_query_id=q["id"],
                text=tr("humor.liked" if action == "like" else "humor.saved"),
            )
        await self.tg.call("answerCallbackQuery", callback_query_id=q["id"])
        if action == "next":
            return await self.send(chat, user, destination, parts[3], parts[4])
        if action == "languages":
            return await self.languages(chat, destination)
        if action in ("approve", "reject"):
            await self.bot.hub.require(chat, user, "moderation", "can_delete_messages")
            row = self.db.one(
                "SELECT * FROM community_jokes WHERE id=? AND chat=? AND state='pending'", (parts[3], chat)
            )
            if not row:
                raise ValueError(tr("humor.unavailable"))
            self.db.execute(
                "UPDATE community_jokes SET state=?,reviewer=? WHERE id=?",
                ("approved" if action == "approve" else "rejected", user, row["id"]),
            )
            self.db.audit(chat, row["author"], 0, user, "joke_review", action)
            return await self.tg.send(destination, tr("hub.saved"))
        raise ValueError(tr("hub.unknown_action"))

    async def command(self, cmd, args, message):
        chat, user = message["chat"]["id"], message["from"]["id"]
        if message["chat"]["type"] == "private":
            # Private joke reading needs no group; it still uses its own persisted deck.
            if cmd not in ("joke", "jokes", "jokelanguages", "jokefavorites", "joketop", "jokedefault"):
                raise ValueError(tr("hub.in_group"))
        await self.member(chat, user)
        if not self.conf(chat)["fun"]:
            raise ValueError(tr("m_150682b0ae9a"))
        if cmd == "jokedefault":
            if args not in set(LANGUAGES) | {"auto", "any"}:
                raise ValueError(tr("humor.default_help"))
            if chat < 0:
                await self.bot.require_admin(chat, user)
                self.db.setting(chat, "joke_language", args)
            else:
                self.db.set(f"joke_language:{user}", args)
            return await self.tg.send(chat, tr("hub.saved"))
        if cmd in ("joke", "jokes"):
            pieces = args.split()
            preferred = self.conf(chat)["joke_language"]
            language = (
                (self.conf(chat)["language"] if chat < 0 else current_language())
                if preferred == "auto"
                else preferred
            )
            category = "all"
            if pieces:
                if pieces[0] in LANGUAGES or pieces[0] == "any":
                    language = pieces.pop(0)
                if pieces:
                    category = pieces.pop(0)
                if pieces:
                    raise ValueError(tr("humor.usage"))
            return await self.send(chat, user, chat, language, category)
        if cmd == "jokelanguages":
            return await self.languages(chat, chat)
        if cmd in ("joketop", "jokefavorites"):
            rows = self.db.all(
                "SELECT joke,count(*) n FROM joke_reactions WHERE chat=? AND action=?"
                + (" AND user=?" if cmd == "jokefavorites" else "")
                + " GROUP BY joke ORDER BY n DESC,joke LIMIT 10",
                (chat, "save", user) if cmd == "jokefavorites" else (chat, "like"),
            )
            texts = []
            for r in rows:
                joke = self.find(chat, r["joke"])
                if joke:
                    texts.append(
                        escape(joke["text"][:300]) + (" · ❤️ " + str(r["n"]) if cmd == "joketop" else "")
                    )
            return await self.tg.send(chat, "\n\n".join(texts) or tr("humor.no_favorites"))
        if cmd == "jokesuggest":
            language, category, text = [p.strip() for p in args.split("|", 2)]
            if language not in LANGUAGES or category not in CATEGORIES or not 10 <= len(text) <= 700:
                raise ValueError(tr("humor.suggest_help"))
            if not self.db.cooldown(chat, user, "joke_submission", 120):
                raise ValueError(tr("party.wait"))
            count = self.db.one(
                "SELECT count(*) n FROM community_jokes WHERE chat=? AND state='pending'", (chat,)
            )["n"]
            if count >= 100:
                raise ValueError(tr("humor.review_full"))
            identity = sha256((str(chat) + "\0" + language + "\0" + text).encode()).hexdigest()[:16]
            self.db.execute(
                "INSERT OR IGNORE INTO community_jokes(id,chat,language,category,text,author,created) VALUES(?,?,?,?,?,?,?)",
                (identity, chat, language, category, text, user, int(time.time())),
            )
            return await self.tg.send(chat, tr("humor.submitted"))
        if cmd == "jokereview":
            await self.bot.hub.require(chat, user, "moderation", "can_delete_messages")
            rows = self.db.all(
                "SELECT * FROM community_jokes WHERE chat=? AND state='pending' ORDER BY created LIMIT 5",
                (chat,),
            )
            if not rows:
                return await self.tg.send(chat, tr("humor.no_pending"))
            for row in rows:
                await self.tg.send(
                    user,
                    escape(row["text"]) + "\n" + escape(row["language"] + " / " + row["category"]),
                    [
                        [
                            button(tr("hub.accept"), f"j:{chat}:approve:{row['id']}", style="success"),
                            button(tr("hub.decline"), f"j:{chat}:reject:{row['id']}", style="danger"),
                        ]
                    ],
                )
