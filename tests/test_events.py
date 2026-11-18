"""Tests for the time-phrase handling. Run with: python -m pytest"""

from datetime import date, datetime

from tfl_closures.events import (LINE_CLOSED, NIGHT_CLOSED, PART_CLOSED, REDUCED,
                                 classify, events_from_row, windows_for)
from tfl_closures.lines import resolve_line_names
from tfl_closures.pdf_parser import Row, _resolve_date


def row(desc_paras, start, end, line="Weaver line"):
    return Row(1, line, resolve_line_names(line), start, end, "", "", desc_paras)


def test_all_day_weekend():
    (w,), night = windows_for("Queen's Park to Harrow & Wealdstone", date(2026, 11, 21), date(2026, 11, 22))
    assert w.all_day and w.start == date(2026, 11, 21) and w.end == date(2026, 11, 22)
    assert not night


def test_after_each_evening():
    ws, night = windows_for("Hackney Downs to Enfield Town and Cheshunt, after 22:45",
                            date(2026, 11, 23), date(2026, 11, 26))
    assert len(ws) == 4 and night
    assert ws[0].start == datetime(2026, 11, 23, 22, 45)
    assert ws[0].end == datetime(2026, 11, 24, 1, 30)


def test_until_morning():
    (w,), _ = windows_for("No service on the entire line until 10:15", date(2026, 11, 22), date(2026, 11, 22))
    assert w.end == datetime(2026, 11, 22, 10, 15)


def test_until_and_after_same_day():
    ws, _ = windows_for("Euston to Kilburn High Road, until 12:00 and after 20:30", date(2027, 1, 31), date(2027, 1, 31))
    assert [(w.start.hour, w.end.hour) for w in ws] == [(4, 12), (20, 1)]


def test_saturday_night_tube_only():
    (w,), night = windows_for("Marble Arch to Ealing Broadway, during Saturday Night Tube only",
                              date(2026, 12, 12), date(2026, 12, 13))
    assert night and w.start == datetime(2026, 12, 13, 0, 30) and w.end == datetime(2026, 12, 13, 5, 30)


def test_friday_night_tube_with_single_day_range():
    (w,), _ = windows_for("Hammersmith to Heathrow during Friday Night Tube", date(2027, 1, 30), date(2027, 1, 30))
    assert w.start == datetime(2027, 1, 30, 0, 30)


def test_including_night_tube_is_continuous():
    (w,), night = windows_for("Kennington to Morden, including during Friday and Saturday Night Tube",
                              date(2027, 1, 9), date(2027, 1, 10))
    assert w.all_day and not night


def test_after_saturday_until_sunday():
    (w,), _ = windows_for("Trains will not stop after 23:00 on Saturday and until 09:00 on Sunday",
                          date(2026, 12, 12), date(2026, 12, 13))
    assert (w.start, w.end) == (datetime(2026, 12, 12, 23), datetime(2026, 12, 13, 9))


def test_after_saturday_and_all_day_sunday():
    (w,), _ = windows_for("Trains will not stop at Acton Main Line after 23:00 Saturday and all day Sunday",
                          date(2027, 3, 6), date(2027, 3, 7))
    assert w.start == datetime(2027, 3, 6, 23) and w.end == datetime(2027, 3, 8, 1, 30)


def test_between_times_during_night_tube():
    (w,), _ = windows_for("Trains will not stop at Westminster between 03:15 and 04:45 during Friday Night Tube",
                          date(2027, 2, 5), date(2027, 2, 6))
    assert (w.start, w.end) == (datetime(2027, 2, 6, 3, 15), datetime(2027, 2, 6, 4, 45))


def test_classify():
    assert classify("No service on the entire line") == LINE_CLOSED
    assert classify("Entire line closed until 10:15") == LINE_CLOSED
    assert classify("Reduced service between Paddington and Maidenhead") == REDUCED
    assert classify("Acton Main Line: Trains will not stop") == REDUCED
    assert classify("No Night Overground service on Saturday night") == NIGHT_CLOSED
    assert classify("Baker Street to Aldgate") == PART_CLOSED


def test_sections_with_same_times_are_combined():
    evs = events_from_row(row(["Hammersmith to Tower Hill,", "Edgware Road to High Street Kensington"],
                              date(2026, 11, 28), date(2026, 11, 29), "Circle"))
    assert len(evs) == 1
    assert evs[0].title == "🚧 Circle: Hammersmith to Tower Hill; Edgware Road to High Street Kensington"


def test_notes_are_not_events():
    evs = events_from_row(row(["Services will finish earlier than normal.",
                               "Please check the TfL Journey Planner nearer the time."],
                              date(2026, 12, 24), date(2026, 12, 24), "London Trams"))
    assert len(evs) == 1 and evs[0].notes


def test_christmas_row_expands_to_every_line():
    ids = resolve_line_names("London Underground, Docklands Light Railway, Elizabeth line, London Overground London Trams")
    assert "bakerloo" in ids and "dlr" in ids and "weaver" in ids and "tram" in ids and len(ids) == 20


def test_date_typos():
    w = []
    # "Saturday 30 - Sunday 30 January": number typo in the end date
    start = _resolve_date("Saturday 30 January", date(2026, 11, 16), None, w)
    assert _resolve_date("Sunday 30 January", date(2026, 11, 16), start, w) == date(2027, 1, 31)
    # "Sunday 6 - Sunday 7 February": weekday typo in the start date
    assert _resolve_date("Sunday 6 February", date(2026, 11, 16), None, w) == date(2027, 2, 6)
    assert len(w) == 2


def test_year_rollover():
    assert _resolve_date("Sunday 23 May", date(2026, 11, 16), None, []) == date(2027, 5, 23)
    assert _resolve_date("Saturday 21 November", date(2026, 11, 16), None, []) == date(2026, 11, 21)
