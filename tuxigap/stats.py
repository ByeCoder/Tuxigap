from .i18n import tr, lazy
import calendar
import csv
from datetime import datetime, timedelta, timezone
from html import escape
from io import StringIO
from zoneinfo import ZoneInfo

PERIODS = {
    "day": lazy("m_8f6356c7fa64"),
    "week": lazy("m_f95cdce37682"),
    "month": lazy("m_3eae222b1a7c"),
    "year": lazy("m_ce742d42a4be"),
}
METRICS = {
    "messages": lazy("m_6d82e3189f4d"),
    "text": lazy("m_d96ce0a50894"),
    "media": lazy("m_14585ae2b641"),
    "joins": lazy("m_1a55098b7972"),
    "leaves": lazy("m_39db927c23ae"),
    "flagged": lazy("m_a339db8565c2"),
    "deleted": lazy("m_59ca629220a6"),
    "warns": lazy("m_4f2f5bdb5ecb"),
    "mutes": lazy("m_410e49592f5d"),
    "bans": lazy("m_75d548abbf99"),
    "ai_calls": lazy("m_3b6f688fb203"),
    "games": lazy("m_21f93f3a013e"),
    "reaction_events": lazy("m_97a755ccf002"),
    "likes": lazy("m_9f23614c3173"),
    "referrals": lazy("m_0887a9f55462"),
    "engine_calls": lazy("m_9c794f45ef88"),
    "engine_errors": lazy("m_b07fe117573d"),
    "join_requests": lazy("hub.requests"),
    "requests_approved": lazy("hub.accepted_metric"),
    "requests_declined": lazy("hub.declined_metric"),
    "party_rounds": lazy("hub.party_metric"),
    "calls_started": lazy("hub.calls_metric"),
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
        raise ValueError(tr("m_b224adf7e41d"))
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
        tr("m_e70a513f92ef", p0=PERIODS[period], p1=escape(db.chat(chat)["title"])),
        tr("m_48750142f43a", p0=local_start, p1=local_end),
        tr("m_9b175afb325c", p0=escape(conf["timezone"])),
    ]
    lines.extend(f"{title}: <b>{totals.get(key, 0):,}</b>" for key, title in METRICS.items())
    lines += [
        tr("m_54d47ae9cc78", p0=active),
        tr("m_318cb6b55283", p0=subscribers),
        tr("m_3b82690f8c88", p0=revenue["n"], p1=revenue["stars"], p2=revenue["refunds"]),
    ]
    if busiest:
        peak = datetime.fromtimestamp(busiest[0]["hour"], ZoneInfo(conf["timezone"]))
        lines.append(tr("m_6ab65396102b", p0=peak, p1=busiest[0]["n"]))
    lines.append(tr("m_afe8b8b8f324"))
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
