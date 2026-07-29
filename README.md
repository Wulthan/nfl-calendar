# NFL All Games Calendar

An iCalendar feed containing **every NFL game** - Hall of Fame
game, all preseason weeks, all 18 regular-season weeks, and the postseason
through the Super Bowl.

Subscribe once and it stays current: the feed is regenerated daily from ESPN's
public schedule data, so flex-scheduling changes, kickoff-time moves, playoff
matchups filling in, and next season's schedule all appear on their own.

## Why

Google Calendar's built-in sports calendars, and most third-party sports
calendar services, are organized **per team**. Following the whole league means
adding all 32 of them – which lands every game in your calendar twice, once from
each side. This feed is league-wide and de-duplicated instead.

## Subscribe

```
https://wulthan.github.io/nfl-calendar/nfl.ics
```

**Google Calendar** - Sidebar **+** next to “Other calendars” → **From URL** →
paste → **Add calendar**. Google refreshes subscribed feeds on its own schedule,
typically every 8–24 hours.

**Apple Calendar** – **File** → **New Calendar Subscription** → paste. Set
*Auto-refresh* to *Every day*.

**Anything else** – any client that accepts an `.ics` URL works. Use the raw
file directly if you prefer a one-off snapshot rather than a live subscription.

> Subscribe to the URL rather than downloading and importing the file. An
> import is a static snapshot and won't pick up schedule changes.

## What's in the feed

| | |
|---|---|
| Coverage | Preseason (incl. Hall of Fame game), regular season, wild card → Super Bowl |
| Events | ~330 per season, one per game |
| Duration | 3h15m per game, marked *free* so it doesn't show you as busy |
| Times | Stored in UTC - your client renders them in your local timezone |
| Extras | TV network, venue, week label, link to the ESPN gamecast |

A typical event:

```
🏈 Buccaneers @ Bengals
Sun 13 Sep 2026, 13:00–16:15   (rendered in your timezone)
Paycor Stadium, Cincinnati, OH

Tampa Bay Buccaneers @ Cincinnati Bengals

Season: 2026
Week: Week 1
TV: FOX
https://www.espn.com/nfl/game/_/gameId/401872925
```

Neutral-site games(international series, Hall of Fame) use “vs” instead of “@".
Games without a confirmed kickoff are titled `… (time TBD)`; games in a flex
window say so in the description.

## How it works

`generate_ics.py` walks ESPN's public scoreboard endpoint week by week across
all three season types, deduplicates by ESPN event ID, and writes a single
RFC 5545 calendar to `public/nfl.ics`. It reads the season structure from the
API response rather than hardcoding week counts, so it keeps working when the
league changes its format.

A GitHub Actions workflow runs it daily, commits the result, and publishes
`public/` to GitHub Pages. Event UIDs are derived from ESPN's game IDs and never
change, so updates replace existing calendar entries instead of creating
duplicates.

## Running it locally

Python 3.10+, no dependencies beyond the standard library.

```bash
python3 generate_ics.py                    # current season → public/nfl.ics
python3 generate_ics.py --year 2027        # a specific season
python3 generate_ics.py --out /tmp/x.ics   # custom output path
```

With no `--year`, the script fetches the current season plus the following one
if ESPN has published it, so the feed never goes empty between seasons.

## License

MIT - see [LICENSE](LICENSE). Not affiliated with or endorsed by the NFL or
ESPN. Schedule data belongs to its respective owners; this project is intended
for personal use.
