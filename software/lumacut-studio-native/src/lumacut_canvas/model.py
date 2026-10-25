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

import uuid
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable

from .workarea import Rect, clamp_offset, fit_scale, is_inside_work_area

# Gültige Parameterbereiche, abgestimmt mit software/lumacut-studio (studio.js).
POWER_RANGE = (1.0, 100.0)          # Prozent
SPEED_RANGE = (1.0, 6000.0)         # mm/min (Marlin-Vorschub F)
PASSES_RANGE = (1, 30)

SHAPE_KINDS = ("rect", "ellipse", "line", "text")

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

    def normalized(self) -> "Layer":
        """Kopie mit Parametern im gültigen Bereich."""
        return replace(
            self,
            power=_clamp(float(self.power), *POWER_RANGE),
            speed=_clamp(float(self.speed), *SPEED_RANGE),
            passes=int(_clamp(int(self.passes), *PASSES_RANGE)),
        )

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color,
                "power": self.power, "speed": self.speed, "passes": self.passes,
                "visible": self.visible, "locked": self.locked}

    @staticmethod
    def from_dict(d: dict) -> "Layer":
        return Layer(
            id=str(d.get("id") or new_id()), name=str(d.get("name", "Ebene")),
            color=str(d.get("color", LAYER_COLORS[0])),
            power=float(d.get("power", 50.0)), speed=float(d.get("speed", 1500.0)),
            passes=int(d.get("passes", 1)), visible=bool(d.get("visible", True)),
            locked=bool(d.get("locked", False)),
        ).normalized()


@dataclass
class Geometry:
    """Geometrie als zwei Punkte p1=(x, y) und p2=(x+w, y+h).

    Für Rechteck, Ellipse und Text ist das die Box (w, h > 0).
    Für Linien sind w/h vorzeichenbehaftet (Linie von p1 nach p2).
    Diese einheitliche Darstellung erlaubt es, Verschieben und Skalieren
    für alle Formen gleich zu behandeln.
    """

    x: float
    y: float
    w: float
    h: float

    def bounds(self) -> Rect:
        return Rect.from_points(self.x, self.y, self.x + self.w, self.y + self.h)

    def translated(self, dx: float, dy: float) -> "Geometry":
        return Geometry(self.x + dx, self.y + dy, self.w, self.h)

    def mapped(self, old: Rect, new: Rect) -> "Geometry":
        """Bildet die Geometrie affin von Box ``old`` auf Box ``new`` ab."""
        sx = new.w / old.w if old.w > 0 else 1.0
        sy = new.h / old.h if old.h > 0 else 1.0
        x1 = new.x + (self.x - old.x) * sx
        y1 = new.y + (self.y - old.y) * sy
        x2 = new.x + (self.x + self.w - old.x) * sx
        y2 = new.y + (self.y + self.h - old.y) * sy
        return Geometry(x1, y1, x2 - x1, y2 - y1)

    def as_tuple(self) -> tuple[float, float, float, float]:
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

    def bounds(self) -> Rect:
        return self.geom.bounds()

    def copy(self, new_identity: bool = False) -> "Shape":
        return replace(self, geom=replace(self.geom),
                       id=new_id() if new_identity else self.id)

    def to_dict(self) -> dict:
        d = {"id": self.id, "kind": self.kind, "layer": self.layer_id,
             "x": self.geom.x, "y": self.geom.y, "w": self.geom.w, "h": self.geom.h}
        if self.kind == "text":
            d["text"] = self.text
            d["font"] = self.font_family
        return d

    @staticmethod
    def from_dict(d: dict) -> "Shape":
        kind = str(d["kind"])
        if kind not in SHAPE_KINDS:
            raise ValueError(f"Unbekannter Objekttyp: {kind}")
        return Shape(kind=kind, layer_id=str(d["layer"]),
                     geom=Geometry(float(d["x"]), float(d["y"]), float(d["w"]), float(d["h"])),
                     text=str(d.get("text", "")), font_family=str(d.get("font", "Segoe UI")),
                     id=str(d.get("id") or new_id()))


def constrain_geometry(g: Geometry) -> Geometry:
    """Hält eine Geometrie still und leise innerhalb der Arbeitsfläche.

    Zu große Objekte werden proportional verkleinert, überstehende
    verschoben. Es gibt bewusst keinen Hinweis in der UI, weil die
    Safezone für den Nutzer unsichtbar bleiben soll.
    """
    b = g.bounds()
    if is_inside_work_area(b):
        return g
    s = fit_scale(b)
    if s < 1.0:
        nb = Rect(b.x, b.y, b.w * s, b.h * s)
        g = g.mapped(b, nb)
        b = nb
    dx, dy = clamp_offset(b)
    return g.translated(dx, dy)


Listener = Callable[[], None]


class Document:
    """Ebenen und Objekte eines Projekts.

    ``layers[0]`` ist die oberste Ebene (wird zuletzt gezeichnet), so wie sie
    auch im Ebenen-Panel oben steht. ``shapes`` ist nach Zeichenreihenfolge
    innerhalb der Ebenen sortiert (später = weiter oben).
    """

    FORMAT = "lumacut-canvas"
    VERSION = 1

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
        layer.power, layer.speed, layer.passes = normalized.power, normalized.speed, normalized.passes
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
            "format": self.FORMAT, "version": self.VERSION, "units": "mm",
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
