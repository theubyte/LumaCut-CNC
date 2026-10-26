"""Importierte Geometrie als Canvas-Objekte anlegen und platzieren.

Regeln (für Vektor und Bild gleich):

* passt die Datei in ihrer Lage in die Arbeitsfläche, bleibt sie dort
  (SVG-Export aus LumaCut kommt so deckungsgleich zurück);
* sonst wird sie an den Ursprung (links oben) bzw. auf den Ablagepunkt
  (Drag & Drop) gesetzt;
* ist sie größer als 360 × 340 mm, wird sie proportional verkleinert –
  alles gemeinsam, damit die Anordnung erhalten bleibt.

Mehrteilige Vektor-Importe werden zu einer Gruppe zusammengefasst.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lumacut_canvas.model import Geometry, Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

VECTOR_SUFFIXES = (".svg", ".dxf")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")
ALL_SUFFIXES = VECTOR_SUFFIXES + IMAGE_SUFFIXES
MAX_OBJECTS = 20000


@dataclass
class ImportResult:
    shapes: list[Shape] = field(default_factory=list)
    scale: float = 1.0                 # < 1: verkleinert, damit es passt
    notes: list[str] = field(default_factory=list)
    kind: str = "vector"               # "vector" | "image"

    def summary(self, name: str) -> str:
        what = ("Bild" if self.kind == "image" else
                f"{len(self.shapes)} Objekt(e)")
        text = f"Importiert: {name} · {what}"
        if self.scale < 0.9999:
            text += f" · auf {self.scale * 100:.0f} % verkleinert (Arbeitsfläche)"
        if self.notes:
            text += " · " + ", ".join(self.notes)
        return text


def _bbox(polys) -> tuple[float, float, float, float]:
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def placement(x0: float, y0: float, w: float, h: float,
              drop: tuple[float, float] | None = None) -> tuple[float, float, float, float]:
    """(Skalierung, dx, dy, s) für Box (x0, y0, w, h): neue Lage = alt*s + d."""
    s = min(1.0, WORK_WIDTH_MM / w if w > 0 else 1.0, WORK_HEIGHT_MM / h if h > 0 else 1.0)
    nw, nh = w * s, h * s
    if drop is not None:
        nx, ny = drop[0] - nw / 2, drop[1] - nh / 2
    elif s == 1.0 and x0 >= 0 and y0 >= 0 and x0 + w <= WORK_WIDTH_MM and y0 + h <= WORK_HEIGHT_MM:
        nx, ny = x0, y0
    else:
        nx, ny = 0.0, 0.0
    nx = min(max(nx, 0.0), WORK_WIDTH_MM - nw)
    ny = min(max(ny, 0.0), WORK_HEIGHT_MM - nh)
    return s, nx - x0 * s, ny - y0 * s, s


def vector_shapes(polylines, layer_id: str, drop=None) -> ImportResult:
    """Polylinien (mm) → polygon/path-Objekte, gemeinsam platziert."""
    polys = [pl for pl in polylines if len(pl.points) >= 2]
    if not polys:
        raise ValueError("Datei enthält keine importierbaren Konturen")
    if len(polys) > MAX_OBJECTS:
        raise ValueError(f"Zu viele Konturen ({len(polys)} > {MAX_OBJECTS})")
    x0, y0, x1, y1 = _bbox([pl.points for pl in polys])
    s, dx, dy, _ = placement(x0, y0, x1 - x0, y1 - y0, drop)
    gid = new_id() if len(polys) > 1 else None
    shapes = []
    for pl in polys:
        pts = [(x * s + dx, y * s + dy) for x, y in pl.points]
        kind = "polygon" if pl.closed and len(pts) >= 3 else "path"
        sh = Shape.from_points(kind, pts, layer_id)
        if gid:
            sh.groups = (gid,)
        shapes.append(sh)
    return ImportResult(shapes, s)


def image_shape(image, w_mm: float, h_mm: float, layer_id: str, drop=None) -> ImportResult:
    s, dx, dy, _ = placement(0.0, 0.0, w_mm, h_mm, drop)
    if drop is None:
        dx, dy = 0.0, 0.0  # Bilder ohne Ablagepunkt links oben
    shape = Shape("image", Geometry(dx, dy, w_mm * s, h_mm * s), layer_id, image=image)
    return ImportResult([shape], s, kind="image")


def import_file(path, layer_id: str, drop: tuple[float, float] | None = None) -> ImportResult:
    """Datei nach Endung importieren; ValueError mit deutscher Meldung."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".svg":
        from .vector import load_svg
        try:
            vi = load_svg(p)
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - Parserfehler verständlich melden
            raise ValueError(f"SVG nicht lesbar: {exc}") from exc
        res = vector_shapes(vi.polylines, layer_id, drop)
        res.notes = vi.notes()
        return res
    if suffix == ".dxf":
        from .vector import load_dxf
        try:
            vi = load_dxf(p)
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"DXF nicht lesbar: {exc}") from exc
        res = vector_shapes(vi.polylines, layer_id, drop)
        res.notes = vi.notes()
        return res
    if suffix in IMAGE_SUFFIXES:
        from .image import load_image
        img, w, h = load_image(p)
        return image_shape(img, w, h, layer_id, drop)
    raise ValueError(f"Dateityp {suffix or '?'} wird nicht unterstützt "
                     f"(SVG, DXF, PNG, JPG, BMP)")
