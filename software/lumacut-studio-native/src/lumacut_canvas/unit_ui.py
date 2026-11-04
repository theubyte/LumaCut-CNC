"""Qt-Seite der Anzeige-Einheit mm/Zoll (siehe :mod:`.units`).

* :func:`display_units` – eine gemeinsame Einstellung mit Signal ``changed``;
  gespeichert in den App-QSettings (``canvas/display_unit``), sofern die App
  eine Organisation gesetzt hat (Tests speichern nichts).
* :class:`LengthSpin` – Zahlenfeld, dessen ``value()``/``setValue()`` immer
  mm sind; angezeigt und getippt wird in der gewählten Einheit.
* :func:`display_speed_units` / :class:`SpeedSpin` / :class:`SpeedUnitCombo` –
  dasselbe für Geschwindigkeiten (mm/min ↔ mm/s, ``canvas/speed_unit``);
  Werte bleiben mm/min.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox

from . import touch, units

SETTINGS_KEY = "canvas/display_unit"


class DisplayUnits(QObject):
    changed = Signal(str)  # neue Einheit ("mm" / "in")

    def __init__(self) -> None:
        super().__init__()
        self._unit = units.MM
        s = touch.default_settings()
        if s is not None and str(s.value(SETTINGS_KEY, units.MM)) in units.UNITS:
            self._unit = str(s.value(SETTINGS_KEY, units.MM))

    @property
    def unit(self) -> str:
        return self._unit

    def set_unit(self, unit: str) -> None:
        unit = units.check(unit)
        if unit == self._unit:
            return
        self._unit = unit
        s = touch.default_settings()
        if s is not None:
            s.setValue(SETTINGS_KEY, unit)
        self.changed.emit(unit)

    def toggle(self) -> None:
        self.set_unit(units.INCH if self._unit == units.MM else units.MM)


_instance: DisplayUnits | None = None


def display_units() -> DisplayUnits:
    global _instance
    if _instance is None:
        _instance = DisplayUnits()
    return _instance


class LengthSpin(QDoubleSpinBox):
    """Längenfeld: intern mm (4 Nachkommastellen), Anzeige in mm oder Zoll."""

    def __init__(self, minimum: float, maximum: float) -> None:
        self._unit = display_units().unit  # vor super(): Qt ruft textFromValue früh
        super().__init__()
        self.setDecimals(4)  # interne mm-Genauigkeit, nicht die Anzeige
        self.setRange(minimum, maximum)
        self.setKeyboardTracking(False)  # erst bei Enter/Fokuswechsel übernehmen
        self.setAlignment(Qt.AlignRight)
        self.setFixedWidth(104)
        self._apply_unit()
        display_units().changed.connect(self.set_unit)

    @property
    def unit(self) -> str:
        return self._unit

    def set_unit(self, unit: str) -> None:
        self._unit = units.check(unit)
        self._apply_unit()

    def _apply_unit(self) -> None:
        self.setSingleStep(units.SINGLE_STEP_MM[self._unit])
        self.setSuffix(units.suffix(self._unit))  # aktualisiert auch den Text

    # --- Anzeige <-> mm -------------------------------------------------
    def textFromValue(self, value: float) -> str:  # noqa: N802
        return units.format_length(value, self._unit, with_unit=False)

    def valueFromText(self, text: str) -> float:  # noqa: N802
        text = text.removesuffix(self.suffix()).strip()
        # Unveränderter Anzeigetext = unveränderter Wert (sonst würde schon der
        # Fokuswechsel auf die gerundete Anzeige „springen“ und Objekte bewegen).
        if text == self.textFromValue(self.value()):
            return self.value()
        try:
            return units.parse_length(text, self._unit)
        except ValueError:
            return self.value()

    def validate(self, text: str, pos: int):  # noqa: D401
        body = text.removesuffix(self.suffix()).strip()
        if body in ("", "-", "+", ".", ",", "-.", "-,"):
            return QValidator.Intermediate, text, pos
        try:
            mm = units.parse_length(body, self._unit)
        except ValueError:
            # z. B. „12 m“ auf dem Weg zu „12 mm“; ungültiges räumt fixup auf.
            return QValidator.Intermediate, text, pos
        if self.minimum() - 1e-9 <= mm <= self.maximum() + 1e-9:
            return QValidator.Acceptable, text, pos
        return QValidator.Intermediate, text, pos

    def fixup(self, text: str) -> str:
        return self.textFromValue(self.value()) + self.suffix()


# --- Geschwindigkeit mm/min ↔ mm/s ---------------------------------------------

SPEED_SETTINGS_KEY = "canvas/speed_unit"


class DisplaySpeedUnits(QObject):
    """Eine gemeinsame Anzeige-Einheit für Geschwindigkeiten (mm/min oder mm/s).

    Gespeichert in den App-QSettings (``canvas/speed_unit``); Werte bleiben
    überall mm/min (Dokument, Tabellen, G-Code)."""

    changed = Signal(str)  # neue Einheit ("mm/min" / "mm/s")

    def __init__(self) -> None:
        super().__init__()
        self._unit = units.MM_PER_MIN
        s = touch.default_settings()
        if s is not None and str(s.value(SPEED_SETTINGS_KEY, units.MM_PER_MIN)) in units.SPEED_UNITS:
            self._unit = str(s.value(SPEED_SETTINGS_KEY, units.MM_PER_MIN))

    @property
    def unit(self) -> str:
        return self._unit

    def set_unit(self, unit: str) -> None:
        unit = units.check_speed(unit)
        if unit == self._unit:
            return
        self._unit = unit
        s = touch.default_settings()
        if s is not None:
            s.setValue(SPEED_SETTINGS_KEY, unit)
        self.changed.emit(unit)

    def toggle(self) -> None:
        self.set_unit(units.MM_PER_S if self._unit == units.MM_PER_MIN else units.MM_PER_MIN)


_speed_instance: DisplaySpeedUnits | None = None


def display_speed_units() -> DisplaySpeedUnits:
    global _speed_instance
    if _speed_instance is None:
        _speed_instance = DisplaySpeedUnits()
    return _speed_instance


class SpeedSpin(QDoubleSpinBox):
    """Geschwindigkeitsfeld: ``value()``/``setValue()`` immer mm/min, angezeigt
    und getippt wird in mm/min oder mm/s (:func:`display_speed_units`)."""

    def __init__(self, minimum: float, maximum: float, value: float | None = None) -> None:
        self._unit = display_speed_units().unit  # vor super(): Qt ruft textFromValue früh
        super().__init__()
        self.setDecimals(units.SPEED_STORE_DECIMALS)  # interne mm/min-Genauigkeit
        self.setRange(minimum, maximum)
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignRight)
        if value is not None:
            self.setValue(value)
        self._apply_unit()
        display_speed_units().changed.connect(self.set_unit)

    @property
    def unit(self) -> str:
        return self._unit

    def set_unit(self, unit: str) -> None:
        self._unit = units.check_speed(unit)
        self._apply_unit()

    def _apply_unit(self) -> None:
        self.setSingleStep(units.SPEED_SINGLE_STEP[self._unit])
        self.setSuffix(units.speed_suffix(self._unit))  # aktualisiert auch den Text

    def textFromValue(self, value: float) -> str:  # noqa: N802
        return units.format_speed(value, self._unit, with_unit=False)

    def valueFromText(self, text: str) -> float:  # noqa: N802
        text = text.removesuffix(self.suffix()).strip()
        # Unveränderter Anzeigetext = unveränderter Wert: 1000 mm/min erscheint als
        # „16.67 mm/s“ und darf beim Fokuswechsel nicht zu 1000,2 mm/min werden.
        if text == self.textFromValue(self.value()):
            return self.value()
        try:
            return units.parse_speed(text, self._unit)
        except ValueError:
            return self.value()

    def validate(self, text: str, pos: int):  # noqa: D401
        body = text.removesuffix(self.suffix()).strip()
        if body in ("", "-", "+", ".", ",", "-.", "-,"):
            return QValidator.Intermediate, text, pos
        try:
            v = units.parse_speed(body, self._unit)
        except ValueError:
            return QValidator.Intermediate, text, pos  # z. B. „3000 mm/m“ unterwegs
        if self.minimum() - 1e-9 <= v <= self.maximum() + 1e-9:
            return QValidator.Acceptable, text, pos
        return QValidator.Intermediate, text, pos

    def fixup(self, text: str) -> str:
        return self.textFromValue(self.value()) + self.suffix()


class SpeedUnitCombo(QComboBox):
    """Auswahl mm/min ↔ mm/s, immer im Gleichlauf mit :func:`display_speed_units`."""

    def __init__(self) -> None:
        super().__init__()
        for u in units.SPEED_UNITS:
            self.addItem(u, u)
        self.setToolTip("Einheit der Geschwindigkeit (gilt überall in der App); "
                        "gespeichert wird immer mm/min")
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._show(display_speed_units().unit)
        self.activated.connect(lambda i: display_speed_units().set_unit(self.itemData(i)))
        display_speed_units().changed.connect(self._show)

    def _show(self, unit: str) -> None:
        self.blockSignals(True)
        self.setCurrentIndex(units.SPEED_UNITS.index(unit))
        self.blockSignals(False)
