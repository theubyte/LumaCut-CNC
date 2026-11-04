"""Anzeige-Einheit mm/Zoll (docs/REVIEW_GAP_ANALYSIS_2026-10-25.md §9/§10).

Gespeichert, gerechnet und an die Maschine geschickt wird **immer in mm**.
Nur Lineale, Statusleiste und die X/Y/B/H-Felder rechnen beim Anzeigen um.
Die Lage des Nullpunkts kommt ausschließlich aus :mod:`.workarea`
(:func:`~.workarea.screen_to_user`); hier gibt es keinen zweiten Schalter.

Qt-frei, damit auch Statuszeilen ohne Editor es benutzen können.
"""

from __future__ import annotations

import math

from .workarea import screen_to_user

MM_PER_INCH = 25.4
MM = "mm"
INCH = "in"
UNITS = (MM, INCH)

#: Nachkommastellen der Anzeige je Einheit (0,01 mm ≈ 0,0004 in).
DECIMALS = {MM: 2, INCH: 3}
#: Pfeiltasten-Schritt je Einheit in mm (0,5 mm bzw. 1/16 in).
SINGLE_STEP_MM = {MM: 0.5, INCH: MM_PER_INCH / 16}
#: „Runde“ Linealabstände in der jeweiligen Einheit.
RULER_STEPS = {MM: (0.5, 1, 2, 5, 10, 20, 50, 100, 200),
               INCH: (0.0625, 0.125, 0.25, 0.5, 1, 2, 5, 10)}


def check(unit: str) -> str:
    if unit not in UNITS:
        raise ValueError(f"Unbekannte Einheit {unit!r} (erlaubt: {', '.join(UNITS)})")
    return unit


def factor(unit: str) -> float:
    """mm je Anzeige-Einheit."""
    return MM_PER_INCH if check(unit) == INCH else 1.0


def to_display(mm: float, unit: str) -> float:
    return mm / factor(unit)


def from_display(value: float, unit: str) -> float:
    return value * factor(unit)


def suffix(unit: str) -> str:
    return " in" if check(unit) == INCH else " mm"


def format_length(mm: float, unit: str, decimals: int | None = None, with_unit: bool = True) -> str:
    d = DECIMALS[check(unit)] if decimals is None else decimals
    text = f"{to_display(mm, unit):.{d}f}"
    return text + suffix(unit) if with_unit else text


def parse_length(text: str, unit: str) -> float:
    """Eingabe (Komma oder Punkt, optional mit „mm“/„in“/″) → mm.

    Eine ausdrücklich angehängte Einheit gewinnt, so kann man im Zoll-Modus
    auch „12 mm“ tippen und umgekehrt.
    """
    t = text.strip().replace(",", ".").replace("\u2033", "in").replace('"', "in")
    explicit = None
    for u in (MM, INCH):
        if t.lower().endswith(u):
            explicit = u
            t = t[: -len(u)].strip()
            break
    return from_display(float(t), explicit or unit)


def format_position(screen_x: float, screen_y: float, unit: str, width: int = 6) -> str:
    """Statuszeile „X … Y …“ in Anzeige-Koordinaten (Nullpunkt aus workarea)."""
    u, v = screen_to_user(screen_x, screen_y)
    d = 1 if check(unit) == MM else 3
    w = width if unit == MM else width + 1
    return f"X {to_display(u, unit):{w}.{d}f}  Y {to_display(v, unit):{w}.{d}f}{suffix(unit)}"


# --- Geschwindigkeit mm/min ↔ mm/s -------------------------------------------
# Gespeichert, gerechnet und als Marlin-Vorschub F geschickt wird **immer
# mm/min**. LightBurn zeigt wahlweise mm/s; hier wird nur beim Anzeigen und
# Eintippen umgerechnet (Ebenen-Panel, Bild-, Materialtest- und Scan-Versatz-Dialog).

MM_PER_MIN = "mm/min"
MM_PER_S = "mm/s"
SPEED_UNITS = (MM_PER_MIN, MM_PER_S)

#: Höchstens so viele Nachkommastellen in der Anzeige (Nullen am Ende entfallen).
SPEED_DECIMALS = {MM_PER_MIN: 1, MM_PER_S: 2}
#: Pfeiltasten-Schritt je Einheit in mm/min (50 mm/min bzw. 1 mm/s).
SPEED_SINGLE_STEP = {MM_PER_MIN: 50.0, MM_PER_S: 60.0}
#: Genauigkeit des umgerechneten Werts in mm/min (wie die Scan-Versatz-Tabelle).
SPEED_STORE_DECIMALS = 3


def check_speed(unit: str) -> str:
    if unit not in SPEED_UNITS:
        raise ValueError(f"Unbekannte Geschwindigkeitseinheit {unit!r} "
                         f"(erlaubt: {', '.join(SPEED_UNITS)})")
    return unit


def speed_factor(unit: str) -> float:
    """mm/min je Anzeige-Einheit (1 mm/s = 60 mm/min)."""
    return 60.0 if check_speed(unit) == MM_PER_S else 1.0


def speed_to_display(mm_min: float, unit: str) -> float:
    return float(mm_min) / speed_factor(unit)


def speed_from_display(value: float, unit: str) -> float:
    return round(float(value) * speed_factor(unit), SPEED_STORE_DECIMALS)


def speed_suffix(unit: str) -> str:
    return " " + check_speed(unit)


def format_speed(mm_min: float, unit: str, with_unit: bool = True,
                 decimals: int | None = None) -> str:
    """``1500`` → „1500 mm/min“ bzw. „25 mm/s“; ``1000`` → „16.67 mm/s“.

    Gerundet auf :data:`SPEED_DECIMALS`, Nullen am Ende entfallen (wie ``:g``)."""
    d = SPEED_DECIMALS[check_speed(unit)] if decimals is None else decimals
    text = f"{speed_to_display(mm_min, unit):.{d}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text + speed_suffix(unit) if with_unit else text


def parse_speed(text: str, unit: str) -> float:
    """Eingabe (Komma oder Punkt, optional mit „mm/min“ / „mm/s“) → mm/min.

    Eine ausdrücklich angehängte Einheit gewinnt (im mm/s-Modus „3000 mm/min“
    tippen geht also auch)."""
    t = str(text).strip().replace(",", ".").replace("\u2212", "-")
    explicit = None
    for u in (MM_PER_MIN, MM_PER_S):
        if t.lower().replace(" ", "").endswith(u):
            explicit = u
            t = t[: t.lower().rfind("mm")].strip()
            break
    value = float(t)
    if not math.isfinite(value):
        raise ValueError(f"Keine Geschwindigkeit: {text!r}")
    return speed_from_display(value, explicit or unit)
