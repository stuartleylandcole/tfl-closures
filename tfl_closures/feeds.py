"""Write .ics feeds (one per line plus one for all lines)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event as VEvent, Timezone

from .events import EMOJI, KIND_LABEL, Event
from .lines import BY_ID, LINES

LONDON = ZoneInfo("Europe/London")
STATUS_URL = "https://tfl.gov.uk/tube-dlr-overground/status/"
# Required wording under TfL's Transport Data Service licence
ATTRIBUTION = "Powered by TfL Open Data"
VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/London
BEGIN:DAYLIGHT
TZOFFSETFROM:+0000
TZOFFSETTO:+0100
TZNAME:BST
DTSTART:19810329T010000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0100
TZOFFSETTO:+0000
TZNAME:GMT
DTSTART:19961027T020000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE
"""


def describe(ev: Event, published: date, pdf_url: str) -> str:
    parts = []
    parts.append(f"{EMOJI[ev.kind]} {KIND_LABEL[ev.kind]}")
    parts.append("")
    parts.extend(ev.sections)
    if ev.source == "pdf":
        parts.append(f"Dates as listed by TfL: {ev.row_dates}")
    parts.extend(ev.notes)
    if ev.warnings:
        parts.append("")
        parts.extend(f"⚠️ {w}" for w in ev.warnings)
    if ev.live_notes:
        parts.append("")
        parts.extend(ev.live_notes)
    parts.append("")
    if ev.source == "pdf":
        parts.append(f"Source: TfL planned track closures, correct at {published:%A %-d %B %Y}. {pdf_url}")
    parts.append(f"Plans can change. Check before you travel: {STATUS_URL}")
    parts.append(ATTRIBUTION)
    parts.append("Unofficial calendar, not produced or endorsed by Transport for London.")
    return "\n".join(parts)


def _vevent(ev: Event, published: date, pdf_url: str, stamp: datetime) -> VEvent:
    v = VEvent()
    v.add("uid", ev.uid)
    v.add("dtstamp", stamp)
    v.add("summary", ev.title)
    w = ev.window
    if w.all_day:
        v.add("dtstart", w.start)
        v.add("dtend", w.end + timedelta(days=1))   # DTEND is exclusive for all-day events
    else:
        v.add("dtstart", w.start.replace(tzinfo=LONDON))
        v.add("dtend", w.end.replace(tzinfo=LONDON))
    v.add("description", describe(ev, published, pdf_url))
    v.add("url", STATUS_URL)
    v.add("categories", [KIND_LABEL[ev.kind]])
    v.add("transp", "TRANSPARENT")                  # don't mark subscribers as busy
    v.add("x-microsoft-cdo-busystatus", "FREE")
    return v


def build_calendar(name: str, desc: str, colour: str | None, events: list[Event],
                   published: date, pdf_url: str, stamp: datetime) -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//tfl-closures//Unofficial TfL planned closures//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", name)
    cal.add("name", name)
    cal.add("x-wr-caldesc", desc)
    cal.add("description", desc)
    cal.add("x-wr-timezone", "Europe/London")
    cal.add("refresh-interval", timedelta(hours=6), parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", "PT6H")
    if colour:
        cal.add("x-apple-calendar-color", colour)
    cal.add_component(Timezone.from_ical(VTIMEZONE))
    for ev in sorted(events, key=lambda e: (e.window.bounds()[0], e.title)):
        cal.add_component(_vevent(ev, published, pdf_url, stamp))
    return cal


def write_feeds(out: Path, events: list[Event], published: date, pdf_url: str) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    # Keep DTSTAMP stable for a given PDF so unchanged feeds produce identical files.
    stamp = datetime(published.year, published.month, published.day, tzinfo=timezone.utc)
    counts = {}
    for line in LINES:
        evs = [e for e in events if e.line_id == line.id]
        cal = build_calendar(
            f"Planned closures: {line.name} (unofficial)",
            f"Planned closures on the {line.name}, plus live updates. "
            f"Unofficial; check before you travel. {ATTRIBUTION}.",
            line.colour, evs, published, pdf_url, stamp)
        (out / f"{line.id}.ics").write_bytes(cal.to_ical())
        counts[line.id] = len(evs)
    cal = build_calendar(
        "Planned closures: all London rail lines (unofficial)",
        "Planned closures on London's Underground, Elizabeth line, Overground, DLR, trams and "
        f"cable car, plus live updates. Unofficial; check before you travel. {ATTRIBUTION}.",
        None, events, published, pdf_url, stamp)
    (out / "all.ics").write_bytes(cal.to_ical())
    counts["all"] = len(events)
    return counts
