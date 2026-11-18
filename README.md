# TfL planned closures as calendars (unofficial)

TfL publishes planned track closures about six months ahead as a [31-page PDF](https://tfl.gov.uk/status-updates/planned-track-closures). This project turns it into one subscribable calendar per line, plus an all-lines calendar. It updates automatically when TfL publishes a new version.

**What people see in their calendar:**

| | Meaning |
|---|---|
| ⛔ | Whole line closed |
| 🚧 | Part of the line closed |
| 🌙 | Closed in the late evening or overnight only (after 22:45, Night Tube, etc.) |
| ⚠️ | Reduced service, or trains not stopping at some stations |
| 📢 | Something from TfL's live status that isn't in the PDF, such as a strike or a late change |

Example: `🚧 Bakerloo: Queen's Park to Harrow & Wealdstone` as an all-day event on Sat–Sun. Another example: `🌙 Weaver line: Hackney Downs to Enfield Town and Cheshunt, after 22:45` as four separate 22:45–01:30 events, Monday to Thursday.

Events are marked "free", so they never block anyone's calendar. Each event description has TfL's full wording and the dates as printed. It also has any notes we added (for example where the PDF has a date typo) and the latest wording from TfL's live status when there is any.

## How it works

```
TfL page ──► find the PDF link ──► download ──► parse (pdfplumber) ──► events
                                                                         │
TfL Unified API (next 6 weeks) ──► match / annotate / add strikes ───────┤
                                                                         ▼
                              docs/<line>.ics, all.ics, index.html, status.json
```

* **Parsing the PDF** (`pdf_parser.py`). The PDF is a Word export with merged and nested table cells, so it's read from cell borders and word positions, not table extraction. Every start-date cell is a row. The line name, end date and description are found from whichever cell sits at that row's height. This handles line names shared across rows, descriptions shared by two date ranges, and tables that continue onto the next page.
* **Dates.** Years are inferred from the publication date. Weekdays are cross-checked, and inconsistencies are corrected and noted in the event. The current PDF has "Saturday 30 – Sunday 30 January" and "Sunday 6 – Sunday 7 February".
* **Times** (`events.py`). Handles "after 22:45" (one event per evening), "until 07:45", "until 12:00 and after 20:30", "between 03:15 and 04:45", "during Friday/Saturday Night Tube only" (00:30–05:30 the morning after), "including during Saturday Night Tube" (continuous), "after 23:00 on Saturday until 09:00 on Sunday" and "after 23:00 Saturday and all day Sunday". Anything without a time is an all-day event.
* **Live status** (`live.py`). TfL's API only has planned works about 3–6 weeks ahead, so it adds to the PDF rather than replacing it. Matching closures get TfL's latest wording, such as replacement buses. Strikes and closures that aren't in the PDF are added as 📢 events. Closures in the next 10 days that the live status doesn't show get a "check before you travel" note. If the API is down, the calendars are still built from the PDF.
* **Stable event IDs.** Each event has a fixed ID based on the line, time and text. Changed or removed closures update or disappear in subscribers' calendars, with no duplicates.

## Safety checks

The scheduled job won't publish if a new PDF looks wrong. It keeps the previous calendars live, the job fails, and GitHub emails you. It counts as wrong if:

* fewer than 40 rows are parsed
* more than 5% of rows can't be turned into events
* a *new* PDF produces under 60% of the previous PDF's events
* a new PDF is dated earlier than the previous one

`docs/status.json` records what was parsed: date warnings, unreadable rows, and closures that are live-only or missing from live status.

## Setup (about 5 minutes)

1. Create a **public** GitHub repository (e.g. `tfl-closures`) and push this folder to `main`.
2. **Settings → Pages**: Source "Deploy from a branch", branch `main`, folder `/docs`.
3. **Settings → Actions → General → Workflow permissions**: "Read and write permissions".
4. **Actions → Update calendars → Run workflow** to do the first build. After that it runs twice a day.
5. Open `https://<your-username>.github.io/tfl-closures/` to see the subscribe page.

Optional:
* `TFL_APP_KEY` secret: a free key from the [TfL API portal](https://api-portal.tfl.gov.uk/). This is only needed if requests get rate-limited.
* `PDF_URL` variable: pins the PDF URL by hand if TfL changes their page and the link can't be found.
* `BASE_URL_OVERRIDE`: set in the workflow if you use a custom domain.

## Running locally

```bash
pip install -r requirements.txt
python -m pytest
python -m tfl_closures.build --out docs --base-url http://localhost:8000
# or with a local PDF and no network:
python -m tfl_closures.build --out docs --pdf tests/fixtures/plannedtrackclosures-2026-11-16.pdf --no-live
```

## Known limitations

* **Google Calendar refreshes subscriptions slowly** (roughly every 12–24 hours) and ignores the suggested refresh interval. Apple Calendar and Outlook are quicker. Event descriptions link to TfL's status page for anything last-minute.
* **Calendar colours** can't be set on a subscriber's behalf in Google. The subscribe page shows each line's colour, and Apple Calendar picks it up automatically.
* **Approximate times.** "Start of service" is taken as 04:30, "end of service" as 01:30 and Night Tube as 00:30–05:30. The exact times are in TfL's wording in each event.
* **Live status times.** The API labels times as UTC, and they're converted to London time. This was checked in November, when the two are the same. It's worth checking once British Summer Time starts that live-only events still show at the right hour.
* **Where the PDF comes from.** tfl.gov.uk refuses requests from GitHub's servers (HTTP 403), so the job downloads TfL's copy on its file server (`content.tfl.gov.uk/planned-track-closures.pdf`) instead. That copy can lag the website by about a week. The newest PDF seen is kept in `data/closures.pdf`. A download only replaces it if its "correct at" date is newer. If the newest PDF is more than 28 days old, the job fails and GitHub emails you.
* **Adding a newer PDF by hand.** Download the PDF from TfL's page. On GitHub, open the `data` folder, choose **Add file → Upload files**, and upload it as `closures.pdf`, replacing the old one. The calendars rebuild within a couple of minutes.
* **Line colours** are approximate TfL brand colours.

Not affiliated with Transport for London. Always check [TfL's status page](https://tfl.gov.uk/tube-dlr-overground/status/) before you travel.
