from html import escape


def button(label, data):
    if len(data.encode()) > 64:
        raise ValueError("Callback exceeds Telegram limit")
    return {"text": label, "callback_data": data}


def admin_keyboard(chat, section, conf):
    def b(label, route):
        return button(label, f"a:{chat}:{route}")

    back = [b("↩️ پنل اصلی", "home")]
    if section == "home":
        return [
            [b("🛡 مدیریت و امنیت", "mod"), b("📊 آمار", "stats")],
            [b("🧠 هوش مصنوعی و یادگیری", "learn"), b("🎮 سرگرمی", "fun")],
            [b("⭐ فروش اشتراک", "plans"), b("📝 محتوا و زمان‌بندی", "content")],
            [b("⚙️ تنظیمات", "settings"), b("🔎 بررسی دسترسی", "diagnose")],
        ]
    if section == "stats":
        return [
            [b("روزانه", "stat:day"), b("هفتگی", "stat:week")],
            [b("ماهانه", "stat:month"), b("سالانه", "stat:year")],
            [b("CSV روز", "csv:day"), b("CSV سال", "csv:year")],
            [b("گزارش خودکار " + ("✅" if conf["reports"] else "❌"), "toggle:reports")],
            back,
        ]
    fields = {
        "mod": [
            ("external_spam", "موتور tg-spam"),
            ("external_review", "بازبینی نتیجهٔ موتور"),
            ("enabled", "مدیریت فعال"),
            ("dry_run", "حالت آزمایشی"),
            ("flood", "ضدفلود"),
            ("duplicates", "ضدتکرار"),
            ("profanity", "کلمات ممنوعه"),
            ("links", "قفل لینک"),
            ("forwards", "قفل فوروارد"),
            ("media", "قفل رسانه"),
            ("stickers", "قفل استیکر"),
            ("bots", "قفل ربات"),
            ("captcha", "کپچای ورود"),
        ],
        "learn": [
            ("ai", "دستیار گفتگو"),
            ("ai_moderation", "بررسی محتوای AI"),
            ("learning", "یادگیری نمونه‌ها"),
            ("learned_enforce", "اعمال خودکار نمونهٔ آموخته‌شده"),
        ],
        "settings": [("welcome", "خوشامدگویی"), ("fun", "سرگرمی فعال")],
    }
    if section in fields:
        rows = [
            [b(("✅ " if conf[key] else "❌ ") + label, "toggle:" + key)] for key, label in fields[section]
        ]
        extras = {
            "mod": [
                [b("ویرایش واژه‌ها", "input:words"), b("تنظیم فلود", "input:flood")],
                [b("سقف اخطار", "input:warn_limit"), b("زمان سکوت", "input:mute_minutes")],
                [b("واکنش: " + conf["action"], "cycle:action")],
                [b("🔒 قفل اضطراری", "lock"), b("🔓 بازگردانی مجوزها", "unlock")],
            ],
            "learn": [
                [b("نمونه‌ها و بازخوردها", "samples"), b("بررسی موارد مشکوک", "review")],
                [b("پاک‌کردن یادگیری", "resetconfirm")],
            ],
            "settings": [
                [b("منطقهٔ زمانی", "input:timezone"), b("ساعت گزارش", "input:report_hour")],
                [b("شروع هفته", "cycle:week_start")],
                [b("متن خوشامد", "input:welcome_text")],
            ],
        }
        return rows + extras.get(section, []) + [back]
    if section == "content":
        return [
            [b("🎉 قرعه‌کشی رایگان", "input:giveaway"), b("📮 نظرسنجی", "input:poll")],
            [b("یادداشت عمومی", "input:note"), b("پاسخ خودکار", "input:filter")],
            [b("مقصد گزارش مدیریت", "input:log_chat")],
            [b("قوانین", "input:rules"), b("خوشامدگویی", "input:welcome_text")],
            [b("پست زمان‌بندی‌شده", "input:schedule"), b("صف ارسال", "jobs")],
            back,
        ]
    if section == "plans":
        return [
            [b("دروازهٔ اشتراک " + ("✅" if conf["paid_gate"] else "❌"), "gateconfirm")],
            [b("ساخت طرح", "input:plan"), b("فهرست طرح‌ها", "planlist")],
            [b("گزارش درآمد", "revenue")],
            back,
        ]
    if section == "fun":
        return fun_keyboard(chat) + [back]
    return [back]


def fun_keyboard(chat):
    def b(label, route):
        return button(label, f"f:{chat}:{route}")

    return [
        [b("🔗 دعوت دوستان", "invite"), b("🏅 برترین معرف‌ها", "referrals")],
        [b("حقیقت", "truth"), b("جرئت", "dare"), b("فال سرگرمی", "fortune")],
        [b("🧩 مسابقه", "quiz"), b("🎲 تاس", "dice")],
        [b("🪨 سنگ کاغذ قیچی", "rps"), b("😄 شوخی", "joke")],
        [b("🎁 پاداش روزانه", "daily"), b("🏆 برترین‌ها", "top")],
        [b("👤 پروفایل", "profile"), b("🛍 نشان‌ها", "shop")],
        [b("👍 پسندیدم", "like"), b("📜 قوانین", "rules")],
    ]


def panel_title(chat, section):
    conf = chat["settings"]
    text = f"🤝 <b>تاکسی گپ — {escape(chat['title'])}</b>\nشناسه: <code>{chat['id']}</code>\n"
    text += (
        "🧪 حالت آزمایشی فعال: پیام حذف و کاربر محدود نمی‌شود.\n"
        if conf["dry_run"]
        else "🛡 اعمال واقعی قوانین فعال است.\n"
    )
    if section == "learn":
        text += "یادگیری از /spam و /ham و دکمه‌های بازخورد مدیر انجام می‌شود. AI فقط با فعال‌سازی و کلید سرویس کار می‌کند. موارد آموخته‌شده ابتدا برای بازبینی ارسال می‌شوند."
    elif section == "plans":
        text += "فروش با Stars؛ گروه/کانال باید خصوصی باشد. قبل از فعال‌سازی، لینک‌های قدیمی را لغو کنید. مدیران از انقضای اشتراک معاف‌اند."
    elif section == "stats":
        text += "دوره‌های تقویمی میلادی؛ هفته از شنبه (قابل تغییر). آمار از زمان اضافه‌شدن ربات جمع‌آوری می‌شود."
    elif section == "settings":
        text += f"منطقه: {escape(conf['timezone'])} | ساعت گزارش: {conf['report_hour']} | شروع هفته (دوشنبه=۰): {conf['week_start']}"
    return text
