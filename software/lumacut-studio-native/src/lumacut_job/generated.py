"""Re-editable generated objects (QR code, barcode, Data Matrix, Aztec, PDF417,
arc text).

The generators create static ``polygon`` groups. To make them editable like in
LightBurn / xTool Creative Space, every part of such a group carries the same
``Shape.generator`` dict::

    {"kind": "qr", "version": 1, "spec": {...}, "box": [w, h]}

``spec`` holds the generator parameters (without the position), ``box`` the
unrotated size of the group when it was generated. When the user later double
clicks the object (or uses „Code bearbeiten…“), :func:`find_unit` collects the
group, :func:`unit_frame` measures where it is now (centre, rotation, scaling
by the user), the dialog opens with the scaled parameters, and the new group
is placed at the same centre with the same rotation (see ``generated_qt``).

The generator group is the *innermost* group of its parts (``groups[-1]``):
grouping it with other objects prepends an outer group, copy/paste and arrays
remap all group ids consistently, ungrouping removes the generator group (the
parts are then plain polygons again).

Pure Python, no Qt.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields, replace

from lumacut_canvas.model import Geometry, keep_inside_together, rotate_point

from .arctext import ArcSpec
from .aztec import AztecSpec
from .barcode import BarcodeSpec
from .datamatrix import DataMatrixSpec
from .pdf417 import Pdf417Spec
from .qr import QrSpec

VERSION = 1
SPECS = {"qr": QrSpec, "barcode": BarcodeSpec, "datamatrix": DataMatrixSpec, "aztec": AztecSpec,
         "pdf417": Pdf417Spec, "arctext": ArcSpec}
LABELS = {"qr": "QR-Code", "barcode": "Barcode", "datamatrix": "Data Matrix", "aztec": "Aztec-Code",
          "pdf417": "PDF417-Code", "arctext": "Bogentext"}
_POSITION = ("x", "y")
# Below this relative change the user did not scale the object (rounding of moves etc.).
SCALE_EPS = 0.002


def spec_kind(spec) -> str:
    for kind, cls in SPECS.items():
        if isinstance(spec, cls):
            return kind
    raise TypeError(f"Kein Erzeuger für {type(spec).__name__}")


def extent(shapes) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of the unrotated boxes of ``shapes``."""
    xs, ys = [], []
    for sh in shapes:
        b = sh.geom.bounds()
        xs += [b.x, b.x + b.w]
        ys += [b.y, b.y + b.h]
    return min(xs), min(ys), max(xs), max(ys)


def make_meta(spec, shapes) -> dict:
    """Generator dict for freshly generated (unrotated) ``shapes``."""
    kind = spec_kind(spec)
    d = {k: v for k, v in asdict(spec.normalized()).items() if k not in _POSITION}
    x0, y0, x1, y1 = extent(shapes)
    return {"kind": kind, "version": VERSION, "spec": d,
            "box": [round(x1 - x0, 6), round(y1 - y0, 6)]}


def tag(shapes, spec) -> list:
    """Attach the same generator dict to every part; returns ``shapes``."""
    if shapes:
        meta = make_meta(spec, shapes)
        for sh in shapes:
            sh.generator = meta
    return shapes


def spec_from_meta(meta: dict):
    """Normalized spec object from a generator dict; ``ValueError`` if unusable."""
    if not isinstance(meta, dict) or meta.get("kind") not in SPECS:
        raise ValueError("Unbekanntes erzeugtes Objekt")
    if int(meta.get("version", 0)) > VERSION:
        raise ValueError("Objekt stammt aus einer neueren Version")
    cls = SPECS[meta["kind"]]
    names = {f.name for f in fields(cls)} - set(_POSITION)
    raw = meta.get("spec") or {}
    try:
        return cls(**{k: v for k, v in raw.items() if k in names}).normalized()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Parameter nicht lesbar: {exc}") from exc


@dataclass
class Unit:
    """A generated group in the document, as it is now."""

    kind: str
    group: str
    ids: list[str]
    meta: dict
    layer_id: str
    outer: tuple[str, ...]        # enclosing groups (outermost first), kept on re-generation
    center: tuple[float, float]
    rot: float
    size: tuple[float, float]     # unrotated size now
    scale: tuple[float, float]    # size now / size when generated

    @property
    def label(self) -> str:
        return LABELS.get(self.kind, "Objekt")

    @property
    def scaled(self) -> bool:
        return any(abs(s - 1.0) > SCALE_EPS for s in self.scale)


def find_unit(doc, shape_id: str) -> Unit | None:
    """The generated group containing ``shape_id``.

    ``None`` if the shape is not part of a generated group (plain object, or
    the group was dissolved). ``ValueError`` if the group was changed so that
    re-generating would lose work (parts from different generators or with
    their own rotation).
    """
    if not doc.has_shape(shape_id):
        return None
    sh = doc.shape(shape_id)
    meta = sh.generator
    if not meta or not sh.groups:
        return None
    if meta.get("kind") == "vartext":   # variable text (lumacut_job.vartext) is a plain text object
        return None
    group = sh.groups[-1]
    parts = [s for s in doc.shapes if s.groups and s.groups[-1] == group]
    label = LABELS.get(meta.get("kind"), "Objekt")
    if any(s.generator != meta for s in parts):
        raise ValueError(f"{label} wurde mit anderen Objekten kombiniert – "
                         "Gruppierung prüfen oder neu einfügen")
    rot = parts[0].geom.rot
    if any(abs(_angle_diff(s.geom.rot, rot)) > 0.01 for s in parts):
        raise ValueError(f"Teile des {label}s sind einzeln gedreht – nicht mehr bearbeitbar")
    if len({s.layer_id for s in parts}) != 1:
        raise ValueError(f"Teile des {label}s liegen auf verschiedenen Ebenen – "
                         "erst auf eine Ebene legen")
    center, size = unit_frame(parts, rot)
    box = meta.get("box") or size
    scale = tuple(n / o if o > 1e-9 else 1.0 for n, o in zip(size, box))
    return Unit(kind=meta["kind"], group=group, ids=[s.id for s in parts], meta=meta,
                layer_id=parts[0].layer_id, outer=tuple(parts[0].groups[:-1]), center=center,
                rot=rot, size=size, scale=scale)  # type: ignore[arg-type]


def _angle_diff(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def unit_frame(parts, rot: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """(centre, (w, h)) of ``parts`` in their common frame rotated by ``rot``."""
    pts = [rotate_point(px, py, 0.0, 0.0, -rot) for s in parts for px, py in s.geom.corner_points()]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    return rotate_point(cx, cy, 0.0, 0.0, rot), (max(xs) - min(xs), max(ys) - min(ys))


def _r(v: float) -> float:
    return round(v, 2)


def scaled_spec(spec, scale: tuple[float, float]):
    """Spec that reproduces a group the user resized by ``scale`` (sx, sy).

    QR / Data Matrix / Aztec / arc text are scaled uniformly (mean of both factors),
    the barcode keeps its proportions per axis: module width with X, bar and
    text height with Y; PDF417 takes its width from X and the row height
    (in module widths) from the ratio Y / X. Unscaled specs are returned unchanged.
    """
    sx, sy = scale
    if abs(sx - 1.0) <= SCALE_EPS and abs(sy - 1.0) <= SCALE_EPS:
        return spec
    k = math.sqrt(max(sx, 1e-9) * max(sy, 1e-9))
    if isinstance(spec, (QrSpec, DataMatrixSpec, AztecSpec)):
        return replace(spec, size_mm=_r(spec.size_mm * k)).normalized()
    if isinstance(spec, Pdf417Spec):
        return replace(spec, width_mm=_r(spec.width_mm * sx),
                       row_height=round(spec.row_height * sy / max(sx, 1e-9), 2)).normalized()
    if isinstance(spec, BarcodeSpec):
        return replace(spec, module_mm=round(spec.module_mm * sx, 3),
                       height_mm=_r(spec.height_mm * sy),
                       text_mm=_r(spec.text_mm * sy)).normalized()
    if isinstance(spec, ArcSpec):
        return replace(spec, radius_mm=_r(spec.radius_mm * k), height_mm=_r(spec.height_mm * k),
                       spacing_mm=_r(spec.spacing_mm * k)).normalized()
    return spec


def place(shapes, center: tuple[float, float], rot: float) -> None:
    """Move freshly generated (unrotated) ``shapes`` so that their centre is
    ``center``, rotate them by ``rot`` about it and keep them inside the work
    area together. Changes the shapes' geometry in place."""
    x0, y0, x1, y1 = extent(shapes)
    dx, dy = center[0] - (x0 + x1) / 2.0, center[1] - (y0 + y1) / 2.0
    geoms: dict[str, Geometry] = {}
    for sh in shapes:
        g = sh.geom.translated(dx, dy)
        if rot:
            g = g.rotated(rot, center[0], center[1])
        geoms[sh.id] = g
    geoms = keep_inside_together(geoms)
    for sh in shapes:
        sh.geom = geoms[sh.id]


__all__ = ["LABELS", "SPECS", "Unit", "VERSION", "extent", "find_unit", "make_meta", "place",
           "scaled_spec", "spec_from_meta", "spec_kind", "tag", "unit_frame"]
