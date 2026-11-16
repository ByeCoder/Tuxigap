import calendar
import csv
from datetime import datetime, timedelta, timezone
from html import escape
from io import StringIO
from zoneinfo import ZoneInfo

PERIODS = {"day": "روزانه", "week": "هفتگی", "month": "ماهانه", "year": "سالانه"}
METRICS = {
    "messages": "کل پیام",
    "text": "متنی",
    "media": "رسانه",
    "joins": "ورود",
    "leaves": "خروج",
    "flagged": "مشکوک",
    "deleted": "حذف",
    "warns": "اخطار",
    "mutes": "سکوت",
    "bans": "مسدود توسط ربات",
    "ai_calls": "درخواست هوش مصنوعی",
    "games": "بازی",
    "reaction_events": "تغییر واکنش اعضا",
    "likes": "پسندیدن تعاملی",
    "referrals": "معرفی معتبر",
    "engine_calls": "بررسی موتور ضداسپم",
    "engine_errors": "خطای موتور ضداسپم",
}


def bounds(period, tz="Asia/Tehran", now=None, previous=False, week_start=5):
    zone = ZoneInfo(tz)
    current = (now or datetime.now(timezone.utc)).astimezone(zone)
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        start -= timedelta(days=(start.weekday() - week_start) % 7)
    elif period == "month":
        start = start.replace(day=1)
    elif period == "year":
        start = start.replace(month=1, day=1)
    elif period != "day":
        raise ValueError("Invalid period")
    end = current + timedelta(microseconds=1)
    if previous:
        end = start
        if period == "day":
            start -= timedelta(days=1)
        elif period == "week":
            start -= timedelta(days=7)
        elif period == "month":
            start = (start - timedelta(days=1)).replace(day=1)
        else:
            start = start.replace(year=start.year - 1)
    return int(start.timestamp()), int(end.timestamp()) + (0 if previous else 1), start, end


def report(db, chat, period, now=None, previous=False):
    conf = db.chat(chat)["settings"]
    begin, end, local_start, local_end = bounds(period, conf["timezone"], now, previous, conf["week_start"])
    # Stored hourly buckets are UTC; half-hour timezone boundaries require finer buckets.
    # All incoming metrics are stored in 1-minute buckets by DB.bump (see db.py).
    rows = db.all(
        "SELECT metric,sum(n) n FROM hours WHERE chat=? AND hour>=? AND hour<? GROUP BY metric",
        (chat, begin, end),
    )
    totals = {r["metric"]: r["n"] for r in rows}
    active = db.one(
        "SELECT count(DISTINCT user) n FROM activity WHERE chat=? AND day>=? AND day<? AND user>0",
        (chat, begin, end),
    )["n"]
    top = db.all(
        "SELECT a.user,sum(a.n) n,coalesce(m.name,cast(a.user as TEXT)) name FROM activity a LEFT JOIN members m ON a.chat=m.chat AND a.user=m.user WHERE a.chat=? AND a.day>=? AND a.day<? AND a.user>0 GROUP BY a.user ORDER BY n DESC LIMIT 10",
        (chat, begin, end),
    )
    revenue = db.one(
        "SELECT count(*) n,coalesce(sum(stars),0) stars,coalesce(sum(CASE WHEN refunded=1 THEN stars ELSE 0 END),0) refunds FROM payments WHERE chat=? AND paid_at>=? AND paid_at<?",
        (chat, begin, end),
    )
    subscribers = db.one(
        "SELECT count(*) n FROM subscriptions WHERE chat=? AND expires>?",
        (chat, int((now or datetime.now(timezone.utc)).timestamp())),
    )["n"]
    busiest = db.all(
        "SELECT hour,sum(n) n FROM hours WHERE chat=? AND metric='messages' AND hour>=? AND hour<? GROUP BY hour ORDER BY n DESC LIMIT 1",
        (chat, begin, end),
    )
    lines = [
        f"📊 <b>آمار {PERIODS[period]} {escape(db.chat(chat)['title'])}</b>",
        f"{local_start:%Y-%m-%d %H:%M} تا {local_end:%Y-%m-%d %H:%M}",
        f"منطقهٔ زمانی: {escape(conf['timezone'])}",
    ]
    lines.extend(f"{title}: <b>{totals.get(key, 0):,}</b>" for key, title in METRICS.items())
    lines += [
        f"کاربران فعال: {active:,}",
        f"مشترک فعال اکنون: {subscribers:,}",
        f"پرداخت‌های دوره: {revenue['n']} | دریافتی: {revenue['stars']} ⭐ | برگشت این پرداخت‌ها: {revenue['refunds']} ⭐",
    ]
    if busiest:
        peak = datetime.fromtimestamp(busiest[0]["hour"], ZoneInfo(conf["timezone"]))
        lines.append(f"پرترافیک‌ترین دقیقه: {peak:%m-%d %H:%M} ({busiest[0]['n']} پیام)")
    lines.append("\n🏆 فعال‌ترین اعضا")
    lines.extend(f"{i}. {escape(r['name'])}: {r['n']:,}" for i, r in enumerate(top, 1))
    return "\n".join(lines), totals


def csv_report(db, chat, period):
    conf = db.chat(chat)["settings"]
    start, end, _, _ = bounds(period, conf["timezone"], week_start=conf["week_start"])
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["bucket_utc", "metric", "count"])
    for row in db.all(
        "SELECT hour,metric,n FROM hours WHERE chat=? AND hour>=? AND hour<? ORDER BY hour,metric",
        (chat, start, end),
    ):
        writer.writerow(
            [datetime.fromtimestamp(row["hour"], timezone.utc).isoformat(), row["metric"], row["n"]]
        )
    return output.getvalue().encode("utf-8-sig")


def month_days(year, month):
    return calendar.monthrange(year, month)[1]
