"""Merge TfL's live line status (Unified API) into the PDF-based events.

The API only carries planned works a few weeks ahead, so it is used to:
  * add TfL's latest wording (replacement buses etc.) to closures we already have,
  * add things the PDF doesn't list (strikes, late changes) as 📢 events,
  * flag closures in the next few days that TfL's live status doesn't show.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from .events import LIVE, Event, Window
from .lines import BY_ID, LINES

API = "https://api.tfl.gov.uk"
LONDON = ZoneInfo("Europe/London")

# statusSeverity values (see /Line/Meta/Severity)
CLOSURE_SEVERITIES = {1, 2, 3, 4, 5, 11, 16}   # Closed, Suspended, Part Suspended, Planned Closure, Part Closure, Part Closed, Not Running
IGNORED_SEVERITIES = {10, 18, 19, 20}          # Good Service, No Issues, Information, Service Closed (overnight)
SPECIAL_SERVICE = 0
CHECK_HORIZON_DAYS = 10                         # flag PDF closures this soon that live status doesn't show


@dataclass
class LiveItem:
    line_id: str
    severity: int
    severity_text: str
    reason: str
    periods: list[tuple[datetime, datetime]]    # naive Europe/London local times

    @property
    def is_closure(self) -> bool:
        return self.severity in CLOSURE_SEVERITIES

    @property
    def is_strike(self) -> bool:
        return self.severity == SPECIAL_SERVICE and "strike" in self.reason.lower()


def fetch(start: date, end: date, app_key: str | None = None, timeout: int = 30) -> list[dict]:
    ids = ",".join(l.id for l in LINES)
    url = f"{API}/Line/{ids}/Status/{start:%Y-%m-%d}/to/{end:%Y-%m-%d}"
    params = {"detail": "false"}
    if app_key:
        params["app_key"] = app_key
    r = requests.get(url, params=params, timeout=timeout,
                     headers={"User-Agent": "tfl-closures-calendar (unofficial)"})
    r.raise_for_status()
    return r.json()


def _to_local(s: str) -> datetime:
    # The API labels times as UTC ("Z"); convert to London local time.
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=ZoneInfo("UTC"))
    return d.astimezone(LONDON).replace(tzinfo=None)


def _merge_periods(periods: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Join periods split at midnight (22:45-23:59 + 00:00-01:29 -> 22:45-01:29)."""
    out: list[list[datetime]] = []
    for s, e in sorted(periods):
        if out and s - out[-1][1] <= timedelta(minutes=2):
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def parse(payload: list[dict]) -> list[LiveItem]:
    items = []
    for line in payload:
        lid = line.get("id")
        if lid not in BY_ID:
            continue
        for st in line.get("lineStatuses", []):
            sev = st.get("statusSeverity")
            if sev in IGNORED_SEVERITIES:
                continue
            periods = [(_to_local(p["fromDate"]), _to_local(p["toDate"]))
                       for p in st.get("validityPeriods", []) if p.get("fromDate")]
            if not periods:
                continue
            items.append(LiveItem(lid, sev, st.get("statusSeverityDescription", ""),
                                  " ".join((st.get("reason") or "").split()),
                                  _merge_periods(periods)))
    return items


def _overlaps(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _short_reason(reason: str, limit: int = 90) -> str:
    text = re.sub(r"^[A-Z0-9&' ]+(LINE|DLR|TRAMS?)?:\s*", "", reason).strip()
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0].rstrip(".")
    return first if len(first) <= limit else first[: limit - 1].rsplit(" ", 1)[0] + "…"


def merge(events: list[Event], items: list[LiveItem], today: date,
          lines_in_payload: set[str]) -> tuple[list[Event], list[str]]:
    """Annotate PDF events with live info, add live-only events. Returns (new_events, report).

    lines_in_payload: line ids the API answered for (including Good Service),
    so we only flag "not in live status" for lines we actually checked.
    """
    report: list[str] = []
    checked = f"{today:%-d %B %Y}"
    matched_items: set[int] = set()

    for ev in events:
        eb = ev.window.bounds()
        # Strikes are never "the same thing" as an engineering closure; they
        # always get their own event, so leave them out of matching.
        hits = [(n, it) for n, it in enumerate(items)
                if it.line_id == ev.line_id and not it.is_strike
                and any(_overlaps(eb, p) for p in it.periods)]
        seen_reasons = set()
        for n, it in hits:
            matched_items.add(n)
            if it.reason and it.reason not in seen_reasons and len(seen_reasons) < 3:
                seen_reasons.add(it.reason)
                ev.live_notes.append(f"TfL live status ({it.severity_text}, checked {checked}): {it.reason}")
        start = eb[0].date()
        if (not hits and ev.line_id in lines_in_payload
                and today <= start <= today + timedelta(days=CHECK_HORIZON_DAYS)):
            ev.warnings.append(
                f"Not showing on TfL's live status as of {checked}. "
                "It may have been cancelled or not yet added, so check before you travel.")
            report.append(f"Not in live status: {ev.title} ({start:%a %-d %b})")

    new_events = []
    for n, it in enumerate(items):
        if n in matched_items or not (it.is_closure or it.is_strike):
            continue
        for s, e in it.periods:
            if e.date() < today:
                continue
            new_events.append(Event(
                line_id=it.line_id, kind=LIVE, title_text=_short_reason(it.reason) or it.severity_text,
                window=Window(s, e, False), sections=[it.reason], notes=[],
                row_dates=f"{s:%a %-d %b %H:%M} to {e:%a %-d %b %H:%M}",
                live_notes=[f"From TfL's live status ({it.severity_text}), checked {checked}."],
                source="live"))
            report.append(f"Live only: {BY_ID[it.line_id].name}: {_short_reason(it.reason)} "
                          f"({s:%a %-d %b %H:%M})")
    return new_events, report


def line_ids(payload: list[dict]) -> set[str]:
    return {l.get("id") for l in payload if l.get("id") in BY_ID}


def load_fixture(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)
