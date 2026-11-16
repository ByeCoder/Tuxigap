from .i18n import tr
from html import escape


def button(label, data):
    if len(data.encode()) > 64:
        raise ValueError(tr("m_8bf43876c3b2"))
    return {"text": str(label), "callback_data": data}


def admin_keyboard(chat, section, conf):
    def b(label, route):
        return button(label, f"a:{chat}:{route}")

    back = [b(tr("m_a8d900e5c14d"), "home")]
    if section == "home":
        return [
            [b(tr("m_abfc8eb5dbde"), "mod"), b(tr("m_e8597a4b3755"), "stats")],
            [b(tr("m_1c03940d19c4"), "learn"), b(tr("m_9d4414d525e9"), "fun")],
            [b(tr("m_a76fb49d1fb2"), "plans"), b(tr("m_69dfaa570f31"), "content")],
            [b(tr("m_d8cdeb272c38"), "settings"), b(tr("m_7a4bfb66a6fb"), "diagnose")],
        ]
    if section == "stats":
        return [
            [b(tr("m_8f6356c7fa64"), "stat:day"), b(tr("m_f95cdce37682"), "stat:week")],
            [b(tr("m_3eae222b1a7c"), "stat:month"), b(tr("m_ce742d42a4be"), "stat:year")],
            [b(tr("m_ad73d685f9f9"), "csv:day"), b(tr("m_41791b7d5500"), "csv:year")],
            [b(tr("m_8e72b0c9e267") + ("✅" if conf["reports"] else "❌"), "toggle:reports")],
            back,
        ]
    fields = {
        "mod": [
            ("anti_raid", tr("m_9f1cd3e9d52a")),
            ("night_mode", tr("m_bf0671dd69c6")),
            ("external_spam", tr("m_bb56814f818a")),
            ("external_review", tr("m_ce5bd78abad9")),
            ("enabled", tr("m_aff0dd322df0")),
            ("dry_run", tr("m_213e14ab997a")),
            ("flood", tr("m_c352b13a06e4")),
            ("duplicates", tr("m_a3e33ac47c7c")),
            ("profanity", tr("m_b26426396fbe")),
            ("links", tr("m_446a7bb410db")),
            ("forwards", tr("m_ab22fa3847a6")),
            ("media", tr("m_592c07071a60")),
            ("stickers", tr("m_9845f0cbb61b")),
            ("bots", tr("m_c15ae4bc5b9e")),
            ("captcha", tr("m_6d6befecac2b")),
        ],
        "learn": [
            ("ai_vision", tr("m_f5295e02bfab")),
            ("ai", tr("m_eef99a52631f")),
            ("ai_moderation", tr("m_d85db8924dcf")),
            ("learning", tr("m_d5168c42c84a")),
            ("learned_enforce", tr("m_ce474022215a")),
        ],
        "settings": [("welcome", tr("m_31a87d66e7c1")), ("fun", tr("m_369fdab1621e"))],
    }
    if section in fields:
        rows = [
            [b(("✅ " if conf[key] else "❌ ") + label, "toggle:" + key)] for key, label in fields[section]
        ]
        extras = {
            "mod": [
                [b(tr("m_a9151517e616"), "input:locks"), b(tr("m_4ec30e9d8572"), "input:allowlist")],
                [b(tr("m_c571d1762720"), "input:night"), b(tr("m_cf45eaa439aa"), "input:limits")],
                [b(tr("m_8ad6086f90ba"), "input:words"), b(tr("m_81a33e04b657"), "input:flood")],
                [b(tr("m_13b44fc16757"), "input:warn_limit"), b(tr("m_e935140ee3f2"), "input:mute_minutes")],
                [b(tr("m_17f84c92a905") + conf["action"], "cycle:action")],
                [b(tr("m_71fed27b95b7"), "lock"), b(tr("m_feb14246cd8a"), "unlock")],
            ],
            "learn": [
                [b(tr("m_f05995ff0a9a"), "input:ai_history")],
                [b(tr("m_7249bc269d2c"), "samples"), b(tr("m_07f04b0897b8"), "review")],
                [b(tr("m_552ac0f63b53"), "resetconfirm")],
            ],
            "settings": [
                [b(tr("language.button"), "language")],
                [b(tr("m_9547b882b1cf"), "input:timezone"), b(tr("m_66345bf86920"), "input:report_hour")],
                [b(tr("m_ca005d052aa8"), "cycle:week_start")],
                [b(tr("m_5baf84bc056d"), "input:welcome_text")],
            ],
        }
        return rows + extras.get(section, []) + [back]
    if section == "content":
        return [
            [b(tr("m_81bd8553d2c2"), "input:giveaway"), b(tr("m_d6bb12c09e8c"), "input:poll")],
            [b(tr("m_80947d613bde"), "input:note"), b(tr("m_23056ed32dc4"), "input:filter")],
            [b(tr("m_9d53c448bf7a"), "input:log_chat")],
            [b(tr("m_9ce7807ac02b"), "input:rules"), b(tr("m_31a87d66e7c1"), "input:welcome_text")],
            [b(tr("m_d079523dd2b3"), "input:schedule"), b(tr("m_0cac24ed1e74"), "jobs")],
            back,
        ]
    if section == "plans":
        return [
            [b(tr("m_14b40a12dab1") + ("✅" if conf["paid_gate"] else "❌"), "gateconfirm")],
            [b(tr("m_008f5ba16721"), "input:plan"), b(tr("m_08bee76408c3"), "planlist")],
            [b(tr("m_cb4f289cb127"), "revenue")],
            back,
        ]
    if section == "fun":
        return fun_keyboard(chat) + [back]
    return [back]


def fun_keyboard(chat):
    def b(label, route):
        return button(label, f"f:{chat}:{route}")

    return [
        [b(tr("m_e9c16c89a000"), "invite"), b(tr("m_2305d58ec122"), "referrals")],
        [
            b(tr("m_94699447fe47"), "truth"),
            b(tr("m_12e925d136ff"), "dare"),
            b(tr("m_1c79b700c0c0"), "fortune"),
        ],
        [b(tr("m_776b55b5cc3e"), "quiz"), b(tr("m_85c5583d6f21"), "dice")],
        [b(tr("m_908240e67a66"), "rps"), b(tr("m_cf7f58ec85a6"), "joke")],
        [b(tr("m_d7d70cdae653"), "daily"), b(tr("m_383cd32f0d6e"), "top")],
        [b(tr("m_c2a2f1daedbb"), "profile"), b(tr("m_72ba15bd7cd2"), "shop")],
        [b(tr("m_17770198bdf0"), "like"), b(tr("m_c9bf44cfe097"), "rules")],
    ]


def panel_title(chat, section):
    conf = chat["settings"]
    text = tr("m_d5c04764ec5d", p0=escape(chat["title"]), p1=chat["id"])
    text += tr("m_2f33587afef5") if conf["dry_run"] else tr("m_39dd81968e2b")
    if section == "learn":
        text += tr("m_e5573637efd4")
    elif section == "plans":
        text += tr("m_d73d2a6086cf")
    elif section == "stats":
        text += tr("m_62f522d8c5ef")
    elif section == "settings":
        text += tr(
            "m_9926d333fcbf", p0=escape(conf["timezone"]), p1=conf["report_hour"], p2=conf["week_start"]
        )
    return text
