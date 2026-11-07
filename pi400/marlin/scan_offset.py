"""Lines up forward and backward raster rows (pure Python).

Measured 06.11. on the burn: a row running +X lies up to 0.64 mm (F3000) below a row running -X,
with a constant part (backlash) and a part growing with speed (the head lags). The table says
"burn of the forward row minus burn of the backward row" per feed; every raster row is moved by half
of that against its direction, so both land in the same place.

Only raster rows are touched: a G0 to its start, then G1s on one Y with laser-off run-up. Vector
lines change direction on the way and stay as they are. A job can opt out with NO_SCAN_OFFSET.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
NO_SCAN_OFFSET = "LUMACUT-NO-SCAN-OFFSET"
MAX_OFFSET_MM = 2.0


def valid_table(value):
    """The stored form, [[feed, offset], ...], as read back from config.json."""
    if not isinstance(value, list) or not value:
        return False
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            return False
        for n in pair:
            if isinstance(n, bool) or not isinstance(n, (int, float)) or n != n:
                return False
        if not 1 <= pair[0] <= 30000 or abs(pair[1]) > MAX_OFFSET_MM:
            return False
    return True


def parse_table(text):
    """'1000:-0.44,3000:-0.64' -> [(feed, offset)] ascending. Empty text: None."""
    text = (text or "").strip()
    if not text:
        return None
    table = []
    for part in text.split(","):
        feed, _, value = part.partition(":")
        feed, value = float(feed), float(value)
        if not 1 <= feed <= 30000 or abs(value) > MAX_OFFSET_MM:
            raise ValueError("Hin/Rück-Tabelle: Tempo 1..30000, Versatz höchstens %g mm" % MAX_OFFSET_MM)
        table.append((feed, value))
    table.sort()
    if len({f for f, _ in table}) != len(table):
        raise ValueError("Hin/Rück-Tabelle: jedes Tempo nur einmal")
    return table


def offset_at(table, feed):
    """Linear between the entries, the end values outside them: never extrapolate a measurement."""
    if feed <= table[0][0]:
        return table[0][1]
    for (f0, v0), (f1, v1) in zip(table, table[1:]):
        if feed <= f1:
            return v0 + (v1 - v0) * (feed - f0) / (f1 - f0)
    return table[-1][1]


def _is_rapid(line):
    return re.match(r"^G0?0\s", line) is not None


def _is_burn_move(line):
    return re.match(r"^G0?1\s", line) is not None


def _words(line):
    return {k: float(v) for k, v in _WORD.findall(line)}


def _shift_row(row, table, travel_x):
    """row: the G0 line and its G1 lines. New lines, or the same lines if this is no raster row."""
    start = _words(row[0])
    moves = [_words(l) for l in row[1:]]
    if "X" not in start or "Y" not in start or len(moves) < 2:
        return row, False
    y = start["Y"]
    if any(m.get("Y", y) != y or "X" not in m or "S" not in m or "Z" in m for m in moves):
        return row, False
    if not any(m["S"] == 0 for m in moves) or not any(m["S"] > 0 for m in moves):
        return row, False
    forward = moves[-1]["X"] > start["X"]
    feed = next((m["F"] for m in moves if "F" in m), None)
    if feed is None:
        return row, False
    # forward minus backward is the error: half of it goes on each direction, against it
    shift = (-offset_at(table, feed) / 2) * (1 if forward else -1)
    out = []
    for line, words in zip(row, [start] + moves):
        x = words["X"] + shift
        if not 0.0 <= x <= travel_x:
            if words.get("S", 0) > 0:
                raise ValueError("Motiv liegt zu nah am Rand für den Hin/Rück-Ausgleich (X %.2f)" % x)
            x = min(travel_x, max(0.0, x))
        out.append(re.sub(r"X\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)", "X%.3f" % x, line, count=1))
    return out, True


def apply(lines, table, travel_x):
    """(lines, number of rows moved). No table or an opted-out job: the lines as they came."""
    lines = list(lines)
    if not table or any(NO_SCAN_OFFSET in l for l in lines[:10]):
        return lines, 0
    out, row, moved = [], [], 0

    def flush():
        nonlocal row, moved
        if row:
            new, did = _shift_row(row, table, travel_x)
            out.extend(new)
            moved += did
            row = []

    for raw in lines:
        line = raw.split(";", 1)[0].strip().upper()
        if _is_rapid(line) and "X" in line:
            flush()
            row = [raw]
        elif _is_burn_move(line) and row:
            row.append(raw)
        else:
            flush()
            out.append(raw)
    flush()
    return out, moved
