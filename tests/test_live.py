from datetime import date, datetime
from pathlib import Path

from tfl_closures import live
from tfl_closures.events import LIVE, events_from_row
from tfl_closures.lines import resolve_line_names
from tfl_closures.pdf_parser import Row

FIXTURE = Path(__file__).parent / "fixtures" / "live_sample.json"


def _row(line, paras, start, end):
    return Row(1, line, resolve_line_names(line), start, end, "", "", paras)


def test_periods_split_at_midnight_are_joined():
    items = live.parse(live.load_fixture(FIXTURE))
    weaver_nightly = [i for i in items if i.line_id == "weaver" and len(i.periods) > 1][0]
    assert len(weaver_nightly.periods) == 4
    assert weaver_nightly.periods[0] == (datetime(2026, 11, 23, 22, 45), datetime(2026, 11, 24, 1, 29))


def test_matching_adds_live_notes_and_strikes_stay_separate():
    payload = live.load_fixture(FIXTURE)
    events = events_from_row(_row("Bakerloo", ["Queen's Park to Harrow & Wealdstone"],
                                  date(2026, 11, 21), date(2026, 11, 22)))
    events += events_from_row(_row("Weaver line", ["Hackney Downs to Enfield Town and Cheshunt, after 22:45"],
                                    date(2026, 11, 23), date(2026, 11, 26)))
    extra, report = live.merge(events, live.parse(payload), date(2026, 11, 18), live.line_ids(payload))
    assert "Replacement buses" in events[0].live_notes[0]
    assert all(e.live_notes for e in events if e.line_id == "weaver")
    strikes = [e for e in extra if e.kind == LIVE and "strike" in e.title.lower()]
    assert {e.line_id for e in strikes} == {"bakerloo", "circle", "district"}


def test_unmatched_soon_closure_is_flagged():
    payload = live.load_fixture(FIXTURE)
    events = events_from_row(_row("Central", ["Somewhere to Elsewhere"], date(2026, 11, 21), date(2026, 11, 22)))
    live.merge(events, live.parse(payload), date(2026, 11, 18), live.line_ids(payload))
    assert any("Not showing on TfL's live status" in w for w in events[0].warnings)
