from ..i18n import lazy

# SPDX-License-Identifier: GPL-3.0-only
# Adapted from Black-Bulls-Bots/zerotwobot, modules/fun_strings.py
# Upstream commit 6f2da0d530a2adeecbebd1c4dc526e4a5144ee03; original authors credited in THIRD_PARTY_NOTICES.md.
import secrets

TOSS = (lazy("m_b909fd558952"), lazy("m_cc43566b300e"))
DECIDE = (lazy("m_5f9a2b795615"), lazy("m_38178a20b470"), lazy("m_6646f562f04c"))
EIGHTBALL = (
    lazy("m_8fe2c73609da"),
    lazy("m_04eb468ebd2e"),
    lazy("m_b9b582075442"),
    lazy("m_4633786ae045"),
    lazy("m_4f846f622315"),
    lazy("m_535b81c1dfcb"),
    lazy("m_5daa0e6e892b"),
    lazy("m_483ca2f6347a"),
    lazy("m_2a882e0c56da"),
    lazy("m_16064cfbe44d"),
)
EYES = [("⌐■", "■"), ("◕", "◕"), ("^", "^"), ("ಠ", "ಠ"), ("•", "•")]
MOUTHS = ("ᴥ", "ω", "‿", "﹏", "ヮ")
EARS = [("ʕ", "ʔ"), ("(", ")"), ("[", "]"), ("ᕦ(", ")ᕥ")]


def emoticon():
    left, right = secrets.choice(EARS)
    a, b = secrets.choice(EYES)
    return left + a + secrets.choice(MOUTHS) + b + right


# Adapted from Astrako/AstrakoBot, modules/shout.py; bounded to avoid Telegram limits.
def shout(text):
    text = text.strip()[:25]
    if not text:
        return ""
    lines = [" ".join(text)]
    for position, symbol in enumerate(text[1:]):
        lines.append(symbol + " " + "  " * position + symbol)
    return "\n".join(lines)
