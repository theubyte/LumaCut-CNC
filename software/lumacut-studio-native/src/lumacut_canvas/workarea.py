"""Arbeitsfläche und (unsichtbare) Safezone.

Koordinaten-Konvention (docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md §2.1)
==========================================================================

Die Maschine homt an die MIN-Endschalter **oben rechts**: X0 Y0 liegt dort,
**+X fährt nach links**, **+Y nach unten/vorne zur Tür**. Pi, Status, Joggen,
Park, Abtasten, Höhenmesh und Kameramosaik sind rohe Maschinen-mm.

Darum gibt es drei Koordinatenarten, umgerechnet *nur* in diesem Modul:

* **Bildschirm** (intern, Dokument, Szene, Overlays, SVG/PNG-Export):
  Ursprung oben links, x nach rechts, y nach unten, 0..360 × 0..340 mm.
  So bleibt die Qt-Szene ungespiegelt (kein ``scale(-1, 1)`` – das würde Text
  und Bilder spiegeln) und alte Dateien liegen an derselben Stelle.
* **Anzeige** (Lineale, Statusleiste, X/Y-Felder): Nullpunkt **oben rechts**,
  X wächst nach links, Y nach unten – wie an der Maschine
  (:func:`screen_to_user` / :func:`user_to_screen`).
* **Maschine** (G-Code, Jobplanung): ``Maschine = Anzeige + 30 mm`` Safezone,
  also ``machine_x = 390 − screen_x``, ``machine_y = 30 + screen_y``
  (:func:`screen_to_machine` / :func:`machine_to_screen`).

Der einzige Schalter ist :data:`ORIGIN_TOP_RIGHT`. Bis 2026-10-26 lief X
ungespiegelt (``machine_x = 30 + screen_x``) – Aufträge kamen seitenverkehrt.
Der Schalter steht vorerst noch auf ``False`` (alte Richtung), bis Scan & Probe
seine Umrechnung nachgezogen hat (docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md
§2.3); aller Canvas-/Job-Code geht aber schon über diese Helfer.

Die Maschine hat eine L-förmige 30-mm-Safezone (X < 30 oder Y < 30), in der
nicht geschnitten werden darf (siehe docs/MASCHINE.md). Diese Zone wird in der
UI bewusst nicht gezeigt: Die sichtbare Arbeitsfläche *ist* bereits der
erlaubte Schneidbereich X 30–390 / Y 30–370. Die Umrechnung in
Maschinenkoordinaten passiert nur an dieser einen Stelle.
Bilder in Maschinenrichtung (Kameramosaik, Höhenkarte: Spalte 0 = kleinstes
Maschinen-X) müssen für die Bildschirm-Darstellung waagerecht gespiegelt
werden (:data:`IMAGE_FLIP_X`).

Dieses Modul ist Qt-frei, damit es auch von Job-/Export-Code ohne GUI
benutzt werden kann.
"""

from __future__ import annotations

from dataclasses import dataclass

# Sichtbare Arbeitsfläche in mm.
WORK_WIDTH_MM: float = 360.0
WORK_HEIGHT_MM: float = 340.0

# Interne Safezone: Versatz der Arbeitsfläche im Maschinenkoordinatensystem.
_SAFEZONE_X_MM: float = 30.0
_SAFEZONE_Y_MM: float = 30.0

#: Einziger Schalter der Konvention: True = Nullpunkt oben rechts (Maschine,
#: §2.1), X wächst nach links. False = alte Konvention (X nach rechts).
ORIGIN_TOP_RIGHT: bool = False
#: Bilder mit Spalte 0 = kleinstes Maschinen-X waagerecht spiegeln?
IMAGE_FLIP_X: bool = ORIGIN_TOP_RIGHT

#: Erlaubter Schneidbereich in Maschinen-mm (unabhängig von der Richtung).
MACHINE_X_MIN: float = _SAFEZONE_X_MM
MACHINE_Y_MIN: float = _SAFEZONE_Y_MM
MACHINE_X_MAX: float = _SAFEZONE_X_MM + WORK_WIDTH_MM
MACHINE_Y_MAX: float = _SAFEZONE_Y_MM + WORK_HEIGHT_MM


@dataclass(frozen=True)
class Rect:
    """Achsparalleles Rechteck in mm (w, h immer >= 0)."""

    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @staticmethod
    def from_points(x1: float, y1: float, x2: float, y2: float) -> "Rect":
        return Rect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def united(self, other: "Rect") -> "Rect":
        return Rect.from_points(
            min(self.x, other.x), min(self.y, other.y),
            max(self.right, other.right), max(self.bottom, other.bottom),
        )


WORK_RECT = Rect(0.0, 0.0, WORK_WIDTH_MM, WORK_HEIGHT_MM)


def is_inside_work_area(r: Rect, eps: float = 1e-6) -> bool:
    """True, wenn ``r`` komplett innerhalb der Arbeitsfläche liegt."""
    return (r.x >= -eps and r.y >= -eps
            and r.right <= WORK_WIDTH_MM + eps and r.bottom <= WORK_HEIGHT_MM + eps)


def clamp_offset(r: Rect) -> tuple[float, float]:
    """Verschiebung (dx, dy), die ``r`` in die Arbeitsfläche schiebt.

    Ist ``r`` größer als die Fläche, wird an der linken/oberen Kante
    ausgerichtet; das Verkleinern übernimmt :func:`fit_scale`.
    """
    dx = 0.0
    dy = 0.0
    if r.right > WORK_WIDTH_MM:
        dx = WORK_WIDTH_MM - r.right
    if r.x + dx < 0.0:
        dx = -r.x
    if r.bottom > WORK_HEIGHT_MM:
        dy = WORK_HEIGHT_MM - r.bottom
    if r.y + dy < 0.0:
        dy = -r.y
    return dx, dy


def fit_scale(r: Rect) -> float:
    """Gleichmäßiger Faktor (<= 1), damit ``r`` in die Arbeitsfläche passt."""
    sx = WORK_WIDTH_MM / r.w if r.w > WORK_WIDTH_MM else 1.0
    sy = WORK_HEIGHT_MM / r.h if r.h > WORK_HEIGHT_MM else 1.0
    return min(sx, sy)


def screen_to_user(x: float, y: float) -> tuple[float, float]:
    """Bildschirm-mm → Anzeige-mm (Nullpunkt oben rechts, X nach links)."""
    return (WORK_WIDTH_MM - x if ORIGIN_TOP_RIGHT else x), y


def user_to_screen(u: float, v: float) -> tuple[float, float]:
    """Anzeige-mm → Bildschirm-mm (Umkehrung; die Spiegelung ist selbstinvers)."""
    return screen_to_user(u, v)


def axis_tooltips() -> tuple[str, str]:
    """Tooltips der X/Y-Felder passend zum Nullpunkt (kein zweiter Schalter in der UI)."""
    if ORIGIN_TOP_RIGHT:
        return ("Abstand der rechten Kante vom Nullpunkt oben rechts",
                "Abstand der oberen Kante vom Nullpunkt oben rechts")
    return "Linke Kante", "Obere Kante"


def user_x_of(r: Rect) -> float:
    """Angezeigtes X eines Rechtecks: Abstand der Kante am Nullpunkt
    (oben rechts → rechte Kante)."""
    return WORK_WIDTH_MM - r.right if ORIGIN_TOP_RIGHT else r.x


def screen_left_for_user_x(u: float, w: float) -> float:
    """Bildschirm-links eines Rechtecks der Breite ``w`` mit angezeigtem X ``u``."""
    return WORK_WIDTH_MM - u - w if ORIGIN_TOP_RIGHT else u


def screen_to_machine(x: float, y: float) -> tuple[float, float]:
    """Bildschirm-mm → Maschinen-mm: ``(390 − x, 30 + y)`` bei Nullpunkt oben rechts."""
    u, v = screen_to_user(x, y)
    return u + _SAFEZONE_X_MM, v + _SAFEZONE_Y_MM


def machine_to_screen(x: float, y: float) -> tuple[float, float]:
    """Maschinen-mm → Bildschirm-mm (Umkehrung von :func:`screen_to_machine`)."""
    return user_to_screen(x - _SAFEZONE_X_MM, y - _SAFEZONE_Y_MM)


def machine_rect_to_screen(x0: float, y0: float, x1: float, y1: float) -> Rect:
    """Maschinen-Rechteck (zwei Ecken) → Bildschirm-:class:`Rect`."""
    ax, ay = machine_to_screen(x0, y0)
    bx, by = machine_to_screen(x1, y1)
    return Rect.from_points(ax, ay, bx, by)


#: Ältere Namen (Job-, Materials-, Scan-Code): Bildschirm ↔ Maschine.
to_machine = screen_to_machine
from_machine = machine_to_screen
