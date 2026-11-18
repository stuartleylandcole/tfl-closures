"""Generate the subscribe page (index.html)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from urllib.parse import quote

from .events import EMOJI, KIND_LABEL, Event
from .lines import LINES

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#16181d;--muted:#5d6370;--line:#e4e2dc;--accent:#0019a8}
@media (prefers-color-scheme:dark){:root{--bg:#121316;--card:#1b1d22;--ink:#eceef2;--muted:#9aa1ad;--line:#2b2e35;--accent:#8fa2ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:1.65rem;line-height:1.2;margin:0 0 8px;letter-spacing:-.01em}
.lede{color:var(--muted);margin:0 0 18px}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:.88rem;color:var(--muted);margin:0 0 22px;padding:0;list-style:none}
.all{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:14px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between}
.all strong{font-size:1rem}
.line{background:var(--card);border:1px solid var(--line);border-radius:14px;margin-bottom:10px;overflow:hidden;display:flex}
.bar{width:10px;flex:none}
.body{padding:12px 14px;flex:1;min-width:0}
.head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.name{font-weight:650;font-size:1.05rem}
.count{color:var(--muted);font-size:.85rem;white-space:nowrap}
.next{color:var(--muted);font-size:.9rem;margin:3px 0 10px;overflow:hidden;text-overflow:ellipsis}
.btns{display:flex;flex-wrap:wrap;gap:8px}
.btn{appearance:none;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:999px;padding:6px 12px;font:inherit;font-size:.85rem;text-decoration:none;cursor:pointer}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
@media (prefers-color-scheme:dark){.btn.primary{color:#0b0d12}}
details{margin-top:10px}
summary{cursor:pointer;color:var(--muted);font-size:.88rem}
ul.upcoming{list-style:none;padding:0;margin:8px 0 0;font-size:.9rem}
ul.upcoming li{padding:6px 0;border-top:1px solid var(--line)}
.when{color:var(--muted);font-size:.82rem;display:block}
footer{color:var(--muted);font-size:.82rem;margin-top:28px;border-top:1px solid var(--line);padding-top:14px}
footer a{color:inherit}
"""

JS = """
document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(b.dataset.copy);const t=b.textContent;b.textContent='Copied';setTimeout(()=>b.textContent=t,1500)}
  catch(e){prompt('Copy this calendar link:',b.dataset.copy)}
}));
"""


def _when(ev: Event) -> str:
    w = ev.window
    if w.all_day:
        if w.start == w.end:
            return f"{w.start:%a %-d %b}"
        return f"{w.start:%a %-d %b} – {w.end:%a %-d %b}"
    if w.start.date() == w.end.date() or w.end - w.start < timedelta(hours=12):
        return f"{w.start:%a %-d %b, %H:%M}–{w.end:%H:%M}"
    return f"{w.start:%a %-d %b %H:%M} – {w.end:%a %-d %b %H:%M}"


def _buttons(url: str) -> str:
    webcal = "webcal://" + url.split("://", 1)[1]
    google = "https://calendar.google.com/calendar/render?cid=" + quote(webcal, safe="")
    return (f'<a class="btn primary" href="{escape(google)}" target="_blank" rel="noopener">Google Calendar</a>'
            f'<a class="btn" href="{escape(webcal)}">Apple / Outlook</a>'
            f'<button class="btn" type="button" data-copy="{escape(url)}">Copy link</button>')


def render(events: list[Event], base_url: str, published: date, pdf_url: str,
           updated: datetime, today: date) -> str:
    base = base_url.rstrip("/")
    upcoming = sorted((e for e in events if e.window.bounds()[1].date() >= today),
                      key=lambda e: (e.window.bounds()[0], e.title))
    legend = "".join(f"<li>{EMOJI[k]} {escape(KIND_LABEL[k])}</li>" for k in EMOJI)
    cards = []
    for line in LINES:
        evs = [e for e in upcoming if e.line_id == line.id]
        if not evs and line.mode in ("tram", "cable-car"):
            continue
        nxt = (f"Next: {escape(_when(evs[0]))} · {EMOJI[evs[0].kind]} {escape(evs[0].title_text)}"
               if evs else "No planned closures listed")
        items = "".join(
            f'<li><span class="when">{escape(_when(e))}</span>{EMOJI[e.kind]} {escape(e.title_text)}</li>'
            for e in evs[:12])
        more = f'<li class="when">…and {len(evs) - 12} more in the calendar</li>' if len(evs) > 12 else ""
        details = (f"<details><summary>Upcoming closures</summary><ul class=\"upcoming\">{items}{more}</ul></details>"
                   if evs else "")
        cards.append(
            f'<section class="line"><div class="bar" style="background:{line.colour}"></div><div class="body">'
            f'<div class="head"><span class="name">{escape(line.name)}</span>'
            f'<span class="count">{len(evs)} upcoming</span></div>'
            f'<div class="next">{nxt}</div>'
            f'<div class="btns">{_buttons(f"{base}/{line.id}.ics")}</div>{details}</div></section>')

    return f"""<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TfL planned closures as calendars (unofficial)</title>
<meta name="description" content="Subscribe to planned track closures for the London lines you use, in Google, Apple or Outlook calendar.">
<style>{CSS}</style></head>
<body><main>
<h1>TfL planned closures, in your calendar</h1>
<p class="lede">Subscribe to the lines you use. Closures appear in your calendar and update automatically when TfL publishes changes.</p>
<ul class="legend">{legend}</ul>
<div class="all"><strong>Every line in one calendar</strong><div class="btns">{_buttons(f"{base}/all.ics")}</div></div>
{''.join(cards)}
<footer>
<p>Built from TfL's <a href="{escape(pdf_url)}">planned track closures list</a> (correct at {published:%-d %B %Y}) and TfL's live line status. Checked daily, last updated {updated:%-d %B %Y, %H:%M}.</p>
<p>Plans can change at short notice. <a href="https://tfl.gov.uk/tube-dlr-overground/status/">Check TfL's status page</a> before you travel. This is an unofficial project and isn't affiliated with Transport for London.</p>
<p>Google Calendar refreshes subscribed calendars roughly every 12–24 hours. On a phone, the Google link opens in your browser; the calendar then appears in the app.</p>
</footer>
</main><script>{JS}</script></body></html>
"""
