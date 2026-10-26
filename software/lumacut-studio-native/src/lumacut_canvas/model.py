"""Qt-freies Dokumentmodell: Ebenen (= Laser-Einstellungen) und Vektorobjekte.

Grundidee: **Eine Ebene entspricht genau einer Laser-Einstellung.**
Objekte speichern nur ihre Geometrie und die Ebene, zu der sie gehören;
Farbe, Leistung, Geschwindigkeit und Durchgänge erben sie von der Ebene.
So ist für den Nutzer jederzeit eindeutig, mit welchen Parametern ein
Objekt gelasert wird.

Alle Koordinaten sind Arbeitsflächen-mm (siehe :mod:`workarea`).
Änderungen sollen über :mod:`commands` laufen (Undo/Redo); das Modell
benachrichtigt registrierte Listener nach jeder Änderung.
"""

from __future__ import annotations

import base64
import math
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Callable, Iterable

from . import hatch as _hatch
from .material import DEPTH_PER_PASS_RANGE, THICKNESS_RANGE
from .workarea import Rect, clamp_offset, fit_scale, is_inside_work_area

# Gültige Parameterbereiche, abgestimmt mit software/lumacut-studio (studio.js).
POWER_RANGE = (1.0, 100.0)          # Prozent
SPEED_RANGE = (1.0, 6000.0)         # mm/min (Marlin-Vorschub F)
PASSES_RANGE = (1, 30)
# Fokus-Absenkung je Durchgang in mm (Z fährt nach jedem Durchgang um diesen
# Wert tiefer, z. B. für Mehrfach-Schnitte in dickem Material). Die Summe
# über alle Durchgänge ist durch MAX_FOCUS_DROP_MM begrenzt: Der Pi fokussiert
# auf Oberfläche + 5,5 mm und sperrt Z unter Oberfläche + 2 mm.
Z_STEP_RANGE = (0.0, 2.0)
MAX_FOCUS_DROP_MM = 3.0
# Material-Felder der Ebene (material.py); nur gespeichert, wenn gesetzt.
MATERIAL_LAYER_FIELDS = ("material", "thickness_mm", "target_depth_mm", "depth_per_pass_mm")
# Schnitt-Optionen der Ebene (lumacut_job.cutpath): Kerf-Versatz, Haltestege
# und An-/Abfahrt. Nur gespeichert, wenn gesetzt (≠ Standard),
# damit Dateien ohne diese Optionen byte-gleich bleiben.
KERF_RANGE = (-2.0, 2.0)            # mm, + = zur Abfallseite (Teile größer, Löcher kleiner)
TAB_COUNT_RANGE = (0, 24)
TAB_WIDTH_RANGE = (0.0, 10.0)       # mm
TAB_SPACING_RANGE = (0.0, 500.0)    # mm, 0 = feste Anzahl
LEAD_RANGE = (0.0, 10.0)            # mm
CUT_LAYER_DEFAULTS = {
    "kerf_mm": 0.0, "tab_count": 0, "tab_width_mm": 1.0, "tab_spacing_mm": 0.0,
    "lead_in_mm": 0.0, "lead_in_arc": False, "lead_out_mm": 0.0,
}
CUT_LAYER_FIELDS = tuple(CUT_LAYER_DEFAULTS)
# Vektor-Füllung je Ebene (hatch.py); nur gespeichert, wenn vom Standard abweichend.
FILL_LAYER_DEFAULTS = {"fill_mode": "none", "line_interval_mm": _hatch.DEFAULT_INTERVAL_MM,
                       "hatch_angle": 0.0, "hatch_bidirectional": True, "hatch_outline": True}
FILL_LAYER_FIELDS = tuple(FILL_LAYER_DEFAULTS)
# Geschlossene Objektarten, die gefüllt werden (Linie/Freihand/Bild nicht).
FILLABLE_KINDS = ("rect", "ellipse", "polygon", "text")

SHAPE_KINDS = ("rect", "ellipse", "line", "text", "polygon", "path", "image")
# Objekte mit Stützpunkten: "polygon" geschlossen, "path" (Freihand) offen.
POINT_KINDS = {"polygon": 3, "path": 2}  # Art -> Mindestanzahl Punkte

# Bildmodi: Rastermodi der Engine (lumacut_job.raster) plus 3D-Tiefe
# (sliced depth). Leistung/Geschwindigkeit eines Bildes kommen aus seinen
# Bildeinstellungen, nicht aus der Ebene (wie bei LightBurn "Image"-Ebenen).
IMAGE_MODES = ("threshold", "floyd", "atkinson", "ordered", "grayscale", "depth3d")


@dataclass(frozen=True)
class ImageSettings:
    """Gravur-Einstellungen eines Bildobjekts (unveränderlich, Undo-sicher)."""

    mode: str = "floyd"
    line_interval_mm: float = 0.1     # 254 DPI
    power: float = 60.0               # % bei Schwarz
    min_power: float = 0.0            # % bei Weiß (nur Graustufen)
    speed_mm_min: float = 3000.0
    passes: int = 1
    threshold: int = 128
    bidirectional: bool = True
    overscan_mm: float = 3.0
    negative: bool = False
    depth_levels: int = 8             # nur 3D-Tiefe
    z_step_mm: float = 0.0            # nur 3D-Tiefe: Fokus je Stufe tiefer

    def normalized(self) -> "ImageSettings":
        return ImageSettings(
            mode=self.mode if self.mode in IMAGE_MODES else "floyd",
            line_interval_mm=_clamp(float(self.line_interval_mm), 0.03, 2.0),
            power=_clamp(float(self.power), *POWER_RANGE),
            min_power=_clamp(float(self.min_power), 0.0, _clamp(float(self.power), *POWER_RANGE)),
            speed_mm_min=_clamp(float(self.speed_mm_min), *SPEED_RANGE),
            passes=int(_clamp(int(self.passes), *PASSES_RANGE)),
            threshold=int(_clamp(int(self.threshold), 0, 255)),
            bidirectional=bool(self.bidirectional),
            overscan_mm=_clamp(float(self.overscan_mm), 0.0, 20.0),
            negative=bool(self.negative),
            depth_levels=int(_clamp(int(self.depth_levels), 2, 64)),
            z_step_mm=_clamp(float(self.z_step_mm), 0.0, 2.0))

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ImageSettings":
        names = {f.name for f in fields(ImageSettings)}
        return ImageSettings(**{k: v for k, v in (d or {}).items() if k in names}).normalized()


@dataclass(frozen=True)
class RasterImage:
    """Eingebettete Bitmap eines Bildobjekts: 8-bit-Graustufen-PNG.

    Transparenz wird beim Import auf Weiß gelegt (Weiß = nicht lasern).
    """

    png: bytes
    px_width: int
    px_height: int
    settings: ImageSettings = field(default_factory=ImageSettings)

    def dpi(self, width_mm: float) -> float:
        """Effektive Auflösung bei der aktuellen Objektbreite."""
        return self.px_width / (abs(width_mm) / 25.4) if width_mm else 0.0

    def to_dict(self) -> dict:
        return {"png": base64.b64encode(self.png).decode("ascii"),
                "px": [self.px_width, self.px_height],
                "settings": self.settings.to_dict()}

    @staticmethod
    def from_dict(d: dict) -> "RasterImage":
        png = base64.b64decode(str(d["png"]))
        if not png.startswith(b"\x89PNG"):
            raise ValueError("Bilddaten sind kein PNG")
        w, h = (int(v) for v in d.get("px", (0, 0)))
        if w <= 0 or h <= 0:
            raise ValueError("Bildgröße fehlt")
        return RasterImage(png, w, h, ImageSettings.from_dict(d.get("settings", {})))


# Vorgabefarben für neue Ebenen, gut unterscheidbar auf dunklem Grund.
LAYER_COLORS = ("#4cd4b0", "#f3a64b", "#6fa8ff", "#f36b73", "#c08cff",
                "#e8e36a", "#5fd3f3", "#ff8fc7")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class Layer:
    """Eine Ebene mit eigener Laser-Einstellung."""

    name: str
    color: str = LAYER_COLORS[0]
    power: float = 50.0             # %
    speed: float = 1500.0           # mm/min
    passes: int = 1
    visible: bool = True
    locked: bool = False
    id: str = field(default_factory=new_id)
    z_step: float = 0.0             # mm Fokus-Absenkung je Durchgang (0 = aus)
    # Material-Grundlage (siehe material.py); alle optional, 0/"" = aus.
    material: str = ""              # Materialname (frei, z. B. aus BUILTIN_MATERIALS)
    thickness_mm: float = 0.0       # Materialdicke
    target_depth_mm: float = 0.0    # Zieltiefe; 0 = Materialdicke (Durchschnitt)
    depth_per_pass_mm: float = 0.0  # Tiefe je Durchgang; 0 = keine Tiefenplanung
    # Schnitt-Optionen (siehe CUT_LAYER_DEFAULTS / lumacut_job.cutpath)
    kerf_mm: float = 0.0            # Versatz geschlossener Konturen
    tab_count: int = 0              # Haltestege je geschlossener Kontur (0 = aus)
    tab_width_mm: float = 1.0       # Breite eines Haltestegs
    tab_spacing_mm: float = 0.0     # > 0: ein Steg je … mm Umfang statt fester Anzahl
    lead_in_mm: float = 0.0         # Anfahrt (Abfallseite), 0 = aus
    lead_in_arc: bool = False       # Anfahrt als Viertelkreis statt Gerade
    lead_out_mm: float = 0.0        # Abfahrt, 0 = aus
    # Vektor-Füllung (siehe hatch.py / FILL_LAYER_DEFAULTS)
    fill_mode: str = "none"          # "none" | "hatch" | "crosshatch"
    line_interval_mm: float = _hatch.DEFAULT_INTERVAL_MM  # Linienabstand
    hatch_angle: float = 0.0         # Grad, [0, 180); Kreuzschraffur zusätzlich +90°
    hatch_bidirectional: bool = True  # jede zweite Linie rückwärts (kürzere Leerfahrten)
    hatch_outline: bool = True       # Kontur zusätzlich zur Füllung lasern

    def normalized(self) -> "Layer":
        """Kopie mit Parametern im gültigen Bereich."""
        return replace(
            self,
            power=_clamp(float(self.power), *POWER_RANGE),
            speed=_clamp(float(self.speed), *SPEED_RANGE),
            passes=int(_clamp(int(self.passes), *PASSES_RANGE)),
            z_step=round(_clamp(float(self.z_step), *Z_STEP_RANGE), 3),
            material=str(self.material or "").strip()[:80],
            thickness_mm=round(_clamp(float(self.thickness_mm), *THICKNESS_RANGE), 3),
            target_depth_mm=round(_clamp(float(self.target_depth_mm), *THICKNESS_RANGE), 3),
            depth_per_pass_mm=round(_clamp(float(self.depth_per_pass_mm),
                                           *DEPTH_PER_PASS_RANGE), 3),
            kerf_mm=round(_clamp(float(self.kerf_mm), *KERF_RANGE), 3),
            tab_count=int(_clamp(int(self.tab_count), *TAB_COUNT_RANGE)),
            tab_width_mm=round(_clamp(float(self.tab_width_mm), *TAB_WIDTH_RANGE), 3),
            tab_spacing_mm=round(_clamp(float(self.tab_spacing_mm), *TAB_SPACING_RANGE), 3),
            lead_in_mm=round(_clamp(float(self.lead_in_mm), *LEAD_RANGE), 3),
            lead_in_arc=bool(self.lead_in_arc),
            lead_out_mm=round(_clamp(float(self.lead_out_mm), *LEAD_RANGE), 3),
            fill_mode=self.fill_mode if self.fill_mode in _hatch.FILL_MODES else "none",
            line_interval_mm=round(_clamp(float(self.line_interval_mm), *_hatch.INTERVAL_RANGE), 3),
            hatch_angle=_hatch.normalize_angle_180(self.hatch_angle),
            hatch_bidirectional=bool(self.hatch_bidirectional),
            hatch_outline=bool(self.hatch_outline),
        )

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color,
                "power": self.power, "speed": self.speed, "passes": self.passes,
                "visible": self.visible, "locked": self.locked, "z_step": self.z_step,
                **{k: getattr(self, k) for k in MATERIAL_LAYER_FIELDS if getattr(self, k)},
                **{k: getattr(self, k) for k, v in CUT_LAYER_DEFAULTS.items()
                   if getattr(self, k) != v},
                **{k: getattr(self, k) for k, v in FILL_LAYER_DEFAULTS.items()
                   if getattr(self, k) != v}}

    @staticmethod
    def from_dict(d: dict) -> "Layer":
        return Layer(
            id=str(d.get("id") or new_id()), name=str(d.get("name", "Ebene")),
            color=str(d.get("color", LAYER_COLORS[0])),
            power=float(d.get("power", 50.0)), speed=float(d.get("speed", 1500.0)),
            passes=int(d.get("passes", 1)), visible=bool(d.get("visible", True)),
            locked=bool(d.get("locked", False)), z_step=float(d.get("z_step", 0.0)),
            material=str(d.get("material", "")),
            thickness_mm=float(d.get("thickness_mm", 0.0)),
            target_depth_mm=float(d.get("target_depth_mm", 0.0)),
            depth_per_pass_mm=float(d.get("depth_per_pass_mm", 0.0)),
            **{k: type(v)(d[k]) for k, v in CUT_LAYER_DEFAULTS.items() if k in d},
            **{k: type(v)(d[k]) for k, v in FILL_LAYER_DEFAULTS.items() if k in d},
        ).normalized()


def normalize_angle(deg: float) -> float:
    """Winkel auf (-180, 180] Grad bringen (0 bleibt exakt 0)."""
    a = math.fmod(float(deg), 360.0)
    if a <= -180.0:
        a += 360.0
    elif a > 180.0:
        a -= 360.0
    return 0.0 if abs(a) < 1e-9 else a


def rotate_point(px: float, py: float, cx: float, cy: float, deg: float) -> tuple[float, float]:
    """Punkt um (cx, cy) drehen; positive Grad = im Uhrzeigersinn auf dem
    Bildschirm (Y nach unten), identisch zu ``QTransform.rotate``."""
    if deg == 0:
        return px, py
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    dx, dy = px - cx, py - cy
    # Auf 1 nm runden, damit 90°-Drehungen keine -1e-15-Ränder erzeugen.
    return round(cx + dx * c - dy * s, 9), round(cy + dx * s + dy * c, 9)


@dataclass
class Geometry:
    """Geometrie als zwei Punkte p1=(x, y) und p2=(x+w, y+h) plus Drehung.

    Für Rechteck, Ellipse und Text ist das die Box (w, h > 0).
    Für Linien sind w/h vorzeichenbehaftet (Linie von p1 nach p2).
    ``rot`` dreht das Objekt in Grad um die Boxmitte (im Uhrzeigersinn).
    Diese einheitliche Darstellung erlaubt es, Verschieben, Skalieren und
    Drehen für alle Formen gleich zu behandeln.
    """

    x: float
    y: float
    w: float
    h: float
    rot: float = 0.0

    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2

    def local_bounds(self) -> Rect:
        """Box ohne Drehung."""
        return Rect.from_points(self.x, self.y, self.x + self.w, self.y + self.h)

    def corner_points(self) -> list[tuple[float, float]]:
        """Eckpunkte (Linie: Endpunkte) nach der Drehung."""
        cx, cy = self.center()
        if self.w == 0 or self.h == 0:
            pts = [(self.x, self.y), (self.x + self.w, self.y + self.h)]
        else:
            pts = [(self.x, self.y), (self.x + self.w, self.y),
                   (self.x + self.w, self.y + self.h), (self.x, self.y + self.h)]
        return [rotate_point(px, py, cx, cy, self.rot) for px, py in pts]

    def bounds(self) -> Rect:
        """Achsparallele Hüllbox (bei Drehung die der gedrehten Box)."""
        if self.rot == 0:
            return self.local_bounds()
        pts = self.corner_points()
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return Rect.from_points(min(xs), min(ys), max(xs), max(ys))

    def translated(self, dx: float, dy: float) -> "Geometry":
        return Geometry(self.x + dx, self.y + dy, self.w, self.h, self.rot)

    def with_center(self, cx: float, cy: float) -> "Geometry":
        return Geometry(cx - self.w / 2, cy - self.h / 2, self.w, self.h, self.rot)

    def rotated(self, delta_deg: float, cx: float, cy: float) -> "Geometry":
        """Um den Punkt (cx, cy) drehen (z. B. Mitte einer Mehrfachauswahl)."""
        ncx, ncy = rotate_point(*self.center(), cx, cy, delta_deg)
        g = self.with_center(ncx, ncy)
        g.rot = normalize_angle(self.rot + delta_deg)
        return g

    def mapped(self, old: Rect, new: Rect) -> "Geometry":
        """Bildet die Geometrie von Box ``old`` auf Box ``new`` ab.

        Ungedreht exakt affin. Gedrehte Objekte bleiben formtreu (keine
        Scherung): ihre Mitte wird affin abgebildet und Breite/Höhe werden mit
        dem in Objektrichtung wirkenden Faktor skaliert. Bei gleichmäßiger
        Skalierung (Umschalt) ist das exakt.
        """
        sx = new.w / old.w if old.w > 0 else 1.0
        sy = new.h / old.h if old.h > 0 else 1.0
        if self.rot == 0:
            x1 = new.x + (self.x - old.x) * sx
            y1 = new.y + (self.y - old.y) * sy
            x2 = new.x + (self.x + self.w - old.x) * sx
            y2 = new.y + (self.y + self.h - old.y) * sy
            return Geometry(x1, y1, x2 - x1, y2 - y1)
        cx, cy = self.center()
        ncx = new.x + (cx - old.x) * sx
        ncy = new.y + (cy - old.y) * sy
        r = math.radians(self.rot)
        c, s = abs(math.cos(r)), abs(math.sin(r))
        fw = math.hypot(sx * c, sy * s)
        fh = math.hypot(sx * s, sy * c)
        g = Geometry(0, 0, self.w * fw, self.h * fh, self.rot)
        return g.with_center(ncx, ncy)

    def copy(self) -> "Geometry":
        return Geometry(self.x, self.y, self.w, self.h, self.rot)

    def as_tuple(self) -> tuple[float, float, float, float]:
        """Box (x, y, w, h) ohne Drehung."""
        return (self.x, self.y, self.w, self.h)


@dataclass
class Shape:
    """Ein Vektorobjekt. Farbe und Laserparameter kommen von der Ebene."""

    kind: str
    geom: Geometry
    layer_id: str
    text: str = ""
    font_family: str = "Segoe UI"
    id: str = field(default_factory=new_id)
    # Gruppenzugehörigkeit, äußerste Gruppe zuerst (verschachtelte Gruppen).
    # Gruppen sind reine Zugehörigkeit; Objekte bleiben flach in ihrer Ebene,
    # darum laufen Export, G-Code und Ebenen unverändert über alle Objekte.
    groups: tuple[str, ...] = ()
    # Stützpunkte für polygon/path, normiert auf die (ungedrehte) Objektbox
    # (0..1). Dadurch wirken Verschieben, Skalieren und Drehen ohne Sonderfälle.
    points: tuple[tuple[float, float], ...] = ()
    # Nur für kind == "image": eingebettete Bitmap + Gravur-Einstellungen.
    image: RasterImage | None = None

    def bounds(self) -> Rect:
        return self.geom.bounds()

    def abs_points(self) -> list[tuple[float, float]]:
        """Stützpunkte in mm im ungedrehten Objektrahmen."""
        g = self.geom
        return [(g.x + u * g.w, g.y + v * g.h) for u, v in self.points]

    @staticmethod
    def from_points(kind: str, pts: list[tuple[float, float]], layer_id: str) -> "Shape":
        """Polygon/Freihand aus Punkten in Arbeitsflächen-mm anlegen."""
        if kind not in POINT_KINDS:
            raise ValueError(f"{kind} hat keine Stützpunkte")
        if len(pts) < POINT_KINDS[kind]:
            raise ValueError(f"{kind} braucht mindestens {POINT_KINDS[kind]} Punkte")
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x, y = min(xs), min(ys)
        w, h = max(xs) - x, max(ys) - y
        norm = tuple(((px - x) / w if w > 0 else 0.0, (py - y) / h if h > 0 else 0.0) for px, py in pts)
        return Shape(kind, Geometry(x, y, w, h), layer_id, points=norm)

    def copy(self, new_identity: bool = False) -> "Shape":
        return replace(self, geom=self.geom.copy(),
                       id=new_id() if new_identity else self.id)

    def to_dict(self) -> dict:
        d = {"id": self.id, "kind": self.kind, "layer": self.layer_id,
             "x": self.geom.x, "y": self.geom.y, "w": self.geom.w, "h": self.geom.h}
        if self.geom.rot:
            d["rot"] = self.geom.rot
        if self.groups:
            d["groups"] = list(self.groups)
        if self.kind == "text":
            d["text"] = self.text
            d["font"] = self.font_family
        if self.kind in POINT_KINDS:
            d["points"] = [[round(u, 6), round(v, 6)] for u, v in self.points]
        if self.kind == "image" and self.image is not None:
            d["image"] = self.image.to_dict()
        return d

    @staticmethod
    def from_dict(d: dict) -> "Shape":
        kind = str(d["kind"])
        if kind not in SHAPE_KINDS:
            raise ValueError(f"Unbekannter Objekttyp: {kind}")
        points = tuple((float(u), float(v)) for u, v in d.get("points", ())) if kind in POINT_KINDS else ()
        if kind in POINT_KINDS and len(points) < POINT_KINDS[kind]:
            raise ValueError(f"{kind} braucht mindestens {POINT_KINDS[kind]} Punkte")
        image = RasterImage.from_dict(d["image"]) if kind == "image" else None
        return Shape(kind=kind, layer_id=str(d["layer"]), points=points, image=image,
                     geom=Geometry(float(d["x"]), float(d["y"]), float(d["w"]), float(d["h"]),
                                   normalize_angle(float(d.get("rot", 0.0)))),
                     text=str(d.get("text", "")), font_family=str(d.get("font", "Segoe UI")),
                     id=str(d.get("id") or new_id()),
                     groups=tuple(str(g) for g in d.get("groups", ()) if g))


def simplify_polyline(pts: list[tuple[float, float]], tolerance_mm: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker: Punkte entfernen, die weniger als ``tolerance_mm``
    von der vereinfachten Linie abweichen. Erster und letzter Punkt bleiben;
    direkt doppelte Punkte fallen weg. Iterativ (keine Rekursionsgrenze)."""
    out: list[tuple[float, float]] = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-9:
            out.append((float(p[0]), float(p[1])))
    if len(out) < 3 or tolerance_mm <= 0:
        return out
    keep = [False] * len(out)
    keep[0] = keep[-1] = True
    stack = [(0, len(out) - 1)]
    while stack:
        i, j = stack.pop()
        (ax, ay), (bx, by) = out[i], out[j]
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for k in range(i + 1, j):
            px, py = out[k]
            d = (abs(dy * (px - ax) - dx * (py - ay)) / seg if seg > 1e-12
                 else math.hypot(px - ax, py - ay))
            if d > best:
                best, idx = d, k
        if idx >= 0 and best > tolerance_mm:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(out, keep) if k]


def constrain_geometry(g: Geometry) -> Geometry:
    """Hält eine Geometrie still und leise innerhalb der Arbeitsfläche.

    Zu große Objekte werden proportional verkleinert, überstehende
    verschoben. Es gibt bewusst keinen Hinweis in der UI, weil die
    Safezone für den Nutzer unsichtbar bleiben soll.
    """
    b = g.bounds()
    if is_inside_work_area(b):
        return g
    g = g.copy()
    s = fit_scale(b)
    if s < 1.0:
        nb = Rect(b.x, b.y, b.w * s, b.h * s)
        g = g.mapped(b, nb)
        b = nb
    dx, dy = clamp_offset(b)
    return g.translated(dx, dy)


def keep_inside_together(geoms: dict[str, Geometry]) -> dict[str, Geometry]:
    """Verschiebt mehrere Geometrien *gemeinsam* in die Arbeitsfläche, damit
    die Anordnung (z. B. einer Gruppe nach dem Drehen) erhalten bleibt."""
    r: Rect | None = None
    for g in geoms.values():
        b = g.bounds()
        r = b if r is None else r.united(b)
    if r is None:
        return geoms
    dx, dy = clamp_offset(r)
    if dx == 0 and dy == 0:
        return geoms
    return {k: g.translated(dx, dy) for k, g in geoms.items()}


Listener = Callable[[], None]


class Document:
    """Ebenen und Objekte eines Projekts.

    ``layers[0]`` ist die oberste Ebene (wird zuletzt gezeichnet), so wie sie
    auch im Ebenen-Panel oben steht. ``shapes`` ist nach Zeichenreihenfolge
    innerhalb der Ebenen sortiert (später = weiter oben).
    """

    FORMAT = "lumacut-canvas"
    # Version 2: Drehung ("rot") und Gruppen ("groups"). Ältere Dateien (v1) werden weiter gelesen;
    # ältere Programmversionen lehnen v2 ab, statt die Drehung still zu verlieren.
    VERSION = 4  # 3: optionale Material-Felder je Ebene; 4: Bildobjekte (v1-v3 laden weiter)
    # Dateien ohne Bilder werden weiter als v3 geschrieben, damit ältere
    # Versionen der App sie öffnen können.
    VERSION_WITHOUT_IMAGES = 3

    def __init__(self, with_default_layer: bool = True) -> None:
        self.layers: list[Layer] = []
        self.shapes: list[Shape] = []
        self.active_layer_id: str | None = None
        self._listeners: list[Listener] = []
        self._batch = 0
        self._dirty = False
        if with_default_layer:
            self.add_layer(Layer(name="Schneiden", color=LAYER_COLORS[0],
                                 power=80.0, speed=600.0, passes=1))

    # --- Benachrichtigung -------------------------------------------------
    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Listener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def changed(self) -> None:
        """Listener informieren (oder bis Ende eines Batches aufschieben)."""
        if self._batch:
            self._dirty = True
            return
        for fn in list(self._listeners):
            fn()

    def begin_batch(self) -> None:
        self._batch += 1

    def end_batch(self) -> None:
        self._batch -= 1
        if self._batch == 0 and self._dirty:
            self._dirty = False
            self.changed()

    # --- Ebenen -----------------------------------------------------------
    def layer(self, layer_id: str) -> Layer:
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        raise KeyError(layer_id)

    def layer_index(self, layer_id: str) -> int:
        return next(i for i, l in enumerate(self.layers) if l.id == layer_id)

    @property
    def active_layer(self) -> Layer | None:
        if self.active_layer_id is None:
            return None
        try:
            return self.layer(self.active_layer_id)
        except KeyError:
            return None

    def set_active_layer(self, layer_id: str | None) -> None:
        if layer_id is not None:
            self.layer(layer_id)  # KeyError, falls unbekannt
        if layer_id != self.active_layer_id:
            self.active_layer_id = layer_id
            self.changed()

    def next_layer_color(self) -> str:
        used = {l.color.lower() for l in self.layers}
        for c in LAYER_COLORS:
            if c not in used:
                return c
        return LAYER_COLORS[len(self.layers) % len(LAYER_COLORS)]

    def add_layer(self, layer: Layer, index: int = 0) -> Layer:
        layer = layer.normalized()
        self.layers.insert(index, layer)
        if self.active_layer_id is None:
            self.active_layer_id = layer.id
        self.changed()
        return layer

    def remove_layer(self, layer_id: str) -> tuple[int, Layer, list[tuple[int, Shape]]]:
        """Entfernt Ebene samt Objekten; liefert alles für ein Undo zurück."""
        idx = self.layer_index(layer_id)
        layer = self.layers.pop(idx)
        removed = [(i, s) for i, s in enumerate(self.shapes) if s.layer_id == layer_id]
        self.shapes = [s for s in self.shapes if s.layer_id != layer_id]
        if self.active_layer_id == layer_id:
            self.active_layer_id = self.layers[min(idx, len(self.layers) - 1)].id if self.layers else None
        self.changed()
        return idx, layer, removed

    def restore_layer(self, idx: int, layer: Layer, shapes: list[tuple[int, Shape]]) -> None:
        self.layers.insert(idx, layer)
        for i, s in sorted(shapes, key=lambda t: t[0]):
            self.shapes.insert(min(i, len(self.shapes)), s)
        self.changed()

    def move_layer(self, layer_id: str, new_index: int) -> None:
        idx = self.layer_index(layer_id)
        new_index = max(0, min(len(self.layers) - 1, new_index))
        if idx == new_index:
            return
        self.layers.insert(new_index, self.layers.pop(idx))
        self.changed()

    def update_layer(self, layer_id: str, **attrs) -> None:
        layer = self.layer(layer_id)
        for k, v in attrs.items():
            if not hasattr(layer, k) or k == "id":
                raise AttributeError(k)
            setattr(layer, k, v)
        normalized = layer.normalized()
        for k in ("power", "speed", "passes", "z_step") + MATERIAL_LAYER_FIELDS + CUT_LAYER_FIELDS \
                + FILL_LAYER_FIELDS:
            setattr(layer, k, getattr(normalized, k))
        self.changed()

    # --- Objekte ----------------------------------------------------------
    def shape(self, shape_id: str) -> Shape:
        for s in self.shapes:
            if s.id == shape_id:
                return s
        raise KeyError(shape_id)

    def has_shape(self, shape_id: str) -> bool:
        return any(s.id == shape_id for s in self.shapes)

    def shapes_in_layer(self, layer_id: str) -> list[Shape]:
        return [s for s in self.shapes if s.layer_id == layer_id]

    def add_shape(self, shape: Shape, index: int | None = None) -> Shape:
        self.layer(shape.layer_id)  # Ebene muss existieren
        shape.geom = constrain_geometry(shape.geom)
        if index is None:
            self.shapes.append(shape)
        else:
            self.shapes.insert(index, shape)
        self.changed()
        return shape

    def remove_shape(self, shape_id: str) -> tuple[int, Shape]:
        idx = next(i for i, s in enumerate(self.shapes) if s.id == shape_id)
        s = self.shapes.pop(idx)
        self.changed()
        return idx, s

    def set_geometry(self, shape_id: str, geom: Geometry) -> None:
        self.shape(shape_id).geom = constrain_geometry(geom)
        self.changed()

    def set_shape_layer(self, shape_id: str, layer_id: str) -> None:
        self.layer(layer_id)
        self.shape(shape_id).layer_id = layer_id
        self.changed()

    def set_text(self, shape_id: str, text: str) -> None:
        self.shape(shape_id).text = text
        self.changed()

    def set_image_settings(self, shape_id: str, settings: ImageSettings) -> None:
        s = self.shape(shape_id)
        if s.image is None:
            raise ValueError("Objekt ist kein Bild")
        s.image = replace(s.image, settings=settings.normalized())
        self.changed()

    def set_groups(self, shape_id: str, groups: tuple[str, ...]) -> None:
        self.shape(shape_id).groups = tuple(groups)
        self.changed()

    def group_members(self, group_id: str) -> list[str]:
        return [s.id for s in self.shapes if group_id in s.groups]

    def unit_of(self, shape_id: str) -> list[str]:
        """Alle Objekte, die zusammen mit ``shape_id`` ausgewählt werden
        (die äußerste Gruppe oder nur das Objekt selbst)."""
        s = self.shape(shape_id)
        if not s.groups:
            return [shape_id]
        top = s.groups[0]
        return [o.id for o in self.shapes if o.groups and o.groups[0] == top]

    def expand_to_groups(self, ids: Iterable[str]) -> list[str]:
        """Auswahl auf ganze (äußerste) Gruppen erweitern; nur bearbeitbare
        Objekte, Reihenfolge wie im Dokument."""
        wanted: set[str] = set()
        for sid in ids:
            if self.has_shape(sid):
                wanted.update(self.unit_of(sid))
        return [s.id for s in self.shapes if s.id in wanted and self.is_editable(s.id)]

    def is_editable(self, shape_id: str) -> bool:
        """Objekt ist sichtbar und nicht gesperrt (über seine Ebene)."""
        layer = self.layer(self.shape(shape_id).layer_id)
        return layer.visible and not layer.locked

    def selection_bounds(self, ids: Iterable[str]) -> Rect | None:
        r: Rect | None = None
        for sid in ids:
            b = self.shape(sid).bounds()
            r = b if r is None else r.united(b)
        return r

    # --- Serialisierung ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format": self.FORMAT,
            "version": (self.VERSION if any(s.kind == "image" for s in self.shapes)
                        else self.VERSION_WITHOUT_IMAGES),
            "units": "mm",
            "work_area": {"width": 360.0, "height": 340.0},
            "active_layer": self.active_layer_id,
            "layers": [l.to_dict() for l in self.layers],
            "objects": [s.to_dict() for s in self.shapes],
        }

    def load_dict(self, d: dict) -> None:
        """Ersetzt den Inhalt. Ungültige Objekte werden still korrigiert."""
        if d.get("format") != self.FORMAT:
            raise ValueError("Keine LumaCut-Canvas-Datei")
        if int(d.get("version", 0)) > self.VERSION:
            raise ValueError("Datei stammt aus einer neueren Version")
        layers = [Layer.from_dict(x) for x in d.get("layers", [])]
        if not layers:
            layers = [Layer(name="Schneiden")]
        ids = {l.id for l in layers}
        shapes = []
        for x in d.get("objects", []):
            s = Shape.from_dict(x)
            if s.layer_id not in ids:
                s.layer_id = layers[-1].id
            s.geom = constrain_geometry(s.geom)
            shapes.append(s)
        self.layers, self.shapes = layers, shapes
        active = d.get("active_layer")
        self.active_layer_id = active if active in ids else layers[0].id
        self.changed()

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        doc = cls(with_default_layer=False)
        doc.load_dict(d)
        return doc
