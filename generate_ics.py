#!/usr/bin/env python3
"""
Build a single iCalendar feed containing every NFL game of the current season:
Hall of Fame game, all preseason weeks, all 18 regular-season weeks, and the
full postseason through the Super Bowl.

Data source: ESPN's public scoreboard API (no API key required).

Usage:
    python generate_ics.py                 # writes public/nfl.ics
    python generate_ics.py --out foo.ics   # custom output path
    python generate_ics.py --year 2026     # force a specific season year
    python generate_ics.py --fixture f.json  # build from a local JSON file (test)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# ESPN season types. 4 = off-season, ignored.
PRESEASON, REGULAR, POSTSEASON = 1, 2, 3
SEASON_TYPES = (PRESEASON, REGULAR, POSTSEASON)

# Postseason week 4 is the Pro Bowl, which is not a real game.
SKIP_WEEK_LABELS = {"pro bowl"}

GAME_DURATION = timedelta(hours=3, minutes=15)
PRODID = "-//nfl-calendar//All NFL Games//EN"
CAL_NAME = "NFL - All Games"
EMOJI = "\N{AMERICAN FOOTBALL}"  # 🏈 U+1F3C8


# ---------------------------------------------------------------- fetching


def fetch(url: str, tries: int = 4) -> dict:
    """GET JSON with a simple retry/backoff."""
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "nfl-calendar/1.0 (+github actions)"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < tries - 1:
                import time

                time.sleep(2 ** attempt)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def current_season_year(today: datetime | None = None) -> int:
    """The 2026 season runs Aug 2026 - Feb 2027, so Jan/Feb belong to the prior year."""
    today = today or datetime.now(timezone.utc)
    return today.year - 1 if today.month <= 2 else today.year


def week_numbers(payload: dict) -> dict[int, list[tuple[int, str]]]:
    """
    Read the season structure ESPN ships with every response, so the script never
    needs hand-maintained week counts. Returns {season_type: [(week, label), ...]}.
    """
    out: dict[int, list[tuple[int, str]]] = {}
    leagues = payload.get("leagues") or []
    calendar = leagues[0].get("calendar", []) if leagues else []
    for block in calendar:
        try:
            stype = int(block.get("value"))
        except (TypeError, ValueError):
            continue
        if stype not in SEASON_TYPES:
            continue
        entries = block.get("entries") or []
        weeks = []
        for entry in entries:
            try:
                num = int(entry.get("value"))
            except (TypeError, ValueError):
                continue
            label = (entry.get("label") or "").strip()
            if label.lower() in SKIP_WEEK_LABELS:
                continue
            weeks.append((num, label))
        if weeks:
            out[stype] = weeks
    return out


def collect_games(year: int) -> list[dict]:
    """Walk every week of every season type and return de-duplicated game dicts."""
    seed = fetch(f"{API}?dates={year}&seasontype={REGULAR}&week=1")

    leagues = seed.get("leagues") or [{}]
    returned = (leagues[0].get("season") or {}).get("year")
    if returned is not None and int(returned) != year:
        print(f"  {year} not published yet (API returned {returned}) - skipping", flush=True)
        return []

    structure = week_numbers(seed)
    if not structure:
        print(f"  no season structure published for {year} - skipping", flush=True)
        return []

    by_id: dict[str, dict] = {}
    for stype in SEASON_TYPES:
        for week, label in structure.get(stype, []):
            payload = fetch(f"{API}?dates={year}&seasontype={stype}&week={week}")
            events = payload.get("events") or []
            for event in events:
                game = parse_event(event, year, label)
                if game:
                    by_id[game["uid"]] = game
            print(
                f"  {year} type {stype} week {week:>2} ({label}): {len(events)} games",
                flush=True,
            )
    return sorted(by_id.values(), key=lambda g: g["start"])


# ---------------------------------------------------------------- parsing


def parse_event(event: dict, year: int, week_label: str) -> dict | None:
    event_id = event.get("id")
    raw_date = event.get("date")
    if not event_id or not raw_date:
        return None

    # ESPN returns e.g. "2026-09-13T17:00Z" (always UTC).
    start = datetime.strptime(raw_date, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)

    comps = event.get("competitions") or [{}]
    comp = comps[0]

    home = away = None
    home_full = away_full = None
    for competitor in comp.get("competitors") or []:
        team = competitor.get("team") or {}
        short = team.get("name") or team.get("shortDisplayName") or team.get("displayName")
        full = team.get("displayName") or team.get("name")
        if competitor.get("homeAway") == "home":
            home, home_full = short, full
        elif competitor.get("homeAway") == "away":
            away, away_full = short, full

    # Neutral-site games (international, Hall of Fame) read better as "vs".
    joiner = "vs" if comp.get("neutralSite") else "@"

    if home and away:
        title = f"{away} {joiner} {home}"
        matchup = f"{away_full} {joiner} {home_full}"
    else:
        title = matchup = event.get("name") or "NFL Game"

    venue = comp.get("venue") or {}
    address = venue.get("address") or {}
    location_bits = [venue.get("fullName")]
    city_bits = [address.get("city"), address.get("state") or address.get("country")]
    city = ", ".join(b for b in city_bits if b)
    if city:
        location_bits.append(city)
    location = ", ".join(b for b in location_bits if b)

    networks: list[str] = []
    for broadcast in comp.get("broadcasts") or []:
        for name in broadcast.get("names") or []:
            if name not in networks:
                networks.append(name)

    notes = [n.get("headline") for n in (comp.get("notes") or []) if n.get("headline")]

    # timeValid=False means ESPN has no confirmed kickoff yet (placeholder time).
    # isTBDFlex means the slot exists but may still be moved by flex scheduling.
    time_unknown = not comp.get("timeValid", True)
    flexible = bool(comp.get("status", {}).get("isTBDFlex"))

    desc_lines = [matchup, "", f"Season: {year}", f"Week: {week_label}"]
    if notes:
        desc_lines.append(f"Note: {notes[0]}")
    if networks:
        desc_lines.append(f"TV: {', '.join(networks)}")
    if time_unknown:
        desc_lines.append("Kickoff time not announced yet - this is a placeholder.")
    elif flexible:
        desc_lines.append("Kickoff slot may still move (flex scheduling).")
    desc_lines.append(f"https://www.espn.com/nfl/game/_/gameId/{event_id}")

    summary = f"{EMOJI} {title} (time TBD)" if time_unknown else f"{EMOJI} {title}"

    return {
        "uid": f"espn-{event_id}@nfl-calendar",
        "start": start,
        "end": start + GAME_DURATION,
        "summary": summary,
        "location": location,
        "description": "\n".join(desc_lines),
    }


# ---------------------------------------------------------------- ics output


def esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """
    RFC 5545 line folding: no line may exceed 75 octets, and a multi-byte
    character must never be split across the fold. We measure in UTF-8 bytes but
    accumulate whole characters, which makes splitting mid-character impossible.
    Continuation lines start with a space, so they only carry 74 bytes of payload.
    """
    if len(line.encode("utf-8")) <= 75:
        return line

    chunks: list[str] = []
    current, current_len, limit = "", 0, 75
    for char in line:
        size = len(char.encode("utf-8"))
        if current_len + size > limit:
            chunks.append(current)
            current, current_len, limit = char, size, 74
        else:
            current += char
            current_len += size
    if current:
        chunks.append(current)
    return "\r\n ".join(chunks)


def stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(games: list[dict], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(CAL_NAME)}",
        f"X-WR-CALDESC:{esc('Every NFL preseason, regular season and postseason game. Times are UTC and render in your local timezone. Auto-updated daily from ESPN.')}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    for game in games:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{game['uid']}",
            f"DTSTAMP:{stamp(now)}",
            f"DTSTART:{stamp(game['start'])}",
            f"DTEND:{stamp(game['end'])}",
            f"SUMMARY:{esc(game['summary'])}",
        ]
        if game["location"]:
            lines.append(f"LOCATION:{esc(game['location'])}")
        lines += [
            f"DESCRIPTION:{esc(game['description'])}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="public/nfl.ics")
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--fixture", default=None, help="build from a local JSON payload")
    args = ap.parse_args()

    games: list[dict] = []

    if args.fixture:
        payload = json.loads(Path(args.fixture).read_text())
        for event in payload.get("events") or []:
            game = parse_event(event, args.year or current_season_year(), "Fixture")
            if game:
                games.append(game)
    else:
        year = args.year or current_season_year()
        # Also pick up next season once ESPN publishes it (usually each May),
        # so the feed never goes empty between seasons.
        years = [year] if args.year else [year, year + 1]
        for candidate in years:
            print(f"Fetching {candidate} season...", flush=True)
            try:
                games += collect_games(candidate)
            except RuntimeError as exc:
                print(f"  skipped {candidate}: {exc}", file=sys.stderr)

    if not games:
        print("No games found - refusing to write an empty calendar.", file=sys.stderr)
        return 1

    seen: dict[str, dict] = {}
    for game in games:
        seen[game["uid"]] = game
    games = sorted(seen.values(), key=lambda g: g["start"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_ics(games), encoding="utf-8", newline="")

    print(
        f"Wrote {len(games)} games to {out} "
        f"({games[0]['start'].date()} → {games[-1]['start'].date()})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
