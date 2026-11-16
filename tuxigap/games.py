from .i18n import tr, lazy
from datetime import datetime, timedelta
import json
import secrets
import time
from zoneinfo import ZoneInfo

JOKES = [
    lazy("m_62a2e52a304d"),
    lazy("m_f8f4a933dfb1"),
    lazy("m_7d5c9c25d586"),
    lazy("m_1473825993c4"),
    lazy("m_850977efc6a5"),
]
TRIVIA = [
    (
        lazy("m_59ae03d4d082"),
        [lazy("m_cdb566689830"), lazy("m_8e8cc4355beb"), lazy("m_6fdbba4a6822"), lazy("m_17a5a5d7f4c7")],
        0,
    ),
    (
        lazy("m_894f8c4f0e93"),
        [lazy("m_6464a0f9e3bb"), lazy("m_28c07e0e1d3b"), lazy("m_97cfe7ee68f5"), lazy("m_e08e33bc5ff3")],
        1,
    ),
    (
        lazy("m_a64c37119e61"),
        [lazy("m_c2494fe15e69"), lazy("m_2ded359e94b9"), lazy("m_6e0b9128cd82"), lazy("m_dad833b4b134")],
        2,
    ),
    (
        lazy("m_6a25306abff6"),
        [lazy("m_9049b29a14ae"), lazy("m_988ba8494945"), lazy("m_dbcd6d34e827"), lazy("m_3a73926280e3")],
        3,
    ),
    (
        lazy("m_56e0d8c2a574"),
        [lazy("m_18885f27b5af"), lazy("m_d9aa89fdd15a"), lazy("m_c1ba60ce1358"), lazy("m_6cc8519b9158")],
        0,
    ),
    (
        lazy("m_198012d2063c"),
        [lazy("m_1545e2e0db01"), lazy("m_1cafee498f10"), lazy("m_82cc5ee4dbae"), lazy("m_fa54b4ac8d9f")],
        1,
    ),
    (
        lazy("m_ff4cd5d7f99c"),
        [lazy("m_eecfc08eb8ff"), lazy("m_878037f2dda2"), lazy("m_95fd21f41a62"), lazy("m_a19eac7347f9")],
        2,
    ),
    (
        lazy("m_00615d6f4c34"),
        [lazy("m_805643537d79"), lazy("m_2d6f931cb306"), lazy("m_f6a2fe08f6dc"), lazy("m_56017f9af593")],
        3,
    ),
    (
        lazy("m_ef8909e74fc0"),
        [lazy("m_1cf982ef60d2"), lazy("m_4a59a742eb1f"), lazy("m_d6897876788c"), lazy("m_f7370aebde93")],
        0,
    ),
    (
        lazy("m_ac9bc8276ba9"),
        [lazy("m_ff10faa697b3"), lazy("m_a6f6bae760a2"), lazy("m_a208cafc95dd"), lazy("m_a07ac7bbc02c")],
        1,
    ),
    (
        lazy("m_8213e7a7ca93"),
        [lazy("m_61805fe672f6"), lazy("m_642abae422e6"), lazy("m_b2f527dc89bc"), lazy("m_221d1e8a77ff")],
        2,
    ),
    (
        lazy("m_ff2c6e2a7e68"),
        [lazy("m_bbaae7f70e1d"), lazy("m_f256a9f3a44d"), lazy("m_d794aecfd205"), lazy("m_5ea9939899ed")],
        3,
    ),
]


def quiz(db, chat):
    question, options, correct = secrets.choice(TRIVIA)
    token = secrets.token_hex(5)
    db.execute(
        "INSERT INTO games VALUES(?,?,?,?,NULL)",
        (token, chat, json.dumps({"answer": correct}), int(time.time()) + 300),
    )
    return question, [[{"text": label, "callback_data": f"q:{token}:{i}"}] for i, label in enumerate(options)]


def answer_quiz(db, token, user, choice):
    with db.transaction():
        game = db.one("SELECT * FROM games WHERE token=?", (token,))
        if not game or game["expires"] < time.time() or game["winner"] is not None:
            return None, tr("m_bdc30e78edd7")
        if not db.execute("INSERT OR IGNORE INTO attempts VALUES(?,?)", (token, user)).rowcount:
            return None, tr("m_e36576a11a6f")
        if int(choice) != json.loads(game["data"])["answer"]:
            return None, tr("m_645addbe140f")
        db.execute("UPDATE games SET winner=? WHERE token=?", (user, token))
        db.member(game["chat"], user)
        db.execute("UPDATE members SET xp=xp+25,coins=coins+10 WHERE chat=? AND user=?", (game["chat"], user))
        db.bump(game["chat"], "games")
    return game["chat"], tr("m_85c9a8d8af41")


def daily(db, chat, user, tz="Asia/Tehran", now=None):
    today = datetime.fromtimestamp(now or time.time(), ZoneInfo(tz)).date()
    with db.transaction():
        member = db.member(chat, user)
        if member["daily_day"] == str(today):
            return tr("m_85c8301fdcf1")
        streak = member["streak"] + 1 if member["daily_day"] == str(today - timedelta(days=1)) else 1
        reward = 10 + min(streak, 7) * 2
        db.execute(
            "UPDATE members SET daily_day=?,streak=?,coins=coins+?,xp=xp+10 WHERE chat=? AND user=?",
            (str(today), streak, reward, chat, user),
        )
    return tr("m_30f6dcf4a7b6", p0=reward, p1=streak)
