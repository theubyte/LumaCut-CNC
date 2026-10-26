"""PDF-Import (Vektorpfade) als Polylinien in Millimetern (Qt-frei).

Liest die Inhalte einer Seite mit ``pypdf`` (BSD-3-Clause) und interpretiert
die Pfad-Operatoren selbst – bewusst ohne PyMuPDF (AGPL):

* Pfadaufbau ``m l c v y h re``, Malen ``S s f F f* B B* b b*``; ``n``
  (reiner Beschneidungspfad) wird verworfen.
* Grafikzustand ``q``/``Q``/``cm`` und Formular-XObjects (``Do``, auch
  verschachtelt, mit ``/Matrix``) – Logos aus Illustrator/Inkscape/CAD liegen
  oft darin.
* Bézierkurven werden mit 0,5-mm-Schritten (wie beim SVG-Import) zerlegt.
* Seitengröße aus der CropBox (sonst MediaBox) inkl. ``/UserUnit`` und
  ``/Rotate``; PDF-Punkte (1/72 Zoll) → mm; y nach oben → Canvas y nach unten
  (Ursprung der Seite = links oben im Canvas).
* Text, eingebettete Bilder und reine weiße Füllflächen (Seitenhintergrund)
  werden gezählt und übersprungen.

Mehrseitige Dateien: ``page`` wählt die Seite (0-basiert, Standard: erste).
"""

from __future__ import annotations

import math
import os

from .vector import DEFAULT_TOLERANCE_MM, MAX_SEGMENTS_PER_CURVE, VectorImport, _finish

PT_TO_MM = 25.4 / 72.0
MAX_FORM_DEPTH = 8
MAX_OPERATIONS = 2_000_000

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(m: Matrix, n: Matrix) -> Matrix:
    """PDF-Konvention (Zeilenvektoren): erst ``m``, dann ``n``."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D,
            e * A + f * C + E, e * B + f * D + F)


def apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def _num(v) -> float:
    return float(v)


def _open(source):
    from pypdf import PdfReader
    try:
        reader = PdfReader(os.fspath(source) if isinstance(source, os.PathLike) else source)
    except Exception as exc:  # noqa: BLE001 - beschädigte Datei
        raise ValueError(f"PDF nicht lesbar: {exc}") from exc
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception:  # noqa: BLE001 - z. B. fehlende AES-Unterstützung
            ok = 0
        if not ok:
            raise ValueError("PDF ist passwortgeschützt")
    return reader


def page_count(source) -> int:
    """Anzahl Seiten (ValueError bei unlesbarer/verschlüsselter Datei)."""
    return len(_open(source).pages)


def _box(page):
    box = page.cropbox if "/CropBox" in page else page.mediabox
    x0, y0, x1, y1 = (float(v) for v in (box.left, box.bottom, box.right, box.top))
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def page_matrix(page) -> tuple[Matrix, float, float]:
    """Matrix PDF-Seitenraum → Canvas-mm (y nach unten) und Seitengröße in mm."""
    x0, y0, x1, y1 = _box(page)
    unit = float(page.get("/UserUnit", 1.0) or 1.0)
    k = PT_TO_MM * unit
    w, h = (x1 - x0) * k, (y1 - y0) * k
    # Ohne Drehung: (x, y) → ((x − x0)·k, (y1 − y)·k)
    m: Matrix = (k, 0.0, 0.0, -k, -x0 * k, y1 * k)
    rot = int(page.get("/Rotate", 0) or 0) % 360
    if rot == 90:      # im Uhrzeigersinn angezeigt
        m = mat_mul(m, (0.0, 1.0, -1.0, 0.0, h, 0.0))
        w, h = h, w
    elif rot == 180:
        m = mat_mul(m, (-1.0, 0.0, 0.0, -1.0, w, h))
    elif rot == 270:
        m = mat_mul(m, (0.0, -1.0, 1.0, 0.0, 0.0, w))
        w, h = h, w
    return m, w, h


def _bezier(p0, p1, p2, p3, n: int):
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def _bezier_steps(p0, p1, p2, p3, tol: float) -> int:
    # Kontrollpolygon ≥ Bogenlänge; 0,5-mm-Schritte wie beim SVG-Import.
    length = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
    step = 0.5 if tol >= 0.05 else max(0.05, 10 * tol)
    return int(min(MAX_SEGMENTS_PER_CURVE, max(8, math.ceil(length / step))))


HAIRLINE_MM = 0.5  # Strich-als-Fläche: Ringbreite bis hierhin gilt als eine Linie


def _area_perimeter(pts):
    a = 0.0
    per = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        a += x0 * y1 - x1 * y0
        per += math.hypot(x1 - x0, y1 - y0)
    return abs(a) / 2, per


def merge_stroke_outlines(subpaths):
    """Als Fläche gespeicherte Striche (zwei fast deckungsgleiche Ringe) → ein Ring.

    Qt, Word, manche CAD-Treiber schreiben eine Linie als schmalen gefüllten
    Ring (Außen- und Innenkante im Abstand der Strichbreite). Gelasert würde
    jede Kante doppelt. Paare mit fast gleicher Box und Ringbreite
    ≤ ``HAIRLINE_MM`` werden auf den äußeren Ring reduziert.
    Rückgabe: (Teilpfade, Anzahl entfernter Ringe).
    """
    closed = [i for i, (pts, c) in enumerate(subpaths) if c and len(pts) >= 3]
    if len(closed) < 2:
        return subpaths, 0
    info = {}
    for i in closed:
        pts = subpaths[i][0]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        info[i] = ((min(xs), min(ys), max(xs), max(ys)), *_area_perimeter(pts))
    drop: set[int] = set()
    for a in closed:
        if a in drop:
            continue
        for b in closed:
            if b <= a or b in drop:
                continue
            ba, aa, pa = info[a]
            bb, ab, pb = info[b]
            if max(abs(u - v) for u, v in zip(ba, bb)) > HAIRLINE_MM:
                continue
            per = (pa + pb) / 2
            if per <= 0 or abs(aa - ab) / per > HAIRLINE_MM:
                continue
            drop.add(b if ab <= aa else a)
            if a in drop:
                break
    return [sp for i, sp in enumerate(subpaths) if i not in drop], len(drop)


def _is_white(color) -> bool:
    return color is not None and all(c >= 0.999 for c in color)


class _Interp:
    def __init__(self, reader, result: VectorImport, tol: float) -> None:
        self.reader = reader
        self.result = result
        self.tol = tol
        self.ops = 0

    def run(self, content, resources, ctm: Matrix, depth: int = 0) -> None:
        from pypdf.generic import ContentStream
        if content is None:
            return
        stream = content if isinstance(content, ContentStream) else ContentStream(content, self.reader)
        stack: list[tuple[Matrix, object]] = []
        fill = None  # Nicht-Strich-Farbe (nur für "weiße Fläche")
        subpaths: list[tuple[list[tuple[float, float]], bool]] = []
        cur: list[tuple[float, float]] = []
        cur_closed = False
        start = None

        def flush_sub():
            nonlocal cur, cur_closed
            if len(cur) >= 2:
                subpaths.append((cur, cur_closed))
            cur, cur_closed = [], False

        def pt(x, y):
            return apply(ctm, _num(x), _num(y))

        in_text = False
        for operands, op in stream.operations:
            self.ops += 1
            if self.ops > MAX_OPERATIONS:
                raise ValueError("PDF zu komplex (zu viele Zeichenbefehle)")
            if isinstance(op, bytes):
                op = op.decode("latin-1")
            if in_text:
                if op == "ET":
                    in_text = False
                continue
            try:
                if op == "q":
                    stack.append((ctm, fill))
                elif op == "Q":
                    if stack:
                        ctm, fill = stack.pop()
                elif op == "cm":
                    ctm = mat_mul(tuple(_num(v) for v in operands), ctm)  # type: ignore[arg-type]
                elif op == "m":
                    flush_sub()
                    cur = [pt(*operands)]
                    start = cur[0]
                elif op == "l":
                    if cur:
                        cur.append(pt(*operands))
                elif op in ("c", "v", "y"):
                    if not cur:
                        continue
                    p0 = cur[-1]
                    v = [pt(operands[i], operands[i + 1]) for i in range(0, len(operands), 2)]
                    if op == "c":
                        p1, p2, p3 = v
                    elif op == "v":
                        p1, (p2, p3) = p0, v
                    else:
                        (p1, p3) = v
                        p2 = p3
                    cur.extend(_bezier(p0, p1, p2, p3, _bezier_steps(p0, p1, p2, p3, self.tol)))
                elif op == "h":
                    if cur:
                        cur_closed = True
                        flush_sub()
                        if start is not None:
                            cur = [start]
                elif op == "re":
                    flush_sub()
                    x, y, w, h = (_num(v) for v in operands)
                    cur = [pt(x, y), pt(x + w, y), pt(x + w, y + h), pt(x, y + h)]
                    cur_closed = True
                    flush_sub()
                    start = None
                elif op in ("S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"):
                    if op in ("s", "b", "b*") and cur:
                        cur_closed = True
                    flush_sub()
                    if op == "n":
                        pass  # Beschneidungspfad, nicht gelasert
                    elif op in ("f", "F", "f*") and _is_white(fill):
                        self.result.skip("weiße Fläche")
                    else:
                        if op != "S":
                            subpaths, merged = merge_stroke_outlines(
                                [(pts, closed or True) for pts, closed in subpaths])
                            for _ in range(merged):
                                self.result.skip("doppelte Strichkante")
                        for pts, closed in subpaths:
                            # Gefüllte Flächen sind immer geschlossen.
                            _finish(pts, closed or op not in ("S",), self.result)
                    subpaths, cur, start = [], [], None
                elif op == "g":
                    fill = (_num(operands[0]),) * 3
                elif op == "rg":
                    fill = tuple(_num(v) for v in operands[:3])
                elif op == "k":
                    c, mg, yy, kk = (_num(v) for v in operands[:4])
                    fill = ((1 - c) * (1 - kk), (1 - mg) * (1 - kk), (1 - yy) * (1 - kk))
                elif op in ("sc", "scn", "cs"):
                    fill = None  # unbekannter Farbraum: nicht als weiß werten
                elif op == "BT":
                    in_text = True
                    self.result.skip("Text")
                elif op == "INLINE IMAGE" or op == "BI":
                    self.result.skip("eingebettetes Bild")
                elif op == "Do":
                    self._xobject(operands[0], resources, ctm, depth)
            except (TypeError, ValueError, IndexError) as exc:
                if isinstance(exc, ValueError) and "zu komplex" in str(exc):
                    raise
                self.result.skip(f"fehlerhafter Befehl {op}")

    def _xobject(self, name, resources, ctm: Matrix, depth: int) -> None:
        try:
            xobjs = resources["/XObject"].get_object() if resources and "/XObject" in resources else None
            xo = xobjs[name].get_object() if xobjs and name in xobjs else None
        except Exception:  # noqa: BLE001
            xo = None
        if xo is None:
            return
        sub = xo.get("/Subtype")
        if sub == "/Image":
            self.result.skip("eingebettetes Bild")
            return
        if sub != "/Form" or depth >= MAX_FORM_DEPTH:
            return
        m = xo.get("/Matrix")
        fm = tuple(float(v) for v in m) if m else IDENTITY
        res = xo.get("/Resources")
        res = res.get_object() if res is not None else resources
        self.run(xo, res, mat_mul(fm, ctm), depth + 1)  # type: ignore[arg-type]


def load_pdf(source, page: int = 0, tolerance_mm: float = DEFAULT_TOLERANCE_MM) -> VectorImport:
    """Eine PDF-Seite → Polylinien in Canvas-mm (Seitenursprung links oben)."""
    reader = _open(source)
    n = len(reader.pages)
    if n == 0:
        raise ValueError("PDF enthält keine Seiten")
    if not 0 <= page < n:
        raise ValueError(f"Seite {page + 1} gibt es nicht (PDF hat {n} Seite(n))")
    pg = reader.pages[page]
    m, _w, _h = page_matrix(pg)
    result = VectorImport()
    res = pg.get("/Resources")
    res = res.get_object() if res is not None else None
    interp = _Interp(reader, result, tolerance_mm)
    interp.run(pg.get_contents(), res, m)
    if not result.polylines:
        hint = ""
        if result.skipped.get("Text") or result.skipped.get("eingebettetes Bild"):
            hint = " (nur Text/Bilder – Text bitte in Pfade umwandeln, Bilder als PNG importieren)"
        raise ValueError("Seite enthält keine Vektorpfade" + hint)
    return result
