"""Regression test against a saved copy of TfL's PDF (correct at 16 November 2026)."""

from datetime import date
from pathlib import Path

import pytest

from tfl_closures.events import events_from_row, merge_repeats
from tfl_closures.pdf_parser import parse_pdf

PDF = Path(__file__).parent / "fixtures" / "plannedtrackclosures-2026-11-16.pdf"
pytestmark = pytest.mark.skipif(not PDF.exists(), reason="sample PDF not present")


@pytest.fixture(scope="module")
def parsed():
    return parse_pdf(str(PDF))


def test_every_row_is_read(parsed):
    assert parsed.published == date(2026, 11, 16)
    assert len(parsed.rows) == 242
    assert all(r.line_ids and r.start and r.sections for r in parsed.rows)
    assert sum(len(events_from_row(r)) for r in parsed.rows) == 396


def test_merged_line_cells_and_page_breaks(parsed):
    # Page 7 starts mid-table: the Boxing Day rows belong to the Elizabeth line
    boxing = [r for r in parsed.rows if r.page == 7 and r.start == date(2026, 12, 26)]
    assert boxing[0].line_ids == ["elizabeth"]
    # Description cell shared by two date rows (Mildmay, page 13)
    shared = [r for r in parsed.rows if r.page == 13 and "westbound only, after 23:45" in r.description]
    assert [(r.start, r.end) for r in shared] == [(date(2027, 1, 25), date(2027, 1, 26)),
                                                  (date(2027, 1, 28), date(2027, 1, 28))]


def test_closures_listed_in_two_weeks_become_one_event(parsed):
    events = merge_repeats([e for r in parsed.rows for e in events_from_row(r)])
    assert len(events) == 389
    romford = [e for e in events if e.line_id == "elizabeth" and "Romford" in e.title_text]
    assert len(romford) == 1
    assert (romford[0].window.start, romford[0].window.end) == (date(2026, 12, 26), date(2027, 1, 3))
    assert romford[0].row_dates == "Saturday 26 December to Sunday 3 January 2027"
    # Same wording on different weekends stays separate
    liberty = [e for e in events if e.line_id == "liberty" and "Romford to Upminster" in e.title_text]
    assert len(liberty) > 3


def test_christmas_day_applies_to_all_lines(parsed):
    xmas = [r for r in parsed.rows if r.start == date(2026, 12, 25)]
    assert len(xmas) == 1 and len(xmas[0].line_ids) == 20
