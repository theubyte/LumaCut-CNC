"""Dialog „Import-Einstellungen“ (Datei-Menü) – Konturen gleich beim Import aufräumen.

Wie LightBurns *Auto-close tolerance* (Einstellungen › DXF-Import) und dessen
Import von SVG-Pfaden mit Löchern als *eine* Form. Alle Schalter sind
standardmäßig aus; die Wahl wird in QSettings (``import/…``) gespeichert und
gilt für jeden Vektor-Import (Strg+I und Drag & Drop: SVG, DXF, PDF, AI, EPS,
xTool). Rechnen in :mod:`.cleanup`.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLabel)

from .cleanup import JOIN_TOLERANCE_MM, JOIN_TOLERANCE_RANGE, ImportOptions


class ImportSettingsDialog(QDialog):
    def __init__(self, options: ImportOptions | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import-Einstellungen")
        self.setObjectName("ImportSettingsDialog")
        o = (options or ImportOptions()).normalized()
        form = QFormLayout(self)
        intro = QLabel("Gilt für jeden Vektor-Import (SVG, DXF, PDF, AI, EPS, xTool). "
                       "Ohne Häkchen bleibt jede Kontur ein eigenes Objekt wie in der Datei.")
        intro.setWordWrap(True)
        form.addRow(intro)
        self.delete_duplicates = QCheckBox("Doppelte Konturen löschen")
        self.delete_duplicates.setObjectName("import_delete_duplicates")
        self.delete_duplicates.setToolTip(
            "Übereinanderliegende gleiche Konturen der Datei (häufig in DXF-Exporten) nur einmal "
            "übernehmen – sonst wird die Kante doppelt gelasert und verkohlt. "
            "Wie Pfad › „Duplikate löschen“ (Alt+Umschalt+D)")
        self.delete_duplicates.setChecked(o.delete_duplicates)
        self.auto_join = QCheckBox("Offene Pfade verbinden")
        self.auto_join.setObjectName("import_auto_join")
        self.auto_join.setToolTip(
            "Lose Strecken, deren Enden höchstens die Toleranz auseinanderliegen, zu Pfaden "
            "verbinden; geschlossene werden Formen (füllbar, mit Kerf / Stegen / An-Abfahrt). "
            "Wie LightBurns „Auto-close tolerance“ und Pfad › „Pfade verbinden“ (Alt+J)")
        self.auto_join.setChecked(o.auto_join)
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setObjectName("import_join_tolerance")
        self.tolerance.setRange(*JOIN_TOLERANCE_RANGE)
        self.tolerance.setDecimals(3)
        self.tolerance.setSingleStep(0.01)
        self.tolerance.setSuffix(" mm")
        self.tolerance.setValue(o.join_tolerance_mm)
        self.tolerance.setToolTip(f"Größter Abstand zweier Enden, die verbunden werden "
                                  f"(Standard {JOIN_TOLERANCE_MM:g} mm wie LightBurn)")
        self.combine_holes = QCheckBox("Löcher mit Außenkontur kombinieren")
        self.combine_holes.setObjectName("import_combine_holes")
        self.combine_holes.setToolTip(
            "Konturen, die in einer anderen liegen (das Innere eines „O“, Ausschnitte eines Logos), "
            "mit ihrer Außenkontur zu einem Objekt mit Loch zusammenfassen – „Jedes Objekt "
            "einzeln“ füllt das Loch dann nicht mit. Wie Pfad › „Kombinieren“ (Strg+Alt+C)")
        self.combine_holes.setChecked(o.combine_holes)
        form.addRow(self.delete_duplicates)
        form.addRow(self.auto_join)
        form.addRow("Toleranz", self.tolerance)
        form.addRow(self.combine_holes)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                                        | QDialogButtonBox.RestoreDefaults)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.RestoreDefaults).setText("Alles aus")
        self.buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        form.addRow(self.buttons)
        self.auto_join.toggled.connect(self._update)
        self._update()

    def _update(self) -> None:
        self.tolerance.setEnabled(self.auto_join.isChecked())

    def restore_defaults(self) -> None:
        d = ImportOptions()
        self.delete_duplicates.setChecked(d.delete_duplicates)
        self.auto_join.setChecked(d.auto_join)
        self.tolerance.setValue(d.join_tolerance_mm)
        self.combine_holes.setChecked(d.combine_holes)

    def options(self) -> ImportOptions:
        return ImportOptions(self.delete_duplicates.isChecked(), self.auto_join.isChecked(),
                             self.tolerance.value(), self.combine_holes.isChecked()).normalized()
