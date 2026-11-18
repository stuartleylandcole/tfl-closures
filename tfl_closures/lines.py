"""Line metadata: TfL API ids, display names, colours and name aliases used in the PDF."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    id: str          # TfL Unified API line id, also used as the feed file name
    name: str        # Display name
    colour: str      # Hex colour (approximate TfL brand colour)
    mode: str        # tube, dlr, elizabeth-line, overground, tram, cable-car


LINES = [
    Line("bakerloo", "Bakerloo", "#B36305", "tube"),
    Line("central", "Central", "#E32017", "tube"),
    Line("circle", "Circle", "#FFD300", "tube"),
    Line("district", "District", "#00782A", "tube"),
    Line("hammersmith-city", "Hammersmith & City", "#F3A9BB", "tube"),
    Line("jubilee", "Jubilee", "#A0A5A9", "tube"),
    Line("metropolitan", "Metropolitan", "#9B0056", "tube"),
    Line("northern", "Northern", "#000000", "tube"),
    Line("piccadilly", "Piccadilly", "#003688", "tube"),
    Line("victoria", "Victoria", "#0098D4", "tube"),
    Line("waterloo-city", "Waterloo & City", "#95CDBA", "tube"),
    Line("elizabeth", "Elizabeth line", "#6950A1", "elizabeth-line"),
    Line("dlr", "DLR", "#00A4A7", "dlr"),
    Line("liberty", "Liberty line", "#61686B", "overground"),
    Line("lioness", "Lioness line", "#FAA61A", "overground"),
    Line("mildmay", "Mildmay line", "#006FE6", "overground"),
    Line("suffragette", "Suffragette line", "#18A95D", "overground"),
    Line("weaver", "Weaver line", "#9B0058", "overground"),
    Line("windrush", "Windrush line", "#DC241F", "overground"),
    Line("tram", "London Trams", "#5FB526", "tram"),
    Line("london-cable-car", "IFS Cloud Cable Car", "#E21836", "cable-car"),
]

BY_ID = {l.id: l for l in LINES}


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("&", "and").replace(",", " ").split())


# Names as they appear in the PDF's first column (normalised) -> line ids.
# Mode-level names expand to every line in that mode (used for Christmas rows).
_ALIASES = {
    "bakerloo": ["bakerloo"],
    "central": ["central"],
    "circle": ["circle"],
    "district": ["district"],
    "hammersmith and city": ["hammersmith-city"],
    "jubilee": ["jubilee"],
    "metropolitan": ["metropolitan"],
    "northern": ["northern"],
    "piccadilly": ["piccadilly"],
    "piccadilly line": ["piccadilly"],
    "victoria": ["victoria"],
    "waterloo and city": ["waterloo-city"],
    "elizabeth line": ["elizabeth"],
    "dlr": ["dlr"],
    "docklands light railway": ["dlr"],
    "liberty line": ["liberty"],
    "lioness line": ["lioness"],
    "mildmay line": ["mildmay"],
    "suffragette line": ["suffragette"],
    "weaver line": ["weaver"],
    "windrush line": ["windrush"],
    "elizabeth": ["elizabeth"],
    "liberty": ["liberty"],
    "lioness": ["lioness"],
    "mildmay": ["mildmay"],
    "suffragette": ["suffragette"],
    "weaver": ["weaver"],
    "windrush": ["windrush"],
    "london trams": ["tram"],
    "trams": ["tram"],
    "london cable car": ["london-cable-car"],
    "ifs cloud cable car": ["london-cable-car"],
    "london underground": [l.id for l in LINES if l.mode == "tube"],
    "london overground": [l.id for l in LINES if l.mode == "overground"],
}


def resolve_line_names(raw: str) -> list[str] | None:
    """Map the text of a line-name cell to line ids.

    Handles single names ("Hammersmith & City") and comma-separated lists of
    modes ("London Underground, Docklands Light Railway, Elizabeth line, ...").
    Returns None if any part is unrecognised.
    """
    tokens = _norm(raw).split()
    if not tokens:
        return None
    # Greedy longest-phrase match, so lists without commas between every
    # name ("London Overground London Trams") still resolve.
    ids: list[str] = []
    i = 0
    while i < len(tokens):
        for n in range(min(4, len(tokens) - i), 0, -1):
            phrase = " ".join(tokens[i:i + n])
            if phrase in _ALIASES:
                ids.extend(x for x in _ALIASES[phrase] if x not in ids)
                i += n
                break
        else:
            return None
    return ids
