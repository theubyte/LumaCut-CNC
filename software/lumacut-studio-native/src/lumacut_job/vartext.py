"""Variable text: text objects whose placeholders are evaluated when the job
is built (send, one-click start, frame, estimate, "G-Code speichern").

LightBurn calls this *Variable Text* (serial number, date/time, *Merge CSV*).
It is opt-in per text object: only text shapes carrying the generator dict ::

    {"kind": "vartext", "version": 1, "spec": {...}}

are evaluated. ``Shape.text`` always stays the *template* (that is what the
canvas shows and what the project file stores); the evaluated text only
exists in the job document built by :func:`evaluate_document`. After a
successful upload the Studio advances the persisted counter / CSV row with
:func:`advanced_spec` (``vartext_qt``), so the next job gets the next value.

Placeholders (same syntax as the batch „Seriennummern…“ in :mod:`serial`):

``{n}``            counter (zero padded to ``pad`` digits)
``{n:3}``          counter padded to 3 digits (overrides ``pad``)
``{date}``         date ``TT.MM.JJJJ``; ``{date:%Y-%m-%d}`` own format
``{time}``         time ``HH:MM``;      ``{time:%H%M%S}`` own format
``{row}``          number of the CSV data row (1 = first row after the header)
``{Name}``         CSV column by header name (``{csv:Name}`` if the name
                   collides with a placeholder above, ``{csv:2}`` = 2nd column)
``{{`` ``}}``      literal braces

Format codes for date/time: ``%d %m %Y %y %H %M %S %j %V %%`` (implemented
here, independent of the platform's ``strftime``).

Copies: all variable text objects with the same ``series`` id form one
series. With ``per_copy`` the copies in one job (reading order: top to
bottom, then left to right) get consecutive values / rows and the counter
advances by the number of copies; without it all copies show the same value
and the counter advances by one ``step`` per job.

Pure Python, no Qt (the text width function is passed in).
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import math
import os
import re
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Callable

from lumacut_canvas.model import Document, Shape, new_id, rotate_point

KIND = "vartext"
VERSION = 1
VALUE_RANGE = (-999_999_999, 999_999_999)
STEP_RANGE = (-999_999, 999_999)
PAD_RANGE = (0, 12)
ROW_RANGE = (1, 1_000_000)
MAX_CSV_BYTES = 20 * 1024 * 1024
MAX_CSV_ROWS = 200_000
DATE_DEFAULT = "%d.%m.%Y"
TIME_DEFAULT = "%H:%M"
RESERVED = ("n", "date", "time", "row", "csv")

_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")
_FMT_CODES = set("dmYyHMSjV%")


class VarTextError(ValueError):
    """Template cannot be evaluated (unknown placeholder, CSV problem, …)."""


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class VarTextSpec:
    series: str = ""             # shared by all copies of one variable text
    start: int = 1               # counter start (for „Zurücksetzen“)
    step: int = 1
    pad: int = 0                 # default zero padding of {n}
    current: int = 1             # value of the next job (persisted, advances)
    per_copy: bool = True        # copies in one job get consecutive values
    csv_path: str = ""
    csv_row: int = 1             # next CSV data row, 1-based (header excluded)
    advance_row: bool = True     # next row(s) after every sent job

    def normalized(self) -> "VarTextSpec":
        return VarTextSpec(
            series=str(self.series or ""),
            start=int(_clamp(int(self.start), *VALUE_RANGE)),
            step=int(_clamp(int(self.step), *STEP_RANGE)),
            pad=int(_clamp(int(self.pad), *PAD_RANGE)),
            current=int(_clamp(int(self.current), *VALUE_RANGE)),
            per_copy=bool(self.per_copy),
            csv_path=str(self.csv_path or "").strip(),
            csv_row=int(_clamp(int(self.csv_row), *ROW_RANGE)),
            advance_row=bool(self.advance_row),
        )


# --- placeholders -------------------------------------------------------------

def placeholders(template: str) -> list[tuple[str, str | None]]:
    """(name, argument) of every placeholder in ``template`` (no literals)."""
    out = []
    for m in _TOKEN.finditer(template or ""):
        if m.group(1) is not None:
            out.append(_split(m.group(1)))
    return out


def _split(inner: str) -> tuple[str, str | None]:
    name, sep, arg = inner.partition(":")
    return name.strip(), (arg if sep else None)


def has_placeholders(template: str) -> bool:
    return bool(placeholders(template))


def uses_csv(template: str) -> bool:
    return any(name not in RESERVED[:4] for name, _ in placeholders(template))


def uses_counter(template: str) -> bool:
    return any(name == "n" for name, _ in placeholders(template))


def format_datetime(fmt: str, now: _dt.datetime) -> str:
    """``%``-format with a fixed, platform independent set of codes."""
    out, i = [], 0
    while i < len(fmt):
        ch = fmt[i]
        if ch != "%":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= len(fmt) or fmt[i + 1] not in _FMT_CODES:
            code = fmt[i:i + 2]
            raise VarTextError(f"Datumsformat „{fmt}“: „{code}“ unbekannt "
                               "(erlaubt: %d %m %Y %y %H %M %S %j %V %%)")
        c = fmt[i + 1]
        out.append({
            "d": f"{now.day:02d}", "m": f"{now.month:02d}", "Y": f"{now.year:04d}",
            "y": f"{now.year % 100:02d}", "H": f"{now.hour:02d}", "M": f"{now.minute:02d}",
            "S": f"{now.second:02d}", "j": f"{now.timetuple().tm_yday:03d}",
            "V": f"{now.isocalendar()[1]:02d}", "%": "%",
        }[c])
        i += 2
    return "".join(out)


def format_counter(value: int, width: int) -> str:
    sign = "-" if value < 0 else ""
    return sign + str(abs(int(value))).zfill(max(0, int(width)))


def _column(table: "CsvTable | None", key: str, explicit: bool) -> int:
    if table is None:
        what = f"{{csv:{key}}}" if explicit else f"{{{key}}}"
        raise VarTextError(f"Platzhalter {what}: keine CSV-Datei gewählt "
                           "(„Variabler Text…“ › CSV-Datei)")
    idx = table.column_index(key)
    if idx is None and explicit and key.isdigit():
        n = int(key)
        if 1 <= n <= len(table.header):
            idx = n - 1
    if idx is None:
        cols = ", ".join(table.header[:8]) + (" …" if len(table.header) > 8 else "")
        raise VarTextError(f"Platzhalter {{{key}}}: keine Spalte „{key}“ in der CSV-Datei "
                           f"(Spalten: {cols})")
    return idx


def evaluate(template: str, *, value: int = 1, pad: int = 0, table: "CsvTable | None" = None,
             row: int = 1, now: _dt.datetime | None = None) -> str:
    """Evaluated text of ``template``. ``row`` is the 1-based CSV data row.

    Raises :class:`VarTextError` for unknown placeholders, a missing CSV
    file / column or a row past the end of the file.
    """
    now = now or _dt.datetime.now()

    def cell(idx: int) -> str:
        if table is None:  # pragma: no cover - _column raised already
            return ""
        if not 1 <= row <= len(table.rows):
            raise VarTextError(
                f"CSV-Zeile {row} gibt es nicht – die Datei hat {len(table.rows)} Datenzeilen "
                "(alle gelasert? In „Variabler Text…“ die Zeile zurücksetzen)")
        values = table.rows[row - 1]
        return values[idx] if idx < len(values) else ""

    def sub(m: re.Match) -> str:
        tok = m.group(0)
        if tok == "{{":
            return "{"
        if tok == "}}":
            return "}"
        name, arg = _split(m.group(1))
        if name == "n":
            if arg is None:
                return format_counter(value, pad)
            if not arg.strip().isdigit() or int(arg) > PAD_RANGE[1]:
                raise VarTextError(f"Platzhalter {tok}: Stellenzahl 0–{PAD_RANGE[1]} erwartet, "
                                   "z. B. {n:3}")
            return format_counter(value, int(arg))
        if name == "date":
            return format_datetime(DATE_DEFAULT if arg is None else arg, now)
        if name == "time":
            return format_datetime(TIME_DEFAULT if arg is None else arg, now)
        if name == "row" and arg is None:
            return str(row)
        if name == "csv":
            if not arg or not arg.strip():
                raise VarTextError("Platzhalter {csv:…}: Spaltenname oder -nummer fehlt")
            return cell(_column(table, arg.strip(), True))
        if not name:
            raise VarTextError(f"Leerer Platzhalter {tok} – für geschweifte Klammern {{{{ }}}} "
                               "schreiben")
        return cell(_column(table, m.group(1).strip(), False))

    return _TOKEN.sub(sub, template or "")


# --- CSV ----------------------------------------------------------------------

@dataclass
class CsvTable:
    header: list[str]
    rows: list[list[str]]
    delimiter: str = ","

    def column_index(self, name: str) -> int | None:
        if name in self.header:
            return self.header.index(name)
        low = name.casefold()
        for i, h in enumerate(self.header):
            if h.casefold() == low:
                return i
        return None

    def row_dict(self, row: int) -> dict[str, str]:
        if not 1 <= row <= len(self.rows):
            return {}
        values = self.rows[row - 1]
        return {h: (values[i] if i < len(values) else "") for i, h in enumerate(self.header)}


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _delimiter(text: str) -> str:
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    counts = {d: first.count(d) for d in (";", ",", "\t", "|")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else ","


def parse_csv(text: str) -> CsvTable:
    """Header + data rows; delimiter ``; , Tab |`` from the header line
    (German Excel writes ``;``). Empty lines are skipped, cells stripped of
    surrounding whitespace, missing header names become ``Spalte N``."""
    delim = _delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [[c.strip() for c in r] for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise VarTextError("CSV-Datei ist leer")
    header = [h or f"Spalte {i + 1}" for i, h in enumerate(rows[0])]
    data = rows[1:]
    if len(data) > MAX_CSV_ROWS:
        raise VarTextError(f"CSV-Datei hat mehr als {MAX_CSV_ROWS} Zeilen")
    return CsvTable(header, data, delim)


_CACHE: dict[str, tuple[int, int, CsvTable]] = {}


def load_csv(path: str) -> CsvTable:
    """Read (and cache by modification time) a CSV file; VarTextError on problems."""
    if not path:
        raise VarTextError("Keine CSV-Datei gewählt")
    try:
        st = os.stat(path)
    except OSError:
        raise VarTextError(f"CSV-Datei nicht gefunden: {path}") from None
    if st.st_size > MAX_CSV_BYTES:
        raise VarTextError(f"CSV-Datei ist größer als {MAX_CSV_BYTES // (1024 * 1024)} MB")
    key = os.path.abspath(path)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise VarTextError(f"CSV-Datei nicht lesbar: {exc}") from None
    table = parse_csv(_decode(data))
    _CACHE[key] = (st.st_mtime_ns, st.st_size, table)
    return table


# --- shapes / meta ------------------------------------------------------------

def make_meta(spec: VarTextSpec) -> dict:
    return {"kind": KIND, "version": VERSION, "spec": asdict(spec.normalized())}


def is_variable(shape: Shape) -> bool:
    g = shape.generator
    return shape.kind == "text" and isinstance(g, dict) and g.get("kind") == KIND


def spec_of(shape: Shape) -> VarTextSpec:
    """Normalized spec of a variable text shape (unknown keys ignored)."""
    meta = shape.generator or {}
    if int(meta.get("version", 0)) > VERSION:
        raise VarTextError("Variabler Text stammt aus einer neueren Version")
    names = {f.name for f in fields(VarTextSpec)}
    raw = meta.get("spec") or {}
    try:
        return VarTextSpec(**{k: v for k, v in raw.items() if k in names}).normalized()
    except (TypeError, ValueError) as exc:
        raise VarTextError(f"Parameter des variablen Texts nicht lesbar: {exc}") from exc


def series_key(shape: Shape) -> str:
    """Series id; a variable text without one is its own series."""
    try:
        return spec_of(shape).series or f"#{shape.id}"
    except VarTextError:
        return f"#{shape.id}"


def reading_order(shapes: list[Shape]) -> list[Shape]:
    """Top to bottom, then left to right (by the box centre; rows within
    half a text height count as one row)."""
    items = []
    for s in shapes:
        b = s.bounds()
        items.append((b.y + b.h / 2.0, b.x + b.w / 2.0, max(abs(s.geom.h), 1e-6), s))
    items.sort(key=lambda t: (t[0], t[1]))
    rows: list[list] = []
    for it in items:
        if rows and abs(it[0] - rows[-1][0][0]) <= 0.5 * max(it[2], rows[-1][0][2]):
            rows[-1].append(it)
        else:
            rows.append([it])
    return [it[3] for row in rows for it in sorted(row, key=lambda t: t[1])]


def advanced_spec(spec: VarTextSpec, copies: int) -> VarTextSpec:
    """Spec after a job that lasered ``copies`` copies of the series."""
    s = spec.normalized()
    k = max(1, int(copies)) if s.per_copy else 1
    row = s.csv_row + k if (s.csv_path and s.advance_row) else s.csv_row
    return replace(s, current=s.current + k * s.step, csv_row=row).normalized()


def refit_text(shape: Shape, text: str, aspect: Callable[..., float]) -> Shape:
    """Copy of ``shape`` with ``text``: same height, font, stretch and
    rotation; the width follows the text, the left edge (in the rotated
    frame, at mid height) stays where it is."""
    out = shape.copy()
    out.text = text
    g = shape.geom
    h = abs(g.h)
    if h <= 0:
        return out
    old = aspect(shape.text, shape.font_family, shape.font_bold, shape.font_italic)
    new = aspect(text, shape.font_family, shape.font_bold, shape.font_italic)
    stretch = abs(g.w) / (h * old) if old > 0 else 1.0
    w_new = h * new * stretch
    if not math.isfinite(w_new) or w_new <= 0:
        return out
    w_new = math.copysign(w_new, g.w if g.w else 1.0)
    cx, cy = g.x + g.w / 2.0, g.y + g.h / 2.0
    lx, ly = rotate_point(cx - g.w / 2.0, cy, cx, cy, g.rot)
    ncx, ncy = rotate_point(lx + w_new / 2.0, ly, lx, ly, g.rot)
    out.geom = replace(g.copy(), x=ncx - w_new / 2.0, y=ncy - g.h / 2.0, w=w_new)
    return out


@dataclass
class SeriesUse:
    """One series in a built job: the spec it was built with and its copies."""

    key: str
    spec: VarTextSpec
    ids: list[str]                      # copies in the job, reading order
    texts: list[str]

    @property
    def copies(self) -> int:
        return len(self.ids)

    def next_spec(self) -> VarTextSpec:
        return advanced_spec(self.spec, self.copies)


@dataclass
class JobUsage:
    series: list[SeriesUse] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.series)

    def summary(self) -> str:
        """Short German text, e.g. „Variabler Text: Nr. 007 … Nr. 009“."""
        parts = []
        for u in self.series:
            if not u.texts:
                continue
            first = u.texts[0].replace("\n", " ")
            last = u.texts[-1].replace("\n", " ")
            parts.append(first if len(u.texts) == 1 else f"{first} … {last}")
        return ("Variabler Text: " + "; ".join(parts)) if parts else ""


def _default_aspect():
    from lumacut_canvas.shape_paths import text_aspect
    return text_aspect


def evaluate_document(doc: Document, aspect: Callable[..., float] | None = None,
                      now: _dt.datetime | None = None) -> tuple[Document, JobUsage]:
    """Job document with evaluated variable texts, plus what was used.

    Returns ``(doc, empty usage)`` unchanged when the document has no variable
    text. Otherwise a new :class:`Document` sharing the layers and the other
    shapes; ``doc`` itself is never changed. Only shapes on visible layers
    are evaluated and counted (hidden layers are not lasered). A copy whose
    text evaluates to blanks is left out of the job. Raises
    :class:`VarTextError` (a ``ValueError``) if a template cannot be
    evaluated – the job must not be sent with literal placeholders.
    """
    visible = {l.id for l in doc.layers if l.visible}
    members: dict[str, list[Shape]] = {}
    for s in doc.shapes:
        if is_variable(s) and s.layer_id in visible:
            members.setdefault(series_key(s), []).append(s)
    if not members:
        return doc, JobUsage()
    aspect = aspect or _default_aspect()
    now = now or _dt.datetime.now()
    replaced: dict[str, Shape | None] = {}
    usage = JobUsage()
    for key, shapes in members.items():
        spec = spec_of(shapes[0])
        table = None
        if spec.csv_path or any(uses_csv(s.text) for s in shapes):
            if not spec.csv_path:
                raise VarTextError("Variabler Text nutzt CSV-Spalten, aber keine CSV-Datei ist gewählt")
            table = load_csv(spec.csv_path)
        ordered = reading_order(shapes)
        texts = []
        for i, s in enumerate(ordered):
            k = i if spec.per_copy else 0
            text = evaluate(s.text, value=spec.current + k * spec.step, pad=spec.pad,
                            table=table, row=spec.csv_row + k, now=now)
            texts.append(text)
            replaced[s.id] = refit_text(s, text, aspect) if text.strip() else None
        usage.series.append(SeriesUse(key, spec, [s.id for s in ordered], texts))
    out = Document(with_default_layer=False)
    out.layers = list(doc.layers)
    out.active_layer_id = doc.active_layer_id
    out.shapes = []
    for s in doc.shapes:
        if s.id in replaced:
            if replaced[s.id] is not None:
                out.shapes.append(replaced[s.id])
        else:
            out.shapes.append(s)
    return out, usage


def new_series() -> str:
    return new_id()


__all__ = ["CsvTable", "JobUsage", "KIND", "SeriesUse", "VarTextError", "VarTextSpec",
           "advanced_spec", "evaluate", "evaluate_document", "format_counter", "format_datetime",
           "has_placeholders", "is_variable", "load_csv", "make_meta", "new_series", "parse_csv",
           "placeholders", "reading_order", "refit_text", "series_key", "spec_of", "uses_counter",
           "uses_csv"]
