# منابع بررسی و مرز پیاده‌سازی

بررسی: ۲۰۲۶-۱۱-۱۶. این‌ها منابع مطالعهٔ امکانات‌اند؛ کدشان در بسته کپی یا vendor نشده است.

| پروژه | مجوز درج‌شده | نکتهٔ مرتبط |
|---|---|---|
| [umputun/tg-spam](https://github.com/umputun/tg-spam) | MIT | ضداسپم، حالت آزمایشی، نمونهٔ سالم/اسپم، AI و API |
| [sametcn99/tg-bot-studio](https://github.com/sametcn99/tg-bot-studio) | GPL-3.0 | مدیریت کانال و گروه، زمان‌بندی، کوییز، امتیاز و اشتراک؛ پروژهٔ کم‌ستاره در زمان بررسی |
| [Black-Bulls-Bots/zerotwobot](https://github.com/Black-Bulls-Bots/zerotwobot) | GPL-3.0 | مدیریت گروه و فرمان‌های سرگرمی؛ وابستگی‌های قدیمی |
| [Astrako/AstrakoBot](https://github.com/Astrako/AstrakoBot) | GPL-3.0 | معماری ماژولی مدیریت و فان؛ راهنمای Python قدیمی |
| [redstone-md/shield](https://github.com/redstone-md/shield) | MIT | گزینهٔ تازهٔ پیدا‌شده؛ بازبینی انسانی، سیاست اعمال و مسیر تحلیل متن/تصویر |

SaitamaRobot اصلی و PaulSonOfLars/tgbot آرشیو شده‌اند و به‌عنوان وابستگی انتخاب نشدند.
وجود یک قابلیت در منابع به معنی وجود آن در Tuxigap نیست؛ فهرست واقعی README معیار است.
هستهٔ پایتونی طبقه‌بند بیزین یا Lua را دوباره پیاده نکرده است؛ موتور واقعی tg-spam به‌صورت اختیاری با API متصل می‌شود و قابلیت‌های تخصصی خودش را ارائه می‌دهد. پنل وب تاکسی گپ مستقل است. کد انیمه، CRM و تحلیل تصویر منابع دیگر در این نسخه ادغام نشده است.

## مراجع فنی اصلی

- [Telegram Bot API](https://core.telegram.org/bots/api): مجوزها، callback، عضویت، پیام و polling.
- [Payments for digital goods](https://core.telegram.org/bots/payments-stars): Stars/XTR، pre-checkout، successful payment، پشتیبانی و بازپرداخت.
- [Star subscriptions](https://core.telegram.org/api/subscriptions): دورهٔ ۳۰روزه؛ دعوت پولی بومی کانال با دسترسی فروخته‌شدهٔ گروه یکی نیست.
- [HTTPX async](https://www.python-httpx.org/async/): اتصال HTTP غیرهم‌زمان.

فروش گروه در این پروژه با صورت‌حساب ربات + دفتر دسترسی + درخواست عضویت ساخته شده است؛
از `createChatSubscriptionInviteLink` که ویژهٔ کانال است برای گروه استفاده نشده است.
