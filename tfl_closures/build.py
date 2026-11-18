"""Build the calendars.

    python -m tfl_closures.build --out docs --base-url https://you.github.io/tfl-closures

Downloads the latest PDF from TfL's planned track closures page (or uses
--pdf), parses it, merges TfL's live status, and writes:

    docs/<line>.ics, docs/all.ics, docs/index.html, docs/status.json

Safety checks refuse to overwrite the published files if the new PDF looks
wrong (e.g. TfL changed the layout). The script then exits with status 1, so
a scheduled GitHub Action fails and GitHub emails the repository owner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import live
from .events import events_from_row, merge_repeats
from .feeds import write_feeds
from .page import render
from .pdf_parser import parse_pdf

PAGE_URL = "https://tfl.gov.uk/status-updates/planned-track-closures"
# TfL's file server copy. Reachable from GitHub Actions (tfl.gov.uk itself
# refuses requests from cloud servers), but may lag the website by a few days.
CONTENT_URL = "https://content.tfl.gov.uk/planned-track-closures.pdf"
LINK_RE = re.compile(r"""["']([^"'\s]*?planned-?track-?closures\.pdf[^"'\s]*)["']""", re.I)
LONDON = ZoneInfo("Europe/London")
UA = {"User-Agent": "tfl-closures-calendar/1.0 (unofficial; +https://github.com/stuartleylandcole/tfl-closures)"}
STORE = Path("data/closures.pdf")           # newest good PDF, committed to the repo
STORE_META = Path("data/closures.json")

MIN_ROWS = 40                 # a real PDF has ~200+ rows
MAX_UNREADABLE_SHARE = 0.05   # rows we couldn't turn into events
MIN_EVENT_RATIO = 0.6         # new PDF must yield at least 60% of the previous PDF's events
STALE_AFTER_DAYS = 28         # fail (and so email the owner) if the newest PDF is older than this


class SafetyCheckFailed(Exception):
    pass


def discover_pdf_url() -> str:
    r = requests.get(PAGE_URL, headers=UA, timeout=30)
    r.raise_for_status()
    m = LINK_RE.search(r.text)
    if not m:
        raise RuntimeError(f"No planned track closures PDF link found on {PAGE_URL}")
    href = m.group(1).replace("&amp;", "&")
    return href if href.startswith("http") else "https://tfl.gov.uk" + href


def download(url: str, dest: Path) -> None:
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError(f"{url} did not return a PDF")
    dest.write_bytes(r.content)


def newest_pdf(tmp: Path) -> tuple[Path, str, list[str]]:
    """Pick the newest PDF among the stored copy and what can be downloaded.

    Sources: PDF_URL (if set), the link on TfL's planned closures page, and
    TfL's file server copy. A downloaded PDF replaces the stored one only if
    its "correct at" date is newer, so a lagging source never goes backwards.
    Returns (path, source_url, notes).
    """
    notes: list[str] = []
    candidates: list[tuple[date, Path, str]] = []
    if STORE.exists():
        meta = json.loads(STORE_META.read_text()) if STORE_META.exists() else {}
        # If someone uploaded a PDF by hand, the recorded URL no longer describes it
        same_file = meta.get("sha256") == hashlib.sha256(STORE.read_bytes()).hexdigest()
        try:
            candidates.append((parse_pdf(str(STORE)).published, STORE,
                               meta.get("url", PAGE_URL) if same_file else PAGE_URL))
        except Exception as e:  # noqa: BLE001
            notes.append(f"Stored PDF unreadable: {e}")

    urls: list[str] = []
    if os.environ.get("PDF_URL"):
        urls.append(os.environ["PDF_URL"])
    try:
        urls.append(discover_pdf_url())
    except Exception as e:  # noqa: BLE001
        notes.append(f"Couldn't read TfL's page ({e}); using other sources")
    urls.append(CONTENT_URL)

    for n, url in enumerate(dict.fromkeys(urls)):
        dest = tmp / f"download-{n}.pdf"
        try:
            download(url, dest)
            candidates.append((parse_pdf(str(dest)).published, dest, url))
        except Exception as e:  # noqa: BLE001
            notes.append(f"Couldn't use {url}: {e}")

    if not candidates:
        raise RuntimeError("No closures PDF available:\n  " + "\n  ".join(notes))
    # max() keeps the first of equal dates, and the stored copy is first, so a
    # download only wins when it is strictly newer.
    published, path, url = max(candidates, key=lambda c: c[0])
    if path != STORE:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_bytes(path.read_bytes())
        STORE_META.write_text(json.dumps({
            "url": url, "published": published.isoformat(),
            "sha256": hashlib.sha256(STORE.read_bytes()).hexdigest()}, indent=2) + "\n")
        notes.append(f"New PDF (correct at {published}) from {url}")
        path = STORE
    return path, url, notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="docs", type=Path)
    ap.add_argument("--base-url", default=os.environ.get("BASE_URL", "https://example.github.io/tfl-closures"))
    ap.add_argument("--pdf", help="Use this local PDF instead of downloading")
    ap.add_argument("--pdf-url", help="PDF URL to record as the source (default: discovered)")
    ap.add_argument("--no-live", action="store_true", help="Skip TfL live status")
    ap.add_argument("--live-fixture", help="Read live status from a JSON file (testing)")
    ap.add_argument("--today", type=date.fromisoformat, help="Override today's date (testing)")
    ap.add_argument("--force", action="store_true", help="Publish even if safety checks fail")
    args = ap.parse_args(argv)

    now = datetime.now(LONDON)
    today = args.today or now.date()
    out: Path = args.out
    status_path = out / "status.json"
    previous = json.loads(status_path.read_text()) if status_path.exists() else {}

    # 1. Get the PDF
    source_notes: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        if args.pdf:
            pdf_path = Path(args.pdf)
            pdf_url = args.pdf_url or previous.get("pdf_url") or PAGE_URL
        else:
            pdf_path, pdf_url, source_notes = newest_pdf(Path(tmp))
        pdf_bytes = pdf_path.read_bytes()
        pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
        parsed = parse_pdf(str(pdf_path))
    for note in source_notes:
        print("  •", note)
    if (today - parsed.published).days > STALE_AFTER_DAYS and not args.force:
        print(f"Newest PDF is correct at {parsed.published}, over {STALE_AFTER_DAYS} days old. "
              "Download the latest from TfL and add it as data/closures.pdf.", file=sys.stderr)
        return 1

    # 2. Rows -> events
    events, unreadable, warnings = [], [], []
    for row in parsed.rows:
        evs = events_from_row(row)
        if not evs:
            unreadable.append(f"p{row.page}: {row.line_label!r} {row.start_raw!r} {row.description!r}")
        warnings.extend(f"p{row.page} {row.line_label}: {w}" for w in row.warnings)
        events.extend(evs)
    events = merge_repeats(events)
    pdf_event_count = len(events)

    # 3. Safety checks (only matter when the PDF has changed)
    problems = []
    if len(parsed.rows) < MIN_ROWS:
        problems.append(f"Only {len(parsed.rows)} rows parsed (expected {MIN_ROWS}+)")
    if parsed.rows and len(unreadable) / len(parsed.rows) > MAX_UNREADABLE_SHARE:
        problems.append(f"{len(unreadable)} of {len(parsed.rows)} rows could not be read")
    if previous.get("pdf_sha256") and previous["pdf_sha256"] != pdf_sha:
        prev_count = previous.get("pdf_event_count", 0)
        if prev_count and pdf_event_count < prev_count * MIN_EVENT_RATIO:
            problems.append(f"New PDF gives {pdf_event_count} events vs {prev_count} before")
        if previous.get("published") and parsed.published.isoformat() < previous["published"]:
            problems.append(f"New PDF is dated {parsed.published}, older than {previous['published']}")
    if problems and not args.force:
        print("Safety checks failed; leaving published calendars unchanged:", file=sys.stderr)
        for p in problems + unreadable[:20]:
            print("  -", p, file=sys.stderr)
        return 1

    # 4. Live status (failures here never block publishing)
    live_report: list[str] = []
    live_ok = False
    if not args.no_live:
        try:
            payload = (live.load_fixture(args.live_fixture) if args.live_fixture
                       else live.fetch(today, today + timedelta(days=42), os.environ.get("TFL_APP_KEY")))
            extra, live_report = live.merge(events, live.parse(payload), today, live.line_ids(payload))
            events.extend(extra)
            live_ok = True
        except Exception as e:  # noqa: BLE001
            live_report = [f"Live status unavailable: {e}"]

    # Drop events that finished more than 2 weeks ago
    cutoff = today - timedelta(days=14)
    events = [e for e in events if e.window.bounds()[1].date() >= cutoff]

    # 5. Write
    counts = write_feeds(out, events, parsed.published, pdf_url)
    (out / "index.html").write_text(render(events, args.base_url, parsed.published, pdf_url, now, today))
    (out / ".nojekyll").write_text("")
    status = {
        "published": parsed.published.isoformat(),
        "pdf_url": pdf_url,
        "pdf_sha256": pdf_sha,
        "pdf_rows": len(parsed.rows),
        "pdf_event_count": pdf_event_count,
        "live_status_used": live_ok,
        "events_per_feed": counts,
        "date_warnings": warnings,
        "unreadable_rows": unreadable,
        "live_report": live_report,
    }
    status_path.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n")

    changed = previous.get("pdf_sha256") != pdf_sha
    print(f"PDF correct at {parsed.published} ({'new' if changed else 'unchanged'}): "
          f"{len(parsed.rows)} rows -> {pdf_event_count} events; "
          f"{len(events)} events published; live status {'used' if live_ok else 'not used'}")
    for line in warnings + live_report:
        print("  •", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
