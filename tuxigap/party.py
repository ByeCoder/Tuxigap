"""Persistent cooperative/competitive group games. Coins never have cash value."""

from html import escape
import json
import secrets
import time

from .i18n import tr
from .ui import button

GAME_TYPES = {"number", "scramble", "riddle", "math", "wordchain"}
WORDS = ("garden", "planet", "puzzle", "friend", "rocket", "forest", "orange", "silver", "bridge", "window")
RIDDLES = (
    ("What has keys but cannot open a door?", "piano"),
    ("What gets wetter as it dries?", "towel"),
    ("What has hands but cannot clap?", "clock"),
    ("What has a neck but no head?", "bottle"),
    ("What can travel around the world while staying in a corner?", "stamp"),
)
JOKES = {
    "tech": (
        "Why do programmers prefer dark mode? Because light attracts bugs.",
        "I told my computer I needed a break. It opened 20 browser tabs.",
        "There are 10 types of people: those who understand binary and those who do not.",
        "My password is incorrect. Now my computer reminds me whenever I forget it.",
        "A SQL query walks into a cafe, approaches two tables, and asks: may I join you?",
    ),
    "animals": (
        "What do you call a bear with no teeth? A gummy bear.",
        "Why do cows wear bells? Their horns do not work.",
        "What do you call an alligator in a vest? An investigator.",
        "What did the ocean say to the penguin? Nothing. It just waved.",
        "What do cats eat for breakfast? Mice Krispies.",
    ),
    "everyday": (
        "I used to hate facial hair. Then it grew on me.",
        "Why did the bicycle fall over? It was two-tired.",
        "I am reading a book about anti-gravity. It is impossible to put down.",
        "Why did the scarecrow win an award? It was outstanding in its field.",
        "I tried to catch fog yesterday. I mist.",
    ),
}


class Party:
    def __init__(self, bot):
        self.bot, self.db, self.tg = bot, bot.db, bot.tg

    def menu(self, chat):
        return [
            [button(tr("party." + mode), f"h:{chat}:game:{mode}") for mode in pair]
            for pair in [("number", "scramble"), ("riddle", "math"), ("wordchain",)]
        ] + [[button(tr("party.scores"), f"h:{chat}:scores")]]

    async def start(self, chat, user, mode):
        if mode not in GAME_TYPES:
            raise ValueError(tr("party.usage"))
        conf = self.db.chat(chat)["settings"]
        if not conf["fun"]:
            raise ValueError(tr("m_150682b0ae9a"))
        await self.bot.require_member(chat, user)
        now = int(time.time())
        if self.db.one("SELECT 1 FROM party_games WHERE chat=? AND state='open' AND expires>?", (chat, now)):
            raise ValueError(tr("party.already"))
        if not self.db.cooldown(chat, user, "party_start", 15):
            raise ValueError(tr("party.wait"))
        if mode == "number":
            data, prompt = {"answer": str(secrets.randbelow(100) + 1)}, tr("party.number_help")
        elif mode == "scramble":
            word = secrets.choice(WORDS)
            shuffled = list(word)
            secrets.SystemRandom().shuffle(shuffled)
            if "".join(shuffled) == word:
                shuffled = shuffled[1:] + shuffled[:1]
            data, prompt = {"answer": word}, tr("party.scramble_help", word=" ".join(shuffled))
        elif mode == "riddle":
            question, answer = secrets.choice(RIDDLES)
            data, prompt = {"answer": answer}, escape(question)
        elif mode == "math":
            a, b = secrets.randbelow(80) + 10, secrets.randbelow(12) + 2
            data, prompt = {"answer": str(a * b)}, f"{a} × {b} = ?"
        else:
            word = secrets.choice(WORDS)
            data, prompt = {"words": [word], "last_user": 0}, tr("party.chain_help", word=word)
        self.db.execute("UPDATE party_games SET state='expired' WHERE chat=? AND state='open'", (chat,))
        self.db.execute(
            "INSERT INTO party_games(chat,mode,data,creator,expires) VALUES(?,?,?,?,?)",
            (chat, mode, json.dumps(data), user, now + 300),
        )
        await self.tg.send(chat, tr("party.started", mode=tr("party." + mode), prompt=prompt))

    def solve(self, chat, user, text, now=None):
        now = int(time.time()) if now is None else now
        answer = text.strip().casefold()
        with self.db.transaction():
            game = self.db.one(
                "SELECT * FROM party_games WHERE chat=? AND state='open' AND expires>? ORDER BY id DESC LIMIT 1",
                (chat, now),
            )
            if not game:
                raise ValueError(tr("party.none"))
            data = json.loads(game["data"])
            if game["mode"] == "wordchain":
                valid = (
                    2 <= len(answer) <= 24
                    and answer.isascii()
                    and answer.isalpha()
                    and answer[0] == data["words"][-1][-1]
                    and answer not in data["words"]
                    and data["last_user"] != user
                )
                if not valid:
                    raise ValueError(tr("party.chain_invalid", letter=data["words"][-1][-1]))
                data["words"].append(answer)
                data["last_user"] = user
                finished = len(data["words"]) >= 30
                points = 3
                self.db.execute(
                    "UPDATE party_games SET data=?,state=? WHERE id=?",
                    (json.dumps(data), "finished" if finished else "open", game["id"]),
                )
                result = tr("party.chain_ok", word=escape(answer), letter=answer[-1])
            else:
                count = self.db.one(
                    "SELECT n FROM party_attempts WHERE game=? AND user=?", (game["id"], user)
                )
                if count and count["n"] >= 5:
                    raise ValueError(tr("party.attempts"))
                self.db.execute(
                    "INSERT INTO party_attempts VALUES(?,?,1) ON CONFLICT(game,user) DO UPDATE SET n=n+1",
                    (game["id"], user),
                )
                if answer != data["answer"]:
                    if game["mode"] == "number" and answer.isdigit():
                        return tr("party.higher") if int(answer) < int(data["answer"]) else tr("party.lower")
                    return tr("party.try_again")
                points = 20
                self.db.execute(
                    "UPDATE party_games SET state='finished',winner=? WHERE id=? AND state='open'",
                    (user, game["id"]),
                )
                result = tr("party.won", user=user, answer=escape(answer))
            self.db.member(chat, user)
            self.db.execute(
                "UPDATE members SET xp=xp+?,coins=coins+? WHERE chat=? AND user=?",
                (points, points // 2, chat, user),
            )
            self.db.execute(
                "INSERT INTO party_scores VALUES(?,?,?,1) ON CONFLICT(chat,user) DO UPDATE SET points=points+excluded.points,rounds=rounds+1",
                (chat, user, points),
            )
            self.db.bump(chat, "party_rounds")
        return result

    def scores(self, chat):
        rows = self.db.all(
            "SELECT p.*,coalesce(m.name,cast(p.user as TEXT)) name FROM party_scores p LEFT JOIN members m ON m.chat=p.chat AND m.user=p.user WHERE p.chat=? ORDER BY points DESC,user LIMIT 15",
            (chat,),
        )
        return (
            tr("party.score_title")
            + "\n"
            + (
                "\n".join(f"{i}. {escape(r['name'])} · {r['points']}" for i, r in enumerate(rows, 1))
                or tr("party.no_scores")
            )
        )
