"""Read TfL's planned track closures PDF into structured rows.

The PDF is exported from Word. Its tables have merged cells (one line name
spanning several closures, one description spanning several date ranges) and
nested tables, so pdfplumber's table extraction is unreliable. Instead we use
the cell borders (thin rectangles) and word positions directly:

  | line name | start date | end date | description |

Each start-date cell is one row. For each row we look up the line-name cell,
end-date cell and description cell that contain the row's vertical midpoint.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import pdfplumber

from .lines import resolve_line_names

DEFAULT_COLS = [72.0, 167.0, 249.0, 334.0, 523.0]
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DATE_RE = re.compile(
    r"(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+"
    r"(?P<day>\d{1,2})\s+(?P<month>" + "|".join(MONTHS) + r")(?:\s+(?P<year>\d{4}))?",
    re.I)
PUB_RE = re.compile(r"correct at date of publication\s+(.+?\d{4})", re.I)


@dataclass
class Row:
    page: int
    line_label: str
    line_ids: list[str]
    start: date | None
    end: date | None
    start_raw: str
    end_raw: str
    sections: list[str]
    warnings: list[str] = field(default_factory=list)

    @property
    def description(self) -> str:
        return "\n".join(self.sections)


@dataclass
class ParsedPdf:
    published: date
    rows: list[Row]


# ---------------------------------------------------------------- geometry

def _column_bounds(page) -> list[float]:
    """x positions of the main table's vertical borders."""
    lengths: Counter = Counter()
    for r in page.rects:
        if r["width"] < 2 and r["height"] > 5:
            lengths[round(r["x0"])] += r["height"]
    xs = sorted(x for x, _ in lengths.most_common(5))
    if len(xs) == 5 and xs[0] < 100 and xs[-1] > 450:
        return [float(x) for x in xs]
    return DEFAULT_COLS


def _cells(page, x0: float, x1: float) -> list[tuple[float, float]]:
    """Vertical extents of the cells in the column [x0, x1]."""
    tops = sorted({round(r["top"], 1) for r in page.rects
                   if r["height"] < 2 and r["x0"] <= x0 + 3 and r["x1"] >= x1 - 3})
    return list(zip(tops, tops[1:]))


def _words_in(words, x0, x1, top, bottom):
    return [w for w in words
            if x0 - 1 <= w["x0"] < x1 - 1 and top - 1 <= w["top"] < bottom - 1]


def _lines_of(words) -> list[tuple[float, str]]:
    """Group words into visual lines: [(top, text)]."""
    out: list[tuple[float, list]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if out and abs(out[-1][0] - w["top"]) < 3:
            out[-1][1].append(w)
        else:
            out.append((w["top"], [w]))
    return [(t, " ".join(x["text"] for x in sorted(ws, key=lambda w: w["x0"]))) for t, ws in out]


def _paragraphs(words) -> list[str]:
    """Split a description cell into paragraphs at blank-line gaps."""
    paras: list[list[str]] = []
    prev_top = None
    for top, text in _lines_of(words):
        if prev_top is None or top - prev_top > 20:
            paras.append([])
        paras[-1].append(text)
        prev_top = top
    return [_clean(" ".join(p)) for p in paras if p]


def _clean(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("–", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------- dates

def _resolve_date(raw: str, published: date, not_before: date | None,
                  warnings: list[str]) -> date | None:
    m = DATE_RE.search(raw)
    if not m:
        warnings.append(f"Could not read date '{raw}'")
        return None
    day, month = int(m["day"]), MONTHS[m["month"].lower()]
    wd = WEEKDAYS.index(m["wd"].lower())
    years = [int(m["year"])] if m["year"] else [published.year, published.year + 1]
    candidates = []
    for y in years:
        try:
            candidates.append(date(y, month, day))
        except ValueError:
            # e.g. "Sunday 31 April"; anchor on the 1st and let the weekday fix it
            candidates.append(date(y, month, 1) + timedelta(days=day - 1))
    lo = published - timedelta(days=21)
    in_range = [d for d in candidates if lo <= d <= published + timedelta(days=400)]
    d = in_range[0] if in_range else candidates[0]
    if d.weekday() != wd:
        # The PDF occasionally has typos in either the weekday or the number:
        #   "Sunday 6 - Sunday 7 February"     (6 Feb is a Saturday: weekday typo)
        #   "Saturday 30 - Sunday 30 January"  (30 Jan is a Saturday: number typo)
        # Trust the number, unless that would put an end date on or before a
        # start date that has a different weekday name - then trust the weekday.
        fixed = d
        if not_before and d <= not_before:
            options = [d + timedelta(days=k) for k in range(1, 7)
                       if (d + timedelta(days=k)).weekday() == wd]
            fixed = options[0]
        warnings.append(
            f"TfL's PDF says '{raw}', but {d:%-d %B %Y} is a {WEEKDAYS[d.weekday()].title()}. "
            f"Assumed {fixed:%A %-d %B}.")
        d = fixed
    return d


# ---------------------------------------------------------------- main

def parse_pdf(path: str) -> ParsedPdf:
    with pdfplumber.open(path) as pdf:
        first_text = pdf.pages[0].extract_text() or ""
        pm = PUB_RE.search(first_text)
        if not pm:
            raise ValueError("Could not find 'Correct at date of publication' on page 1")
        dm = DATE_RE.search(pm.group(1))
        if not dm or not dm["year"]:
            raise ValueError(f"Could not read publication date from '{pm.group(1)}'")
        published = date(int(dm["year"]), MONTHS[dm["month"].lower()], int(dm["day"]))

        rows: list[Row] = []
        last_label = ""
        for pno, page in enumerate(pdf.pages, start=1):
            words = [w for w in page.extract_words(extra_attrs=["size"]) if w["size"] < 13]
            c = _column_bounds(page)
            line_cells = _cells(page, c[0], c[1])
            start_cells = _cells(page, c[1], c[2])
            end_cells = _cells(page, c[2], c[3])
            desc_cells = _cells(page, c[3], c[4])

            def cell_at(cells, y):
                for t, b in cells:
                    if t <= y < b:
                        return t, b
                return None

            for t, b in start_cells:
                sw = _words_in(words, c[1], c[2], t, b)
                if not sw:
                    continue
                mid = (t + b) / 2
                warnings: list[str] = []

                lc = cell_at(line_cells, mid)
                label = _clean(" ".join(x for _, x in _lines_of(
                    _words_in(words, c[0], c[1], *lc)))) if lc else ""
                if not label:
                    # Continuation of a merged cell, possibly from the previous page
                    label = last_label
                    if not label:
                        warnings.append("No line name found")
                last_label = label

                ec = cell_at(end_cells, mid)
                dc = cell_at(desc_cells, mid)
                start_raw = _clean(" ".join(x for _, x in _lines_of(sw)))
                end_raw = _clean(" ".join(x for _, x in _lines_of(
                    _words_in(words, c[2], c[3], *ec)))) if ec else ""
                sections = _paragraphs(_words_in(words, c[3], c[4], *dc)) if dc else []
                if not sections:
                    warnings.append("No description found")

                start = _resolve_date(start_raw, published, None, warnings)
                end = _resolve_date(end_raw, published, start, warnings) if end_raw else start
                if start and end and end < start:
                    warnings.append(f"End {end} is before start {start}")
                ids = resolve_line_names(label)
                if not ids:
                    warnings.append(f"Unknown line name '{label}'")
                rows.append(Row(pno, label, ids or [], start, end,
                                start_raw, end_raw, sections, warnings))
        return ParsedPdf(published, rows)
