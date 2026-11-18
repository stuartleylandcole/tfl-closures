"""Turn parsed PDF rows into calendar events.

Each description paragraph ("section") is classified and its time phrases are
turned into one or more time windows. Sections in the same row that end up
with identical windows are combined into one event, so a weekend with two
part-closures on one line shows as one calendar entry rather than two.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .lines import BY_ID
from .pdf_parser import Row

# TfL's "traffic day" runs from roughly 04:30 until 01:30 the next morning.
SERVICE_START = time(4, 30)
SERVICE_END = time(1, 30)          # on the following calendar day
NIGHT_START = time(0, 30)          # Night Tube / Night Overground, morning after
NIGHT_END = time(5, 30)

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Severity order: most severe first
LINE_CLOSED, PART_CLOSED, NIGHT_CLOSED, REDUCED, LIVE = "line", "part", "night", "reduced", "live"
EMOJI = {LINE_CLOSED: "⛔", PART_CLOSED: "🚧", NIGHT_CLOSED: "🌙", REDUCED: "⚠️", LIVE: "📢"}
KIND_LABEL = {
    LINE_CLOSED: "Whole line closed",
    PART_CLOSED: "Part of the line closed",
    NIGHT_CLOSED: "Closure in the late evening or overnight only",
    REDUCED: "Reduced service or trains not stopping at some stations",
    LIVE: "Update from TfL's live status (not in the planned closures list)",
}
SEVERITY = [LINE_CLOSED, PART_CLOSED, NIGHT_CLOSED, REDUCED, LIVE]


@dataclass
class Window:
    """Either an all-day span (dates, inclusive) or a timed span (local datetimes)."""
    start: date | datetime
    end: date | datetime
    all_day: bool

    def key(self):
        return (self.all_day, self.start, self.end)

    def bounds(self) -> tuple[datetime, datetime]:
        """Approximate real-time extent, for overlap checks."""
        if self.all_day:
            return (datetime.combine(self.start, SERVICE_START),
                    datetime.combine(self.end + timedelta(days=1), SERVICE_END))
        return self.start, self.end


@dataclass
class Event:
    line_id: str
    kind: str
    title_text: str
    window: Window
    sections: list[str]
    notes: list[str]
    row_dates: str
    warnings: list[str] = field(default_factory=list)
    live_notes: list[str] = field(default_factory=list)
    source: str = "pdf"

    @property
    def title(self) -> str:
        return f"{EMOJI[self.kind]} {BY_ID[self.line_id].name}: {self.title_text}"

    @property
    def uid(self) -> str:
        w = self.window
        raw = "|".join([self.line_id, self.source, str(w.all_day), str(w.start), str(w.end),
                        _norm(self.title_text)])
        return hashlib.sha1(raw.encode()).hexdigest()[:20] + "@tfl-closures"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# ---------------------------------------------------------------- text helpers

NOTE_RE = re.compile(r"^(please|check|use |replacement)", re.I)
TIME = r"(\d{1,2}:\d{2})"


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def tidy(text: str) -> str:
    text = re.sub(r"-\s+(?=the\b)", "-", text)          # "Harrow-on- the-Hill"
    text = re.sub(r"\s+,", ",", text)
    text = text.strip().rstrip(",;.").strip()
    return text[:1].upper() + text[1:]


def split_sections(row: Row) -> tuple[list[str], list[str]]:
    """Split description paragraphs into closure sections and general notes."""
    sections, notes = [], []
    for para in row.sections:
        for part in re.split(r";\s*", para):
            part = tidy(part)
            if not part:
                continue
            (notes if NOTE_RE.match(part) else sections).append(part)
    return sections, notes


def classify(text: str) -> str:
    t = text.lower()
    if re.search(r"no service on the entire line|entire line closed|^no service\b", t):
        return LINE_CLOSED
    if re.search(r"no night overground service|no night tube service", t):
        return NIGHT_CLOSED
    if re.search(r"will not stop|reduced service|finish earlier", t):
        return REDUCED
    return PART_CLOSED


# ---------------------------------------------------------------- timing

def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _first_weekday(name: str, start: date, end: date) -> date | None:
    wd = WEEKDAYS.index(name.lower())
    for d in _days(start, end):
        if d.weekday() == wd:
            return d
    return None


def _nights(text: str, start: date, end: date) -> list[date]:
    """Evenings (as dates) on which a Night Tube/Overground-only closure applies."""
    t = text.lower()
    named = []
    if re.search(r"friday and saturday night", t):
        named = [4, 5]
    elif re.search(r"friday night", t):
        named = [4]
    elif re.search(r"saturday night", t):
        named = [5]
    if named:
        return [d for d in _days(start - timedelta(days=1), end) if d.weekday() in named]
    # Unnamed ("during Night Overground hours only"): nights inside the range
    last = end - timedelta(days=1) if end > start else start
    return [d for d in _days(start if end > start else start - timedelta(days=1), last)
            if d.weekday() in (4, 5)]


def windows_for(text: str, start: date, end: date) -> tuple[list[Window], bool]:
    """Return (windows, is_night_only) for a section's time phrases."""
    t = text.lower()
    dt = datetime.combine

    # "after 23:00 on Saturday and until 09:00 on Sunday" / "after 19:30 on Saturday until 12:00 on Sunday"
    m = re.search(rf"after {TIME}(?: on)? (\w+day),?(?: and)? until {TIME}(?: on)? (\w+day)", t)
    if m:
        d1 = _first_weekday(m[2], start, end) or start
        d2 = _first_weekday(m[4], d1, end + timedelta(days=1)) or end
        return [Window(dt(d1, _t(m[1])), dt(d2, _t(m[3])), False)], False

    # "after 23:00 Saturday and all day Sunday"
    m = re.search(rf"after {TIME}(?: on)? (\w+day) and all day (\w+day)", t)
    if m:
        d1 = _first_weekday(m[2], start, end) or start
        d2 = _first_weekday(m[3], d1, end + timedelta(days=1)) or end
        return [Window(dt(d1, _t(m[1])), dt(d2 + timedelta(days=1), SERVICE_END), False)], False

    night = re.search(r"night (tube|overground)", t) and not re.search(r"including", t)
    night = night or re.search(r"no night (overground|tube) service", t)
    if night:
        ws = []
        for d in _nights(t, start, end):
            morning = d + timedelta(days=1)
            s, e = NIGHT_START, NIGHT_END
            if m := re.search(rf"between {TIME} and {TIME}", t):
                s, e = _t(m[1]), _t(m[2])
            elif m := re.search(rf"after {TIME}", t):
                s = _t(m[1])
            ws.append(Window(dt(morning, s), dt(morning, e), False))
        if ws:
            return ws, True

    ws = []
    m_until = re.search(rf"until {TIME}", t)
    m_after = re.search(rf"after {TIME}", t)
    m_between = re.search(rf"between {TIME} and {TIME}", t)
    if m_between:
        for d in _days(start, end):
            ws.append(Window(dt(d, _t(m_between[1])), dt(d, _t(m_between[2])), False))
        return ws, False
    if m_until or m_after:
        for d in _days(start, end):
            if m_until:
                ws.append(Window(dt(d, SERVICE_START), dt(d, _t(m_until[1])), False))
            if m_after:
                a = _t(m_after[1])
                # times after midnight belong to the same traffic day
                day = d + timedelta(days=1) if a < time(4) else d
                ws.append(Window(dt(day, a), dt(d + timedelta(days=1), SERVICE_END), False))
        evening_only = bool(m_after and not m_until and _t(m_after[1]) >= time(19))
        return ws, evening_only

    return [Window(start, end, True)], False


# ---------------------------------------------------------------- rows -> events

def _fmt_range(start: date, end: date) -> str:
    if start == end:
        return f"{start:%A %-d %B %Y}"
    return f"{start:%A %-d %B} to {end:%A %-d %B %Y}"


def events_from_row(row: Row) -> list[Event]:
    if not row.start or not row.line_ids:
        return []
    end = row.end or row.start
    sections, notes = split_sections(row)
    groups: dict[tuple, list[tuple[str, str]]] = {}
    order: list[tuple] = []
    window_of: dict[tuple, Window] = {}
    for sec in sections:
        kind = classify(sec)
        wins, night_only = windows_for(sec, row.start, end)
        if kind == PART_CLOSED and night_only:
            kind = NIGHT_CLOSED
        for w in wins:
            k = w.key()
            if k not in groups:
                groups[k] = []
                order.append(k)
                window_of[k] = w
            groups[k].append((kind, sec))

    events = []
    for k in order:
        items = groups[k]
        kind = min((i[0] for i in items), key=SEVERITY.index)
        title = "; ".join(s for _, s in items)
        for line_id in row.line_ids:
            events.append(Event(
                line_id=line_id, kind=kind, title_text=title, window=window_of[k],
                sections=[s for _, s in items], notes=notes,
                row_dates=_fmt_range(row.start, end), warnings=list(row.warnings)))
    return events


REPEAT_NOTE = "TfL's PDF lists this closure in more than one week; it's shown here as one event."


def merge_repeats(events: list[Event]) -> list[Event]:
    """Combine closures that TfL lists in more than one week.

    The PDF is arranged by week, so a closure running from Saturday 26 December
    to Sunday 3 January appears in the week of 21 December *and* again in the
    week of 28 December (as Monday 28 December to Sunday 3 January). Events on
    the same line with the same wording whose dates overlap or touch become one.
    """
    out: list[Event] = []
    groups: dict[tuple, list[Event]] = {}
    for ev in events:
        groups.setdefault((ev.line_id, ev.kind, _norm(ev.title_text), ev.window.all_day), []).append(ev)
    for evs in groups.values():
        evs.sort(key=lambda e: e.window.bounds()[0])
        merged = [evs[0]]
        for ev in evs[1:]:
            cur = merged[-1]
            w, c = ev.window, cur.window
            if w.all_day and w.start <= c.end + timedelta(days=1):
                if w.end > c.end:
                    cur.window = Window(c.start, w.end, True)
                cur.row_dates = _fmt_range(cur.window.start, cur.window.end)
                cur.warnings += [x for x in ev.warnings if x not in cur.warnings]
                if REPEAT_NOTE not in cur.notes:
                    cur.notes = cur.notes + [REPEAT_NOTE]
            elif not w.all_day and w.key() == c.key():
                continue   # exact repeat of a timed window
            else:
                merged.append(ev)
        out.extend(merged)
    return sorted(out, key=lambda e: (e.window.bounds()[0], e.line_id, e.title))
