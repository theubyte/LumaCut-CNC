"""Touch-Modus: Bildschirmmaße für Finger statt Maus (Surface Pro & Co.).

Alle Größen sind Bildschirmpixel und damit unabhängig vom Zoom. Die View
rechnet sie über ``px_per_mm`` in Szenen-mm um.

* ``MOUSE`` entspricht den bisherigen, kompakten Werten.
* ``TOUCH`` vergrößert Anfasser, Fangbereiche und Bedienelemente auf
  Fingergröße (Microsoft empfiehlt ≥ 7–9 mm ≈ 32–44 px Trefferfläche).

Der Modus wird beim Start automatisch erkannt (Touchscreen vorhanden), schaltet
sich bei der ersten echten Touch-Eingabe ein und kann über „Touch-Modus“ fest
ein- oder ausgeschaltet werden; diese Wahl wird in QSettings gespeichert.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, QSettings, Qt
from PySide6.QtGui import QInputDevice

SETTINGS_KEY = "canvas/touch_mode"


@dataclass(frozen=True)
class TouchMetrics:
    handle_px: float         # gezeichnete Kantenlänge der Skalier-Griffe
    handle_hit_px: float     # halbe Kantenlänge des Fangquadrats (≥ handle_px / 2)
    rotate_offset_px: float  # Abstand des Dreh-Griffs über der oberen Kante
    hit_tolerance_px: float  # Fangabstand für dünne Objekte (Linien, Umrisse)
    icon_px: int             # Icongröße der Werkzeugleisten
    zoom_button_px: int      # Kantenlänge der Zoom-Knöpfe im Canvas


MOUSE = TouchMetrics(handle_px=9.0, handle_hit_px=9.0, rotate_offset_px=24.0,
                     hit_tolerance_px=5.0, icon_px=22, zoom_button_px=44)
# 16 px sichtbar, 2 × 16 = 32 px Trefferfläche, Dreh-Griff deutlich abgesetzt.
TOUCH = TouchMetrics(handle_px=16.0, handle_hit_px=16.0, rotate_offset_px=44.0,
                     hit_tolerance_px=12.0, icon_px=32, zoom_button_px=52)


def metrics(touch: bool) -> TouchMetrics:
    return TOUCH if touch else MOUSE


def has_touchscreen() -> bool:
    """True, wenn das System einen Touchscreen meldet."""
    try:
        return any(d.type() == QInputDevice.DeviceType.TouchScreen for d in QInputDevice.devices())
    except Exception:  # pragma: no cover - sehr alte Plattform-Plugins
        return False


def is_touchscreen_event(event) -> bool:
    """Echte Touchscreen-Eingabe (keine Touchpad- oder aus Mausereignissen
    synthetisierten Touch-Events, vgl. ``AA_SynthesizeTouchForUnhandledMouseEvents``)."""
    dev = event.device() if hasattr(event, "device") else None
    return dev is not None and dev.type() == QInputDevice.DeviceType.TouchScreen


def is_mouse_from_touch(event) -> bool:
    """Mausereignis, das Qt oder das System aus einer Touch-Eingabe erzeugt hat."""
    try:
        if event.source() != Qt.MouseEventSource.MouseEventNotSynthesized:
            return True
    except (AttributeError, RuntimeError):
        pass
    return is_touchscreen_event(event)


def default_settings() -> QSettings | None:
    """Anwendungs-QSettings, aber nur wenn die App eine Organisation gesetzt hat
    (in Tests ohne Organisation wird nichts gespeichert)."""
    if QCoreApplication.instance() is None or not QCoreApplication.organizationName():
        return None
    return QSettings()


def load_setting(settings: QSettings | None) -> bool | None:
    """Gespeicherte Wahl (True/False) oder None = automatisch."""
    if settings is None or not settings.contains(SETTINGS_KEY):
        return None
    v = settings.value(SETTINGS_KEY)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def save_setting(settings: QSettings | None, on: bool) -> None:
    if settings is not None:
        settings.setValue(SETTINGS_KEY, bool(on))
        settings.sync()
