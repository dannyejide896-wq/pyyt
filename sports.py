import asyncio
import time
from datetime import datetime, timedelta, timezone
from html import escape

import feedparser
import httpx

ESPN = "https://site.api.espn.com/apis/site/v2/sports"

# sport code -> list of (ESPN path, label)
SPORTS = {
    "football": [
        ("soccer/eng.1", "Premier League"),
        ("soccer/esp.1", "La Liga"),
        ("soccer/ita.1", "Serie A"),
        ("soccer/ger.1", "Bundesliga"),
        ("soccer/fra.1", "Ligue 1"),
        ("soccer/uefa.champions", "Champions League"),
    ],
    "nba": [("basketball/nba", "NBA")],
    "nfl": [("football/nfl", "NFL")],
    "mlb": [("baseball/mlb", "MLB")],
    "nhl": [("hockey/nhl", "NHL")],
}

# sport code -> RSS feeds ("all" = general sports headlines)
NEWS_FEEDS = {
    "all": ["https://feeds.bbci.co.uk/sport/rss.xml"],
    "football": [
        "https://feeds.bbci.co.uk/sport/football/rss.xml",
        "https://www.espn.com/espn/rss/soccer/news",
    ],
    "nba": ["https://www.espn.com/espn/rss/nba/news"],
    "nfl": ["https://www.espn.com/espn/rss/nfl/news"],
    "mlb": ["https://www.espn.com/espn/rss/mlb/news"],
    "nhl": ["https://www.espn.com/espn/rss/nhl/news"],
}

TRANSFER_WORDS = (
    "transfer", "signing", "signs", "loan", "bid", "deal",
    "contract", "join", "agree", "fee", "release clause",
)

# ---------- tiny TTL cache ----------
_cache: dict = {}


def cache_get(key, ttl):
    item = _cache.get(key)
    if item and time.time() - item[0] < ttl:
        return item[1]
    return None


def cache_set(key, value):
    _cache[key] = (time.time(), value)
    return value


# ---------- scoreboard (scores + fixtures) ----------
async def fetch_scoreboard(path: str, day: str):
    key = ("sb", path, day)
    hit = cache_get(key, 30)
    if hit is not None:
        return hit
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{ESPN}/{path}/scoreboard", params={"dates": day})
        r.raise_for_status()
        events = r.json().get("events", [])
    except Exception:  # noqa: BLE001
        return []  # don't cache failures
    return cache_set(key, events)


def parse_event(ev):
    try:
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = teams["home"], teams["away"]
        st = ev["status"]["type"]

        def name(c):
            t = c["team"]
            return t.get("shortDisplayName") or t.get("displayName", "?")

        return {
            "home": name(home),
            "away": name(away),
            "hscore": home.get("score", "0"),
            "ascore": away.get("score", "0"),
            "state": st.get("state"),
            "detail": st.get("shortDetail", ""),
            "date": ev.get("date", ""),
        }
    except (KeyError, IndexError):
        return None


def format_event(e):
    h, a = escape(e["home"]), escape(e["away"])
    if e["state"] == "pre":
        return f"🕒 {e['date'][11:16]} UTC  {h} vs {a}"
    if e["state"] == "in":
        return f"🔴 {escape(e['detail'])}  {h} {e['hscore']}–{e['ascore']} {a}"
    return f"✅ {escape(e['detail'])}  {h} {e['hscore']}–{e['ascore']} {a}"


async def get_scores(sport: str):
    """Today's matches for a sport. Returns None if the sport is unknown."""
    leagues = SPORTS.get(sport)
    if not leagues:
        return None
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    results = await asyncio.gather(*(fetch_scoreboard(p, today) for p, _ in leagues))

    out = [f"⚽ <b>Today's {escape(sport.upper())} matches</b>"]
    found = False
    for (_, label), events in zip(leagues, results):
        parsed = [x for x in (parse_event(ev) for ev in events) if x]
        if not parsed:
            continue
        found = True
        out.append(f"\n🏆 <b>{escape(label)}</b>")
        out.extend(format_event(e) for e in parsed)
    if not found:
        out.append("\nNo matches today.")
    return "\n".join(out)


async def get_fixtures(sport: str, days: int = 3):
    """Upcoming matches over the next few days. Returns None if sport unknown."""
    leagues = SPORTS.get(sport)
    if not leagues:
        return None
    now = datetime.now(timezone.utc)
    day_keys = [(now + timedelta(days=i)).strftime("%Y%m%d") for i in range(days + 1)]

    jobs = [(label, d, fetch_scoreboard(p, d)) for p, label in leagues for d in day_keys]
    results = await asyncio.gather(*(j[2] for j in jobs))

    rows = []
    for (label, _, _), events in zip(jobs, results):
        for ev in events:
            e = parse_event(ev)
            if e and e["state"] == "pre":
                rows.append((e["date"], label, e))
    rows.sort(key=lambda r: r[0])

    out = [f"📅 <b>Upcoming {escape(sport.upper())} fixtures</b>\n"]
    if not rows:
        out.append("No upcoming fixtures found.")
    for date, label, e in rows[:15]:
        out.append(
            f"{date[5:10]} {date[11:16]} UTC  {escape(e['home'])} vs "
            f"{escape(e['away'])}  <i>({escape(label)})</i>"
        )
    return "\n".join(out)


# ---------- news ----------
def _parse_feeds(urls):
    entries, seen = [], set()
    for url in urls:
        try:
            for e in feedparser.parse(url).entries:
                link = e.get("link")
                if link and link not in seen:
                    seen.add(link)
                    entries.append(e)
        except Exception:  # noqa: BLE001
            pass
    entries.sort(key=lambda e: e.get("published_parsed") or time.gmtime(0), reverse=True)
    return entries


async def _get_entries(sport: str):
    key = ("news", sport)
    hit = cache_get(key, 300)
    if hit is not None:
        return hit
    entries = await asyncio.to_thread(_parse_feeds, NEWS_FEEDS[sport])
    return cache_set(key, entries)


def _format_links(entries, limit=8):
    lines = []
    for e in entries[:limit]:
        title = escape(e.get("title", "Untitled"))
        lines.append(f'• <a href="{e.get("link", "")}">{title}</a>')
    return "\n".join(lines) or "Nothing found right now."


async def get_news(sport: str = "all"):
    """Latest headlines. Returns None if the sport is unknown."""
    if sport not in NEWS_FEEDS:
        return None
    entries = await _get_entries(sport)
    return f"📰 <b>Latest {escape(sport)} news</b>\n\n" + _format_links(entries)


async def get_transfers():
    entries = await _get_entries("football")
    picked = [
        e for e in entries
        if any(w in (e.get("title", "") + " " + e.get("summary", "")).lower()
               for w in TRANSFER_WORDS)
    ]
    return "🔁 <b>Transfer news</b>\n\n" + _format_links(picked)


def sports_list_text():
    codes = "\n".join(f"<code>{k}</code>" for k in SPORTS)
    return "🏅 <b>Available sports</b>\n" + codes
